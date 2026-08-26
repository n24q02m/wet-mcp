// src/worker.ts
// Worker fronting the wet-mcp container Durable Object.
//
// Two distinct request paths:
//  - INBOUND: requests on the custom domain hit the default export `fetch`,
//    which routes them to the per-user WetContainer Durable Object.
//  - OUTBOUND: the container calls http://{kv,d1,vectorize}.internal/... which
//    is intercepted by the `@cloudflare/containers` proxy and dispatched to the
//    `WetContainer.outboundByHost` handlers below, serviced from the Worker's
//    KV / D1 / Vectorize bindings. enableInternet=true lets every OTHER host
//    (Jina, Vertex, SearXNG) reach the public internet.
import { Container, ContainerProxy, type OutboundHandler } from '@cloudflare/containers'

// ContainerProxy must be exported from the Worker entrypoint: the containers
// runtime discovers it via `ctx.exports.ContainerProxy` to route the container's
// intercepted outbound traffic (kv/d1/vectorize.internal) back into the Worker.
// Without this re-export, applyOutboundInterception() throws at container start.
export { ContainerProxy }

export interface Env {
  KV: {
    get(k: string, type: 'arrayBuffer'): Promise<ArrayBuffer | null>
    get(k: string): Promise<string | null>
    put(k: string, v: string | ArrayBuffer): Promise<void>
    delete(k: string): Promise<void>
  }
  D1: { prepare(sql: string): { bind(...p: unknown[]): { all(): Promise<{ results: unknown[] }> } }; batch(statements: unknown[]): Promise<{ results: unknown[] }[]> }
  VECTORIZE: {
    upsert(v: unknown[]): Promise<{ mutationId: string }>
    query(vector: number[], opts: { topK: number; filter?: unknown }): Promise<{ matches: unknown[] }>
    deleteByIds(ids: string[]): Promise<{ mutationId: string }>
  }
  WET?: { idFromName(n: string): unknown; get(id: unknown): { fetch(r: Request): Promise<Response> } }
  // Container config (wrangler.jsonc `vars`) + secrets (`wrangler secret put`),
  // forwarded into the container process via WetContainer.envVars.
  MCP_STORAGE_BACKEND: string
  MCP_KV_BASE_URL: string
  DOCS_DB_BACKEND: string
  MCP_D1_BASE_URL: string
  MCP_VECTORIZE_BASE_URL: string
  MCP_VECTORIZE_IDX: string
  EMBEDDING_MODELS: string
  RERANK_MODELS: string
  LLM_MODELS: string
  SEARCH_BACKEND: string
  WET_AUTO_SEARXNG: string
  PUBLIC_URL: string
  CREDENTIAL_SECRET: string
  JINA_AI_API_KEY: string
  GOOGLE_VERTEX_EXPRESS_API_KEY: string
  XAI_API_KEY: string
  MCP_RELAY_PASSWORD: string
  MCP_DCR_SERVER_SECRET: string
  // search secrets — exactly one set depending on SEARCH_BACKEND
  SEARXNG_URL?: string
  TAVILY_API_KEY?: string
  // Capability provider chains (search/browser) + per-task disable-local toggles.
  SEARCH_BACKENDS?: string
  BRAVE_API_KEY?: string
  EXA_API_KEY?: string
  BROWSER_BACKENDS?: string
  CF_ACCOUNT_ID?: string
  CF_BROWSER_RENDERING_TOKEN?: string
  BROWSERLESS_URL?: string
  BROWSERLESS_TOKEN?: string
  CAPSOLVER_API_KEY?: string
  DISABLE_LOCAL_EMBED?: string
  DISABLE_LOCAL_RERANK?: string
  DISABLE_LOCAL_SEARCH?: string
  DISABLE_LOCAL_BROWSER?: string
  RESPECT_ROBOTS_TXT?: string
}

