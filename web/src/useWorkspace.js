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
  const [handoffs, setHandoffs] = useState([])
  const [presence, setPresence] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)

  const load = useCallback(async () => {
    const client = makeClient({ slug, credential, authType })
    const [s, t, d, h, p] = await Promise.all([
      client.summary(),
      client.tasks(),
      client.decisions(),
      client.handoffs(),
      client.presence(),
    ])
    setSummary(s)
    setTasks(t)
    setDecisions(d)
    setHandoffs(h)
    setPresence(p)
  }, [slug, credential, authType])

  // Initial snapshot.
  useEffect(() => {
    if (!slug) {
      setSummary(null)
      setTasks([])
      setDecisions([])
      setHandoffs([])
      setPresence([])
      setError(null)
      return
    }
    setError(null)
    load().catch((e) => setError(authMessage(e)))
  }, [slug, load])

  // Real-time stream: reconnect with exponential backoff (mirrors the hub
  // bridge), apply events locally, and refresh only the tiny summary on a
  // trailing debounce — never the 4-collection reload per frame.
  useEffect(() => {
    if (!slug) return undefined
    const client = makeClient({ slug, credential, authType })
    let cancelled = false
    let ws = null
    let retries = 0
    let retryTimer = null
    let summaryTimer = null

    const scheduleSummary = () => {
      clearTimeout(summaryTimer)
      summaryTimer = setTimeout(() => {
        client.summary().then(setSummary).catch(() => {})
      }, SUMMARY_DEBOUNCE)
    }

    const connectWs = () => {
      if (cancelled) return
      ws = new WebSocket(client.socketUrl())
      wsRef.current = ws

      ws.onopen = () => {
        retries = 0
        setConnected(true)
      }
      ws.onmessage = (msg) => {
        let event
        try {
          event = JSON.parse(msg.data)
        } catch {
          return // malformed frame: drop, keep streaming
        }
        if (event.type === 'ping') return // keepalive
        if (event.type === 'workspace_deleted') {
          setError(`Workspace '${slug}' was deleted.`)
          ws.close() // deliberate; onclose sees wsRef.current !== ws → no reconnect
          wsRef.current = null
          return
        }
        applyEvent(event, { setTasks, setDecisions, setHandoffs, setPresence })
        if (
          event.type.startsWith('task_') ||
          event.type.startsWith('decision_') ||
          event.type.startsWith('handoff_')
        )
          scheduleSummary()
      }
      ws.onclose = () => {
        setConnected(false)
        if (cancelled || wsRef.current !== ws) return // deliberate teardown / stale socket
        wsRef.current = null
        const delay = Math.min(BACKOFF_MIN * 2 ** retries, BACKOFF_MAX)
        retries += 1
        retryTimer = setTimeout(() => {
          load().catch(() => {}) // authoritative resync after a drop
          connectWs()
        }, delay)
      }
      ws.onerror = () => {} // onclose always follows; single reconnect path
    }
    connectWs()

    return () => {
      cancelled = true
      clearTimeout(retryTimer)
      clearTimeout(summaryTimer)
      if (wsRef.current) {
        wsRef.current = null
        ws.close()
      }
    }
  }, [slug, credential, authType, load])

  return {
    summary,
    tasks,
    decisions,
    handoffs,
    presence,
    connected,
    error,
    reload: load,
    setTasks,
    setDecisions,
    setHandoffs,
  }
}

const BACKOFF_MIN = 1000
const BACKOFF_MAX = 30000
const SUMMARY_DEBOUNCE = 500

function authMessage(e) {
  if (e instanceof ApiError && (e.status === 401 || e.status === 403)) {
    return 'Authentication failed (check your workspace slug and credential, then reconnect).'
  }
  return e.message
}

export function applyEvent(event, { setTasks, setDecisions, setHandoffs, setPresence }) {
  const { type, data } = event
  if (type === 'task_created') {
    setTasks((prev) => upsertById(prev, data))
  } else if (type === 'task_updated') {
    setTasks((prev) => upsertById(prev, data))
  } else if (type === 'task_deleted') {
    setTasks((prev) => prev.filter((t) => t.id !== data.id))
  } else if (type === 'decision_created') {
    setDecisions((prev) => [data, ...prev.filter((d) => d.id !== data.id)])
  } else if (type === 'decision_deleted') {
    setDecisions((prev) => prev.filter((d) => d.id !== data.id))
  } else if (type === 'handoff_created') {
    setHandoffs?.((prev) => [data, ...prev.filter((h) => h.id !== data.id)])
  } else if (type === 'handoff_updated') {
    // Handoffs are recency-ordered; an update (ack/resolve) keeps its position.
    setHandoffs?.((prev) => upsertById(prev, data))
  } else if (type === 'handoff_deleted') {
    setHandoffs?.((prev) => prev.filter((h) => h.id !== data.id))
  } else if (type === 'presence_updated') {
    setPresence((prev) => upsertById(prev, data))
  }
}

export function upsertById(list, item) {
  const idx = list.findIndex((x) => x.id === item.id)
  if (idx === -1) return [...list, item]
  const next = list.slice()
  next[idx] = item
  return next
}
