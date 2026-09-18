import React, { useState } from 'react'
import HandoffCreateForm from './HandoffCreateForm.jsx'

// Session handoffs: what each session left behind for the next one. Lifecycle
// actions (pick up / resolve / delete) are optimistic with rollback on failure,
// mirroring the decision/task lists.
export default function HandoffList({ handoffs, client, canWrite, tasks = [], onMutate }) {
  const [createError, setCreateError] = useState(null)
  const [rowError, setRowError] = useState(null)
  const taskTitle = (id) => (id ? tasks.find((t) => t.id === id)?.title : null)

  const addOptimistic = (handoff) => {
    setCreateError(null)
    onMutate?.((prev) => [handoff, ...prev])
  }
  const rollback = (tempId) => onMutate?.((prev) => prev.filter((h) => h.id !== tempId))

  // Apply a lifecycle action optimistically; restore the original on failure.
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

  return (
    <section className="card">
      <h2>Session handoffs</h2>

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
      {createError && <div className="error inline">{createError}</div>}
      {!canWrite && client && (
        <p className="muted small hint">Read-only credential — creating handoffs may be rejected by the server.</p>
      )}

      {rowError && <div className="error inline">{rowError}</div>}
      {handoffs.length === 0 && <p className="empty">No handoffs yet — leave one when you wrap up a session.</p>}
      <ul>
        {handoffs.map((h) => (
          <li key={h.id} className={`handoff${h.__optimistic ? ' optimistic' : ''}`}>
            <div className="decision-title">
              <span className={`handoff-status ${h.status}`}>{h.status}</span> {h.summary}
              {canWrite && client && !h.__optimistic && (
                <span className="row-actions">
                  {h.status === 'open' && (
                    <button type="button" className="ghost row-action" onClick={() => pickUp(h)}>
                      pick up
                    </button>
                  )}
                  {h.status !== 'resolved' && (
                    <button type="button" className="ghost row-action" onClick={() => resolve(h)}>
                      resolve
                    </button>
                  )}
                  <button
                    type="button"
                    className="ghost danger row-action"
                    aria-label={`Delete handoff: ${h.summary}`}
                    onClick={() => remove(h)}
                  >
                    ✕
                  </button>
                </span>
              )}
            </div>
            {h.next_action && <div className="small">▸ next: {h.next_action}</div>}
            {h.blockers && <div className="muted small">⚠ {h.blockers}</div>}
            <div className="muted small">
              {h.created_by && <span>by {h.created_by} · </span>}
              {h.branch && <span>⎇ {h.branch} · </span>}
              {taskTitle(h.task_id) && <span>↳ {taskTitle(h.task_id)} · </span>}
              {new Date(h.created_at).toLocaleString()}
            </div>
          </li>
        ))}
      </ul>
    </section>
  )
}
