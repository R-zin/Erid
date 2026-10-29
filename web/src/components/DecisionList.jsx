import React, { useState } from 'react'
import DecisionCreateForm from './DecisionCreateForm.jsx'
import { matchesAgentFilter } from '../utils/filter.js'

export default function DecisionList({ decisions, client, canWrite, tasks = [], onMutate, agentFilter = 'all' }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)
  const taskTitle = (id) => (id ? tasks.find((t) => t.id === id)?.title : null)

  const filtered = decisions.filter((d) => matchesAgentFilter(d.made_by, agentFilter))

  const addOptimistic = (decision) => {
    setCreateError(null)
    onMutate?.((prev) => [decision, ...prev])
  }
  const reconcile = (tempId, real) => {
    onMutate?.((prev) => {
      if (prev.some((d) => d.id === real.id)) {
        return prev.filter((d) => d.id !== tempId)
      }
      return prev.map((d) => (d.id === tempId ? real : d))
    })
  }
  const rollback = (tempId) => onMutate?.((prev) => prev.filter((d) => d.id !== tempId))

  const removeDecision = async (decision, index) => {
    setRowError(null)
    onMutate?.((prev) => prev.filter((d) => d.id !== decision.id))
    try {
      await client.deleteDecision(decision.id)
    } catch (e) {
      onMutate?.((prev) => {
        const next = prev.slice()
        next.splice(Math.min(index, next.length), 0, decision)
        return next
      })
      setRowError(e.message)
    }
  }

  return (
    <div className="card-panel">
      <div className="card-header">
        <div className="card-title-group">
          <h3 className="card-title">Recent Decisions</h3>
          <span className="count-tag">
            {String(decisions.length).padStart(2, '0')} logged
          </span>
        </div>
        <span className="material-symbols-outlined muted" style={{ fontSize: 18 }}>
          psychology
        </span>
      </div>

      <div className="card-body" style={{ paddingBottom: 8 }}>
        {onMutate && (
          <DecisionCreateForm
            client={client}
            disabled={!client}
            tasks={tasks}
            onOptimistic={addOptimistic}
            onRollback={rollback}
            onReconcile={reconcile}
            onError={setCreateError}
          />
        )}
        {createError && <div className="error-banner inline">{createError}</div>}
        {!canWrite && client && (
          <p className="muted small" style={{ margin: '4px 0 10px' }}>
            Read-only credential — creating decisions may be rejected by the server.
          </p>
        )}
        {rowError && <div className="error-banner inline">{rowError}</div>}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-placeholder" style={{ padding: '24px 16px' }}>
          No decisions recorded yet.
        </div>
      ) : (
        <ul className="stream-list">
          {filtered.map((d, index) => (
            <li
              key={d.id}
              className={`stream-item${d.__optimistic ? ' optimistic' : ''}`}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
                <h4 style={{ margin: 0, fontSize: 14, fontWeight: 600, color: 'var(--primary)' }}>
                  {d.title}
                </h4>
                {canWrite && client && !d.__optimistic && (
                  <button
                    type="button"
                    className="ghost danger"
                    aria-label={`Delete ${d.title}`}
                    onClick={() => removeDecision(d, index)}
                    style={{ padding: '2px 6px', fontSize: 11 }}
                  >
                    ✕
                  </button>
                )}
              </div>

              {d.reason && (
                <p style={{ margin: '4px 0', fontSize: 13, color: 'var(--on-surface-variant)', lineHeight: 1.4 }}>
                  {d.reason}
                </p>
              )}

              <div className="task-bottom-meta" style={{ marginTop: 6 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                  {d.made_by && (
                    <span className="agent-tag">
                      by {d.made_by}
                    </span>
                  )}
                  {taskTitle(d.task_id) && (
                    <span className="agent-tag">
                      ↳ {taskTitle(d.task_id)}
                    </span>
                  )}
                  {d.related_files && (
                    <span className="agent-tag" style={{ fontFamily: 'var(--font-mono)' }}>
                      📄 {d.related_files}
                    </span>
                  )}
                </div>

                <span>
                  {new Date(d.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })}
                </span>
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
