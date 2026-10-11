import React from 'react'

export default function Presence({ presence, agentFilter = 'all' }) {
  const filtered = presence.filter((p) => {
    if (agentFilter === 'all') return true
    if (agentFilter === 'human') return p.actor_type === 'human'
    if (agentFilter === 'claude') return /claude/i.test(p.actor_name)
    if (agentFilter === 'cursor') return /cursor/i.test(p.actor_name)
    if (agentFilter === 'codex') return /codex/i.test(p.actor_name)
    return true
  })

  return (
    <div className="card-panel">
      <div className="card-header">
        <div className="card-title-group">
          <span className="pulse-indicator live" style={{ width: 8, height: 8 }}>
            <span className="dot-core" style={{ background: 'var(--green)' }} />
          </span>
          <h3 className="card-title">Presence Feed</h3>
        </div>
        <span className="count-tag" style={{ color: 'var(--green)', borderColor: 'var(--green)' }}>LIVE</span>
      </div>

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
