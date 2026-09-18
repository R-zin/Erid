import React, { useState } from 'react'
import { ApiError } from '../api.js'

// Leave a session handoff in the active workspace. Only `summary` is required;
// the rest (next action, blockers, branch, linked task) folds out under the
// toggle so the common case stays one field. The new handoff is applied
// optimistically and replaced by the WebSocket `handoff_created` event.
export default function HandoffCreateForm({ client, disabled, tasks = [], onOptimistic, onRollback, onError }) {
  const [summary, setSummary] = useState('')
  const [nextAction, setNextAction] = useState('')
  const [blockers, setBlockers] = useState('')
  const [branch, setBranch] = useState('')
  const [taskId, setTaskId] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const trimmed = summary.trim()
    if (!trimmed || busy || disabled) return

    const tempId = `temp-${Date.now()}`
    const optimistic = {
      id: tempId,
      summary: trimmed,
      next_action: nextAction.trim() || null,
      blockers: blockers.trim() || null,
      branch: branch.trim() || null,
      task_id: taskId || null,
      status: 'open',
      created_by: null,
      created_at: new Date().toISOString(),
      __optimistic: true,
    }
    onOptimistic(optimistic)

    setBusy(true)
    try {
      await client.createHandoff({
        summary: trimmed,
        next_action: nextAction.trim() || null,
        blockers: blockers.trim() || null,
        branch: branch.trim() || null,
        task_id: taskId || null,
      })
      onRollback(tempId) // real record arrives via the WebSocket
      setSummary('')
      setNextAction('')
      setBlockers('')
      setBranch('')
      setTaskId('')
      setShowAdvanced(false)
    } catch (err) {
      onRollback(tempId)
      onError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="handoff-create" onSubmit={submit}>
      <div className="task-create-row">
        <input
          value={summary}
          onChange={(e) => setSummary(e.target.value)}
          placeholder={disabled ? 'Connect a workspace to leave a handoff' : 'Hand off your session: what did you do?'}
          aria-label="handoff summary"
          disabled={disabled}
          required
        />
        <button type="submit" disabled={disabled || busy || !summary.trim()}>
          {busy ? 'Handing off…' : 'Hand off'}
        </button>
      </div>

      {!disabled && (
        <>
          <button type="button" className="ghost small-toggle" onClick={() => setShowAdvanced((v) => !v)}>
            {showAdvanced ? '▾ fewer options' : '▸ next action / blockers / branch / task'}
          </button>
          {showAdvanced && (
            <div className="task-create-row">
              <input
                value={nextAction}
                onChange={(e) => setNextAction(e.target.value)}
                placeholder="recommended next action (optional)"
                aria-label="next action"
              />
              <input
                value={blockers}
                onChange={(e) => setBlockers(e.target.value)}
                placeholder="blockers / risks (optional)"
                aria-label="blockers"
              />
              <input
                value={branch}
                onChange={(e) => setBranch(e.target.value)}
                placeholder="branch (optional)"
                aria-label="branch"
              />
              <select value={taskId} onChange={(e) => setTaskId(e.target.value)} aria-label="linked task">
                <option value="">no task</option>
                {tasks.map((t) => (
                  <option key={t.id} value={t.id}>
                    {t.title}
                  </option>
                ))}
              </select>
            </div>
          )}
        </>
      )}
    </form>
  )
}

function describeError(err) {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
    return 'Permission denied creating handoff — this workspace needs a credential with write access. Reconnect with a valid API key or token.'
  }
  return `Failed to create handoff: ${err.message}`
}
