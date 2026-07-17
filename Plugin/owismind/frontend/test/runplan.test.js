// Durable workflow plan + durable feed adapter (v1.3) - pure reducer tests.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createAnswerState,
  applyEvent,
  durableEventToUi,
  durableTerminalEvent,
  answerText,
} from '../src/composables/timelineModel.js'

test('plan event installs the plan and step_status ticks it', () => {
  const s = createAnswerState()
  applyEvent(s, {
    type: 'plan',
    goal: 'Compare revenue and tickets',
    steps: [
      { id: 'S1', title: 'Revenue', status: 'pending' },
      { id: 'S2', title: 'Tickets', status: 'pending' },
    ],
  })
  assert.equal(s.plan.goal, 'Compare revenue and tickets')
  assert.equal(s.plan.steps.length, 2)
  applyEvent(s, { type: 'step_status', id: 'S1', status: 'running' })
  assert.equal(s.plan.steps[0].status, 'running')
  applyEvent(s, { type: 'step_status', id: 'S1', status: 'completed' })
  applyEvent(s, { type: 'step_status', id: 'ghost', status: 'running' })
  assert.equal(s.plan.steps[0].status, 'completed')
  assert.equal(s.plan.steps[1].status, 'pending')
})

test('a replan PLAN_READY replaces the plan wholesale', () => {
  const s = createAnswerState()
  applyEvent(s, { type: 'plan', goal: 'g', steps: [{ id: 'S1', title: 'a' }] })
  applyEvent(s, {
    type: 'plan',
    goal: 'g2',
    steps: [{ id: 'S1', title: 'a', status: 'completed' }, { id: 'S2', title: 'b' }],
  })
  assert.equal(s.plan.goal, 'g2')
  assert.equal(s.plan.steps.length, 2)
  assert.equal(s.plan.steps[0].status, 'completed')
})

test('plan is bounded and malformed steps are dropped (never throws)', () => {
  const s = createAnswerState()
  const steps = Array.from({ length: 20 }, (_, i) => ({ id: 'S' + i, title: 't' }))
  steps.push(null, { title: 'no id' })
  applyEvent(s, { type: 'plan', goal: 'x'.repeat(1000), steps })
  assert.equal(s.plan.steps.length, 12)
  assert.equal(s.plan.goal.length, 300)
})

test('durableEventToUi maps the persisted feed to reducer events', () => {
  assert.deepEqual(
    durableEventToUi({ event_type: 'PLAN_READY', payload: { goal: 'g', steps: [] } })[0],
    { type: 'plan', goal: 'g', steps: [] },
  )
  const started = durableEventToUi({ event_type: 'STEP_STARTED', payload: { id: 'S1', title: 'T' } })
  assert.deepEqual(started[0], { type: 'step_status', id: 'S1', status: 'running' })
  assert.equal(started[1].type, 'agent_event')
  const done = durableEventToUi({ event_type: 'STEP_COMPLETED', payload: { id: 'S1' } })
  assert.equal(done[0].status, 'completed')
  assert.deepEqual(durableEventToUi({ event_type: 'DONE' }), [{ type: 'run_done' }])
  assert.equal(durableEventToUi({ event_type: 'ERROR', payload: { code: 'quota_blocked' } })[0].message,
    'quota_blocked')
  // persisted agent pass-through keeps the timeline alive on replay
  const agent = durableEventToUi({
    event_type: 'AGENT_CALLING_AGENT',
    payload: { eventKind: 'CALLING_AGENT', toolName: 'ask_revenue_expert' },
  })
  assert.equal(agent[0].type, 'agent_event')
  assert.equal(agent[0].eventKind, 'CALLING_AGENT')
  // unknown types are silently ignored
  assert.deepEqual(durableEventToUi({ event_type: 'SOMETHING_NEW' }), [])
  assert.deepEqual(durableEventToUi({ type: 'answer_delta' }), [])
})

test('FINAL_ANSWER chunks replay as merged answer text', () => {
  const s = createAnswerState()
  for (const evt of durableEventToUi({ event_type: 'FINAL_ANSWER', payload: { text: 'Hello ' } })) {
    applyEvent(s, evt)
  }
  for (const evt of durableEventToUi({ event_type: 'FINAL_ANSWER', payload: { text: 'world.' } })) {
    applyEvent(s, evt)
  }
  assert.equal(answerText(s), 'Hello world.')
})

test('durableTerminalEvent maps the poll envelope statuses', () => {
  assert.deepEqual(durableTerminalEvent('completed'), { type: 'run_done' })
  assert.deepEqual(durableTerminalEvent('partial'), { type: 'stopped' })
  assert.deepEqual(durableTerminalEvent('stopped'), { type: 'stopped' })
  assert.deepEqual(durableTerminalEvent('deadline_reached', 'deadline_reached'),
    { type: 'error', message: 'deadline_reached' })
  assert.equal(durableTerminalEvent('executing'), null)
})
