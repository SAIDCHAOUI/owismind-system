// Thin client for the OWIsMind Flask backend (chat storage + polling transport).
//
// In a DSS standard webapp, `getWebAppBackendUrl` is injected globally by the
// "dataiku" standardWebAppLibrary. We resolve it lazily and never hardcode URLs.
// Paths must match the Flask routes exactly (blueprint prefix "/owismind-api"),
// with no trailing slash.

// BEGIN impersonation (temporary) - admin "view as user". This adds the
// X-OWI-Impersonate header to EVERY call when an admin is impersonating a user.
// Removable: delete this import + the merge in request() below, and the
// features/admin-impersonate folder.
import { impersonationHeaders } from '../features/admin-impersonate/impersonation.js'
// END impersonation (temporary)

function backendUrl(path) {
  const resolver = window.getWebAppBackendUrl;
  if (typeof resolver !== 'function') {
    throw new Error('getWebAppBackendUrl unavailable (run inside the DSS webapp)');
  }
  return resolver(path);
}

// Single fetch helper: same-origin credentials (so DSS auth cookies travel),
// JSON in/out, and a stable error code surfaced from the backend when present.
async function request(path, options) {
  const opts = options || {};
  const res = await fetch(backendUrl(path), {
    credentials: 'same-origin',
    ...opts,
    // BEGIN impersonation (temporary) - carry the X-OWI-Impersonate header (empty
    // object when not impersonating). Server honours it only for real admins.
    headers: { Accept: 'application/json', ...impersonationHeaders(), ...(opts.headers || {}) },
    // END impersonation (temporary)
  });
  if (!res.ok) {
    let code = 'http_' + res.status;
    try {
      const data = await res.json();
      if (data && data.error) code = data.error;
    } catch (e) {
      /* ignore non-JSON error bodies */
    }
    throw new Error(code);
  }
  return res.json();
}

// Identity of the caller, resolved server-side from the browser auth headers.
// Returns { status, user_id, display_name, groups, needs_config, is_admin }.
// POST (not GET): /me's side effect (record the user + first-admin bootstrap) lives on
// POST, so a prefetch/scanner GET can neither create a user row nor win the admin
// election. Called once on init; identity itself is still resolved server-side.
export function fetchMe() {
  return request('/owismind-api/me', { method: 'POST' });
}

// Start a real agent run for one message; returns { status, run_id, exchange_id }.
// Transport is POLLING, not SSE: DSS's internal nginx can buffer a long-lived stream
// so events would arrive all at once. Instead the agent runs in a background worker
// and the front polls /chat/poll (short requests the proxy never buffers) - the same
// pattern as the project's production Dash app. The frontend sends ONLY
// { session_id, message, agent_key, history_limit }; agent_key is the OPAQUE logical
// key from /agents (identity + real agent id are resolved server-side). history_limit
// bounds the multi-turn context window (re-validated/clamped to [10,50] server-side).
// Throws on a non-2xx response with the backend's stable error code (e.g.
// agent_not_enabled, busy). `parentExchangeId` (optional) links the new exchange into
// the conversation tree: it becomes the new exchange's parent and bounds the agent's
// context to that branch's ancestor chain (null = a new branch at the conversation root).
export function startChat(sessionId, message, agentKey, historyLimit, parentExchangeId, mode, webappLang, screenContext) {
  return request('/owismind-api/chat/start', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      session_id: sessionId,
      message,
      agent_key: agentKey,
      history_limit: historyLimit,
      parent_exchange_id: parentExchangeId || null,
      // Model mode (eco / medium / high). Unknown/absent -> medium server-side.
      mode: mode || undefined,
      // Web-app configured language (fr / en) - helps the agent pick the reply
      // language (the language of the message itself still wins server-side).
      webapp_lang: webappLang || undefined,
      // Screen-awareness pointer: which exchange + tab the user is viewing in the
      // Evidence panel (so the agent knows what's on screen). Owner-scoped server-side.
      screen_context: screenContext || undefined,
    }),
  });
}

// Fetch the run's normalised events since `cursor`. Returns
// { status, events: [...], cursor, done, error }. `events` are the new normalised
// events in order (run_started / agent_event / answer_delta / generated_sql /
// usage_summary / final_answer / run_done / error); `cursor` is the next value to
// send back; `done` signals the run finished. Throws (e.g. run_not_found) on a
// non-2xx response.
export function pollChat(runId, cursor) {
  const q = '?run_id=' + encodeURIComponent(runId) + '&cursor=' + encodeURIComponent(cursor);
  return request('/owismind-api/chat/poll' + q, { method: 'GET' });
}

