// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/sourceAnalyze.test.js
// Pure aggregation model for the totals bar + the Analyze mini-pivot
// (composables/sourceModel.js). NO install: from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  isNumericColType,
  isTemporalColType,
  bucketOptionsFor,
  buildSourceAggregatePayload,
  buildSourceRowsPayload,
  shareOfTotal,
  formatStatNumber,
  sortBucketRowsAsc,
  formatBucketKey,
  makeSourceChip,
  statsSpecFor,
  monthRangeToBetween,
  betweenValuesToMonthRange,
  yearOfValue,
  chipOp,
  SOURCE_Q_MAX,
} from '../src/composables/sourceModel.js'
import { extraMessages } from '../src/i18n/extra.js'

// --- type classifiers ----------------------------------------------------------

test('isNumericColType: Dataiku / PG numeric type names, case-insensitive', () => {
  for (const t of ['int', 'INT', 'bigint', 'smallint', 'tinyint', 'integer', 'float', 'double', 'double precision', 'decimal', 'numeric', 'real', 'money', 'serial', 'bigserial', 'float8']) {
    assert.equal(isNumericColType(t), true, 'numeric: ' + t)
  }
  for (const t of ['string', 'text', 'varchar', 'boolean', 'date', 'timestamp', 'interval', 'geopoint', 'point', 'DECIMAL(10,2)', '', null, undefined]) {
    assert.equal(isNumericColType(t), false, 'not numeric: ' + t)
  }
})

test('isTemporalColType: date / time / timestamp, case-insensitive', () => {
  for (const t of ['date', 'DATE', 'timestamp', 'timestamp with time zone', 'timestamptz', 'datetime']) {
    assert.equal(isTemporalColType(t), true, 'temporal: ' + t)
  }
  for (const t of ['int', 'string', 'double', 'numeric', 'time', 'time with time zone', '', null, undefined]) {
    assert.equal(isTemporalColType(t), false, 'not temporal: ' + t)
  }
})

test('bucketOptionsFor: only temporal columns get bucket options', () => {
  assert.deepEqual(bucketOptionsFor('date'), ['month', 'quarter', 'year'])
  assert.deepEqual(bucketOptionsFor('timestamp'), ['month', 'quarter', 'year'])
  assert.deepEqual(bucketOptionsFor('int'), [])
  assert.deepEqual(bucketOptionsFor('string'), [])
  assert.deepEqual(bucketOptionsFor(''), [])
})

// --- buildSourceAggregatePayload ----------------------------------------------

test('buildSourceAggregatePayload: reuses the chip -> filter mapping + effective q', () => {
  const chips = [
    makeSourceChip('country', ['DZ'], 1),
    makeSourceChip('phase', ['ACTUALS', 'BUDGET'], 2),
  ]
  const p = buildSourceAggregatePayload('agentA', 3, '  algerie ', chips,
    { column: 'month', bucket: 'quarter' }, [{ fn: 'sum', column: 'amount' }], 50)
  assert.equal(p.agent, 'agentA')
  assert.equal(p.source, 3)
  assert.equal(p.q, 'algerie') // trimmed, effective
  assert.deepEqual(p.filters, [
    { column: 'country', op: '=', values: ['DZ'] },
    { column: 'phase', op: 'IN', values: ['ACTUALS', 'BUDGET'] },
  ])
  assert.deepEqual(p.group, { column: 'month', bucket: 'quarter' })
  assert.deepEqual(p.measures, [{ fn: 'sum', column: 'amount' }])
  assert.equal(p.limit, 50)
})

test('buildSourceAggregatePayload: q below the threshold becomes empty', () => {
  const p = buildSourceAggregatePayload('a', 0, 'a', [], null, [{ fn: 'count', column: null }], 1)
  assert.equal(p.q, '')
})

test('buildSourceAggregatePayload: q is clamped to the max length', () => {
  const long = 'x'.repeat(SOURCE_Q_MAX + 40)
  const p = buildSourceAggregatePayload('a', 0, long, [], null, [{ fn: 'count', column: null }], 1)
  assert.equal(p.q.length, SOURCE_Q_MAX)
})

