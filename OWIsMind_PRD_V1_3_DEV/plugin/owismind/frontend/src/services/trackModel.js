// Usage-analytics model - the PURE logic behind the lightweight product-usage
// tracker (services/track.js does the browser wiring). No window / navigator / DOM
// access here so the whole thing stays unit-testable under node:test.
//
// This mirrors the SERVER-side caps and whitelist exactly (the backend is
// authoritative and re-enforces everything): the client only trims early so a
// best-effort payload never carries junk. Tracking is best-effort: nothing in this
// module throws for a caller (bad input yields a clamped value or a dropped event).

// Whitelisted event name -> category. The server drops any name not in this map, so
// the two lists MUST stay identical. Adding an event = one entry here + one entry on
// the backend whitelist.
export const CATEGORY_BY_NAME = {
  // nav
  webapp_opened: 'nav',
  page_viewed: 'nav',
  // chat
  conversation_created: 'chat',
  conversation_opened: 'chat',
  question_sent: 'chat',
  answer_received: 'chat',
  answer_stopped: 'chat',
  question_edited: 'chat',
  answer_regenerated: 'chat',
  answer_version_switched: 'chat',
  cell_value_added_to_prompt: 'chat',
  cell_value_removed_from_prompt: 'chat',
  screen_context_offered: 'chat',
  screen_context_included: 'chat',
  screen_context_dismissed: 'chat',
  // ui
  mode_changed: 'ui',
  agent_changed: 'ui',
  theme_changed: 'ui',
  sidebar_toggled: 'ui',
  // evidence
  evidence_panel_opened: 'evidence',
  evidence_panel_closed: 'evidence',
  evidence_filter_added: 'evidence',
  evidence_filter_removed: 'evidence',
  evidence_row_drilled: 'evidence',
  evidence_searched: 'evidence',
  // evidence tab views (one first-class name per tab, so dashboards read feature
  // usage directly; evidence_tab_viewed is the fallback for future tabs)
  evidence_proof_viewed: 'evidence',
  source_data_viewed: 'evidence',
  chart_viewed: 'evidence',
  table_viewed: 'evidence',
  kpi_viewed: 'evidence',
  evidence_tab_viewed: 'evidence',
  // source
  source_explorer_opened: 'source',
  source_dataset_switched: 'source',
  source_filter_added: 'source',
  source_filter_removed: 'source',
  source_searched: 'source',
  source_cell_clicked: 'source',
  // feedback
  feedback_submitted: 'feedback',
  // benchmark
  benchmark_suggestion_sent: 'benchmark',
  // error
  error_frontend: 'error',
  error_backend: 'error',
}

// Caps (client mirror of the server's). The batch/queue/props limits are load-bearing
// for the wiring in track.js; the string widths just keep a stray long field from
// bloating a beacon before the server truncates it to its column widths.
export const MAX_BATCH = 40 // events per POST /track batch (server drops the excess)
export const MAX_QUEUE = 200 // in-memory queue cap (oldest dropped past this)
export const MAX_PROPS_CHARS = 2000 // JSON-serialized props ceiling before {_truncated:true}
export const MAX_ID_CHARS = 64 // event id ceiling
export const MAX_ERROR_EVENTS = 10 // error_frontend/error_backend cap per app session

// Per-field string widths (mirror of the server columns). Applied defensively so a
// pathological value never travels; the server remains authoritative.
export const STRING_CAPS = {
  name: 64,
  client_ts: 40,
  app_session_id: 64,
  view: 64,
  conversation_id: 128,
  agent_key: 128,
  mode: 16,
}

// True when `name` is a whitelisted event (unknown names are dropped, never sent).
export function isWhitelisted(name) {
  return Object.prototype.hasOwnProperty.call(CATEGORY_BY_NAME, name)
}

// Truncate a value to a string of at most `max` chars. Non-strings are coerced with
// String(); null/undefined -> '' (so a required field is never `null` on the wire).
function capString(value, max) {
  const s = value == null ? '' : String(value)
  return s.length > max ? s.slice(0, max) : s
}

// A field that is legitimately absent -> null; otherwise a capped string. Empty string
// also collapses to null so "no view / no conversation" is uniform on the wire.
function nullableString(value, max) {
  if (value == null) return null
  const s = String(value)
  if (!s) return null
  return s.length > max ? s.slice(0, max) : s
}

// Clamp props to the serialized ceiling. A props object whose JSON is over
// MAX_PROPS_CHARS (or that cannot be serialized at all, e.g. a cycle) is replaced by
// the marker {_truncated:true} rather than dropped, so the event still counts.
export function capProps(props) {
  const p = props && typeof props === 'object' ? props : {}
  let serialized
  try {
    serialized = JSON.stringify(p)
  } catch (e) {
    return { _truncated: true }
  }
  if (serialized == null || serialized.length > MAX_PROPS_CHARS) return { _truncated: true }
  return p
}

// Shape one client event from a name + props + a context bag. Returns null when the
// name is not whitelisted (the caller drops it). `ctx` supplies the id / client_ts /
// seq / app_session_id (minted by the wiring) plus the ambient view / conversation /
// agent / mode. Every string field is capped; props are clamped by capProps.
export function makeEvent(name, props, ctx) {
  if (!isWhitelisted(name)) return null
  const c = ctx || {}
  return {
    id: capString(c.id, MAX_ID_CHARS),
    name: capString(name, STRING_CAPS.name),
    client_ts: capString(c.client_ts, STRING_CAPS.client_ts),
    seq: Number.isFinite(c.seq) ? c.seq : 0,
    app_session_id: capString(c.app_session_id, STRING_CAPS.app_session_id),
    view: nullableString(c.view, STRING_CAPS.view),
    conversation_id: nullableString(c.conversation_id, STRING_CAPS.conversation_id),
    agent_key: nullableString(c.agent_key, STRING_CAPS.agent_key),
    mode: nullableString(c.mode, STRING_CAPS.mode),
    props: capProps(props),
  }
}

// Push one event onto `queue` (mutating), dropping the OLDEST events past `maxSize` so
// growth stays bounded when nothing is flushing (offline / outside DSS). Returns the
// number of events dropped (0 in the common case).
export function pushEvent(queue, event, maxSize = MAX_QUEUE) {
  queue.push(event)
  let dropped = 0
  while (queue.length > maxSize) {
    queue.shift()
    dropped += 1
  }
  return dropped
}

// Remove and return up to `maxBatch` events from the FRONT of `queue` (FIFO order),
// mutating the queue. Used to carve the next POST /track batch.
export function drainBatch(queue, maxBatch = MAX_BATCH) {
  return queue.splice(0, maxBatch)
}

// A per-app-session limiter for the noisy error events: at most `max`
// error_frontend/error_backend get through (a broken page could otherwise fire an
// unbounded stream). Non-error names are always allowed and never counted. Stateful by
// design (one instance per app session), but framework-free so it is unit-testable.
export function createErrorLimiter(max = MAX_ERROR_EVENTS) {
  let count = 0
  return {
    allow(name) {
      if (name !== 'error_frontend' && name !== 'error_backend') return true
      if (count >= max) return false
      count += 1
      return true
    },
    get count() {
      return count
    },
  }
}
