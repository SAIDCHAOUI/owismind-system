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
// Usage analytics: record backend failures (best-effort; track never throws).
import { track } from './track.js'

function backendUrl(path) {
  const resolver = window.getWebAppBackendUrl;
  if (typeof resolver !== 'function') {
    throw new Error('getWebAppBackendUrl unavailable (run inside the DSS webapp)');
  }
  return resolver(path);
}

// Emit an error_backend usage event for a failed request. Skipped for /track itself
// (a tracking failure must not track itself) and for /chat/poll (fires every 500ms
// during a run - it would flood). The model-level limiter caps this to 10 per session.
// Only the route path is recorded: the query string is stripped because some GET
// endpoints carry user-typed search text in it (e.g. distinct ?q=), which must never
// reach the analytics table.
function trackBackendError(path, status) {
  const p = (path || '').split('?')[0];
  if (p.indexOf('/track') !== -1 || p.indexOf('/chat/poll') !== -1) return;
  track('error_backend', { path: p, status });
}

// Single fetch helper: same-origin credentials (so DSS auth cookies travel),
// JSON in/out, and a stable error code surfaced from the backend when present.
async function request(path, options) {
  const opts = options || {};
  let res;
  try {
    res = await fetch(backendUrl(path), {
      credentials: 'same-origin',
      ...opts,
      // BEGIN impersonation (temporary) - carry the X-OWI-Impersonate header (empty
      // object when not impersonating). Server honours it only for real admins.
      headers: { Accept: 'application/json', ...impersonationHeaders(), ...(opts.headers || {}) },
      // END impersonation (temporary)
    });
  } catch (e) {
    // Network / resolver failure (no HTTP response): status 0. Rethrow unchanged.
    trackBackendError(path, 0);
    throw e;
  }
  if (!res.ok) {
    let code = 'http_' + res.status;
    try {
      const data = await res.json();
      if (data && data.error) code = data.error;
    } catch (e) {
      /* ignore non-JSON error bodies */
    }
    trackBackendError(path, res.status);
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

// Benchmark scoring for ONE agent (its logical key) and an OPTIONAL benchmark id (omit
// for the agent's newest benchmark). A benchmark is a named, unique evaluation campaign
// that ACCUMULATES runs over time; the score is over ALL questions ever added, using the
// latest attempt of each. Returns { status, configured:bool, read_error?:str, results }
// where results = { benchmark_id, benchmark_name, benchmarks, kpis, configs, categories,
// detail }. `benchmarks` is the selector (one entry per benchmark of this agent); each
// `detail` row now carries its own run_id, attempt_no, delta, attempts[], expected_sql,
// expected_tool and actual_tools (latest attempt per question x config). `configured:false`
// means no benchmark is wired for that agent; `read_error` is a soft degraded read.
export function fetchBenchmarkResults(agentKey, benchmarkId) {
  const qs = new URLSearchParams();
  qs.set('agent', agentKey);
  if (benchmarkId) qs.set('benchmark_id', benchmarkId);
  return request('/owismind-api/benchmark/results?' + qs.toString(), { method: 'GET' });
}

// Full detail of ONE benchmark attempt (any signed-in user), loaded on demand when a user expands a
// question: the complete agent answer + the SQL the agent actually generated + each query's captured
// result table. `keys` = { run_id, question_id, agent_key, mode }. Returns
// { configured, read_error?, detail:{ found, answer_text, sql_items:[...] } }.
export function fetchBenchmarkAttempt(agentKey, keys) {
  const k = keys || {};
  const qs = new URLSearchParams();
  qs.set('agent', agentKey);
  qs.set('run_id', k.run_id || '');
  qs.set('question_id', k.question_id || '');
  qs.set('agent_key', k.agent_key || '');
  qs.set('mode', k.mode || '');
  return request('/owismind-api/benchmark/attempt?' + qs.toString(), { method: 'GET' });
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

// One bounded window of the evidence table. The payload NEVER carries SQL - see
// composables/evidenceModel.js buildRowsPayload for the exact shape (limit/offset
// pagination + an optional full-text q over all columns). Returns
// { status, rows, has_more, offset }.
export function fetchEvidenceRows(payload) {
  return request('/owismind-api/evidence/rows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// DB-computed aggregation over the FULL filtered set of ONE exchange's evidence table
// (the totals bar + the Analyze mini-pivot). The payload carries the SAME scope as
// /evidence/rows (see composables/evidenceModel.js buildEvidenceAggregatePayload: chips as
// filters + kept ids, include_advanced, optional drill/table/q) WITHOUT limit/offset/sort,
// PLUS { group, measures, limit } - never SQL. Returns { status, rows, totals, truncated }
// identical to /source/aggregate:
//   - group null: rows = [{ m0, m1, ... }] (one row), totals = null.
//   - group set:  rows = [{ key, m0, ... }] (ordered), totals = { m0, ... } over the
//     same filter (for exact shares), truncated = true when the group cap bit.
export function fetchEvidenceAggregate(payload) {
  return request('/owismind-api/evidence/aggregate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// Bounded distinct values of one column (the CASCADING filter-chip picker). POST (was
// GET): the picker now carries the same scope /evidence/rows does, so it only offers
// values compatible with the OTHER active filters. `excludeId` (optional) is the server
// id of the chip being edited, so its own predicate never scopes its own picker.
// `search` (optional) is the picker's own search on THAT column. `extra` (optional) is
// the scope object built by composables/evidenceModel.js buildEvidenceDistinctScope
// ({ filters, kept_ids, include_advanced, drill?, scope_q? }) - the OTHER active chips
// minus the one being edited. Omit `extra` for the legacy (no-cascade) picker. Returns
// { status, values, truncated }.
export function fetchEvidenceDistinct(exchangeId, column, excludeId, search, extra) {
  const e = extra || {};
  const body = { exchange_id: exchangeId, column };
  if (excludeId != null) body.exclude_id = excludeId;
  if (search) body.q = search;
  if (e.filters) body.filters = e.filters;
  if (e.kept_ids) body.kept_ids = e.kept_ids;
  if (e.include_advanced != null) body.include_advanced = e.include_advanced;
  if (e.drill) body.drill = e.drill;
  if (e.scope_q) body.scope_q = e.scope_q;
  return request('/owismind-api/evidence/distinct', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// --- Source Data Explorer -----------------------------------------------------

// Descriptor of one of an agent's configured source datasets: its label + columns.
// `agentKey` is the OPAQUE logical key from /agents, `sourceId` the integer index in
// that agent's `sources` list; the server resolves both to a dataset (never named by
// the client). Returns { status, label, columns: [{ name, type }] }.
export function fetchSourceMeta(agentKey, sourceId) {
  const q =
    '?agent=' + encodeURIComponent(agentKey) + '&source=' + encodeURIComponent(sourceId);
  return request('/owismind-api/source/meta' + q);
}

// One bounded window of a source dataset. The payload NEVER names a table/connection -
// see composables/sourceModel.js buildSourceRowsPayload for the exact shape (agent
// key + integer source id + plain-text search + structured filters + limit + offset +
// sort). Returns { status, rows, has_more, offset }.
export function fetchSourceRows(payload) {
  return request('/owismind-api/source/rows', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// DB-computed aggregation over the FULL filtered set of a source dataset (the totals
// bar + the Analyze mini-pivot). The payload NEVER names a table/connection - see
// composables/sourceModel.js buildSourceAggregatePayload for the exact shape (agent
// key + integer source id + plain-text search + structured filters + optional group +
// measures + group-rows limit). Returns { status, rows, totals, truncated }:
//   - group null: rows = [{ m0, m1, ... }] (one row), totals = null.
//   - group set:  rows = [{ key, m0, ... }] (ordered), totals = { m0, ... } over the
//     same filter (for exact shares), truncated = true when the group cap bit.
export function fetchSourceAggregate(payload) {
  return request('/owismind-api/source/aggregate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// Bounded distinct values of one column of a source dataset (the CASCADING filter
// picker). POST (was GET): the picker now carries the same scope /source/rows does, so it
// only offers values compatible with the OTHER active filters. `search` (optional) is the
// picker's own search on THAT column. `filters` (optional) are the OTHER active chips
// (already shaped {column, op, values}, minus the one being edited) and `scopeQ` the
// table-level search over ALL columns - together they make the picker cascade. Omit both
// for the legacy (no-cascade) picker. Returns { status, values, truncated }.
export function fetchSourceDistinct(agentKey, sourceId, column, search, filters, scopeQ) {
  const body = { agent: agentKey, source: sourceId, column };
  if (search) body.q = search;
  if (filters && filters.length) body.filters = filters;
  if (scopeQ) body.scope_q = scopeQ;
  return request('/owismind-api/source/distinct', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
}

// The project's SQL dataset NAMES, for the agent-profile source picker (admin only,
// server-gated: 403 if the caller is not an admin). A listing failure degrades to an
// empty list + an `error` field, never a 500. Returns { datasets: [name, ...], error? }.
export function adminListSourceDatasets() {
  return request('/owismind-api/admin/sources/datasets', { method: 'GET' });
}

// Agents the admin has enabled, for any authenticated caller (chat-side picker +
// agent library). Returns { status, count, agents: [{ key, label, tagline,
// description, capabilities, tools, icon, badge }] } - opaque logical keys plus the
// admin-AUTHORED display profile (no raw agent_id / project_key ever leaks).
export function fetchAgents() {
  return request('/owismind-api/agents', { method: 'GET' });
}

// --- Help & Support hub (general feedback + agent-on-data requests) ----------

// The caller's own DSS projects, for the "request an agent" project picker. The
// server resolves them via impersonation (the real DSS user behind the browser auth
// headers) - bounded, on-demand only, never a scan of every project on the instance.
// Returns { ok:true, projects:[{key,label}] } or { ok:false, reason }. A `false` or
// EMPTY response means the picker must fall back to manual entry - see
// composables/catalogFallback.js for the exact rule.
export function getCatalogProjects() {
  return request('/owismind-api/catalog/projects', { method: 'GET' });
}

// The SQL datasets of ONE of the caller's own DSS projects (same impersonation
// mechanism as getCatalogProjects, called only once a project is picked). Returns
// { ok:true, datasets:[{dataset, table, connection, type}] } or { ok:false, reason }.
export function getCatalogDatasets(projectKey) {
  return request('/owismind-api/catalog/datasets?project_key=' + encodeURIComponent(projectKey || ''), {
    method: 'GET',
  });
}

// Submit a general feedback item (bug / wrong answer / feature / UX / perf / data /
// routing / other). `payload` = { category?, message, linked_session_id? }. Returns
// { status:'ok', feedback_id }; throws 'impersonation_read_only' (403 - the server
// blocks writes while an admin is viewing as another user, same fence as every other
// WRITE route) or the backend's stable error code on any other non-2xx.
// Named `submitGeneralFeedback` (not `submitFeedback`) to avoid colliding with the
// existing per-message thumbs-up/down `submitFeedback` above.
export function submitGeneralFeedback(payload) {
  return request('/owismind-api/feedback/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// The caller's own feedback history (newest first), including the admin status /
// response once set. Returns { status:'ok', items:[...] }. Owner-scoped server-side.
export function getMyFeedback() {
  return request('/owismind-api/feedback/mine', { method: 'GET' });
}

// Submit a "request a new agent on my data" form. `payload` = { project_key,
// project_label, datasets:[{dataset, table, connection}], business_case, use_cases,
// importance }. `datasets` may be an empty array (manual-catalog fallback still fills
// each entry the same shape - see composables/catalogFallback.js). Returns
// { status:'ok', request_id }; throws 'impersonation_read_only' (403, same write
// fence as submitGeneralFeedback) or the backend's stable error code.
export function submitAgentRequest(payload) {
  return request('/owismind-api/agent-request/submit', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}

// The caller's own agent requests (newest first), including the admin status /
// response once set. Returns { status:'ok', items:[...] }. Owner-scoped server-side.
export function getMyAgentRequests() {
  return request('/owismind-api/agent-request/mine', { method: 'GET' });
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
