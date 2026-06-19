# Frontend - backend communication

> Audience: frontend developer. Last updated: 2026-06-19. Summary: how the OWIsMind
> frontend talks to the Flask backend (the `backend.js` client, the complete call catalogue
> including budget and agent profile routes, the streaming-by-polling loop, applying normalized
> events to the reactive model, the stop flow, Evidence / artifacts retrieval) and which stable
> error codes it consumes.

This page describes the transport layer on the frontend side: the thin HTTP client, the catalogue of backend
calls, the polling loop that animates a live answer, and the separate channels for Evidence and artifacts.
Everything goes through a single fetch helper and a single state reducer; understanding those two pieces is
enough to follow any flow. The function, route, error-code and payload-key names are quoted verbatim from the
code (`Plugin/owismind/frontend/src/`).

## 1. The HTTP client: `getWebAppBackendUrl` + `request()`

All backend traffic goes through `services/backend.js`. The frontend never hardcodes a URL: DSS injects
`window.getWebAppBackendUrl` globally (via the "dataiku" `standardWebAppLibrary`), and the helper
`backendUrl(path)` resolves it lazily. If the resolver is absent (app launched outside the DSS webapp
context), `backendUrl` immediately throws `getWebAppBackendUrl unavailable (run inside the DSS webapp)`: it is
an explicit guardrail that requires running inside the DSS webapp.

The Flask blueprint prefix `/owismind-api` is hardcoded into every path (with no trailing slash). On the
server side it matches the blueprint's `url_prefix="/owismind-api"` (see
[Backend - API reference](../04-backend/02-api-reference.md)).

The `request(path, options)` helper is the ONLY `fetch` point in the whole application. Its behavioral
signature matters more than its body:

```js
const res = await fetch(backendUrl(path), {
  credentials: 'same-origin',
  ...opts,
  headers: { Accept: 'application/json', ...(opts.headers || {}) },
});
if (!res.ok) {
  let code = 'http_' + res.status;
  try { const data = await res.json(); if (data && data.error) code = data.error; } catch (e) {}
  throw new Error(code);
}
return res.json();
```

Three design decisions shape everything else:

- `credentials: 'same-origin'`: the DSS auth cookies travel with every request. This is how the backend
  resolves the caller's identity server-side, from the headers; there is no separate application token on the
  frontend.
- `Accept: application/json` is systematic. `Content-Type: application/json` is added only case by case by the
  POST functions (never on a GET).
- Stable error codes: on a non-2xx response, `request()` tries to read `{ error: "<code>" }` from the JSON
  body and throws an `Error` whose `.message` IS that stable code (e.g. `agent_not_enabled`, `busy`,
  `run_not_found`). If the body is not JSON, the fallback is `http_<status>` (e.g. `http_500`). The entire
  calling layer (stores, composables) compares `e.message` against known codes: it is the frontend's single
  error surface.

## 2. Backend call catalogue

All of these functions are exported from `backend.js`. The routes are relative to `/owismind-api`.

### Core chat and identity

| Function (export) | Method + route | Body / params | Response (shape) |
|---|---|---|---|
| `fetchMe()` | POST `/me` | none | `{status, user_id, display_name, groups, needs_config, is_admin}` |
| `startChat(...)` | POST `/chat/start` | JSON (see 2.1) | `{status, run_id, exchange_id}` |
| `pollChat(runId, cursor)` | GET `/chat/poll?run_id=&cursor=` | query | `{status, events:[...], cursor, done, error}` |
| `stopChat(runId)` | POST `/chat/stop` | `{run_id}` | `{status:'ok'}` (404 `run_not_found` benign) |
| `fetchConversations(cursor, limit)` | GET `/conversations` | optional query | `{status, conversations:[{session_id,title,last_at}], next_cursor, has_more}` |
| `fetchConversation(sessionId)` | GET `/conversation?session_id=` | query | `{status, session_id, count, rows:[...]}` |
| `submitFeedback(exchangeId, rating, reasons, comment)` | POST `/chat/feedback` | `{exchange_id, rating, reasons, comment}` | `{status:'ok'}` |

