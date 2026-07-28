import React from 'react'

export default function Presence({ presence }) {
  return (
    <section className="card">
      <h2>Live presence</h2>
      {presence.length === 0 && <p className="empty">No one is active right now.</p>}
      <ul>
        {presence.map((p) => (
          <li key={p.id} className="presence">
            <span className={`dot ${p.actor_type}`} />
            <div>
              <strong>{p.actor_name}</strong>
              <span className="muted"> {p.actor_type}</span>
              <div className="muted small">
                {p.current_task && <div>▸ {p.current_task}</div>}
                {p.current_file && <div className="file">{p.current_file}</div>}
                <div>{timeAgo(p.last_seen)}</div>
              </div>
            </div>
          </li>
        ))}
      </ul>
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
