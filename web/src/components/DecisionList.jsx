import React, { useState } from 'react'
import DecisionCreateForm from './DecisionCreateForm.jsx'

export default function DecisionList({ decisions, client, canWrite, tasks = [], onMutate }) {
  const [createError, setCreateError] = useState(null)
  const taskTitle = (id) => (id ? tasks.find((t) => t.id === id)?.title : null)

  const addOptimistic = (decision) => {
    setCreateError(null)
    onMutate?.((prev) => [decision, ...prev])
  }
  const rollback = (tempId) => onMutate?.((prev) => prev.filter((d) => d.id !== tempId))

  return (
    <section className="card">
      <h2>Recent decisions</h2>

      {onMutate && (
        <DecisionCreateForm
          client={client}
          disabled={!client}
          tasks={tasks}
          onOptimistic={addOptimistic}
          onRollback={rollback}
          onError={setCreateError}
        />
      )}
      {createError && <div className="error inline">{createError}</div>}
      {!canWrite && client && (
        <p className="muted small hint">
          Read-only credential — creating decisions may be rejected by the server.
        </p>
      )}

      {decisions.length === 0 && <p className="empty">No decisions recorded yet.</p>}
      <ul>
        {decisions.map((d) => (
          <li key={d.id} className={`decision${d.__optimistic ? ' optimistic' : ''}`}>
            <div className="decision-title">{d.title}</div>
            {d.reason && <div className="muted small">{d.reason}</div>}
            <div className="muted small">
              {d.made_by && <span>by {d.made_by} · </span>}
              {taskTitle(d.task_id) && <span>↳ {taskTitle(d.task_id)} · </span>}
              {new Date(d.created_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
