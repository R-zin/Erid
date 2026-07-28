import React from 'react'

const STATUS_ORDER = { in_progress: 0, blocked: 1, todo: 2, done: 3 }

export default function TaskList({ tasks }) {
  const sorted = [...tasks].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  )
  return (
    <section className="card">
      <h2>Tasks ({tasks.filter((t) => t.status !== 'done').length} open)</h2>
      {sorted.length === 0 && <p className="empty">No tasks yet.</p>}
      <ul>
        {sorted.map((t) => (
          <li key={t.id} className={`task ${t.status}`}>
            <span className={`badge ${t.status}`}>{t.status.replace('_', ' ')}</span>
            <span className={t.status === 'done' ? 'done-title' : ''}>{t.title}</span>
            {t.assigned_to && <span className="muted"> @{t.assigned_to}</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}
