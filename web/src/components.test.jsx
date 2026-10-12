import React from 'react'
import { renderToString } from 'react-dom/server'
import { describe, it, expect } from 'vitest'
import Presence from './components/Presence.jsx'
import TaskList from './components/TaskList.jsx'
import HandoffList from './components/HandoffList.jsx'
import DecisionList from './components/DecisionList.jsx'
import WorkspaceSwitcher from './components/WorkspaceSwitcher.jsx'

describe('Nordic Editorial UI Components', () => {
  describe('Presence component', () => {
    it('renders empty presence placeholder', () => {
      const html = renderToString(<Presence presence={[]} />)
      expect(html).toContain('Presence Feed')
      expect(html).toContain('No active agents')
    })

    it('renders human and AI presence items with Nordic badges', () => {
      const sample = [
        {
          id: 'p1',
          actor_name: 'Razin M',
          actor_type: 'human',
          current_file: 'src/auth.py',
          current_task: 'Refactoring session tokens',
          last_seen: new Date().toISOString(),
        },
        {
          id: 'p2',
          actor_name: 'Claude-3.7',
          actor_type: 'ai',
          current_file: 'src/bridge.py',
          last_seen: new Date().toISOString(),
        },
      ]
      const html = renderToString(<Presence presence={sample} />)
      expect(html).toContain('Razin M')
      expect(html).toContain('Claude-3.7')
      expect(html).toContain('src/auth.py')
      expect(html).toContain('Refactoring session tokens')
      expect(html).toContain('presence-indicator-dot human')
      expect(html).toContain('presence-indicator-dot ai')
    })

    it('filters presence by agent filter', () => {
      const sample = [
        { id: 'p1', actor_name: 'Razin M', actor_type: 'human', last_seen: new Date().toISOString() },
        { id: 'p2', actor_name: 'Claude-3.7', actor_type: 'ai', last_seen: new Date().toISOString() },
      ]
      const html = renderToString(<Presence presence={sample} agentFilter="claude" />)
      expect(html).toContain('Claude-3.7')
      expect(html).not.toContain('Razin M')
    })

    it('renders check in action when client and write credentials exist', () => {
      const html = renderToString(<Presence presence={[]} client={{}} canWrite={true} />)
      expect(html).toContain('Check In')
    })
  })

  describe('TaskList component', () => {
    it('renders tasks with editorial status badges and task IDs', () => {
      const tasks = [
        { id: 'tk10001', title: 'Implement Redis pub/sub backoff', status: 'in_progress', assigned_to: 'claude-3.7' },
        { id: 'tk10002', title: 'Sync git diff schema', status: 'done', assigned_to: 'razin' },
      ]
      const html = renderToString(
        <TaskList tasks={tasks} client={null} canWrite={false} onMutate={() => {}} />
      )
      expect(html).toContain('Active Tasks')
      expect(html).toContain('Implement Redis pub/sub backoff')
      expect(html).toContain('Sync git diff schema')
      expect(html).toContain('tk1000')
      expect(html).toContain('badge in_progress')
      expect(html).toContain('badge done')
      expect(html).toContain('claude-3.7')
    })
  })

  describe('HandoffList component', () => {
    it('renders handoffs with pending badges and actions', () => {
      const handoffs = [
        {
          id: 'h1',
          summary: 'Auth middleware refactor complete',
          status: 'open',
          created_by: 'Claude Code',
          branch: 'feature/auth',
          next_action: 'Run integration test validation',
          created_at: new Date().toISOString(),
        },
      ]
      const html = renderToString(
        <HandoffList handoffs={handoffs} client={null} canWrite={true} onMutate={() => {}} />
      )
      expect(html).toContain('Session Handoffs')
      expect(html).toContain('Auth middleware refactor complete')
      expect(html).toContain('Run integration test validation')
      expect(html).toContain('feature/auth')
      expect(html).toContain('Pending')
      expect(html).toContain('action-required-badge')
    })
  })

  describe('DecisionList component', () => {
    it('renders decisions with reasons and author metadata', () => {
      const decisions = [
        {
          id: 'd1',
          title: 'Use Redis pub/sub for cross-agent event distribution',
          reason: 'Ensures real-time push latency under 50ms across workspaces',
          made_by: 'architect',
          created_at: new Date().toISOString(),
        },
      ]
      const html = renderToString(
        <DecisionList decisions={decisions} client={null} canWrite={false} onMutate={() => {}} />
      )
      expect(html).toContain('Recent Decisions')
      expect(html).toContain('Use Redis pub/sub for cross-agent event distribution')
      expect(html).toContain('architect')
    })
  })

  describe('WorkspaceSwitcher component', () => {
    it('renders workspaces dropdown', () => {
      const workspaces = [{ slug: 'production-api', credential: 'secret' }]
      const html = renderToString(
        <WorkspaceSwitcher
          workspaces={workspaces}
          active={workspaces[0]}
          activeSlug="production-api"
          onSelect={() => {}}
          onSave={() => {}}
          onRemove={() => {}}
        />
      )
      expect(html).toContain('production-api')
      expect(html).toContain('+ New')
    })
  })

  describe('ContinuousContext page', () => {
    it('renders hero and vector topology schematic', async () => {
      const { default: ContinuousContext } = await import('./pages/ContinuousContext.jsx')
      const html = renderToString(<ContinuousContext onNavigateWorkspace={() => {}} />)
      expect(html).toContain('AI agents shouldn’t wake up with amnesia')
      expect(html).toContain('Sub-graph Topology')
      expect(html).toContain('Durable Handoffs')
      expect(html).toContain('Claude Code')
      expect(html).toContain('Cursor IDE')
    })
  })

  describe('LiveWorkspace page', () => {
    it('renders control band, search bar, and active columns', async () => {
      const { default: LiveWorkspace } = await import('./pages/LiveWorkspace.jsx')
      const html = renderToString(
        <LiveWorkspace
          slug="test-hub"
          summary={{ open_task_count: 2, open_handoff_count: 1, active_developers: ['alice'], decision_count: 3 }}
          tasks={[{ id: 't1', title: 'Task 1', status: 'in_progress' }]}
          decisions={[{ id: 'd1', title: 'Decision 1', reason: 'speed' }]}
          handoffs={[{ id: 'h1', summary: 'Handoff 1', status: 'open' }]}
          presence={[{ id: 'p1', actor_name: 'alice', actor_type: 'human', last_seen: new Date().toISOString() }]}
          client={{}}
          credential="key-1"
          error={null}
          isAuthError={false}
          activeSlug="test-hub"
          setTasks={() => {}}
          setDecisions={() => {}}
          setHandoffs={() => {}}
        />
      )
      expect(html).toContain('test-hub')
      expect(html).toContain('Search context in test-hub')
      expect(html).toContain('Open Tasks')
      expect(html).toContain('Pending Handoff')
      expect(html).toContain('Task 1')
      expect(html).toContain('Decision 1')
    })
  })
})

