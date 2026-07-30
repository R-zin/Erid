import React, { useState } from 'react'
import TaskCreateForm from './TaskCreateForm.jsx'

const STATUS_ORDER = { in_progress: 0, blocked: 1, todo: 2, done: 3 }

export default function TaskList({ tasks, client, canWrite, onMutate }) {
  const [createError, setCreateError] = useState(null)
  const sorted = [...tasks].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  )

  const addOptimistic = (task) => {
    setCreateError(null)
    onMutate((prev) => [...prev, task])
  }
  const rollback = (tempId) => onMutate((prev) => prev.filter((t) => t.id !== tempId))

  return (
    <section className="card">
      <h2>Tasks ({tasks.filter((t) => t.status !== 'done').length} open)</h2>

      <TaskCreateForm
        client={client}
        disabled={!client}
        onOptimistic={addOptimistic}
        onRollback={rollback}
        onError={setCreateError}
      />
      {createError && <div className="error inline">{createError}</div>}
      {!canWrite && client && (
        <p className="muted small hint">
          Read-only credential — creating tasks may be rejected by the server.
        </p>
      )}

      {sorted.length === 0 && <p className="empty">No tasks yet.</p>}
      <ul>
        {sorted.map((t) => (
          <li key={t.id} className={`task ${t.status}${t.__optimistic ? ' optimistic' : ''}`}>
            <span className={`badge ${t.status}`}>{t.status.replace('_', ' ')}</span>
            <span className={t.status === 'done' ? 'done-title' : ''}>{t.title}</span>
            {t.assigned_to && <span className="muted"> @{t.assigned_to}</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}
