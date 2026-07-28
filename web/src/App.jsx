import React, { useState } from 'react'
import { useWorkspace } from './useWorkspace.js'
import Presence from './components/Presence.jsx'
import TaskList from './components/TaskList.jsx'
import DecisionList from './components/DecisionList.jsx'

export default function App() {
  const [slug, setSlug] = useState(() => localStorage.getItem('ch_slug') || 'erid')
  const [apiKey, setApiKey] = useState(() => localStorage.getItem('ch_key') || '')
  const [active, setActive] = useState({ slug, apiKey })

  const { summary, tasks, decisions, presence, connected, error } = useWorkspace(active.slug, active.apiKey)

  const connect = (e) => {
    e.preventDefault()
    localStorage.setItem('ch_slug', slug)
    localStorage.setItem('ch_key', apiKey)
    setActive({ slug, apiKey })
  }

  return (
    <div className="app">
      <header className="topbar">
        <h1>AI Context Hub</h1>
        <form className="connect" onSubmit={connect}>
          <input
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="workspace slug"
            aria-label="workspace slug"
          />
          <input
            value={apiKey}
            onChange={(e) => setApiKey(e.target.value)}
            placeholder="api key (optional)"
            aria-label="api key"
            type="password"
          />
          <button type="submit">Connect</button>
        </form>
        <span className={connected ? 'status on' : 'status off'}>
          {connected ? '● live' : '○ offline'}
        </span>
      </header>

      {error && <div className="error">Error: {error}</div>}

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
        <TaskList tasks={tasks} />
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
