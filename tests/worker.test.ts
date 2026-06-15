import { describe, expect, it } from 'vitest'
import worker from '../src/worker'

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

describe('outbound handlers', () => {
  it('KV get 404 then put then get 200', async () => {
    const env = fakeEnv()
    let res = await worker.fetch(new Request('http://kv.internal/wet%2Fconfig'), env as never)
    expect(res.status).toBe(404)
    res = await worker.fetch(new Request('http://kv.internal/wet%2Fconfig', { method: 'PUT', body: 'blob' }), env as never)
    expect(res.status).toBe(200)
    res = await worker.fetch(new Request('http://kv.internal/wet%2Fconfig'), env as never)
    expect(await res.text()).toBe('blob')
  })

  it('D1 query uses prepared statement', async () => {
    const env = fakeEnv()
    const res = await worker.fetch(
      new Request('http://d1.internal/query', { method: 'POST', body: JSON.stringify({ sql: 'SELECT 1', params: [] }) }),
      env as never,
    )
    const body = (await res.json()) as { results: unknown[] }
    expect(body.results.length).toBe(1)
  })

  it('Vectorize query returns matches', async () => {
    const env = fakeEnv()
    const res = await worker.fetch(
      new Request('http://vectorize.internal/query', { method: 'POST', body: JSON.stringify({ vector: [0.1], topK: 1 }) }),
      env as never,
    )
    const body = (await res.json()) as { matches: unknown[] }
    expect(body.matches.length).toBe(1)
  })
})
