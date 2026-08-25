import { describe, it, expect } from 'vitest'
import { applyEvent, upsertById } from './useWorkspace.js'

// Capture state through plain setter closures, mirroring React's setState(fn).
function makeStore(initial) {
  let state = initial
  return {
    set: (fn) => {
      state = fn(state)
    },
    get: () => state,
  }
}

function wireSetters({ tasks = [], decisions = [], presence = [] } = {}) {
  const t = makeStore(tasks)
  const d = makeStore(decisions)
  const p = makeStore(presence)
  return {
    setters: { setTasks: t.set, setDecisions: d.set, setPresence: p.set },
    stores: { t, d, p },
  }
}

describe('upsertById', () => {
  it('appends a new item', () => {
    expect(upsertById([{ id: 1 }], { id: 2 })).toEqual([{ id: 1 }, { id: 2 }])
  })

  it('replaces an existing item in place', () => {
    expect(upsertById([{ id: 1, v: 'a' }], { id: 1, v: 'b' })).toEqual([{ id: 1, v: 'b' }])
  })
})

describe('applyEvent', () => {
  it('upserts on task_created and task_updated', () => {
    const { setters, stores } = wireSetters()
    applyEvent({ type: 'task_created', data: { id: 't1', title: 'one' } }, setters)
    applyEvent({ type: 'task_updated', data: { id: 't1', title: 'one', status: 'done' } }, setters)
    expect(stores.t.get()).toEqual([{ id: 't1', title: 'one', status: 'done' }])
  })

  it('removes on task_deleted (payload is {id, workspace_id})', () => {
    const { setters, stores } = wireSetters({ tasks: [{ id: 't1' }, { id: 't2' }] })
    applyEvent({ type: 'task_deleted', data: { id: 't1', workspace_id: 'w' } }, setters)
    expect(stores.t.get()).toEqual([{ id: 't2' }])
  })

  it('prepends on decision_created and dedupes by id', () => {
    const { setters, stores } = wireSetters({ decisions: [{ id: 'd1' }] })
    applyEvent({ type: 'decision_created', data: { id: 'd2', title: 'new' } }, setters)
    applyEvent({ type: 'decision_created', data: { id: 'd2', title: 'new2' } }, setters)
    expect(stores.d.get()).toEqual([{ id: 'd2', title: 'new2' }, { id: 'd1' }])
  })

  it('removes on decision_deleted', () => {
    const { setters, stores } = wireSetters({ decisions: [{ id: 'd1' }, { id: 'd2' }] })
    applyEvent({ type: 'decision_deleted', data: { id: 'd2', workspace_id: 'w' } }, setters)
    expect(stores.d.get()).toEqual([{ id: 'd1' }])
  })

  it('upserts on presence_updated', () => {
    const { setters, stores } = wireSetters({ presence: [{ id: 'p1', actor_name: 'a' }] })
    applyEvent({ type: 'presence_updated', data: { id: 'p1', actor_name: 'a', current_file: 'x' } }, setters)
    expect(stores.p.get()).toEqual([{ id: 'p1', actor_name: 'a', current_file: 'x' }])
  })

  it('ignores unknown types (incl. the server ping keepalive) without touching state', () => {
    const { setters, stores } = wireSetters({
      tasks: [{ id: 't1' }],
      decisions: [{ id: 'd1' }],
      presence: [{ id: 'p1' }],
    })
    applyEvent({ type: 'ping' }, setters)
    applyEvent({ type: 'some_future_event', data: { id: 'z' } }, setters)
    expect(stores.t.get()).toEqual([{ id: 't1' }])
    expect(stores.d.get()).toEqual([{ id: 'd1' }])
    expect(stores.p.get()).toEqual([{ id: 'p1' }])
  })
})
