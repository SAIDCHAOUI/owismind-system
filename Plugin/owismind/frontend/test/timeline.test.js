// Unit tests for the pure chronological timeline reducer (composables/timelineModel.js).
// Runnable with the built-in test runner (NO install): from frontend/ run
//   node --test test/
// These live OUTSIDE src/, so they are never bundled by Vite nor packaged into the zip.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createAnswerState,
  applyEvent,
  answerText,
  timelineSignature,
  timelineEvents,
  timelineBodyItems,
  timelineSegments,
  activitySummary,
  stepStampDiff,
  usageFromRow,
} from '../src/composables/timelineModel.js'
import { resolveTimelineStep, timelineMessages } from '../src/registries/timelineSteps.js'

function feed(events) {
  const s = createAnswerState()
  for (const e of events) applyEvent(s, e)
  return s
}
const kinds = (s) => s.timeline.map((i) => i.kind)
const texts = (s) => s.timeline.filter((i) => i.kind === 'text').map((i) => i.text)

// #4 — chronological alternation: event → text → event → text (the headline fix).
test('chronological alternation: event → text → event → text', () => {
  const s = feed([
    { type: 'run_started', exchangeId: 'x1' },
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'agent_event', eventKind: 'AGENT_TOOL_START', toolName: 'resolve' },
    { type: 'answer_delta', text: "I'll help you find the revenue..." },
    { type: 'agent_event', eventKind: 'AGENT_TOOL_START', toolName: 'revenue' },
    { type: 'answer_delta', text: "Here's the revenue breakdown..." },
  ])
  assert.deepEqual(kinds(s), ['event', 'event', 'text', 'event', 'text'])
  // Each text block stays exactly where it was received (not moved under the trace).
  assert.deepEqual(texts(s), [
    "I'll help you find the revenue...",
    "Here's the revenue breakdown...",
  ])
  assert.equal(s.exchangeId, 'x1')
  // Earlier events are sealed 'done' once later content arrives; the rest is consistent.
  assert.equal(s.timeline[0].status, 'done')
  assert.equal(s.timeline[1].status, 'done')
  assert.equal(s.timeline[3].status, 'done')
})

// #5 — successive text chunks merge into ONE block (no duplication, no fragmentation).
test('successive text chunks merge into one block', () => {
  const s = feed([
    { type: 'answer_delta', text: 'Hello ' },
    { type: 'answer_delta', text: 'world' },
    { type: 'answer_delta', text: '!' },
  ])
  assert.deepEqual(kinds(s), ['text'])
  assert.equal(s.timeline[0].text, 'Hello world!')
  assert.equal(answerText(s), 'Hello world!')
})

// #6 — final answer after streamed text must NOT be duplicated.
test('final answer after streamed text is not duplicated', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'answer_delta', text: 'Streamed answer.' },
    { type: 'final_answer', text: 'Streamed answer.' },
    { type: 'run_done' },
  ])
  assert.equal(texts(s).length, 1)
  assert.equal(answerText(s), 'Streamed answer.')
  assert.equal(s.status, 'done')
})

// Structured agents (memory L019): the whole answer arrives ONLY in final_answer.
test('structured agent: final answer with no prior deltas is shown once', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'agent_event', eventKind: 'AGENT_TOOL_START', toolName: 'revenue' },
    { type: 'final_answer', text: 'Whole answer at the end.' },
    { type: 'run_done' },
  ])
  assert.deepEqual(kinds(s), ['event', 'event', 'text'])
  assert.equal(answerText(s), 'Whole answer at the end.')
})

// #7 (partial) — error is appended in place, status flips, partial text is preserved.
test('error after partial text: appended in place, partial kept', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'answer_delta', text: 'partial' },
    { type: 'error', message: 'agent_unavailable' },
  ])
  assert.equal(s.status, 'error')
  assert.equal(s.error, 'agent_unavailable')
  assert.equal(s.timeline[s.timeline.length - 1].kind, 'error')
  assert.equal(answerText(s), 'partial') // partial answer not lost
})

// User stop: a `stopped` terminal event flips status to 'stopped' and KEEPS the partial
// (the worker emits final_answer with the partial, then stopped). Not treated as an error.
test('user stop after partial text: status stopped, partial kept once', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'answer_delta', text: 'partial answer' },
    { type: 'final_answer', text: 'partial answer' },
    { type: 'stopped', exchangeId: 'x9' },
  ])
  assert.equal(s.status, 'stopped')
  assert.equal(answerText(s), 'partial answer')
  assert.equal(texts(s).length, 1) // not duplicated
})

