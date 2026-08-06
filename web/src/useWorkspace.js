import { useCallback, useEffect, useRef, useState } from 'react'
import { makeClient, ApiError } from './api.js'

// Live workspace state: initial REST snapshot + real-time WebSocket events.
// `credential` (API key or JWT) + `authType` ('key' | 'token') authenticate
// both the REST calls and the socket. Auth failures (401/403) surface as an
// ApiError so the UI can prompt the user to re-authenticate.
export function useWorkspace(slug, credential, authType) {
  const [summary, setSummary] = useState(null)
  const [tasks, setTasks] = useState([])
  const [decisions, setDecisions] = useState([])
  const [presence, setPresence] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)

  const load = useCallback(async () => {
    const client = makeClient({ slug, credential, authType })
    const [s, t, d, p] = await Promise.all([
      client.summary(),
      client.tasks(),
      client.decisions(),
      client.presence(),
    ])
    setSummary(s)
    setTasks(t)
    setDecisions(d)
    setPresence(p)
  }, [slug, credential, authType])

  // Initial snapshot.
  useEffect(() => {
    if (!slug) {
      setSummary(null)
      setTasks([])
      setDecisions([])
      setPresence([])
      setError(null)
      return
    }
    setError(null)
    load().catch((e) => setError(authMessage(e)))
  }, [slug, load])

  // Real-time stream.
  useEffect(() => {
    if (!slug) return undefined
    const client = makeClient({ slug, credential, authType })
    const ws = new WebSocket(client.socketUrl())
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)
    ws.onmessage = (msg) => {
      const event = JSON.parse(msg.data)
      applyEvent(event, { setTasks, setDecisions, setPresence })
      // Keep the header summary fresh on any change.
      load().catch(() => {})
    }

    return () => {
      ws.close()
      wsRef.current = null
    }
  }, [slug, credential, authType, load])

  return { summary, tasks, decisions, presence, connected, error, reload: load, setTasks, setDecisions }
}

function authMessage(e) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
    return 'Authentication failed (check your workspace slug and credential, then reconnect).'
  }
  return e.message
}

function applyEvent(event, { setTasks, setDecisions, setPresence }) {
  const { type, data } = event
  if (type === 'task_created') {
    setTasks((prev) => upsertById(prev, data))
  } else if (type === 'task_updated') {
    setTasks((prev) => upsertById(prev, data))
  } else if (type === 'decision_created') {
    setDecisions((prev) => [data, ...prev.filter((d) => d.id !== data.id)])
  } else if (type === 'presence_updated') {
    setPresence((prev) => upsertById(prev, data))
  }
}

function upsertById(list, item) {
  const idx = list.findIndex((x) => x.id === item.id)
  if (idx === -1) return [...list, item]
  const next = list.slice()
  next[idx] = item
  return next
}
