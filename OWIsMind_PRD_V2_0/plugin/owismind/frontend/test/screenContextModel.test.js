// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/screenContextModel.test.js
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
  describeSnapshot,
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

// --- the unified Analyze workspace, projected onto the frozen blocks ----------
// The standalone explorer shapes its figures in the workspace (measures + optional
// grouping). The payload contract is UNCHANGED: grouped -> `analyze`, ungrouped -> `calc`.
test('workspace: the DEFAULT state (one row count, no group) is not user-shaped -> null', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [], q: '',
    totalCount: 640, totalLoading: false,
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'count', column: null }],
    workspaceGroup: null, workspaceLoading: false,
    workspaceRows: [{ m0: 640 }],
  })
  assert.equal(snap, null)
})

test('workspace: a GROUPING fills the analyze block (first measure, rows, total, truncated)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [], q: '',
    columns: [{ name: 'Solution', type: 'string' }, { name: 'Revenues', type: 'double' }],
    totalCount: 640, totalLoading: false,
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }, { fn: 'count', column: null }],
    workspaceGroup: 'Solution', workspaceBucket: 'month', workspaceLoading: false,
    workspaceRows: [{ key: 'Voice', m0: 900, m1: 12 }, { key: 'Data', m0: 300, m1: 4 }],
    workspaceTotals: { m0: 1200, m1: 16 },
    workspaceTruncated: true,
  })
  assert.ok(snap)
  assert.equal(snap.surface, 'explorer')
  assert.deepEqual(snap.analyze, {
    group: 'Solution', bucket: null, fn: 'sum', measure_column: 'Revenues',
    rows: [{ key: 'Voice', value: '900' }, { key: 'Data', value: '300' }],
    total: '1200', truncated: true,
  })
  assert.equal('calc' in snap, false) // grouped -> the figures live in `analyze`
  assert.equal(snap.row_count, 640)
})

test('workspace: a TEMPORAL grouping keeps its bucket', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'order_date', type: 'date' }],
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'count', column: null }],
    workspaceGroup: 'order_date', workspaceBucket: 'quarter', workspaceLoading: false,
    workspaceRows: [{ key: '2025-01-01', m0: 12 }],
  })
  assert.equal(snap.analyze.bucket, 'quarter')
  assert.equal(snap.analyze.fn, 'count')
  assert.equal(snap.analyze.measure_column, null)
})

test('workspace: the analyze measure is the first one the contract accepts (count/sum/avg)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'Solution', type: 'string' }, { name: 'Revenues', type: 'double' }],
    workspaceActive: true,
    // median is a legal WORKSPACE measure but not a legal `analyze` fn: the block travels
    // with the next qualifying measure, read from ITS position (m1).
    workspaceMeasures: [{ fn: 'median', column: 'Revenues' }, { fn: 'avg', column: 'Revenues' }],
    workspaceGroup: 'Solution', workspaceLoading: false,
    workspaceRows: [{ key: 'Voice', m0: 5, m1: 42 }],
    workspaceTotals: { m0: 6, m1: 40 },
  })
  assert.equal(snap.analyze.fn, 'avg')
  assert.equal(snap.analyze.measure_column, 'Revenues')
  assert.deepEqual(snap.analyze.rows, [{ key: 'Voice', value: '42' }])
  assert.equal(snap.analyze.total, '40')
})

test('workspace: no measure qualifies for analyze -> no analyze block (still user-shaped)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'Solution', type: 'string' }],
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'median', column: 'Revenues' }],
    workspaceGroup: 'Solution', workspaceLoading: false,
    workspaceRows: [{ key: 'Voice', m0: 5 }],
  })
  assert.ok(snap)
  assert.equal('analyze' in snap, false)
})

test('workspace: MEASURES ONLY (no grouping) fill the calc block with the KPI figures', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [], q: '',
    columns: [{ name: 'Revenues', type: 'double' }],
    totalCount: 640, totalLoading: false,
    workspaceActive: true,
    workspaceMeasures: [
      { fn: 'count', column: null },
      { fn: 'sum', column: 'Revenues' },
      { fn: 'avg', column: 'Revenues' },
    ],
    workspaceGroup: null, workspaceLoading: false,
    workspaceRows: [{ m0: 640, m1: 1234.5, m2: 12.3 }],
  })
  assert.ok(snap)
  // The row count needs no column: it already travels as `row_count`.
  assert.deepEqual(snap.calc, {
    column: 'Revenues',
    measures: [{ fn: 'sum', value: '1234.5' }, { fn: 'avg', value: '12.3' }],
  })
  assert.equal('analyze' in snap, false)
  assert.equal(snap.row_count, 640)
})

test('workspace: the calc block carries ONE column (the first measured one)', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    workspaceActive: true,
    workspaceMeasures: [
      { fn: 'sum', column: 'Revenues' },
      { fn: 'count_distinct', column: 'Account' },
      { fn: 'max', column: 'Revenues' },
    ],
    workspaceGroup: null, workspaceLoading: false,
    workspaceRows: [{ m0: 100, m1: 7, m2: 60 }],
  })
  assert.equal(snap.calc.column, 'Revenues')
  assert.deepEqual(snap.calc.measures, [{ fn: 'sum', value: '100' }, { fn: 'max', value: '60' }])
})

