// Plugin/owismind/frontend/test/screenContextModel.test.js
// Pure screen-context model (composables/screenContextModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  SS_FILTERS,
  SS_VALUES,
  SS_VALUE_CHARS,
  SS_Q_CHARS,
  SS_DATASET_CHARS,
  SS_AGENT_CHARS,
  SS_DRILL,
  SS_ANALYZE_ROWS,
  SS_MEASURE_VALUE_CHARS,
  snapshotFromExplorer,
  snapshotFromEvidence,
  pickSnapshot,
  snapshotSignature,
} from '../src/composables/screenContextModel.js'

// --- caps mirror the backend -------------------------------------------------
test('caps mirror the backend contract', () => {
  assert.equal(SS_FILTERS, 8)
  assert.equal(SS_VALUES, 5)
  assert.equal(SS_VALUE_CHARS, 80)
  assert.equal(SS_Q_CHARS, 80)
  assert.equal(SS_DATASET_CHARS, 120)
  assert.equal(SS_AGENT_CHARS, 80)
  assert.equal(SS_DRILL, 6)
  assert.equal(SS_ANALYZE_ROWS, 5)
  assert.equal(SS_MEASURE_VALUE_CHARS, 40)
})

// --- explorer: meaningful gate + basic shape ---------------------------------
test('explorer: a bare panel (no filters/q/calc/analyze) -> null', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', agentLabel: 'Revenue', columns: [],
    chips: [], q: '', totalCount: 42, totalLoading: false,
  })
  assert.equal(snap, null)
})

test('explorer: a bare row_count alone is NOT meaningful -> null', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [], q: '', totalCount: 999, totalLoading: false,
  })
  assert.equal(snap, null)
})

test('explorer: one user filter opens the offer + carries surface/dataset/agent', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', agentLabel: 'Revenue expert', columns: [],
    chips: [{ column: 'country', op: '=', values: ['FR'] }],
    q: '', totalCount: 12, totalLoading: false,
  })
  assert.equal(snap.surface, 'explorer')
  assert.equal(snap.dataset, 'Sales')
  assert.equal(snap.agent, 'Revenue expert')
  assert.deepEqual(snap.filters, [{ column: 'country', op: '=', values: ['FR'] }])
  assert.equal(snap.row_count, 12)
})

test('explorer: an effective search (>=2 chars) opens the offer', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [], q: 'acme', totalCount: null, totalLoading: false,
  })
  assert.ok(snap)
  assert.equal(snap.q, 'acme')
  // A 1-char query is below the effective threshold -> not meaningful.
  assert.equal(snapshotFromExplorer({ activeSourceLabel: 'Sales', chips: [], q: 'a' }), null)
})

// --- filters: BETWEEN rendering + values cap 5 with more ----------------------
test('explorer: BETWEEN filter keeps op + its two boundary values', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [
      { column: 'year_month', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31T23:59:59.999999'] },
    ],
  })
  assert.deepEqual(snap.filters, [{
    column: 'year_month', op: 'BETWEEN',
    values: ['2025-01-01', '2025-12-31T23:59:59.999999'],
  }])
})

test('explorer: an IN filter caps values at 5 and reports the cut count as `more`', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [
      { column: 'city', op: 'IN', values: ['a', 'b', 'c', 'd', 'e', 'f', 'g'] },
    ],
  })
  assert.equal(snap.filters[0].op, 'IN')
  assert.deepEqual(snap.filters[0].values, ['a', 'b', 'c', 'd', 'e'])
  assert.equal(snap.filters[0].more, 2)
})

test('explorer: exactly 5 values -> no `more` key', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [
      { column: 'city', op: 'IN', values: ['a', 'b', 'c', 'd', 'e'] },
    ],
  })
  assert.equal('more' in snap.filters[0], false)
})

test('explorer: filter list is capped at SS_FILTERS', () => {
  const chips = []
  for (let i = 0; i < SS_FILTERS + 3; i++) chips.push({ column: 'c' + i, op: '=', values: ['x'] })
  const snap = snapshotFromExplorer({ activeSourceLabel: 'Sales', chips })
  assert.equal(snap.filters.length, SS_FILTERS)
})

test('explorer: a long value + long dataset + long agent are bounded', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'D'.repeat(SS_DATASET_CHARS + 50),
    agentLabel: 'A'.repeat(SS_AGENT_CHARS + 50),
    chips: [{ column: 'c', op: '=', values: ['V'.repeat(SS_VALUE_CHARS + 50)] }],
  })
  assert.equal(snap.dataset.length, SS_DATASET_CHARS)
  assert.equal(snap.agent.length, SS_AGENT_CHARS)
  assert.equal(snap.filters[0].values[0].length, SS_VALUE_CHARS)
})

// --- calc: raw values + loading omission -------------------------------------
test('explorer: calc carries raw String(v) figures (never a formatted number)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    calcColumn: 'amount_eur', calcFns: ['sum', 'median'], calcLoading: false,
    calcValues: { sum: 1234567.89, median: '42' },
  })
  assert.deepEqual(snap.calc, {
    column: 'amount_eur',
    measures: [{ fn: 'sum', value: '1234567.89' }, { fn: 'median', value: '42' }],
  })
})

