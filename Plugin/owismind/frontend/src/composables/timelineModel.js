// Chronological answer timeline — a PURE, framework-free reducer (no Vue import) that
// turns the backend's normalized event stream into ONE ordered, incremental list. Each
// element appears exactly where it was received and new elements are only ever appended
// below — an activity event, a chunk of intermediate agent text, a tool call, more
// text, the final answer, or an error all interleave in true arrival order. The DATA
// stays chronological; how items are grouped on screen (the collapsible activity block
// above the answer) is a display concern handled by the read-only selectors below.
//
// It is pure so it can be unit-tested with node:test, and it mutates the state object
// IN PLACE so the same calls drive a Vue reactive() proxy (fine-grained live re-render,
// memory L020) — the store owns wrapping the state in reactive().
//
// State shape (the answer "version"):
//   { timeline:[item], sql:[{sql,success,row_count}], usage, status, error,
//     showSql, exchangeId, feedbackRating, feedbackReasons, feedbackComment, _seq }
//
// Feedback fields are OUT-OF-BAND (persisted server-side per exchange, not derived
// from the event stream): `applyEvent` never touches them — the chat store / message
// component own setting them from `/conversation` rows or after a /chat/feedback call.
//
// Timeline item shapes (discriminated by `kind`), each with a stable `id` + arrival
// `seq` (sequence/order of arrival):
//   event: { id, seq, kind:'event', eventKind, toolName, blockId, elapsedSeconds, label, status:'running'|'done' }
//   text:  { id, seq, kind:'text', text, open:bool }   // open = still merging deltas
//   error: { id, seq, kind:'error', message }
//
// We deliberately do NOT put the persisted raw trace, generated SQL payloads, or any
// other technical/sensitive footer data into the timeline: SQL stays in `state.sql`
// (its own collapsible panel) and the raw trace is never sent to the front at all.

/** Build a fresh answer-version state (optionally overriding fields). */
export function createAnswerState(over) {
  return {
    timeline: [],
    sql: [],
    usage: null,
    status: 'running',
    error: '',
    showSql: false,
    exchangeId: null,
    feedbackRating: null, // 1 (up) | 0 (down) | null (none)
    feedbackReasons: [], // reason codes (down)
    feedbackComment: '', // free-text (down)
    _seq: 0,
    ...(over || {}),
  }
}

function nextSeq(state) {
  state._seq = (state._seq || 0) + 1
  return state._seq
}

function lastItem(state) {
  const tl = state.timeline
  return tl.length ? tl[tl.length - 1] : null
}

// Mark every still-"running" event as done. Only the most-recently-received event is
// ever shown as running; as soon as anything follows it (another event or some text),
// it is finalized. Called on every new item and on terminal events.
function sealEvents(state) {
  for (const it of state.timeline) {
    if (it.kind === 'event' && it.status === 'running') it.status = 'done'
  }
}

// Close the current text block so a later delta starts a NEW block instead of extending
// a paragraph that an event has already interrupted.
function closeText(state) {
  const last = lastItem(state)
  if (last && last.kind === 'text') last.open = false
}

function hasStreamedText(state) {
  return state.timeline.some((it) => it.kind === 'text' && (it.text || '').length > 0)
}

function pushEvent(state, evt) {
  sealEvents(state)
  closeText(state)
  // Backend-provided human label (orchestrator whitelist pass-through): copied
  // only when it is a NON-EMPTY string, capped at 300 chars (mirrors the
  // streaming.py cap). Display-only — it never feeds ids, seq or
  // timelineSignature, so the chat auto-scroll gating (F8/F13) is untouched.
  const label = typeof evt.label === 'string' && evt.label ? evt.label.slice(0, 300) : null
  state.timeline.push({
    id: 'ev-' + nextSeq(state),
    seq: state._seq,
    kind: 'event',
    eventKind: evt.eventKind || null,
    toolName: evt.toolName || null,
    blockId: evt.blockId || null,
    elapsedSeconds: evt.elapsedSeconds,
    label,
    status: 'running',
  })
}

