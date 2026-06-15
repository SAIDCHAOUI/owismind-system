// test/chartGeometry.test.js — pure unit tests for chartGeometry.js
// No install — run from Plugin/owismind/frontend/:
//   node --test test/chartGeometry.test.js
//   node --test test/*.test.js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildChartGeometry } from '../src/components/evidence/chartGeometry.js'

// ── Fixtures ─────────────────────────────────────────────────────────────────

const COLUMNS = ['Month', 'Revenue', 'Cost']
const ROWS = [
  ['Jan', 1000, 400],
  ['Feb', 1500, 600],
  ['Mar', 1200, 500],
  ['Apr', 1800, 700],
]

// ── LINE chart ────────────────────────────────────────────────────────────────

test('line chart: ok=true with valid spec', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, true)
  assert.equal(g.type, 'line')
})

test('line chart: polylines has correct count (one per y series)', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue', 'Cost'] })
  assert.equal(g.ok, true)
  assert.equal(g.polylines.length, 2)
  assert.equal(g.polylines[0].key, 'Revenue')
  assert.equal(g.polylines[1].key, 'Cost')
})

test('line chart: dots count matches row count per series', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.polylines[0].dots.length, ROWS.length)
})

test('line chart: case-insensitive column resolution', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'month', y: ['REVENUE'] })
  assert.equal(g.ok, true)
  assert.equal(g.polylines[0].key, 'REVENUE')
})

test('line chart: missing x column → ok=false', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'NoSuchColumn', y: ['Revenue'] })
  assert.equal(g.ok, false)
  assert.ok(g.reason.includes('x column not found'))
})

test('line chart: missing y column → ok=false', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Profit'] })
  assert.equal(g.ok, false)
  assert.ok(g.reason.includes('y column not found'))
})

test('line chart: non-numeric cells coerced to 0, does not crash', () => {
  const rows = [['Jan', 'N/A', null], ['Feb', 500, undefined], ['Mar', '700', 200]]
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows, x: 'Month', y: ['Revenue', 'Cost'] })
  assert.equal(g.ok, true)
  // 'N/A' → 0, null → 0, undefined → 0, '700' → 700
  assert.equal(g.polylines[0].dots[0].value, 0)
  assert.equal(g.polylines[0].dots[2].value, 700)
})

test('line chart: no rows → ok=false', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: [], x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, false)
})

test('line chart: truncated flag when rows exceed cap', () => {
  const bigRows = Array.from({ length: 70 }, (_, i) => ['M' + i, i * 100, i * 40])
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: bigRows, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, true)
  assert.equal(g.truncated, true)
})

// ── BAR chart ─────────────────────────────────────────────────────────────────

test('bar chart: ok=true with valid spec', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, true)
  assert.equal(g.type, 'bar')
})

test('bar chart: bars array has one entry per y series', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue', 'Cost'] })
  assert.equal(g.bars.length, 2)
})

test('bar chart: rects count matches row count', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.bars[0].rects.length, ROWS.length)
})

test('bar chart: rect dimensions are positive numbers', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  const rect = g.bars[0].rects[0]
  assert.ok(typeof rect.x === 'number')
  assert.ok(typeof rect.y === 'number')
  assert.ok(rect.width > 0)
  assert.ok(rect.height >= 1) // min height 1 enforced
})

test('bar chart: case-insensitive column resolution', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: ROWS, x: 'MONTH', y: ['cost'] })
  assert.equal(g.ok, true)
})

test('bar chart: non-numeric cells → height 0 clamped to 1 (no crash)', () => {
  const rows = [['A', 'bad', null], ['B', 200, 50]]
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, true)
  assert.ok(g.bars[0].rects[0].height >= 1)
})

test('bar chart: no rows → ok=false', () => {
  const g = buildChartGeometry({ type: 'bar', columns: COLUMNS, rows: [], x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, false)
})

// ── PIE chart ─────────────────────────────────────────────────────────────────

const PIE_COLUMNS = ['Category', 'Share']
const PIE_ROWS = [
  ['Alpha', 40],
  ['Beta', 30],
  ['Gamma', 20],
  ['Delta', 10],
]

test('pie chart: ok=true with valid spec', () => {
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows: PIE_ROWS, x: 'Category', y: ['Share'] })
  assert.equal(g.ok, true)
  assert.equal(g.type, 'pie')
})

test('pie chart: wedges sum to ~100%', () => {
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows: PIE_ROWS, x: 'Category', y: ['Share'] })
  const totalPct = g.wedges.reduce((s, w) => s + w.pct, 0)
  assert.ok(Math.abs(totalPct - 100) < 0.1, 'wedge percentages should sum to ~100')
})

test('pie chart: wedge count matches slice count', () => {
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows: PIE_ROWS, x: 'Category', y: ['Share'] })
  assert.equal(g.wedges.length, PIE_ROWS.length)
})

test('pie chart: case-insensitive column resolution', () => {
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows: PIE_ROWS, x: 'CATEGORY', y: ['share'] })
  assert.equal(g.ok, true)
})

test('pie chart: all-zero values → ok=false', () => {
  const rows = [['A', 0], ['B', 0]]
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows, x: 'Category', y: ['Share'] })
  assert.equal(g.ok, false)
})

test('pie chart: negative values are dropped (not included in pie)', () => {
  const rows = [['A', 50], ['B', -10], ['C', 30]]
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows, x: 'Category', y: ['Share'] })
  assert.equal(g.ok, true)
  assert.equal(g.wedges.length, 2) // B is dropped
})

test('pie chart: caps at 12 slices and adds "Other" bucket', () => {
  const bigRows = Array.from({ length: 15 }, (_, i) => ['Cat' + i, 10])
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows: bigRows, x: 'Category', y: ['Share'] })
  assert.equal(g.ok, true)
  assert.equal(g.truncated, true)
  // 12 kept + 1 "Other"
  assert.equal(g.wedges.length, 13)
  assert.equal(g.wedges[12].isOther, true)
})

test('pie chart: non-numeric cells → treated as 0, dropped from pie', () => {
  const rows = [['A', 'N/A'], ['B', 80], ['C', null]]
  const g = buildChartGeometry({ type: 'pie', columns: PIE_COLUMNS, rows, x: 'Category', y: ['Share'] })
  assert.equal(g.ok, true)
  assert.equal(g.wedges.length, 1) // only B survives (positive)
})

// ── Guard cases (missing spec) ────────────────────────────────────────────────

test('unknown type → ok=false', () => {
  const g = buildChartGeometry({ type: 'scatter', columns: COLUMNS, rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, false)
  assert.ok(g.reason.includes('unknown chart type'))
})

test('empty columns → ok=false', () => {
  const g = buildChartGeometry({ type: 'bar', columns: [], rows: ROWS, x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, false)
})

test('missing y array → ok=false', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: ROWS, x: 'Month', y: [] })
  assert.equal(g.ok, false)
})

test('captured:false scenario — rows=[] → line ok=false (no rows)', () => {
  const g = buildChartGeometry({ type: 'line', columns: COLUMNS, rows: [], x: 'Month', y: ['Revenue'] })
  assert.equal(g.ok, false)
})
