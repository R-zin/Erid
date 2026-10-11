import React, { useEffect, useMemo, useState } from 'react'
import { useWorkspace } from './useWorkspace.js'
import { useWorkspaces } from './useWorkspaces.js'
import { makeClient } from './api.js'
import Presence from './components/Presence.jsx'
import TaskList from './components/TaskList.jsx'
import DecisionList from './components/DecisionList.jsx'
import HandoffList from './components/HandoffList.jsx'
import WorkspaceSwitcher from './components/WorkspaceSwitcher.jsx'
import OAuthLogin from './components/OAuthLogin.jsx'

export default function App() {
  const {
    workspaces,
    active,
    activeSlug,
    upsertWorkspace,
    removeWorkspace,
    selectWorkspace,
  } = useWorkspaces()

  const [agentFilter, setAgentFilter] = useState('all')
  const [activeModal, setActiveModal] = useState(null) // 'context' | 'guide' | null

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

  const openTasksCount = summary?.open_task_count ?? tasks.filter((t) => t.status !== 'done').length
  const pendingHandoffsCount = summary?.open_handoff_count ?? handoffs.filter((h) => h.status !== 'resolved').length
  const activeCollabsCount = summary?.active_developers?.length ?? presence.length
  const decisionsCount = summary?.decision_count ?? decisions.length

  return (
    <div className="app-wrapper">
      {/* Top Header Bar */}
      <header className="top-header">
        <div className="top-header-inner">
          <div className="brand-group">
            <div className="brand-logo" onClick={() => setActiveModal(null)}>
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
              className={`nav-link ${activeModal === null ? 'active' : ''}`}
              onClick={() => setActiveModal(null)}
            >
              Live Workspace
            </button>
            <button
              type="button"
              className={`nav-link ${activeModal === 'context' ? 'active' : ''}`}
              onClick={() => setActiveModal('context')}
            >
              Continuous Context
            </button>
            <button
              type="button"
              className={`nav-link ${activeModal === 'guide' ? 'active' : ''}`}
              onClick={() => setActiveModal('guide')}
            >
              Field Guide
            </button>
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
          </div>
        </div>
      </header>

      {/* Subheader / Control Band */}
      <section className="sub-header-band">
        <div className="sub-header-inner">
          <div className="control-left">
            <div className="switcher-pill">
              <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--on-surface-variant)', textTransform: 'uppercase' }}>
                Workspace:
              </span>
              <span style={{ fontWeight: 600, color: 'var(--primary)', fontFamily: 'var(--font-sans)' }}>
                {slug || 'None selected'}
              </span>
            </div>

            <div className="kpi-pills-row">
              <div className="kpi-pill">
                <span className="pill-dot primary" />
                <span>{openTasksCount} Open Tasks</span>
              </div>
              <div className="kpi-pill accent">
                <span className="pill-dot accent" style={{ animation: 'pulse-ring 2s infinite' }} />
                <span>{pendingHandoffsCount} Pending Handoff</span>
              </div>
              <div className="kpi-pill">
                <span className="pill-dot green" />
                <span>{activeCollabsCount} Active Collaborators</span>
              </div>
              <div className="kpi-pill">
                <span className="pill-dot tint" />
                <span>{decisionsCount} Decisions</span>
              </div>
            </div>
          </div>

          {/* Agent Filter Toggles */}
          <div className="filter-pills-row">
            {[
              { id: 'all', label: 'All agents' },
              { id: 'claude', label: 'Claude Code' },
              { id: 'cursor', label: 'Cursor IDE' },
              { id: 'codex', label: 'Codex' },
              { id: 'human', label: 'Human' },
            ].map((f) => (
              <button
                key={f.id}
                type="button"
                className={`filter-btn ${agentFilter === f.id ? 'active' : ''}`}
                onClick={() => setAgentFilter(f.id)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>
      </section>

      {/* Main Board Stage */}
      <main className="main-stage">
        {!slug && (
          <div className="error-banner" style={{ background: 'var(--surface-container)', color: 'var(--on-surface)', borderColor: 'var(--outline-variant)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span className="material-symbols-outlined" style={{ color: 'var(--secondary-container)' }}>info</span>
              <strong>No workspace selected</strong>
            </div>
            <p style={{ margin: '4px 0 8px', color: 'var(--on-surface-variant)' }}>
              Add a workspace with <strong>+ New</strong> in the top bar to get started, or sign in with your provider.
            </p>
            <OAuthLogin slug={activeSlug || 'default'} />
          </div>
        )}

        {error && slug && (
          <div className="error-banner">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span className="material-symbols-outlined">warning</span>
              <strong>Error: {error}</strong>
            </div>
            {isAuthError && (
              <div className="small" style={{ marginTop: 6 }}>
                Open <strong>Edit</strong> in the workspace selector above to update the credential for this workspace.
              </div>
            )}
          </div>
        )}

        {/* 3-Column Split Board */}
        <div className="board-grid">
          {/* Column 1: Active Tasks */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <TaskList
              tasks={tasks}
              client={client}
              canWrite={!!credential}
              onMutate={setTasks}
              agentFilter={agentFilter}
            />
          </div>

          {/* Column 2: Session Handoffs & Decisions */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
            <HandoffList
              handoffs={handoffs}
              client={client}
              canWrite={!!credential}
              tasks={tasks}
              onMutate={setHandoffs}
              agentFilter={agentFilter}
            />

            <DecisionList
              decisions={decisions}
              client={client}
              canWrite={!!credential}
              tasks={tasks}
              onMutate={setDecisions}
              agentFilter={agentFilter}
            />
          </div>

          {/* Column 3: Live Presence & Context Footprint */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
            <Presence presence={presence} agentFilter={agentFilter} />

            {/* Context Memory Footprint Box */}
            <div className="memory-footprint-box">
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', color: 'var(--on-surface-variant)', letterSpacing: '0.04em' }}>
                  Context Footprint
                </span>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--primary)', fontWeight: 600 }}>
                  {slug ? `${tasks.length + decisions.length + handoffs.length} state items` : 'idle'}
                </span>
              </div>
              <div className="memory-bar-track">
                <div
                  className="memory-bar-fill"
                  style={{ width: slug ? `${Math.min(100, Math.max(15, (tasks.length + decisions.length) * 10))}%` : '5%' }}
                />
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--on-surface-variant)', fontFamily: 'var(--font-mono)' }}>
                <span>Sync: WebSocket feed</span>
                <span>Eviction: LRU-window</span>
              </div>
            </div>
          </div>
        </div>
      </main>

      {/* RPC Stream Ticker (Bottom Edge) */}
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

      {/* Modals for Field Guide & Continuous Context */}
      {activeModal && (
        <div className="modal-overlay" onClick={() => setActiveModal(null)}>
          <div className="modal-card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2 style={{ margin: 0, fontFamily: 'var(--font-serif)', fontSize: 22, color: 'var(--primary)' }}>
                {activeModal === 'context' ? 'Erid: Continuous Context' : 'The Clean Field Guide'}
              </h2>
              <button
                type="button"
                className="ghost"
                onClick={() => setActiveModal(null)}
                style={{ padding: '4px 8px' }}
              >
                ✕
              </button>
            </div>

            {activeModal === 'context' ? (
              <div style={{ lineHeight: 1.6, color: 'var(--on-surface-variant)' }}>
                <p>
                  <strong>Claude Code, Cursor, and Codex CLI</strong> all read from and write to the same project state — tasks, decisions, and who's-working-on-what — instead of every session starting from zero.
                </p>
                <div style={{ background: 'var(--surface-container)', padding: 14, borderRadius: 6, margin: '12px 0' }}>
                  <h4 style={{ margin: '0 0 6px 0', color: 'var(--primary)', fontFamily: 'var(--font-serif)' }}>Core Principles</h4>
                  <ul style={{ margin: 0, paddingLeft: 20 }}>
                    <li><strong>Continuity:</strong> New sessions call <code>workspace_summary</code> and catch up immediately.</li>
                    <li><strong>No Duplicate Work:</strong> <code>search_context</code> surfaces past decisions before re-deciding them.</li>
                    <li><strong>Coordination:</strong> <code>update_presence</code> broadcasts active files so agents don't collide.</li>
                  </ul>
                </div>
              </div>
            ) : (
              <div style={{ lineHeight: 1.6, color: 'var(--on-surface-variant)' }}>
                <p>
                  Quick reference for connecting your editor tools to this active hub:
                </p>
                <div style={{ background: 'var(--surface-container)', padding: 12, borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 12, margin: '12px 0' }}>
                  <div># Connect Claude Code plugin:</div>
                  <div style={{ color: 'var(--primary)', fontWeight: 600 }}>claude plugin add editors/claude-code</div>
                  <br />
                  <div># Inspect API health:</div>
                  <div style={{ color: 'var(--primary)', fontWeight: 600 }}>curl http://localhost:8000/health</div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
