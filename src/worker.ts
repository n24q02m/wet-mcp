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
  D1: { prepare(sql: string): { bind(...p: unknown[]): { all(): Promise<{ results: unknown[] }> } } }
  VECTORIZE: {
    upsert(v: unknown[]): Promise<{ mutationId: string }>
    query(vector: number[], opts: { topK: number; filter?: unknown }): Promise<{ matches: unknown[] }>
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
] as const

function pickContainerEnv(env: Env): Record<string, string> {
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
  if (url.pathname === '/query' && request.method === 'POST') {
    const { sql, params } = (await request.json()) as { sql: string; params: unknown[] }
    const { results } = await env.D1.prepare(sql).bind(...(params ?? [])).all()
    return Response.json({ results })
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
  if (request.method === 'GET') return Response.json({ ready: true })
  return new Response('not found', { status: 404 })
}

// Outbound handler registry, keyed by internal hostname. Both production (via
// @cloudflare/containers -> WetContainer.outboundByHost) and the direct fetch
// dispatch below share this single source of truth, so they can never drift.
const OUTBOUND_BY_HOST: Record<string, OutboundHandler<Env>> = {
  'kv.internal': kvOutbound,
  'd1.internal': d1Outbound,
  'vectorize.internal': vectorizeOutbound,
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    // Direct outbound entry: a request addressed to one of the internal hosts is
    // serviced by its handler (the same registry the container proxy uses). This
    // makes the handlers unit-testable and gives the kv.internal readiness probe
    // a reachable endpoint.
    const host = new URL(request.url).hostname
    const handler = OUTBOUND_BY_HOST[host]
    if (handler) return handler(request, env)

    // Inbound production request -> route to the per-user container DO.
    if (env.WET) {
      const userId = extractUserId(request)
      const stub = env.WET.get(env.WET.idFromName(userId))
      return stub.fetch(request)
    }
    return new Response('not found', { status: 404 })
  },
}

function extractUserId(request: Request): string {
  // JWT sub from the Bearer token (verified by mcp-core OAuth middleware in the
  // container). Single-instance-per-user: fall back to "default" when absent.
  const auth = request.headers.get('authorization') ?? ''
  const m = auth.match(/^Bearer\s+(.+)$/)
  if (!m) return 'default'
  try {
    const payload = JSON.parse(atob(m[1].split('.')[1] ?? ''))
    return typeof payload.sub === 'string' ? payload.sub : 'default'
  } catch {
    return 'default'
  }
}

// Per-user container Durable Object. wrangler.jsonc binds WET to this class and
// runs the ghcr.io/n24q02m/wet-mcp:http image; one instance per JWT sub. The
// container's HTTP server listens on 8080 (Dockerfile http target: MCP_PORT=8080
// + EXPOSE 8080).
export class WetContainer extends Container<Env> {
  defaultPort = 8080
  sleepAfter = '1h'
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
