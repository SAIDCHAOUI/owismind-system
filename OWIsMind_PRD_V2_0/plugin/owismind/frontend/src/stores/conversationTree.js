// Pure conversation-tree helpers (no Vue, unit-tested). An exchange = { id, parentId,
// createdAt, ... }. The active path follows, at each node, the override child if set,
// else the LATEST child by createdAt (tiebreak id). A turn's "versions" are its siblings.
const ROOT = '__root__'
const keyOf = (parentId) => parentId || ROOT

function byCreatedAt(a, b) {
  const c = String(a.createdAt || '').localeCompare(String(b.createdAt || ''))
  return c !== 0 ? c : String(a.id || '').localeCompare(String(b.id || ''))
}

export function childrenOf(exchanges, parentId) {
  return exchanges.filter((e) => keyOf(e.parentId) === keyOf(parentId)).sort(byCreatedAt)
}

export function activeChildOf(exchanges, parentId, overrides) {
  const kids = childrenOf(exchanges, parentId)
  if (!kids.length) return null
  const chosen = (overrides || {})[keyOf(parentId)]
  return kids.find((e) => e.id === chosen) || kids[kids.length - 1] // default = latest
}

export function buildActivePath(exchanges, overrides) {
  const out = []
  let parentId = null
  const guard = exchanges.length + 1 // hard stop against any cycle
  for (let i = 0; i < guard; i++) {
    const node = activeChildOf(exchanges, parentId, overrides)
    if (!node) break
    const siblings = childrenOf(exchanges, parentId)
    out.push({ exchange: node, siblings, versionIdx: siblings.findIndex((e) => e.id === node.id) })
    if (!node.id) break // a live leaf with no backend id yet has no children - stop
    parentId = node.id
  }
  return out
}
