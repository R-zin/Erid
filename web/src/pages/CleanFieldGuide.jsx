import React, { useState } from 'react'

// Every command and config here mirrors README.md and clients/ in the repo.
// Keep them in sync when those change.

const SECTIONS = [
  { id: 'getting-started', num: '00', title: 'Quickstart' },
  { id: 'architecture', num: '01', title: 'Architecture' },
  { id: 'clients', num: '02', title: 'Connect your tools' },
  { id: 'mcp-spec', num: '03', title: 'MCP tools & prompts' },
  { id: 'rest-ws', num: '04', title: 'REST & WebSocket' },
]

const TOOL_GROUPS = [
  { group: 'Workspace', tools: ['workspace_summary', 'search_context', 'list_workspaces', 'active_developers'] },
  { group: 'Tasks', tools: ['current_tasks', 'create_task', 'update_task', 'delete_task'] },
  { group: 'Decisions', tools: ['create_decision', 'recent_decisions', 'task_decisions', 'delete_decision'] },
  { group: 'Handoffs', tools: ['create_handoff', 'recent_handoffs', 'acknowledge_handoff', 'resolve_handoff'] },
  { group: 'Presence', tools: ['update_presence'] },
]

const PROMPTS = [
  { name: 'catch_up', desc: 'Brief an agent that just joined: open handoffs, key decisions, who is active.' },
  { name: 'summarize_workspace', desc: 'Summarize the current state of a workspace.' },
  { name: 'standup_report', desc: 'Draft a standup-style report of recent work.' },
]

function Code({ children }) {
  return <pre className="code-block">{children}</pre>
}

function SectionHead({ num, kicker, title }) {
  return (
    <>
      <div className="label">
        <span className="accent-text">{num}</span> / {kicker}
      </div>
      <h2 className="guide-title">{title}</h2>
    </>
  )
}