### Evidence Studio

| Function (export) | Method + route | Response (shape) |
|---|---|---|
| `fetchEvidenceMeta(exchangeId)` | GET `/evidence/meta?exchange_id=` | interactive meta (see section 5) |
| `fetchEvidenceRows(payload)` | POST `/evidence/rows` | `{status, rows, page, has_more, ...}` |
| `fetchEvidenceDistinct(exchangeId, column, excludeId)` | GET `/evidence/distinct?...` | `{status, values, truncated}` |

### Agents and agent profiles

| Function (export) | Method + route | Response (shape) |
|---|---|---|
| `fetchAgents()` | GET `/agents` | `{status, count, agents:[{key, label, tagline, description, capabilities, tools, icon, badge}]}` |

`fetchAgents()` returns the admin-authored display profile for each agent alongside the opaque logical
key and label. The raw `agent_id` and `project_key` NEVER appear in this response. This is the call that
feeds `session.agents`, which in turn populates both the chat `AgentPicker` and the `AgentsView` library
cards.

### Monthly budget / usage

| Function (export) | Method + route | Response (shape) |
|---|---|---|
| `fetchUsage()` | GET `/usage` | `{status, usage: {spent_usd, limit_usd, limit_source, enforced, blocked, remaining_usd, next_reset, period_start, lifetime_tokens, lifetime_cost}}` |

`fetchUsage()` is strictly owner-scoped: it returns only the caller's own budget status. It is called
once during `session.init()` and refreshed after every completed run (fire-and-forget in `chat.js`
`_runExchange` `finally` block). On error, `session.usage` keeps its last known value; the server-side
gate in `/chat/start` remains authoritative.

### Admin endpoints (403 if not admin)

| Function (export) | Method + route | Body / params | Response (shape) |
|---|---|---|---|
| `fetchAdminStorage()` | GET `/admin/storage` | none | `{connection, project_key, table_prefix, namespace, tables}` |
| `fetchAdminUsers()` | GET `/admin/users` | none | `{users:[{user_id, is_admin, ...}]}` |
| `setUserAdmin(userId, isAdmin)` | POST `/admin/users/set-admin` | `{user_id, is_admin}` | refreshed users list |
| `fetchAdminProjects()` | GET `/admin/projects` | none | `{projects:["KEY",...]}` |
| `fetchAdminProjectAgents(projectKey)` | GET `/admin/projects/<key>/agents` | path | `{project_key, agents:[{agent_id, description}]}` |
| `fetchAdminAgents()` | GET `/admin/agents` | none | `{agents:[{logical_key, project_key, agent_id, label, profile:{tagline, description, capabilities, tools, icon, badge}}]}` |
| `saveAdminAgents(agents)` | POST `/admin/agents` | `{agents:[{project_key, agent_id, profile?}]}` | stored selection |
| `fetchAdminBudget()` | GET `/admin/budget` | none | `{status, config, period_start, next_reset, users:[...]}` |
| `saveAdminBudget(config)` | POST `/admin/budget` | `{limit_usd, enabled, temp_limit_usd?, temp_days?}` | refreshed overview |
| `saveAdminUserQuota(payload)` | POST `/admin/budget/users` | `{user_ids, clear, limit_usd?, expires_days?, note?}` | refreshed overview |

Cross-cutting points that often surprise:

- `fetchMe()` is deliberately a POST. The `/me` route has a side effect (creating the user row and
  bootstrapping the first-admin election); as a POST, a prefetch or a scanner GET can neither create a user
  nor win the election. It is called exactly once at init.
- The admin endpoints are gated server-side: 403 if the caller is not an admin. The frontend performs no
  security check; it shows the admin views based on `session.isAdmin`, but it is the server that decides.