test('explorer: calc omitted while loading (never a stale figure)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    calcColumn: 'amount_eur', calcFns: ['sum'], calcLoading: true,
    calcValues: { sum: 999 },
  })
  // calcColumn is still chosen -> meaningful, but the calc section is omitted.
  assert.ok(snap)
  assert.equal('calc' in snap, false)
})

test('explorer: calc column chosen with values still null -> meaningful, no calc section', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    calcColumn: 'amount_eur', calcFns: ['sum'], calcLoading: false, calcValues: null,
  })
  assert.ok(snap)
  assert.equal('calc' in snap, false)
})

// --- row_count omission ------------------------------------------------------
test('explorer: row_count omitted while totalLoading (never a stale count)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [{ column: 'c', op: '=', values: ['x'] }],
    totalCount: 500, totalLoading: true,
  })
  assert.equal('row_count' in snap, false)
})

// --- analyze: rows, bucket, loading, non-temporal bucket ---------------------
test('explorer: analyze breakdown maps rows key/m0 to strings + keeps bucket for temporal', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'order_date', type: 'date' }, { name: 'amount', type: 'double' }],
    analyzeGroup: 'order_date', analyzeBucket: 'month', analyzeFn: 'sum',
    analyzeMeasureColumn: 'amount', analyzeLoading: false, analyzeTruncated: true,
    analyzeTotals: { m0: 1000 },
    analyzeRows: [{ key: '2025-01-01', m0: 300 }, { key: '2025-02-01', m0: 700 }],
  })
  assert.deepEqual(snap.analyze, {
    group: 'order_date', bucket: 'month', fn: 'sum', measure_column: 'amount',
    rows: [{ key: '2025-01-01', value: '300' }, { key: '2025-02-01', value: '700' }],
    total: '1000', truncated: true,
  })
})

test('explorer: analyze drops the bucket for a NON-temporal group column', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'country', type: 'string' }],
    analyzeGroup: 'country', analyzeBucket: 'month', analyzeFn: 'count',
    analyzeLoading: false, analyzeRows: [{ key: 'FR', m0: 5 }],
  })
  assert.equal(snap.analyze.bucket, null)
  assert.equal(snap.analyze.measure_column, null) // count -> no measure column
})

test('explorer: analyze omitted while loading and when rows empty', () => {
  const loading = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [{ column: 'c', op: '=', values: ['x'] }],
    analyzeGroup: 'country', analyzeFn: 'count', analyzeLoading: true,
    analyzeRows: [{ key: 'FR', m0: 5 }],
  })
  assert.equal('analyze' in loading, false)
  const empty = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [{ column: 'c', op: '=', values: ['x'] }],
    analyzeGroup: 'country', analyzeFn: 'count', analyzeLoading: false, analyzeRows: [],
  })
  assert.equal('analyze' in empty, false)
})

test('explorer: analyze caps rows at SS_ANALYZE_ROWS', () => {
  const rows = []
  for (let i = 0; i < SS_ANALYZE_ROWS + 3; i++) rows.push({ key: 'k' + i, m0: i })
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'country', type: 'string' }],
    analyzeGroup: 'country', analyzeFn: 'count', analyzeLoading: false, analyzeRows: rows,
  })
  assert.equal(snap.analyze.rows.length, SS_ANALYZE_ROWS)
})

// --- evidence legacy: agent-locked chips gate + inclusion --------------------
test('evidence legacy: agent-locked chips ALONE do not open the offer -> null', () => {
  const snap = snapshotFromEvidence({
    selectedTable: 'orders',
    chips: [{ column: 'status', op: '=', values: ['won'], source: 'agent', editable: false }],
  }, [])
  assert.equal(snap, null)
})

test('evidence legacy: a USER chip opens the offer AND locked chips are still rendered', () => {
  const snap = snapshotFromEvidence({
    selectedTable: 'orders', agentLabel: 'Revenue',
    chips: [
      { column: 'status', op: '=', values: ['won'], source: 'agent', editable: false },
      { column: 'country', op: '=', values: ['FR'], source: 'user', editable: true },
    ],
  }, [])
  assert.ok(snap)
  assert.equal(snap.surface, 'evidence')
  assert.equal(snap.dataset, 'orders')
  // BOTH chips travel (the locked one defines the scope of the figures).
  assert.equal(snap.filters.length, 2)
  assert.deepEqual(snap.filters.map((f) => f.column), ['status', 'country'])
})

test('evidence legacy: a drill opens the offer + carries the drill labels', () => {
  const snap = snapshotFromEvidence({
    selectedTable: 'orders',
    chips: [{ column: 'status', op: '=', values: ['won'], source: 'agent', editable: false }],
    drill: [{ column: 'region', value: 'EMEA' }],
  }, [])
  assert.ok(snap)
  assert.deepEqual(snap.drill, [{ column: 'region', value: 'EMEA' }])
})

