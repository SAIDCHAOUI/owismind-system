// Plugin/owismind/frontend/test/evidenceModel.test.js
// Pure Evidence Studio model (composables/evidenceModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  chipsFromMeta,
  buildRowsPayload,
  buildEvidenceAggregatePayload,
  buildEvidenceDistinctScope,
  buildDrillLabels,
  isModified,
  normalizeEditableOp,
  lastEvidenceExchangeId,
  effectiveEvidenceQuery,
  EVIDENCE_Q_MIN,
  EVIDENCE_Q_MAX,
  EVIDENCE_DEFAULT_LIMIT,
} from '../src/composables/evidenceModel.js'
import { extraMessages } from '../src/i18n/extra.js'

const META = {
  available: true,
  chips: [
    { id: 0, column: 'solution', op: 'IN', values: ['OBS', 'OCD'], editable: true },
    { id: 1, column: 'period', op: '>=', values: ['2025-01'], editable: false },
  ],
  advanced: { present: true, display: '(a OR b)' },
}

test('chipsFromMeta clones values and tags agent chips', () => {
  const chips = chipsFromMeta(META)
  assert.equal(chips.length, 2)
  assert.equal(chips[0].key, 'a0')
  assert.equal(chips[0].source, 'agent')
  chips[0].values.push('X')
  assert.equal(META.chips[0].values.length, 2) // no aliasing
})

test('buildRowsPayload partitions editable filters vs kept locked ids (limit/offset)', () => {
  const chips = chipsFromMeta(META)
  const p = buildRowsPayload('ex1', chips, true, 20, 40, { column: 'period', dir: 'desc' })
  assert.deepEqual(p.filters, [{ column: 'solution', op: 'IN', values: ['OBS', 'OCD'] }])
  assert.deepEqual(p.kept_ids, [1])
  assert.equal(p.include_advanced, true)
  assert.equal(p.limit, 20)
  assert.equal(p.offset, 40)
  assert.ok(!('page' in p)) // the page index is gone from the contract
  assert.equal(p.exchange_id, 'ex1')
  assert.deepEqual(p.sort, { column: 'period', dir: 'desc' })
})

test('buildRowsPayload defaults: omitted limit / offset / sort', () => {
  const p = buildRowsPayload('ex1', [], false)
  assert.equal(p.limit, EVIDENCE_DEFAULT_LIMIT) // fallback window when no limit is passed
  assert.equal(p.offset, 0)
  assert.equal(p.sort, null)
  assert.deepEqual(p.filters, [])
  assert.deepEqual(p.kept_ids, [])
})

test('removed locked chip leaves kept_ids; user chip becomes a filter', () => {
  const chips = chipsFromMeta(META).filter((c) => c.key !== 'a1')
  chips.push({ key: 'u1', id: null, column: 'country', op: '=', values: ['DZ'], editable: true, source: 'user' })
  const p = buildRowsPayload('ex1', chips, false, 100, 0, null)
  assert.deepEqual(p.kept_ids, [])
  assert.equal(p.filters.length, 2)
  assert.equal(p.include_advanced, false)
})

test('isModified detects edits, removals and advanced toggle', () => {
  const base = chipsFromMeta(META)
  assert.equal(isModified(META, base, true), false)
  assert.equal(isModified(META, base, false), true) // advanced removed
  const edited = chipsFromMeta(META)
  edited[0].values = ['OBS']
  assert.equal(isModified(META, edited, true), true)
  assert.equal(isModified(META, chipsFromMeta(META).slice(1), true), true) // chip removed
})

test('normalizeEditableOp: single value = "=", several = "IN"', () => {
  assert.equal(normalizeEditableOp(['x']), '=')
  assert.equal(normalizeEditableOp(['x', 'y']), 'IN')
})

// --- lastEvidenceExchangeId (evidence continuity on conversation switch) ------------

const turn = (id, sql) => ({ exchange: { id, version: { sql } } })

test('lastEvidenceExchangeId: picks the LAST sql-bearing turn of the active path', () => {
  const turns = [
    turn('e1', [{ sql: 'SELECT 1', success: true }]),
    turn('e2', []),
    turn('e3', [{ sql: 'SELECT 3', success: true }]),
    turn('e4', []), // last turn has no SQL -> walk back to e3
  ]
  assert.equal(lastEvidenceExchangeId(turns), 'e3')
})

test('lastEvidenceExchangeId: requires a SUCCESSFUL sql (failed-only turns skipped)', () => {
  const turns = [
    turn('e1', [{ sql: 'SELECT 1', success: true }]),
    turn('e2', [{ sql: 'SELECT broken', success: false }]),
  ]
  assert.equal(lastEvidenceExchangeId(turns), 'e1')
})

