# Backend - API reference

> Audience: backend developer, integrator. Last updated: 2026-06-18. Summary: complete
> catalogue of the `/owismind-api/*` endpoints (parameters, response shapes, error codes, HTTP statuses,
> auth and owner-scoping), grouped by domain.

All routes are mounted under the `/owismind-api` prefix (blueprint `owismind_api`, defined in
`api/routes.py`). The Vue 3 frontend consumes ONLY logical keys and structured data: it
never chooses a table, a connection, a SQL query, or a raw `agent_id`. The error contract
(stable, machine-readable codes, plus an HTTP status) is the API that the frontend maps to i18n messages.

## Cross-cutting conventions

Before detailing each route, here are the rules common to the whole API (unless stated otherwise in
the route's own section).

- **Response shape.** Success: `{"status": "ok", ...}` (most often a splat `**result` or
  `**meta` / `**page` of the business payload). Error: `{"status": "error", "error": "<code>"}` with an
  appropriate HTTP status. A `<code>` is always a stable string (`agent_not_enabled`,
  `storage_not_configured`, ...), never an internal detail.
- **Authentication.** Every route except `/ping` calls `resolve_identity(request.headers)`
  (`security/identity.py`). A failure raises `IdentityError`, turned into `401 {"error":
  "unauthenticated"}`. The identity (`user_id`) ALWAYS comes from the authenticated browser
  headers, never from the request body.
- **Storage guard.** Except for `/ping` and `/me`, every route refuses if `sql_config.is_configured()` is
  false, with `409 {"error": "storage_not_configured"}`. `/me` tolerates a pristine instance (it returns
  `needs_config: true`).
- **Agent whitelist.** The frontend sends an opaque logical key `agent_key` (shape `ag_<12 hex>`),
  resolved server-side to `(project_key, agent_id)` by `settings.resolve_enabled_agent`. A raw `agent_id`
  is never accepted.
- **Owner-scoping.** All chat and Evidence reads/writes are scoped by `user_id`. A forged id
  can at worst reveal only the caller's own data. For the real identity under which the
  SQL runs (run-as-user), see the [security model](../02-architecture/04-security-model.md).
- **Trace hooks.** Two blueprint-scoped hooks (`@api.before_request` / `@api.after_request`)
  log `method + path` then `status + duration` FOR `/owismind-api/*` only. Message content is
  NEVER logged (log hygiene): only the metadata flows.

The full chat turn (from `POST /chat/start` through the auto-opening of Evidence) is described in
sequence in the [runtime flows](../02-architecture/03-runtime-flows.md); this page remains a per-endpoint
reference catalogue.

## Route summary table

| Method | Path | Domain | Auth | Storage required |
|---|---|---|---|---|
| GET | `/ping` | health | no | no |
| GET, POST | `/me` | identity | yes | no (tolerates pristine) |
| GET | `/agents` | agents | yes | yes |
| POST | `/chat/start` | chat | yes | yes |
| GET | `/chat/poll` | chat | yes | yes |
| POST | `/chat/stop` | chat | yes | yes |
| POST | `/chat/feedback` | chat | yes | yes |
| GET | `/conversations` | conversations | yes | yes |
| GET | `/conversation` | conversations | yes | yes |
| GET | `/evidence/meta` | evidence | yes | yes |
| POST | `/evidence/rows` | evidence | yes | yes |
| GET | `/evidence/distinct` | evidence | yes | yes |
| GET | `/admin/storage` | admin | yes | yes + admin |
| GET | `/admin/users` | admin | yes | yes + admin |
| POST | `/admin/users/set-admin` | admin | yes | yes + admin |
| GET | `/admin/projects` | admin | yes | yes + admin |
| GET | `/admin/projects/<project_key>/agents` | admin | yes | yes + admin |
| GET, POST | `/admin/agents` | admin | yes | yes + admin |

## 1. Health and identity

### `GET /ping`

Liveness, **without auth**. Returns the backend's real Python version (via `sys.version.split()[0]`).
Deliberately minimal: it NEVER exposes the storage config (connection, project key, table
names), because `/ping` is reachable without authentication. The resolved config is readable only by an
admin via `/admin/storage`.

```json
{ "status": "ok", "python": "3.9.23" }
```

### `GET|POST /me`

Returns the caller's identity (resolved server-side from the headers), their admin status, and the config state.

```json
{
  "status": "ok",
  "user_id": "said.chaoui",
  "display_name": "Said",
  "groups": ["data_team"],
  "needs_config": false,
  "is_admin": true
}
```

- `needs_config = not sql_config.is_configured()`.
- `display_name` is DERIVED from the login (DSS does not provide a display name): the segment before the first
  `.`, title-cased per hyphen group (`said.chaoui` -> `Said`). It is a default; the frontend falls back to
  the raw login if absent.
- **GET vs POST side effect (crucial design).** `admin.record_user(identity)` (upsert into the
  users registry + election of the first admin) is called ONLY on POST. GET stays read-only: a
  prefetch or a GET scanner must neither create a user row nor win the "first to open =
  admin" election. The frontend issues POST once at init. Both methods return the same shape.
- `is_admin` is only resolved if the config is present (otherwise `false`). An exception from the
  registry is swallowed and returns `is_admin: false` rather than a 500.

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |

No `storage_not_configured` here (this route tolerates a pristine instance).

## 2. Agents (chat-side picker)

### `GET /agents`

Lists the agents the admin has enabled, for any authenticated caller. Feeds the chat agent picker.
Projects ONLY `key` (= the opaque `logical_key`) and `label`: never `agent_id` nor `project_key`
(whitelist).

```json
{
  "status": "ok",
  "count": 1,
  "agents": [{ "key": "ag_3f2a91c0e7b4", "label": "OWIsMind_orchestrator" }]
}
```

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `storage_not_configured` | 409 | storage not configured |
| `storage_unavailable` | 500 | failure reading the settings |

## 3. Chat

### `POST /chat/start`

Starts an agent run in a background worker and returns an opaque `run_id`. This is the chat's main entry
point. JSON body:

| Field | Type | Required | Bounds / default |
|---|---|---|---|
| `session_id` | str | yes | non-empty after strip, <= 128 (`MAX_SESSION_ID_LENGTH`) |
| `message` | str | yes | non-empty after strip, <= 8000 (`MAX_MESSAGE_LENGTH`) |
| `agent_key` | str | yes | opaque, <= 64 (`MAX_AGENT_KEY_LENGTH`), resolved against the whitelist |
| `history_limit` | int | no | clamped `[10, 50]`, default 20 (number of MESSAGES replayed); never raises |
| `parent_exchange_id` | str | no | conversation tree edge; invalid value -> `None`; never raises |
| `mode` | str | no | `eco` / `medium` / `high` (`context.MODEL_MODES`); unknown or absent -> `medium` |
| `webapp_lang` | str | no | `fr` / `en` (`context._LANG_LABEL`); unknown or absent -> `None` |
| `screen_context` | dict | no | sanitized (see 6); otherwise `None` |

Exact server-side sequence (the order of the guards matters for error mapping):

1. `resolve_identity` -> `401` on failure.
2. `validate_chat_start_request(...)` (validates `session_id` + `message` + `agent_key`) -> `400 <code>`
   if invalid.
3. `validate_history_limit` and `validate_optional_exchange_id` read separately from the body (the main
   validator stays unchanged).
4. Storage guard -> `409 storage_not_configured`.
5. **Whitelist**: `settings.resolve_enabled_agent(agent_key)`. `None` (forged or stale key) ->
   `404 agent_not_enabled`. On success: `project_key` + `agent_id`.
6. Content-free log: `user_id`, `session_id`, `agent_key`, `msg_len` (never the content).
7. **Admission gate BEFORE any write**: `stream_manager.can_accept(user_id)` returns
   `(ok, reason)`. `reason == "rate_limited"` -> `429`, otherwise (`"busy"`) -> `503`.
8. **Phase one (write)**: `ensure_chat_table()` then `chat_v5.save_user_message(...)` returns an
   `exchange_id` (generated in Python, without readback). Failure -> `500 storage_unavailable`.
9. Resolution of `mode` (default `medium`), `webapp_lang`, and detection of THIS turn's reply language:
   `context.detect_prompt_language(message, default=webapp_lang or "fr")` on the RAW message.
10. Construction of the per-turn suffix `context.build_user_suffix(...)`, appended at the END of the
    current message (the agent is stateless between calls and honors the end of the prompt better).
11. `screen_context = _sanitize_screen_context(body.get("screen_context"))`.
12. `stream_manager.start_run(...)` (bounded worker). `CapacityError` -> `503 busy`; any other exception ->
    `500 agent_unavailable`.
13. Success: `{"status": "ok", "run_id": ..., "exchange_id": ...}`. The `run_id` is the only
    opaque handle on the frontend side; `agent_id` stays server-side.

```json
{ "status": "ok", "run_id": "a1b2c3d4e5f6...", "exchange_id": "9f8e7d6c..." }
```

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `missing_session_id`, `empty_session_id`, `session_id_too_long`, `missing_message`, `message_too_long`, `empty_message`, `missing_agent_key`, `empty_agent_key`, `agent_key_too_long`, `invalid_payload` | 400 | failure of `validate_chat_start_request` |
| `storage_not_configured` | 409 | storage not configured |
| `agent_not_enabled` | 404 | `agent_key` not resolved by the whitelist |
| `rate_limited` | 429 | per-user spacing (< 1 s since the last start) |
| `busy` | 503 | global concurrent-runs cap reached (8) |
| `storage_unavailable` | 500 | failure of phase one (message persistence) |
| `agent_unavailable` | 500 | worker start failure (other than `CapacityError`) |

> Note: `rate_limited` (429) and `busy` (503) are distinct by design. 429 = per-user spacing (1 s),
> 503 = global concurrent cap (8). The distinction serves client-side retry.

### `GET /chat/poll`

Returns the run's normalized events from a cursor (live timeline). The transport is
streaming-by-polling: the worker runs in the background, the frontend polls `/chat/poll` every
~500 ms. The full detail of the run lifecycle and the cursor is in
[Streaming and runs](03-streaming-and-runs.md).

Query parameters:

| Param | Type | Default / bounds |
|---|---|---|
| `run_id` | str | required; <= 64 (`_MAX_RUN_ID_LENGTH`) otherwise `400 invalid_run_id` |
| `cursor` | int | default 0; non-int or < 0 normalized to 0 |

`stream_manager.poll(run_id, user_id, cursor)`. **Owner-scope**: `None` (unknown run OR belonging to
another user) -> `404 run_not_found`, without revealing which.

```json
{
  "status": "ok",
  "events": [ { "type": "agent_event" }, { "type": "answer_delta" } ],
  "cursor": 12,
  "done": false,
  "error": null
}
```

- `events`: the new normalized events since the cursor. The possible types are `run_started`,
  `agent_event`, `answer_delta`, `generated_sql`, `usage_summary`, `final_answer`, `run_done`, `error`.
- `cursor`: the next cursor to send (= total number of events already produced).
- `done`: the run is finished.
- `error`: terminal code (`run_<reason>`, `agent_unavailable`, ...) or `null`.

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `invalid_run_id` | 400 | `run_id` empty or > 64 |
| `run_not_found` | 404 | unknown run or another user's run (owner-scope) |

### `POST /chat/stop`

Requests a cooperative stop of an in-flight run belonging to the caller. Body `{"run_id": "..."}`.

`run_id` non-str / empty / > 64 -> `400 invalid_run_id`. `stream_manager.request_stop(run_id, user_id)`
false -> `404 run_not_found` (unknown run, already finished/evicted, or another user's run: a no-op that the
client treats as "already done"). Success `{"status": "ok"}`. The identity comes from the headers, never from the
body. The worker sees the request between two streamed chunks, persists the accumulated PARTIAL response, and
ends the run with a terminal `stopped` event (not an error).

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `invalid_run_id` | 400 | `run_id` non-str, empty or > 64 |
| `run_not_found` | 404 | unknown run, already finished, or another user's run |

### `POST /chat/feedback`

Persists feedback (thumbs up/down + reasons + comment) on a message belonging to the caller. Body validated by
`validate_feedback`, which returns `(exchange_id, rating, reasons, comment)`:

| Field | Type | Rule |
|---|---|---|
| `exchange_id` | str | required, non-empty, <= 128; otherwise `invalid_exchange_id` |
| `rating` | int / null | `0` (down), `1` (up) or `null` (clear); a **bool is rejected explicitly** (`True`/`False` are int subtypes) -> `invalid_rating` |
| `reasons` | list | filtered on `ALLOWED_FEEDBACK_REASONS = ("incorrect", "incomplete", "off_topic", "other")`; cap 8 (`MAX_FEEDBACK_REASONS`) |
| `comment` | str | truncated to 2000 (`MAX_FEEDBACK_COMMENT_CHARS`) |

`chat_v5.save_feedback(...)` is **owner-scope** (`WHERE exchange_id AND user_id`): rating someone else's
exchange is a silent no-op. Success `{"status": "ok"}`.

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `storage_not_configured` | 409 | storage not configured |
| `invalid_payload`, `invalid_exchange_id`, `invalid_rating` | 400 | failure of `validate_feedback` |
| `storage_unavailable` | 500 | write failure |

## 4. Conversations (sidebar)

### `GET /conversations`

Paginated (keyset) list of the signed-in user's conversations, names only, never a message body,
strictly owner-scoped.

| Param | Type | Default / bounds |
|---|---|---|
| `limit` | int | clamped `[1, 60]`, default 30 (`validate_conversations_limit`) |
| `cursor` | str | opaque base64 token; defensively bounded to <= 512 chars otherwise `400 invalid_cursor` |

`chat_v5.list_conversations(user_id, cursor_token, limit)`. The response is a splat of the `page` dict (which
typically includes `conversations`, `has_more`, and the next cursor).

```json
{
  "status": "ok",
  "conversations": [
    { "session_id": "...", "title": "Real revenue of account X", "last_at": "2026-06-18T09:12:00Z" }
  ],
  "has_more": false
}
```

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `storage_not_configured` | 409 | storage not configured |
| `invalid_cursor` | 400 | cursor > 512 chars |
| `storage_unavailable` | 500 | listing failure |

> IN FLUX: the `title` is DERIVED server-side from the first message (cleaned, truncated to `CONV_TITLE_MAXLEN`,
> actual value 56 in the code, and not 140 as some stale `docs/` documents indicate). There is
> no `title` column in the database yet: the AI-title feature is deferred.

### `GET /conversation`

All the messages of ONE of the caller's sessions, in chronological order, bounded. Lazily loaded on click
of a conversation in the sidebar.

| Param | Type | Rule |
|---|---|---|
| `session_id` | str | strip, non-empty, <= 128 (`MAX_SESSION_ID_LENGTH`) otherwise `400 invalid_session_id` |

`chat_v5.messages_for_session(user_id, session_id)` -> read strictly scoped to `(user_id, session_id)`,
bounded by an absolute row cap (`SESSION_MESSAGES_CAP = 500`). The `rows` follow the stable column order
`chat_v5._COLUMNS` (`exchange_id, session_id, user_id, user_display_name, user_groups, user_text,
assistant_text, generated_sql, agent_key, created_at, answered_at, feedback_rating, feedback_reasons,
feedback_comment, parent_exchange_id, input_tokens, output_tokens, total_tokens, estimated_cost`), so
that the frontend reuses a single row->message mapper. The data model detail is in
[Storage and data model](04-storage-and-data-model.md).

```json
{ "status": "ok", "session_id": "...", "count": 4, "rows": [ /* ... */ ] }
```

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | identity not resolvable |
| `storage_not_configured` | 409 | storage not configured |
| `invalid_session_id` | 400 | `session_id` empty or > 128 |
| `storage_unavailable` | 500 | load failure |

## 5. Evidence Studio (owner-scope, read-only)

The three `/evidence/*` routes share the `_evidence_guard()` guard, which chains: (1)
`resolve_identity` -> `401 unauthenticated`; (2) `is_configured()` -> `409 storage_not_configured`;
(3) `ensure_chat_table()` -> `500 storage_unavailable`; (4) **per-user rate gate**
`evidence_throttle.can_accept(user_id)` -> `429 rate_limited`. The token bucket
(`EVIDENCE_BUCKET_CAPACITY = 15` tokens, `EVIDENCE_REFILL_PER_SEC = 10.0`) absorbs the legitimate burst
(the meta + rows pair of the auto-opening) but refuses a scripted burst that would pin the threads of the
single-process backend. The body of the Evidence routes NEVER carries SQL.

### `GET /evidence/meta`

Interactive descriptor of an exchange's Evidence (badge, sources, chips, computation, captured result,
drill, collapsed SQL) or a degraded shape. The caller sends ONLY `exchange_id` (via
`validate_required_exchange_id`); table, connection, SQL, and dataset matching are all resolved
server-side. Owner-scope: another user's exchange returns 404.

