/**
 * Matches an actor against the active agent filter tab.
 *
 * @param {string|null|undefined} actor - The actor name, handle, or assignee.
 * @param {string} filter - 'all' | 'human' | 'claude' | 'cursor' | 'codex'
 * @param {string|null} [actorType=null] - Optional explicit actor_type (e.g. from presence)
 * @returns {boolean}
 */
export function matchesAgentFilter(actor, filter = 'all', actorType = null) {
  if (!filter || filter === 'all') return true
  if (actorType === 'human' && filter === 'human') return true
  if (actorType === 'ai' && filter === 'human') return false
  if (!actor) return false

  if (filter === 'human') {
    return !/(claude|cursor|codex|agent|bot)/i.test(actor)
  }
  if (filter === 'claude') return /claude/i.test(actor)
  if (filter === 'cursor') return /cursor/i.test(actor)
  if (filter === 'codex') return /codex/i.test(actor)

  return true
}
