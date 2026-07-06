// Plugin/owismind/frontend/test/sourceModel.test.js
// Pure Source Data Explorer model (composables/sourceModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  normalizeSourceOp,
  makeSourceChip,
  effectiveSourceQuery,
  chipsToFilters,
  buildSourceRowsPayload,
  statsSpecFor,
  defaultCalcFnsFor,
  monthRangeToBetween,
  monthRangeToBetweenLexical,
  betweenValuesToMonthRange,
  looksLikeIsoDateValues,
  SOURCE_Q_MIN,
  SOURCE_Q_MAX,
  SOURCE_DEFAULT_LIMIT,
} from '../src/composables/sourceModel.js'
import { extraMessages } from '../src/i18n/extra.js'

test('normalizeSourceOp: single value = "=", several = "IN"', () => {
  assert.equal(normalizeSourceOp(['x']), '=')
  assert.equal(normalizeSourceOp(['x', 'y']), 'IN')
})

test('makeSourceChip: stable key, normalized op, cloned values', () => {
  const values = ['A']
  const chip = makeSourceChip('country', values, 3)
  assert.equal(chip.key, 'u3')
  assert.equal(chip.column, 'country')
  assert.equal(chip.op, '=')
  assert.deepEqual(chip.values, ['A'])
  values.push('B')
  assert.equal(chip.values.length, 1) // no aliasing with the source array
  assert.equal(makeSourceChip('c', ['A', 'B'], 4).op, 'IN')
})

