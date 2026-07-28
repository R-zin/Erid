import { useCallback, useEffect, useRef, useState } from 'react'
import { makeClient } from './api.js'

// Live workspace state: initial REST snapshot + real-time WebSocket events.
export function useWorkspace(slug, apiKey) {
  const [summary, setSummary] = useState(null)
  const [tasks, setTasks] = useState([])
  const [decisions, setDecisions] = useState([])
  const [presence, setPresence] = useState([])
  const [connected, setConnected] = useState(false)
  const [error, setError] = useState(null)
  const wsRef = useRef(null)

  const load = useCallback(async () => {
    const client = makeClient({ slug, apiKey })
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
  }, [slug, apiKey])

  // Initial snapshot.
  useEffect(() => {
    setError(null)
    load().catch((e) => setError(e.message))
  }, [load])

  // Real-time stream.
  useEffect(() => {
    if (!slug) return undefined
    const client = makeClient({ slug, apiKey })
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
  }, [slug, apiKey, load])

  return { summary, tasks, decisions, presence, connected, error, reload: load }
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
