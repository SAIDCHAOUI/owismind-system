// Multi-SQL Evidence selector choices - run with `node --test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { sqlChoices } from '../src/composables/sqlChoices.js'
import { reduceWorkspace } from '../src/composables/workspaceModel.js'

const ev = (seq, op, p) => ({ type: 'workspace', v: 1, op, seq, ...p })
const WS = reduceWorkspace([
  ev(1, 'plan.set', { mission: 'M', origin: 'model', steps: [{ id: 'p1', label: 'Revenus' }, { id: 'p2', label: 'Tickets' }] }),
  ev(2, 'prov.set', { sql_id: 's1q1', agent_key: 'revenue', tool: 'semantic-model-query', success: true, step_id: 'p1', row_count: 7 }),
  ev(3, 'prov.set', { sql_id: 's2q1', agent_key: 'tickets', tool: 'semantic-model-query', success: true, step_id: 'p2', row_count: 4 }),
  ev(4, 'widget.add', { id: 'w1', kind: 'table', title: 'Table T', sql_id: 's2q1' }),
])

test('server queries drive the list; the workspace adds step labels and widgets', () => {
  const meta = {
    sql_id: 's2q1',
    queries: [
      { index: 1, success: true, row_count: 7, sql_id: 's1q1', step_index: 1, agent_key: 'revenue', active: false, widgets: [{ id: 'w9', title: 'Chart C' }] },
      { index: 2, success: false, row_count: null, step_index: 1, active: false },
      { index: 3, success: true, row_count: 4, sql_id: 's2q1', step_index: 2, agent_key: 'tickets', active: true, widgets: [] },
    ],
  }
  const c = sqlChoices(meta, WS, 's2q1')
  assert.deepEqual(c.map((x) => x.sqlId), ['s1q1', 's2q1'])
  assert.deepEqual(c.map((x) => x.n), [1, 2])
  assert.deepEqual(c[0], { sqlId: 's1q1', n: 1, active: false, success: true, stepIndex: 1, stepLabel: 'Revenus', agentKey: 'revenue', widgets: ['Chart C'], rowCount: 7 })
  assert.equal(c[1].active, true)
  // Server sent no widget titles: the workspace widgets bound to that sql_id are used.
  assert.deepEqual(c[1].widgets, ['Table T'])
})

test('without a workspace: server fields only', () => {
  const meta = { queries: [{ success: true, row_count: 3, sql_id: 's1q1', step_index: 2, active: true }, { success: false, sql_id: 's1q2', active: false }] }
  const c = sqlChoices(meta, null, null)
  assert.equal(c[0].stepIndex, 2)
  assert.equal(c[0].stepLabel, null)
  assert.equal(c[1].success, false)
  assert.equal(c[1].rowCount, null)
})

test('older backend (no sql_id in queries): the workspace sql_ids, active from the request', () => {
  const c = sqlChoices({ queries: [{ index: 1, success: true }] }, WS, 's1q1')
  assert.deepEqual(c.map((x) => x.sqlId), ['s1q1', 's2q1'])
  assert.deepEqual(c.map((x) => x.active), [true, false])
  assert.equal(c[0].rowCount, 7)
  assert.deepEqual(sqlChoices(null, null, null), [])
})

test('a carried widget (continued Studio) never labels a query of this exchange', () => {
  const ws = reduceWorkspace([
    { type: 'workspace', v: 1, op: 'studio.carry', seq: 1, base_exchange_id: 'ex-a', widgets: [{ id: 'w1', kind: 'table', title: 'Old', sql_id: 's1q1', origin: 'ex-a' }] },
    { type: 'workspace', v: 1, op: 'widget.add', seq: 2, id: 'w2', kind: 'table', title: 'New', sql_id: 's1q1' },
  ])
  const out = sqlChoices({ queries: [{ sql_id: 's1q1' }] }, ws, 's1q1')
  assert.deepEqual(out[0].widgets, ['New'])
})