test('buildSourceAggregatePayload: group null when absent or column-less', () => {
  assert.equal(buildSourceAggregatePayload('a', 0, '', [], null, [{ fn: 'count', column: null }], 1).group, null)
  assert.equal(buildSourceAggregatePayload('a', 0, '', [], {}, [{ fn: 'count', column: null }], 1).group, null)
  assert.equal(buildSourceAggregatePayload('a', 0, '', [], { bucket: 'month' }, [{ fn: 'count', column: null }], 1).group, null)
})

test('buildSourceAggregatePayload: an invalid bucket is dropped to null (non-temporal group)', () => {
  const p = buildSourceAggregatePayload('a', 0, '', [], { column: 'country', bucket: 'week' }, [{ fn: 'count', column: null }], 1)
  assert.deepEqual(p.group, { column: 'country', bucket: null })
})

test('buildSourceAggregatePayload: measures - count forced column null, unknown fn dropped, capped at 8', () => {
  const p = buildSourceAggregatePayload('a', 0, '', [], null, [
    { fn: 'count', column: 'ignored' }, // count never carries a column
    { fn: 'sum', column: 'x' },
    { fn: 'bogus', column: 'y' }, // dropped
    { fn: 'avg', column: null }, // avg with no column stays null (server rejects)
  ], 1)
  assert.deepEqual(p.measures, [
    { fn: 'count', column: null },
    { fn: 'sum', column: 'x' },
    { fn: 'avg', column: null },
  ])

  const many = Array.from({ length: 12 }, () => ({ fn: 'sum', column: 'x' }))
  const capped = buildSourceAggregatePayload('a', 0, '', [], null, many, 1)
  assert.equal(capped.measures.length, 8)
})

test('buildSourceAggregatePayload: limit passthrough (null stays null)', () => {
  assert.equal(buildSourceAggregatePayload('a', 0, '', [], null, [{ fn: 'count', column: null }], null).limit, null)
  assert.equal(buildSourceAggregatePayload('a', 0, '', [], null, [{ fn: 'count', column: null }], 50).limit, 50)
})

test('buildSourceAggregatePayload: does not alias the chip values array', () => {
  const chip = makeSourceChip('c', ['A'], 1)
  const p = buildSourceAggregatePayload('a', 1, '', [chip], null, [{ fn: 'count', column: null }], 1)
  p.filters[0].values.push('B')
  assert.equal(chip.values.length, 1)
})

// --- shareOfTotal --------------------------------------------------------------

test('shareOfTotal: exact percent, null on 0 / null / non-finite', () => {
  assert.equal(shareOfTotal(25, 100), 25)
  assert.equal(shareOfTotal(1, 3), (1 / 3) * 100)
  assert.equal(shareOfTotal(50, 0), null) // divide-by-zero guarded
  assert.equal(shareOfTotal(5, null), null)
  assert.equal(shareOfTotal(null, 100), null)
  assert.equal(shareOfTotal(NaN, 100), null)
  assert.equal(shareOfTotal(5, NaN), null)
  assert.equal(shareOfTotal(Infinity, 100), null)
  assert.equal(shareOfTotal(-10, 100), -10) // negatives allowed (a valid share)
})


test('sortBucketRowsAsc: chronological display order, null keys last, non-destructive', () => {
  const raw = [
    { key: '2026-03-01T00:00:00', m0: 3 },
    { key: null, m0: 9 },
    { key: '2025-11-01T00:00:00', m0: 1 },
    { key: '2026-01-01T00:00:00', m0: 2 },
  ]
  const sorted = sortBucketRowsAsc(raw)
  assert.deepEqual(sorted.map((r) => r.m0), [1, 2, 3, 9]) // oldest first, null last
  assert.deepEqual(raw.map((r) => r.m0), [3, 9, 1, 2]) // input untouched
  assert.deepEqual(sortBucketRowsAsc([]), [])
  assert.deepEqual(sortBucketRowsAsc(null), [])
})

// --- formatStatNumber ----------------------------------------------------------

test('formatStatNumber: locale grouping differs fr vs en; decimals capped to 2', () => {
  const en = formatStatNumber(1234567, 'en')
  const fr = formatStatNumber(1234567, 'fr')
  assert.ok(en.includes(','), 'en groups with a comma: ' + en)
  assert.ok(!fr.includes(','), 'fr does not group with a comma: ' + fr)
  assert.notEqual(en, fr) // the grouping separator differs

  // Integers keep no decimals; non-integers cap at 2.
  assert.equal(formatStatNumber(42, 'en'), '42')
  assert.equal(formatStatNumber(3.14159, 'en'), '3.14')
  assert.equal(formatStatNumber(2.5, 'en'), '2.5')
})

