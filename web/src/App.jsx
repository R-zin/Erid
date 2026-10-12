import React, { useEffect, useMemo, useState } from 'react'
import { useWorkspace } from './useWorkspace.js'
import { useWorkspaces } from './useWorkspaces.js'
import { makeClient } from './api.js'
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

  return (
    <div className="app-wrapper">
      {/* Top Header Bar matching Stitch */}
      <header className="top-header">
        <div className="top-header-inner">
          <div className="brand-group">
            <div className="brand-logo" onClick={() => setCurrentPage('workspace')}>
              erid<span className="brand-dot">.</span>
            </div>

            <div className="protocol-badge">
              <span className={`pulse-indicator ${connected ? 'live' : 'offline'}`}>
                <span className="dot-core" />
              </span>
              <span>Protocol v0.1 • {connected ? 'WS Active' : 'WS Disconnected'}</span>
            </div>
          </div>

          <nav className="top-nav">
            <button
              type="button"
              className={`nav-link ${currentPage === 'workspace' ? 'active' : ''}`}
              onClick={() => setCurrentPage('workspace')}
            >
              Live Workspace
            </button>
            <button
              type="button"
              className={`nav-link ${currentPage === 'continuous-context' ? 'active' : ''}`}
              onClick={() => setCurrentPage('continuous-context')}
            >
              Continuous Context
            </button>
            <button
              type="button"
              className={`nav-link ${currentPage === 'field-guide' ? 'active' : ''}`}
              onClick={() => setCurrentPage('field-guide')}
            >
              Clean Field Guide
            </button>
            <a
              className="nav-link"
              href="https://github.com/R-zin/Erid"
              target="_blank"
              rel="noreferrer"
            >
              GitHub
            </a>
          </nav>

          <div className="header-actions">
            <button
              type="button"
              className="primary"
              onClick={() => setCurrentPage('workspace')}
              style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '7px 12px', fontSize: 12 }}
            >
              <span>Connect Client</span>
              <span className="material-symbols-outlined" style={{ fontSize: 15 }}>arrow_forward</span>
            </button>
            <WorkspaceSwitcher
              workspaces={workspaces}
              active={active}
              activeSlug={activeSlug}
              onSelect={selectWorkspace}
              onSave={upsertWorkspace}
              onRemove={removeWorkspace}
            />
          </div>
        </div>
      </header>

      {/* Main Page Content */}
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
      </div>

      {/* Pinned Real-Time RPC Stream Ticker (Bottom Edge) */}
      <footer className="rpc-stream-footer">
        <div className="rpc-pill">
          <span className={`pulse-indicator ${connected ? 'live' : 'offline'}`} style={{ width: 6, height: 6 }}>
            <span className="dot-core" />
          </span>
          <span>RPC STREAM</span>
        </div>
        <div className="rpc-stream-content">
          {lastEvent ? (
            <span>
              <span className="rpc-key">{"{"}"event": </span>
              <span className="rpc-val">"{lastEvent.type}"</span>
              <span className="rpc-key">, "ts": </span>
              <span className="rpc-val">{Math.floor(lastEvent.ts / 1000)}</span>
              {lastEvent.data?.id && (
                <>
                  <span className="rpc-key">, "id": </span>
                  <span className="rpc-val">"{lastEvent.data.id}"</span>
                </>
              )}
              {lastEvent.data?.title && (
                <>
                  <span className="rpc-key">, "title": </span>
                  <span className="rpc-val">"{lastEvent.data.title}"</span>
                </>
              )}
              <span className="rpc-key">{"}"}</span>
            </span>
          ) : (
            <span>
              <span className="rpc-key">{"{"}"status": </span>
              <span className="rpc-val">"{connected ? 'listening_on_mesh' : 'awaiting_connection'}"</span>
              <span className="rpc-key">, "workspace": </span>
              <span className="rpc-val">"{slug || 'none'}"</span>
              <span className="rpc-key">, "transport": </span>
              <span className="rpc-val">"websocket_push"</span>
              <span className="rpc-key">{"}"}</span>
            </span>
          )}
        </div>
      </footer>
    </div>
  )
}
