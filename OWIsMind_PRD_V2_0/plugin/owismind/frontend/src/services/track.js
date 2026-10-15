// Usage-analytics tracker - browser wiring around the pure trackModel. Best-effort by
// contract: track() NEVER throws and a transport failure never affects the user. Events
// are queued and flushed in small batches to POST /track (the server always answers 200).
//
// Transport rules:
//   - queue is bounded (trackModel.MAX_QUEUE); the flush loop ticks every 5s while the
//     queue is non-empty, and an immediate flush fires once the queue reaches 20 events.
//   - a normal flush uses fetch (keepalive) - on a NETWORK failure the batch is requeued
//     (so nothing is lost while offline); on ANY HTTP response, 2xx or not, the batch is
//     dropped (the server accepted the attempt; retrying would double-count).
//   - the final flush on page hide uses navigator.sendBeacon so in-flight events survive
//     an unload the fetch would otherwise abort.
//   - while an admin is impersonating a user, track() is a no-op (the server drops those
//     too; this just avoids the traffic).
//
// The backend base path is resolved the same way as services/backend.js
// (window.getWebAppBackendUrl), so we never hardcode a URL and degrade to a no-op flush
// outside DSS. We intentionally do NOT import backend.js (it imports us for error_backend).
import {
  makeEvent,
  pushEvent,
  drainBatch,
  createErrorLimiter,
  MAX_QUEUE,
  MAX_BATCH,
} from './trackModel.js'
// Impersonation guard (temporary feature, isolated folder): read-only helper, no store.
import { getImpersonateTarget } from '../features/admin-impersonate/impersonation.js'

const TRACK_PATH = '/owismind-api/track'
const FLUSH_INTERVAL_MS = 5000
const FLUSH_THRESHOLD = 20 // immediate flush once the queue reaches this many events

// A UUID (crypto.randomUUID when available) with a Math.random hex fallback so an old /
// locked-down browser still yields a stable-enough id. Never throws.
function uuid() {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
      return crypto.randomUUID()
    }
  } catch (e) {
    /* fall through to the hex fallback */
  }
  const rnd = () => Math.random().toString(16).slice(2, 10)
  return rnd() + rnd() + '-' + Date.now().toString(16) + '-' + rnd()
}

// One id per browser tab/app session (all events of a load share it); monotonic seq for
// intra-session ordering; the ambient view is set by the router hook (setCurrentView).
const APP_SESSION_ID = uuid()
let seqCounter = 0
let currentView = null

const queue = []
const errorLimiter = createErrorLimiter()
let flushTimer = null
let started = false

// Resolve the /track URL exactly like services/backend.js. Returns null (no-op) when the
// DSS resolver is absent (running outside the webapp) so events simply stay queued.
function trackUrl() {
  const resolver = window.getWebAppBackendUrl
  if (typeof resolver !== 'function') return null
  try {
    return resolver(TRACK_PATH)
  } catch (e) {
    return null
  }
}

function isImpersonating() {
  try {
    return !!getImpersonateTarget()
  } catch (e) {
    return false
  }
}

// The router hook sets the current route name here; makeEvent stamps it as `view`.
export function setCurrentView(name) {
  currentView = name || null
}

// Queue one event. Never throws. `ctx` may carry conversation_id / agent_key / mode (and
// may override `view`); anything absent falls back to the ambient values. Unknown event
// names are dropped by makeEvent; error events beyond the session cap are dropped by the
// limiter; an impersonating admin is a full no-op.
export function track(name, props = {}, ctx = {}) {
  try {
    if (isImpersonating()) return
    // Bound the noisy error stream BEFORE shaping (a broken page could flood otherwise).
    if (!errorLimiter.allow(name)) return
    const event = makeEvent(name, props, {
      id: uuid(),
      client_ts: new Date().toISOString(),
      seq: ++seqCounter,
      app_session_id: APP_SESSION_ID,
      view: ctx.view !== undefined ? ctx.view : currentView,
      conversation_id: ctx.conversation_id != null ? ctx.conversation_id : null,
      agent_key: ctx.agent_key != null ? ctx.agent_key : null,
      mode: ctx.mode != null ? ctx.mode : null,
    })
    if (!event) return // unknown/dropped name
    pushEvent(queue, event, MAX_QUEUE)
    if (queue.length >= FLUSH_THRESHOLD) flush()
    else ensureTimer()
  } catch (e) {
    /* tracking is best-effort: swallow everything. */
  }
}

