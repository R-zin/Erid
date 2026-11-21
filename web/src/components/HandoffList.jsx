import React, { useState } from 'react'
import HandoffCreateForm from './HandoffCreateForm.jsx'
import SectionHeader from './SectionHeader.jsx'

export default function HandoffList({ handoffs, client, canWrite, tasks = [], onMutate, agentFilter = 'all', index }) {
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
    <section className="card-panel" aria-label="Handoffs">
      <SectionHeader
        index={index}
        title="Handoffs"
        meta={
          pendingCount > 0 ? (
            <span className="action-required-badge">{pendingCount} Pending</span>
          ) : (
            <span className="count-tag">none pending</span>
          )
        }
      />

      <div className="card-body">
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
        <div className="empty-placeholder">No handoffs yet. Leave one when you wrap up an agent session.</div>
      ) : (
        <ul className="stream-list">
          {filtered.map((h) => (
            <li
              key={h.id}
              className={`stream-item${h.__optimistic ? ' optimistic' : ''}${h.status === 'open' ? ' open-handoff' : ''}`}
            >
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
                <div className="btn-row">
                  <span className={`badge ${h.status}`}>{h.status}</span>
                  {h.branch && <span className="agent-tag" style={{ color: 'var(--on-surface)' }}>⎇ {h.branch}</span>}
                </div>
                <span className="presence-time">
                  {h.created_at
                    ? new Date(h.created_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                    : 'now'}
                </span>
              </div>

              {(h.created_by || h.recipient) && (
                <div className="label" style={{ marginTop: 8 }}>
                  {h.created_by || 'someone'}
                  {h.recipient && <span className="accent-text"> → </span>}
                  {h.recipient}
                </div>
              )}

              <p style={{ margin: '6px 0 0', fontSize: 14, fontWeight: 500 }}>{h.summary}</p>

              {h.next_action && (
                <p className="handoff-next">
                  <span className="label">Next</span>
                  {h.next_action}
                </p>
              )}

              {h.blockers && <p className="handoff-blockers">Blocked: {h.blockers}</p>}

              {taskTitle(h.task_id) && (
                <div className="agent-tag" style={{ marginTop: 6 }}>↳ {taskTitle(h.task_id)}</div>
              )}

              {canWrite && client && !h.__optimistic && (
                <div className="btn-row" style={{ marginTop: 10 }}>
                  {h.status === 'open' && (
                    <button type="button" className="primary small" onClick={() => pickUp(h)}>
                      Pick up
                    </button>
                  )}
                  {h.status !== 'resolved' && (
                    <button type="button" className="ghost small" onClick={() => resolve(h)}>
                      Resolve
                    </button>
                  )}
                  <button
                    type="button"
                    className="ghost danger icon"
                    aria-label={`Delete handoff: ${h.summary}`}
                    onClick={() => remove(h)}
                  >
                    ✕
                  </button>
                </div>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}
