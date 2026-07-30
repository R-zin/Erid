import { useCallback, useEffect, useState } from 'react'
import { listWorkspaces } from './api.js'

// Workspace-list source decision (#5):
//
// The `GET /api/workspaces` discovery endpoint is being built concurrently and
// is not guaranteed to exist, so the dashboard does NOT depend on it. The
// source of truth is a USER-MANAGED list persisted in localStorage: each entry
// is `{ slug, credential, authType }` (`authType` is 'key' | 'token'). The user
// adds/removes workspaces by slug; credentials are remembered per slug so
// switching is instant. On mount we ALSO attempt a fault-tolerant fetch of
// `/api/workspaces` and merge any returned slugs into the picker (credential
// blank). Every fetch failure is swallowed — discovery is purely additive and
// never blocks or breaks the local list.

const LS_KEY = 'ch_workspaces'
const LS_ACTIVE = 'ch_active_slug'

function readList() {
  try {
    const raw = localStorage.getItem(LS_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed.filter((w) => w && w.slug) : []
  } catch {
    return []
  }
}

function writeList(list) {
  localStorage.setItem(LS_KEY, JSON.stringify(list))
}

// Migrate pre-auth single-workspace storage (ch_slug/ch_key) into the list.
function seedFromLegacy() {
  const slug = localStorage.getItem('ch_slug')
  if (!slug) return []
  const credential = localStorage.getItem('ch_key') || ''
  return [{ slug, credential, authType: 'key' }]
}

export function useWorkspaces() {
  const [workspaces, setWorkspaces] = useState(() => {
    const existing = readList()
    if (existing.length > 0) return existing
    return seedFromLegacy()
  })
  const [activeSlug, setActiveSlug] = useState(
    () => localStorage.getItem(LS_ACTIVE) || readList()[0]?.slug || localStorage.getItem('ch_slug') || '',
  )

  // Optional backend discovery: merge slugs, ignore all failures.
  useEffect(() => {
    let cancelled = false
    listWorkspaces().then((slugs) => {
      if (cancelled || slugs.length === 0) return
      setWorkspaces((prev) => {
        const known = new Set(prev.map((w) => w.slug))
        const added = slugs
          .filter((s) => !known.has(s))
          .map((s) => ({ slug: s, credential: '', authType: 'key' }))
        if (added.length === 0) return prev
        const next = [...prev, ...added]
        writeList(next)
        return next
      })
    })
    return () => {
      cancelled = true
    }
  }, [])

  const persist = useCallback((next) => {
    setWorkspaces(next)
    writeList(next)
  }, [])

  const upsertWorkspace = useCallback(
    ({ slug, credential = '', authType = 'key' }) => {
      slug = (slug || '').trim()
      if (!slug) return
      persist([
        ...workspaces.filter((w) => w.slug !== slug),
        { slug, credential, authType },
      ])
      setActiveSlug(slug)
      localStorage.setItem(LS_ACTIVE, slug)
    },
    [workspaces, persist],
  )

  const removeWorkspace = useCallback(
    (slug) => {
      const next = workspaces.filter((w) => w.slug !== slug)
      persist(next)
      if (slug === activeSlug) {
        const fallback = next[0]?.slug || ''
        setActiveSlug(fallback)
        localStorage.setItem(LS_ACTIVE, fallback)
      }
    },
    [workspaces, activeSlug, persist],
  )

  const selectWorkspace = useCallback(
    (slug) => {
      setActiveSlug(slug)
      localStorage.setItem(LS_ACTIVE, slug)
    },
    [],
  )

  const active = workspaces.find((w) => w.slug === activeSlug) || null

  return {
    workspaces,
    active,
    activeSlug,
    upsertWorkspace,
    removeWorkspace,
    selectWorkspace,
  }
}
