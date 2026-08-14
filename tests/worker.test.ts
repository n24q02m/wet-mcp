import { describe, expect, it } from 'vitest'
import worker, { OUTBOUND_BY_HOST, pickContainerEnv } from '../src/worker'

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
      deleted: [] as string[][],
      async deleteByIds(ids: string[]) {
        this.deleted.push(ids)
        return { mutationId: 'm-del' }
      },
    },
  }
}

// Invoke an outbound handler DIRECTLY (the production path is the container proxy
// via WetContainer.outboundByHost; the handlers are NOT reachable through the
// public `fetch` entrypoint, so tests exercise them through the exported registry).
const kvH = OUTBOUND_BY_HOST['kv.internal']!
const d1H = OUTBOUND_BY_HOST['d1.internal']!
const vectorizeH = OUTBOUND_BY_HOST['vectorize.internal']!
// Handlers also take an OutboundHandlerContext third arg (containerId/className);
// unused by these handlers, only needed to satisfy the call signature in tests.
const ctx = { containerId: 'test', className: 'WetContainer' } as never

describe('container environment forwarding', () => {
  it('forwards the explicit robots policy to the Python process', () => {
    const env = { RESPECT_ROBOTS_TXT: 'true' }

    expect(pickContainerEnv(env as never)).toEqual({ RESPECT_ROBOTS_TXT: 'true' })
  })
})

describe('outbound handlers', () => {
  it('KV get 404 then put then get 200', async () => {
    const env = fakeEnv()
    let res = await kvH(new Request('http://kv.internal/wet%2Fconfig'), env as never, ctx)
    expect(res.status).toBe(404)
    res = await kvH(new Request('http://kv.internal/wet%2Fconfig', { method: 'PUT', body: 'blob' }), env as never, ctx)
    expect(res.status).toBe(200)
    res = await kvH(new Request('http://kv.internal/wet%2Fconfig'), env as never, ctx)
    expect(await res.text()).toBe('blob')
  })

  it('D1 query uses prepared statement', async () => {
    const env = fakeEnv()
    const res = await d1H(
      new Request('http://d1.internal/query', { method: 'POST', body: JSON.stringify({ sql: 'SELECT 1', params: [] }) }),
      env as never,
      ctx,
    )
    const body = (await res.json()) as { results: unknown[] }
    expect(body.results.length).toBe(1)
  })

  it('Vectorize query returns matches', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/query', { method: 'POST', body: JSON.stringify({ vector: [0.1], topK: 1 }) }),
      env as never,
      ctx,
    )
    const body = (await res.json()) as { matches: unknown[] }
    expect(body.matches.length).toBe(1)
  })

  it('Vectorize deleteByIds forwards the ids to the binding', async () => {
    const env = fakeEnv()
    const res = await vectorizeH(
      new Request('http://vectorize.internal/deleteByIds', { method: 'POST', body: JSON.stringify({ ids: ['c1', 'c2'] }) }),
      env as never,
      ctx,
    )
    expect(res.status).toBe(200)
    expect(env.VECTORIZE.deleted).toEqual([['c1', 'c2']])
    expect(await res.json()).toEqual({ mutationId: 'm-del' })
  })

  it('KV readiness probe: GET __ready -> {ready:true}', async () => {
    const env = fakeEnv()
    const res = await kvH(new Request('http://kv.internal/__ready'), env as never, ctx)
    expect(res.status).toBe(200)
    expect(await res.json()).toEqual({ ready: true })
  })

  it('KV readiness probe does not shadow a real missing key', async () => {
    const env = fakeEnv()
    // a real key that happens to be absent still 404s (the probe is the reserved __ready only)
    const res = await kvH(new Request('http://kv.internal/wet%2Fsubs%2Fu1%2Fconfig'), env as never, ctx)
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

describe('single-DO collapse (2026-06-30): every request routes to "default"', () => {
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

  // A bare, no-Bearer /mcp request is now rejected at the edge auth gate before DO
  // routing ever runs (see 'edge auth gate (/mcp)' below) -- exercise the "always
  // 'default'" DO-routing invariant on a non-gated path instead (/authorize is one
  // of the paths the edge gate deliberately leaves untouched).
  it('no Bearer token, non-/mcp path -> routes to the "default" DO', async () => {
    const { calls, env } = envWithDoSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/authorize'), env as never)
    expect(res.status).toBe(200)
    expect(calls).toEqual(['default'])
  })

  it('Bearer token without sub -> routes to the "default" DO', async () => {
    const { calls, env } = envWithDoSpy()
    // header.payload.sig where payload has no `sub`
    const jwt = `h.${btoa(JSON.stringify({ aud: 'x' }))}.s`
    // POST: this exercises DO-routing/sub-extraction, not GET-stream semantics
    // (a bare GET now declines 405 before DO routing, see 'edge auth gate' below).
    await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { method: 'POST', headers: { authorization: `Bearer ${jwt}` } }),
      env as never,
    )
    expect(calls).toEqual(['default'])
  })

  it('Bearer token with sub -> still routes to the "default" DO (stateless container, sub externalised to D1/Vectorize/KV)', async () => {
    const { calls, env } = envWithDoSpy()
    const jwt = `h.${btoa(JSON.stringify({ sub: 'user-123' }))}.s`
    // POST: see rationale above.
    await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { method: 'POST', headers: { authorization: `Bearer ${jwt}` } }),
      env as never,
    )
    expect(calls).toEqual(['default'])
  })
})

