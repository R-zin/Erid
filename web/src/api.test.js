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

  it('search sends query param and limit', async () => {
    const calls = stubFetch(new Response('{"query":"auth","tasks":[],"decisions":[]}', { status: 200 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    const res = await client.search('auth', 10)
    expect(calls[0].url).toBe('/api/workspaces/ws/search?q=auth&limit=10')
    expect(res.query).toBe('auth')
  })

  it('updatePresence posts presence heartbeat payload', async () => {
    const payload = { actor_name: 'dev', actor_type: 'human', current_task: 'debugging' }
    const calls = stubFetch(new Response(JSON.stringify(payload), { status: 200 }))
    const client = makeClient({ slug: 'ws', credential: 'k' })
    await client.updatePresence(payload)
    expect(calls[0].url).toBe('/api/workspaces/ws/presence')
    expect(calls[0].options.method).toBe('POST')
    expect(JSON.parse(calls[0].options.body)).toEqual(payload)
  })
})

describe('top-level workspace management API', () => {
  it('provisionWorkspace sends POST /api/workspaces?slug=...', async () => {
    const calls = stubFetch(new Response('{"slug":"new-ws","api_key":"key-123"}', { status: 201 }))
    const { provisionWorkspace } = await import('./api.js')
    const res = await provisionWorkspace('new-ws')
    expect(calls[0].url).toBe('/api/workspaces?slug=new-ws')
    expect(calls[0].options.method).toBe('POST')
    expect(res.api_key).toBe('key-123')
  })

  it('deleteWorkspace sends DELETE /api/workspaces/{slug} with auth header', async () => {
    const calls = stubFetch(new Response(null, { status: 204 }))
    const { deleteWorkspace } = await import('./api.js')
    const ok = await deleteWorkspace('old-ws', 'secret-key', { authType: 'key' })
    expect(ok).toBe(true)
    expect(calls[0].url).toBe('/api/workspaces/old-ws')
    expect(calls[0].options.method).toBe('DELETE')
    expect(calls[0].options.headers['X-API-Key']).toBe('secret-key')
  })

  it('listWorkspacesDetailed returns full array of workspace objects', async () => {
    const mockList = [{ slug: 'w1', name: 'w1', is_secured: true }]
    stubFetch(new Response(JSON.stringify(mockList), { status: 200 }))
    const { listWorkspacesDetailed } = await import('./api.js')
    const res = await listWorkspacesDetailed()
    expect(res).toEqual(mockList)
  })
})

