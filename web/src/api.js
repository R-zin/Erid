// Thin client for the Context Hub REST API + WebSocket.

export function makeClient({ slug, apiKey, base = '' }) {
  const headers = apiKey ? { 'X-API-Key': apiKey } : {}
  const root = `${base}/api/workspaces/${slug}`

  const get = async (path) => {
    const r = await fetch(`${root}${path}`, { headers })
    if (!r.ok) throw new Error(`${r.status} ${r.statusText}`)
    return r.json()
  }

  return {
    summary: () => get('/summary'),
    tasks: () => get('/tasks'),
    decisions: () => get('/decisions'),
    presence: () => get('/presence'),

    socketUrl() {
      const proto = window.location.protocol === 'https:' ? 'wss' : 'ws'
      const host = base ? new URL(base).host : window.location.host
      const q = apiKey ? `?api_key=${encodeURIComponent(apiKey)}` : ''
      return `${proto}://${host}${root}/ws${q}`
    },
  }
}