test('lastEvidenceExchangeId: skips turns without a persisted exchange id', () => {
  const turns = [
    turn('e1', [{ sql: 'SELECT 1', success: true }]),
    turn(null, [{ sql: 'SELECT 2', success: true }]), // live, not yet reconciled
  ]
  assert.equal(lastEvidenceExchangeId(turns), 'e1')
})

test('lastEvidenceExchangeId: null on empty/malformed input', () => {
  assert.equal(lastEvidenceExchangeId([]), null)
  assert.equal(lastEvidenceExchangeId(null), null)
  assert.equal(lastEvidenceExchangeId([{}, { exchange: null }]), null)
  assert.equal(lastEvidenceExchangeId([turn('e1', [])]), null)
  assert.equal(lastEvidenceExchangeId([{ exchange: { id: 'x', version: null } }]), null)
})

// --- buildRowsPayload drill extension (trust layer v2, spec §3) ----------------------

test('buildRowsPayload without the drill/table/q args has none of those keys', () => {
  const p = buildRowsPayload('ex1', chipsFromMeta(META), true, 20, 0, null)
  assert.ok(!('drill' in p))
  assert.ok(!('table' in p))
  assert.ok(!('q' in p))
  assert.deepEqual(p.kept_ids, [1])
  assert.equal(p.limit, 20)
  assert.equal(p.offset, 0)
})

test('buildRowsPayload maps drill labels to clean {column, value} pairs', () => {
  const drill = [
    { column: 'customer', value: 'Algerie Telecom', extra: 'never sent' },
    { column: 'phase', value: null },
  ]
  const p = buildRowsPayload('ex1', [], false, 100, 0, null, drill)
  assert.deepEqual(p.drill, [
    { column: 'customer', value: 'Algerie Telecom' },
    { column: 'phase', value: null },
  ])
})

test('buildRowsPayload: empty or null drill list adds no drill key', () => {
  assert.ok(!('drill' in buildRowsPayload('ex1', [], false, 100, 0, null, [])))
  assert.ok(!('drill' in buildRowsPayload('ex1', [], false, 100, 0, null, null)))
})

// --- buildRowsPayload table selector (multi-table SQL) -------------------------------

test('buildRowsPayload adds the table key only for a non-empty string', () => {
  const withTable = buildRowsPayload('ex1', [], false, 100, 0, null, null, 'Tickets')
  assert.equal(withTable.table, 'Tickets')
  // Absent / empty / non-string -> no table key (server defaults to first matched).
  assert.ok(!('table' in buildRowsPayload('ex1', [], false, 100, 0, null, null)))
  assert.ok(!('table' in buildRowsPayload('ex1', [], false, 100, 0, null, null, '')))
  assert.ok(!('table' in buildRowsPayload('ex1', [], false, 100, 0, null, null, 123)))
})

test('buildRowsPayload table is independent of the drill key', () => {
  const drill = [{ column: 'phase', value: null }]
  const p = buildRowsPayload('ex1', [], false, 100, 0, null, drill, 'DRIVE_Revenues')
  assert.deepEqual(p.drill, [{ column: 'phase', value: null }])
  assert.equal(p.table, 'DRIVE_Revenues')
})

// --- buildRowsPayload search (v2 q, appended after table) ----------------------------

test('effectiveEvidenceQuery: trims, drops below the min, clamps to the max', () => {
  assert.equal(effectiveEvidenceQuery('  ab '), 'ab')
  assert.equal(effectiveEvidenceQuery('a'), '') // 1 char < EVIDENCE_Q_MIN
  assert.equal(effectiveEvidenceQuery('  '), '')
  assert.equal(effectiveEvidenceQuery(null), '')
  assert.equal(effectiveEvidenceQuery(undefined), '')
  assert.equal(EVIDENCE_Q_MIN, 2)
  const long = 'x'.repeat(EVIDENCE_Q_MAX + 50)
  assert.equal(effectiveEvidenceQuery(long).length, EVIDENCE_Q_MAX)
})

test('buildRowsPayload adds the q key only for an effective (>= 2 chars) search', () => {
  const p = buildRowsPayload('ex1', [], false, 100, 0, null, null, null, '  Algerie ')
  assert.equal(p.q, 'Algerie') // trimmed + kept (>= 2 chars)
  // Below the threshold / absent -> no q key (server returns the unsearched window).
  assert.ok(!('q' in buildRowsPayload('ex1', [], false, 100, 0, null, null, null, 'a')))
  assert.ok(!('q' in buildRowsPayload('ex1', [], false, 100, 0, null, null, null, '')))
  assert.ok(!('q' in buildRowsPayload('ex1', [], false, 100, 0, null)))
})

