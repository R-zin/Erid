import React, { useState } from 'react'
import HandoffCreateForm from './HandoffCreateForm.jsx'

export default function HandoffList({ handoffs, client, canWrite, tasks = [], onMutate, agentFilter = 'all' }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)
  const taskTitle = (id) => (id ? tasks.find((t) => t.id === id)?.title : null)

  const filtered = handoffs.filter((h) => {
    if (agentFilter === 'all') return true
    if (!h.created_by) return false
    if (agentFilter === 'human') return !/(claude|cursor|codex|agent)/i.test(h.created_by)
    if (agentFilter === 'claude') return /claude/i.test(h.created_by)
    if (agentFilter === 'cursor') return /cursor/i.test(h.created_by)
    if (agentFilter === 'codex') return /codex/i.test(h.created_by)
    return true
  })

  const addOptimistic = (handoff) => {
    setCreateError(null)
    onMutate?.((prev) => [handoff, ...prev])
  }
  const rollback = (tempId) => onMutate?.((prev) => prev.filter((h) => h.id !== tempId))

  const act = async (handoff, patch, call) => {
    setRowError(null)
    onMutate?.((prev) => prev.map((h) => (h.id === handoff.id ? { ...handoff, ...patch } : h)))
    try {
      await call()
    } catch (e) {
      onMutate?.((prev) => prev.map((h) => (h.id === handoff.id ? handoff : h)))
      setRowError(e.message)
    }
  }

  const pickUp = (handoff) =>
    act(
      handoff,
      { status: 'acknowledged', acknowledged_at: new Date().toISOString() },
      () => client.acknowledgeHandoff(handoff.id),
    )

  const resolve = (handoff) =>
    act(handoff, { status: 'resolved', resolved_at: new Date().toISOString() }, () =>
      client.resolveHandoff(handoff.id),
    )

  const remove = (handoff) => {
    setRowError(null)
    onMutate?.((prev) => prev.filter((h) => h.id !== handoff.id))
    client
      .deleteHandoff(handoff.id)
      .catch((e) => {
        onMutate?.((prev) => {
          const next = prev.slice()
          next.splice(0, 0, handoff)
          return next
        })
        setRowError(e.message)
      })
  }

  const pendingCount = handoffs.filter((h) => h.status !== 'resolved').length

  return (
    <div className="card-panel">
      <div className="card-header">
        <div className="card-title-group">
          <span className="material-symbols-outlined" style={{ fontSize: 20, color: 'var(--secondary-container)' }}>
            swap_horiz
          </span>
          <h3 className="card-title">Session Handoffs</h3>
          {pendingCount > 0 && (
            <span className="action-required-badge">
              {pendingCount} Pending
            </span>
          )}
        </div>
        <span className="material-symbols-outlined muted" style={{ fontSize: 18 }}>
          history_toggle_off
        </span>
      </div>

      <div className="card-body" style={{ paddingBottom: 8 }}>
        {onMutate && (
          <HandoffCreateForm
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
            Read-only credential — creating handoffs may be rejected by the server.
          </p>
        )}
        {rowError && <div className="error-banner inline">{rowError}</div>}
      </div>

      {filtered.length === 0 ? (
        <div className="empty-placeholder" style={{ padding: '24px 16px' }}>
          No session handoffs yet. Leave one when you wrap up an agent session.
        </div>
      ) : (
        <ul className="stream-list">
          {filtered.map((h) => {
            const isOpen = h.status === 'open'
            return (
              <li
                key={h.id}
                className={`stream-item${h.__optimistic ? ' optimistic' : ''}`}
                style={{
                  background: isOpen ? 'rgba(253, 106, 73, 0.04)' : undefined,
                  borderLeft: isOpen ? '3px solid var(--secondary-container)' : undefined,
                }}
              >
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                    <span className={`badge ${h.status}`}>{h.status}</span>
                    {h.created_by && (
                      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--primary)', fontWeight: 600 }}>
                        {h.created_by}
                      </span>
                    )}
                  </div>
                  <span className="small muted">
                    {new Date(h.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                  </span>
                </div>

                <p style={{ margin: '0 0 6px 0', fontSize: 14, fontWeight: 500, color: 'var(--on-surface)' }}>
                  {h.summary}
                </p>

                {h.next_action && (
                  <div style={{ background: 'var(--surface)', padding: '6px 10px', borderRadius: 4, border: 'var(--border-hairline)', fontSize: 12, margin: '6px 0' }}>
                    <span style={{ color: 'var(--secondary)', fontWeight: 600 }}>Next action: </span>
                    {h.next_action}
                  </div>
                )}

                {h.blockers && (
                  <div style={{ color: 'var(--error)', fontSize: 12, margin: '4px 0', display: 'flex', alignItems: 'center', gap: 4 }}>
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }}>warning</span>
                    {h.blockers}
                  </div>
                )}

                <div className="task-bottom-meta" style={{ marginTop: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                    {h.branch && (
                      <span className="agent-tag">
                        ⎇ {h.branch}
                      </span>
                    )}
                    {taskTitle(h.task_id) && (
                      <span className="agent-tag">
                        ↳ {taskTitle(h.task_id)}
                      </span>
                    )}
                  </div>

                  {canWrite && client && !h.__optimistic && (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                      {h.status === 'open' && (
                        <button
                          type="button"
                          className="ghost"
                          onClick={() => pickUp(h)}
                          style={{ padding: '3px 8px', fontSize: 11, borderColor: 'var(--secondary-container)', color: 'var(--secondary)' }}
                        >
                          Acknowledge
                        </button>
                      )}
                      {h.status !== 'resolved' && (
                        <button
                          type="button"
                          className="ghost"
                          onClick={() => resolve(h)}
                          style={{ padding: '3px 8px', fontSize: 11, background: 'var(--primary-container)', color: 'var(--on-primary)' }}
                        >
                          Resolve
                        </button>
                      )}
                      <button
                        type="button"
                        className="ghost danger"
                        aria-label={`Delete handoff: ${h.summary}`}
                        onClick={() => remove(h)}
                        style={{ padding: '3px 6px', fontSize: 11 }}
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
