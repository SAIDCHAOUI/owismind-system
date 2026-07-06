// Pure model for the SCREEN CONTEXT -> AGENT feature (NO Vue import - node:test
// testable, F11). It projects the live Source Data explorer / Evidence "Source data"
// state the user shaped (filters, search, DB row count, computed figures, breakdown)
// into a compact `source_state` snapshot the front sends on /chat/start when the user
// consents. The backend (agents/context.sanitize_source_state) re-validates and bounds
// EVERYTHING; these caps are the exact client mirror so a best-effort payload never
// carries junk. Raw String(v) values only (never formatStatNumber): the block is
// locale-neutral, the agent formats.
//
// A snapshot is meaningful only when the user SHAPED the view. Agent-locked Evidence
// chips define the scope (so they are INCLUDED in the rendered filters) but do NOT open
// the offer on their own; a bare row_count never opens it either.
import {
  chipOp,
  effectiveSourceQuery,
  isTemporalColType,
} from './sourceModel.js'
import { effectiveEvidenceQuery } from './evidenceModel.js'

// Caps mirroring the backend (agents/context.py). Everything is bounded so the block
// can never bloat the prompt.
export const SS_FILTERS = 8
export const SS_VALUES = 5
export const SS_VALUE_CHARS = 80
export const SS_Q_CHARS = 80
export const SS_DATASET_CHARS = 120
export const SS_AGENT_CHARS = 80
export const SS_COLUMN_CHARS = 64
export const SS_DRILL = 6
export const SS_CALC_MEASURES = 8
export const SS_MEASURE_VALUE_CHARS = 40
export const SS_ANALYZE_ROWS = 5

// Whitelisted aggregate / analyze functions + buckets (mirror of the backend tuples).
const AGG_FNS = new Set(['count', 'count_distinct', 'sum', 'avg', 'median', 'min', 'max'])
const ANALYZE_FNS = new Set(['count', 'sum', 'avg'])
const ANALYZE_BUCKETS = new Set(['month', 'quarter', 'year'])

// String projection: coerce, then bound to `cap`. null/undefined -> ''.
function _cap(value, cap) {
  return String(value == null ? '' : value).slice(0, cap)
}

// The column type of one column of the active scope ('' when unknown).
function _colType(columns, name) {
  const c = (columns || []).find((x) => x && x.name === name)
  return c ? c.type : ''
}

// Render one filter chip into the frozen filter shape: { column, op, values, more? }.
// `values` keeps the first SS_VALUES entries (raw, bounded); `more` is the count that
// were cut. A BETWEEN chip carries exactly its 2 boundary values (chipOp guarantees it).
// Returns null when the chip has no column or no values.
function _filterFromChip(chip) {
  if (!chip || !chip.column) return null
  const all = Array.isArray(chip.values) ? chip.values : []
  if (!all.length) return null
  const values = all.slice(0, SS_VALUES).map((v) => _cap(v, SS_VALUE_CHARS))
  const item = { column: _cap(chip.column, SS_COLUMN_CHARS), op: chipOp(chip), values }
  const more = all.length - values.length
  if (more >= 1) item.more = more
  return item
}

// The filter list from a chip array (bounded at SS_FILTERS). Used for BOTH surfaces:
// explorer chips are all user filters; Evidence chips include the agent-locked ones
// (they define the scope of the figures, so they are rendered too).
function _buildFilters(chips) {
  const out = []
  for (const c of chips || []) {
    const f = _filterFromChip(c)
    if (f) out.push(f)
    if (out.length >= SS_FILTERS) break
  }
  return out
}

// The calc block { column, measures: [{ fn, value }] } or null. OMITTED while the
// figures are loading or absent (never a stale figure paired with new filters).
function _buildCalc(state) {
  if (state.calcLoading) return null
  const column = state.calcColumn
  const values = state.calcValues
  if (!column || !values || typeof values !== 'object') return null
  const fns = Array.isArray(state.calcFns) && state.calcFns.length
    ? state.calcFns
    : Object.keys(values)
  const measures = []
  for (const fn of fns) {
    if (!AGG_FNS.has(fn)) continue
    const v = values[fn]
    if (v == null) continue
    measures.push({ fn, value: _cap(v, SS_MEASURE_VALUE_CHARS) })
    if (measures.length >= SS_CALC_MEASURES) break
  }
  if (!measures.length) return null
  return { column: _cap(column, SS_COLUMN_CHARS), measures }
}