test('workspace: figures omitted while loading / before the first result (still shaped)', () => {
  const loading = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'Solution', type: 'string' }],
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }],
    workspaceGroup: 'Solution', workspaceLoading: true,
    workspaceRows: [{ key: 'Voice', m0: 900 }],
  })
  assert.ok(loading)
  assert.equal('analyze' in loading, false)
  const noResult = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    workspaceActive: true,
    workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }],
    workspaceGroup: null, workspaceLoading: false, workspaceRows: [],
  })
  assert.ok(noResult)
  assert.equal('calc' in noResult, false)
})

test('workspace: an INACTIVE workspace leaves the legacy calc / analyze path untouched', () => {
  const snap = snapshotFromExplorer({
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'country', type: 'string' }],
    // The Evidence hosts never activate the workspace: their own state must still win.
    workspaceActive: false,
    workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }], workspaceGroup: 'Solution',
    workspaceRows: [{ key: 'Voice', m0: 900 }], workspaceLoading: false,
    calcColumn: 'amount', calcFns: ['sum'], calcLoading: false, calcValues: { sum: 5 },
    analyzeGroup: 'country', analyzeFn: 'count', analyzeLoading: false,
    analyzeRows: [{ key: 'FR', m0: 3 }],
  })
  assert.deepEqual(snap.calc, { column: 'amount', measures: [{ fn: 'sum', value: '5' }] })
  assert.equal(snap.analyze.group, 'country')
})

test('workspace: a shaped workspace re-signs when the grouping or the measures change', () => {
  const base = {
    activeSourceLabel: 'Sales', chips: [],
    columns: [{ name: 'Solution', type: 'string' }, { name: 'Revenues', type: 'double' }],
    workspaceActive: true, workspaceLoading: false,
    workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }],
    workspaceGroup: 'Solution',
    workspaceRows: [{ key: 'Voice', m0: 900 }],
  }
  const a = snapshotFromExplorer(base)
  // Same shape, different FIGURES -> same signature (an opt-out must not churn).
  const sameShape = snapshotFromExplorer({ ...base, workspaceRows: [{ key: 'Voice', m0: 42 }] })
  assert.equal(snapshotSignature(a), snapshotSignature(sameShape))
  const otherGroup = snapshotFromExplorer({ ...base, workspaceGroup: 'Account' })
  assert.notEqual(snapshotSignature(a), snapshotSignature(otherGroup))
  const otherMeasure = snapshotFromExplorer({ ...base, workspaceMeasures: [{ fn: 'avg', column: 'Revenues' }] })
  assert.notEqual(snapshotSignature(a), snapshotSignature(otherMeasure))
})