// User stop BEFORE any text (only event-kind steps streamed): status stopped, no text
// block (the component renders an "interrupted" placeholder for an empty terminal answer).
test('user stop before any text: status stopped, no text block', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'agent_event', eventKind: 'AGENT_TOOL_START', toolName: 'revenue' },
    { type: 'final_answer', text: '' },
    { type: 'stopped', exchangeId: 'x9' },
  ])
  assert.equal(s.status, 'stopped')
  assert.equal(answerText(s), '')
  assert.equal(texts(s).length, 0)
})

// The "Stopping…" flag is set by the store on the live version and MUST be cleared by
// any terminal event (so the spinner/blink never lingers once the run actually ends).
test('stopping flag is cleared on the terminal event', () => {
  const s = createAnswerState()
  applyEvent(s, { type: 'answer_delta', text: 'partial' })
  s.stopping = true // store sets this when the user presses ■ (cooperative backend stop)
  applyEvent(s, { type: 'stopped', exchangeId: 'x9' })
  assert.equal(s.status, 'stopped')
  assert.equal(s.stopping, false)
})

test('stopping flag is cleared on run_done and on error too', () => {
  const done = createAnswerState()
  done.stopping = true
  applyEvent(done, { type: 'run_done' })
  assert.equal(done.stopping, false)
  const err = createAnswerState()
  err.stopping = true
  applyEvent(err, { type: 'error', message: 'boom' })
  assert.equal(err.stopping, false)
})

// A late `stopped` never overrides an already-terminal status (mirrors run_done's guard).
test('stopped does not override a prior terminal status', () => {
  const s = feed([
    { type: 'answer_delta', text: 'x' },
    { type: 'run_done' },
    { type: 'stopped' },
  ])
  assert.equal(s.status, 'done')
})

test('unknown / malformed event types are ignored (UI never breaks)', () => {
  const s = feed([
    { type: 'totally_unknown', foo: 1 },
    { type: 'answer_delta', text: 'ok' },
    {},
    null,
  ])
  assert.deepEqual(kinds(s), ['text'])
  assert.equal(answerText(s), 'ok')
})

test('generated_sql goes to the SQL panel, never the timeline', () => {
  const s = feed([
    { type: 'answer_delta', text: 'a' },
    { type: 'generated_sql', sql: 'SELECT 1', success: true, rowCount: 1 },
  ])
  assert.deepEqual(kinds(s), ['text'])
  assert.equal(s.sql.length, 1)
  assert.equal(s.sql[0].sql, 'SELECT 1')
  assert.equal(s.sql[0].row_count, 1)
})

test('usage_summary is captured without touching the timeline', () => {
  const s = feed([
    { type: 'answer_delta', text: 'a' },
    { type: 'usage_summary', promptTokens: 5, completionTokens: 7, totalTokens: 12, estimatedCost: 0.001 },
  ])
  assert.deepEqual(kinds(s), ['text'])
  assert.equal(s.usage.totalTokens, 12)
})

test('items have unique ids and strictly increasing seq', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A' },
    { type: 'answer_delta', text: 'x' },
    { type: 'agent_event', eventKind: 'B' },
  ])
  const ids = s.timeline.map((i) => i.id)
  assert.equal(new Set(ids).size, ids.length)
  for (let i = 1; i < s.timeline.length; i++) {
    assert.ok(s.timeline[i].seq > s.timeline[i - 1].seq)
  }
})

test('createAnswerState carries feedback defaults and accepts overrides', () => {
  const s = createAnswerState()
  assert.equal(s.feedbackRating, null)
  assert.deepEqual(s.feedbackReasons, [])
  assert.equal(s.feedbackComment, '')
  const o = createAnswerState({ exchangeId: 'e1', feedbackRating: 0, feedbackReasons: ['incorrect'], feedbackComment: 'x' })
  assert.equal(o.exchangeId, 'e1')
  assert.equal(o.feedbackRating, 0)
  assert.deepEqual(o.feedbackReasons, ['incorrect'])
  assert.equal(o.feedbackComment, 'x')
})

test('timelineSignature changes as text grows (drives auto-scroll re-check)', () => {
  const s = createAnswerState()
  const a = timelineSignature(s)
  applyEvent(s, { type: 'answer_delta', text: 'hi' })
  const b = timelineSignature(s)
  applyEvent(s, { type: 'answer_delta', text: ' there' })
  const c = timelineSignature(s)
  assert.notEqual(a, b)
  assert.notEqual(b, c)
})