// The analyze (breakdown) block or null. OMITTED while loading or with no rows. `bucket`
// is only kept when the group column is temporal (mirror of aggregateSurface.runAnalyze,
// which sends bucket:null for a non-temporal group). measure_column is null for count.
function _buildAnalyze(state, columns) {
  if (state.analyzeLoading) return null
  const group = state.analyzeGroup
  const fn = state.analyzeFn
  if (!group || !ANALYZE_FNS.has(fn)) return null
  const rawRows = Array.isArray(state.analyzeRows) ? state.analyzeRows : []
  const rows = []
  for (const r of rawRows.slice(0, SS_ANALYZE_ROWS)) {
    if (!r || r.key == null || r.m0 == null) continue
    rows.push({ key: _cap(r.key, SS_VALUE_CHARS), value: _cap(r.m0, SS_MEASURE_VALUE_CHARS) })
    if (rows.length >= SS_ANALYZE_ROWS) break
  }
  if (!rows.length) return null
  const temporal = isTemporalColType(_colType(columns, group))
  const bucket = temporal && ANALYZE_BUCKETS.has(state.analyzeBucket) ? state.analyzeBucket : null
  const totals = state.analyzeTotals && state.analyzeTotals.m0 != null
    ? _cap(state.analyzeTotals.m0, SS_MEASURE_VALUE_CHARS)
    : null
  return {
    group: _cap(group, SS_COLUMN_CHARS),
    bucket,
    fn,
    measure_column: fn === 'count' ? null : (state.analyzeMeasureColumn ? _cap(state.analyzeMeasureColumn, SS_COLUMN_CHARS) : null),
    rows,
    total: totals,
    truncated: !!state.analyzeTruncated,
  }
}

// A DB row count kept only when it is a non-negative integer AND not currently loading
// (a stale count paired with new filters would lie). Omitted otherwise.
function _rowCount(state) {
  if (state.totalLoading) return null
  const rc = state.totalCount
  if (rc == null) return null
  const n = Number(rc)
  if (!Number.isFinite(n) || n < 0) return null
  return Math.floor(n)
}

// Assemble the sections shared by both surfaces from a normalized state + columns.
// Returns { filters, q, drill, calc, analyze, row_count } with each key present only
// when it carries data. `drill` is only supplied for the Evidence legacy surface.
function _sections(state, columns, effectiveQuery, drillLabels) {
  const sections = {}
  const filters = _buildFilters(state.chips)
  if (filters.length) sections.filters = filters
  const q = _cap(effectiveQuery, SS_Q_CHARS)
  if (q) sections.q = q
  if (Array.isArray(drillLabels) && drillLabels.length) {
    const drill = []
    for (const d of drillLabels.slice(0, SS_DRILL)) {
      if (!d || !d.column || d.value == null) continue
      drill.push({ column: _cap(d.column, SS_COLUMN_CHARS), value: _cap(d.value, SS_VALUE_CHARS) })
      if (drill.length >= SS_DRILL) break
    }
    if (drill.length) sections.drill = drill
  }
  const calc = _buildCalc(state)
  if (calc) sections.calc = calc
  const analyze = _buildAnalyze(state, columns)
  if (analyze) sections.analyze = analyze
  const rc = _rowCount(state)
  if (rc != null) sections.row_count = rc
  return sections
}

// Build the final snapshot from a surface + dataset + agent + sections, applying the
// meaningful-state gate. `userShaped` is true when the user actually shaped the view
// (excludes agent-locked-chips-only and bare-row_count states). Returns null otherwise.
function _finalize(surface, dataset, agentLabel, sections, userShaped) {
  const ds = _cap(dataset, SS_DATASET_CHARS)
  if (!ds) return null
  const meaningful = userShaped
    || !!sections.q
    || !!sections.drill
    || !!sections.calc
    || !!sections.analyze
  if (!meaningful) return null
  const out = { surface, dataset: ds }
  const agent = _cap(agentLabel, SS_AGENT_CHARS)
  if (agent) out.agent = agent
  if (sections.filters) out.filters = sections.filters
  if (sections.q) out.q = sections.q
  if (sections.drill) out.drill = sections.drill
  if (sections.calc) out.calc = sections.calc
  if (sections.analyze) out.analyze = sections.analyze
  if (sections.row_count != null) out.row_count = sections.row_count
  return out
}

