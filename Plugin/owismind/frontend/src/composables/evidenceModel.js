// Pure Evidence Studio model helpers (NO Vue import - node:test testable, F11).
//
// Local chip shape (the store's editable working state):
//   { key, id, column, op, values, editable, source }
//   - key:      stable v-for key ('a<id>' agent chips, 'u<n>' user-added)
//   - id:       server predicate id (agent chips) or null (user-added)
//   - editable: =/IN chips (value-editable via the distinct picker)
//   - source:   'agent' | 'user'
//
// The /evidence/rows payload NEVER carries SQL: editable chips travel as
// structured {column, op, values} filters; locked agent chips travel as kept
// ids only (the backend re-derives them from the stored SQL by id).

// Minimum / maximum effective length of the exchange-table search term. Below the
// min the term is dropped (mirrors the backend, which ignores a q shorter than 2
// chars after trimming); above the max it is clamped. Identical grammar to the
// Source Explorer q so both search boxes behave the same.
export const EVIDENCE_Q_MIN = 2
export const EVIDENCE_Q_MAX = 200
// Fallback window size when a call omits `limit` (the store always passes an
// explicit 100 / 20). Mirrors the backend's default limit.
export const EVIDENCE_DEFAULT_LIMIT = 50

// The effective search term: trimmed, dropped to '' below EVIDENCE_Q_MIN chars,
// and clamped to EVIDENCE_Q_MAX (the backend clamps identically). Always a string.
export function effectiveEvidenceQuery(q) {
  const trimmed = (q == null ? '' : String(q)).trim()
  if (trimmed.length < EVIDENCE_Q_MIN) return ''
  return trimmed.slice(0, EVIDENCE_Q_MAX)
}

export function chipsFromMeta(meta) {
  const chips = meta && Array.isArray(meta.chips) ? meta.chips : []
  return chips.map((c) => ({
    key: 'a' + c.id,
    id: c.id,
    column: c.column,
    op: c.op,
    values: Array.isArray(c.values) ? c.values.slice() : [],
    editable: !!c.editable,
    source: 'agent',
  }))
}

// Cosmetic op for an edited/user chip: one value reads as '=', several as 'IN'
// (the backend treats both identically and re-normalizes anyway).
// CONTRACT: `values` must be non-empty - the backend rejects an '=' filter
// without exactly one value, so the store removes a chip instead of letting its
// last value be deselected.
export function normalizeEditableOp(values) {
  return values.length > 1 ? 'IN' : '='
}

// Assemble the /evidence/rows request body. Pagination is limit/offset (v2):
// `limit` is the window size (fresh load 100, "load more" 20), `offset` the
// running count of already-loaded rows; the server clamps both. `drill`, `table`
// and `q` are OPTIONAL trailing arguments (in that order) so every legacy
// positional call keeps working and each key is added only when meaningful.
export function buildRowsPayload(exchangeId, chips, includeAdvanced, limit, offset, sort, drill, table, q) {
  const filters = []
  const keptIds = []
  for (const c of chips) {
    if (c.editable || c.source === 'user') {
      filters.push({ column: c.column, op: c.op === '=' ? '=' : 'IN', values: c.values.slice() })
    } else if (c.id != null) {
      keptIds.push(c.id)
    }
  }
  const payload = {
    exchange_id: exchangeId,
    filters,
    kept_ids: keptIds,
    include_advanced: !!includeAdvanced,
    limit: limit || EVIDENCE_DEFAULT_LIMIT,
    offset: offset || 0,
    sort: sort || null,
  }
  // Drill-down (trust layer v2): only {column, value} pairs travel - the server
  // re-derives the drillable group keys from the STORED SQL and 400s anything
  // else, so this list is a request, never an authority.
  if (Array.isArray(drill) && drill.length) {
    payload.drill = drill.map((d) => ({ column: d.column, value: d.value }))
  }
  // Source-table selector (multi-table SQL): only a dataset NAME travels - the
  // server matches it against the SQL's own set of matched tables and falls back
  // to the first when unknown. Absent / empty -> default (first matched) table.
  if (typeof table === 'string' && table) {
    payload.table = table
  }
  // Full-text search over ALL columns of the active exchange table: only the
  // effective (>= 2 chars, folded, clamped) form travels; below the threshold no
  // `q` key is added so the server returns the unsearched window.
  const cleanQ = effectiveEvidenceQuery(q)
  if (cleanQ) {
    payload.q = cleanQ
  }
  return payload
}