// --- Activity-block selectors (grouped steps above the answer, UI/UX session) -------

test('timelineEvents / timelineBodyItems split the timeline without reordering', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'AGENT_TURN_START' },
    { type: 'answer_delta', text: 'partial' },
    { type: 'agent_event', eventKind: 'AGENT_TOOL_START', toolName: 'sql' },
    { type: 'answer_delta', text: ' answer' },
    { type: 'error', message: 'boom' },
  ])
  const events = timelineEvents(s)
  const body = timelineBodyItems(s)
  assert.deepEqual(events.map((i) => i.kind), ['event', 'event'])
  assert.deepEqual(body.map((i) => i.kind), ['text', 'text', 'error'])
  // Selectors only READ: ids are the original items', order is arrival order.
  for (let i = 1; i < events.length; i++) assert.ok(events[i].seq > events[i - 1].seq)
  for (let i = 1; i < body.length; i++) assert.ok(body[i].seq > body[i - 1].seq)
  assert.equal(events.length + body.length, s.timeline.length)
})

test('timelineBodyItems whitelists text/error and drops transient narration', () => {
  const s = feed([
    { type: 'narration', text: 'Consulting the revenue expert…' },
    { type: 'answer_delta', text: 'Here is the analysis.' },
    { type: 'narration', text: 'Writing the answer…' },
  ])
  const body = timelineBodyItems(s)
  // Narration is live-only: it must never surface as a persisted body item.
  assert.deepEqual(body.map((i) => i.kind), ['text'])
  assert.equal(body[0].text, 'Here is the analysis.')
})

test('selectors tolerate a null/empty state', () => {
  assert.deepEqual(timelineEvents(null), [])
  assert.deepEqual(timelineBodyItems(undefined), [])
  assert.deepEqual(activitySummary(null), { count: 0, seconds: null })
})

test('activitySummary: count + MAX elapsedSeconds (elapsed-since-start stamps)', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A', elapsedSeconds: 0.4 },
    { type: 'agent_event', eventKind: 'B', elapsedSeconds: 3.2 },
    { type: 'agent_event', eventKind: 'C' }, // missing stamp ignored
    { type: 'agent_event', eventKind: 'D', elapsedSeconds: 1.1 }, // out-of-order safe
  ])
  assert.deepEqual(activitySummary(s), { count: 4, seconds: 3.2 })
})

test('activitySummary with no events: zero count, null seconds', () => {
  const s = feed([{ type: 'answer_delta', text: 'only text' }])
  assert.deepEqual(activitySummary(s), { count: 0, seconds: null })
})

// --- timelineSegments (live interleaved view: event phases + in-place answers) ------

test('timelineSegments groups consecutive events and keeps text in place', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A' },
    { type: 'agent_event', eventKind: 'B' },
    { type: 'answer_delta', text: 'first partial answer' },
    { type: 'agent_event', eventKind: 'C' },
    { type: 'answer_delta', text: 'final answer' },
    { type: 'error', message: 'boom' },
  ])
  const segs = timelineSegments(s)
  assert.deepEqual(segs.map((g) => g.kind), ['events', 'text', 'events', 'text', 'error'])
  assert.equal(segs[0].items.length, 2)
  assert.equal(segs[2].items.length, 1)
  assert.equal(segs[1].item.text, 'first partial answer')
  assert.equal(segs[4].item.message, 'boom')
})

test('timelineSegments keys are stable across incremental feeds (no remounts)', () => {
  const s = createAnswerState()
  applyEvent(s, { type: 'agent_event', eventKind: 'A' })
  const k1 = timelineSegments(s).map((g) => g.key)
  applyEvent(s, { type: 'agent_event', eventKind: 'B' })
  applyEvent(s, { type: 'answer_delta', text: 'x' })
  applyEvent(s, { type: 'agent_event', eventKind: 'C' })
  const k2 = timelineSegments(s).map((g) => g.key)
  // The first segment keeps its key (derived from its FIRST item) as it grows,
  // and a later phase gets a distinct key.
  assert.equal(k2[0], k1[0])
  assert.equal(new Set(k2).size, k2.length)
})

test('timelineSegments tolerates null state and splits around interleaved text', () => {
  assert.deepEqual(timelineSegments(null), [])
  const s = feed([
    { type: 'answer_delta', text: 'text first' },
    { type: 'agent_event', eventKind: 'A' },
  ])
  const segs = timelineSegments(s)
  assert.deepEqual(segs.map((g) => g.kind), ['text', 'events'])
})

