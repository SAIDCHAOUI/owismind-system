// Plan settling on a finished run (PlanCard) - run with `node --test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { planNeedsSettle, settlePlanState } from '../src/composables/planSettle.js'
import { planProgress, stepsWithProgress, reduceWorkspace, finalizeWorkspace } from '../src/composables/workspaceModel.js'

function stateWith(status, steps) {
  return { status, plan: { version: 1, origin: 'model', mission: 'm', steps }, notes: [], widgets: [] }
}

const STEPS = [
  { id: 'p1', label: 'Revenue', status: 'done' },
  { id: 'p2', label: 'Tickets', status: 'done' },
  { id: 'p3', label: 'Synthesis', status: 'todo' },
]

test('a successful run closes the unchecked synthesis step', () => {
  const view = settlePlanState(stateWith('done', STEPS))
  assert.deepEqual(view.plan.steps.map((s) => s.status), ['done', 'done', 'done'])
  assert.deepEqual(planProgress(view), { done: 3, total: 3, pct: 100 })
})

test('a step still running on a successful run is closed too; an error step is kept', () => {
  const view = settlePlanState(stateWith('done', [
    { id: 'p1', label: 'a', status: 'error' },
    { id: 'p2', label: 'b', status: 'running' },
    { id: 'p3', label: 'c', status: 'todo' },
  ]))
  assert.deepEqual(view.plan.steps.map((s) => s.status), ['error', 'done', 'done'])
})

test('a batch step closed on success is filled up to its total', () => {
  const view = settlePlanState(stateWith('done', [{ id: 'p1', label: 'a', status: 'running', total: 4, done: 2, unit: 'pays' }]))
  const [step] = stepsWithProgress(view)
  assert.equal(step.done, 4)
  assert.equal(step.batchPct, 100)
})

test('running, stopped and error runs keep their honest state (same object)', () => {
  for (const status of ['running', 'stopped', 'error']) {
    const state = stateWith(status, STEPS)
    assert.equal(planNeedsSettle(state), false)
    assert.equal(settlePlanState(state), state)
  }
})

test('the stored state is never mutated; nothing to settle returns the same object', () => {
  const state = stateWith('done', STEPS.map((s) => ({ ...s })))
  settlePlanState(state)
  assert.equal(state.plan.steps[2].status, 'todo')
  const closed = stateWith('done', [{ id: 'p1', label: 'a', status: 'done' }])
  assert.equal(settlePlanState(closed), closed)
  assert.equal(settlePlanState(null), null)
  const noPlan = { status: 'done', plan: null, notes: [], widgets: [] }
  assert.equal(settlePlanState(noPlan), noPlan)
})

test('a reloaded conversation (replayed events + sealed status) settles the same way', () => {
  const events = [
    { type: 'workspace', v: 1, seq: 1, op: 'plan.set', mission: 'm', origin: 'model', steps: [{ id: 'p1', label: 'a' }, { id: 'p2', label: 'b' }] },
    { type: 'workspace', v: 1, seq: 2, op: 'plan.step', step_id: 'p1', status: 'done' },
  ]
  const restored = finalizeWorkspace(reduceWorkspace(events, 'x1'), 'done')
  assert.deepEqual(planProgress(restored), { done: 1, total: 2, pct: 50 })
  assert.deepEqual(planProgress(settlePlanState(restored)), { done: 2, total: 2, pct: 100 })
  const stopped = finalizeWorkspace(reduceWorkspace(events, 'x1'), 'stopped')
  assert.deepEqual(planProgress(settlePlanState(stopped)), { done: 1, total: 2, pct: 50 })
})
