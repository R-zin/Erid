import React from 'react'

export default function DecisionList({ decisions }) {
  return (
    <section className="card">
      <h2>Recent decisions</h2>
      {decisions.length === 0 && <p className="empty">No decisions recorded yet.</p>}
      <ul>
        {decisions.map((d) => (
          <li key={d.id} className="decision">
            <div className="decision-title">{d.title}</div>
            {d.reason && <div className="muted small">{d.reason}</div>}
            <div className="muted small">
              {d.made_by && <span>by {d.made_by} · </span>}
              {new Date(d.created_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