// --- stepStampDiff (per-step duration from elapsed-since-start backend stamps) ------

test('stepStampDiff: gap to the next stamped event', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A', elapsedSeconds: 0.5 },
    { type: 'agent_event', eventKind: 'B', elapsedSeconds: 2.75 },
    { type: 'agent_event', eventKind: 'C', elapsedSeconds: 3.0 },
  ])
  const events = timelineEvents(s)
  assert.equal(stepStampDiff(events, 0), 2.25)
  assert.equal(stepStampDiff(events, 1), 0.25)
  // Last event has no successor -> unknown.
  assert.equal(stepStampDiff(events, 2), null)
})

test('stepStampDiff: null on missing stamps, negative gaps and bad input', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A' }, // no stamp
    { type: 'agent_event', eventKind: 'B', elapsedSeconds: 5 },
    { type: 'agent_event', eventKind: 'C', elapsedSeconds: 1 }, // out of order
    { type: 'agent_event', eventKind: 'D', elapsedSeconds: 2 },
  ])
  const events = timelineEvents(s)
  assert.equal(stepStampDiff(events, 0), null) // cur unstamped
  assert.equal(stepStampDiff(events, 1), null) // negative gap
  assert.equal(stepStampDiff(events, 2), 1)
  assert.equal(stepStampDiff(events, -1), null)
  assert.equal(stepStampDiff(null, 0), null)
})

// --- agent_event label pass-through (trust layer v2, spec §5) ------------------------

test('agent_event copies a non-empty string label onto the pushed item', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'CALLING_AGENT', label: 'Interrogation des revenus' },
    { type: 'agent_event', eventKind: 'AGENT_DONE' }, // no label → null
  ])
  assert.equal(s.timeline[0].label, 'Interrogation des revenus')
  assert.equal(s.timeline[1].label, null)
})

test('agent_event label: non-string or empty values stay null', () => {
  const s = feed([
    { type: 'agent_event', eventKind: 'A', label: '' },
    { type: 'agent_event', eventKind: 'B', label: 42 },
    { type: 'agent_event', eventKind: 'C', label: { nope: true } },
  ])
  for (const it of s.timeline) assert.equal(it.label, null)
})

test('agent_event label is capped at 300 chars (streaming.py mirror)', () => {
  const s = feed([{ type: 'agent_event', eventKind: 'A', label: 'x'.repeat(500) }])
  assert.equal(s.timeline[0].label.length, 300)
})

// F8 invariant: the label is display-only — ids, seq and the signature that gates the
// chat auto-scroll must be byte-identical with or without labels.
test('timelineSignature and ids are identical with and without labels (F8)', () => {
  const mk = (label) =>
    feed([
      { type: 'agent_event', eventKind: 'CALLING_AGENT', ...(label ? { label } : {}) },
      { type: 'answer_delta', text: 'hello' },
      { type: 'run_done' },
    ])
  const withLabel = mk('Interroger les revenus')
  const without = mk(null)
  assert.equal(timelineSignature(withLabel), timelineSignature(without))
  assert.deepEqual(
    withLabel.timeline.map((i) => [i.id, i.seq]),
    without.timeline.map((i) => [i.id, i.seq]),
  )
})

// --- resolveTimelineStep (backend label preference + orchestrator kinds) -------------

test('resolveTimelineStep prefers the backend label over the registry', () => {
  const r = resolveTimelineStep('CALLING_AGENT', "Interroger l'agent revenus")
  assert.deepEqual(r, { key: '', fallback: "Interroger l'agent revenus", icon: 'route' })
  // An unknown kind with a label still renders the label, with the generic icon.
  const u = resolveTimelineStep('SOME_NEW_KIND', 'Étape inédite')
  assert.deepEqual(u, { key: '', fallback: 'Étape inédite', icon: 'route' })
})

test('resolveTimelineStep keeps the known kind icon when a label is provided', () => {
  assert.equal(resolveTimelineStep('AGENT_DONE', 'Agent revenus terminé').icon, 'check')
  assert.equal(resolveTimelineStep('WRITING_ANSWER', 'Rédaction…').icon, 'sparkle')
})

