// Pure model of the Analyze workspace's measure picker (MeasurePicker.vue): every measure
// the dataset CAN compute, grouped by column TYPE so the list reads at a glance (user ask
// 2026-10-20), plus the search filter and the keyboard stepping. No Vue, no i18n: tested
// under node:test (F11); the component only renders it.
//
// Groups, in reading order (an empty group is dropped):
//   rows   -> the row count (needs no column, the most asked figure)
//   number -> numeric quantity columns: sum, average, median, min, max
//   date   -> temporal columns: min, max (earliest / latest)
//   text   -> everything else, numeric IDENTIFIERS included: distinct values
// The functions per column come from measureSpecForColumn, the SAME rule the builder and
// the backend validation follow, so the picker never offers a measure the server refuses.
import { isNumericColType, isTemporalColType, measureSpecForColumn, measureKey } from './sourceModel.js'

export const MEASURE_GROUP_ORDER = ['rows', 'number', 'date', 'text']

// The picker group of a column, by type (an identifier is never summed: it is text here).
export function measureGroupOf(type, isIdentifier) {
  if (isNumericColType(type) && !isIdentifier) return 'number'
  if (isTemporalColType(type)) return 'date'
  return 'text'
}

// Short i18n key of a function INSIDE its column block ("Sum", not "Sum of Revenues": the
// column is already named above it). `count` keeps its whole phrase ("Row count").
const SHORT_LABEL_KEYS = {
  count: 'src.an.fn.count',
  sum: 'src.calc.sum',
  avg: 'src.calc.avg',
  median: 'src.calc.median',
  min: 'src.calc.min',
  max: 'src.calc.max',
  count_distinct: 'src.calc.distinct',
}
export function measureShortLabelKey(fn) {
  return SHORT_LABEL_KEYS[fn] || ''
}

// Build the grouped offer: [{ kind, columns: [{ name, type, options: [{ fn, column, key }] }] }].
// The rows group holds one pseudo column (name null) carrying the row count. Column order
// inside a group is the dataset's natural order; the REAL column name is kept verbatim
// (F25: proof surface). `isIdentifier(name)` flags identifier-shaped columns.
export function buildMeasureGroups(columns, isIdentifier) {
  const isId = typeof isIdentifier === 'function' ? isIdentifier : () => false
  const byKind = { rows: [], number: [], date: [], text: [] }
  byKind.rows.push({ name: null, type: '', options: [{ fn: 'count', column: null, key: 'count' }] })
  for (const col of Array.isArray(columns) ? columns : []) {
    if (!col || !col.name) continue
    const ident = !!isId(col.name)
    const options = measureSpecForColumn(col.name, col.type, ident)
      .filter((spec) => measureShortLabelKey(spec.fn))
      .map((spec) => ({ fn: spec.fn, column: col.name, key: measureKey({ fn: spec.fn, column: col.name }) }))
    if (!options.length) continue
    byKind[measureGroupOf(col.type, ident)].push({ name: col.name, type: col.type || '', options })
  }
  return MEASURE_GROUP_ORDER
    .filter((kind) => byKind[kind].length)
    .map((kind) => ({ kind, columns: byKind[kind] }))
}

// Filter the groups on a search term (case-insensitive). A column whose NAME matches keeps
// all its functions; otherwise only the options whose rendered label matches survive
// (`labelOf(option)` -> string, e.g. "Sum of Revenues"), so both "revenue" and "sum" find
// "Sum of Revenues". Empty columns and groups are dropped. A blank term returns the input.
export function filterMeasureGroups(groups, term, labelOf) {
  const list = Array.isArray(groups) ? groups : []
  const needle = String(term == null ? '' : term).trim().toLowerCase()
  if (!needle) return list
  const label = typeof labelOf === 'function' ? labelOf : () => ''
  const out = []
  for (const g of list) {
    const columns = []
    for (const c of g.columns) {
      const nameHit = c.name != null && String(c.name).toLowerCase().includes(needle)
      const options = nameHit
        ? c.options
        : c.options.filter((o) => String(label(o) || '').toLowerCase().includes(needle))
      if (options.length) columns.push({ ...c, options })
    }
    if (columns.length) out.push({ kind: g.kind, columns })
  }
  return out
}

// Every option in display order (the keyboard walks this list).
export function flattenMeasureOptions(groups) {
  const out = []
  for (const g of Array.isArray(groups) ? groups : []) {
    for (const c of g.columns) {
      for (const o of c.options) out.push(o)
    }
  }
  return out
}

// Keyboard step over the flat list: the next ENABLED option `step` (+1 / -1) away from
// `current`, wrapping around; `current` -1 starts before the first (step +1) or after the
// last (step -1). `isDisabled(option)` skips what cannot be picked (already measured).
// Returns -1 when nothing is pickable.
export function stepMeasureOption(options, current, step, isDisabled) {
  const list = Array.isArray(options) ? options : []
  const n = list.length
  if (!n) return -1
  const skip = typeof isDisabled === 'function' ? isDisabled : () => false
  const dir = step < 0 ? -1 : 1
  let i = current >= 0 && current < n ? current : (dir > 0 ? -1 : n)
  for (let k = 0; k < n; k += 1) {
    i = (i + dir + n) % n
    if (!skip(list[i])) return i
  }
  return -1
}
