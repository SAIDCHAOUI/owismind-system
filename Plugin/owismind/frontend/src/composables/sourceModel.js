// Pure Source Data Explorer model helpers (NO Vue import - node:test testable, F11).
//
// User-filter chip shape (the store's working state):
//   { key, column, op, values }
//   - key:    stable v-for key ('u<n>')
//   - op:     '=' (one value) | 'IN' (several) - cosmetic; the backend re-normalizes
//   - values: the selected distinct values
//
// The /source/rows payload carries the agent's logical KEY + the integer source id +
// a plain-text search + structured {column, op, values} filters. It never names a
// table or a connection - the server resolves the source id to a dataset.

// Minimum effective search length: below this the term is dropped (mirrors the
// backend, which ignores a q shorter than 2 chars after trimming).
export const SOURCE_Q_MIN = 2
// Hard cap on the search string (mirrors the backend q length limit).
export const SOURCE_Q_MAX = 200

// Cosmetic op for a user filter: one value reads as '=', several as 'IN' (the
// backend treats both identically and re-normalizes). CONTRACT: `values` must be
// non-empty - the store removes a chip instead of letting its last value drop.
export function normalizeSourceOp(values) {
  return values.length > 1 ? 'IN' : '='
}

// Build one user-filter chip. `seq` is a monotonically-increasing counter owned by
// the store so every chip keeps a stable, unique v-for key across edits.
export function makeSourceChip(column, values, seq) {
  return {
    key: 'u' + seq,
    column,
    op: normalizeSourceOp(values),
    values: values.slice(),
  }
}

// The effective search term: trimmed, dropped to '' below SOURCE_Q_MIN chars, and
// clamped to SOURCE_Q_MAX (the backend clamps identically). Always a string so the
// payload matches the frozen `q: str` contract.
export function effectiveSourceQuery(q) {
  const trimmed = (q == null ? '' : String(q)).trim()
  if (trimmed.length < SOURCE_Q_MIN) return ''
  return trimmed.slice(0, SOURCE_Q_MAX)
}

// Assemble the /source/rows request body. `sourceId` is the integer id from the
// agent's `sources` list; `chips` are the user filters; `sort` is {column, dir} or
// null. Chips with no column or no values are skipped defensively.
export function buildSourceRowsPayload(agentKey, sourceId, q, chips, page, sort) {
  const filters = []
  for (const c of chips || []) {
    if (!c || !c.column || !Array.isArray(c.values) || !c.values.length) continue
    filters.push({
      column: c.column,
      op: normalizeSourceOp(c.values),
      values: c.values.slice(),
    })
  }
  return {
    agent: agentKey,
    source: sourceId,
    q: effectiveSourceQuery(q),
    filters,
    page: page || 0,
    sort: sort || null,
  }
}
