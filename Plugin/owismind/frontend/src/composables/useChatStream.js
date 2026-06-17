// Chat transport - the validated polling loop, ported VERBATIM in behavior from the
// plugin's App.vue (L019/L020). Transport is POLLING (not SSE): DSS's
// internal proxy buffers long-lived streams, so the run executes in a background worker
// and we poll /chat/poll for normalized events.
//
// Each polled event is fed to the PURE timeline reducer (applyEvent, timelineModel.js),
// which builds the single ordered, incremental display timeline. `target` is the
// REACTIVE answer-version object the store created with reactive() - the reducer mutates
// it in place, so nested mutations (timeline.push, text +=) re-render live (L020).
import { startChat, pollChat } from '../services/backend.js'
import { applyEvent } from './timelineModel.js'

const POLL_INTERVAL_MS = 500
// The DSS proxy can blip a single poll while the worker keeps producing the answer, so a
// transient poll error is retried with backoff rather than failing the whole run.
const MAX_POLL_FAILURES = 5
const MAX_BACKOFF_MS = 5000
// Stable backend error codes that are TERMINAL (retrying the poll cannot help).
const TERMINAL_CODES = new Set(['run_not_found', 'invalid_run_id', 'unauthenticated'])
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))

// Apply one normalized event to the live answer version. Thin wrapper over the pure
// reducer (kept as a named export for clarity/testing parity with the reducer).
export function handleEvent(target, evt) {
  applyEvent(target, evt)
}

// Start a run and poll its event timeline into `target` until done. The frontend
// sends ONLY { sessionId, message, agentKey } - agentKey is the OPAQUE logical key
// (identity + real agent id resolved server-side). Throws the backend's stable
// error code (agent_not_enabled, busy, run_not_found…) for the caller to handle.
//
// `token` is an optional { cancelled } object: the caller flips it to true to stop the
// loop (e.g. the user navigated away or started a newer run / switched conversation), so
// an abandoned run is no longer polled. A single transient poll error is retried with
// backoff; a TERMINAL code (e.g. run_not_found after a backend restart) ends the run
// cleanly as recoverable.
//
// `parentExchangeId` (optional) links the new exchange into the conversation tree (branch
// point). `onExchangeId` (optional) is invoked once with the real exchange id returned by
// /chat/start, so the store can reconcile the temporary (null) tree key to the backend id
// before this exchange can become the parent of a follow-up.
export async function runChatStream({ sessionId, message, agentKey, historyLimit, parentExchangeId, mode, webappLang, screenContext, target, token, onExchangeId, onRunId }) {
  const { run_id: runId, exchange_id } = await startChat(sessionId, message, agentKey, historyLimit, parentExchangeId, mode, webappLang, screenContext)
  // Surface the run id so the store can request a user stop (POST /chat/stop) on THIS run.
  if (onRunId && runId) onRunId(runId)
  if (onExchangeId && exchange_id) onExchangeId(exchange_id)
  let cursor = 0
  let failures = 0
  for (;;) {
    if (token && token.cancelled) return
    let res
    try {
      res = await pollChat(runId, cursor)
      failures = 0
    } catch (e) {
      // Superseded mid-poll (conversation switched / newer run started): stop without
      // touching the stale version - same guard the success path applies after its await.
      if (token && token.cancelled) return
      const code = (e && e.message) || ''
      if (TERMINAL_CODES.has(code)) {
        // The run is gone (e.g. the backend restarted mid-run): recoverable, not a crash.
        if (target.status === 'running') {
          applyEvent(target, {
            type: 'error',
            message: code === 'run_not_found' ? 'run_lost' : code,
          })
        }
        return
      }
      failures += 1
      if (failures > MAX_POLL_FAILURES) throw e
      await sleep(Math.min(POLL_INTERVAL_MS * 2 ** failures, MAX_BACKOFF_MS))
      continue
    }
    if (token && token.cancelled) return
    for (const evt of res.events || []) applyEvent(target, evt)
    cursor = res.cursor
    if (res.done) break
    await sleep(POLL_INTERVAL_MS)
  }
  // Defensive: if the run ended without a terminal event, stop the spinner.
  if (target.status === 'running') applyEvent(target, { type: 'run_done' })
}