test('evidence legacy: dataset falls back to the first source label when no table selected', () => {
  const snap = snapshotFromEvidence({
    selectedTable: null, sources: [{ dataset: 'primary_orders' }],
    chips: [{ column: 'c', op: '=', values: ['x'], source: 'user', editable: true }],
  }, [])
  assert.equal(snap.dataset, 'primary_orders')
})

// --- pickSnapshot priority ---------------------------------------------------
test('pickSnapshot: Evidence panel open wins over the standalone explorer', () => {
  const snap = pickSnapshot({
    sourcesState: {
      open: true, agentKey: 'ag_src', activeSourceLabel: 'ExplorerDS',
      chips: [{ column: 'x', op: '=', values: ['1'] }],
    },
    evidenceState: {
      open: true, exchangeId: 7, sourceTabKey: null, selectedTable: 'EvidenceDS',
      chips: [{ column: 'y', op: '=', values: ['2'], source: 'user', editable: true }],
    },
    agentLabels: { ag_src: 'SrcAgent' },
  })
  assert.equal(snap.surface, 'evidence')
  assert.equal(snap.dataset, 'EvidenceDS')
})

test("pickSnapshot: Evidence sourceTabKey 'agent:' -> explorer snapshot relabelled 'evidence'", () => {
  const snap = pickSnapshot({
    sourcesState: {
      open: true, agentKey: 'ag_embed', activeSourceLabel: 'EmbeddedDS',
      chips: [{ column: 'city', op: '=', values: ['Paris'] }],
    },
    evidenceState: {
      open: true, exchangeId: 9, agentKey: 'ag_exch', sourceTabKey: 'agent:123',
      chips: [],
    },
    agentLabels: { ag_exch: 'Exchange Agent', ag_embed: 'Embedded Agent' },
  })
  // Explorer state is used, relabelled surface 'evidence', with the EXCHANGE agent label.
  assert.equal(snap.surface, 'evidence')
  assert.equal(snap.dataset, 'EmbeddedDS')
  assert.equal(snap.agent, 'Exchange Agent')
  assert.deepEqual(snap.filters, [{ column: 'city', op: '=', values: ['Paris'] }])
})

test('pickSnapshot: neither panel open -> null; explorer used when only it is open', () => {
  assert.equal(pickSnapshot({ sourcesState: { open: false }, evidenceState: { open: false } }), null)
  const snap = pickSnapshot({
    sourcesState: {
      open: true, agentKey: 'ag', activeSourceLabel: 'DS',
      chips: [{ column: 'x', op: '=', values: ['1'] }],
    },
    evidenceState: { open: false },
    agentLabels: { ag: 'A' },
  })
  assert.equal(snap.surface, 'explorer')
})

// --- snapshotSignature stability ---------------------------------------------
test('snapshotSignature: excludes row_count / calc values / analyze rows', () => {
  const base = {
    activeSourceLabel: 'Sales', agentLabel: 'Rev', chips: [{ column: 'c', op: '=', values: ['x'] }],
    columns: [{ name: 'g', type: 'string' }, { name: 'amount', type: 'double' }],
    calcColumn: 'amount', calcFns: ['sum'], calcLoading: false, calcValues: { sum: 1 },
    analyzeGroup: 'g', analyzeFn: 'count', analyzeLoading: false,
    analyzeRows: [{ key: 'FR', m0: 3 }], analyzeTotals: { m0: 3 }, analyzeTruncated: false,
    totalCount: 10, totalLoading: false,
  }
  const a = snapshotFromExplorer(base)
  const b = snapshotFromExplorer({
    ...base,
    totalCount: 9999,                       // row_count differs
    calcValues: { sum: 424242 },            // calc figure differs
    analyzeRows: [{ key: 'FR', m0: 88888 }], // analyze figure differs
    analyzeTotals: { m0: 88888 },
  })
  assert.equal(snapshotSignature(a), snapshotSignature(b))
})

test('snapshotSignature: a changed FILTER value re-offers (signature differs)', () => {
  const a = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [{ column: 'c', op: '=', values: ['FR'] }],
  })
  const b = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [{ column: 'c', op: '=', values: ['DE'] }],
  })
  assert.notEqual(snapshotSignature(a), snapshotSignature(b))
})

test('snapshotSignature: a changed calc COLUMN re-offers', () => {
  const common = {
    activeSourceLabel: 'Sales', chips: [], calcLoading: false,
    columns: [{ name: 'a', type: 'double' }, { name: 'b', type: 'double' }],
  }
  const a = snapshotFromExplorer({ ...common, calcColumn: 'a', calcFns: ['sum'], calcValues: { sum: 1 } })
  const b = snapshotFromExplorer({ ...common, calcColumn: 'b', calcFns: ['sum'], calcValues: { sum: 1 } })
  assert.notEqual(snapshotSignature(a), snapshotSignature(b))
})

test('snapshotSignature: null snapshot -> null signature', () => {
  assert.equal(snapshotSignature(null), null)
})
