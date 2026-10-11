import React, { useState } from 'react'

export default function CleanFieldGuide({ onNavigateWorkspace }) {
  const [activeSection, setActiveSection] = useState('getting-started')
  const [searchTerm, setSearchTerm] = useState('')

  const sections = [
    { id: 'getting-started', num: '00', title: 'Zero-Config Quickstart' },
    { id: 'architecture', num: '01', title: 'Core Architecture' },
    { id: 'clients', num: '02', title: 'Client Integrations' },
    { id: 'mcp-spec', num: '03', title: 'MCP Specification' },
    { id: 'rest-ws', num: '04', title: 'REST & WebSocket API' },
  ]

  const filteredSections = sections.filter((s) =>
    s.title.toLowerCase().includes(searchTerm.toLowerCase()) ||
    s.num.includes(searchTerm)
  )

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto', padding: '32px 24px', width: '100%' }}>
      {/* Decorative ambient gradient bar */}
      <div style={{ height: 3, background: 'linear-gradient(to right, var(--primary), var(--secondary-container), var(--surface-high))', borderRadius: 2, marginBottom: 24, opacity: 0.8 }} />

      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr', gap: 32, alignItems: 'start' }}>
        {/* LEFT COLUMN: Sticky Navigation Tree */}
        <aside style={{ position: 'sticky', top: 90, display: 'flex', flexDirection: 'column', gap: 16 }}>
          <div style={{ background: 'var(--surface-container-low)', padding: 16, borderRadius: 8, border: 'var(--border-hairline)', boxShadow: 'var(--shadow-sm)' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', paddingBottom: 10, marginBottom: 12, borderBottom: 'var(--border-hairline)' }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--on-surface-variant)', fontWeight: 600 }}>
                Field Manual v0.9
              </span>
              <span style={{ padding: '2px 6px', background: 'var(--surface-container-high)', color: 'var(--primary)', fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700, borderRadius: 2 }}>
                STABLE
              </span>
            </div>

            {/* Quick Search */}
            <div style={{ position: 'relative', marginBottom: 16 }}>
              <input
                type="text"
                placeholder="Quick find specs, MCP..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                style={{ width: '100%', padding: '6px 28px 6px 10px', fontSize: 12, fontFamily: 'var(--font-mono)' }}
              />
              <span className="material-symbols-outlined" style={{ position: 'absolute', right: 8, top: 7, fontSize: 16, color: 'var(--on-surface-variant)' }}>
                search
              </span>
            </div>

            {/* Nav list */}
            <nav style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {filteredSections.map((s) => (
                <button
                  key={s.id}
                  type="button"
                  onClick={() => setActiveSection(s.id)}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    padding: '8px 12px',
                    borderRadius: 4,
                    border: 'none',
                    background: activeSection === s.id ? 'var(--primary-container)' : 'transparent',
                    color: activeSection === s.id ? '#ffffff' : 'var(--on-surface)',
                    cursor: 'pointer',
                    textAlign: 'left',
                    fontSize: 13,
                    fontWeight: activeSection === s.id ? 600 : 400,
                    transition: 'all 0.15s ease',
                  }}
                >
                  <span style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: activeSection === s.id ? 'var(--secondary-container)' : 'var(--outline)' }}>
                      {s.num} //
                    </span>
                    <span>{s.title}</span>
                  </span>
                  {activeSection === s.id && (
                    <span style={{ width: 4, height: 12, borderRadius: 2, background: 'var(--secondary-container)' }} />
                  )}
                </button>
              ))}
            </nav>
          </div>

          <div style={{ background: 'var(--surface-container)', padding: 14, borderRadius: 8, border: 'var(--border-hairline)', fontSize: 12 }}>
            <span style={{ fontWeight: 600, color: 'var(--primary)' }}>Have a running hub?</span>
            <p style={{ margin: '4px 0 10px', color: 'var(--on-surface-variant)' }}>
              Inspect live tasks and presence in the dashboard.
            </p>
            <button type="button" className="primary" onClick={onNavigateWorkspace} style={{ width: '100%', fontSize: 12 }}>
              Open Live Workspace
            </button>
          </div>
        </aside>

        {/* RIGHT COLUMN: Interactive Documentation Content */}
        <main style={{ display: 'flex', flexDirection: 'column', gap: 28, background: 'var(--surface-lowest)', padding: 32, borderRadius: 12, border: 'var(--border-hairline)', boxShadow: 'var(--shadow-sm)' }}>
          {activeSection === 'getting-started' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--secondary-container)', fontWeight: 600, marginBottom: 6 }}>
                <span>00 // GETTING STARTED</span>
              </div>
              <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: '0 0 16px', color: 'var(--primary)' }}>
                Zero-Config Multi-Client Quickstart
              </h2>
              <p style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--on-surface-variant)' }}>
                Erid bridges disparate agent sessions into a unified real-time context store. When you launch Erid, a local Postgres (state), Redis (pub/sub), and FastAPI service start instantly.
              </p>

              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: '24px 0 10px', color: 'var(--primary)' }}>
                1. Native Launch (No Docker)
              </h3>
              <p style={{ fontSize: 13, color: 'var(--on-surface-variant)' }}>
                Requirements: Postgres and Redis running locally, and <code className="agent-tag">uv</code>.
              </p>
              <div style={{ background: 'var(--surface-container)', padding: 16, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 12, margin: '8px 0 16px', lineHeight: 1.6 }}>
                <span className="muted"># Start the REST API &amp; WebSocket bus</span>
                <br />
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>cd api</span>
                <br />
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
                  DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:5432/erid" \
                </span>
                <br />
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
                  REDIS_URL="redis://localhost:6379/0" uv run uvicorn app.main:app --port 8000
                </span>
              </div>

              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: '24px 0 10px', color: 'var(--primary)' }}>
                2. Containerized Launch
              </h3>
              <div style={{ background: 'var(--surface-container)', padding: 16, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 12, margin: '8px 0 16px' }}>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>docker compose up -d postgres redis api web</span>
              </div>
            </div>
          )}

          {activeSection === 'architecture' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--secondary-container)', fontWeight: 600, marginBottom: 6 }}>
                <span>01 // ARCHITECTURE</span>
              </div>
              <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: '0 0 16px', color: 'var(--primary)' }}>
                Core Mesh &amp; Event Topology
              </h2>
              <p style={{ fontSize: 15, lineHeight: 1.6, color: 'var(--on-surface-variant)' }}>
                Erid treats context not as ephemeral prompt tokens, but as a durable graph of collaborative work.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, margin: '20px 0' }}>
                <div style={{ background: 'var(--surface-container)', padding: 16, borderRadius: 6, border: 'var(--border-hairline)' }}>
                  <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, margin: '0 0 6px', color: 'var(--primary)' }}>Postgres (State)</h4>
                  <p style={{ fontSize: 13, color: 'var(--on-surface-variant)', margin: 0 }}>
                    Persists tasks, decisions, and session handoffs with foreign-key referential integrity.
                  </p>
                </div>
                <div style={{ background: 'var(--surface-container)', padding: 16, borderRadius: 6, border: 'var(--border-hairline)' }}>
                  <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, margin: '0 0 6px', color: 'var(--primary)' }}>Redis (Pub/Sub)</h4>
                  <p style={{ fontSize: 13, color: 'var(--on-surface-variant)', margin: 0 }}>
                    Broadcasts mutations with sub-millisecond latency to all connected editor bridges and WebSockets.
                  </p>
                </div>
              </div>
            </div>
          )}

          {activeSection === 'clients' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--secondary-container)', fontWeight: 600, marginBottom: 6 }}>
                <span>02 // CLIENT INTEGRATIONS</span>
              </div>
              <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: '0 0 16px', color: 'var(--primary)' }}>
                Editor &amp; Agent Configuration
              </h2>

              <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, margin: '20px 0 8px', color: 'var(--primary)' }}>Claude Code</h4>
              <p style={{ fontSize: 13, color: 'var(--on-surface-variant)' }}>Add the official Claude Code plugin:</p>
              <div style={{ background: 'var(--surface-container)', padding: 14, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>claude plugin add editors/claude-code</span>
              </div>

              <h4 style={{ fontFamily: 'var(--font-serif)', fontSize: 18, margin: '20px 0 8px', color: 'var(--primary)' }}>Cursor IDE</h4>
              <p style={{ fontSize: 13, color: 'var(--on-surface-variant)' }}>Point your Cursor MCP configuration to the Erid server:</p>
              <div style={{ background: 'var(--surface-container)', padding: 14, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.5 }}>
                <div>&#123;</div>
                <div style={{ paddingLeft: 16 }}>"mcpServers": &#123;</div>
                <div style={{ paddingLeft: 32 }}>"erid": &#123; "command": "uv", "args": ["run", "python", "-m", "src.bridge"] &#125;</div>
                <div style={{ paddingLeft: 16 }}>&#125;</div>
                <div>&#125;</div>
              </div>
            </div>
          )}

          {activeSection === 'mcp-spec' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--secondary-container)', fontWeight: 600, marginBottom: 6 }}>
                <span>03 // MCP SPECIFICATION</span>
              </div>
              <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: '0 0 16px', color: 'var(--primary)' }}>
                Model Context Protocol Tools
              </h2>
              <p style={{ fontSize: 14, lineHeight: 1.6, color: 'var(--on-surface-variant)' }}>
                The Hub exposes the following standard MCP tools to any connected AI assistant:
              </p>
              <ul style={{ listStyle: 'none', padding: 0, display: 'flex', flexDirection: 'column', gap: 10, margin: '16px 0' }}>
                {[
                  { name: 'workspace_summary', desc: 'Returns high-level state, active tasks, and waiting handoffs.' },
                  { name: 'catch_up', desc: 'Synthesizes everything that happened since the last session wrapped up.' },
                  { name: 'create_handoff', desc: 'Leaves a durable brief and next action for whoever picks up next.' },
                  { name: 'create_decision', desc: 'Records architectural rationale to avoid duplicate circular analysis.' },
                  { name: 'update_presence', desc: 'Broadcasts active files being viewed or edited to avoid collision.' },
                ].map((tool) => (
                  <li key={tool.name} style={{ background: 'var(--surface-container)', padding: '10px 14px', borderRadius: 6, border: 'var(--border-hairline)' }}>
                    <code style={{ color: 'var(--secondary)', fontWeight: 600, fontSize: 13 }}>{tool.name}</code>
                    <div style={{ color: 'var(--on-surface-variant)', fontSize: 12, marginTop: 2 }}>{tool.desc}</div>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {activeSection === 'rest-ws' && (
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--secondary-container)', fontWeight: 600, marginBottom: 6 }}>
                <span>04 // API REFERENCE</span>
              </div>
              <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: '0 0 16px', color: 'var(--primary)' }}>
                REST Routes &amp; Real-Time WebSocket
              </h2>
              <p style={{ fontSize: 14, color: 'var(--on-surface-variant)' }}>
                Interactive OpenAPI Swagger documentation is available locally at:
              </p>
              <div style={{ background: 'var(--surface-container)', padding: 14, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>http://localhost:8000/docs</span>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