test('chipsToFilters: shapes chips to {column, op, values}, skips empty, keeps BETWEEN', () => {
  const chips = [
    { key: 'u1', column: 'country', op: '=', values: ['FR'] },
    { key: 'u2', column: 'solution', op: 'IN', values: ['OBS', 'OCD'] },
    { key: 'u3', column: 'created', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31'] },
    { key: 'u4', column: '', values: ['x'] }, // no column -> skipped
    { key: 'u5', column: 'c', values: [] }, // no values -> skipped
  ]
  assert.deepEqual(chipsToFilters(chips), [
    { column: 'country', op: '=', values: ['FR'] },
    { column: 'solution', op: 'IN', values: ['OBS', 'OCD'] },
    { column: 'created', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31'] },
  ])
  assert.deepEqual(chipsToFilters(null), [])
})

test('effectiveSourceQuery: trims, drops below the min, clamps to the max', () => {
  assert.equal(effectiveSourceQuery('  ab '), 'ab')
  assert.equal(effectiveSourceQuery('a'), '') // 1 char < SOURCE_Q_MIN
  assert.equal(effectiveSourceQuery('  '), '') // whitespace only
  assert.equal(effectiveSourceQuery(null), '')
  assert.equal(effectiveSourceQuery(undefined), '')
  assert.equal(SOURCE_Q_MIN, 2)
  const long = 'x'.repeat(SOURCE_Q_MAX + 50)
  assert.equal(effectiveSourceQuery(long).length, SOURCE_Q_MAX)
})

test('buildSourceRowsPayload: full shape per the frozen contract (limit/offset)', () => {
  const chips = [
    makeSourceChip('country', ['DZ'], 1),
    makeSourceChip('phase', ['ACTUALS', 'BUDGET'], 2),
  ]
  const p = buildSourceRowsPayload('agentA', 3, 'algerie', chips, 20, 40, { column: 'total', dir: 'desc' })
  assert.equal(p.agent, 'agentA')
  assert.equal(p.source, 3)
  assert.equal(p.q, 'algerie')
  assert.deepEqual(p.filters, [
    { column: 'country', op: '=', values: ['DZ'] },
    { column: 'phase', op: 'IN', values: ['ACTUALS', 'BUDGET'] },
  ])
  assert.equal(p.limit, 20)
  assert.equal(p.offset, 40)
  assert.ok(!('page' in p)) // the page index is gone from the contract
  assert.deepEqual(p.sort, { column: 'total', dir: 'desc' })
})

test('buildSourceRowsPayload: q below the threshold becomes an empty string', () => {
  const p = buildSourceRowsPayload('agentA', 0, 'a', [], 100, 0, null)
  assert.equal(p.q, '')
  assert.deepEqual(p.filters, [])
  assert.equal(p.limit, 100)
  assert.equal(p.offset, 0)
  assert.equal(p.sort, null)
})

test('buildSourceRowsPayload: op is derived from the value count, not a stale chip op', () => {
  // A chip whose op says '=' but that carries two values must still travel as 'IN'.
  const chip = { key: 'u1', column: 'phase', op: '=', values: ['A', 'B'] }
  const p = buildSourceRowsPayload('agentA', 1, '', [chip], 100, 0, null)
  assert.deepEqual(p.filters, [{ column: 'phase', op: 'IN', values: ['A', 'B'] }])
})

test('buildSourceRowsPayload: skips empty / malformed chips', () => {
  const chips = [
    { key: 'u1', column: 'ok', op: '=', values: ['v'] },
    { key: 'u2', column: '', op: '=', values: ['v'] }, // no column
    { key: 'u3', column: 'noval', op: '=', values: [] }, // no values
    null,
  ]
  const p = buildSourceRowsPayload('agentA', 1, '', chips, 100, 0, null)
  assert.deepEqual(p.filters, [{ column: 'ok', op: '=', values: ['v'] }])
})

test('buildSourceRowsPayload: defaults for omitted limit / offset / sort', () => {
  const p = buildSourceRowsPayload('agentA', 2, '', undefined, undefined, undefined, undefined)
  assert.equal(p.limit, SOURCE_DEFAULT_LIMIT) // fallback window when no limit is passed
  assert.equal(p.offset, 0)
  assert.equal(p.sort, null)
  assert.deepEqual(p.filters, [])
})

test('buildSourceRowsPayload: does not alias the chip values array', () => {
  const chip = makeSourceChip('c', ['A'], 1)
  const p = buildSourceRowsPayload('agentA', 1, '', [chip], 100, 0, null)
  p.filters[0].values.push('B')
  assert.equal(chip.values.length, 1)
})

// --- i18n contract: every Source Explorer key exists in fr + en ----------------------

const SRC_KEYS = [
  'ev.tab.sources', 'ev.table.cols',
  'src.cta.title', 'src.cta.hint', 'src.panel.title', 'src.dataset_label',
  'src.search.placeholder', 'src.search.min', 'src.search.go',
  'src.filters.title', 'src.filters.add', 'src.filters.clear', 'src.filters.remove',
  'src.picker.empty', 'src.picker.truncated', 'src.picker.max', 'src.picker.apply',
  'src.loading', 'src.error', 'src.retry', 'src.empty',
  'src.loaded', 'src.more', 'src.loadingMore', 'src.cols',
]

test('extra.js covers every Source Explorer key (fr + en)', () => {
  for (const loc of ['fr', 'en']) {
    for (const key of SRC_KEYS) {
      const v = extraMessages[loc][key]
      assert.equal(typeof v, 'string', loc + ' missing ' + key)
      assert.ok(v.length > 0, loc + ' empty ' + key)
    }
  }
})

// --- Calculate zone: default measure subset per column type --------------------

test('defaultCalcFnsFor: numeric -> [sum], temporal -> [min,max], other -> [count_distinct]', () => {
  // Numeric storage + PostgreSQL type names.
  for (const t of ['int', 'bigint', 'float', 'double', 'decimal', 'numeric', 'money']) {
    assert.deepEqual(defaultCalcFnsFor(t), ['sum'], 'numeric ' + t)
  }
  // Temporal type names (bare "time" is NOT temporal - falls through to the default).
  for (const t of ['date', 'datetime', 'timestamp', 'timestamptz']) {
    assert.deepEqual(defaultCalcFnsFor(t), ['min', 'max'], 'temporal ' + t)
  }
  // Anything else (text, boolean, unknown, empty).
  for (const t of ['string', 'boolean', 'time', 'geopoint', '', null, undefined]) {
    assert.deepEqual(defaultCalcFnsFor(t), ['count_distinct'], 'other ' + t)
  }
})

test('defaultCalcFnsFor: every default fn is one the column type actually offers', () => {
  for (const t of ['int', 'date', 'string', 'boolean', '']) {
    const offered = new Set(statsSpecFor(t).map((s) => s.fn))
    for (const fn of defaultCalcFnsFor(t)) {
      assert.ok(offered.has(fn), t + ' default ' + fn + ' not in its spec')
    }
  }
})

// --- Date-like STRING columns: sniffing + TEXT-safe lexical BETWEEN bounds --------

test('looksLikeIsoDateValues: YYYY-MM prefix with optional day/time tail -> true', () => {
  assert.equal(looksLikeIsoDateValues(['2025-01', '2025-02', '2024-12']), true)
  assert.equal(looksLikeIsoDateValues(['2025-01-15', '2025-02-28']), true)
  assert.equal(looksLikeIsoDateValues(['2025-01-15T00:00:00', '2025-02-01 09:30']), true)
  // Mixed month + full timestamp forms in the same window.
  assert.equal(looksLikeIsoDateValues(['2025-01', '2025-02-28T23:59:59.999']), true)
})

test('looksLikeIsoDateValues: nulls / empties are ignored, all-empty -> false', () => {
  assert.equal(looksLikeIsoDateValues([null, '2025-01', '', '2025-02']), true)
  assert.equal(looksLikeIsoDateValues([null, null, '']), false)
  assert.equal(looksLikeIsoDateValues([]), false)
  assert.equal(looksLikeIsoDateValues(null), false)
})

test('looksLikeIsoDateValues: any non-date value -> false', () => {
  assert.equal(looksLikeIsoDateValues(['2025-01', 'FR', '2025-02']), false)
  assert.equal(looksLikeIsoDateValues(['2025', '2026']), false) // year only, no month
  assert.equal(looksLikeIsoDateValues(['2025/01', '2025/02']), false) // wrong separator
  assert.equal(looksLikeIsoDateValues(['25-01']), false) // 2-digit year
  assert.equal(looksLikeIsoDateValues(['OBS', 'OCD']), false)
})

test('monthRangeToBetweenLexical: TEXT-safe bounds YYYY-MM .. YYYY-MM-99', () => {
  assert.deepEqual(monthRangeToBetweenLexical('2025-01', '2025-03'), {
    start: '2025-01', end: '2025-03-99',
  })
  // Reversed From > To is swapped (same span).
  assert.deepEqual(monthRangeToBetweenLexical('2025-03', '2025-01'), {
    start: '2025-01', end: '2025-03-99',
  })
  // Single-month range.
  assert.deepEqual(monthRangeToBetweenLexical('2024-12', '2024-12'), {
    start: '2024-12', end: '2024-12-99',
  })
  // Malformed input -> null (apply stays disabled).
  assert.equal(monthRangeToBetweenLexical('2025-13', '2025-03'), null)
  assert.equal(monthRangeToBetweenLexical('', '2025-03'), null)
  assert.equal(monthRangeToBetweenLexical('2025-01', 'x'), null)
})

test('monthRangeToBetweenLexical: bounds order real text values correctly (both collations)', () => {
  const { start, end } = monthRangeToBetweenLexical('2025-01', '2025-03')
  // In-range month strings and full ISO days of the span sit within [start, end].
  const inRange = ['2025-01', '2025-01-01', '2025-02-15', '2025-03', '2025-03-31',
    '2025-03-31T23:59:59.999']
  for (const v of inRange) {
    assert.ok(start <= v && v <= end, 'byte-wise includes ' + v)
  }
  // The month before and the month after the span fall outside.
  for (const v of ['2024-12', '2024-12-31', '2025-04', '2025-04-01']) {
    assert.ok(!(start <= v && v <= end), 'byte-wise excludes ' + v)
  }
  // Punctuation-insensitive collation approximation: drop '-' then compare the digit run.
  const strip = (s) => s.replace(/-/g, '')
  const s2 = strip(start)
  const e2 = strip(end)
  for (const v of inRange) assert.ok(s2 <= strip(v) && strip(v) <= e2, 'digit-run includes ' + v)
  for (const v of ['2024-12', '2025-04-01']) {
    assert.ok(!(s2 <= strip(v) && strip(v) <= e2), 'digit-run excludes ' + v)
  }
})

test('betweenValuesToMonthRange: round-trips BOTH bound styles', () => {
  // Calendar-precise bounds (temporal columns).
  const cal = monthRangeToBetween('2025-01', '2025-03')
  assert.deepEqual(betweenValuesToMonthRange([cal.start, cal.end]), { from: '2025-01', to: '2025-03' })
  // TEXT-safe lexical bounds (string columns).
  const lex = monthRangeToBetweenLexical('2025-01', '2025-03')
  assert.deepEqual(betweenValuesToMonthRange([lex.start, lex.end]), { from: '2025-01', to: '2025-03' })
  // A lexical single-month range too.
  const one = monthRangeToBetweenLexical('2024-12', '2024-12')
  assert.deepEqual(betweenValuesToMonthRange([one.start, one.end]), { from: '2024-12', to: '2024-12' })
})
