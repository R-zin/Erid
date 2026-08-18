import { useCallback, useEffect, useState } from 'react'
import { listWorkspaces } from './api.js'

// Workspace-list source decision:
//
// The source of truth is a USER-MANAGED list: the user adds/removes workspaces
// by slug, and each one's credential is remembered so switching is instant. On
// mount we ALSO make a fault-tolerant fetch of `GET /api/workspaces` and merge
// any returned slugs into the picker (credential blank). Every fetch failure is
// swallowed — discovery is purely additive and never blocks the local list.
//
// Storage is split deliberately:
//
//   localStorage   the workspace list — `{ slug, authType }` only, plus the
//                  active slug. Non-secret, so it survives restarts and the
//                  picker stays stable.
//   sessionStorage the credentials — `{ [slug]: credential }`, scoped to this
//                  tab session and gone when the tab closes.
//
// Credentials are workspace API keys and bearer JWTs; anything in localStorage
// persists indefinitely and is readable by any script on the origin, so a
// single XSS would exfiltrate every credential the user had ever entered.
// Tab-scoped storage is the strongest the browser offers here — there is no web
// equivalent of the VS Code extension's SecretStorage
// (editors/vscode/src/extension.ts) short of moving to an httpOnly session
// cookie. The cost is re-entering credentials in a new tab.

const LS_KEY = 'ch_workspaces' // [{ slug, authType }] — never credentials
const LS_ACTIVE = 'ch_active_slug'
const SS_CREDS = 'ch_credentials' // { [slug]: credential } — tab session only

function readCredentials() {
  try {
    const parsed = JSON.parse(sessionStorage.getItem(SS_CREDS) || 'null')
    return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed : {}
  } catch {
    return {}
  }
}

function writeCredentials(map) {
  try {
    sessionStorage.setItem(SS_CREDS, JSON.stringify(map))
  } catch {
    // Storage disabled (private mode / quota). The session simply stays
    // unauthenticated rather than the dashboard failing to render.
  }
}

function readList() {
  let entries = []
  try {
    const parsed = JSON.parse(localStorage.getItem(LS_KEY) || 'null')
    entries = Array.isArray(parsed) ? parsed.filter((w) => w && w.slug) : []
  } catch {
    return []
  }
  // One-time migration: earlier builds persisted `credential` in localStorage.
  // Move any found into sessionStorage and rewrite the list without them, so an
  // upgrade doesn't silently leave old secrets behind on disk.
  const stale = entries.filter((w) => w.credential)
  if (stale.length > 0) {
    const creds = readCredentials()
    for (const w of stale) creds[w.slug] = w.credential
    writeCredentials(creds)
    entries = entries.map(({ slug, authType }) => ({ slug, authType: authType || 'key' }))
    writeList(entries)
  }
  const creds = readCredentials()
  return entries.map(({ slug, authType }) => ({
    slug,
    authType: authType || 'key',
    credential: creds[slug] || '',
  }))
}

// Persists the list (slug + authType) and the credentials to their separate
// stores. Always call this rather than touching either store directly.
function writeList(list) {
  localStorage.setItem(
    LS_KEY,
    JSON.stringify(list.map(({ slug, authType }) => ({ slug, authType: authType || 'key' }))),
  )
  writeCredentials(Object.fromEntries(list.filter((w) => w.credential).map((w) => [w.slug, w.credential])))
}

// Migrate pre-auth single-workspace storage (ch_slug/ch_key) into the list.
function seedFromLegacy() {
  const slug = localStorage.getItem('ch_slug')
  if (!slug) return []
  const credential = localStorage.getItem('ch_key') || ''
  if (credential) {
    writeCredentials({ ...readCredentials(), [slug]: credential })
    localStorage.removeItem('ch_key') // never leave a secret in localStorage
  }
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