// Keys forwarded from the Worker env (wrangler vars + secrets) into the container
// process. Unset/empty values are dropped so an unused optional secret (tavily vs
// searxng) never injects a blank.
const CONTAINER_ENV_KEYS = [
  'MCP_STORAGE_BACKEND', 'MCP_KV_BASE_URL', 'DOCS_DB_BACKEND',
  'MCP_D1_BASE_URL', 'MCP_VECTORIZE_BASE_URL', 'MCP_VECTORIZE_IDX',
  'EMBEDDING_MODELS', 'RERANK_MODELS', 'LLM_MODELS',
  'SEARCH_BACKEND', 'WET_AUTO_SEARXNG', 'SEARXNG_URL', 'TAVILY_API_KEY',
  'PUBLIC_URL', 'CREDENTIAL_SECRET', 'JINA_AI_API_KEY',
  'GOOGLE_VERTEX_EXPRESS_API_KEY', 'XAI_API_KEY',
  'MCP_RELAY_PASSWORD', 'MCP_DCR_SERVER_SECRET',
  // capability provider chains + disable-local toggles (WS-2/3/4/5)
  'SEARCH_BACKENDS', 'BRAVE_API_KEY', 'EXA_API_KEY',
  'BROWSER_BACKENDS', 'CF_ACCOUNT_ID', 'CF_BROWSER_RENDERING_TOKEN',
  'BROWSERLESS_URL', 'BROWSERLESS_TOKEN', 'CAPSOLVER_API_KEY',
  'DISABLE_LOCAL_EMBED', 'DISABLE_LOCAL_RERANK',
  'DISABLE_LOCAL_SEARCH', 'DISABLE_LOCAL_BROWSER',
  'RESPECT_ROBOTS_TXT',
  // CF AI Gateway (llm-main) litellm routing
  'OPENROUTER_API_BASE', 'OPENROUTER_API_KEY', 'JINA_AI_API_BASE',
] as const

export function pickContainerEnv(env: Env): Record<string, string> {
  const out: Record<string, string> = {}
  for (const k of CONTAINER_ENV_KEYS) {
    const v = (env as unknown as Record<string, unknown>)[k]
    if (typeof v === 'string' && v !== '') out[k] = v
  }
  return out
}

// --- Outbound handlers (container -> Worker bindings) -----------------------
// These run when the container makes an outbound HTTP request to one of the
// internal hostnames. They are registered via `WetContainer.outboundByHost`
// (assignment, NOT a class field) so the assignment hits the inherited setter
// and populates the package's module-level handler registry. A `static
// outboundByHost = {...}` field would use define-semantics, bypass the setter,
// and silently fall through to the public internet (kv.internal -> NXDOMAIN).