- Agent whitelist (chat side): the frontend NEVER sends or receives a raw `agent_id` on the chat flow.
  `fetchAgents()` returns only opaque logical keys plus the admin-authored profile; the resolution
  `agent_key -> (project_key, agent_id)` is entirely server-side (see
  [Security model](../02-architecture/04-security-model.md)). The `agent_id` values only appear in the
  admin endpoints.
- `saveAdminAgents` sends `profile?` alongside `project_key` / `agent_id`. The server re-validates and
  sanitizes the profile via `security/validation.py::validate_agent_meta` before persisting. The frontend
  enforces soft limits (char count, icon whitelist) as a UX guard, but the server is authoritative.
- `saveAdminBudget` accepts an optional temporary boost (`temp_limit_usd` + `temp_days`): if both are
  present, the boost is stored (overriding the previous one); if either is absent or both are zero, the
  existing boost is cleared. This preserves the permanent limit untouched when touching only the boost.
- `saveAdminUserQuota` targets one, several, or all users (`user_ids: [...]`). `clear: true` removes
  the per-user override; `expires_days` absent or `null` = permanent override.

### 2.1 The `startChat` payload

`startChat` is the richest call. The frontend sends only LOGICAL data; no sensitive technical key:

```js
body: JSON.stringify({
  session_id: sessionId,
  message,
  agent_key: agentKey,                  // OPAQUE logical key (resolved server-side)
  history_limit: historyLimit,          // re-clamped [10,50] server-side (default 20)
  parent_exchange_id: parentExchangeId || null,   // conversation-tree edge
  mode: mode || undefined,              // eco / medium / high (server default: eco)
  webapp_lang: webappLang || undefined, // fr / en (helps choose the answer language)
  screen_context: screenContext || undefined,     // pointer to "what is on screen"
})
```

- `parent_exchange_id` attaches the new exchange into the conversation TREE and bounds the agent's context to
  that branch's ancestor chain. `null` creates a new branch at the root.
- An unknown or absent `mode` (eco / medium / high) falls back to `medium` server-side (the backend
  conservative default, verified in `api/routes.py`). The frontend itself defaults to `eco` via
  `ui.modelMode` (MODELMODE_DEFAULT), so an absent mode reaches the server only in edge cases.
- `webapp_lang` (the UI language, `ui.lang`) serves only as a tie-break: the language of the message itself
  wins server-side.
- `screen_context` is built only when the Evidence panel is open (see section 6). It is owner-scoped
  server-side, so a forged id reveals nothing.

## 3. The transport: streaming-by-polling

The heart of the transport lives in `composables/useChatStream.js`. The choice of polling (rather than SSE) is
a documented architecture decision: DSS places an internal nginx in front of each webapp backend, and a long
`text/event-stream` response can be buffered by that proxy (the events would then all arrive at once at the
end, instead of arriving live). The chosen pattern runs the agent in a background worker thread that
accumulates its progress in an in-memory dict; the frontend polls that dict with short requests that the proxy
never buffers.

> The canonical sequence diagram of streaming-by-polling (worker thread, `_RUNS` dict, `/chat/poll` loop at
> 500 ms, cursor) lives in
> [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md). This page does not redraw
> that diagram; it describes the CLIENT SIDE of that loop.

### 3.1 Loop constants

```js
const POLL_INTERVAL_MS = 500            // nominal polling cadence
const MAX_POLL_FAILURES = 5             // tolerance for transient proxy blips
const MAX_BACKOFF_MS = 5000             // exponential-backoff ceiling
const TERMINAL_CODES = new Set(['run_not_found', 'invalid_run_id', 'unauthenticated'])
```

### 3.2 `runChatStream`: the complete loop

`runChatStream` receives a destructured object
(`{ sessionId, message, agentKey, historyLimit, parentExchangeId, mode, webappLang, screenContext, target,
token, onExchangeId, onRunId }`) and runs the following sequence.

1. Start: `await startChat(...)` returns `{ run_id, exchange_id }`.
2. Reconciliation callbacks, each invoked once:
   - `onRunId(runId)` reports the run id back to the store, so a stop can be requested on THIS run.
   - `onExchangeId(exchange_id)` reports the real backend exchange id, so that the store reconciles its
     temporary tree key (`null`) before this exchange can become the parent of a next one.
