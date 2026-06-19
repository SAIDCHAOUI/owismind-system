Here is the complete technical review of the OWIsMind webapp backend.

---

## 1. Complete API Route List

All routes mount under `/owismind-api` via `Blueprint("owismind_api", url_prefix="/owismind-api")` in `api/routes.py`, registered via `register_routes(app)` called from the thin `webapps/webapp-owismind-ai-agents/backend.py` bootstrap.

| Method | Path | Purpose |
|---|---|---|
| GET | `/owismind-api/ping` | Liveness probe; returns Python version; no auth, no storage config exposed |
| GET, POST | `/owismind-api/me` | Resolve caller identity + admin flag. POST writes the user row (first-admin bootstrap); GET is read-only |
| GET | `/owismind-api/usage` | Caller's own monthly budget status (spend / limit / source / blocked); owner-scoped; rate-limited via `evidence_throttle.usage_can_accept` |
| GET | `/owismind-api/agents` | Enabled agents (opaque logical key + label + admin-authored profile only; no `agent_id` leak) |
| POST | `/owismind-api/chat/start` | Validate + budget-gate + persist user message (phase 1) + spawn background worker; returns `{run_id, exchange_id}` |
| GET | `/owismind-api/chat/poll` | Return normalized events since `cursor`; owner-scoped on `run_id` |
| POST | `/owismind-api/chat/stop` | Cooperative early stop; sets `stop_requested` flag on the run state; owner-scoped |
| POST | `/owismind-api/chat/feedback` | Persist thumbs-up/down + reasons + comment on one exchange; owner-scoped UPDATE |
| GET | `/owismind-api/conversations` | Keyset-paginated names-only conversation list; owner-scoped |
| GET | `/owismind-api/conversation` | All messages of one session (lazy, on click); owner-scoped |
| GET | `/owismind-api/evidence/meta` | Full evidence descriptor for one exchange: parsed SQL, chip predicates, trust-layer verification, captured result, drill-down availability, artifact list with built chart/KPI payloads |
| POST | `/owismind-api/evidence/rows` | One bounded page of the re-filtered evidence table; structured filter chips sent (never raw SQL) |
| GET | `/owismind-api/evidence/distinct` | Bounded distinct values of one column for filter-chip picker |
| GET | `/owismind-api/admin/storage` | Resolved storage config (connection, prefix, table names); admin-gated |
| GET | `/owismind-api/admin/users` | All registered users with admin flags; admin-gated |
| POST | `/owismind-api/admin/users/set-admin` | Set/clear admin flag (cannot remove last admin); admin-gated |
| GET, POST | `/owismind-api/admin/budget` | Get or set global monthly budget config + per-user usage overview; admin-gated |
| POST | `/owismind-api/admin/budget/users` | Set or clear per-user quota overrides (one / many / all, permanent or temporary); admin-gated |
| GET | `/owismind-api/admin/projects` | DSS projects visible to the webapp identity; admin-gated |
| GET | `/owismind-api/admin/projects/<project_key>/agents` | Agents of one project (validated against visible list); admin-gated |
| GET, POST | `/owismind-api/admin/agents` | Get or set the enabled-agent whitelist; POST re-validates every agent against live DSS listings + sanitizes `validate_agent_meta`; admin-gated |

---

## 2. End-to-End Artifact Pipeline

**Step 1 - Agent emits `ARTIFACT` event (LangGraph Code Agent)**

The orchestrator calls `show_chart` or `show_table`, which causes DSS to emit a raw chunk `{type:"event", eventKind:"ARTIFACT", eventData:{kind, title, chart:{type,x,y}}}`.

**Step 2 - `streaming.run_agent_streamed` normalizes it**

In `streaming.py`, the `_ARTIFACT_KIND = "ARTIFACT"` branch calls `_normalized_artifact_event(event_data)`. This function validates `kind in ("chart","table","kpi")`, enforces string caps on title/x/y column names (max 128 chars, max 8 y-series), and rejects unknown chart types. Returns a clean `{type:"artifact", kind, title, chart:{type,x,y}}` dict (no data rows). A `kpi` artifact carries a `{label, value[, delta, delta_pct]}` block instead.

**Step 3 - Worker accumulates the spec, then persists via `artifacts_storage.save_artifacts`**

In `stream_manager._worker`, the `etype == "artifact"` branch appends to `artifacts[]` (bounded at `MAX_ARTIFACTS_ACCUM = 8`). The artifact is NOT added to the polled live timeline. After the full run ends, `artifacts_storage.save_artifacts(exchange_id, user_id, artifacts)` is called best-effort (a failure never breaks the answer).

`save_artifacts` in `storage/artifacts.py` calls `_sanitize(artifacts)` (double-sanitizes: once upstream in streaming, once here), serializes to JSON, caps the JSON at `MAX_ARTIFACTS_JSON_CHARS = 16_000`, then executes an UPSERT:

