import React, { useState } from 'react'
import TaskCreateForm from './TaskCreateForm.jsx'
import { matchesAgentFilter } from '../utils/filter.js'

const STATUS_ORDER = { in_progress: 0, blocked: 1, todo: 2, done: 3 }
const STATUSES = ['todo', 'in_progress', 'blocked', 'done']

export default function TaskList({ tasks, client, canWrite, onMutate, agentFilter = 'all' }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)

  const filtered = tasks.filter((t) => matchesAgentFilter(t.assigned_to, agentFilter))

  const sorted = [...filtered].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  )

  const addOptimistic = (task) => {
    setCreateError(null)
    onMutate((prev) => [...prev, task])
  }
  const reconcile = (tempId, real) => {
    onMutate((prev) => {
      if (prev.some((t) => t.id === real.id)) {
        return prev.filter((t) => t.id !== tempId)
      }
      return prev.map((t) => (t.id === tempId ? real : t))
    })
  }
  const rollback = (tempId) => onMutate((prev) => prev.filter((t) => t.id !== tempId))

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
      onMutate((prev) => [...prev, task])
      setRowError(e.message)
    }
  }

  const openCount = tasks.filter((t) => t.status !== 'done').length

  return (
    <div className="card-panel">
      <div className="card-header">
        <div className="card-title-group">
          <h3 className="card-title">Active Tasks</h3>
          <span className="count-tag">
            {String(openCount).padStart(2, '0')} open
          </span>
        </div>
        <span className="material-symbols-outlined muted" style={{ fontSize: 18 }}>
          task_alt
        </span>
      </div>

      <div className="card-body" style={{ paddingBottom: 8 }}>
        <TaskCreateForm
          client={client}
          disabled={!client}
          onOptimistic={addOptimistic}
          onRollback={rollback}
          onReconcile={reconcile}
          onError={setCreateError}
        />
        {createError && <div className="error-banner inline">{createError}</div>}
        {!canWrite && client && (
          <p className="muted small" style={{ margin: '4px 0 10px' }}>
            Read-only credential — creating tasks may be rejected by the server.
          </p>
        )}
        {rowError && <div className="error-banner inline">{rowError}</div>}
      </div>

      {sorted.length === 0 ? (
        <div className="empty-placeholder" style={{ padding: '24px 16px' }}>
          No tasks found matching filter.
        </div>
      ) : (
        <ul className="stream-list">
          {sorted.map((t) => {
            const shortId = t.id ? String(t.id).slice(0, 6) : 'NEW'
            return (
              <li
                key={t.id}
                className={`stream-item${t.__optimistic ? ' optimistic' : ''}`}
              >
                <div className="task-top-meta">
                  <span className={`badge ${t.status}`}>
                    {t.status.replace('_', ' ')}
                  </span>
                  <span className="task-id">#TK-{shortId}</span>
                </div>

                <h4 className={`task-heading ${t.status === 'done' ? 'done' : ''}`}>
                  {t.title}
                </h4>

                <div className="task-bottom-meta">
                  <span className="agent-tag">
                    <span className="material-symbols-outlined" style={{ fontSize: 13, color: 'var(--surface-tint)' }}>
                      {t.assigned_to && /(claude|cursor|codex|agent)/i.test(t.assigned_to) ? 'smart_toy' : 'person'}
                    </span>
                    Agent: {t.assigned_to || 'Unassigned'}
                  </span>

                  {canWrite && client && !t.__optimistic && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      <select
                        aria-label={`Set status for ${t.title}`}
                        value={t.status}
                        onChange={(e) => changeStatus(t, e.target.value)}
                        style={{ padding: '3px 6px', fontSize: 11 }}
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
                        style={{ padding: '2px 6px', fontSize: 11 }}
                      >
                        ✕
                      </button>
                    </div>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