function appendText(state, delta) {
  if (!delta) return
  // Text following an event finalizes that event (it was the work that produced it).
  sealEvents(state)
  const last = lastItem(state)
  if (last && last.kind === 'text' && last.open) {
    // Merge consecutive deltas of the same block into one text element (no duplicates,
    // no fragmentation): mutate THROUGH the array element so a reactive proxy updates.
    last.text += delta
  } else {
    state.timeline.push({
      id: 'txt-' + nextSeq(state),
      seq: state._seq,
      kind: 'text',
      text: delta,
      open: true,
    })
  }
}

function pushFinalAnswer(state, finalText) {
  sealEvents(state)
  // Never duplicate already-streamed text: if deltas built any text block, the answer is
  // already on screen and final_answer just confirms it. Only materialize the final text
  // when nothing streamed — i.e. structured agents that emit the whole answer at the end
  // (memory L019). The block is closed (no further deltas expected).
  if (hasStreamedText(state)) {
    closeText(state)
    return
  }
  if (finalText) {
    state.timeline.push({
      id: 'txt-' + nextSeq(state),
      seq: state._seq,
      kind: 'text',
      text: finalText,
      open: false,
    })
  }
}

function pushError(state, message) {
  sealEvents(state)
  closeText(state)
  state.timeline.push({
    id: 'err-' + nextSeq(state),
    seq: state._seq,
    kind: 'error',
    message: message || 'inconnue',
  })
}

// A live "what I'm doing now" narration message (transient — backend never
// persists it as the answer, so it only ever appears during a live run). It
// interleaves in arrival order like text, but is rendered as a muted status
// line and is NEVER part of answerText (copy) or the stored answer.
function pushNarration(state, text) {
  if (!text) return
  sealEvents(state)
  closeText(state)
  state.timeline.push({
    id: 'narr-' + nextSeq(state),
    seq: state._seq,
    kind: 'narration',
    text,
  })
}

/**
 * Apply ONE normalized backend event to the answer state, in place.
 *
 * Handles every event the backend emits (run_started / agent_event / answer_delta /
 * generated_sql / usage_summary / final_answer / run_done / error) and SILENTLY IGNORES
 * any unknown event type so a new/unexpected event can never break the UI. Returns the
 * same state for chaining/testing.
 */
export function applyEvent(state, evt) {
  switch (evt && evt.type) {
    case 'run_started':
      state.status = 'running'
      if (evt.exchangeId != null) state.exchangeId = evt.exchangeId
      break
    case 'agent_event':
      pushEvent(state, evt)
      break
    case 'answer_delta':
      appendText(state, evt.text || '')
      break
    case 'narration':
      // Live progress message (transient): shown in the flow, never persisted.
      pushNarration(state, evt.text || '')
      break
    case 'generated_sql':
      // Evidence, not trace: kept out of the timeline, shown in its own SQL panel.
      state.sql.push({ sql: evt.sql, success: evt.success, row_count: evt.rowCount })
      break
    case 'usage_summary':
      state.usage = {
        promptTokens: evt.promptTokens,
        completionTokens: evt.completionTokens,
        totalTokens: evt.totalTokens,
        estimatedCost: evt.estimatedCost,
      }
      break
    case 'final_answer':
      pushFinalAnswer(state, evt.text || '')
      break
    case 'run_done':
      sealEvents(state)
      closeText(state)
      if (state.status === 'running') state.status = 'done'
      break
    case 'stopped':
      // User-requested early stop (cooperative). The partial answer was already
      // materialized by the preceding final_answer; this only marks the version as
      // interrupted — NOT an error (no error item, no red toast). Like run_done, it
      // only flips a still-running version, so a late/duplicate stop is a no-op.
      sealEvents(state)
      closeText(state)
      if (state.status === 'running') state.status = 'stopped'
      break
    case 'error':
      state.status = 'error'
      state.error = evt.message || 'inconnue'
      pushError(state, state.error)
      break
    default:
      // Unknown / unhandled event type — ignore, never throw.
      break
  }
  return state
}

/**
 * Build the `usage` object for a RELOADED exchange from its persisted /conversation
 * row (the live path fills `usage` from the usage_summary event instead). Returns null
 * when no usage was stored at all (an early-stopped run, or a pre-usage-feature row) so
 * the message component shows no usage line rather than an empty/zero one. A partially
 * stored row (some columns null) keeps the present values and nulls the rest.
 */
