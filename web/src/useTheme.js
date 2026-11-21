import { useCallback, useEffect, useState } from 'react'

// Light/dark theme with an explicit user choice layered over the OS setting.
//
// The choice is a per-viewer convenience, so it lives in localStorage under
// `erid-theme` ('light' | 'dark'); with nothing stored, `prefers-color-scheme`
// decides. index.html applies the stored choice before first paint (no flash);
// this hook keeps `<html data-theme>` in sync afterwards.
export const THEME_KEY = 'erid-theme'

function readStored() {
  try {
    const v = window.localStorage.getItem(THEME_KEY)
    return v === 'light' || v === 'dark' ? v : null
  } catch {
    return null
  }
}

function systemTheme() {
  try {
    return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
  } catch {
    return 'light'
  }
}

export function resolveTheme(stored, system) {
  return stored || system
}

export function useTheme() {
  const hasWindow = typeof window !== 'undefined'
  const [stored, setStored] = useState(() => (hasWindow ? readStored() : null))
  const [system, setSystem] = useState(() => (hasWindow ? systemTheme() : 'light'))
  const theme = resolveTheme(stored, system)

  // Follow OS changes while the user hasn't picked explicitly.
  useEffect(() => {
    if (!hasWindow || !window.matchMedia) return undefined
    const mq = window.matchMedia('(prefers-color-scheme: dark)')
    const onChange = (e) => setSystem(e.matches ? 'dark' : 'light')
    mq.addEventListener?.('change', onChange)
    return () => mq.removeEventListener?.('change', onChange)
  }, [hasWindow])

  useEffect(() => {
    if (!hasWindow) return
    const root = document.documentElement
    if (stored) root.dataset.theme = stored
    else delete root.dataset.theme
  }, [hasWindow, stored])

  const toggle = useCallback(() => {
    const next = theme === 'dark' ? 'light' : 'dark'
    setStored(next)
    try {
      window.localStorage.setItem(THEME_KEY, next)
    } catch {
      /* storage blocked: the choice just won't persist */
    }
  }, [theme])

  return { theme, toggle }
}
