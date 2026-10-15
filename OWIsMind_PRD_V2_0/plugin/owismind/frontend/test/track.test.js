// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/track.test.js
// Pure usage-analytics model (services/trackModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  CATEGORY_BY_NAME,
  MAX_BATCH,
  MAX_QUEUE,
  MAX_PROPS_CHARS,
  MAX_ID_CHARS,
  MAX_ERROR_EVENTS,
  STRING_CAPS,
  isWhitelisted,
  makeEvent,
  capProps,
  pushEvent,
  drainBatch,
  createErrorLimiter,
} from '../src/services/trackModel.js'

test('caps have the contract values', () => {
  assert.equal(MAX_BATCH, 40)
  assert.equal(MAX_QUEUE, 200)
  assert.equal(MAX_PROPS_CHARS, 2000)
  assert.equal(MAX_ID_CHARS, 64)
  assert.equal(MAX_ERROR_EVENTS, 10)
})

test('whitelist: known names map to a category, unknown are rejected', () => {
  assert.equal(isWhitelisted('webapp_opened'), true)
  assert.equal(isWhitelisted('question_sent'), true)
  assert.equal(isWhitelisted('error_backend'), true)
  assert.equal(isWhitelisted('not_a_real_event'), false)
  assert.equal(isWhitelisted(''), false)
  assert.equal(isWhitelisted(undefined), false)
  // A representative sample of each category is present.
  assert.equal(CATEGORY_BY_NAME.page_viewed, 'nav')
  assert.equal(CATEGORY_BY_NAME.evidence_row_drilled, 'evidence')
  assert.equal(CATEGORY_BY_NAME.source_cell_clicked, 'source')
  assert.equal(CATEGORY_BY_NAME.feedback_submitted, 'feedback')
  assert.equal(CATEGORY_BY_NAME.benchmark_suggestion_sent, 'benchmark')
  // The first-class evidence tab-view names (split of evidence_tab_changed).
  assert.equal(CATEGORY_BY_NAME.evidence_proof_viewed, 'evidence')
  assert.equal(CATEGORY_BY_NAME.source_data_viewed, 'evidence')
  assert.equal(CATEGORY_BY_NAME.chart_viewed, 'evidence')
  assert.equal(CATEGORY_BY_NAME.table_viewed, 'evidence')
  assert.equal(CATEGORY_BY_NAME.kpi_viewed, 'evidence')
  assert.equal(CATEGORY_BY_NAME.evidence_tab_viewed, 'evidence')
})

test('makeEvent: unknown name -> null', () => {
  assert.equal(makeEvent('nope', {}, {}), null)
})

test('makeEvent: shapes a full event and mirrors ctx', () => {
  const ev = makeEvent('question_sent', { length: 3 }, {
    id: 'id-1',
    client_ts: '2026-07-02T00:00:00.000Z',
    seq: 7,
    app_session_id: 'sess-1',
    view: 'chat',
    conversation_id: 'conv-1',
    agent_key: 'owismind',
    mode: 'smart',
  })
  assert.deepEqual(ev, {
    id: 'id-1',
    name: 'question_sent',
    client_ts: '2026-07-02T00:00:00.000Z',
    seq: 7,
    app_session_id: 'sess-1',
    view: 'chat',
    conversation_id: 'conv-1',
    agent_key: 'owismind',
    mode: 'smart',
    props: { length: 3 },
  })
})

test('makeEvent: absent nullable fields collapse to null; seq defaults to 0', () => {
  const ev = makeEvent('webapp_opened', {}, { id: 'x', client_ts: 't', app_session_id: 's' })
  assert.equal(ev.view, null)
  assert.equal(ev.conversation_id, null)
  assert.equal(ev.agent_key, null)
  assert.equal(ev.mode, null)
  assert.equal(ev.seq, 0)
  // Empty-string view/conversation also collapse to null (uniform "absent").
  const ev2 = makeEvent('webapp_opened', {}, { view: '', conversation_id: '' })
  assert.equal(ev2.view, null)
  assert.equal(ev2.conversation_id, null)
})

test('makeEvent: string fields are truncated to their column widths', () => {
  const longView = 'v'.repeat(STRING_CAPS.view + 50)
  const longId = 'i'.repeat(MAX_ID_CHARS + 50)
  const ev = makeEvent('page_viewed', {}, { id: longId, view: longView })
  assert.equal(ev.view.length, STRING_CAPS.view)
  assert.equal(ev.id.length, MAX_ID_CHARS)
})

test('capProps: small object passes through unchanged', () => {
  const p = { a: 1, b: 'two' }
  assert.equal(capProps(p), p)
})