test('buildRowsPayload q is independent of the drill and table keys', () => {
  const drill = [{ column: 'phase', value: null }]
  const p = buildRowsPayload('ex1', [], false, 20, 0, null, drill, 'DRIVE_Revenues', 'total')
  assert.deepEqual(p.drill, [{ column: 'phase', value: null }])
  assert.equal(p.table, 'DRIVE_Revenues')
  assert.equal(p.q, 'total')
})

// --- buildEvidenceAggregatePayload (DB totals bar + Analyze pivot, shared with sources) ---

const AGG_META = {
  available: true,
  chips: [
    { id: 0, column: 'solution', op: 'IN', values: ['OBS', 'OCD'], editable: true },
    { id: 1, column: 'period', op: '>=', values: ['2025-01'], editable: false },
  ],
}

test('buildEvidenceAggregatePayload: same scope as rows, no limit/offset/sort, plus group/measures/limit', () => {
  const chips = chipsFromMeta(AGG_META)
  const p = buildEvidenceAggregatePayload(
    'ex1', chips, true, null, 'Tickets', '  algerie ',
    { column: 'period', bucket: 'quarter' }, [{ fn: 'sum', column: 'amount' }], 50,
  )
  // The rows-side scope, verbatim.
  assert.equal(p.exchange_id, 'ex1')
  assert.deepEqual(p.filters, [{ column: 'solution', op: 'IN', values: ['OBS', 'OCD'] }])
  assert.deepEqual(p.kept_ids, [1])
  assert.equal(p.include_advanced, true)
  assert.equal(p.table, 'Tickets')
  assert.equal(p.q, 'algerie') // trimmed, effective
  // The aggregate additions, shaped exactly like /source/aggregate.
  assert.deepEqual(p.group, { column: 'period', bucket: 'quarter' })
  assert.deepEqual(p.measures, [{ fn: 'sum', column: 'amount' }])
  assert.equal(p.limit, 50)
  // Never the rows-only pagination keys (limit IS present: it is the group-rows cap).
  assert.ok(!('offset' in p))
  assert.ok(!('sort' in p))
  assert.ok('limit' in p)
})

test('buildEvidenceAggregatePayload: group/measures normalized like the source builder', () => {
  const p = buildEvidenceAggregatePayload('ex1', [], false, null, null, '', { bucket: 'month' }, [
    { fn: 'count', column: 'ignored' }, // count never carries a column
    { fn: 'bogus', column: 'x' }, // dropped
  ], null)
  assert.equal(p.group, null) // a column-less group is dropped to null
  assert.deepEqual(p.measures, [{ fn: 'count', column: null }])
  assert.equal(p.limit, null) // null limit passes through
})

test('buildEvidenceAggregatePayload: drill forwarded, absent optional scope adds no keys', () => {
  const withDrill = buildEvidenceAggregatePayload(
    'ex1', [], false, [{ column: 'phase', value: null }], null, '',
    null, [{ fn: 'count', column: null }], 1,
  )
  assert.deepEqual(withDrill.drill, [{ column: 'phase', value: null }])
  const bare = buildEvidenceAggregatePayload('ex1', [], false, null, null, '', null, [{ fn: 'count', column: null }], 1)
  assert.ok(!('drill' in bare))
  assert.ok(!('table' in bare))
  assert.ok(!('q' in bare))
})

// --- buildEvidenceDistinctScope (CASCADING filter-chip picker scope, A4) -------------

test('buildEvidenceDistinctScope: partitions chips like rows (filters + kept ids)', () => {
  const chips = chipsFromMeta(AGG_META) // one editable IN chip (id 0) + one locked chip (id 1)
  const scope = buildEvidenceDistinctScope(chips, true, null, '', null)
  assert.deepEqual(scope.filters, [{ column: 'solution', op: 'IN', values: ['OBS', 'OCD'] }])
  assert.deepEqual(scope.kept_ids, [1])
  assert.equal(scope.include_advanced, true)
  // No drill / scope_q added when not meaningful.
  assert.ok(!('drill' in scope))
  assert.ok(!('scope_q' in scope))
})

test('buildEvidenceDistinctScope: drops the chip being edited so it never self-scopes', () => {
  const chips = [
    { key: 'u1', id: null, column: 'solution', op: 'IN', values: ['OBS'], editable: true, source: 'user' },
    { key: 'u2', id: null, column: 'metric', op: '=', values: ['Actuals'], editable: true, source: 'user' },
  ]
  // Editing chip u1: only the OTHER chip (u2) stays in the picker scope.
  const scope = buildEvidenceDistinctScope(chips, false, null, '', 'u1')
  assert.deepEqual(scope.filters, [{ column: 'metric', op: '=', values: ['Actuals'] }])
  assert.deepEqual(scope.kept_ids, [])
})