```sql
INSERT INTO <table> (exchange_id, user_id, artifacts, created_at)
VALUES (?, ?, ?, now())
ON CONFLICT (exchange_id) DO UPDATE SET artifacts = EXCLUDED.artifacts, user_id = EXCLUDED.user_id
```

with `pre_queries=["SET LOCAL statement_timeout TO '30000'"]` and `post_queries=["COMMIT"]`.

**Step 4 - Served via `/evidence/meta`**

In `routes.py`'s `evidence_meta`, after `evidence_service.evidence_meta` returns the SQL proof block, `artifacts_storage.read_artifacts(user_id, exchange_id)` is called (owner-scoped, read-only with `SET LOCAL statement_timeout + transaction_read_only`). For each artifact:
- `kind == "chart"`: calls `chart_payload.build_chart_payload(result_block, a["chart"])` - pure function, returns `{ok, labels, datasets, truncated}` for Chart.js or `{ok: False, reason}`.
- `kind == "kpi"`: calls `chart_payload.build_kpi_payload(result_block, a["kpi"])`.

The `result_block` comes from the active `generated_sql` item's captured `result` field (stored in `chat_v5`). The agent chose axes only; `chart_payload.py` does all column resolution (`_resolve` is case-insensitive), number coercion (`_to_number` handles currency/percent/comma), and pie-slice grouping (max `MAX_SLICES = 12`, tail -> "Other"). A non-numeric series returns `{ok: False}` - honest empty state, never a broken chart.

**Extension seam**: Adding a new artifact type (e.g. `"report"`) requires: (a) add the kind to `_ARTIFACT_KINDS` in `artifacts.py` + `streaming._normalized_artifact_event`; (b) add a `build_report_payload` function in `chart_payload.py`; (c) handle it in the `evidence_meta` route's artifact loop.

---

## 3. Agent Invocation and Streaming Model

**Why polling, not SSE**: DSS's nginx proxy buffers long-lived event-streams, making SSE useless. The production Dash app on the same instance uses polling; this backend ports that pattern.

**Flow** (`stream_manager.py`):

1. `start_run(project_key, agent_id, message, exchange_id, ...)` registers a UUID `run_id` in the module-level `_RUNS` dict (guarded by `_LOCK`), increments `_LAST_START_BY_USER`, and spawns a daemon thread via `threading.Thread(target=_worker, ...)`.

2. `_worker` assembles history via `chat_v5.history_messages_for_chain` (recursive ancestor chain), builds a screen-context block via `_build_screen_block`, then calls `streaming.run_agent_streamed(project_key, agent_id, agent_messages)`.

3. `run_agent_streamed` calls `dataiku.api_client().get_project(project_key).get_llm(agent_id).new_completion()`, replays turns with `completion.with_message(content, role)`, then iterates `completion.execute_streamed()`. Each chunk is normalized into typed event dicts and yielded.

4. Between every chunk, `_stop_reason(run_id, started_at)` checks: explicit `stop_requested` flag, `MAX_RUN_SECONDS = 300`, or `ABANDON_AFTER_SECONDS = 30` since last poll.

5. The worker appends each event to `_RUNS[run_id]["events"]` via `_append_event_locked_free`. Live timeline is capped at `MAX_LIVE_EVENTS = 5000`; answer accumulation at `MAX_ANSWER_CHARS = 1_000_000`.

6. `poll(run_id, user_id, cursor)` slices `events[cursor:]` under `_LOCK`, updates `last_poll_at`, returns `{events, cursor, done, error}`. Owner-scoped: a `run_id` owned by someone else returns `None` (-> 404).

7. Finished runs are evicted after `FINISHED_TTL_SECONDS = 60`; any run is hard-evicted after `HARD_TTL_SECONDS = 600`. `MAX_CONCURRENT_RUNS = 8`.

---

## 4. PostgreSQL Tables

All physical names are `public."{PROJECT_KEY}_owismind_{logical}"`. The `_vN` suffix is the immutable versioning scheme (no ALTER of old tables; new version = new table).

| Logical name | Physical example | Purpose |
|---|---|---|
| `webapp_chat_v5` | `…_owismind_webapp_chat_v5` | One row per exchange: user text, assistant text, `generated_sql` (JSON list), `agent_key`, feedback columns, `parent_exchange_id`, per-exchange token/cost usage. Source of truth. |
| `webapp_users_v1` | `…_owismind_webapp_users_v1` | User registry: `user_id`, `display_name`, `is_admin`, lifetime token/cost accumulators (`total_input_tokens`, `total_output_tokens`, `total_cost`). |
| `webapp_settings_v1` | `…_owismind_webapp_settings_v1` | Key-value store for global settings: `enabled_agents` JSON whitelist, `monthly_budget` config JSON. |
| `webapp_usage_monthly_v1` | `…_owismind_webapp_usage_monthly_v1` | Per-(user, calendar-month) usage bucket. PK `(user_id, period_start)`. Monthly quota is a single PK lookup; resets naturally (new month = new row, no cron). |
| `webapp_artifacts_v1` | `…_owismind_webapp_artifacts_v1` | Per-exchange artifact specs (JSON list of chart/table/KPI specs). PK `exchange_id`. Data not stored here - reuses `generated_sql.result`. |
| `webapp_user_quota_v1` | `…_owismind_webapp_user_quota_v1` | Per-user monthly budget overrides. PK `user_id`. `expires_at NULL` = permanent; future timestamp = temporary boost. Absence of a row = use global default. |

