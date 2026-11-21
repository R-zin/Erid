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
  authType = 'key',
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
  const inProgressCount = tasks.filter((t) => t.status === 'in_progress').length
  const blockedCount = tasks.filter((t) => t.status === 'blocked').length
  const pendingHandoffsCount = summary?.open_handoff_count ?? handoffs.filter((h) => h.status !== 'resolved').length
  const activeCollabsCount = summary?.active_developers?.length ?? presence.length
  const decisionsCount = summary?.decision_count ?? decisions.length
  const pad = (n) => String(n).padStart(2, '0')

  const credentialLabel = !credential ? 'No credential' : authType === 'token' ? 'Signed in (token)' : 'API key'

  const stats = [
    { label: 'Open Tasks', value: openTasksCount, foot: blockedCount ? `${blockedCount} blocked` : 'none blocked' },
    { label: 'In Progress', value: inProgressCount, foot: 'being worked on' },
    { label: 'Decisions', value: decisionsCount, foot: 'recorded' },
    { label: 'Pending Handoffs', value: pendingHandoffsCount, foot: pendingHandoffsCount ? 'awaiting pickup' : 'all clear' },
    { label: 'Active Now', value: activeCollabsCount, foot: 'online now', accent: true },
  ]

  const clearSearch = () => {
    setSearchQuery('')
    setSearchResults(null)
  }

  return (
    <div className="w-full flex flex-col">
      {/* Masthead */}
      <section className="ws-masthead">
        <div style={{ minWidth: 0 }}>
          <div className="ws-breadcrumb label">
            <span className="square" aria-hidden="true" />
            <span>Workspace</span>
            <span aria-hidden="true">/</span>
            <span>{credentialLabel}</span>
          </div>
          <h1 className={`ws-title${slug ? '' : ' placeholder'}`}>{slug || 'No workspace'}</h1>
        </div>
      </section>

      {/* Stats */}
      <section className="stats-row" aria-label="Workspace counts">
        {stats.map((st) => (
          <div key={st.label} className={`stat-cell${st.accent ? ' accent' : ''}`}>
            <span className="label">{st.label}</span>
            <span className="stat-value">{slug ? pad(st.value) : '—'}</span>
            <span className="stat-foot">{slug ? st.foot : '\u00a0'}</span>
          </div>
        ))}
      </section>

      {/* Toolbar: agent filters + search */}
      <div className="toolbar">
        <div className="filter-pills-row" role="group" aria-label="Filter by agent">
          {[
            { id: 'all', label: 'All' },
            { id: 'claude', label: 'Claude Code' },
            { id: 'cursor', label: 'Cursor' },
            { id: 'codex', label: 'Codex' },
            { id: 'human', label: 'Humans' },
          ].map((f) => (
            <button
              key={f.id}
              type="button"
              className={`filter-btn ${agentFilter === f.id ? 'active' : ''}`}
              aria-pressed={agentFilter === f.id}
              onClick={() => setAgentFilter(f.id)}
            >
              {f.label}
            </button>
          ))}
        </div>
        <div className="search-input-group">
          <span className="material-symbols-outlined search-icon" aria-hidden="true">search</span>
          <input
            type="text"
            className="context-search-input"
            placeholder={slug ? `Search context in ${slug}` : 'Select a workspace to search'}
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            aria-label="search context"
            disabled={!slug}
          />
          {isSearching && <span className="search-status-tag">Searching…</span>}
          {searchQuery && (
            <button type="button" className="ghost search-clear-btn" onClick={clearSearch} aria-label="clear search">
              ✕
            </button>
          )}
        </div>
      </div>

      <main className="main-stage">
        {!slug && (
          <div className="notice-banner">
            <div className="label" style={{ marginBottom: 6 }}>Get started</div>
            <p style={{ margin: '0 0 4px', fontSize: 15, maxWidth: '60ch' }}>
              Add a workspace with <strong>+ New</strong> in the top bar, or sign in with your provider.
            </p>
            <OAuthLogin slug={activeSlug || 'default'} />
          </div>
        )}

        {error && slug && (
          <div className="error-banner" role="alert">
            <strong>Error: {error}</strong>
            {isAuthError && (
              <div className="small" style={{ marginTop: 6 }}>
                Open <strong>Edit</strong> in the workspace selector above to update the credential for this workspace.
              </div>
            )}
          </div>
        )}

        {searchError && (
          <div className="error-banner" role="alert">
            Search failed: {searchError}
          </div>
        )}

        {searchQuery.trim() && searchResults && (
          <section className="search-results-card" aria-label="Search results">
            <div className="search-results-header">
              <div className="card-title-group">
                <span className="card-title">Results for &ldquo;{searchQuery}&rdquo;</span>
                <span className="count-tag">
                  {searchResults.tasks?.length || 0} tasks · {searchResults.decisions?.length || 0} decisions
                </span>
              </div>
              <button type="button" className="ghost small" onClick={clearSearch}>
                Dismiss
              </button>
            </div>
            <div className="search-results-body">
              {searchResults.tasks?.length === 0 && searchResults.decisions?.length === 0 ? (
                <div className="empty-placeholder" style={{ paddingLeft: 0 }}>
                  No tasks or decisions matched &ldquo;{searchQuery}&rdquo;
                </div>
              ) : (
                <div className="search-results-grid">
                  {searchResults.tasks?.length > 0 && (
                    <div>
                      <div className="search-col-title">Tasks ({searchResults.tasks.length})</div>
                      <ul className="search-item-list">
                        {searchResults.tasks.map((t) => (
                          <li key={t.id} className="search-item">
                            <span className={`badge ${t.status}`} style={{ alignSelf: 'flex-start' }}>
                              {t.status.replace('_', ' ')}
                            </span>
                            <span style={{ fontWeight: 500 }}>{t.title}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                  {searchResults.decisions?.length > 0 && (
                    <div>
                      <div className="search-col-title">Decisions ({searchResults.decisions.length})</div>
                      <ul className="search-item-list">
                        {searchResults.decisions.map((d) => (
                          <li key={d.id} className="search-item">
                            <span style={{ fontWeight: 600 }}>{d.title}</span>
                            {d.reason && <p className="row-text" style={{ margin: 0 }}>{d.reason}</p>}
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </div>
              )}
            </div>
          </section>
        )}

        {/* 8 / 4 split, numbered sections */}
        <div className="board-grid">
          <div className="board-col">
            <TaskList
              index={1}
              tasks={tasks}
              client={client}
              canWrite={!!credential}
              onMutate={setTasks}
              agentFilter={agentFilter}
            />
            <DecisionList
              index={2}
              decisions={decisions}
              client={client}
              canWrite={!!credential}
              tasks={tasks}
              onMutate={setDecisions}
              agentFilter={agentFilter}
            />
          </div>

          <div className="board-col">
            <Presence index={3} presence={presence} agentFilter={agentFilter} client={client} canWrite={!!credential} />
            <HandoffList
              index={4}
              handoffs={handoffs}
              client={client}
              canWrite={!!credential}
              tasks={tasks}
              onMutate={setHandoffs}
              agentFilter={agentFilter}
            />
          </div>
        </div>
      </main>
    </div>
  )
}
