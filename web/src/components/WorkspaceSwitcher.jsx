import React, { useEffect, useState } from 'react'

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
    <div style={{ position: 'relative' }}>
      <div className="switcher-row">
        <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span className="small muted" style={{ textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600, fontSize: 10 }}>
            Workspace
          </span>
          <select
            id="ws-select"
            value={activeSlug}
            onChange={(e) => onSelect(e.target.value)}
            aria-label="active workspace"
            style={{ fontWeight: 600, color: 'var(--primary)', padding: '5px 10px' }}
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
        </div>

        <button
          type="button"
          className="ghost"
          onClick={() => (editing ? setEditing(false) : setEditing(true))}
          style={{ padding: '5px 10px' }}
        >
          {editing ? 'Close' : active ? 'Edit' : 'Connect'}
        </button>
        <button
          type="button"
          className="ghost"
          onClick={openNew}
          style={{ padding: '5px 10px', color: 'var(--primary)' }}
        >
          + New
        </button>
        {active && (
          <button
            type="button"
            className="ghost danger"
            onClick={() => onRemove(active.slug)}
            title={`Remove ${active.slug}`}
            style={{ padding: '5px 8px' }}
          >
            ✕
          </button>
        )}
      </div>

      {editing && (
        <form className="switcher-form" onSubmit={submit}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 4 }}>
            <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--primary)' }}>
              {slug ? `Configure Workspace: ${slug}` : 'Add New Workspace'}
            </span>
            <button
              type="button"
              className="ghost"
              onClick={() => setEditing(false)}
              style={{ border: 'none', padding: '2px 6px', fontSize: 11 }}
            >
              ✕
            </button>
          </div>
          <div className="switcher-form-inputs">
            <input
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              placeholder="workspace slug (e.g. production-api)"
              aria-label="workspace slug"
              required
            />
            <input
              value={credential}
              onChange={(e) => setCredential(e.target.value)}
              placeholder={authType === 'token' ? 'bearer JWT (optional)' : 'API key (optional)'}
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
          </div>
          <div className="switcher-form-actions">
            <button type="button" className="ghost" onClick={() => setEditing(false)}>
              Cancel
            </button>
            <button type="submit" className="primary">
              Save &amp; Connect
            </button>
          </div>
        </form>
      )}
    </div>
  )
}
