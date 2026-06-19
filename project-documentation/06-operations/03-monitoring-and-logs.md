# Monitoring and logs

> Audience: operator, support. Last updated: 2026-06-19. Summary: where to look to
> diagnose OWIsMind (the webapp backend log, content-free), which identifiers to correlate
> (`run_id`, `exchange_id`, `user_id`), how to monitor run concurrency and the caps,
> and the safety best practices on a shared Dataiku instance.

OWIsMind does not ship a dedicated observability stack (no Prometheus, no business
dashboard). Monitoring relies on two sources: the **DSS webapp backend log** (the primary
source, real-time) and an **optional traces dataset** (offline analysis, write-only). This
document explains what you find there, what NEVER appears there, and how to relate the lines to one another.

## 1. Where to look: the webapp backend log

The Flask backend (`python-lib/owismind/`) writes its logs to the **DSS webapp backend log**
(the `webapp-owismind-ai-agents` webapp). This is the console DSS shows when you open the webapp and
look at its backend (Log / View backend log button, depending on the instance version). All
logging goes through the standard `logging` logger (each module does
`logger = logging.getLogger(__name__)`), so the lines are prefixed by the module that emits them
(`owismind.api.routes`, `owismind.agents.stream_manager`, etc.).

### 1.1 Configurable log level

Verbosity is driven by the **`log_level`** parameter in the webapp Settings (`webapp.json`),
a SELECT with three values: `DEBUG`, `INFO`, `WARNING`, default **`INFO`**. At backend startup,
`register_routes(app)` calls `sql_config.apply_log_level()`, which applies the chosen level both
to the root logger and to the `owismind` logger, then logs `Log level set to <LEVEL>`. To change the
level, change the parameter in the Settings then **restart the backend** (the level is only read
at boot, via `apply_log_level()`).

| Level | When to use it |
|---|---|
| `WARNING` | Quiet production: keeps only rejections and anomalies (rate limit, concurrency cap, traces not written, swallowed failures). |
| `INFO` (default) | Normal operation: traces every API request, the lifecycle of every run, Evidence observability. This is the right default for support. |
| `DEBUG` | Fine-grained investigation only. More verbose; switch back to `INFO` once the diagnosis is done. |

### 1.2 What the backend logs at startup (version marker)

`register_routes(app)` writes, at boot, two lines that confirm WHICH build is running and HOW
storage resolved:

- `OWIsMind storage status: {...}`: the full dictionary returned by `storage_status()`
  (configured, connection, project_key, namespace, traces_dataset, and the physical table names). This
  first reflex lets you verify, without admin authentication, that the expected connection
  (`SQL_owi`) and project key (`OWISMIND_DEV`) are correctly resolved.
- `OWIsMind API ready - <N> routes: <sorted list>`: the live route table (all the rules
  under `/owismind-api`). If an expected route is missing, the deployed build is not the one you think.

See also [Installation and configuration](01-installation-and-configuration.md) for the meaning of these
fields and [Build, packaging and deployment](02-build-package-deploy.md) for the "restart the
backend" rule after any `python-lib` change.

### 1.3 One line per API request (blueprint-scoped hooks)

Two `@api.before_request` / `@api.after_request` hooks trace EVERY `/owismind-api/*` request:

- at the start: `→ <method> <path>` (and a timer `g._owi_t0` is set);
- at the end: `← <method> <path> -> <status> (<ms> ms)`.

Key point for support: these hooks are **blueprint-scoped** (decorated `@api.before_request`), so
they only fire for OWIsMind routes, not for DSS internal health pings. The
millisecond duration on the `←` line is the most direct tool for spotting a slow route (for
example an abnormally long `/chat/poll` or an `/evidence/rows` that pulls a lot). The **content** of the
requests never appears on these lines: only method, path, status, duration.

## 2. What is NEVER logged: the content of messages

This is a structuring privacy and hygiene guarantee, worth knowing to reassure a user
or an auditor: **the content of user messages and agent responses is never written
to the logs.** Only metadata (length, identifiers, statuses) is.