const kvOutbound: OutboundHandler<Env> = async (request, env) => {
  const url = new URL(request.url)
  const key = decodeURIComponent(url.pathname.replace(/^\//, ''))
  // Readiness probe (E.1): once this handler answers, outbound interception is
  // wired, so the container's first credential PUT is safe. Mirrors
  // vectorizeOutbound's GET -> {ready:true}. Reserved key, checked before the
  // normal key lookup so it never shadows a real KV key.
  if (request.method === 'GET' && key === '__ready') {
    return Response.json({ ready: true })
  }
  if (request.method === 'GET') {
    // Credential blobs are binary (nonce + AES-GCM ciphertext); read/write as
    // ArrayBuffer so bytes round-trip without UTF-8 corruption.
    const v = await env.KV.get(key, 'arrayBuffer')
    return v === null ? new Response('', { status: 404 }) : new Response(v, { status: 200 })
  }
  if (request.method === 'PUT') {
    await env.KV.put(key, await request.arrayBuffer())
    return new Response('', { status: 200 })
  }
  if (request.method === 'DELETE') {
    await env.KV.delete(key)
    return new Response('', { status: 200 })
  }
  return new Response('method not allowed', { status: 405 })
}

const d1Outbound: OutboundHandler<Env> = async (request, env) => {
  const url = new URL(request.url)
  if (request.method === 'POST') {
    if (url.pathname === '/query') {
      const { sql, params } = (await request.json()) as { sql: string; params: unknown[] }
      const { results } = await env.D1.prepare(sql).bind(...(params ?? [])).all()
      return Response.json({ results })
    }
    if (url.pathname === '/batch') {
      const queries = (await request.json()) as { sql: string; params: unknown[] }[]
      const stmts = queries.map((q) => env.D1.prepare(q.sql).bind(...(q.params ?? [])))
      const batchResults = await env.D1.batch(stmts)
      return Response.json({ results: batchResults })
    }
  }
  return new Response('not found', { status: 404 })
}

const vectorizeOutbound: OutboundHandler<Env> = async (request, env) => {
  const url = new URL(request.url)
  if (url.pathname === '/upsert' && request.method === 'POST') {
    const vectors = (await request.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l))
    return Response.json(await env.VECTORIZE.upsert(vectors))
  }
  if (url.pathname === '/query' && request.method === 'POST') {
    const { vector, topK, filter } = (await request.json()) as { vector: number[]; topK: number; filter?: unknown }
    return Response.json(await env.VECTORIZE.query(vector, { topK, filter }))
  }
  // Re-indexing deletes chunk rows from D1; without this route their vectors
  // stay in the index and come back as search hits whose content is gone.
  if (url.pathname === '/deleteByIds' && request.method === 'POST') {
    const { ids } = (await request.json()) as { ids: string[] }
    return Response.json(await env.VECTORIZE.deleteByIds(ids))
  }
  if (request.method === 'GET') return Response.json({ ready: true })
  return new Response('not found', { status: 404 })
}

// Outbound handler registry, keyed by internal hostname. Production container
// outbound (kv/d1/vectorize.internal) reaches these via @cloudflare/containers'
// ContainerProxy + the WetContainer.outboundByHost assignment below — NOT via the
// public `fetch` export. Exported so unit tests can invoke a handler directly
// instead of routing an internal-host request through the public entrypoint.
export const OUTBOUND_BY_HOST: Record<string, OutboundHandler<Env>> = {
  'kv.internal': kvOutbound,
  'd1.internal': d1Outbound,
  'vectorize.internal': vectorizeOutbound,
}

// Bearer credential presence check. Structural only -- validity is the container's job.
const BEARER = /^Bearer\s+\S/i

function unauthenticated(request: Request): Response {
  const { origin } = new URL(request.url)
  return new Response(null, {
    status: 401,
    headers: {
      'WWW-Authenticate': `Bearer resource_metadata="${origin}/.well-known/oauth-protected-resource"`,
    },
  })
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Public entrypoint: ONLY routes inbound requests to the per-user container
    // DO. The kv/d1/vectorize.internal outbound handlers are deliberately NOT
    // dispatched here — exposing them on the public fetch surface would let an
    // external caller (request hostname spoofed to kv.internal) read/write/delete
    // the credential KV namespace unauthenticated. Production container outbound
    // reaches them via @cloudflare/containers' ContainerProxy + the
    // WetContainer.outboundByHost registry below; unit tests call the handlers
    // directly via the OUTBOUND_BY_HOST export.
    // Edge auth gate. mcp-core's OAuth AS runs INSIDE the container, so before this
    // gate every anonymous /mcp request started the container and reset its 5m idle
    // timer -- an unauthenticated caller could pin it awake and bill GiB-s around the
    // clock. Verified 2026-07-09: a python-httpx client POSTed /mcp with no
    // Authorization header every ~20s for 12h+. The check is STRUCTURAL: it rejects
    // requests carrying no bearer credential at all and reproduces the container's own
    // 401 (empty body + RFC 9728 WWW-Authenticate). Token VALIDITY is never judged
    // here -- the container remains the sole authority, so no mcp-core auth logic is
    // duplicated at the edge.
    const url = new URL(request.url)
    if (url.pathname === '/mcp' || url.pathname.startsWith('/mcp/')) {
      if (!BEARER.test(request.headers.get('authorization') ?? '')) return unauthenticated(request)
    }
    // Standing GET /mcp = the streamable-HTTP server-push SSE stream. On a
    // scale-to-zero container this is pure idle cost: @cloudflare/containers
    // counts an open stream as an in-flight request forever (inflight > 0 =>
    // activity never expires), so a single idle client pins the container
    // awake 24/7. None of this stack's servers send server-initiated
    // messages; request-scoped notifications ride the POST's own SSE
    // response. The spec allows declining the stream: both official SDKs
    // treat 405 as the optional-feature path and continue POST-only.
    if (request.method === 'GET' && (url.pathname === '/mcp' || url.pathname.startsWith('/mcp/'))) {
      return new Response(null, { status: 405, headers: { Allow: 'POST, DELETE' } })
    }
    if (env.WET) {
      const userId = await extractUserId()
      const stub = env.WET.get(env.WET.idFromName(userId))
      return stub.fetch(request)
    }
    return new Response('not found', { status: 404 })
  },
}

