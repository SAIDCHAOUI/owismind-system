// Per-(agent, dataset) VIEW MEMORY for the Source Data explorer (NO Vue import -
// node:test testable, F11). Keeps a user's working view (filters + search + sort +
// Calculate selection) alive across panel close/reopen and agent switches, WITHIN the
// browser session only (no localStorage - the store is a singleton per app session).
//
// The store persists a snapshot at every view-destroying transition and restores it when
// the same (agent, dataset) meta loads again, so filters never silently vanish. All
// branching lives here (the Pinia store has no node tests): the store only wires it.
//
// A "view" is the plain shape { chips, q, sort, calcColumn, calcFns }:
//   - chips:      user-filter chips  [{ key, column, op, values[] }]
//   - q:          raw search text (string)
//   - sort:       { column, dir } | null
//   - calcColumn: the Calculate zone column | null
//   - calcFns:    selected measure fn keys (string[])
import { statsSpecFor, defaultCalcFnsFor } from './sourceModel.js'

// The composite key. A NUL byte separates the agent key from the source id so no agent
// key / id combination can ever collide (a NUL cannot appear in either token).
function _key(agentKey, sourceId) {
  return String(agentKey) + '\u0000' + String(sourceId)
}

// Deep-copy a view so neither save nor restore ever hands out a reference the caller (or
// a later restore) could mutate in place. The shape is fixed, so a targeted clone is both
// exact and cheap: primitives pass through, arrays are sliced, nested chip values copied.
function _cloneView(view) {
  if (!view) return null
  return {
    chips: Array.isArray(view.chips)
      ? view.chips.map((c) => ({
          key: c && c.key,
          column: c && c.column,
          op: c && c.op,
          values: c && Array.isArray(c.values) ? c.values.slice() : [],
        }))
      : [],
    q: view.q == null ? '' : String(view.q),
    sort: view.sort && view.sort.column
      ? { column: view.sort.column, dir: view.sort.dir }
      : null,
    calcColumn: view.calcColumn == null ? null : view.calcColumn,
    calcFns: Array.isArray(view.calcFns) ? view.calcFns.slice() : [],
  }
}

// A bounded, session-scoped memory of per-(agent, dataset) views. `cap` bounds the number
// of remembered views (FIFO eviction of the oldest insertion past the cap) so a long
// browsing session can never grow the map without bound. A Map preserves insertion order,
// which is exactly the eviction order we want.
export function createViewMemory(cap = 24) {
  const store = new Map()

  // Save (deep-copied) the view for one (agent, dataset). Updating an existing key keeps
  // its original insertion slot (no churn); a brand-new key past the cap evicts the oldest.
  function save(agentKey, sourceId, view) {
    const key = _key(agentKey, sourceId)
    if (store.has(key)) {
      store.set(key, _cloneView(view))
      return
    }
    if (store.size >= cap) {
      const oldest = store.keys().next().value
      if (oldest !== undefined) store.delete(oldest)
    }
    store.set(key, _cloneView(view))
  }

  // Return a fresh deep copy of the remembered view for one (agent, dataset), or null.
  function restore(agentKey, sourceId) {
    const v = store.get(_key(agentKey, sourceId))
    return v ? _cloneView(v) : null
  }

  // Forget one (agent, dataset) view (used when its live view became trivial, so clearing
  // filters then leaving does not resurrect stale chips on return).
  function remove(agentKey, sourceId) {
    store.delete(_key(agentKey, sourceId))
  }

  function clear() {
    store.clear()
  }

  return { save, restore, remove, clear }
}

// --- Pure sanitizers applied on RESTORE (columns can have changed since the save) -------

// Keep only well-formed chips whose column still exists in the freshly loaded columns.
// `op` is cosmetic (the backend re-derives '='/'IN' from the value count, BETWEEN is kept
// verbatim by the store's chipOp), so a chip is kept on column + non-empty values alone,
// whatever its op string. Returns a fresh array with copied values (never shared refs).
export function sanitizeRestoredChips(chips, columns) {
  const names = new Set((columns || []).map((c) => c && c.name))
  const out = []
  for (const c of chips || []) {
    if (!c || !c.column || !names.has(c.column)) continue
    if (!Array.isArray(c.values) || !c.values.length) continue
    out.push({
      key: c.key,
      column: c.column,
      op: c.op,
      values: c.values.slice(),
    })
  }
  return out
}

// Null a restored sort unless its column still exists and its direction is a valid
// 'asc' | 'desc' (anything else would produce an undefined ORDER BY server-side).
export function sanitizeRestoredSort(sort, columns) {
  if (!sort || !sort.column) return null
  const names = new Set((columns || []).map((c) => c && c.name))
  if (!names.has(sort.column)) return null
  if (sort.dir !== 'asc' && sort.dir !== 'desc') return null
  return { column: sort.column, dir: sort.dir }
}

// Sanitize the restored Calculate selection against the freshly loaded columns.
// Returns { column, fns }:
//   - column is null (and fns empty) when the remembered column no longer exists,
//   - otherwise fns is the remembered subset filtered to statsSpecFor(type) ORDER (never
//     the stored order; drops fns that type no longer offers), falling back to
//     defaultCalcFnsFor(type) when nothing survives so a live column always shows figures.
export function sanitizeRestoredCalc(calcColumn, calcFns, columns) {
  if (!calcColumn) return { column: null, fns: [] }
  const col = (columns || []).find((c) => c && c.name === calcColumn)
  if (!col) return { column: null, fns: [] }
  const type = col.type
  const wanted = new Set(calcFns || [])
  let fns = statsSpecFor(type).map((s) => s.fn).filter((fn) => wanted.has(fn))
  if (!fns.length) fns = defaultCalcFnsFor(type)
  return { column: calcColumn, fns }
}