3. Infinite loop, `cursor` at 0 and `failures` at 0:
   - Cancellation guard BEFORE the poll: if `token.cancelled`, exit without touching the version (which may
     already be stale).
   - `res = await pollChat(runId, cursor)`, then `failures = 0` on success.
   - On a poll error, re-check `token.cancelled` after the `await` ("superseded mid-poll" race: conversation
     changed, a newer run started). Then:
     - If the code is TERMINAL (`run_not_found` / `invalid_run_id` / `unauthenticated`), the run has
       disappeared (typically a backend restarted mid-run). An `error` event is applied to the `target` (with
       `message: 'run_lost'` when it is `run_not_found`, otherwise the raw code), BUT only if
       `target.status === 'running'`. This is treated as RECOVERABLE, not as a crash.
     - Otherwise, transient error: `failures += 1`. Beyond `MAX_POLL_FAILURES`, the error is re-thrown (hard
       failure). Otherwise an exponential backoff `min(500 * 2 ** failures, 5000)` ms then `continue`.
   - Applying the events: re-guard `token.cancelled`, then
     `for (const evt of res.events || []) applyEvent(target, evt)`. Adopt `cursor = res.cursor`. If
     `res.done`, `break`.
   - Otherwise `await sleep(POLL_INTERVAL_MS)` before the next round.
4. Defensive net: if the loop exits without a terminal event and `target.status` is still `running`, apply
   `{ type: 'run_done' }` to stop the spinner (never overwrite a `stopped`/`error` already received).

The `cursor` is purely a SERVER counter: it is the number of events already consumed. The server returns the
`events[start:]` slice and the new cursor `len(events)`. The client simply re-posts what it was given: no
duplicate, no loss. Any attempt to compute the cursor client-side would break the contract.

### 3.3 The cancellation token

`token` is a simple `{ cancelled }` object. The caller (the store) sets it to `true` to stop the loop
(navigation, a newer run, a conversation switch); an abandoned run is then no longer polled client-side.
Important point: cancelling the polling client-side does NOT stop the worker on the backend. The backend has
its own abandonment detection (a `last_poll_at` heartbeat updated on every poll, and an
`ABANDON_AFTER_SECONDS` cutoff when nobody polls anymore) to free the slot and stop burning tokens. See
[Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md).

## 4. Applying events to the reactive model

`composables/timelineModel.js` exposes `applyEvent(state, evt)`, a PURE reducer (no Vue import) that mutates
the state object IN PLACE. The store wraps that state in `reactive()`, so each nested mutation
(`timeline.push`, `text +=`) re-renders live. `useChatStream` applies each polled event through this reducer.

### 4.1 The answer "version"

`createAnswerState()` produces the shape of an answer version:

```
{ timeline:[item], sql:[{sql,success,row_count}], usage, status:'running'|'done'|'stopped'|'error',
  stopping:false, error:'', showSql:false, exchangeId,
  feedbackRating, feedbackReasons, feedbackComment, _seq:0 }
```

The feedback fields are OUT-OF-BAND (persisted per exchange server-side, never derived from the event stream):
`applyEvent` never touches them. The timeline items are discriminated by `kind`, each with a stable `id` and an
arrival `seq`: `event`, `text` (with `open` = a block still merging deltas), `error`, and `narration`
(transient, live-only).

### 4.2 The normalized events consumed

`applyEvent` handles each `evt.type` and silently IGNORES any unknown type, so that a new event can never break
the UI.

