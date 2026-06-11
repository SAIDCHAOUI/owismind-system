// Plugin/owismind/frontend/test/evidenceModel.test.js
// Pure Evidence Studio model (composables/evidenceModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  chipsFromMeta,
  buildRowsPayload,
  buildDrillLabels,
  isModified,
  normalizeEditableOp,
  lastEvidenceExchangeId,
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

test('buildRowsPayload partitions editable filters vs kept locked ids', () => {
  const chips = chipsFromMeta(META)
  const p = buildRowsPayload('ex1', chips, true, 2, { column: 'period', dir: 'desc' })
  assert.deepEqual(p.filters, [{ column: 'solution', op: 'IN', values: ['OBS', 'OCD'] }])
  assert.deepEqual(p.kept_ids, [1])
  assert.equal(p.include_advanced, true)
  assert.equal(p.page, 2)
  assert.equal(p.exchange_id, 'ex1')
  assert.deepEqual(p.sort, { column: 'period', dir: 'desc' })
})

test('buildRowsPayload defaults: omitted page and sort', () => {
  const p = buildRowsPayload('ex1', [], false)
  assert.equal(p.page, 0)
  assert.equal(p.sort, null)
  assert.deepEqual(p.filters, [])
  assert.deepEqual(p.kept_ids, [])
})

test('removed locked chip leaves kept_ids; user chip becomes a filter', () => {
  const chips = chipsFromMeta(META).filter((c) => c.key !== 'a1')
  chips.push({ key: 'u1', id: null, column: 'country', op: '=', values: ['DZ'], editable: true, source: 'user' })
  const p = buildRowsPayload('ex1', chips, false, 0, null)
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

test('buildRowsPayload without the drill argument has NO drill key (back-compat 5 args)', () => {
  const p = buildRowsPayload('ex1', chipsFromMeta(META), true, 1, null)
  assert.ok(!('drill' in p))
  // The 5-positional contract is untouched.
  assert.deepEqual(p.kept_ids, [1])
  assert.equal(p.page, 1)
})

test('buildRowsPayload maps drill labels to clean {column, value} pairs', () => {
  const drill = [
    { column: 'customer', value: 'Algerie Telecom', extra: 'never sent' },
    { column: 'phase', value: null },
  ]
  const p = buildRowsPayload('ex1', [], false, 0, null, drill)
  assert.deepEqual(p.drill, [
    { column: 'customer', value: 'Algerie Telecom' },
    { column: 'phase', value: null },
  ])
})

test('buildRowsPayload: empty or null drill list adds no drill key', () => {
  assert.ok(!('drill' in buildRowsPayload('ex1', [], false, 0, null, [])))
  assert.ok(!('drill' in buildRowsPayload('ex1', [], false, 0, null, null)))
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
  // "source rows" banner — more keys than the backend accepts means NO drill.
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

// Frozen explanation-step kinds (spec §2) — the frontend renders t('ev.exp.' + kind).
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
