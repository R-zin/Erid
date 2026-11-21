import React, { useState } from 'react'
import DecisionCreateForm from './DecisionCreateForm.jsx'
import SectionHeader from './SectionHeader.jsx'

export default function DecisionList({ decisions, client, canWrite, tasks = [], onMutate, agentFilter = 'all', index }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)
  const taskTitle = (id) => (id ? tasks.find((t) => t.id === id)?.title : null)

  const filtered = decisions.filter((d) => {
    if (agentFilter === 'all') return true
    if (!d.made_by) return false
    if (agentFilter === 'human') return !/(claude|cursor|codex|agent)/i.test(d.made_by)
    if (agentFilter === 'claude') return /claude/i.test(d.made_by)
    if (agentFilter === 'cursor') return /cursor/i.test(d.made_by)
    if (agentFilter === 'codex') return /codex/i.test(d.made_by)
    return true
  })

  const addOptimistic = (decision) => {
    setCreateError(null)
    onMutate?.((prev) => [decision, ...prev])
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
    <section className="card-panel" aria-label="Decisions">
      <SectionHeader
        index={index}
        title="Decisions"
        meta={<span className="count-tag">{String(decisions.length).padStart(2, '0')} recorded</span>}
      />

      <div className="card-body">
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
        {createError && <div className="error-banner inline">{createError}</div>}
        {!canWrite && client && (
          <p className="muted small" style={{ margin: '4px 0 10px' }}>
            Read-only credential — creating decisions may be rejected by the server.
          </p>
        )}
        {rowError && <div className="error-banner inline">{rowError}</div>}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-placeholder">No decisions recorded yet.</div>
      ) : (
        <ul className="stream-list">
          {filtered.map((d, index) => (
            <li key={d.id} className={`stream-item${d.__optimistic ? ' optimistic' : ''}`}>
              <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12 }}>
                <h3 className="row-title">
                  <span className="row-id">DEC-{String(d.id).slice(0, 4)}</span>
                  {d.title}
                </h3>
                <div className="btn-row" style={{ flex: 'none' }}>
                  <span className="agent-tag">
                    {d.made_by && <>by <strong style={{ color: 'var(--on-surface)' }}>{d.made_by}</strong> · </>}
                    {d.created_at
                      ? new Date(d.created_at).toLocaleDateString([], { month: 'short', day: 'numeric' })
                      : 'now'}
                  </span>
                  {canWrite && client && !d.__optimistic && (
                    <button
                      type="button"
                      className="ghost danger icon"
                      aria-label={`Delete ${d.title}`}
                      onClick={() => removeDecision(d, index)}
                    >
                      ✕
                    </button>
                  )}
                </div>
              </div>

              {d.reason && <p className="row-text">{d.reason}</p>}

              {(taskTitle(d.task_id) || d.related_files) && (
                <div className="btn-row" style={{ marginTop: 8 }}>
                  {taskTitle(d.task_id) && <span className="agent-tag">↳ {taskTitle(d.task_id)}</span>}
                  {d.related_files && <span className="agent-tag">{d.related_files}</span>}
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