`evidence_service.evidence_meta(user_id, exchange_id)`. An `EvidenceError(code, status)` returns that
`code` + `status`; any other exception -> `500 evidence_unavailable`. The route also enriches the
artifacts (chart / table / kpi) via `artifacts_storage.read_artifacts` + `chart_payload`, on a
best-effort basis: a failure degrades to `artifacts: []`, never a 500. The shaping of charts/KPIs and the
construction of the Chart.js payload are detailed in
[Evidence Studio and artifacts](05-evidence-and-artifacts.md).

| Param | Type | Rule |
|---|---|---|
| `exchange_id` | str | required, non-empty, <= 128 otherwise `400 invalid_exchange_id` |

| Error code | HTTP status | Condition |
|---|---|---|
| `unauthenticated` | 401 | guard |
| `storage_not_configured` | 409 | guard |
| `storage_unavailable` | 500 | table bootstrap |
| `rate_limited` | 429 | Evidence token bucket |
| `invalid_exchange_id` | 400 | invalid `exchange_id` |
| `<EvidenceError.code>` | `<EvidenceError.status>` | Evidence business error (code and status carried by the exception) |
| `evidence_unavailable` | 500 | unexpected exception |

### `POST /evidence/rows`

A bounded page of the evidence table, rebuilt from STRUCTURED filters (the body never carries
SQL). Validated by `validate_evidence_rows_request`, which returns `(exchange_id, filters,
kept_ids, include_advanced, page, sort, drill, table)`:

