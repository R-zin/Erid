import React, { useState } from 'react'
import TaskCreateForm from './TaskCreateForm.jsx'

const STATUS_ORDER = { in_progress: 0, blocked: 1, todo: 2, done: 3 }
const STATUSES = ['todo', 'in_progress', 'blocked', 'done']

export default function TaskList({ tasks, client, canWrite, onMutate }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)
  const sorted = [...tasks].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  )

  const addOptimistic = (task) => {
    setCreateError(null)
    onMutate((prev) => [...prev, task])
  }
  const rollback = (tempId) => onMutate((prev) => prev.filter((t) => t.id !== tempId))

  // Optimistic per-row mutations; the WS event reconciles the real record.
  const changeStatus = async (task, status) => {
    setRowError(null)
    const before = task
    onMutate((prev) => prev.map((t) => (t.id === task.id ? { ...t, status } : t)))
    try {
      await client.updateTask(task.id, { status })
    } catch (e) {
      onMutate((prev) => prev.map((t) => (t.id === before.id ? before : t)))
      setRowError(e.message)
    }
  }

  const removeTask = async (task) => {
    setRowError(null)
    onMutate((prev) => prev.filter((t) => t.id !== task.id))
    try {
      await client.deleteTask(task.id)
    } catch (e) {
      onMutate((prev) => [...prev, task]) // sorted render re-seats it
      setRowError(e.message)
    }
  }

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

      {rowError && <div className="error inline">{rowError}</div>}
      {sorted.length === 0 && <p className="empty">No tasks yet.</p>}
      <ul>
        {sorted.map((t) => (
          <li key={t.id} className={`task ${t.status}${t.__optimistic ? ' optimistic' : ''}`}>
            <span className={`badge ${t.status}`}>{t.status.replace('_', ' ')}</span>
            <span className={t.status === 'done' ? 'done-title' : ''}>{t.title}</span>
            {t.assigned_to && <span className="muted"> @{t.assigned_to}</span>}
            {canWrite && client && !t.__optimistic && (
              <span className="row-actions">
                <select
                  aria-label={`Set status for ${t.title}`}
                  value={t.status}
                  onChange={(e) => changeStatus(t, e.target.value)}
                >
                  {STATUSES.map((s) => (
                    <option key={s} value={s}>
                      {s.replace('_', ' ')}
                    </option>
                  ))}
                </select>
                <button
                  type="button"
                  className="ghost danger"
                  aria-label={`Delete ${t.title}`}
                  onClick={() => removeTask(t)}
                >
                  ✕
                </button>
              </span>
            )}
          </li>
        ))}
      </ul>
    </section>
  )
}