test('formatStatNumber: tiny non-zero magnitudes never render as "0"', () => {
  // A MIN of 0.0004 shown as "0" would be a wrong number, not a truncation: below
  // 0.01 the formatter switches to significant digits.
  assert.equal(formatStatNumber(0.0004, 'en'), '0.0004')
  assert.equal(formatStatNumber(0.003, 'en'), '0.003')
  assert.equal(formatStatNumber(-0.0004, 'en'), '-0.0004')
  assert.equal(formatStatNumber(0, 'en'), '0') // a real zero still reads 0
})

test('formatStatNumber: integer strings beyond 2^53 stay DB-exact (no Number() drift)', () => {
  // 9007199254740993 is unrepresentable as a JS double (rounds to ...992): the raw
  // string must pass through untouched instead of showing an altered total.
  assert.equal(formatStatNumber('9007199254740993', 'en'), '9007199254740993')
  assert.equal(formatStatNumber('-12345678901234567890', 'en'), '-12345678901234567890')
  // 15-digit-or-less integers are safe and still get locale grouping.
  assert.equal(formatStatNumber('123456789012345', 'en'), '123,456,789,012,345')
})

test('formatStatNumber: numeric strings format, non-numeric strings pass through, null -> dash', () => {
  assert.equal(formatStatNumber('1234.5', 'en'), '1,234.5') // PG decimals arrive as strings
  assert.equal(formatStatNumber('2026-03-31', 'en'), '2026-03-31') // a date passes through verbatim
  assert.equal(formatStatNumber('n/a', 'en'), 'n/a')
  assert.equal(formatStatNumber(null, 'en'), '-')
  assert.equal(formatStatNumber(undefined, 'en'), '-')
  assert.equal(formatStatNumber('', 'en'), '')
})

// --- formatBucketKey -----------------------------------------------------------

test('formatBucketKey: month / quarter / year from an ISO timestamp (UTC-safe)', () => {
  assert.equal(formatBucketKey('2026-03-01T00:00:00', 'month'), '2026-03')
  assert.equal(formatBucketKey('2026-03-01', 'quarter'), '2026-Q1')
  assert.equal(formatBucketKey('2026-11-01', 'quarter'), '2026-Q4')
  assert.equal(formatBucketKey('2026-07-01', 'year'), '2026')
})

test('formatBucketKey: quarter boundaries', () => {
  assert.equal(formatBucketKey('2026-01-01', 'quarter'), '2026-Q1')
  assert.equal(formatBucketKey('2026-04-01', 'quarter'), '2026-Q2')
  assert.equal(formatBucketKey('2026-07-01', 'quarter'), '2026-Q3')
  assert.equal(formatBucketKey('2026-10-01', 'quarter'), '2026-Q4')
})

test('formatBucketKey: epoch-ms number and numeric string', () => {
  const ms = Date.UTC(2026, 2, 1) // 2026-03
  assert.equal(formatBucketKey(ms, 'month'), '2026-03')
  assert.equal(formatBucketKey(String(ms), 'month'), '2026-03')
})

test('formatBucketKey: null key -> null; unparseable falls back to its string', () => {
  assert.equal(formatBucketKey(null, 'month'), null)
  assert.equal(formatBucketKey(undefined, 'month'), null)
  assert.equal(formatBucketKey('not-a-date', 'month'), 'not-a-date')
})

// --- statsSpecFor (Calculate zone measures, chosen by column TYPE) --------------

test('statsSpecFor: numeric -> sum, avg, median, min, max (ordered, with label keys)', () => {
  // Exact type names only: 'decimal(10,2)' is NOT numeric here, mirroring the
  // backend gate (which would refuse SUM on it) - the UI must not offer it.
  const spec = statsSpecFor('decimal')
  assert.deepEqual(spec.map((s) => s.fn), ['sum', 'avg', 'median', 'min', 'max'])
  assert.deepEqual(spec.map((s) => s.labelKey), [
    'src.calc.sum', 'src.calc.avg', 'src.calc.median', 'src.calc.min', 'src.calc.max',
  ])
  // Same shape whatever the numeric alias.
  assert.deepEqual(statsSpecFor('bigint').map((s) => s.fn), ['sum', 'avg', 'median', 'min', 'max'])
})

