import React, { useState } from 'react'
import { matchesAgentFilter } from '../utils/filter.js'

export default function Presence({ presence, agentFilter = 'all', client = null, canWrite = false }) {
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
      setCheckInMsg('Presence broadcasted!')
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

  const filtered = presence.filter((p) => matchesAgentFilter(p.actor_name, agentFilter, p.actor_type))

  return (
    <div className="card-panel">
      <div className="card-header">
        <div className="card-title-group">
          <span className="pulse-indicator live" style={{ width: 8, height: 8 }}>
            <span className="dot-core" style={{ background: 'var(--green)' }} />
          </span>
          <h3 className="card-title">Presence Feed</h3>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          {canWrite && client && (
            <button
              type="button"
              className="ghost"
              style={{ fontSize: 11, padding: '2px 8px' }}
              onClick={() => setShowCheckIn((v) => !v)}
            >
              {showCheckIn ? 'Close' : 'Check In'}
            </button>
          )}
          <span className="count-tag" style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>LIVE</span>
        </div>
      </div>

      {showCheckIn && (
        <form onSubmit={handleCheckIn} style={{ padding: '12px 16px', background: 'var(--surface-container-low)', borderBottom: 'var(--border-hairline)' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            <span style={{ fontSize: 11, fontWeight: 600, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', color: 'var(--on-surface-variant)' }}>
              Broadcast Presence Heartbeat
            </span>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={actorName}
                onChange={(e) => setActorName(e.target.value)}
                placeholder="Your Name / Handle"
                aria-label="presence actor name"
                required
                style={{ fontSize: 12, padding: '4px 8px' }}
              />
              <input
                value={currentTask}
                onChange={(e) => setCurrentTask(e.target.value)}
                placeholder="Current task (optional)"
                aria-label="presence task"
                style={{ fontSize: 12, padding: '4px 8px' }}
              />
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <input
                value={currentFile}
                onChange={(e) => setCurrentFile(e.target.value)}
                placeholder="Active file (optional)"
                aria-label="presence file"
                style={{ fontSize: 12, padding: '4px 8px' }}
              />
              <button type="submit" className="primary" disabled={busy || !actorName.trim()} style={{ fontSize: 11, whiteSpace: 'nowrap' }}>
                {busy ? 'Broadcasting…' : 'Broadcast'}
              </button>
            </div>
            {checkInMsg && (
              <span style={{ fontSize: 11, color: checkInMsg.includes('failed') ? 'var(--error)' : 'var(--green-text)', fontFamily: 'var(--font-mono)' }}>
                {checkInMsg}
              </span>
            )}
          </div>
        </form>
      )}

      <div className="card-body" style={{ padding: '12px 16px' }}>
        {filtered.length === 0 ? (
          <div className="empty-placeholder">No active agents or developers matching filter.</div>
        ) : (
          <ul className="stream-list">
            {filtered.map((p) => {
              const isAi = p.actor_type !== 'human'
              return (
                <li key={p.id} className="presence-item">
                  <div className={`presence-indicator-dot ${isAi ? 'ai' : 'human'}`} />
                  <div className="presence-content">
                    <div>
                      <span className="presence-actor">[{p.actor_name}]</span>
                      <span className="muted small"> ({p.actor_type})</span>
                    </div>
                    {p.current_task && (
                      <div className="presence-task">
                        <span className="muted">▸ </span>
                        {p.current_task}
                      </div>
                    )}
                    {p.current_file && (
                      <div className="presence-file">
                        📄 {p.current_file}
                      </div>
                    )}
                    <div className="presence-time">{timeAgo(p.last_seen)}</div>
                  </div>
                </li>
              )
            })}
          </ul>
        )}
      </div>

      <div style={{ padding: '8px 16px', background: 'var(--surface-low)', borderTop: 'var(--border-hairline)', textAlign: 'center' }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
          Heartbeat interval: 1500ms • Active Mesh
        </span>
      </div>
    </div>
  )
}

function timeAgo(iso) {
  const then = new Date(iso)
  const secs = Math.max(0, (Date.now() - then.getTime()) / 1000)
  if (secs < 60) return `${Math.floor(secs)}s ago`
  if (secs < 3600) return `${Math.floor(secs / 60)}m ago`
  return `${Math.floor(secs / 3600)}h ago`
}
