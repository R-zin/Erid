import React, { useState } from 'react'
import SectionHeader from './SectionHeader.jsx'

export default function Presence({ presence, agentFilter = 'all', client = null, canWrite = false, index }) {
  const [showCheckIn, setShowCheckIn] = useState(false)
  const [actorName, setActorName] = useState('Web Client')
  const [currentTask, setCurrentTask] = useState('')
  const [currentFile, setCurrentFile] = useState('')
  const [busy, setBusy] = useState(false)
  const [checkInMsg, setCheckInMsg] = useState(null)

  const handleCheckIn = async (e) => {
    e.preventDefault()
    if (!actorName.trim() || !client || busy) return
    setBusy(true)
    setCheckInMsg(null)
    try {
      await client.updatePresence({
        actor_name: actorName.trim(),
        actor_type: 'human',
        current_task: currentTask.trim() || null,
        current_file: currentFile.trim() || null,
      })
      setCheckInMsg('Presence sent.')
      setTimeout(() => {
        setShowCheckIn(false)
        setCheckInMsg(null)
      }, 1500)
    } catch (err) {
      setCheckInMsg(err.message || 'Check-in failed')
    } finally {
      setBusy(false)
    }
  }

  const filtered = presence.filter((p) => {
    if (agentFilter === 'all') return true
    if (agentFilter === 'human') return p.actor_type === 'human'
    if (agentFilter === 'claude') return /claude/i.test(p.actor_name)
    if (agentFilter === 'cursor') return /cursor/i.test(p.actor_name)
    if (agentFilter === 'codex') return /codex/i.test(p.actor_name)
    return true
  })

  return (
    <section className="card-panel" aria-label="Presence">
      <SectionHeader
        index={index}
        title="Presence"
        meta={<span className="count-tag accent">{presence.length} online</span>}
      >
        {canWrite && client && (
          <button type="button" className="ghost small" onClick={() => setShowCheckIn((v) => !v)}>
            {showCheckIn ? 'Close' : 'Check In'}
          </button>
        )}
      </SectionHeader>

      {showCheckIn && (
        <form onSubmit={handleCheckIn} className="card-body" style={{ borderBottom: 'var(--border-hairline)', paddingBottom: 12 }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span className="label">Broadcast presence</span>
            <div className="task-create-row">
              <input
                value={actorName}
                onChange={(e) => setActorName(e.target.value)}
                placeholder="Your name / handle"
                aria-label="presence actor name"
                required
              />
              <input
                value={currentTask}
                onChange={(e) => setCurrentTask(e.target.value)}
                placeholder="Current task (optional)"
                aria-label="presence task"
              />
            </div>
            <div className="task-create-row">
              <input
                value={currentFile}
                onChange={(e) => setCurrentFile(e.target.value)}
                placeholder="Active file (optional)"
                aria-label="presence file"
              />
              <button type="submit" className="primary" disabled={busy || !actorName.trim()} style={{ whiteSpace: 'nowrap' }}>
                {busy ? 'Sending…' : 'Broadcast'}
              </button>
            </div>
            {checkInMsg && (
              <span className="mono small" style={{ color: checkInMsg.includes('failed') ? 'var(--error)' : 'var(--green-text)' }}>
                {checkInMsg}
              </span>
            )}
          </div>
        </form>
      )}

      {filtered.length === 0 ? (
        <div className="empty-placeholder">No active agents or developers match this filter.</div>
      ) : (
        <ul className="stream-list">
          {filtered.map((p) => {
            const isAi = p.actor_type !== 'human'
            return (
              <li key={p.id} className="presence-item">
                <div className={`presence-indicator-dot ${isAi ? 'ai' : 'human'}`} />
                <div className="presence-content">
                  <div className="presence-head">
                    <span>
                      <span className="presence-actor">{p.actor_name}</span>
                      <span className="presence-kind">{isAi ? 'Agent' : 'Human'}</span>
                    </span>
                    <span className="presence-time">{timeAgo(p.last_seen)}</span>
                  </div>
                  {p.current_task && <div className="presence-task">{p.current_task}</div>}
                  {p.current_file && <div className="presence-file">{p.current_file}</div>}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}

function timeAgo(iso) {
  const then = new Date(iso)
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000)
  if (secs < 60) return `${Math.floor(secs)}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}
