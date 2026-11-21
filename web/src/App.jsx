import React, { useEffect, useMemo, useState } from 'react'
import { useWorkspace } from './useWorkspace.js'
import { useWorkspaces } from './useWorkspaces.js'
import { makeClient } from './api.js'
import { useTheme } from './useTheme.js'
import WorkspaceSwitcher from './components/WorkspaceSwitcher.jsx'
import LiveWorkspace from './pages/LiveWorkspace.jsx'
import ContinuousContext from './pages/ContinuousContext.jsx'
import CleanFieldGuide from './pages/CleanFieldGuide.jsx'

export default function App() {
  const {
    workspaces,
    active,
    activeSlug,
    upsertWorkspace,
    removeWorkspace,
    selectWorkspace,
  } = useWorkspaces()

  const { theme, toggle: toggleTheme } = useTheme()

  // Default page: 'workspace' (can switch to 'continuous-context' | 'field-guide')
  const [currentPage, setCurrentPage] = useState('workspace')

  // OAuth callback capture: after social login the API redirects back to
  // `#/oauth/callback?token=…&slug=…&name=…`. Persist the minted JWT as the
  // workspace's `token` credential (the same slot the dashboard already uses)
  // and strip the fragment so the token doesn't linger in the address bar.
  useEffect(() => {
    const hash = window.location.hash
    if (!hash.startsWith('#/oauth/callback')) return
    const params = new URLSearchParams(hash.slice(hash.indexOf('?') + 1))
    const token = params.get('token')
    const slugParam = params.get('slug')
    if (token && slugParam) {
      upsertWorkspace({ slug: slugParam, credential: token, authType: 'token' })
    }
    window.history.replaceState(null, '', window.location.pathname + window.location.search)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const credential = active?.credential || ''
  const authType = active?.authType || 'key'
  const slug = active?.slug || ''

  const {
    summary,
    tasks,
    decisions,
    handoffs,
    presence,
    lastEvent,
    connected,
    error,
    setTasks,
    setDecisions,
    setHandoffs,
  } = useWorkspace(slug, credential, authType)

  // A client bound to the active workspace for mutations (task create). Null
  // until a workspace is selected so the form can disable itself.
  const client = useMemo(
    () => (slug ? makeClient({ slug, credential, authType }) : null),
    [slug, credential, authType],
  )

  const isAuthError = !!error && /authentication failed/i.test(error)

  const PAGES = [
    { id: 'workspace', label: 'Workspace' },
    { id: 'continuous-context', label: 'Continuous Context' },
    { id: 'field-guide', label: 'Field Guide' },
  ]

  return (
    <div className="app-wrapper">
      <header className="top-header">
        <div className="top-header-inner">
          <div className="brand-group">
            <button
              type="button"
              className="brand-logo"
              onClick={() => setCurrentPage('workspace')}
              aria-label="Erid home"
            >
              Erid<span className="brand-dot">.</span>
            </button>
            <span className="brand-slash" aria-hidden="true">/</span>
            <span className="live-pill" title={connected ? 'WebSocket connected' : 'WebSocket disconnected'}>
              <span className={`pulse-indicator ${connected ? 'live' : 'offline'}`}>
                <span className="dot-core" />
              </span>
              {connected ? 'Live' : 'Offline'}
            </span>
          </div>

          <nav className="top-nav" aria-label="Primary">
            {PAGES.map((p) => (
              <button
                key={p.id}
                type="button"
                className={`nav-link ${currentPage === p.id ? 'active' : ''}`}
                aria-current={currentPage === p.id ? 'page' : undefined}
                onClick={() => setCurrentPage(p.id)}
              >
                {p.label}
              </button>
            ))}
            <a className="nav-link" href="https://github.com/R-zin/Erid" target="_blank" rel="noreferrer">
              GitHub
            </a>
          </nav>

          <div className="header-actions">
            <WorkspaceSwitcher
              workspaces={workspaces}
              active={active}
              activeSlug={activeSlug}
              onSelect={selectWorkspace}
              onSave={upsertWorkspace}
              onRemove={removeWorkspace}
            />
            <ThemeToggle theme={theme} onToggle={toggleTheme} />
          </div>
        </div>
      </header>

      <div style={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {currentPage === 'workspace' && (
          <LiveWorkspace
            slug={slug}
            summary={summary}
            tasks={tasks}
            decisions={decisions}
            handoffs={handoffs}
            presence={presence}
            client={client}
            credential={credential}
            authType={authType}
            error={error}
            isAuthError={isAuthError}
            activeSlug={activeSlug}
            setTasks={setTasks}
            setDecisions={setDecisions}
            setHandoffs={setHandoffs}
          />
        )}

        {currentPage === 'continuous-context' && (
          <ContinuousContext onNavigateWorkspace={() => setCurrentPage('workspace')} />
        )}

        {currentPage === 'field-guide' && (
          <CleanFieldGuide onNavigateWorkspace={() => setCurrentPage('workspace')} />
        )}

        <footer className="site-footer">
          <span>Erid · Shared context for AI coding tools</span>
          <nav aria-label="Footer">
            <a href="https://github.com/R-zin/Erid#readme" target="_blank" rel="noreferrer">Docs</a>
            <a href="https://github.com/R-zin/Erid/blob/main/api/openapi.json" target="_blank" rel="noreferrer">API (OpenAPI)</a>
            <a href="https://github.com/R-zin/Erid" target="_blank" rel="noreferrer">GitHub</a>
          </nav>
        </footer>
      </div>

      <EventStream connected={connected} lastEvent={lastEvent} slug={slug} />
    </div>
  )
}

function ThemeToggle({ theme, onToggle }) {
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      className="theme-toggle"
      onClick={onToggle}
      aria-label={`Switch to ${next} mode`}
      title={`Switch to ${next} mode`}
    >
      <span className="material-symbols-outlined" style={{ fontSize: 18 }} aria-hidden="true">
        {theme === 'dark' ? 'light_mode' : 'dark_mode'}
      </span>
    </button>
  )
}

function EventStream({ connected, lastEvent, slug }) {
  const time = (ts) => new Date(ts).toLocaleTimeString([], { hour12: false })
  const subject = (e) => e.data?.title || e.data?.summary || e.data?.actor_name || e.data?.slug || ''
  return (
    <footer className="rpc-stream-footer" aria-live="polite">
      <div className="rpc-pill">
        <span className={`pulse-indicator ${connected ? 'live' : 'offline'}`} style={{ width: 6, height: 6 }}>
          <span className="dot-core" />
        </span>
        <span>Event stream</span>
      </div>
      <div className="rpc-stream-content">
        {lastEvent ? (
          <span>
            <span className="rpc-time">[{time(lastEvent.ts)}]</span>{' '}
            <span className="rpc-type">{lastEvent.type}</span>
            {subject(lastEvent) && <span>: &ldquo;{subject(lastEvent)}&rdquo;</span>}
          </span>
        ) : (
          <span className="rpc-key">
            {!slug ? 'No workspace selected' : connected ? `Listening on ${slug}…` : 'Waiting for connection…'}
          </span>
        )}
      </div>
      {lastEvent?.seq != null && <span className="rpc-seq">seq {lastEvent.seq}</span>}
    </footer>
  )
}