| Field | Rule |
|---|---|
| `exchange_id` | required, via `validate_required_exchange_id` |
| `filters` | list <= 20 (`MAX_EVIDENCE_FILTERS`); each item `{column, op, values}`; `op` in `("=", "IN")` (`EVIDENCE_FILTER_OPS`) otherwise `invalid_filter_op`; `values` a list of 1..50 (`MAX_EVIDENCE_IN_VALUES`, exactly 1 for `"="`); each value via `_validate_evidence_value` (bool accepted on a boolean column, NaN/Inf rejected -> `invalid_filter_value`, str/number bounded to 500 chars -> `filter_value_too_long`) |
| `kept_ids` | list <= 100 (`MAX_EVIDENCE_KEPT_IDS`) of integers >= 0; bool rejected -> `invalid_kept_ids` |
| `include_advanced` | coerced to bool |
| `page` | CLAMPED `[0, 20]` (`MAX_EVIDENCE_PAGE`); never raises (bounds the cost of the OFFSET sort) |
| `sort` | `{column, dir}`; malformed -> `None` (graceful degradation); `dir` normalized `asc` / `desc` |
| `drill` | list <= 8 (`MAX_EVIDENCE_DRILL`) of `{column, value}`; a malformed drill RAISES `invalid_drill` (a silently dropped drill would show the NON-drilled page = a scope honesty violation, not a cosmetic degradation); `value` may be `None` -> IS NULL test |
| `table` | optional source selector <= 256 chars (`MAX_EVIDENCE_TABLE_CHARS`); malformed -> `None`; the service matches it against the set of matched tables of the stored SQL (never an arbitrary table) |