test('statsSpecFor: temporal -> min, max only', () => {
  assert.deepEqual(statsSpecFor('date').map((s) => s.fn), ['min', 'max'])
  assert.deepEqual(statsSpecFor('timestamp').map((s) => s.labelKey), ['src.calc.min', 'src.calc.max'])
})

test('statsSpecFor: anything else -> distinct count', () => {
  for (const t of ['string', 'text', 'boolean', '', null, undefined]) {
    const spec = statsSpecFor(t)
    assert.equal(spec.length, 1)
    assert.equal(spec[0].fn, 'count_distinct')
    assert.equal(spec[0].labelKey, 'src.calc.distinct')
  }
})

test('statsSpecFor: every label key exists in fr + en', () => {
  const keys = new Set()
  for (const t of ['int', 'date', 'string']) statsSpecFor(t).forEach((s) => keys.add(s.labelKey))
  for (const loc of ['fr', 'en']) {
    for (const k of keys) {
      const v = extraMessages[loc][k]
      assert.equal(typeof v, 'string', loc + ' missing ' + k)
      assert.ok(v.length > 0, loc + ' empty ' + k)
    }
  }
})

test('buildSourceAggregatePayload: median flows through (numeric measure)', () => {
  const p = buildSourceAggregatePayload('a', 1, '', [], null, [{ fn: 'median', column: 'amount' }], 1)
  assert.deepEqual(p.measures, [{ fn: 'median', column: 'amount' }])
})

// --- monthRangeToBetween (temporal range filter) -------------------------------

test('monthRangeToBetween: inclusive span, exact month lengths', () => {
  assert.deepEqual(monthRangeToBetween('2026-01', '2026-06'), {
    start: '2026-01-01', end: '2026-06-30T23:59:59.999999',
  })
  // 31-day end month.
  assert.equal(monthRangeToBetween('2026-01', '2026-01').end, '2026-01-31T23:59:59.999999')
  // 30-day end month.
  assert.equal(monthRangeToBetween('2026-04', '2026-04').end, '2026-04-30T23:59:59.999999')
})

test('monthRangeToBetween: February leap vs non-leap', () => {
  assert.equal(monthRangeToBetween('2026-02', '2026-02').end, '2026-02-28T23:59:59.999999') // 2026 not leap
  assert.equal(monthRangeToBetween('2024-02', '2024-02').end, '2024-02-29T23:59:59.999999') // 2024 leap
})

test('monthRangeToBetween: same-month range', () => {
  assert.deepEqual(monthRangeToBetween('2026-03', '2026-03'), {
    start: '2026-03-01', end: '2026-03-31T23:59:59.999999',
  })
})

test('monthRangeToBetween: reversed From > To is swapped', () => {
  assert.deepEqual(monthRangeToBetween('2026-06', '2026-01'), monthRangeToBetween('2026-01', '2026-06'))
})

test('monthRangeToBetween: full-year fill (YYYY-01 .. YYYY-12)', () => {
  assert.deepEqual(monthRangeToBetween('2025-01', '2025-12'), {
    start: '2025-01-01', end: '2025-12-31T23:59:59.999999',
  })
})

test('monthRangeToBetween: null on missing / malformed month', () => {
  assert.equal(monthRangeToBetween('', '2026-06'), null)
  assert.equal(monthRangeToBetween('2026-06', ''), null)
  assert.equal(monthRangeToBetween('2026-13', '2026-06'), null) // month out of range
  assert.equal(monthRangeToBetween('2026-00', '2026-06'), null)
  assert.equal(monthRangeToBetween('2026', '2026-06'), null) // not YYYY-MM
  assert.equal(monthRangeToBetween(null, undefined), null)
})

// --- betweenValuesToMonthRange (inverse, for pre-filling the edit popover) ------

test('betweenValuesToMonthRange: reads YYYY-MM back from stored boundary values', () => {
  assert.deepEqual(
    betweenValuesToMonthRange(['2026-01-01', '2026-06-30T23:59:59.999999']),
    { from: '2026-01', to: '2026-06' },
  )
})