- `/chat/start` logs a deliberately content-free line:
  `/chat/start - user_id=... session_id=... agent_key=... msg_len=...`. The message length
  (`msg_len`) is logged, never the message. This is the only entry point where a body could
  leak, and it stays content-free by explicit choice. When the monthly budget gate fires,
  a dedicated INFO line is logged BEFORE the run starts:
  `/chat/start - monthly quota exceeded user_id=... spent=... limit=...`; the route then
  returns HTTP 402 (`monthly_quota_exceeded`) with the budget status in the body.
- The authentication header values (which may carry credentials / cookies) are
  NEVER logged by `security/identity.py`. On an identity failure, it is the NAMES of the keys
  present (not their values) that are logged for diagnostics.
- When a run fails, no agent / SQL / connection internal is disclosed: the state machine
  logs the exception server-side (`logger.exception`) but only returns a stable code to the client
  (`agent_unavailable`). The technical detail stays in the backend log, the client sees only the code.
- The `result` captured by Evidence (the data rows) is persistence-only: it is neither pushed
  into the agent context nor onto the polled timeline, and does not appear in the logs.

Consequence for support: you can share a log extract without exposing the business content
of the conversations. To relate a log to a conversation, you rely on the **identifiers**
(next section), not on the text.

## 3. The identifiers useful for correlation

Three identifiers let you follow a single chat turn across the layers. They are stable
and appear verbatim in the log lines, so they are greppable.

| Identifier | What it designates | Where it appears |
|---|---|---|
| `user_id` | The DSS login of the caller (e.g. `said.chaoui`), resolved from the headers, never from the body. Used for scoping (chat, feedback, Evidence, admin). | `/chat/start`, run start line, Evidence observability. |
| `session_id` | The conversation (groups several exchanges), stamped in the URL `/chat/<sessionId>`. | `/chat/start`. |
| `exchange_id` | ONE exchange (one user turn + response), one row of `webapp_chat_v5`, `uuid4().hex` generated in Python. | `/chat/start` return, run end lines, `save_trace`, Evidence observability. |
| `run_id` | The in-flight generation cycle (worker thread + `_RUNS` state), opaque handle `uuid4().hex`. | all the `stream_manager - ...` lines. |

> Important distinction: a `run_id` is ephemeral (it lives for the duration of the run, plus a short
> TTL window), whereas an `exchange_id` is durably persisted in `webapp_chat_v5`. To find a past
> conversation you search by `exchange_id` / `session_id`; to follow a live generation
> you follow the `run_id`.

### 3.1 Following a run end to end

The lifecycle of a run produces `stream_manager - ...` lines that all carry the `run_id` and
the `exchange_id`, which lets you reconstruct the whole story of a turn:

- **Start**: `stream_manager - started run_id=... exchange_id=... agent_id=... user_id=...`.
  This is also the only place where the raw `agent_id` (resolved server-side from the whitelist) appears,
  log-side only, never returned to the front.
- **Nominal end**: `stream_manager - done run_id=... exchange_id=... answer_len=... sql_count=...`.
- **Stop by the user**: `stream_manager - stopped by user run_id=... exchange_id=...
  answer_len=... sql_count=...` (this is NOT an error: a partial response is persisted).
- **Cut by a safety bound** (timeout / abandon):
  `stream_manager - ended run_id=... early (<reason>) ...`; the terminal client-side event is then
  `error: run_<reason>`.
- **Failure**: `stream_manager - agent run failed run_id=... exchange_id=...` (full trace server-side
  via `logger.exception`), client event `agent_unavailable`.

The full flow (front -> `/chat/start` -> worker -> `/chat/poll` -> persistence) is described in
sequence in [Runtime flow](../02-architecture/03-runtime-flows.md) and the detail of the
run lifecycle in
[Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md). This document does not
redraw it.

### 3.2 Evidence observability

Each call to `/evidence/meta` writes a dedicated observability line that summarizes the quality of the
evidence, precisely because the level of verification is the central stake of the trust layer:

