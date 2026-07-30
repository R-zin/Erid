import React, { useEffect, useState } from 'react'

// Workspace picker + auth. The active workspace is chosen from a dropdown;
// "edit" reveals a form to add a new workspace or update the active one's
// credential. The credential may be an API key (`X-API-Key`) or a bearer JWT.
export default function WorkspaceSwitcher({
  workspaces,
  active,
  activeSlug,
  onSelect,
  onSave,
  onRemove,
}) {
  const [editing, setEditing] = useState(false)
  const [slug, setSlug] = useState('')
  const [credential, setCredential] = useState('')
  const [authType, setAuthType] = useState('key')

  // Populate the form from the active workspace whenever it changes or we
  // open the editor.
  useEffect(() => {
    if (!editing) return
    setSlug(active?.slug || '')
    setCredential(active?.credential || '')
    setAuthType(active?.authType || 'key')
  }, [editing, active])

  const openNew = () => {
    setSlug('')
    setCredential('')
    setAuthType('key')
    setEditing(true)
  }

  const submit = (e) => {
    e.preventDefault()
    if (!slug.trim()) return
    onSave({ slug: slug.trim(), credential: credential.trim(), authType })
    setEditing(false)
  }

  return (
    <div className="switcher">
      <div className="switcher-row">
        <label className="muted small" htmlFor="ws-select">
          Workspace
        </label>
        <select
          id="ws-select"
          value={activeSlug}
          onChange={(e) => onSelect(e.target.value)}
          aria-label="active workspace"
        >
          {workspaces.length === 0 && <option value="">— none saved —</option>}
          {activeSlug === '' && workspaces.length > 0 && <option value="">— select —</option>}
          {workspaces.map((w) => (
            <option key={w.slug} value={w.slug}>
              {w.slug}
              {w.credential ? '' : ' (no credential)'}
            </option>
          ))}
        </select>
        <button type="button" className="ghost" onClick={() => (editing ? setEditing(false) : setEditing(true))}>
          {editing ? 'Close' : active ? 'Edit' : 'Connect'}
        </button>
        <button type="button" className="ghost" onClick={openNew}>
          + New
        </button>
        {active && (
          <button
            type="button"
            className="ghost danger"
            onClick={() => onRemove(active.slug)}
            title={`Remove ${active.slug}`}
          >
            Remove
          </button>
        )}
      </div>

      {editing && (
        <form className="switcher-form" onSubmit={submit}>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="workspace slug"
            aria-label="workspace slug"
            required
          />
          <input
            value={credential}
            onChange={(e) => setCredential(e.target.value)}
            placeholder={authType === 'token' ? 'bearer JWT (optional)' : 'api key (optional)'}
            aria-label="credential"
            type="password"
          />
          <select
            value={authType}
            onChange={(e) => setAuthType(e.target.value)}
            aria-label="credential type"
            title="How the credential is sent"
          >
            <option value="key">API key (X-API-Key)</option>
            <option value="token">Bearer JWT</option>
          </select>
          <button type="submit">Save &amp; connect</button>
        </form>
      )}
    </div>
  )
}
