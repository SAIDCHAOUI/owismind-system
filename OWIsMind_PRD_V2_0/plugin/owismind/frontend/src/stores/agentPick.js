// Pure: choose the default agent key - the last-used one if still enabled, else the first
// enabled agent (empty string when there are no agents). No Vue / no I/O, so it stays
// unit-testable with node:test (NO INSTALL: no vitest).
export function pickDefaultAgent(agents, lastKey) {
  if (!agents || !agents.length) return ''
  if (lastKey && agents.some((a) => a.key === lastKey)) return lastKey
  return agents[0].key
}
