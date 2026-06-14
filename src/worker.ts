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
}