async function extractUserId(): Promise<string> {
  // SINGLE-DO COLLAPSE (2026-06-30): route EVERY request (OAuth /authorize,
  // /token, /.well-known AND every sub's /mcp) to the one reserved "default"
  // Durable Object. Under max_instances=1 (locked solo-dev cost rule) the prior
  // per-sub-DO routing DEADLOCKED: the OAuth flow (no Bearer) warmed DO "default"
  // while the first /mcp (Bearer sub) needed DO "<sub>" -- a 2nd container that
  // cannot spawn under max=1 ("Maximum number of running container instances
  // exceeded" 500). Safe: the container is STATELESS -- per-sub data is
  // externalised (D1 sub-column / Vectorize sub-filter / KV) keyed by the Bearer
  // JWT sub, so one container serves all subs with no leakage. (Trade-off: one
  // shared container for all subs; fine for solo / low concurrency.)
  return 'default'
}

// Per-user container Durable Object. wrangler.jsonc binds WET to this class and
// runs the Cloudflare-managed wet-mcp HTTP image; one instance per JWT sub. The
// container's HTTP server listens on 8080 (Dockerfile http target: MCP_PORT=8080
// + EXPOSE 8080).
export class WetContainer extends Container<Env> {
  defaultPort = 8080
  sleepAfter = '5m'
  // Port-readiness probe used by @cloudflare/containers' waitForPort(): it does
  // tcpPort.fetch('http://' + pingEndpoint) against the container's bound port, so the
  // host segment is only a Host header (no DNS) and ANY HTTP response marks the port
  // ready. core-py serves 200 at '/', so this points there. It does NOT drive the
  // platform's `healthy` metric -- see the edge auth gate above for the real cause of
  // containers never sleeping.
  pingEndpoint = 'localhost/'
  // The container reaches cloud model/search APIs (Jina, Vertex, Tavily) over the
  // public internet; kv/d1/vectorize.internal stay intercepted (see outboundByHost).
  enableInternet = true
  // Forward Worker config (vars) + secrets into the container process. Without
  // this the Python server defaults to MCP_STORAGE_BACKEND=local / DOCS_DB_BACKEND=sqlite
  // on the ephemeral container FS and downloads local ONNX models.
  envVars = pickContainerEnv(this.env)
}

// Register outbound interception. MUST be an assignment (invokes the inherited
// `static set outboundByHost`) — a class field would bypass the setter. Reuses
// OUTBOUND_BY_HOST so the proxy registry and the direct fetch dispatch are one
// source of truth (footgun #1: assignment, never a static field).
WetContainer.outboundByHost = OUTBOUND_BY_HOST as Record<string, OutboundHandler>
