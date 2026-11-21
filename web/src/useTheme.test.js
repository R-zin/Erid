import { describe, it, expect } from 'vitest'
import { resolveTheme, THEME_KEY } from './useTheme.js'

describe('resolveTheme', () => {
  it('follows the system preference when nothing is stored', () => {
    expect(resolveTheme(null, 'dark')).toBe('dark')
    expect(resolveTheme(null, 'light')).toBe('light')
  })

  it('an explicit choice overrides the system preference', () => {
    expect(resolveTheme('light', 'dark')).toBe('light')
    expect(resolveTheme('dark', 'light')).toBe('dark')
  })

  it('uses the same storage key as the pre-paint script in index.html', async () => {
    const { readFileSync } = await import('node:fs')
    const html = readFileSync(new URL('../index.html', import.meta.url), 'utf8')
    expect(html).toContain(`localStorage.getItem('${THEME_KEY}')`)
  })
})