test('capProps: oversized serialized props -> {_truncated:true}', () => {
  const big = { blob: 'x'.repeat(MAX_PROPS_CHARS + 1) }
  assert.deepEqual(capProps(big), { _truncated: true })
})

test('capProps: at exactly the cap still passes', () => {
  // Build props whose JSON is exactly MAX_PROPS_CHARS chars: {"v":"..."} = 8 wrapper chars.
  const filler = 'a'.repeat(MAX_PROPS_CHARS - 8)
  const p = { v: filler }
  assert.equal(JSON.stringify(p).length, MAX_PROPS_CHARS)
  assert.equal(capProps(p), p)
})

test('capProps: non-serializable (cycle) -> {_truncated:true}', () => {
  const a = {}
  a.self = a
  assert.deepEqual(capProps(a), { _truncated: true })
})

test('capProps: non-object input -> {} (empty, not truncated)', () => {
  assert.deepEqual(capProps(null), {})
  assert.deepEqual(capProps('str'), {})
  assert.deepEqual(capProps(undefined), {})
})

test('makeEvent: oversized props become the truncation marker', () => {
  const ev = makeEvent('page_viewed', { blob: 'x'.repeat(MAX_PROPS_CHARS + 1) }, {})
  assert.deepEqual(ev.props, { _truncated: true })
})

test('pushEvent: appends and reports zero dropped under the cap', () => {
  const q = []
  assert.equal(pushEvent(q, { id: 1 }, 3), 0)
  assert.equal(pushEvent(q, { id: 2 }, 3), 0)
  assert.equal(q.length, 2)
})

test('pushEvent: drops the OLDEST past the cap', () => {
  const q = []
  for (let i = 0; i < 3; i++) pushEvent(q, { id: i }, 3)
  assert.deepEqual(q.map((e) => e.id), [0, 1, 2])
  const dropped = pushEvent(q, { id: 3 }, 3)
  assert.equal(dropped, 1)
  // Oldest (0) evicted, newest (3) kept, order preserved.
  assert.deepEqual(q.map((e) => e.id), [1, 2, 3])
  assert.equal(q.length, 3)
})

test('pushEvent: default cap is MAX_QUEUE and stays bounded', () => {
  const q = []
  for (let i = 0; i < MAX_QUEUE + 25; i++) pushEvent(q, { id: i })
  assert.equal(q.length, MAX_QUEUE)
  // The last id is the newest; the first is exactly 25 (the first 25 were evicted).
  assert.equal(q[q.length - 1].id, MAX_QUEUE + 24)
  assert.equal(q[0].id, 25)
})

test('drainBatch: removes at most maxBatch from the FRONT (FIFO)', () => {
  const q = []
  for (let i = 0; i < 5; i++) q.push({ id: i })
  const batch = drainBatch(q, 2)
  assert.deepEqual(batch.map((e) => e.id), [0, 1])
  assert.deepEqual(q.map((e) => e.id), [2, 3, 4])
})

test('drainBatch: caps a large queue at MAX_BATCH', () => {
  const q = []
  for (let i = 0; i < MAX_BATCH + 10; i++) q.push({ id: i })
  const batch = drainBatch(q)
  assert.equal(batch.length, MAX_BATCH)
  assert.equal(q.length, 10)
})

test('drainBatch: empty queue yields an empty batch', () => {
  const q = []
  assert.deepEqual(drainBatch(q, 5), [])
})

test('error limiter: allows up to MAX_ERROR_EVENTS error events, then blocks', () => {
  const lim = createErrorLimiter()
  for (let i = 0; i < MAX_ERROR_EVENTS; i++) {
    assert.equal(lim.allow('error_frontend'), true)
  }
  assert.equal(lim.allow('error_frontend'), false)
  assert.equal(lim.allow('error_backend'), false)
  assert.equal(lim.count, MAX_ERROR_EVENTS)
})

test('error limiter: counts frontend + backend together', () => {
  const lim = createErrorLimiter(3)
  assert.equal(lim.allow('error_frontend'), true)
  assert.equal(lim.allow('error_backend'), true)
  assert.equal(lim.allow('error_frontend'), true)
  assert.equal(lim.allow('error_backend'), false)
})

test('error limiter: non-error names are always allowed and never counted', () => {
  const lim = createErrorLimiter(1)
  for (let i = 0; i < 100; i++) assert.equal(lim.allow('page_viewed'), true)
  assert.equal(lim.count, 0)
  // The one error budget is still intact after all those page_viewed events.
  assert.equal(lim.allow('error_frontend'), true)
  assert.equal(lim.allow('error_frontend'), false)
})