| `evt.type` | Effect on the state |
|---|---|
| `run_started` | `status='running'` ; if `evt.exchangeId != null` -> `state.exchangeId` |
| `agent_event` | `pushEvent`: an `event` item (seals the preceding events, closes the text) |
| `answer_delta` | `appendText(evt.text)`: merge into the open text block, otherwise a new block |
| `narration` | `pushNarration`: a transient item (never persisted as an answer) |
| `generated_sql` | `state.sql.push({sql, success, row_count})` (outside the timeline, dedicated SQL panel) |
| `usage_summary` | `state.usage = {promptTokens, completionTokens, totalTokens, estimatedCost}` |
| `final_answer` | `pushFinalAnswer`: materializes the text ONLY if nothing has already streamed |
| `run_done` | seals events + closes text ; `stopping=false` ; `running` -> `done` |
| `stopped` | same as `run_done` but `running` -> `stopped` (user stop, not an error) |
| `error` | `status='error'`, `error=message`, `pushError` (an `error` item) |

Four subtleties to know:

- `sealEvents`: on each new item, any event still `running` flips to `done`. Only one event is ever shown
  "running" (the most recent); everything after it is finalized.
- `appendText` merges consecutive deltas of the same block (`last.text += delta`) to avoid fragmentation and
  duplicates; the mutation goes through the array element to trigger the reactive proxy.
- `pushFinalAnswer` materializes the final text ONLY if nothing has streamed (`hasStreamedText`). For an agent
  that streams deltas (the normal case), `final_answer` only confirms and closes the block, with no duplicate;
  the final text is materialized only for structured agents that emit the whole answer at the end.
- `stopped` only marks the version as interrupted: no `error` item, no red toast. The partial answer has
  already been materialized by the `final_answer` that the worker emits BEFORE the `stopped`. Like `run_done`,
  it only flips a version that is still `running`, so a late or duplicate stop is a no-op.

> Important casing note: the events use camelCase (`exchangeId`, `promptTokens`, `rowCount`, `sqlIndex`) that
> the reducer reads as-is. The SQL storage, by contrast, uses snake_case (`row_count`, `input_tokens`).
> `usageFromRow(row)` bridges snake -> camel when a conversation is reloaded from `/conversation` (the live
> path, for its part, fills `usage` via the `usage_summary` event). `usageFromRow` returns `null` if nothing
> was stored, so as not to display an empty usage line.

### 4.3 The read-only selectors

Several PURE selectors read the timeline without mutating it, so without moving the stable ids or the
`timelineSignature` (the auto-scroll gating of `ChatThread` depends on it): `answerText` (concatenation of the
`text` blocks for copying), `timelineSignature` (`length|textLen|status`, a cheap change signature),
`timelineEvents` / `timelineBodyItems` / `timelineSegments` (grouped activity + body rendering), and
`stepStampDiff` / `activitySummary` (durations derived from the `elapsedSeconds` stamps set by the backend, the
total being the MAX of the stamps, never a sum). `narration` is deliberately EXCLUDED from the persisted body
and from the segments. See [Frontend - state and stores](02-state-and-stores.md) and
[Frontend - components and views](03-components-and-views.md) for the use of these selectors.

## 5. Evidence and artifacts: a SEPARATE channel

The evidence data does NOT travel through `/chat/poll`. The live timeline only carries `event` items, text
deltas, and the LIST of SQL (text + `success` + `row_count`, without the result rows). The captured results
(rows) and the artifact specs (`{kind, title, chart|kpi}`) are persisted server-side at the end of the run,
then read back afterwards via `/evidence/meta`.

On the frontend side, this channel has its own store, `stores/evidence.js`, which orchestrates
`fetchEvidenceMeta` / `fetchEvidenceRows` / `fetchEvidenceDistinct` with staleness guards (`seq` for the
open/close transitions, `rowsSeq` for the rows: the same idiom as the cancellation token of `chat.js`, last
request wins). The `/evidence/rows` payload is built by `composables/evidenceModel.js` and NEVER CARRIES any
SQL: the editable chips travel as structured filters `{column, op, values}` and the locked agent chips travel
as `kept_ids` (the backend re-derives them from its stored SQL by id).

