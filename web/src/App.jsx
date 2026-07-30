import React, { useMemo } from 'react'
import { useWorkspace } from './useWorkspace.js'
import { useWorkspaces } from './useWorkspaces.js'
import { makeClient } from './api.js'
import Presence from './components/Presence.jsx'
import TaskList from './components/TaskList.jsx'
import DecisionList from './components/DecisionList.jsx'
import WorkspaceSwitcher from './components/WorkspaceSwitcher.jsx'

export default function App() {
  const {
    workspaces,
    active,
    activeSlug,
    upsertWorkspace,
    removeWorkspace,
    selectWorkspace,
  } = useWorkspaces()

  const credential = active?.credential || ''
  const authType = active?.authType || 'key'
  const slug = active?.slug || ''

  const { summary, tasks, decisions, presence, connected, error, setTasks } =
    useWorkspace(slug, credential, authType)

  // A client bound to the active workspace for mutations (task create). Null
  // until a workspace is selected so the form can disable itself.
  const client = useMemo(
    () => (slug ? makeClient({ slug, credential, authType }) : null),
    [slug, credential, authType],
  )

  const isAuthError =
    !!error && /authentication failed/i.test(error)

  return (
    <div className="app">
      <header className="topbar">
        <h1>AI Context Hub</h1>
        <WorkspaceSwitcher
          workspaces={workspaces}
          active={active}
          activeSlug={activeSlug}
          onSelect={selectWorkspace}
          onSave={upsertWorkspace}
          onRemove={removeWorkspace}
        />
        <span className={connected ? 'status on' : 'status off'}>
          {connected ? '● live' : '○ offline'}
        </span>
      </header>

      {!slug && (
        <div className="error">
          No workspace selected. Add one with <strong>+ New</strong> above (slug + optional
          API key or token) to get started.
        </div>
      )}

      {error && slug && (
        <div className="error">
          Error: {error}
          {isAuthError && (
            <div className="small" style={{ marginTop: 6 }}>
              Open <strong>Edit</strong> above to update the credential for this workspace.
            </div>
          )}
        </div>
      )}

      {summary && (
        <section className="summary">
          <Stat label="Workspace" value={summary.slug} />
          <Stat label="Tasks" value={summary.task_count} />
          <Stat label="Open" value={summary.open_task_count} />
          <Stat label="Decisions" value={summary.decision_count} />
          <Stat label="Active" value={summary.active_developers.length} />
        </section>
      )}

      <main className="grid">
        <Presence presence={presence} />
        <TaskList tasks={tasks} client={client} canWrite={!!credential} onMutate={setTasks} />
        <DecisionList decisions={decisions} />
      </main>
    </div>
  )
}

function Stat({ label, value }) {
  return (
    <div className="stat">
      <div className="stat-value">{value}</div>
      <div className="stat-label">{label}</div>
    </div>
  )
}