`evidence_service.evidence_rows(...)`. Response = splat of the `result` (page of rows + pagination meta).

| Error code | HTTP status | Condition |
|---|---|---|
| guards (`unauthenticated`, `storage_not_configured`, `storage_unavailable`, `rate_limited`) | 401 / 409 / 500 / 429 | `_evidence_guard()` |
| `invalid_payload`, `invalid_exchange_id`, `invalid_filters`, `invalid_filter_column`, `invalid_filter_op`, `invalid_filter_values`, `invalid_filter_value`, `filter_value_too_long`, `invalid_kept_ids`, `invalid_drill` | 400 | failure of `validate_evidence_rows_request` |
| `<EvidenceError.code>` | `<EvidenceError.status>` | Evidence business error |
| `evidence_unavailable` | 500 | unexpected exception |

### `GET /evidence/distinct`

Bounded distinct values of ONE column (the value picker of the filter chips).

| Param | Type | Rule |
|---|---|---|
| `exchange_id` | str | required, via `validate_required_exchange_id` |
| `column` | str | shape only, via `validate_evidence_column` (<= 128, otherwise `invalid_filter_column`); the EXISTENCE is re-validated against the live schema by the service |
| `exclude_id` | int | optional; server id of the chip currently being edited (its own predicate must not scope its own picker); malformed or < 0 -> `None` |