Indexes on `webapp_chat_v5`: `(user_id, created_at DESC)` for the conversation sidebar, `(user_id, session_id, created_at DESC)` for per-session reads.

---

## 5. Extension Seams

**New artifact type (e.g. PDF export spec, email)**:
- `streaming._ARTIFACT_KINDS` and `streaming._normalized_artifact_event`: add the new `kind` and its validation block.
- `storage/artifacts.py` `_ARTIFACT_KINDS` and `_sanitize`: add the new kind's sanitization branch.
- `evidence/chart_payload.py`: add a `build_<kind>_payload(result_block, spec)` function.
- `routes.py` `evidence_meta`: add an `elif a.get("kind") == "<kind>"` branch in the artifact loop.

**New tool result type** (e.g. a tool that returns structured JSON instead of SQL rows):
- `streaming.py`: add a new `eventKind` constant and a `_normalized_<kind>_event` function.
- `stream_manager._worker`: add a corresponding `elif etype == "<kind>"` accumulator branch.
- Persistence: either reuse `artifacts_storage` (for spec-only) or add a new `storage/<kind>.py` with its own DDL (new `_vN` table, no ALTER) registered in `migrations._DDL_BY_LOGICAL`.

**New export endpoint** (e.g. `/evidence/export/csv`):
- Add a new `@api.route("/evidence/export/csv", methods=["GET"])` in `routes.py`.
- Reuse `_evidence_guard()` for auth/rate-limiting.
- Call `evidence_service._context(user_id, exchange_id)` to get the resolved table/colmap, then build a bounded `build_rows_query` call from `query_builders.py` (already parametrized and injection-safe).
- Must apply `_EVIDENCE_TIMEOUT_PRE_QUERIES` via the executor and cap the row count.

---

## 6. Safety Mechanisms Already in Place

Every new feature must respect these in-place constraints:

**SQL safety**:
- All user values go through `sql_value(v)` (`Constant(v)` + `toSQL`, parametrized Postgres). No f-strings around user content.
- `pg_identifier(name)` validates identifiers before quoting; raises `ValueError` on unsafe names.
- Writes: `pre_queries=[DDL or DML]` + `post_queries=["COMMIT"]`. Reads: `pre_queries=["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]` - transaction-scoped, never leaks to other workloads.
- `_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"` on all writes.

**Owner-scoping**: every chat/evidence/artifact read includes `WHERE user_id = {sql_value(user_id)}` - a forged `exchange_id` returns empty results for another user's data, never leaks.

**Identity**: always resolved server-side via `resolve_identity(request.headers)` from the DSS auth cookie (short-TTL cache at `_AUTH_TTL_SECONDS = 5.0`). Never from the request body.

**Rate / concurrency caps**: `stream_manager.MAX_CONCURRENT_RUNS = 8`, `MIN_START_INTERVAL_SECONDS = 1.0` per user. Evidence routes: `evidence_throttle.can_accept(user_id)` token bucket. Usage route: `evidence_throttle.usage_can_accept(user_id)`.

**Memory caps**: `MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000`, `MAX_ARTIFACTS_ACCUM = 8`, `MAX_ARTIFACTS_JSON_CHARS = 16_000`, `capture.MAX_RESULT_ROWS = 200`, `capture.MAX_SQL_ITEMS = 20`, `capture.MAX_PERSISTED_TEXT_CHARS = 262_144`.

**Agent whitelist**: the frontend sends an opaque `agent_key` (SHA-1 hash of `project_key:agent_id`, prefixed `ag_`). Resolved via `settings.resolve_enabled_agent(agent_key)` - a key not in the whitelist resolves to `None` and the request is rejected with 404. `agent_id` and `project_key` are never accepted from the frontend.

**No-ALTER versioning**: new tables are always `_vN` (new DDL entry in `migrations._DDL_BY_LOGICAL`). The only exception is additive `ADD COLUMN IF NOT EXISTS` on `webapp_users_v1` for usage counters (authorized, listed in `_ALTERS_BY_LOGICAL`).

**Best-effort failure isolation**: artifact storage, trace storage, and usage aggregation all catch and log exceptions without re-raising - a storage failure on any of these never aborts the agent answer already accumulated in `answer_parts`.