// Map ONE captured-result row to drill labels: pair each drillable column
// (server-derived meta.drilldown.columns) with the row's value at that column's
// index in the captured result. The name lookup is case-insensitive because the
// capture keeps the agent's SQL aliases while drilldown columns come from the
// live colmap - casing may differ for the same column. Returns null (callers
// abort SILENTLY) when ANY column cannot be mapped or its cell is unusable: a
// partial drill would quietly lie about the scope of the source rows.
// `cap` mirrors the backend's 8-entry limit on the /evidence/rows `drill` list.
export function buildDrillLabels(columns, resultColumns, row, cap) {
  const max = cap == null ? 8 : cap
  if (!Array.isArray(columns) || columns.length === 0) return null
  if (!Array.isArray(resultColumns) || !Array.isArray(row)) return null
  const byName = new Map()
  for (let i = 0; i < resultColumns.length; i++) {
    const k = String(resultColumns[i]).toLowerCase()
    if (!byName.has(k)) byName.set(k, i) // first occurrence wins (deterministic)
  }
  // More drillable columns than the backend accepts per request: a truncated
  // drill would show a SUPERSET of the group under a "source rows" banner -
  // abort instead of lying (CONTRACT-01; the backend refuses this case too).
  if (columns.length > max) return null
  const labels = []
  for (const column of columns) {
    const idx = byName.get(String(column).toLowerCase())
    if (idx == null) return null
    const value = row[idx]
    // Only what the /evidence/rows drill contract accepts (str | finite number
    // | bool | null) may travel: a missing cell, an object or a non-finite
    // number means this captured row cannot prove the drill - abort.
    if (value === undefined) return null
    if (typeof value === 'number' && !Number.isFinite(value)) return null
    if (value !== null && typeof value === 'object') return null
    labels.push({ column, value })
  }
  return labels
}

// Order-stable, type-faithful chip-state fingerprint (positional tuples - no
// object-key-order pitfalls). Deliberately sensitive to VALUE ORDER inside a
// chip: re-adding a removed value may read as "modified", which is acceptable
// for a badge + reset affordance ("touched = modified").
function signature(chips, includeAdvanced) {
  return JSON.stringify([
    chips.map((c) => [c.source, c.id, c.column, c.op, c.values]),
    !!includeAdvanced,
  ])
}

// True when the local chip state no longer matches the agent's stored scope
// (drives the "modified" badge + the "agent version" reset button).
export function isModified(meta, chips, includeAdvanced) {
  const baseAdvanced = !!(meta && meta.advanced && meta.advanced.present)
  return signature(chipsFromMeta(meta), baseAdvanced) !== signature(chips, includeAdvanced)
}

// The exchange to auto-open Evidence Studio for when (re)entering a conversation:
// the LAST turn of the active path whose answer produced at least one successful
// SQL (same predicate as the end-of-run auto-open in chat.js) and has a persisted
// exchange id. `turns` is the chat store's active-path array ({ exchange } rows);
// returns the exchange id or null when the conversation has nothing to prove.
export function lastEvidenceExchangeId(turns) {
  if (!Array.isArray(turns)) return null
  for (let i = turns.length - 1; i >= 0; i--) {
    const ex = turns[i] && turns[i].exchange
    if (!ex || ex.id == null) continue
    const v = ex.version
    if (v && Array.isArray(v.sql) && v.sql.some((q) => q && q.success)) return ex.id
  }
  return null
}
