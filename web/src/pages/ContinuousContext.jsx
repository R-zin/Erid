import React, { useState } from 'react'

const COMPOSE_CMD = 'docker compose up -d postgres api web'

// Everything on this page describes what Erid actually does today — no
// performance numbers or features the code doesn't have.
const CLIENTS = [
  { name: 'Claude Code', via: 'MCP over HTTP' },
  { name: 'Cursor', via: 'MCP over HTTP' },
  { name: 'Codex CLI', via: 'MCP over HTTP' },
  { name: 'VS Code · JetBrains', via: 'REST + WebSocket' },
]

const BACKING = [
  { name: 'PostgreSQL', note: 'Tasks, decisions, handoffs, presence', tag: 'state' },
  { name: 'LISTEN / NOTIFY', note: 'Fans each change out to every API instance', tag: 'on commit' },
]

const FEATURES = [
  {
    num: '01',
    kicker: 'Continuity',
    title: 'Durable Handoffs',
    body:
      'When a session ends, leave a handoff: what was done, files changed, commands run, blockers and the next action. Whoever picks up next acknowledges it, then resolves it.',
    example: ['Handoff · acknowledged', 'Next: add integration tests for jwt_helper.py'],
  },
  {
    num: '02',
    kicker: 'Coordination',
    title: 'Presence',
    body:
      'Each agent or person reports the task and file they are on, so everyone can see who is touching what before they start. It is a signal, not a lock.',
    example: ['claude · src/auth/jwt_helper.py', 'last seen 12s ago'],
  },
  {
    num: '03',
    kicker: 'Memory',
    title: 'Decisions',
    body:
      'Record why something was decided, optionally linked to a task and files. Agents search decisions before re-deciding, so settled questions stay settled.',
    example: ['search_context("jwt")', '→ 2 decisions, 1 task'],
  },
]

