// Thin client for the Context Hub REST API + WebSocket.
//
// Auth: a credential may be a raw workspace/actor API key (sent as the
// `X-API-Key` header) or a short-lived JWT (sent as `Authorization: Bearer`).
// The caller tells us which via `authType` ('key' | 'token'); when omitted we
// default to the API-key header, matching the original behaviour. On the
// WebSocket the same credential travels as `?api_key=` or `?token=`.

function authHeader(credential, authType) {
  if (!credential) return {}
  return authType === 'token'
    ? { Authorization: `Bearer ${credential}` }
    : { 'X-API-Key': credential }
}

export class ApiError extends Error {
  constructor(status, statusText) {
    super(`${status} ${statusText}`)
    this.status = status
  }
}

export function makeClient({ slug, credential, authType = 'key', base = '' }) {
  const headers = authHeader(credential, authType)
  const root = `${base}/api/workspaces/${slug}`

  const request = async (path, options = {}) => {
    const r = await fetch(`${root}${path}`, { headers, ...options })
    if (!r.ok) throw new ApiError(r.status, r.statusText)
    return r.status === 204 ? null : r.json() // DELETE → No Content
  }

  const get = (path) => request(path)
  const post = (path, body) =>
    request(path, {
      method: 'POST',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  const put = (path, body) =>
    request(path, {
      method: 'PUT',
      headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    })
  const del = (path) => request(path, { method: 'DELETE' })

  return {
    summary: () => get('/summary'),
    tasks: () => get('/tasks'),
    decisions: () => get('/decisions'),
    handoffs: () => get('/handoffs'),
    presence: () => get('/presence'),
    createTask: (task) => post('/tasks', task),
    createDecision: (decision) => post('/decisions', decision),
    createHandoff: (handoff) => post('/handoffs', handoff),
    acknowledgeHandoff: (id) => post(`/handoffs/${id}/acknowledge`),
    resolveHandoff: (id) => post(`/handoffs/${id}/resolve`),
    updateTask: (id, patch) => put(`/tasks/${id}`, patch),
    deleteTask: (id) => del(`/tasks/${id}`),
    deleteDecision: (id) => del(`/decisions/${id}`),
    deleteHandoff: (id) => del(`/handoffs/${id}`),

    socketUrl() {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = base ? new URL(base).host : window.location.host
      let q = ''
      if (credential) {
        const param = authType === 'token' ? 'token' : 'api_key'
        q = `?${param}=${encodeURIComponent(credential)}`
      }
      return `${proto}://${host}${root}/ws${q}`
    },
  }
}

// OPTIONAL discovery of known workspaces. The `GET /api/workspaces` list
// endpoint is being built concurrently and may not exist; every failure is
// swallowed and reported as an empty list so the UI degrades gracefully. We
// tolerate a JSON array of objects with a `slug` field, bare slug strings, or
// an object wrapping the array under a `workspaces` key.
export async function listWorkspaces({ base = '' } = {}) {
  try {
    const r = await fetch(`${base}/api/workspaces`)
    if (!r.ok) return []
    const data = await r.json()
    const arr = Array.isArray(data) ? data : data?.workspaces
    if (!Array.isArray(arr)) return []
    return arr
      .map((w) => (typeof w === 'string' ? w : w?.slug))
      .filter((s) => typeof s === 'string' && s.length > 0)
  } catch {
    return []
  }
}