`evidence_service.evidence_distinct(user_id, exchange_id, column, exclude_id)`.

| Error code | HTTP status | Condition |
|---|---|---|
| guards (`unauthenticated`, `storage_not_configured`, `storage_unavailable`, `rate_limited`) | 401 / 409 / 500 / 429 | `_evidence_guard()` |
| `invalid_exchange_id`, `invalid_filter_column` | 400 | validation |
| `<EvidenceError.code>` | `<EvidenceError.status>` | Evidence business error |
| `evidence_unavailable` | 500 | unexpected exception |

## 6. screen_context (sanitization, on `/chat/start`)

The optional `screen_context` field of `POST /chat/start` is a bounded view of what the
user is looking at (the exchange rendered in the Evidence panel and its tab). `_sanitize_screen_context`
(in `api/routes.py`):

- `raw` non-dict or without a truthy `open` -> `None`.
- `exchange_id` must be str or int (bool excluded) otherwise `None`.
- Returns `{"open": True, "exchange_id": str(exch)[:128], "active_tab": tab if in _SCREEN_TABS else
  None}`, with `_SCREEN_TABS = ("evidence", "chart", "table")`.

The worker reads the artifacts of this exchange OWNER-SCOPE, so a forged id can only reveal the
caller's own data.

## 7. Admin