export default function ContinuousContext({ onNavigateWorkspace }) {
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('with-erid')

  const copyCompose = () => {
    navigator.clipboard?.writeText(COMPOSE_CMD)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="w-full flex flex-col">
      {/* Hero */}
      <section className="page-hero">
        <div className="ws-breadcrumb label">
          <span className="square" aria-hidden="true" />
          <span>How Erid works</span>
          <span aria-hidden="true">/</span>
          <span>MCP · REST · WebSocket</span>
        </div>
        <div className="page-hero-grid">
          <h1 className="page-title">
            AI agents shouldn’t wake up with amnesia<span className="brand-dot">.</span>
          </h1>
          <p className="page-lede">
            One shared hub for tasks, decisions, handoffs and presence. Claude Code, Cursor and Codex CLI read and
            write the same project state over MCP, and the dashboard shows it live.
          </p>
        </div>
        <div className="btn-row" style={{ marginTop: 28, gap: 12 }}>
          <button type="button" className="accent" onClick={onNavigateWorkspace}>
            Open the dashboard
          </button>
          <button type="button" className="ghost code-chip" onClick={copyCompose} title="Copy command">
            <span className="muted">$</span> {COMPOSE_CMD}
            <span className="material-symbols-outlined" style={{ fontSize: 15 }} aria-hidden="true">
              {copied ? 'check' : 'content_copy'}
            </span>
          </button>
          {copied && <span className="mono small accent-text">Copied</span>}
          <span className="label" style={{ marginLeft: 'auto' }}>Self-hosted · FastAPI + Postgres</span>
        </div>
      </section>

      {/* How it fits together */}
      <section className="card-panel" aria-label="How it fits together">
        <div className="card-header">
          <div className="card-title-group">
            <span className="section-num">01</span>
            <h2 className="card-title">How it fits together</h2>
          </div>
          <span className="count-tag">one hub · many clients</span>
        </div>

        <div className="topology">
          <div className="topology-col">
            <div className="label topology-head">Clients</div>
            {CLIENTS.map((c) => (
              <div key={c.name} className="topology-node">
                <span className="topology-name">{c.name}</span>
                <span className="topology-note">{c.via}</span>
              </div>
            ))}
          </div>

          <div className="topology-hub">
            <div className="label" style={{ color: 'inherit', opacity: 0.7 }}>The hub</div>
            <div className="topology-hub-title">Erid API</div>
            <p>
              One FastAPI service. REST, MCP and the WebSocket stream share the same service layer, and every change is
              written together with its event in a single transaction.
            </p>
            <div className="topology-hub-routes mono">
              <span>/mcp</span>
              <span>/api</span>
              <span>/api/…/ws</span>
            </div>
          </div>

          <div className="topology-col">
            <div className="label topology-head">Behind it</div>
            {BACKING.map((b) => (
              <div key={b.name} className="topology-node">
                <span className="topology-name">{b.name}</span>
                <span className="topology-note">{b.note}</span>
                <span className="topology-tag">{b.tag}</span>
              </div>
            ))}
            <button type="button" className="topology-node topology-link" onClick={onNavigateWorkspace}>
              <span className="topology-name">Dashboard</span>
              <span className="topology-note">Live over WebSocket; reconnects replay with ?since=</span>
              <span className="material-symbols-outlined" style={{ fontSize: 16 }} aria-hidden="true">arrow_forward</span>
            </button>
          </div>
        </div>

        <div className="topology-foot">
          <span>Writes made with an actor’s key are attributed to that actor</span>
          <span>Missed events replay with ?since=</span>
        </div>
      </section>

      {/* What you get */}
      <section className="card-panel" aria-label="What you get">
        <div className="card-header">
          <div className="card-title-group">
            <span className="section-num">02</span>
            <h2 className="card-title">What you get</h2>
          </div>
          <span className="count-tag">shared by every agent</span>
        </div>
        <div className="feature-grid">
          {FEATURES.map((f) => (
            <article key={f.num} className="feature">
              <div className="label">
                <span className="accent-text">{f.num}</span> / {f.kicker}
              </div>
              <h3 className="feature-title">{f.title}</h3>
              <p className="row-text" style={{ margin: 0 }}>{f.body}</p>
              <div className="feature-example mono">
                <div>{f.example[0]}</div>
                <div className="muted">{f.example[1]}</div>
              </div>
            </article>
          ))}
        </div>
      </section>

      {/* Walkthrough */}
      <section className="card-panel" aria-label="Session continuity">
        <div className="card-header">
          <div className="card-title-group">
            <span className="section-num">03</span>
            <h2 className="card-title">Session continuity in action</h2>
          </div>
          <div className="btn-row" role="group" aria-label="Compare">
            <button
              type="button"
              className={`filter-btn ${activeTab === 'with-erid' ? 'active' : ''}`}
              aria-pressed={activeTab === 'with-erid'}
              onClick={() => setActiveTab('with-erid')}
            >
              With Erid
            </button>
            <button
              type="button"
              className={`filter-btn ${activeTab === 'isolated' ? 'active' : ''}`}
              aria-pressed={activeTab === 'isolated'}
              onClick={() => setActiveTab('isolated')}
            >
              Without
            </button>
          </div>
        </div>

        <div className="walkthrough mono">
          {activeTab === 'with-erid' ? (
            <>
              <div className="walk-step">1. Claude Code wraps up</div>
              <div className="muted">
                &gt; create_handoff(summary="JWT verification moved to jwt_helper.py", next_action="Add integration
                tests")
              </div>
              <div className="walk-ok">✓ Handoff saved and pushed to every connected client.</div>
              <div className="walk-step">2. Cursor starts the next session</div>
              <div className="muted">&gt; catch_up prompt → workspace_summary, recent_handoffs, recent_decisions</div>
              <div className="accent-text">↳ 1 open handoff from Claude Code: “JWT verification moved to jwt_helper.py”</div>
              <div className="muted">&gt; acknowledge_handoff(…)</div>
              <div className="walk-ok">✓ Cursor starts on the tests without re-deriving the auth change.</div>
            </>
          ) : (
            <>
              <div className="walk-step" style={{ color: 'var(--error)' }}>Each session starts from zero</div>
              <div className="muted">&gt; Cursor opens a session with no tasks, decisions or handoffs to read.</div>
              <div className="muted">&gt; It re-reads the code to rediscover what the last session already did.</div>
              <div className="muted">&gt; It may redo the work, or contradict a decision made earlier.</div>
            </>
          )}
        </div>
      </section>
    </div>
  )
}