// Snapshot the Source Data explorer state. All chips are user filters, so any chip opens
// the offer. Returns a `source_state` (surface 'explorer') or null when nothing meaningful.
export function snapshotFromExplorer(s) {
  const state = s || {}
  const sections = _sections(state, state.columns, effectiveSourceQuery(state.q), null)
  // Every explorer chip is a user filter; calcColumn chosen / analyze rows also open the
  // offer even before the figures land (the sections themselves omit while loading).
  const userShaped = (Array.isArray(state.chips) && state.chips.length > 0)
    || !!state.calcColumn
    || (!!state.analyzeGroup && Array.isArray(state.analyzeRows) && state.analyzeRows.length > 0)
  return _finalize('explorer', state.activeSourceLabel, state.agentLabel, sections, userShaped)
}

// Snapshot the Evidence "Source data" LEGACY state. Agent-locked chips are INCLUDED in
// the rendered filters (they define the scope) but do NOT open the offer on their own;
// only user-shaped chips (editable / source 'user'), a drill, a search, a calc column or
// an analyze selection do. `evColumns` = the exchange meta columns (temporal detection).
export function snapshotFromEvidence(ev, evColumns) {
  const state = ev || {}
  const drillLabels = Array.isArray(state.drill) ? state.drill : null
  const sections = _sections(state, evColumns, effectiveEvidenceQuery(state.q), drillLabels)
  const dataset = state.selectedTable
    || (Array.isArray(state.sources) && state.sources[0]
      && (state.sources[0].label || state.sources[0].dataset))
    || ''
  const userChip = (state.chips || []).some((c) => c && (c.editable || c.source === 'user'))
  const userShaped = userChip
    || !!state.calcColumn
    || (!!state.analyzeGroup && Array.isArray(state.analyzeRows) && state.analyzeRows.length > 0)
  return _finalize('evidence', dataset, state.agentLabel, sections, userShaped)
}

// Pick the active snapshot with the frozen priority: Evidence panel first (its embedded
// agent sub-mode reuses the explorer state, relabelled surface 'evidence'), else the
// standalone Source Data explorer, else null. `agentLabels` is a { key -> label } map.
export function pickSnapshot({ sourcesState, evidenceState, agentLabels } = {}) {
  const labels = agentLabels || {}
  const ev = evidenceState || {}
  const src = sourcesState || {}
  if (ev.open) {
    const tabKey = typeof ev.sourceTabKey === 'string' ? ev.sourceTabKey : ''
    if (tabKey.indexOf('agent:') === 0) {
      // Embedded agent sub-mode: the Source data tab drives the SOURCES store surface.
      // Reuse the explorer projection but stamp surface 'evidence' + the exchange agent.
      const snap = snapshotFromExplorer({
        ...src,
        agentLabel: labels[ev.agentKey] || src.agentLabel || '',
      })
      if (!snap) return null
      snap.surface = 'evidence'
      return snap
    }
    return snapshotFromEvidence(
      { ...ev, agentLabel: labels[ev.agentKey] || '' },
      ev.columns,
    )
  }
  if (src.open) {
    return snapshotFromExplorer({ ...src, agentLabel: labels[src.agentKey] || src.agentLabel || '' })
  }
  return null
}

// Stable scope signature of a snapshot (for the sticky-per-signature consent). Excludes
// the volatile figures (row_count, calc measure values, analyze rows/total) so a refetch
// of the numbers never churns the decision; a change to any FILTER / search / drill /
// calc column / analyze selection does re-offer.
export function snapshotSignature(snap) {
  if (!snap) return null
  return JSON.stringify([
    snap.surface,
    snap.dataset,
    snap.agent || '',
    (snap.filters || []).map((f) => [f.column, f.op, f.values]),
    snap.q || '',
    (snap.drill || []).map((d) => [d.column, d.value]),
    snap.calc ? snap.calc.column : null,
    snap.analyze
      ? [snap.analyze.group, snap.analyze.bucket, snap.analyze.fn, snap.analyze.measure_column]
      : null,
  ])
}