// Request a cooperative early stop of one of the caller's own in-flight runs (the ■
// button). Server-side the worker stops iterating the LLM Mesh stream, persists the
// PARTIAL answer, and ends the run with a terminal `stopped` event (not an error). The
// run is owner-scoped. Returns { status:'ok' }; throws 'run_not_found' (404) when the run
// is already finished/unknown - callers treat that as a benign no-op ("already done").
export function stopChat(runId) {
  return request('/owismind-api/chat/stop', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ run_id: runId }),
  });
}

// Names-only, keyset-paginated conversation list (sidebar). Never returns bodies.
// Returns { status, conversations: [{ session_id, title, last_at }], next_cursor,
// has_more }. `cursor`/`limit` are optional; the backend clamps the page size.
export function fetchConversations(cursor, limit) {
  const qs = new URLSearchParams()
  if (cursor) qs.set('cursor', cursor)
  if (limit) qs.set('limit', String(limit))
  const suffix = qs.toString() ? `?${qs.toString()}` : ''
  return request(`/owismind-api/conversations${suffix}`)
}

// Full messages of ONE session - lazy, fetched only when a conversation is opened.
// Returns { status, session_id, count, rows: [...] } - one row per stored exchange
// (user_text, assistant_text, generated_sql, feedback, parent_exchange_id, …).
export function fetchConversation(sessionId) {
  return request(`/owismind-api/conversation?session_id=${encodeURIComponent(sessionId)}`)
}

// Persist 👍/👎 feedback for ONE message (the caller's own). rating: 1 (up) | 0 (down)
// | null (clear). reasons: array of reason codes (down). comment: free text (down).
// Returns { status:'ok' }; throws the backend error code on a non-2xx.
export function submitFeedback(exchangeId, rating, reasons, comment) {
  return request('/owismind-api/chat/feedback', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ exchange_id: exchangeId, rating, reasons: reasons || [], comment: comment || '' }),
  });
}

// --- Benchmark suggestions (collaborative golden-set intake) -------------------

// Suggest a brand-new benchmark Q/A from scratch. `fields` =
// { question, reference_answer, expected_value?, expected_value_type?, category?, language? }.
// Returns { status:'ok', suggestion_id }; throws the backend error code on a non-2xx.
export function suggestBenchmarkManual(fields) {
  return request('/owismind-api/benchmark/suggest', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(fields),
  });
}

// Suggest a benchmark Q/A built from one of the caller's own chat answers. The backend
// reconstructs the question / agent answer / SQL from the persisted exchange (owner-scoped);
// the client only sends the verdict + the correction. `payload` =
// { exchange_id, answer_is_correct, reference_answer?, missing_explanation?, category? }.
export function suggestBenchmarkFromChat(payload) {
  return request('/owismind-api/benchmark/suggest-from-chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// The caller's own benchmark suggestions (newest first). Returns
// { status, count, suggestions: [{ suggestion_id, source, question, reference_answer,
// answer_is_correct, category, language, status, created_at }] }. Owner-scoped server-side.
export function fetchMySuggestions() {
  return request('/owismind-api/benchmark/suggestions', { method: 'GET' });
}

// --- Benchmark results (consultation, ALL users) ------------------------------

// Benchmark scoring for ONE agent (its logical key) and an OPTIONAL run id (omit for
// the newest run). Returns { status, configured:bool, read_error?:str, results } where
// results = { run_id, runs, kpis, configs, categories, detail }. `configured:false`
// means no benchmark is wired for that agent; `read_error` is a soft degraded read.
export function fetchBenchmarkResults(agentKey, runId) {
  const qs = new URLSearchParams();
  qs.set('agent', agentKey);
  if (runId) qs.set('run_id', runId);
  return request('/owismind-api/benchmark/results?' + qs.toString(), { method: 'GET' });
}

// --- Admin: benchmark configuration + review (server-gated: 403 if not admin) ---

// Tables visible on one SQL connection, for the agent-profile benchmark table picker.
// Returns { tables: [name, ...], error? }.
export function adminListBenchmarkTables(connection) {
  return request('/owismind-api/admin/benchmark/tables?connection=' + encodeURIComponent(connection || ''), {
    method: 'GET',
  });
}

// Validate that a table carries the columns a benchmark needs. Returns
// { ok:bool, missing:[name, ...], error? }.
export function adminValidateBenchmarkTable(connection, table) {
  return request('/owismind-api/admin/benchmark/validate-table', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ connection, table }),
  });
}

