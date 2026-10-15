// Live widget payloads (client twin of evidence/chart_payload.py) - run with `node --test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  toNumber, capturedResult, buildChartPayload, buildKpiPayload, widgetRenderData, MAX_SLICES,
} from '../src/composables/widgetData.js'

const RESULT = {
  captured: true,
  columns: ['Region', 'revenue', 'budget'],
  rows: [['Nord', 1200, 1000], ['Sud', '950', 900], ['Ouest', null, 800]],
  row_count: 3,
  truncated: false,
}

test('toNumber mirrors _to_number (formatted strings, booleans, separators)', () => {
  assert.equal(toNumber(12), 12)
  assert.equal(toNumber(true), null)
  assert.equal(toNumber(null), null)
  assert.equal(toNumber('1 234,5'), 1234.5)
  assert.equal(toNumber('1,234.56'), 1234.56)
  assert.equal(toNumber('12.5%'), 12.5)
  assert.equal(toNumber('€ 90'), 90)
  assert.equal(toNumber('1e3'), 1000)
  assert.equal(toNumber('abc'), null)
  assert.equal(toNumber('42 units'), 42)
  assert.equal(toNumber(Infinity), null)
})

test('capturedResult normalizes a live generated_sql capture', () => {
  assert.deepEqual(capturedResult({ columns: ['a'], rows: [[1]] }, 7), {
    captured: true, columns: ['a'], rows: [[1]], row_count: 7, truncated: false,
  })
  assert.equal(capturedResult(null), null)
  assert.equal(capturedResult({ columns: ['a'] }), null)
})

test('bar chart: one dataset per y column, case-insensitive columns, gaps kept', () => {
  const out = buildChartPayload(RESULT, { type: 'bar', x: 'region', y: ['REVENUE', 'budget'] })
  assert.equal(out.ok, true)
  assert.deepEqual(out.labels, ['Nord', 'Sud', 'Ouest'])
  assert.deepEqual(out.datasets[0], { label: 'REVENUE', data: [1200, 950, null] })
  assert.deepEqual(out.datasets[1].data, [1000, 900, 800])
})

test('chart honest failures', () => {
  assert.deepEqual(buildChartPayload(null, { type: 'bar', x: 'a', y: ['b'] }), { ok: false, reason: 'no_data' })
  assert.deepEqual(buildChartPayload(RESULT, { type: 'radar', x: 'Region', y: ['revenue'] }), { ok: false, reason: 'bad_spec' })
  assert.deepEqual(buildChartPayload(RESULT, { type: 'bar', x: 'nope', y: ['revenue'] }), { ok: false, reason: 'x_not_found' })
  assert.deepEqual(buildChartPayload(RESULT, { type: 'bar', x: 'Region', y: ['nope'] }), { ok: false, reason: 'y_not_found' })
  const text = { ...RESULT, rows: [['a', 'x', 'y']] }
  assert.deepEqual(buildChartPayload(text, { type: 'line', x: 'Region', y: ['revenue'] }), { ok: false, reason: 'no_numeric' })
})

test('pie / donut: positive values only, sorted, tail folded into Other', () => {
  const rows = Array.from({ length: 15 }, (_, i) => ['c' + i, i + 1])
  const res = { captured: true, columns: ['cat', 'n'], rows, row_count: 15 }
  const out = buildChartPayload(res, { type: 'donut', x: 'cat', y: ['n'] })
  assert.equal(out.ok, true)
  assert.equal(out.labels.length, MAX_SLICES)
  assert.equal(out.labels[0], 'c14')
  assert.equal(out.labels[MAX_SLICES - 1], 'Other')
  assert.equal(out.truncated, true)
  const sum = rows.reduce((a, r) => a + r[1], 0)
  assert.equal(out.datasets[0].data.reduce((a, v) => a + v, 0), sum)
})

test('kpi: first row, optional deltas', () => {
  const res = { captured: true, columns: ['total', 'delta_pct'], rows: [[4200, '3.5']], row_count: 1 }
  assert.deepEqual(buildKpiPayload(res, { label: 'Total', value: 'TOTAL', delta_pct: 'delta_pct' }), {
    ok: true, label: 'Total', value: 4200, delta_pct: 3.5,
  })
  assert.deepEqual(buildKpiPayload(res, { label: 'x', value: 'nope' }), { ok: false, reason: 'value_not_found' })
  assert.deepEqual(buildKpiPayload(res, {}), { ok: false, reason: 'bad_spec' })
})

test('widgetRenderData: the server payload wins over the live build', () => {
  const widget = { id: 'w1', kind: 'chart', chart: { type: 'bar', x: 'Region', y: ['revenue'] } }
  const server = { ok: true, labels: ['S'], datasets: [] }
  assert.equal(widgetRenderData(widget, { serverData: server, result: RESULT }).data, server)
  assert.equal(widgetRenderData(widget, { result: RESULT }).data.ok, true)
  assert.equal(widgetRenderData({ kind: 'table' }, { result: RESULT }).data, null)
  assert.equal(widgetRenderData({ kind: 'table' }, { result: RESULT }).result, RESULT)
  // No rows from any source yet: no payload (the card shows its waiting state).
  assert.equal(widgetRenderData(widget, { result: null }).data, null)
})