```
/evidence/meta - user_id=... exchange_id=... available=... reason=... level=... result_captured=... drill_available=... artifacts=N
```

For support, this line tells you at a glance why an Evidence panel is degraded
(`available=false` + a stable `reason`), whether the `result` could be captured (`result_captured`), and
how many artifacts (chart/table/kpi) are attached. The capture of the `result` is **best-effort** and
can be absent on the instance (the key of the tool span rows is not confirmed): a
`result_captured=false` is therefore a normal possible state, not necessarily an incident. The detail of the
Evidence pipeline lives in
[Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

## 4. The optional traces dataset

In addition to the logs, the admin can configure a **traces dataset** (`traces_dataset`, a SELECT of
the project's SQL-backed datasets, plus a `(none)` entry). When it is defined, the backend appends,
**write-only**, one line per exchange whose run returned a footer trace: the raw end-of-stream
trace (nested spans, tool outputs, usage), serialized to JSON. Characteristics to
know for operations:

- **Write-only**: the webapp NEVER reads this dataset online (re-reading the blob on every
  request would slow the app down). It serves only for offline analysis in the Flow.
- **Best-effort**: a write failure (missing dataset, incompatible schema, blob too large) is
  logged on a short line (`save_trace - ...`) and swallowed. A lost trace NEVER breaks the
  response already on screen.
- **Bounded**: `MAX_TRACE_BYTES = 4_000_000`; beyond that, a small marker `{"_truncated": true, ...}`
  is stored in place of the blob (and logged at `warning`). Real traces are tens of KB.
- **Dataset shape**: first create in the Flow a **SQL-table-backed** dataset with exactly
  three columns (`exchange_id` string, `trace` string, `created_at` date; the column order
  does not matter, the code aligns the write). Avoid a CSV / filesystem dataset: its own
  row length limit could be exceeded by a large JSON line.
- **Why a Dataset append and not a direct SQL INSERT**: DSS logs the full text of every
  `SQLExecutor2` query, so an `INSERT ... VALUES ('<big JSON>')` would write the whole blob into a
  logged statement (and, on this instance, a scenario materializes these logs and a cell that is too long
  triggers "row too long"). The Dataset API (`write_with_schema`, appendMode) does not go through this
  SQL logging. This mechanism is detailed in the code (`storage/chat_traces.py`).

To relate a trace to a run, use the `exchange_id`: it appears both in the log line
`save_trace - append to dataset ... exchange_id=...` and as a column of the dataset.

> IN FLUX: the agent layer (`dataiku-agents/`) that PRODUCES this footer trace is being edited
> live. The event contract stays stable (the trace arrives in the stream footer), but the exact content
> of the blob may evolve.

## 5. Monitoring run concurrency and the caps

The backend is a bounded worker by design (Dataiku instance safety). Several caps protect
the instance; exceeding them produces rejections visible in the log and HTTP codes client-side. The
values are constants of the `agents/stream_manager.py` module.

| Guardrail | Value | Effect when reached | Trace / code |
|---|---|---|---|
| Global concurrent runs cap | `MAX_CONCURRENT_RUNS = 8` | new `/chat/start` rejected | `/chat/start - rejected before write: busy` then `503 busy`; the real guard (`CapacityError`) logs `concurrency cap reached, rejected` |
| Per-user spacing | `MIN_START_INTERVAL_SECONDS = 1.0` s | starts too close together from the same user rejected | `/chat/start - rejected before write: rate_limited` then `429 rate_limited` |
| Wall-clock deadline | `MAX_RUN_SECONDS = 300.0` s | run cut short (between chunks) | `stream_manager - ended ... early (...)` |
| Abandon (tab closed) | `ABANDON_AFTER_SECONDS = 30.0` s | run cut if the front stopped polling | `stream_manager - ended ... early (...)` |
| Finished run eviction | `FINISHED_TTL_SECONDS = 60.0` s | run state freed after the end | `stream_manager - evicted N stale run(s)` |
| Absolute lifetime | `HARD_TTL_SECONDS = 600.0` s | orphan run evicted even if never polled | same (eviction) |
| Per-run memory bounds | `MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000`, `MAX_ARTIFACTS_ACCUM = 8` | live timeline / response capped (terminals always emitted) | (no rejection, just capping) |

Interpretation for support:

- A spike of `429 rate_limited` = a single user spamming `/chat/start` (per-user gate of 1 s),
  not a global overload. The client can retry after a short pause.
- A spike of `503 busy` = the GLOBAL cap of 8 simultaneous runs is reached. This is the signal of a real
  load (several users at the same time); the run is rejected BEFORE any write, hence with no
  SQL cost. If it is recurring and legitimate, it is a point to escalate (the cap is deliberately
  generous for a small panel of users).
- Regular `evicted N stale run(s)` lines are normal (cleanup of finished runs).
- Known documented limitation: the deadline and the abandon are evaluated BETWEEN chunks. An upstream call
  that is totally frozen and never yields stays bounded only by the memory TTL (no dedicated
  watchdog, an assumed choice). See
  [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md).

> Operational assumption to lock in: all this state (`_RUNS`, the identity cache, the rate-limit
> counters) is **per-process**. The model assumes a **single-process** DSS backend. In
> multi-process, the cap would be multiplied by N and a cross-process `/chat/poll` would return `404`. To
> force / verify at 1 process at deployment. See
> [Security model](../02-architecture/04-security-model.md).

## 6. Operational best practices (Dataiku instance safety)

The project's non-negotiable rule #2 is **Dataiku instance safety**: never introduce
heavy, blocking or unbounded load. The code already respects this posture; on the operations side, here are
the reflexes that extend it.

- **Keep the backend single-process** (see above). This is the prerequisite that makes the caps, the
  identity cache and the run ownership correct.
- **Keep `log_level` on `INFO`** in normal operation; only switch to `DEBUG` for an
  investigation, then return to `INFO` (and restart the backend to apply).
- **Do not read the traces dataset online** from the app: it is write-only by design.
  Analysis is done in the Flow, off the hot path.
- **First diagnosis = the webapp backend log**, in this order: the boot `storage status` line
  (did the config resolve?), the route table (is the right build running?), then the
  `→ / ←` lines (latencies) and `stream_manager - ...` lines (run lifecycle) for the specific incident.
- **Never run a heavy ad hoc SQL query** on the storage connection from an external tool
  during usage hours: there is deliberately no generic SQL route, and the
  storage is sized for bounded reads (row caps everywhere).
- **Correlate by identifiers**, never by content: the content is absent from the logs by choice. You
  relate an incident to a conversation via `run_id` (live) or `exchange_id` / `session_id` (persisted).
- **After any `python-lib` / `backend.py` change**: restart the backend (otherwise the old code
  runs and the logs describe a stale build). After any frontend-only change: a simple
  refresh is enough, no restart. See
  [Build, packaging and deployment](02-build-package-deploy.md).

For a concrete incident (backend not restarted, mode that does not respond, `storage_not_configured`),
the step-by-step procedures are in the [Runbooks](04-runbooks.md).

## See also

- [Installation and configuration](01-installation-and-configuration.md) - choose the SQL connection, the
  traces dataset and the log level in the webapp Settings.
- [Build, packaging and deployment](02-build-package-deploy.md) - the "restart the backend" rule
  after a python-lib change, and the what-to-rebuild-when matrix.
- [Runbooks (incident procedures)](04-runbooks.md) - resolve a backend not restarted, a mode that
  does not respond, or a `storage not configured`.
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - the detail
  of the caps, TTLs and the run state machine.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - the meaning of the
  `/evidence/meta` observability line and the best-effort capture of the result.
- [Security model](../02-architecture/04-security-model.md) - single-process assumption,
  owner-scoping, and content-free log hygiene.
- [Runtime flow](../02-architecture/03-runtime-flows.md) - the full sequence of a chat
  turn that the log lines let you follow.
