import { describe, it, expect, vi, afterEach } from 'vitest'
import { makeClient, ApiError } from './api.js'

afterEach(() => {
  vi.unstubAllGlobals()
})

function stubFetch(response) {
  const calls = []
  vi.stubGlobal('fetch', vi.fn(async (url, options) => {
    calls.push({ url, options })
    return response
  }))
  return calls
}

describe('makeClient request semantics', () => {
  it('parses JSON on 200', async () => {
    stubFetch(new Response('{"task_count": 3}', { status: 200 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    expect(await client.summary()).toEqual({ task_count: 3 })
  })

  it('returns null on 204 (DELETE No Content)', async () => {
    stubFetch(new Response(null, { status: 204 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    expect(await client.deleteTask('abc')).toBeNull()
  })

  it('throws ApiError with status on 401/403', async () => {
    stubFetch(new Response('unauthorized', { status: 401, statusText: 'Unauthorized' }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    const err = await client.tasks().catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(401)
  })

  it('del sends method DELETE', async () => {
    const calls = stubFetch(new Response(null, { status: 204 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    await client.deleteDecision('d1')
    expect(calls[0].url).toBe('/api/workspaces/ws/decisions/d1')
    expect(calls[0].options.method).toBe('DELETE')
  })

  it('put sends JSON content-type and body', async () => {
    const calls = stubFetch(new Response('{"id":"t1","status":"done"}', { status: 200 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    await client.updateTask('t1', { status: 'done' })
    expect(calls[0].url).toBe('/api/workspaces/ws/tasks/t1')
    expect(calls[0].options.method).toBe('PUT')
    expect(calls[0].options.headers['Content-Type']).toBe('application/json')
    expect(JSON.parse(calls[0].options.body)).toEqual({ status: 'done' })
  })

  it('sends X-API-Key for key auth and Bearer for token auth', async () => {
    const keyCalls = stubFetch(new Response('[]', { status: 200 }))
    await makeClient({ slug: 'ws', credential: 'secret', authType: 'key' }).tasks()
    expect(keyCalls[0].options.headers['X-API-Key']).toBe('secret')

    const tokCalls = stubFetch(new Response('[]', { status: 200 }))
    await makeClient({ slug: 'ws', credential: 'jwt', authType: 'token' }).tasks()
    expect(tokCalls[0].options.headers.Authorization).toBe('Bearer jwt')
  })
})