The meta consumed from `/evidence/meta` includes `available` (plus `reason` when the view is degraded, raw SQL
only), `chips`, `advanced`, `sources`, `artifacts`, `result:{captured, columns, rows}` and `drilldown`. The
default tab is computed from `artifacts` (`_defaultTab`: `chart`/`table` if an artifact exists, otherwise
`evidence`). Switching tabs does NOT TOUCH `open` (the scroll gate of `ChatThread` is gated on `evidence.open`,
not on `activeTab`). The rows pagination adopts the page ECHOED by the server (which clamps deep pages via
`MAX_EVIDENCE_PAGE`, mirrored by `MAX_PAGE = 20` on the frontend) and the lazy accumulation is bounded at
`MAX_ROWS = 500`.

> IN FLUX: the `result.rows` key (captured result) is best-effort on the backend (the key of the tool span's
> rows is not confirmed on the instance). The capture may be absent without breaking the rendering
> (`result.captured: false`). The backend detail lives in
> [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

## 6. The STOP flow ("Stopping...")

The `chat` store (`stores/chat.js`) wraps `useChatStream`, owns the exchange tree and orchestrates the stop. It
holds four local handles: `activeToken` (the cancellation token of the in-flight loop), `activeRunId` (the
server run id, for an explicit stop), `stopPending` (covers the "user presses stop BEFORE `/chat/start`
returned the run_id" race) and `activeVersion` (the in-flight version, to finalize the partial on screen).

`stopGeneration()` sums up the contract:

```js
function stopGeneration() {
  if (!sending.value) return
  if (activeRunId) stopChat(activeRunId).catch(() => {})   // POST /chat/stop
  else stopPending = true                                  // run_id not yet known
  if (activeVersion && activeVersion.status === 'running') {
    activeVersion.stopping = true                          // shows "Stopping..."
  }
}
```

The why: the backend stop is COOPERATIVE. The LLM Mesh stream has NO cancel API; the worker can only break
BETWEEN two streamed chunks (an in-flight LLM or SQL call keeps it busy for a few seconds). Rather than fake a
false instant stop, the frontend KEEPS polling and shows a blinking "Stopping..." indicator (`stopping=true`
plus spinner) until the terminal `stopped` event arrives and finalizes the partial. The `stopping` flag is
local and optimistic; it is reset to `false` by ANY terminal event (`run_done`, `stopped`, `error`). On the
backend side, `request_stop` sets `stop_requested=true` (owner-scoped), the worker stops iterating, persists
the partial, emits `final_answer` THEN `stopped`. A 404 `run_not_found` means the run is already finished or
unknown; the frontend treats that 404 as a benign no-op via the `.catch`.

`cancelActive()` is distinct from the stop: it cancels the token (and thus stops the polling client-side) and
resets `activeToken` / `activeRunId` / `activeVersion` / `stopPending`. It is called at the start of any new
run, as well as in `newConversation` and `openSession` (conversation switch).

### 6.1 The lifecycle of a send

`_runExchange(userText, parentId)` is the only place where an exchange is created then run. It: (1) calls
`cancelActive()`, creates a reactive version and an exchange (`id: null`, stable `uid`); (2) builds
`screenContext` ONLY if the Evidence panel is open; (3) calls `runChatStream({...})` with `target: version`,
`token`, `onExchangeId` (reconciles `id`) and `onRunId` (sets `activeRunId`, triggers a deferred
`stopPending`); (4) auto-opens Evidence (premium reveal) if the answer finished CLEANLY and produced at least
one successful SQL (`version.sql.some(q => q && q.success)`), never on `stopped`/`error`; (5) in `catch`, if
the error is `monthly_quota_exceeded`, drops the optimistic exchange from `exchanges` (no empty error bubble)
instead of setting `version.status='error'`; otherwise sets `version.status='error'`; (6) in `finally`, resets
`sending=false`, promotes the conversation to the top of the sidebar (data captured at the run entry), and calls
`session.loadUsage()` (fire-and-forget) to refresh the budget status immediately after every run. The `canSend`
guard blocks any send as long as the thread on screen is not that of the active session, which avoids a
cross-conversation corruption. The detail of the conversation tree and the stores is in
[Frontend - state and stores](02-state-and-stores.md).

## 7. The error-code surface

The stable codes emitted by the backend and consumed via `e.message` on the frontend:

| Endpoint | Codes (with HTTP status) |
|---|---|
| `/chat/start` | `unauthenticated` (401), validation (400), `storage_not_configured` (409), `agent_not_enabled` (404), `rate_limited` (429), `busy` (503), `storage_unavailable` (500), `agent_unavailable` (500), `monthly_quota_exceeded` (402) |
| `/chat/poll` | `unauthenticated` (401), `invalid_run_id` (400), `run_not_found` (404, mapped to `run_lost` when the run disappeared in mid-flight) |
| `/chat/stop` | `unauthenticated` (401), `invalid_run_id` (400), `run_not_found` (404 = benign no-op) |
| Terminal error events in the stream (not HTTP codes) | `run_timeout`, `run_abandoned`, `agent_unavailable`: arrive as `{type:'error', message:...}` and go through `applyEvent` (an `error` item + `status='error'`) |
| Generic fallback | `http_<status>` when the body is not JSON |

`monthly_quota_exceeded` (402) from `/chat/start` is the budget gate: no run was started, so the store
drops the optimistic exchange and relies on the budget banner (refreshed via `session.loadUsage()`) to
explain the situation. The server enforces this gate before the agent is even called.

On the `useChatStream` side, the set `TERMINAL_CODES = {run_not_found, invalid_run_id, unauthenticated}`
distinguishes the UNRECOVERABLE poll errors (the run is dead, exit cleanly) from the transient proxy blips
(retry with backoff up to 5 failures). The complete list of endpoints, payloads and codes lives in
[Backend - API reference](../04-backend/02-api-reference.md).

## 8. Subtle points to remember

- The cursor is a server counter, not a timestamp: the frontend blindly re-posts `res.cursor`.
- Cancelling the polling client-side does not stop the worker; the backend cuts off on its own after ~30 s
  without a poll.
- The defensive `run_done` net applies only if `status === 'running'`, so as not to overwrite a terminal
  already received.
- `final_answer` adds text only if nothing has streamed (never a duplication in the normal case).
- `stopping` (local, optimistic) and `stopped` (server terminal event) are distinct; every terminal resets
  `stopping=false`.
- Unknown event types are ignored on both sides: adding a new event type is backward-compatible.
- `narration` is transient: never in the persisted body nor in `answerText`, only live.
- The `monthly_quota_exceeded` error (402) is a BUDGET GATE - not a validation error. The store handles it
  specially (drops the optimistic exchange, no error bubble, refreshes usage).
- `fetchAgents()` now returns profile fields (`tagline`, `description`, `capabilities`, `tools`, `icon`,
  `badge`) alongside `key` and `label`. These are admin-authored; they may be empty strings/arrays if
  the admin has not filled them in yet.

> IN FLUX: the agent layer (`dataiku-agents/`) is being edited live. The LangGraph agents PRODUCE the raw
> events that `streaming.py` normalizes, so their behavior may evolve; on the other hand, the CONTRACT of
> normalized events described here (the backend -> frontend format) is the stable part of the interface.

## See also
- [Frontend - state and Pinia stores](02-state-and-stores.md) - the `chat`/`session`/`evidence`/`ui` stores that consume this client and the reducer.
- [Frontend - components and views](03-components-and-views.md) - how `MessageAgent`/`ChatThread`/`EvidencePanel` render the state animated here.
- [Backend - API reference](../04-backend/02-api-reference.md) - the server contract of each endpoint, payloads and codes.
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - the worker thread, the `_RUNS` dict, the cursor and the server-side stop (home of the polling diagram).
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - the capture, the meta and the artifacts read back via `/evidence/meta`.
- [Runtime flows](../02-architecture/03-runtime-flows.md) - the same chat turn seen end to end (home of the sequence diagram).
- [ADR-0002 - Streaming by polling](../08-decisions/0002-streaming-par-polling.md) - the transport decision (no SSE, DSS proxy).