The `/admin/*` routes share `_admin_guard()`: (1) `resolve_identity` -> `401 unauthenticated`;
(2) `is_configured()` -> `409 storage_not_configured`; (3) `admin.is_admin(user_id)` false ->
`403 forbidden` (a failure of the check -> `500 storage_unavailable`). The application admin (the `is_admin`
flag in the table) is distinct from DSS rights: see the
[security model](../02-architecture/04-security-model.md).

### `GET /admin/storage`

Resolved storage config, via `sql_config.storage_status()`: `configured`, `connection`,
`project_key` (+ `project_key_source`), `table_prefix` (+ `table_prefix_input` / `table_prefix_ignored`),
`namespace`, `traces_dataset`, and the physical names computed in `tables` (`chat` -> `webapp_chat_v5`,
`users` -> `webapp_users_v1`, `settings` -> `webapp_settings_v1`, `usage_monthly` ->
`webapp_usage_monthly_v1`).

```json
{ "status": "ok", "storage": { "configured": true, "connection": "SQL_owi", "tables": { "chat": "OWISMIND_DEV_owismind_webapp_chat_v5" } } }
```

### `GET /admin/users`

`{"status": "ok", "count": ..., "users": [...]}` via `admin.list_users()`. `storage_unavailable` (500)
on query failure.

### `POST /admin/users/set-admin`

Sets or removes a user's admin flag. Body `{"user_id": "...", "is_admin": true|false}`.

- empty `user_id` -> `400 missing_user_id`.
- **Anti-lockout guard**: removing the flag (`is_admin` false) from an admin while `admin.count_admins()
  <= 1` -> `400 cannot_remove_last_admin`.
- Otherwise `admin.set_admin(target, value)` then returns the up-to-date list (`{"status": "ok", "users":
  [...]}`).

| Error code | HTTP status | Condition |
|---|---|---|
| guards (`unauthenticated`, `storage_not_configured`, `forbidden`) | 401 / 409 / 403 | `_admin_guard()` |
| `missing_user_id` | 400 | empty `user_id` |
| `cannot_remove_last_admin` | 400 | removal of the last admin |
| `storage_unavailable` | 500 | write failure |

### `GET /admin/projects`

`discovery.list_project_keys()` -> `{"status": "ok", "count": ..., "projects": [...]}`. Failure ->
`500 discovery_unavailable`.

### `GET /admin/projects/<project_key>/agents`

Lists a project's agents (id + description), for the admin picker. The `<project_key>` is
**re-validated** against the list of visible projects BEFORE the listing (`if project_key not in
set(discovery.list_project_keys())` -> `404 project_not_found`): an admin cannot probe an
arbitrary or hidden key.

```json
{ "status": "ok", "project_key": "OWISMIND_DEV", "count": 2, "agents": [{ "agent_id": "agent:bHrWLyOL", "description": "SalesDrive_revenue_expert" }] }
```