describe('edge auth gate (/mcp)', () => {
  function envWithFetchSpy() {
    const fetchCalls: Request[] = []
    return {
      fetchCalls,
      env: {
        WET: {
          idFromName: (n: string) => ({ name: n }),
          get: (_id: unknown) => ({
            fetch: async (r: Request) => {
              fetchCalls.push(r)
              return new Response('routed', { status: 200 })
            },
          }),
        },
      },
    }
  }

  it('POST /mcp with no Authorization -> 401, stub never called', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/mcp', { method: 'POST' }), env as never)
    expect(res.status).toBe(401)
    expect(res.headers.get('WWW-Authenticate')).toMatch(
      /^Bearer resource_metadata="https:\/\/[^"]+\/\.well-known\/oauth-protected-resource"$/,
    )
    expect(await res.text()).toBe('')
    expect(fetchCalls.length).toBe(0)
  })

  it('OPTIONS /mcp with no Authorization -> 401, stub never called', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/mcp', { method: 'OPTIONS' }), env as never)
    expect(res.status).toBe(401)
    expect(fetchCalls.length).toBe(0)
  })

  it('POST /mcp with Authorization: Bearer anything -> stub called exactly once', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { method: 'POST', headers: { authorization: 'Bearer anything' } }),
      env as never,
    )
    expect(res.status).toBe(200)
    expect(fetchCalls.length).toBe(1)
  })

  it('GET /mcp with Authorization: Bearer x -> 405, Allow: POST, DELETE, stub never called', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp', { method: 'GET', headers: { authorization: 'Bearer x' } }),
      env as never,
    )
    expect(res.status).toBe(405)
    expect(res.headers.get('Allow')).toBe('POST, DELETE')
    expect(fetchCalls.length).toBe(0)
  })

  it('GET /mcp/sub with Authorization: Bearer x -> 405', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(
      new Request('https://wet.n24q02m.com/mcp/sub', { method: 'GET', headers: { authorization: 'Bearer x' } }),
      env as never,
    )
    expect(res.status).toBe(405)
    expect(fetchCalls.length).toBe(0)
  })

  it('GET /mcp with no Authorization -> still 401 (bearer gate runs before the 405 decline)', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/mcp', { method: 'GET' }), env as never)
    expect(res.status).toBe(401)
    expect(fetchCalls.length).toBe(0)
  })

  it('GET /authorize with no Authorization -> passes through, stub called', async () => {
    const { fetchCalls, env } = envWithFetchSpy()
    const res = await worker.fetch(new Request('https://wet.n24q02m.com/authorize?foo=1'), env as never)
    expect(res.status).toBe(200)
    expect(fetchCalls.length).toBe(1)
  })
})