// Start (or keep) the 5s flush ticker. It self-stops when the queue drains, and every
// enqueue re-arms it, so no timer runs while idle.
function ensureTimer() {
  if (flushTimer != null) return
  try {
    flushTimer = setInterval(() => {
      if (!queue.length) {
        clearTimer()
        return
      }
      flush()
    }, FLUSH_INTERVAL_MS)
  } catch (e) {
    /* no timers available (non-DOM env): flushing falls back to threshold/beacon. */
  }
}
function clearTimer() {
  if (flushTimer == null) return
  try {
    clearInterval(flushTimer)
  } catch (e) {
    /* ignore */
  }
  flushTimer = null
}

// Put an un-sent batch back at the FRONT (it is the oldest data), then trim the front
// again if that pushed us over the cap - so a long offline spell stays bounded.
function requeueFront(batch) {
  if (!batch || !batch.length) return
  queue.unshift(...batch)
  const overflow = queue.length - MAX_QUEUE
  if (overflow > 0) queue.splice(0, overflow)
  ensureTimer()
}

// Send the next batch via fetch (keepalive). Network failure -> requeue (keep the data);
// any HTTP response -> drop (the server took it). Never throws.
function flush() {
  if (!queue.length) return
  const url = trackUrl()
  if (!url) return // outside DSS: keep queued (bounded by the cap)
  const batch = drainBatch(queue, MAX_BATCH)
  const body = JSON.stringify({ events: batch })
  try {
    fetch(url, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body,
      keepalive: true,
    }).catch(() => {
      // NETWORK failure only (fetch rejects): keep the events for a later flush.
      requeueFront(batch)
    })
    // On any HTTP response (2xx or not) the batch stays dropped: we do not re-add it.
  } catch (e) {
    requeueFront(batch)
  }
}

// Final flush on page hide: sendBeacon survives the unload a fetch would abort. Drains
// the whole queue in <=MAX_BATCH chunks (bounded by MAX_QUEUE/MAX_BATCH iterations).
function beaconFlush() {
  try {
    if (isImpersonating()) return
    if (!queue.length) return
    const url = trackUrl()
    if (!url) return
    const beacon =
      typeof navigator !== 'undefined' && typeof navigator.sendBeacon === 'function'
        ? navigator.sendBeacon.bind(navigator)
        : null
    if (!beacon) {
      flush() // no beacon API: best-effort keepalive fetch
      return
    }
    let guard = 0
    const maxChunks = Math.ceil(MAX_QUEUE / MAX_BATCH) + 1
    while (queue.length && guard < maxChunks) {
      guard += 1
      const batch = drainBatch(queue, MAX_BATCH)
      const blob = new Blob([JSON.stringify({ events: batch })], { type: 'application/json' })
      const ok = beacon(url, blob)
      if (!ok) {
        // The UA refused the beacon (queue full / too large): put it back and stop.
        requeueFront(batch)
        break
      }
    }
  } catch (e) {
    /* best-effort: never block an unload. */
  }
}

// One-time init on module load: register the page-hide flush hooks and emit
// webapp_opened. Idempotent (multiple imports share this single module instance).
function init() {
  if (started) return
  started = true
  try {
    window.addEventListener('pagehide', beaconFlush)
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') beaconFlush()
    })
  } catch (e) {
    /* non-DOM env: no page-hide hooks (tests never import this module). */
  }
  track('webapp_opened', {})
}

init()