// Set / clear an admin override on one scored question. `payload` =
// { agent, run_id, question_id, agent_key, mode, verdict:'correct'|'incorrect'|'', comment }.
// An empty verdict clears the override. Returns { status:'ok' } (re-fetch results to
// reflect the new effective verdict).
export function adminBenchmarkOverride(payload) {
  return request('/owismind-api/admin/benchmark/override', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// --- Evidence Studio ----------------------------------------------------------

// Interactive descriptor of one exchange's evidence: columns, filter chips
// (decomposed from the agent's stored SQL), advanced fragment and raw SQL.
// `available: false` + `reason` = degraded (raw SQL only).
export function fetchEvidenceMeta(exchangeId) {
  return request('/owismind-api/evidence/meta?exchange_id=' + encodeURIComponent(exchangeId));
}

// One bounded page of the evidence table. The payload NEVER carries SQL - see
// composables/evidenceModel.js buildRowsPayload for the exact shape.
export function fetchEvidenceRows(payload) {
  return request('/owismind-api/evidence/rows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// Bounded distinct values of one column (the filter-chip picker).
// `excludeId` (optional) is the server id of the chip being edited, so its own
// predicate never scopes its own picker. Returns { status, values, truncated }.
export function fetchEvidenceDistinct(exchangeId, column, excludeId) {
  let q = '?exchange_id=' + encodeURIComponent(exchangeId) + '&column=' + encodeURIComponent(column);
  if (excludeId != null) q += '&exclude_id=' + encodeURIComponent(excludeId);
  return request('/owismind-api/evidence/distinct' + q);
}

// Agents the admin has enabled, for any authenticated caller (chat-side picker +
// agent library). Returns { status, count, agents: [{ key, label, tagline,
// description, capabilities, tools, icon, badge }] } - opaque logical keys plus the
// admin-AUTHORED display profile (no raw agent_id / project_key ever leaks).
export function fetchAgents() {
  return request('/owismind-api/agents', { method: 'GET' });
}

// --- Monthly budget / usage ---------------------------------------------------

// The caller's own monthly budget status. Returns { status, usage: {...} } where usage
// carries spend_usd, the effective limit + its source (default / global temp boost /
// per-user override), remaining, whether enforcement is on / the user is blocked, the
// reset date and the lifetime counters. Strictly owner-scoped server-side.
export function fetchUsage() {
  return request('/owismind-api/usage', { method: 'GET' });
}

// --- Admin endpoints (server-gated: 403 if the caller is not an admin) --------

// Resolved storage config: { connection, project_key, table_prefix, namespace, tables }.
export function fetchAdminStorage() {
  return request('/owismind-api/admin/storage', { method: 'GET' });
}

// Every user who has opened the webapp: { users: [{ user_id, is_admin, ... }] }.
export function fetchAdminUsers() {
  return request('/owismind-api/admin/users', { method: 'GET' });
}

// Grant/revoke admin for a user; returns the refreshed users list.
export function setUserAdmin(userId, isAdmin) {
  return request('/owismind-api/admin/users/set-admin', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ user_id: userId, is_admin: isAdmin }),
  });
}

// --- Admin: agent whitelist configuration ------------------------------------

// DSS project keys this webapp can see: { projects: ["KEY", ...] }.
export function fetchAdminProjects() {
  return request('/owismind-api/admin/projects', { method: 'GET' });
}

// Agents available in one project: { project_key, agents: [{ agent_id, description }] }.
export function fetchAdminProjectAgents(projectKey) {
  return request('/owismind-api/admin/projects/' + encodeURIComponent(projectKey) + '/agents', {
    method: 'GET',
  });
}

// Currently enabled agents (admin view): { agents: [{ logical_key, project_key,
// agent_id, label, profile: { tagline, description, capabilities, tools, icon, badge } }] }.
export function fetchAdminAgents() {
  return request('/owismind-api/admin/agents', { method: 'GET' });
}

// Persist the enabled-agents selection; backend re-validates each entry against the
// live DSS listings and sanitizes the authored profile. `agents` is a list of
// { project_key, agent_id, profile? } where `profile` is the admin-authored display
// copy (tagline/description/capabilities/tools/icon/badge). Returns the stored selection.
export function saveAdminAgents(agents) {
  return request('/owismind-api/admin/agents', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ agents }),
  });
}

// --- Admin: monthly budgets / quotas -----------------------------------------

// Global budget config + every user's current-month usage & resolved limit.
// Returns { status, config, period_start, next_reset, users: [...] }.
export function fetchAdminBudget() {
  return request('/owismind-api/admin/budget', { method: 'GET' });
}

// Persist the GLOBAL budget config. `config` = { limit_usd, enabled, temp_limit_usd,
// temp_days } (a temp boost is stored only when both temp_limit_usd and temp_days are
// set, else cleared). Returns the refreshed overview.
export function saveAdminBudget(config) {
  return request('/owismind-api/admin/budget', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(config),
  });
}

// Set or clear a PER-USER monthly limit override for one, several or all users.
// `payload` = { user_ids:[...], clear:bool, limit_usd, expires_days, note }.
// (clear:true removes the override; expires_days absent/null = permanent.)
// Returns the refreshed overview.
export function saveAdminUserQuota(payload) {
  return request('/owismind-api/admin/budget/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
