// src/worker.ts
// Worker fronting the wet-mcp container Durable Object + outbound handlers for
// KV / D1 / Vectorize. Container calls http://{kv,d1,vectorize}.internal/...
// internally; production requests on the custom domain are forwarded to the DO.
import { Container } from '@cloudflare/containers'

export interface Env {
  KV: { get(k: string): Promise<string | null>; put(k: string, v: string): Promise<void>; delete(k: string): Promise<void> }
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

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url)
    const host = url.hostname

    if (host === 'kv.internal') {
      const key = decodeURIComponent(url.pathname.replace(/^\//, ''))
      if (request.method === 'GET') {
        const v = await env.KV.get(key)
        return v === null ? new Response('', { status: 404 }) : new Response(v, { status: 200 })
      }
      if (request.method === 'PUT') {
        await env.KV.put(key, await request.text())
        return new Response('', { status: 200 })
      }
      if (request.method === 'DELETE') {
        await env.KV.delete(key)
        return new Response('', { status: 200 })
      }
      return new Response('method not allowed', { status: 405 })
    }

    if (host === 'd1.internal' && url.pathname === '/query' && request.method === 'POST') {
      const { sql, params } = (await request.json()) as { sql: string; params: unknown[] }
      const { results } = await env.D1.prepare(sql).bind(...(params ?? [])).all()
      return Response.json({ results })
    }

    if (host === 'vectorize.internal') {
      if (url.pathname === '/upsert' && request.method === 'POST') {
        const vectors = (await request.text()).split('\n').filter(Boolean).map((l) => JSON.parse(l))
        return Response.json(await env.VECTORIZE.upsert(vectors))
      }
      if (url.pathname === '/query' && request.method === 'POST') {
        const { vector, topK, filter } = (await request.json()) as { vector: number[]; topK: number; filter?: unknown }
        return Response.json(await env.VECTORIZE.query(vector, { topK, filter }))
      }
      if (request.method === 'GET') return Response.json({ ready: true })
    }

    // Production request -> route to the per-user container Durable Object.
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
  // public internet; kv/d1/vectorize.internal stay intercepted by the Worker.
  enableInternet = true
  // Forward Worker config (vars) + secrets into the container process. Without
  // this the Python server defaults to MCP_STORAGE_BACKEND=local / DOCS_DB_BACKEND=sqlite
  // on the ephemeral container FS and downloads local ONNX models.
  envVars = pickContainerEnv(this.env)
}
