import React, { useState } from 'react'
import { ApiError } from '../api.js'

const STATUSES = ['todo', 'in_progress', 'blocked', 'done']

// Quick-create a task in the active workspace. The new task is applied
// optimistically (the WebSocket `task_created` event will upsert the real,
// server-assigned record over it); on failure we roll back and surface the API
// error with a re-auth hint on 401/403.
export default function TaskCreateForm({ client, disabled, onOptimistic, onRollback, onError }) {
  const [title, setTitle] = useState('')
  const [status, setStatus] = useState('todo')
  const [assignedTo, setAssignedTo] = useState('')
  const [showAdvanced, setShowAdvanced] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    const trimmed = title.trim()
    if (!trimmed || busy || disabled) return

    // Optimistic placeholder with a temporary id; replaced by the WS upsert.
    const tempId = `temp-${Date.now()}`
    const optimistic = {
      id: tempId,
      title: trimmed,
      status,
      assigned_to: assignedTo.trim() || null,
      created_by: null,
      created_at: new Date().toISOString(),
      updated_at: null,
      __optimistic: true,
    }
    onOptimistic(optimistic)

    setBusy(true)
    try {
      await client.createTask({
        title: trimmed,
        status,
        assigned_to: assignedTo.trim() || null,
      })
      // Real record arrives via the WebSocket; drop the placeholder.
      onRollback(tempId)
      setTitle('')
      setAssignedTo('')
      setStatus('todo')
      setShowAdvanced(false)
    } catch (err) {
      onRollback(tempId)
      onError(describeError(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="task-create" onSubmit={submit}>
      <div className="task-create-row">
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder={disabled ? 'Connect a workspace to add tasks' : 'New task title…'}
          aria-label="new task title"
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
            {showAdvanced ? '▾ fewer options' : '▸ status / assignee'}
          </button>
          {showAdvanced && (
            <div className="task-create-row">
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                aria-label="task status"
              >
                {STATUSES.map((s) => (
                  <option key={s} value={s}>
                    {s.replace('_', ' ')}
                  </option>
                ))}
              </select>
              <input
                value={assignedTo}
                onChange={(e) => setAssignedTo(e.target.value)}
                placeholder="assignee (optional)"
                aria-label="assignee"
              />
            </div>
          )}
        </>
      )}
    </form>
  )
}

function describeError(err) {
  if (err instanceof ApiError && (err.status === 401 || err.status === 403)) {
    return 'Permission denied creating task — this workspace needs a credential with write access. Reconnect with a valid API key or token.'
  }
  return `Failed to create task: ${err.message}`
}