export function usageFromRow(row) {
  if (!row) return null
  const has = (v) => v != null
  if (
    !has(row.input_tokens) &&
    !has(row.output_tokens) &&
    !has(row.total_tokens) &&
    !has(row.estimated_cost)
  ) {
    return null
  }
  return {
    promptTokens: has(row.input_tokens) ? row.input_tokens : null,
    completionTokens: has(row.output_tokens) ? row.output_tokens : null,
    totalTokens: has(row.total_tokens) ? row.total_tokens : null,
    estimatedCost: has(row.estimated_cost) ? row.estimated_cost : null,
  }
}

/** The full answer text = concatenation of the timeline's text blocks (for copy). */
export function answerText(state) {
  if (!state || !state.timeline) return ''
  return state.timeline
    .filter((it) => it.kind === 'text')
    .map((it) => it.text || '')
    .join('')
}

/** Cheap change signature for the streaming version (drives auto-scroll re-checks). */
export function timelineSignature(state) {
  if (!state || !state.timeline) return '0'
  let textLen = 0
  for (const it of state.timeline) if (it.kind === 'text') textLen += (it.text || '').length
  return state.timeline.length + '|' + textLen + '|' + state.status
}

// --- Activity-block selectors (display grouping, NOT a timeline mutation) -------------
// The message component renders the agent's activity (event items) as ONE grouped,
// collapsible block above the answer, ChatGPT-style. These selectors only READ the
// timeline — items keep their stable ids, so v-for keys and timelineSignature (and
// therefore the ChatThread scroll gating, F13) are unaffected.

/** The activity events (reasoning/tool steps) in arrival order. */
export function timelineEvents(state) {
  if (!state || !state.timeline) return []
  return state.timeline.filter((it) => it.kind === 'event')
}

/** The non-event items (text blocks + errors) in arrival order — the rendered answer. */
export function timelineBodyItems(state) {
  if (!state || !state.timeline) return []
  return state.timeline.filter((it) => it.kind !== 'event')
}

/**
 * The timeline as chronological SEGMENTS for the LIVE view: consecutive events are
 * grouped ({ kind:'events', key, items }) and text/error items stay in place
 * ({ kind:'text'|'error', key, item }). This preserves the real interleave — an
 * orchestrator that answers mid-run shows its partial answer BETWEEN two event
 * phases, with the next phase ticking below it. Keys are derived from the stable
 * item ids, so v-for/TransitionGroup diffing never remounts existing rows.
 */
export function timelineSegments(state) {
  if (!state || !state.timeline) return []
  const segments = []
  for (const it of state.timeline) {
    if (it.kind === 'event') {
      const last = segments[segments.length - 1]
      if (last && last.kind === 'events') last.items.push(it)
      else segments.push({ kind: 'events', key: 'seg-' + it.id, items: [it] })
    } else {
      segments.push({ kind: it.kind, key: it.id, item: it })
    }
  }
  return segments
}

/**
 * Duration of the event at `idx` derived from the backend stamps: the gap between
 * its elapsed-since-run-start stamp and the NEXT event's. Null when either stamp
 * is missing, the gap is negative, or the event is the last one (no successor to
 * bound it). Used for steps that arrive ALREADY SEALED inside one poll batch —
 * the client clock never saw them running, but the emission stamps still carry
 * their true duration.
 */
export function stepStampDiff(events, idx) {
  if (!Array.isArray(events) || idx < 0) return null
  const cur = events[idx]
  const next = events[idx + 1]
  if (!cur || !next) return null
  if (cur.elapsedSeconds == null || next.elapsedSeconds == null) return null
  const d = next.elapsedSeconds - cur.elapsedSeconds
  return d >= 0 ? d : null
}

/**
 * One-line summary of the activity block (collapsed header): step count + total
 * duration. `elapsedSeconds` is stamped by the backend as elapsed-since-run-start
 * (streaming.py), so the total is the MAX across events — robust to out-of-order
 * or missing stamps, never a sum of cumulative values.
 */
export function activitySummary(state) {
  const events = timelineEvents(state)
  let seconds = null
  for (const it of events) {
    if (it.elapsedSeconds != null && (seconds == null || it.elapsedSeconds > seconds)) {
      seconds = it.elapsedSeconds
    }
  }
  return { count: events.length, seconds }
}