test('betweenValuesToMonthRange: round-trips monthRangeToBetween', () => {
  for (const [f, t] of [['2026-01', '2026-06'], ['2024-02', '2024-02'], ['2025-01', '2025-12']]) {
    const r = monthRangeToBetween(f, t)
    assert.deepEqual(betweenValuesToMonthRange([r.start, r.end]), { from: f, to: t })
  }
})

test('betweenValuesToMonthRange: null when not exactly 2 readable values', () => {
  assert.equal(betweenValuesToMonthRange(['2026-01-01']), null) // wrong length
  assert.equal(betweenValuesToMonthRange(['2026-01-01', '2026-06-30', 'extra']), null)
  assert.equal(betweenValuesToMonthRange(['x', 'y']), null) // unreadable
  assert.equal(betweenValuesToMonthRange(null), null)
})

test('yearOfValue: leading 4-digit year of an ISO date / timestamp', () => {
  assert.equal(yearOfValue('2026-03-01'), '2026')
  assert.equal(yearOfValue('2026-03-01T00:00:00'), '2026')
  assert.equal(yearOfValue('1999-12-31'), '1999')
  assert.equal(yearOfValue('not-a-date'), null)
  assert.equal(yearOfValue(''), null)
  assert.equal(yearOfValue(null), null)
})

// --- BETWEEN chip: op preserved end to end -------------------------------------

test('chipOp: BETWEEN preserved only for a 2-value chip, else derived', () => {
  assert.equal(chipOp({ op: 'BETWEEN', values: ['a', 'b'] }), 'BETWEEN')
  assert.equal(chipOp({ op: 'BETWEEN', values: ['a'] }), '=') // not a valid range -> derived
  assert.equal(chipOp({ op: 'BETWEEN', values: ['a', 'b', 'c'] }), 'IN') // 3 values -> derived
  assert.equal(chipOp({ op: 'IN', values: ['a', 'b'] }), 'IN')
  assert.equal(chipOp({ op: '=', values: ['a'] }), '=')
})

test('makeSourceChip: explicit BETWEEN op kept for 2 values, ignored otherwise', () => {
  const range = makeSourceChip('sale_date', ['2026-01-01', '2026-06-30T23:59:59.999999'], 7, 'BETWEEN')
  assert.equal(range.op, 'BETWEEN')
  assert.deepEqual(range.values, ['2026-01-01', '2026-06-30T23:59:59.999999'])
  // A single value can never be a BETWEEN range: it falls back to the derived op.
  assert.equal(makeSourceChip('sale_date', ['2026-01-01'], 8, 'BETWEEN').op, '=')
  // No op passed -> derived as before.
  assert.equal(makeSourceChip('country', ['A', 'B'], 9).op, 'IN')
})

test('buildSourceRowsPayload: forwards a BETWEEN chip op + its 2 values untouched', () => {
  const chip = makeSourceChip('sale_date', ['2026-01-01', '2026-06-30T23:59:59.999999'], 1, 'BETWEEN')
  const p = buildSourceRowsPayload('agentA', 3, '', [chip], 100, 0, null)
  assert.deepEqual(p.filters, [
    { column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'] },
  ])
})

test('buildSourceAggregatePayload: forwards a BETWEEN chip op + its 2 values untouched', () => {
  const chip = makeSourceChip('sale_date', ['2026-01-01', '2026-06-30T23:59:59.999999'], 1, 'BETWEEN')
  const p = buildSourceAggregatePayload('agentA', 3, '', [chip], null, [{ fn: 'count', column: null }], 1)
  assert.deepEqual(p.filters, [
    { column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'] },
  ])
})

test('buildSourceRowsPayload: a mislabeled BETWEEN chip (not 2 values) is re-derived', () => {
  // Defensive: a chip that claims BETWEEN but carries 3 values must not travel as BETWEEN.
  const chip = { key: 'u1', column: 'sale_date', op: 'BETWEEN', values: ['a', 'b', 'c'] }
  const p = buildSourceRowsPayload('agentA', 3, '', [chip], 100, 0, null)
  assert.deepEqual(p.filters, [{ column: 'sale_date', op: 'IN', values: ['a', 'b', 'c'] }])
})
