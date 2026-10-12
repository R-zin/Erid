import React, { useEffect, useState } from 'react'
import Presence from '../components/Presence.jsx'
import TaskList from '../components/TaskList.jsx'
import DecisionList from '../components/DecisionList.jsx'
import HandoffList from '../components/HandoffList.jsx'
import OAuthLogin from '../components/OAuthLogin.jsx'

export default function LiveWorkspace({
  slug,
  summary,
  tasks,
  decisions,
  handoffs,
  presence,
  client,
  credential,
  error,
  isAuthError,
  activeSlug,
  setTasks,
  setDecisions,
  setHandoffs,
}) {
  const [agentFilter, setAgentFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState(null)
  const [isSearching, setIsSearching] = useState(false)
  const [searchError, setSearchError] = useState(null)

  // Debounced search query against backend API /search endpoint
  useEffect(() => {
    const q = searchQuery.trim()
    if (!q) {
      setSearchResults(null)
      setIsSearching(false)
      setSearchError(null)
      return
    }

    setIsSearching(true)
    setSearchError(null)

    const timer = setTimeout(async () => {
      try {
        if (client) {
          const res = await client.search(q, 20)
          setSearchResults(res)
        } else {
          const lower = q.toLowerCase()
          setSearchResults({
            query: q,
            tasks: tasks.filter((t) => t.title.toLowerCase().includes(lower)),
            decisions: decisions.filter(
              (d) =>
                d.title.toLowerCase().includes(lower) ||
                (d.reason && d.reason.toLowerCase().includes(lower)),
            ),
          })
        }
      } catch (err) {
        setSearchError(err.message || 'Search failed')
      } finally {
        setIsSearching(false)
      }
    }, 250)

    return () => clearTimeout(timer)
  }, [searchQuery, client, tasks, decisions])

  const openTasksCount = summary?.open_task_count ?? tasks.filter((t) => t.status !== 'done').length
  const pendingHandoffsCount = summary?.open_handoff_count ?? handoffs.filter((h) => h.status !== 'resolved').length
  const activeCollabsCount = summary?.active_developers?.length ?? presence.length
  const decisionsCount = summary?.decision_count ?? decisions.length

  return (
    <div className="w-full flex flex-col">
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

      {/* Context Search Band */}
      <div className="search-bar-strip">
        <div className="search-bar-strip-inner">
          <div className="search-input-group">
            <span className="material-symbols-outlined search-icon">search</span>
            <input
              type="text"
              className="context-search-input"
              placeholder={slug ? `Search context in ${slug} (tasks, decisions, rationale)…` : 'Select a workspace to search…'}
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="search context"
              disabled={!slug}
            />
            {isSearching && <span className="search-status-tag">Searching…</span>}
            {searchQuery && (
              <button
                type="button"
                className="ghost search-clear-btn"
                onClick={() => {
                  setSearchQuery('')
                  setSearchResults(null)
                }}
                aria-label="clear search"
              >
                ✕
              </button>
            )}
          </div>
          {searchQuery && searchResults && (
            <div className="search-results-summary">
              <span>{searchResults.tasks?.length || 0} tasks • {searchResults.decisions?.length || 0} decisions</span>
            </div>
          )}
        </div>
      </div>

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

        {/* Search Results Panel */}
        {searchQuery.trim() && searchResults && (
          <div className="search-results-card">
            <div className="search-results-header">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <span className="material-symbols-outlined" style={{ fontSize: 18, color: 'var(--primary)' }}>saved_search</span>
                <span style={{ fontWeight: 600, fontFamily: 'var(--font-serif)', fontSize: 16 }}>
                  Search Results for &ldquo;{searchQuery}&rdquo;
                </span>
              </div>
              <button
                type="button"
                className="ghost"
                onClick={() => {
                  setSearchQuery('')
                  setSearchResults(null)
                }}
                style={{ fontSize: 11 }}
              >
                Dismiss
              </button>
            </div>
            <div className="search-results-body">
              {searchResults.tasks?.length === 0 && searchResults.decisions?.length === 0 ? (
                <div className="empty-placeholder">No tasks or decisions matched &ldquo;{searchQuery}&rdquo;</div>
              ) : (
                <div className="search-results-grid">
                  {searchResults.tasks?.length > 0 && (
                    <div className="search-col">
                      <div className="search-col-title">Tasks ({searchResults.tasks.length})</div>
                      <ul className="search-item-list">
                        {searchResults.tasks.map((t) => (
                          <li key={t.id} className="search-item">
                            <span className={`badge ${t.status}`} style={{ fontSize: 10, padding: '1px 6px' }}>{t.status}</span>
                            <span style={{ fontWeight: 500, fontSize: 13 }}>{t.title}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {searchResults.decisions?.length > 0 && (
                    <div className="search-col">
                      <div className="search-col-title">Decisions ({searchResults.decisions.length})</div>
                      <ul className="search-item-list">
                        {searchResults.decisions.map((d) => (
                          <li key={d.id} className="search-item">
                            <span style={{ fontWeight: 500, fontSize: 13 }}>{d.title}</span>
                            {d.reason && <p style={{ fontSize: 12, color: 'var(--on-surface-variant)', margin: '2px 0 0' }}>{d.reason}</p>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
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
            <Presence presence={presence} agentFilter={agentFilter} client={client} canWrite={!!credential} />

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
    </div>
  )
}