test('resolveTimelineStep without label: orchestrator kinds resolve to cataloged keys', () => {
  const kinds = [
    'START', 'PLANNING', 'PLAN_READY', 'DIRECT_ANSWER', 'CALLING_AGENT',
    'AGENT_DONE', 'RUNNING_TOOL', 'TOOL_DONE', 'WRITING_ANSWER', 'DONE',
  ]
  for (const k of kinds) {
    const r = resolveTimelineStep(k)
    assert.ok(r.key, k + ' must resolve to an i18n key')
    // Every key must exist in BOTH locale catalogs (merged into vue-i18n at setup).
    assert.equal(typeof timelineMessages.fr[r.key], 'string', 'fr missing ' + r.key)
    assert.equal(typeof timelineMessages.en[r.key], 'string', 'en missing ' + r.key)
  }
})

test('resolveTimelineStep with an empty/non-string label falls back to the registry', () => {
  assert.equal(resolveTimelineStep('AGENT_DONE', '').key, 'tl.kind.agent_done')
  assert.equal(resolveTimelineStep('AGENT_DONE', undefined).key, 'tl.kind.agent_done')
  // Pre-existing kinds are untouched by the new optional parameter.
  assert.equal(resolveTimelineStep('AGENT_TOOL_START').key, 'tl.kind.tool_start')
})

test('humanize strips SUB_AGENT_AGENT_ then SUB_AGENT_ prefixes', () => {
  assert.equal(resolveTimelineStep('SUB_AGENT_AGENT_TOOL_START').fallback, 'Tool start')
  assert.equal(resolveTimelineStep('SUB_AGENT_THINKING').fallback, 'Thinking')
})

// --- Usage: live path (usage_summary event) + reload path (usageFromRow) --------------

test('usage_summary event populates state.usage (live path)', () => {
  const s = feed([
    { type: 'usage_summary', promptTokens: 1662, completionTokens: 806, totalTokens: 2468, estimatedCost: 0.0101375 },
  ])
  assert.deepEqual(s.usage, {
    promptTokens: 1662,
    completionTokens: 806,
    totalTokens: 2468,
    estimatedCost: 0.0101375,
  })
})

test('usageFromRow maps the persisted columns (reload path)', () => {
  assert.deepEqual(
    usageFromRow({
      input_tokens: 3383,
      output_tokens: 3127,
      total_tokens: 6510,
      estimated_cost: 0.0354988,
    }),
    { promptTokens: 3383, completionTokens: 3127, totalTokens: 6510, estimatedCost: 0.0354988 },
  )
})

test('usageFromRow returns null when no usage was stored (early-stopped / legacy row)', () => {
  assert.equal(usageFromRow({ input_tokens: null, output_tokens: null, total_tokens: null, estimated_cost: null }), null)
  assert.equal(usageFromRow({}), null)
  assert.equal(usageFromRow(null), null)
})

test('usageFromRow keeps present values and nulls the missing ones (partial row)', () => {
  assert.deepEqual(usageFromRow({ input_tokens: 100, estimated_cost: 0.002 }), {
    promptTokens: 100,
    completionTokens: null,
    totalTokens: null,
    estimatedCost: 0.002,
  })
})

test('usageFromRow surfaces a stored zero (a real run, not "no usage")', () => {
  // 0 is a legitimate stored value (e.g. cached completion): it must NOT be dropped.
  assert.deepEqual(usageFromRow({ input_tokens: 0, output_tokens: 0, total_tokens: 0, estimated_cost: 0 }), {
    promptTokens: 0,
    completionTokens: 0,
    totalTokens: 0,
    estimatedCost: 0,
  })
})

test('narration: live transient messages appear in the flow but never in answerText', () => {
  const s = feed([
    { type: 'run_started', exchangeId: 7 },
    { type: 'agent_event', eventKind: 'CALLING_AGENT', label: 'Calling X' },
    { type: 'narration', text: 'Je consulte l’expert revenus : YTD EVPL…' },
    { type: 'answer_delta', text: 'EVPL a généré 1,2 M€.' },
    { type: 'run_done' },
  ])
  const narrs = s.timeline.filter((it) => it.kind === 'narration')
  assert.equal(narrs.length, 1)
  assert.match(narrs[0].text, /EVPL/)
  // Narration is transient: NOT part of the copied/stored answer.
  assert.equal(answerText(s), 'EVPL a généré 1,2 M€.')
  // It is NOT rendered as a live segment (it duplicated the step labels and broke
  // the bounded window); only events + text/error reach the live flow.
  const segKinds = timelineSegments(s).map((x) => x.kind)
  assert.ok(!segKinds.includes('narration'))
  assert.deepEqual(segKinds, ['events', 'text'])
})

test('narration: empty text is ignored (no empty bubble)', () => {
  const s = feed([{ type: 'narration', text: '' }])
  assert.equal(s.timeline.filter((it) => it.kind === 'narration').length, 0)
})
