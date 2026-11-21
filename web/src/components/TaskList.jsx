import React, { useState } from 'react'
import TaskCreateForm from './TaskCreateForm.jsx'
import SectionHeader from './SectionHeader.jsx'

const STATUS_ORDER = { in_progress: 0, blocked: 1, todo: 2, done: 3 }
const STATUSES = ['todo', 'in_progress', 'blocked', 'done']

export default function TaskList({ tasks, client, canWrite, onMutate, agentFilter = 'all', index }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)

  const filtered = tasks.filter((t) => {
    if (agentFilter === 'all') return true
    if (!t.assigned_to) return false
    if (agentFilter === 'human') return !/(claude|cursor|codex|agent|bot)/i.test(t.assigned_to)
    if (agentFilter === 'claude') return /claude/i.test(t.assigned_to)
    if (agentFilter === 'cursor') return /cursor/i.test(t.assigned_to)
    if (agentFilter === 'codex') return /codex/i.test(t.assigned_to)
    return true
  })

  const sorted = [...filtered].sort(
    (a, b) => (STATUS_ORDER[a.status] ?? 9) - (STATUS_ORDER[b.status] ?? 9),
  )

  const addOptimistic = (task) => {
    setCreateError(null)
    onMutate((prev) => [...prev, task])
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
    <section className="card-panel" aria-label="Tasks">
      <SectionHeader
        index={index}
        title="Tasks"
        meta={<span className="count-tag">{String(openCount).padStart(2, '0')} open</span>}
      />

      <div className="card-body">
        <TaskCreateForm
          client={client}
          disabled={!client}
          onOptimistic={addOptimistic}
          onRollback={rollback}
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
        <div className="empty-placeholder">No tasks match this filter.</div>
      ) : (
        <ul className="stream-list">
          {sorted.map((t) => {
            const shortId = t.id ? String(t.id).slice(0, 6) : 'NEW'
            return (
              <li key={t.id} className={`stream-item${t.__optimistic ? ' optimistic' : ''}`}>
                <div className="task-row">
                  <span>
                    <span className={`badge ${t.status}`}>{t.status.replace('_', ' ')}</span>
                  </span>
                  <span className="task-id">TK-{shortId}</span>
                  <h3 className={`task-heading ${t.status === 'done' ? 'done' : ''}`}>{t.title}</h3>
                  <div className="task-row-actions">
                    <span className="task-assignee">{t.assigned_to ? `@${t.assigned_to}` : 'unassigned'}</span>
                    {canWrite && client && !t.__optimistic && (
                      <>
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
                          className="ghost danger icon"
                          aria-label={`Delete ${t.title}`}
                          onClick={() => removeTask(t)}
                        >
                          ✕
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