| Error code | HTTP status | Condition |
|---|---|---|
| guards | 401 / 409 / 403 | `_admin_guard()` |
| `project_not_found` | 404 | `project_key` not visible |
| `discovery_unavailable` | 500 | discovery failure |

### `GET|POST /admin/agents`

Reads or writes the whitelist of enableable agents.

- **GET**: the stored selection (admin view, includes `project_key` / `agent_id`) -> `{"status": "ok",
  "count": ..., "agents": [...]}`.
- **POST**: persists `{"agents": [{"project_key": ..., "agent_id": ...}, ...]}`. `agents` non-list ->
  `400 invalid_payload`; > 50 (`MAX_ENABLED_AGENTS`) -> `400 too_many_agents`. Each requested agent is
  **RE-VALIDATED server-side** against the live DSS listings (visible project AND agent actually present);
  a missing agent is skipped (logged), not an error. The `logical_key` is derived from a STABLE hash of
  `project_key:agent_id` by `_logical_key` (`"ag_" + sha1(...)[:12]`): stable so that re-saving keeps
  the same key (existing conversations referencing `agent_key` stay valid), opaque so that the
  frontend never receives a raw `agent_id`. Persistence via `settings.set_enabled_agents(enabled,
  updated_by=user_id)`.

| Error code | HTTP status | Condition |
|---|---|---|
| guards | 401 / 409 / 403 | `_admin_guard()` |
| `invalid_payload` | 400 | `agents` non-list (POST) |
| `too_many_agents` | 400 | > 50 agents (POST) |
| `storage_unavailable` | 500 | read failure (GET) or write failure (POST) |

## Consolidated error-code catalogue

| Code | Status | Emitting endpoints |
|---|---|---|
| `unauthenticated` | 401 | all except `/ping` |
| `storage_not_configured` | 409 | all except `/ping` and `/me` |
| `forbidden` | 403 | `/admin/*` (non-admin) |
| `invalid_payload` | 400 | `/chat/start`, `/chat/feedback`, `/evidence/rows`, `/admin/agents` |
| `missing_*` / `empty_*` / `*_too_long` (chat fields) | 400 | `/chat/start` |
| `invalid_run_id` | 400 | `/chat/poll`, `/chat/stop` |
| `invalid_cursor` | 400 | `/conversations` |
| `invalid_session_id` | 400 | `/conversation` |
| `invalid_exchange_id`, `invalid_rating` | 400 | `/chat/feedback`, `/evidence/*` |
| `invalid_filter_*`, `filter_value_too_long`, `invalid_kept_ids`, `invalid_drill` | 400 | `/evidence/rows`, `/evidence/distinct` |
| `missing_user_id`, `cannot_remove_last_admin` | 400 | `/admin/users/set-admin` |
| `too_many_agents` | 400 | `/admin/agents` |
| `agent_not_enabled` | 404 | `/chat/start` |
| `run_not_found` | 404 | `/chat/poll`, `/chat/stop` |
| `project_not_found` | 404 | `/admin/projects/<key>/agents` |
| `rate_limited` | 429 | `/chat/start`, `/evidence/*` |
| `busy` | 503 | `/chat/start` |
| `storage_unavailable` | 500 | most storage-backed routes |
| `agent_unavailable` | 500 | `/chat/start` |
| `evidence_unavailable` | 500 | `/evidence/*` |
| `discovery_unavailable` | 500 | `/admin/projects*` |

## See also
- [Backend - overview and structure](01-overview-and-structure.md) - blueprint, sub-packages, cross-cutting guards.
- [Backend - streaming and run lifecycle](03-streaming-and-runs.md) - `/chat/poll`, cursor, admission, caps and stop.
- [Backend - storage and data model](04-storage-and-data-model.md) - `webapp_*` tables, `_COLUMNS`, conversation tree.
- [Backend - Evidence Studio and artifacts](05-evidence-and-artifacts.md) - meta, capture, levels, chart_payload.
- [Backend - security and validation](06-security-and-validation.md) - payload validation, SQL safety, read-only guards.
- [Frontend - communication with the backend](../03-frontend/04-backend-communication.md) - the same contract seen from the client side (call catalogue, polling, i18n mapping of the codes).
- [Architecture - runtime flow](../02-architecture/03-runtime-flows.md) - complete sequence of a chat turn (the diagram's focal point).
- [Architecture - security model](../02-architecture/04-security-model.md) - run-as-user, owner-scoping, agent whitelist.
