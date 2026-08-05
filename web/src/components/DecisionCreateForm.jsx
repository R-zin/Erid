import React, { useState } from 'react'
import { ApiError } from '../api.js'

// Quick-create a decision in the active workspace, mirroring TaskCreateForm.
// The new decision is applied optimistically (the WebSocket `decision_created`
// event prepends the real, server-assigned record over it); on failure we roll
// back and surface the API error with a re-auth hint on 401/403. Optionally
// links the decision to an existing task (`decisions.task_id`).
export default function DecisionCreateForm({ client, disabled, tasks = [], onOptimistic, onRollback, onError }) {
  const [title, setTitle] = useState('')
  const [reason, setReason] = useState('')
  const [relatedFiles, setRelatedFiles] = useState('')
  const [madeBy, setMadeBy] = useState('')
  const [taskId, setTaskId] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || busy || disabled) return

    // Optimistic placeholder with a temporary id; replaced by the WS prepend.
    const tempId = `temp-${Date.now()}`
    const optimistic = {
      id: tempId,
      title: trimmed,
      reason: reason.trim() || null,
      related_files: relatedFiles.trim() || null,
      made_by: madeBy.trim() || null,
      task_id: taskId || null,
      created_at: new Date().toISOString(),
      __optimistic: true,
    }
    onOptimistic(optimistic)

    setBusy(true)
    try {
      await client.createDecision({
        title: trimmed,
        reason: reason.trim() || null,
        related_files: relatedFiles.trim() || null,
        made_by: madeBy.trim() || null,
        task_id: taskId || null,
      })
      // Real record arrives via the WebSocket; drop the placeholder.
      onRollback(tempId)
      setTitle('')
      setReason('')
      setRelatedFiles('')
      setMadeBy('')
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
    <form className="decision-create" onSubmit={submit}>
      <div className="task-create-row">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={disabled ? 'Connect a workspace to record decisions' : 'New decision…'}
          aria-label="new decision title"
          disabled={disabled}
          required
        />
        <button type="submit" disabled={disabled || busy || !title.trim()}>
          {busy ? 'Adding…' : 'Add'}
        </button>
      </div>

      {!disabled && (
        <>
          <button
            type="button"
            className="ghost small-toggle"
            onClick={() => setShowAdvanced((v) => !v)}
          >
            {showAdvanced ? '▾ fewer options' : '▸ reason / files / link'}
          </button>
          {showAdvanced && (
            <>
              <div className="task-create-row">
                <input
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="reason (optional)"
                  aria-label="decision reason"
                />
                <input
                  value={madeBy}
                  onChange={(e) => setMadeBy(e.target.value)}
                  placeholder="made by (optional)"
                  aria-label="made by"
                />
              </div>
              <div className="task-create-row">
                <input
                  value={relatedFiles}
                  onChange={(e) => setRelatedFiles(e.target.value)}
                  placeholder="related files (optional)"
                  aria-label="related files"
                />
                <select
                  value={taskId}
                  onChange={(e) => setTaskId(e.target.value)}
                  aria-label="link to task"
                >
                  <option value="">(no task)</option>
                  {tasks.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.title}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}
        </>
      )}
    </form>
  )
}

function describeError(err) {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
    return 'Permission denied creating decision — this workspace needs a credential with write access. Reconnect with a valid API key or token.'
  }
  return `Failed to create decision: ${err.message}`
}
