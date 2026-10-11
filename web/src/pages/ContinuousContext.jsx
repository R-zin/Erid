import React, { useState } from 'react'

export default function ContinuousContext({ onNavigateWorkspace }) {
  const [copied, setCopied] = useState(false)
  const [activeTab, setActiveTab] = useState('with-erid')

  const copyDocker = () => {
    navigator.clipboard?.writeText('docker compose up -d postgres redis api web')
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  return (
    <div className="w-full flex flex-col">
      {/* Top Ambient Narrative Beacon */}
      <section style={{ maxWidth: 1400, margin: '0 auto', padding: '48px 24px 24px', width: '100%' }}>
        <div style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '4px 10px', background: 'var(--surface-container)', borderRadius: 4, border: 'var(--border-hairline)', marginBottom: 20 }}>
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--secondary-container)' }} />
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Architecture Specification RFC-09
          </span>
          <span style={{ color: 'var(--outline-variant)', fontSize: 11 }}>/</span>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--primary)', fontWeight: 600 }}>
            Model Context Protocol 2.1
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 32, alignItems: 'flex-end' }}>
          <div>
            <h1 style={{ fontFamily: 'var(--font-serif)', fontSize: 'clamp(32px, 5vw, 56px)', fontWeight: 400, lineHeight: 1.15, color: 'var(--primary)', margin: 0, letterSpacing: '-0.02em' }}>
              AI agents shouldn’t wake up with amnesia<span style={{ color: 'var(--secondary-container)' }}>.</span>
            </h1>
          </div>
          <div>
            <p style={{ fontSize: 16, lineHeight: 1.6, color: 'var(--on-surface-variant)', margin: 0 }}>
              A unified, real-time context bus. Claude Code, Cursor, and Codex read and write to the exact same project brain without drift, hallucinated diffs, or collision.
            </p>
          </div>
        </div>

        {/* Action Row */}
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 16, marginTop: 32 }}>
          <button
            type="button"
            className="accent"
            onClick={onNavigateWorkspace}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 8, padding: '12px 20px', fontSize: 13, fontWeight: 600 }}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>bolt</span>
            Start Context Engine
          </button>

          <div
            onClick={copyDocker}
            style={{ display: 'inline-flex', alignItems: 'center', gap: 10, padding: '10px 16px', background: 'var(--surface-container)', borderRadius: 6, border: 'var(--border-hairline)', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 13, userSelect: 'all' }}
            title="Click to copy command"
          >
            <span style={{ color: 'var(--on-surface-variant)' }}>$</span>
            <span style={{ color: 'var(--primary)', fontWeight: 500 }}>docker compose up -d</span>
            <span className="material-symbols-outlined" style={{ fontSize: 16, color: 'var(--on-surface-variant)' }}>
              {copied ? 'check' : 'content_copy'}
            </span>
            {copied && <span style={{ color: 'var(--secondary)', fontSize: 11 }}>Copied!</span>}
          </div>

          <div style={{ marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
            <span className="pulse-indicator live" style={{ width: 6, height: 6 }}>
              <span className="dot-core" />
            </span>
            <span>Dual-Stack: Local Ephemeral · Raft Cluster Sync</span>
          </div>
        </div>
      </section>

      {/* Interactive Vector Context Flow Topology */}
      <section style={{ maxWidth: 1400, margin: '0 auto', padding: '16px 24px', width: '100%' }}>
        <div style={{ background: 'var(--surface-container)', border: 'var(--border-hairline)', borderRadius: 12, padding: 24, boxShadow: 'var(--shadow-sm)' }}>
          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, borderBottom: 'var(--border-hairline)', paddingBottom: 14, marginBottom: 20 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: 0, color: 'var(--primary)' }}>
                Sub-graph Topology
              </h3>
              <span style={{ padding: '2px 8px', background: 'var(--surface-low)', borderRadius: 4, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
                Live Pub/Sub Sync
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              <div style={{ background: 'var(--surface-lowest)', padding: '4px 10px', borderRadius: 4, border: 'var(--border-hairline)' }}>
                <span className="muted">latency: </span>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>1.2ms</span>
              </div>
              <div style={{ background: 'var(--surface-lowest)', padding: '4px 10px', borderRadius: 4, border: 'var(--border-hairline)' }}>
                <span className="muted">events: </span>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>4,812/s</span>
              </div>
              <div style={{ background: 'var(--surface-lowest)', padding: '4px 10px', borderRadius: 4, border: 'var(--border-hairline)' }}>
                <span className="muted">drift: </span>
                <span style={{ color: 'var(--secondary-container)', fontWeight: 600 }}>0.00%</span>
              </div>
            </div>
          </div>

          {/* SVG Routing Schematic & 3 Columns */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 20, alignItems: 'center', position: 'relative' }}>
            {/* Column 1: Client Agents */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: 'var(--border-hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 20 }}>terminal</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>Cursor IDE</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Editor Workspace agent</div>
                  </div>
                </div>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--secondary-container)' }} />
              </div>

              <div style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: '1px solid rgba(253, 106, 73, 0.4)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--secondary-container)', fontSize: 20 }}>psychology</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>Claude Code</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Context stream author</div>
                  </div>
                </div>
                <span style={{ padding: '2px 6px', background: 'var(--secondary-fixed)', color: 'var(--on-secondary-fixed)', borderRadius: 4, fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 600 }}>
                  TX 41b/s
                </span>
              </div>

              <div style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: 'var(--border-hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 20 }}>data_object</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>Codex CLI</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Background runner</div>
                  </div>
                </div>
                <span style={{ width: 8, height: 8, borderRadius: '50%', background: 'var(--outline)' }} />
              </div>
            </div>

            {/* Column 2: Central Hub Core */}
            <div style={{ display: 'flex', justifyContent: 'center' }}>
              <div style={{ width: '100%', maxWidth: 360, background: 'var(--primary-container)', color: '#ffffff', borderRadius: 12, padding: 20, boxShadow: 'var(--shadow-md)', position: 'relative', overflow: 'hidden' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: '1px solid rgba(255,255,255,0.15)', paddingBottom: 10, marginBottom: 12 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span className="material-symbols-outlined" style={{ color: 'var(--secondary-container)', fontSize: 22 }}>hub</span>
                    <span style={{ fontFamily: 'var(--font-serif)', fontSize: 18, color: '#ffffff' }}>Erid Core Bus</span>
                  </div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, padding: '2px 6px', background: 'rgba(255,255,255,0.1)', borderRadius: 4 }}>v0.1-rc3</span>
                </div>
                <p style={{ fontSize: 12, lineHeight: 1.5, color: '#b3ccc8', margin: '0 0 16px' }}>
                  In-memory vector sync and AST diff indexer routing unified MCP events without session loss.
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, fontFamily: 'var(--font-mono)', fontSize: 11 }}>
                  <div style={{ background: 'rgba(255,255,255,0.06)', padding: '6px 8px', borderRadius: 4 }}>
                    <div style={{ color: '#768e8b', fontSize: 10 }}>Active Locks</div>
                    <div style={{ color: '#ffffff', fontWeight: 600 }}>1 Mutex (auth.py)</div>
                  </div>
                  <div style={{ background: 'rgba(255,255,255,0.06)', padding: '6px 8px', borderRadius: 4 }}>
                    <div style={{ color: '#768e8b', fontSize: 10 }}>Vector Dedupe</div>
                    <div style={{ color: 'var(--secondary-container)', fontWeight: 600 }}>99.8% hit rate</div>
                  </div>
                </div>
              </div>
            </div>

            {/* Column 3: Storage & Observers */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              <div style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: 'var(--border-hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 20 }}>database</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>PostgreSQL</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Durability & WAL sync</div>
                  </div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>pgvector</span>
              </div>

              <div style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: 'var(--border-hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 20 }}>swap_horiz</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>Redis Event Bus</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Low-latency Pub/Sub</div>
                  </div>
                </div>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--secondary-container)', fontWeight: 600 }}>&lt;1ms</span>
              </div>

              <div
                onClick={onNavigateWorkspace}
                style={{ padding: '12px 14px', borderRadius: 6, background: 'var(--surface-lowest)', border: 'var(--border-hairline)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', boxShadow: 'var(--shadow-sm)', cursor: 'pointer' }}
              >
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 20 }}>monitoring</span>
                  <div>
                    <div style={{ fontWeight: 600, color: 'var(--primary)', fontSize: 13 }}>Live Observer</div>
                    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--on-surface-variant)' }}>Real-Time Inspector</div>
                  </div>
                </div>
                <span className="material-symbols-outlined" style={{ color: 'var(--primary)', fontSize: 18 }}>arrow_forward</span>
              </div>
            </div>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', justifyContent: 'space-between', gap: 12, marginTop: 20, paddingTop: 14, borderTop: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
            <div style={{ display: 'flex', gap: 16 }}>
              <span>• Zero JSON transformation overhead</span>
              <span>• stdio / WebSocket multiplexing</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--primary)', cursor: 'pointer' }} onClick={onNavigateWorkspace}>
              <span>Deterministic context replay available</span>
              <span className="material-symbols-outlined" style={{ fontSize: 14 }}>arrow_forward</span>
            </div>
          </div>
        </div>
      </section>

      {/* Architectural Guarantees (4 Core Tenets) */}
      <section style={{ maxWidth: 1400, margin: '0 auto', padding: '36px 24px', width: '100%' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'flex-end', justifyContent: 'space-between', marginBottom: 24, gap: 16 }}>
          <div>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--secondary-container)', textTransform: 'uppercase', letterSpacing: '0.04em', fontWeight: 600, marginBottom: 4 }}>
              Foundational Mechanics
            </div>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontSize: 32, margin: 0, color: 'var(--primary)' }}>
              Architectural Guarantees
            </h2>
          </div>
          <p style={{ maxWidth: 440, margin: 0, color: 'var(--on-surface-variant)', fontSize: 14 }}>
            Engineered explicitly for multi-agent co-authorship. Eliminate conflicting diffs and stale memory states completely.
          </p>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(300px, 1fr))', gap: 20 }}>
          {/* Card 1 */}
          <div className="card-panel" style={{ padding: 20, background: 'var(--surface-container)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
              <span>01 / PERSISTENCE</span>
              <span style={{ padding: '2px 6px', background: 'var(--surface-lowest)', borderRadius: 2, color: 'var(--primary)' }}>Session Preservation</span>
            </div>
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: '0 0 8px', color: 'var(--primary)' }}>
              Durable Handoffs
            </h3>
            <p style={{ fontSize: 13, color: 'var(--on-surface-variant)', lineHeight: 1.5, margin: '0 0 16px' }}>
              Session state never evaporates when context limits trigger a compaction. Active file touches, open tickets, and planned AST mutations transfer cleanly.
            </p>
            <div style={{ background: 'var(--surface-lowest)', padding: 12, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>Handoff Ticket #7419</span>
                <span style={{ color: 'var(--secondary-container)', fontWeight: 600 }}>● Acknowledged</span>
              </div>
              <div style={{ color: 'var(--on-surface-variant)', fontSize: 10 }}>Next: Commit JWT rotation logic in services/auth.go</div>
            </div>
          </div>

          {/* Card 2 */}
          <div className="card-panel" style={{ padding: 20, background: 'var(--surface-container)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
              <span>02 / COORDINATION</span>
              <span style={{ padding: '2px 6px', background: 'var(--surface-lowest)', borderRadius: 2, color: 'var(--primary)' }}>Live Locking</span>
            </div>
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: '0 0 8px', color: 'var(--primary)' }}>
              Presence & Anti-Collision
            </h3>
            <p style={{ fontSize: 13, color: 'var(--on-surface-variant)', lineHeight: 1.5, margin: '0 0 16px' }}>
              Dynamic semantic locks on repository branches and file ASTs. Never watch two agents simultaneously rewrite the same middleware file with opposing patterns.
            </p>
            <div style={{ background: 'var(--surface-lowest)', padding: 12, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--secondary-container)', fontWeight: 600 }}>
                <span className="material-symbols-outlined" style={{ fontSize: 16 }}>lock</span>
                File Mutex Acquired: auth.py
              </div>
              <div style={{ color: 'var(--on-surface-variant)', fontSize: 10, marginTop: 4 }}>Held by Agent: claude_code_session_09</div>
            </div>
          </div>

          {/* Card 3 */}
          <div className="card-panel" style={{ padding: 20, background: 'var(--surface-container)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--on-surface-variant)' }}>
              <span>03 / CONTEXT PURITY</span>
              <span style={{ padding: '2px 6px', background: 'var(--surface-lowest)', borderRadius: 2, color: 'var(--primary)' }}>Semantic Filter</span>
            </div>
            <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 20, margin: '0 0 8px', color: 'var(--primary)' }}>
              Deduplication Engine
            </h3>
            <p style={{ fontSize: 13, color: 'var(--on-surface-variant)', lineHeight: 1.5, margin: '0 0 16px' }}>
              Vector similarity sweeps detect redundant codebase analysis before LLMs burn input tokens. Reuses historical reasoning with verifiable validity.
            </p>
            <div style={{ background: 'var(--surface-lowest)', padding: 12, borderRadius: 6, border: 'var(--border-hairline)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--primary)', fontWeight: 600 }}>
                <span>Token Savings:</span>
                <span style={{ color: 'var(--green)' }}>+48% cached</span>
              </div>
              <div style={{ color: 'var(--on-surface-variant)', fontSize: 10, marginTop: 4 }}>Vector index: 12,480 code nodes indexed</div>
            </div>
          </div>
        </div>
      </section>

      {/* Multi-Agent Walkthrough */}
      <section style={{ maxWidth: 1400, margin: '0 auto', padding: '24px', width: '100%' }}>
        <div style={{ background: 'var(--surface-container-low)', border: 'var(--border-hairline)', borderRadius: 12, padding: 24 }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderBottom: 'var(--border-hairline)', paddingBottom: 14, marginBottom: 16 }}>
            <div>
              <h3 style={{ fontFamily: 'var(--font-serif)', fontSize: 22, margin: 0, color: 'var(--primary)' }}>
                Session Continuity in Action
              </h3>
              <p style={{ margin: '4px 0 0', color: 'var(--on-surface-variant)', fontSize: 13 }}>
                Observe how Claude Code and Cursor exchange context across session boundaries.
              </p>
            </div>
            <div style={{ display: 'flex', gap: 6 }}>
              <button
                type="button"
                className={`filter-btn ${activeTab === 'with-erid' ? 'active' : ''}`}
                onClick={() => setActiveTab('with-erid')}
              >
                With Erid Hub
              </button>
              <button
                type="button"
                className={`filter-btn ${activeTab === 'isolated' ? 'active' : ''}`}
                onClick={() => setActiveTab('isolated')}
              >
                Without (Isolated)
              </button>
            </div>
          </div>

          <div style={{ background: 'var(--surface-container)', borderRadius: 8, padding: 16, fontFamily: 'var(--font-mono)', fontSize: 12, lineHeight: 1.6, overflowX: 'auto' }}>
            {activeTab === 'with-erid' ? (
              <div>
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>1. Claude Code wraps up:</span>
                <div style={{ color: 'var(--on-surface-variant)' }}>&gt; create_handoff(task="auth-refactor", summary="JWT verification extracted to jwt_helper.py")</div>
                <div style={{ color: 'var(--green)', marginTop: 4 }}>✔ Handoff recorded. Broadcasted to live Redis bus.</div>
                <br />
                <span style={{ color: 'var(--primary)', fontWeight: 600 }}>2. Cursor opens next session:</span>
                <div style={{ color: 'var(--on-surface-variant)' }}>&gt; catch_up()</div>
                <div style={{ color: 'var(--secondary)' }}>↳ Detected 1 waiting handoff from Claude Code: "JWT verification extracted to jwt_helper.py".</div>
                <div style={{ color: 'var(--green)' }}>✔ Cursor immediately starts writing integration tests without re-analyzing auth!</div>
              </div>
            ) : (
              <div style={{ color: 'var(--on-surface-variant)' }}>
                <span style={{ color: 'var(--error)', fontWeight: 600 }}>Disconnected session:</span>
                <div>&gt; Cursor opens session: Context empty (0 tasks, 0 decisions, 0 memory).</div>
                <div>&gt; Cursor re-scans the entire codebase (spending 85,000 input tokens).</div>
                <div>&gt; Cursor unintentionally rewrites auth.py using different pattern, causing git merge conflicts.</div>
              </div>
            )}
          </div>
        </div>
      </section>
    </div>
  )
}