test('workspace: pickSnapshot carries it through the standalone explorer', () => {
  const snap = pickSnapshot({
    sourcesState: {
      open: true, agentKey: 'ag', activeSourceLabel: 'Revenues dataset',
      chips: [], q: '',
      columns: [{ name: 'Solution', type: 'string' }],
      workspaceActive: true, workspaceLoading: false,
      workspaceMeasures: [{ fn: 'sum', column: 'Revenues' }],
      workspaceGroup: 'Solution',
      workspaceRows: [{ key: 'Voice', m0: 900 }],
    },
    evidenceState: { open: false },
    agentLabels: { ag: 'Revenue expert' },
  })
  assert.ok(snap)
  assert.equal(snap.surface, 'explorer')
  assert.equal(snap.agent, 'Revenue expert')
  assert.equal(snap.analyze.group, 'Solution')
  // The describe projection surfaces it as the ANALYZE row of the chip detail.
  const line = describeSnapshot(snap).find((r) => r.labelKey === 'prompt.screen.d.analyze')
  assert.ok(line)
  assert.equal(line.fnKey, 'src.calc.sum')
  assert.equal(line.group, 'Solution')
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

// --- describeSnapshot: full-transparency ordered projection ------------------
test('describeSnapshot: null / non-object -> []', () => {
  assert.deepEqual(describeSnapshot(null), [])
  assert.deepEqual(describeSnapshot(undefined), [])
  assert.deepEqual(describeSnapshot(42), [])
  assert.deepEqual(describeSnapshot('x'), [])
})

test('describeSnapshot: empty-but-object snapshot -> []', () => {
  assert.deepEqual(describeSnapshot({}), [])
})

test('describeSnapshot: full snapshot -> ordered rows covering every field', () => {
  const snap = {
    surface: 'explorer',
    dataset: 'Sales',
    agent: 'Revenue expert',
    filters: [
      { column: 'country', op: '=', values: ['FR'] },
      { column: 'city', op: 'IN', values: ['a', 'b'], more: 3 },
      { column: 'year_month', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31'] },
    ],
    q: 'acme',
    row_count: 128,
    drill: [{ column: 'region', value: 'EMEA' }],
    calc: { column: 'amount_eur', measures: [{ fn: 'sum', value: '1234' }, { fn: 'count_distinct', value: '7' }] },
    analyze: {
      group: 'order_date', bucket: 'month', fn: 'sum', measure_column: 'amount',
      rows: [{ key: '2025-01', value: '300' }, { key: '2025-02', value: '700' }],
      total: '1000', truncated: true,
    },
  }
  const rows = describeSnapshot(snap)
  // Ordered: dataset, agent, 3 filters, q, rows, drill, 2 calc, analyze = 10 entries.
  assert.deepEqual(rows.map((r) => r.key), [
    'dataset', 'agent', 'filter-0', 'filter-1', 'filter-2', 'q', 'rows', 'drill-0',
    'calc-0', 'calc-1', 'analyze',
  ])
  assert.deepEqual(rows.map((r) => r.labelKey), [
    'prompt.screen.d.dataset', 'prompt.screen.d.agent',
    'prompt.screen.d.filter', 'prompt.screen.d.filter', 'prompt.screen.d.filter',
    'prompt.screen.d.q', 'prompt.screen.d.rows', 'prompt.screen.d.drill',
    'prompt.screen.d.calc', 'prompt.screen.d.calc', 'prompt.screen.d.analyze',
  ])
  // Values verbatim.
  assert.equal(rows[0].text, 'Sales')
  assert.equal(rows[1].text, 'Revenue expert')
  assert.equal(rows[5].text, '"acme"') // q quoted
  assert.equal(rows[6].text, '128')    // row_count as string
  assert.equal(rows[7].text, 'region = EMEA')
})

test('describeSnapshot: filter texts render =, IN (+more), BETWEEN', () => {
  const rows = describeSnapshot({
    dataset: 'Sales',
    filters: [
      { column: 'country', op: '=', values: ['FR'] },
      { column: 'city', op: 'IN', values: ['a', 'b'], more: 3 },
      { column: 'year_month', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31'] },
    ],
  })
  const f = rows.filter((r) => r.labelKey === 'prompt.screen.d.filter')
  assert.deepEqual(f.map((r) => r.text), [
    'country = "FR"',
    'city IN ("a", "b")',
    'year_month BETWEEN 2025-01-01 AND 2025-12-31',
  ])
  // The overflow marker is NOT baked into the text: the row carries `more` so the
  // component renders it translated ((+3 autres) / (+3 more)).
  assert.deepEqual(f.map((r) => r.more), [0, 3, 0])
})

test('describeSnapshot: calc rows carry the src.calc.* fnKey (count_distinct -> distinct)', () => {
  const rows = describeSnapshot({
    dataset: 'Sales',
    calc: { column: 'amount_eur', measures: [
      { fn: 'sum', value: '1234' },
      { fn: 'median', value: '42' },
      { fn: 'count_distinct', value: '7' },
    ] },
  })
  const calc = rows.filter((r) => r.labelKey === 'prompt.screen.d.calc')
  assert.deepEqual(calc.map((r) => r.fnKey), ['src.calc.sum', 'src.calc.median', 'src.calc.distinct'])
  assert.equal(calc[0].text, '(amount_eur) = 1234')
})

test('describeSnapshot: analyze one-liner (sum/measure/bucket) + rows joined + truncated flag', () => {
  const [line] = describeSnapshot({
    dataset: 'Sales',
    analyze: {
      group: 'order_date', bucket: 'month', fn: 'sum', measure_column: 'amount',
      rows: [{ key: '2025-01', value: '300' }, { key: '2025-02', value: '700' }],
      truncated: true,
    },
  }).filter((r) => r.labelKey === 'prompt.screen.d.analyze')
  // Fully structured: the component translates every connector; only identifiers and
  // values stay verbatim here.
  assert.equal(line.fnKey, 'src.calc.sum')
  assert.equal(line.measureText, 'amount')
  assert.equal(line.group, 'order_date')
  assert.equal(line.bucketKey, 'src.an.bucket.month')
  assert.equal(line.topText, '2025-01 = 300; 2025-02 = 700')
  assert.equal(line.truncated, true)
})

test('describeSnapshot: analyze count uses "rows" as the measure and drops the bucket when absent', () => {
  const [line] = describeSnapshot({
    dataset: 'Sales',
    analyze: {
      group: 'country', bucket: null, fn: 'count', measure_column: null,
      rows: [{ key: 'FR', value: '5' }], truncated: false,
    },
  }).filter((r) => r.labelKey === 'prompt.screen.d.analyze')
  // count has no measured column: measureText is null (the component shows the
  // translated "rows" word) and the absent bucket yields no bucketKey.
  assert.equal(line.fnKey, 'src.calc.count')
  assert.equal(line.measureText, null)
  assert.equal(line.bucketKey, null)
  assert.equal(line.topText, 'FR = 5')
  assert.equal(line.truncated, false)
})