test('buildEvidenceDistinctScope: excludeChipKey null keeps every chip (ADD flow)', () => {
  const chips = [
    { key: 'u1', id: null, column: 'metric', op: '=', values: ['Actuals'], editable: true, source: 'user' },
  ]
  const scope = buildEvidenceDistinctScope(chips, false, null, '', null)
  assert.deepEqual(scope.filters, [{ column: 'metric', op: '=', values: ['Actuals'] }])
})

test('buildEvidenceDistinctScope: drill + scope_q added only when meaningful', () => {
  const withExtras = buildEvidenceDistinctScope(
    [], false, [{ column: 'phase', value: null }], '  algerie ', null,
  )
  assert.deepEqual(withExtras.drill, [{ column: 'phase', value: null }])
  assert.equal(withExtras.scope_q, 'algerie') // trimmed + effective
  // A too-short scope_q is dropped (mirrors the effective-query threshold).
  const shortQ = buildEvidenceDistinctScope([], false, null, 'a', null)
  assert.ok(!('scope_q' in shortQ))
  const noDrill = buildEvidenceDistinctScope([], false, [], '', null)
  assert.ok(!('drill' in noDrill))
})

test('buildEvidenceDistinctScope: a USER BETWEEN chip forwards op BETWEEN untouched', () => {
  const chips = [
    { key: 'u1', id: null, column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30'], editable: true, source: 'user' },
  ]
  const scope = buildEvidenceDistinctScope(chips, false, null, '', null)
  assert.deepEqual(scope.filters, [{ column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30'] }])
})

// --- BETWEEN forwarding on the evidence rows + aggregate paths (temporal range chips) ---

test('buildRowsPayload: a USER BETWEEN chip forwards op BETWEEN + its 2 values untouched', () => {
  const chips = [
    { key: 'u1', id: null, column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'], editable: true, source: 'user' },
  ]
  const p = buildRowsPayload('ex1', chips, false, 100, 0, null)
  assert.deepEqual(p.filters, [
    { column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'] },
  ])
})

test('buildEvidenceAggregatePayload: a USER BETWEEN chip forwards op BETWEEN as well', () => {
  const chips = [
    { key: 'u1', id: null, column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'], editable: true, source: 'user' },
  ]
  const p = buildEvidenceAggregatePayload('ex1', chips, false, null, null, '', null, [{ fn: 'count', column: null }], 1)
  assert.deepEqual(p.filters, [
    { column: 'sale_date', op: 'BETWEEN', values: ['2026-01-01', '2026-06-30T23:59:59.999999'] },
  ])
})

test('buildRowsPayload: a mislabeled BETWEEN chip (not exactly 2 values) is re-derived to IN', () => {
  const chips = [
    { key: 'u1', id: null, column: 'sale_date', op: 'BETWEEN', values: ['a', 'b', 'c'], editable: true, source: 'user' },
  ]
  const p = buildRowsPayload('ex1', chips, false, 100, 0, null)
  assert.deepEqual(p.filters, [{ column: 'sale_date', op: 'IN', values: ['a', 'b', 'c'] }])
})

test('buildRowsPayload: editable =/IN chips still travel as =/IN (chipOp regression guard)', () => {
  const chips = [
    { key: 'a0', id: 0, column: 'solution', op: 'IN', values: ['OBS', 'OCD'], editable: true, source: 'agent' },
    { key: 'u1', id: null, column: 'country', op: '=', values: ['DZ'], editable: true, source: 'user' },
  ]
  const p = buildRowsPayload('ex1', chips, false, 100, 0, null)
  assert.deepEqual(p.filters, [
    { column: 'solution', op: 'IN', values: ['OBS', 'OCD'] },
    { column: 'country', op: '=', values: ['DZ'] },
  ])
})

// --- buildDrillLabels (captured-result row → drill labels) ---------------------------

const RESULT_COLS = ['Customer', 'total']

test('buildDrillLabels maps drill columns to row values (case-insensitive)', () => {
  // Drilldown column is lowercase, the captured result kept the agent's casing.
  const labels = buildDrillLabels(['customer'], RESULT_COLS, ['Algerie Telecom', 99])
  assert.deepEqual(labels, [{ column: 'customer', value: 'Algerie Telecom' }])
})

test('buildDrillLabels keeps a null cell (server renders IS NULL)', () => {
  const labels = buildDrillLabels(['customer'], RESULT_COLS, [null, 1])
  assert.deepEqual(labels, [{ column: 'customer', value: null }])
})

test('buildDrillLabels aborts (null) on an unmappable column', () => {
  assert.equal(buildDrillLabels(['country'], RESULT_COLS, ['x', 1]), null)
})

test('buildDrillLabels aborts on missing cell, object cell or non-finite number', () => {
  assert.equal(buildDrillLabels(['total'], RESULT_COLS, ['only-one-cell']), null) // undefined
  assert.equal(buildDrillLabels(['customer'], RESULT_COLS, [{ a: 1 }, 2]), null)
  assert.equal(buildDrillLabels(['total'], RESULT_COLS, ['x', Infinity]), null)
})

test('buildDrillLabels aborts (null) above the 8-column cap instead of truncating', () => {
  // CONTRACT-01: a truncated drill would show a SUPERSET of the group under a
  // "source rows" banner - more keys than the backend accepts means NO drill.
  const cols = Array.from({ length: 10 }, (_, i) => 'c' + i)
  const row = cols.map((_, i) => i)
  assert.equal(buildDrillLabels(cols, cols, row), null)
  assert.equal(buildDrillLabels(cols, cols, row, 3), null)
  // At or under the cap, every column maps and every label travels.
  const eight = cols.slice(0, 8)
  const labels = buildDrillLabels(eight, cols, row)
  assert.equal(labels.length, 8)
  assert.deepEqual(labels[7], { column: 'c7', value: 7 })
})

test('buildDrillLabels: null on empty/malformed inputs', () => {
  assert.equal(buildDrillLabels([], RESULT_COLS, []), null)
  assert.equal(buildDrillLabels(null, RESULT_COLS, []), null)
  assert.equal(buildDrillLabels(['customer'], null, ['x']), null)
  assert.equal(buildDrillLabels(['customer'], RESULT_COLS, null), null)
})

// --- i18n contract: trust-layer keys (frozen enum coverage, fr + en) -----------------

// Frozen explanation-step kinds (spec §2) - the frontend renders t('ev.exp.' + kind).
const FROZEN_KINDS = [
  'source', 'join',
  'filter_eq', 'filter_neq', 'filter_gt', 'filter_gte', 'filter_lt', 'filter_lte',
  'filter_in', 'filter_notin', 'filter_between', 'filter_null', 'filter_notnull',
  'filter_like', 'filter_advanced', 'filter_unmapped',
  'group', 'distinct',
  'agg_sum', 'agg_avg', 'agg_min', 'agg_max', 'agg_count_star', 'agg_count',
  'agg_count_distinct', 'agg_filtered',
  'calc_ratio', 'calc_percent', 'calc_diff', 'calc_share',
  'window_rank', 'window_row_number', 'window_running', 'window_lag',
  'having', 'sort', 'topn', 'limit_arbitrary', 'cte_step', 'union', 'opaque',
]

const PROOF_KEYS = [
  'ev.proof.level.result', 'ev.proof.level.source', 'ev.proof.level.partial',
  'ev.proof.level.declared', 'ev.proof.level.partial_note',
  'ev.proof.level.desc.result', 'ev.proof.level.desc.source',
  'ev.proof.level.desc.partial', 'ev.proof.level.desc.declared',
  'ev.proof.sources', 'ev.proof.sources.more', 'ev.proof.calc',
  'ev.proof.result', 'ev.proof.result.rows', 'ev.proof.result.missing',
  'ev.proof.result.truncated', 'ev.proof.result.drill',
  'ev.proof.drill.banner', 'ev.proof.drill.exit', 'ev.proof.explore',
]

test('extra.js covers every frozen ev.exp.* kind and every ev.proof.* key (fr + en)', () => {
  for (const loc of ['fr', 'en']) {
    for (const kind of FROZEN_KINDS) {
      const v = extraMessages[loc]['ev.exp.' + kind]
      assert.equal(typeof v, 'string', loc + ' missing ev.exp.' + kind)
      assert.ok(v.length > 0, loc + ' empty ev.exp.' + kind)
    }
    for (const key of PROOF_KEYS) {
      const v = extraMessages[loc][key]
      assert.equal(typeof v, 'string', loc + ' missing ' + key)
      assert.ok(v.length > 0, loc + ' empty ' + key)
    }
  }
})

test('ev.sql.title moved to the technical-details wording (both locales)', () => {
  assert.equal(extraMessages.fr['ev.sql.title'], 'Détails techniques (SQL)')
  assert.equal(extraMessages.en['ev.sql.title'], 'Technical details (SQL)')
})
