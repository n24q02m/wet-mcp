import { describe, expect, it } from 'vitest'
import worker, { OUTBOUND_BY_HOST } from '../src/worker'

function fakeEnv() {
  const kv = new Map<string, string>()
  return {
    KV: {
      get: async (k: string) => (kv.has(k) ? kv.get(k)! : null),
      put: async (k: string, v: string) => void kv.set(k, v),
      delete: async (k: string) => void kv.delete(k),
    },
    D1: {
      prepare: (sql: string) => ({
        bind: (..._p: unknown[]) => ({ all: async () => ({ results: [{ ok: 1, sql }] }) }),
      }),
    },
    VECTORIZE: {
      upsert: async () => ({ mutationId: 'm1' }),
      query: async () => ({ matches: [{ id: 'a', score: 0.9 }] }),
    },
  }
}

// Invoke an outbound handler DIRECTLY (the production path is the container proxy
// via WetContainer.outboundByHost; the handlers are NOT reachable through the
// public `fetch` entrypoint, so tests exercise them through the exported registry).
const kvH = OUTBOUND_BY_HOST['kv.internal']!
const d1H = OUTBOUND_BY_HOST['d1.internal']!
const vectorizeH = OUTBOUND_BY_HOST['vectorize.internal']!

describe('outbound handlers', () => {
  it('KV get 404 then put then get 200', async () => {
    const env = fakeEnv()
    let res = await kvH(new Request('http://kv.internal/wet%2Fconfig'), env as never)
    expect(res.status).toBe(404)
    res = await kvH(new Request('http://kv.internal/wet%2Fconfig', { method: 'PUT', body: 'blob' }), env as never)
    expect(res.status).toBe(200)
    res = await kvH(new Request('http://kv.internal/wet%2Fconfig'), env as never)
    expect(await res.text()).toBe('blob')
  })

  it('D1 query uses prepared statement', async () => {
    const env = fakeEnv()
    const res = await d1H(
      new Request('http://d1.internal/query', { method: 'POST', body: JSON.stringify({ sql: 'SELECT 1', params: [] }) }),
      env as never,
    )
    const body = (await res.json()) as { results: unknown[] }
    expect(body.results.length).toBe(1)
  })

  it('Vectorize query returns matches', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/query', { method: 'POST', body: JSON.stringify({ vector: [0.1], topK: 1 }) }),
      env as never,
    )
    const body = (await res.json()) as { matches: unknown[] }
    expect(body.matches.length).toBe(1)
  })

  it('KV readiness probe: GET __ready -> {ready:true}', async () => {
    const env = fakeEnv()
    const res = await kvH(new Request('http://kv.internal/__ready'), env as never)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ready: true })
  })

  it('KV readiness probe does not shadow a real missing key', async () => {
    const env = fakeEnv()
    // a real key that happens to be absent still 404s (the probe is the reserved __ready only)
    const res = await kvH(new Request('http://kv.internal/wet%2Fsubs%2Fu1%2Fconfig'), env as never)
    expect(res.status).toBe(404)
  })
})

describe('public fetch entrypoint does NOT expose outbound handlers (security)', () => {
  it('a public request with an internal hostname is NOT serviced by a handler', async () => {
    const env = fakeEnv() // no WET binding -> DO routing path returns 404
    // Even if an external caller spoofs the hostname to kv.internal, the public
    // fetch must NOT read/write the credential KV — it only routes to the DO.
    const res = await worker.fetch(new Request('http://kv.internal/wet%2Fconfig'), env as never)
    expect(res.status).toBe(404)
    expect(await res.text()).toBe('not found')
  })
})

describe('single-user DO contract (E.2)', () => {
  function envWithDoSpy() {
    const calls: string[] = []
    return {
      calls,
      env: {
        WET: {
          idFromName: (n: string) => {
            calls.push(n)
            return { name: n }
          },
          get: (_id: unknown) => ({ fetch: async () => new Response('routed', { status: 200 }) }),
        },
      },
    }
  }

  it('no Bearer token -> routes to the "default" DO', async () => {
    const { calls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/mcp'), env as never)
    expect(res.status).toBe(200)
    expect(calls).toEqual(['default'])
  })

  it('Bearer token without sub -> routes to the "default" DO', async () => {
    const { calls, env } = envWithDoSpy()
    // header.payload.sig where payload has no `sub`
    const jwt = `h.${btoa(JSON.stringify({ aud: 'x' }))}.s`
    await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { headers: { authorization: `Bearer ${jwt}` } }),
      env as never,
    )
    expect(calls).toEqual(['default'])
  })

  it('Bearer token with sub -> routes to that sub DO (per-user isolation)', async () => {
    const { calls, env } = envWithDoSpy()
    const jwt = `h.${btoa(JSON.stringify({ sub: 'user-123' }))}.s`
    await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { headers: { authorization: `Bearer ${jwt}` } }),
      env as never,
    )
    expect(calls).toEqual(['user-123'])
  })
})