export default function CleanFieldGuide({ onNavigateWorkspace }) {
  const [activeSection, setActiveSection] = useState('getting-started')
  const [searchTerm, setSearchTerm] = useState('')

  const q = searchTerm.toLowerCase()
  const filteredSections = SECTIONS.filter((s) => s.title.toLowerCase().includes(q) || s.num.includes(searchTerm))
  const toolCount = TOOL_GROUPS.reduce((n, g) => n + g.tools.length, 0)

  return (
    <div className="guide">
      <aside className="guide-nav">
        <div className="card-header" style={{ paddingLeft: 0, paddingRight: 0 }}>
          <h2 className="card-title">Field Guide</h2>
        </div>

        <input
          type="text"
          placeholder="Find a section…"
          aria-label="find a section"
          value={searchTerm}
          onChange={(e) => setSearchTerm(e.target.value)}
          style={{ width: '100%', margin: '12px 0' }}
        />

        <nav className="guide-links" aria-label="Field guide sections">
          {filteredSections.map((s) => (
            <button
              key={s.id}
              type="button"
              className={`guide-link${activeSection === s.id ? ' active' : ''}`}
              aria-current={activeSection === s.id ? 'true' : undefined}
              onClick={() => setActiveSection(s.id)}
            >
              <span className="section-num">{s.num}</span>
              <span>{s.title}</span>
            </button>
          ))}
          {filteredSections.length === 0 && <span className="muted small">No section matches.</span>}
        </nav>

        <div className="guide-cta">
          <div className="label">Have a running hub?</div>
          <p className="row-text" style={{ margin: '6px 0 12px' }}>See tasks, handoffs and presence live.</p>
          <button type="button" className="primary" onClick={onNavigateWorkspace} style={{ width: '100%' }}>
            Open workspace
          </button>
        </div>
      </aside>

      <main className="guide-body">
        {activeSection === 'getting-started' && (
          <div>
            <SectionHead num="00" kicker="Getting started" title="Quickstart" />
            <p className="guide-lede">
              Erid is one FastAPI service backed by Postgres. Postgres holds the state and fans events out with
              LISTEN/NOTIFY. Run it with Docker Compose or natively.
            </p>

            <h3 className="guide-h3">With Docker Compose</h3>
            <Code>{`docker compose up -d postgres api web
# API        http://localhost:8000   (docs at /docs)
# Dashboard  http://localhost:8080`}</Code>

            <h3 className="guide-h3">Natively</h3>
            <p className="row-text">
              Needs Postgres running locally and <code className="mono">uv</code>. The API runs its database
              migrations on startup.
            </p>
            <Code>{`createdb erid
cd api
DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/erid" \\
  uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# dashboard (proxies /api to :8000)
cd web && npm install && npm run dev    # http://localhost:5173`}</Code>
          </div>
        )}

        {activeSection === 'architecture' && (
          <div>
            <SectionHead num="01" kicker="Architecture" title="How the pieces fit" />
            <p className="guide-lede">
              Context lives in Postgres as tasks, decisions, handoffs and presence, scoped to a workspace. REST, MCP and
              the WebSocket stream all go through the same service layer.
            </p>
            <div className="guide-cards">
              <div className="guide-card">
                <h4>State: Postgres</h4>
                <p>Stores tasks, decisions (optionally linked to a task), handoffs and presence for each workspace.</p>
              </div>
              <div className="guide-card">
                <h4>Events: outbox + LISTEN/NOTIFY</h4>
                <p>
                  Each change is written with an event in the same transaction, then broadcast on commit to every API
                  instance and WebSocket. Clients that reconnect replay what they missed with ?since=.
                </p>
              </div>
              <div className="guide-card">
                <h4>Access: open or secured</h4>
                <p>
                  A workspace is open until secured. Secured workspaces accept the workspace key, per-actor keys with
                  roles and grants, or Ed25519 JWTs. Google/GitHub sign-in needs an invite from an owner.
                </p>
              </div>
              <div className="guide-card">
                <h4>Attribution</h4>
                <p>Anything written with an actor’s key or token is recorded as that actor, whatever the request claims.</p>
              </div>
            </div>
          </div>
        )}

        {activeSection === 'clients' && (
          <div>
            <SectionHead num="02" kicker="Clients" title="Connect your tools" />
            <p className="guide-lede">
              Clients connect by URL to <code className="mono">/mcp</code>. Set the default workspace with the{' '}
              <code className="mono">X-Erid-Workspace</code> header; for a secured workspace also send{' '}
              <code className="mono">X-API-Key</code> or a bearer token. More in <code className="mono">clients/README.md</code>.
            </p>

            <h3 className="guide-h3">Claude Code</h3>
            <Code>{`claude mcp add --transport http erid http://localhost:8000/mcp \\
  --header "X-Erid-Workspace: your-workspace" \\
  --header "X-API-Key: $ERID_API_KEY"`}</Code>
            <p className="row-text">
              Or, from a session at the repo root, install the bundled plugin for <code className="mono">/hub:*</code>{' '}
              commands: <code className="mono">/plugin install ./editors/claude-code</code>
            </p>

            <h3 className="guide-h3">Cursor</h3>
            <p className="row-text">
              In <code className="mono">.cursor/mcp.json</code> (project) or <code className="mono">~/.cursor/mcp.json</code>:
            </p>
            <Code>{`{
  "mcpServers": {
    "erid": {
      "url": "http://localhost:8000/mcp",
      "headers": { "X-Erid-Workspace": "your-workspace", "X-API-Key": "<key>" }
    }
  }
}`}</Code>

            <h3 className="guide-h3">Codex CLI</h3>
            <p className="row-text">
              Merge into <code className="mono">~/.codex/config.toml</code>:
            </p>
            <Code>{`[mcp_servers.erid]
url = "http://localhost:8000/mcp"
http_headers = { "X-Erid-Workspace" = "your-workspace" }
env_http_headers = { "X-API-Key" = "ERID_API_KEY" }`}</Code>
          </div>
        )}

        {activeSection === 'mcp-spec' && (
          <div>
            <SectionHead num="03" kicker="MCP" title="MCP tools & prompts" />
            <p className="guide-lede">
              {toolCount} tools, each enforcing the same permission as the matching REST route.
            </p>
            <div className="guide-cards">
              {TOOL_GROUPS.map((g) => (
                <div key={g.group} className="guide-card">
                  <h4>{g.group}</h4>
                  <ul className="tool-list mono">
                    {g.tools.map((t) => (
                      <li key={t}>{t}</li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>

            <h3 className="guide-h3">Prompts</h3>
            <ul className="search-item-list">
              {PROMPTS.map((p) => (
                <li key={p.name} className="search-item">
                  <code className="mono accent-text" style={{ fontWeight: 600 }}>{p.name}</code>
                  <span className="row-text" style={{ margin: 0 }}>{p.desc}</span>
                </li>
              ))}
            </ul>

            <h3 className="guide-h3">Resources</h3>
            <Code>{`workspace://index
workspace://{slug}/summary   workspace://{slug}/tasks
workspace://{slug}/decisions workspace://{slug}/handoffs
workspace://{slug}/presence`}</Code>
          </div>
        )}

        {activeSection === 'rest-ws' && (
          <div>
            <SectionHead num="04" kicker="API reference" title="REST & WebSocket" />
            <p className="guide-lede">
              REST lives under <code className="mono">/api/workspaces/{'{slug}'}</code>. Interactive OpenAPI docs are
              served by the API itself:
            </p>
            <Code>http://localhost:8000/docs</Code>

            <h3 className="guide-h3">Live events</h3>
            <p className="row-text">
              Subscribe to a workspace’s events over WebSocket. Every stored event carries a <code className="mono">seq</code>;
              reconnect with the last one you saw to replay what you missed. Browsers can’t set headers on a WebSocket,
              so pass the credential as <code className="mono">?api_key=</code> or <code className="mono">?token=</code>.
            </p>
            <Code>{`ws://localhost:8000/api/workspaces/{slug}/ws?since=<seq>&token=<jwt>`}</Code>
          </div>
        )}
      </main>
    </div>
  )
}
