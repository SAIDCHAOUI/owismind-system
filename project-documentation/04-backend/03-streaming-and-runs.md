# Backend - streaming and run lifecycle

> Audience: backend developer. Last updated: 2026-06-18. Summary: how the Flask backend streams an
> agent's progress to the browser without SSE (one bounded worker thread plus a module-level dict polled
> by the client), including event normalization, cooperative stop handling and the instance-safety
> guardrails.

## Why polling and not SSE

OWIsMind does not push a long stream to the browser. The reason is written at the top of
`agents/stream_manager.py`: DSS places an internal nginx in front of every webapp Python backend. A long
`text/event-stream` HTTP response can be buffered by that proxy, so the agent's events would arrive all
at once at the end instead of in real time. The pattern we chose is the one the production Dash WebApp
(same instance) uses by design: never expose a long response. We run the agent in a background thread,
accumulate progress in a module-level dict, and the frontend polls that dict roughly every 500 ms. Each
poll is a normal short request that the proxy never buffers.

`stream_manager.py` carries this proven pattern over to the Flask/Vue stack and adds two safety nets the
Dash version did not have: a concurrency cap (bounded threads) and a TTL eviction (no memory leak from
orphaned runs). This choice is formalized in
[ADR-0002 - Polling-based streaming](../08-decisions/0002-streaming-par-polling.md). The same sequence
seen end to end (frontend -> `/chat/start` -> worker -> agents -> `/chat/poll` -> persistence -> Evidence
opening) is described in [Runtime flow](../02-architecture/03-runtime-flows.md), and on the frontend side
in [Frontend - communication with the backend](../03-frontend/04-backend-communication.md).

## Vocabulary: run, exchange, session

Three distinct notions intersect here and must not be confused:

| Term | Definition | Identifier |
|---|---|---|
| run | An IN-FLIGHT generation cycle on the backend side: one worker thread plus one entry in the `_RUNS` dict. | `run_id` = `uuid4().hex`, opaque |
| exchange | The row persisted in `webapp_chat_v5` (one user turn plus assistant reply). | `exchange_id` |
| session | The conversation that groups several exchanges, stamped in the URL `/chat/<sessionId>`. | `session_id` |

The `run_id` never leaves the process memory: it serves only for polling and stopping. The reply itself
is written to the `exchange_id` (see [Storage and data model](04-storage-and-data-model.md)).

## Polling flow architecture

```mermaid
flowchart TD
    subgraph route["api/routes.py (request thread)"]
        START["POST /chat/start"]
        POLL["GET /chat/poll (cursor)"]
        STOP["POST /chat/stop"]
    end
    subgraph mgr["agents/stream_manager.py (module state, guarded by _LOCK)"]
        RUNS["_RUNS: run_id -> {events[], done, error, user_id,<br/>started_at, finished_at, last_poll_at, stop_requested}"]
        WORKER["_worker (daemon thread owi-agent-run-XXXX)"]
    end
    STREAM["agents/streaming.run_agent_streamed<br/>(normalized event generator)"]
    MESH["LLM Mesh: project.get_llm(agent_id).new_completion()<br/>.execute_streamed()"]
    STORE["storage/*: chat_v5, usage, chat_traces, artifacts"]

    START -->|can_accept then start_run| RUNS
    START -.spawn.-> WORKER
    WORKER -->|iterates| STREAM
    STREAM -->|raw chunks| MESH
    WORKER -->|append events under _LOCK| RUNS
    WORKER -->|best-effort phase two| STORE
    POLL -->|poll: slice events[cursor:] + done| RUNS
    STOP -->|request_stop: stop_requested=True| RUNS
    WORKER -.reads stop_requested + last_poll_at between chunks.-> RUNS
```

The core of the contract: the worker WRITES into `_RUNS`, the poll READS from `_RUNS`, never the other
way around. Everything goes through a single `threading.Lock` because the critical sections are tiny (a
list append or a list slice), so a global lock is simpler and safer than a per-run lock.

## The lifecycle of a run in `stream_manager.py`

### Shared state and lock

All the state lives in two module-level dicts guarded by `_LOCK`:

- `_RUNS`: `run_id -> {events, done, error, user_id, started_at, finished_at, last_poll_at, stop_requested}`.
- `_LAST_START_BY_USER`: `user_id -> monotonic timestamp` of the last start, for the per-user spacing
  grid.

The exact shape of a run is set in `start_run`. All internal timestamps are `time.monotonic()` values
(insensitive to system clock changes).

### The instance-safety bounds

All the tuning constants are at the top of `stream_manager.py`. They materialize the non-negotiable
Dataiku instance-safety rule: no run may indefinitely consume a thread, an LLM Mesh connection or
memory.

| Constant | Value | Role |
|---|---|---|
| `MAX_CONCURRENT_RUNS` | `8` | Hard cap on simultaneously in-flight runs across the whole process. |
| `FINISHED_TTL_SECONDS` | `60.0` | Time during which a finished run remains readable (covers a late/duplicate poll: it sees the terminal events instead of a 404). |
| `HARD_TTL_SECONDS` | `600.0` | Absolute lifetime of any run, even with a tab closed mid-run: guarantees no orphan accumulates. |
| `MAX_LIVE_EVENTS` | `5000` | Per-run bound on the live timeline being polled. |
| `MAX_ANSWER_CHARS` | `1_000_000` | Per-run bound on the accumulated reply. |
| `MAX_ARTIFACTS_ACCUM` | `8` | Bound on the number of artifact specs (chart/table) accumulated. |
| `MAX_RUN_SECONDS` | `300.0` | Hard wall-clock deadline: a run cannot occupy a worker for more than 5 minutes. |
| `ABANDON_AFTER_SECONDS` | `30.0` | If the browser has stopped polling (tab closed) for this long AFTER it had started polling, the run is treated as abandoned and cut. |
| `MIN_START_INTERVAL_SECONDS` | `1.0` | Minimum spacing between two starts FROM THE SAME user (anti-spam pre-gate). |

Important point documented in the code: `MAX_RUN_SECONDS` and `ABANDON_AFTER_SECONDS` are evaluated
BETWEEN streamed chunks. This is an explicit, accepted limitation: an upstream call that is fully blocked
and never yields is bounded only by the memory TTL. A watchdog thread would be required for that and is
deliberately not added (higher risk on a valid path).

### `can_accept(user_id)`: the admission pre-check

The route calls `can_accept` BEFORE any database write. It reflects the hard concurrency cap so a
saturated request can be rejected before persisting a user message (a wasted INSERT plus an auth round
trip), and it adds a lightweight per-user spacing grid. It returns `(ok, reason)` where `reason` is
`"busy"` (cap reached) or `"rate_limited"`. Anti-race detail: the user's spacing timestamp is reserved
under the SAME lock, so that two concurrent `/chat/start` calls from the same user do not both clear the
grid. On the route side, `rate_limited` becomes HTTP 429 and `busy` becomes HTTP 503.

`can_accept` is advisory (there is a benign, documented TOCTOU window between it and the hard cap). The
real gate is still `start_run`, which recounts the active runs under the lock and raises `CapacityError`
(mapped to HTTP 503 `busy` by the route).

### `start_run(...)`: registration and spawn

```python
start_run(project_key, agent_id, message, exchange_id, user_id,
          parent_exchange_id, history_limit, user_suffix, screen_context=None)
```

The mechanics: it generates `run_id = uuid4().hex`, evicts the stale runs under the lock
(`_evict_stale_locked`), recounts the active runs and raises `CapacityError` if
`active >= MAX_CONCURRENT_RUNS` (a second guard, on top of `can_accept`), registers the run shape, then
launches a `threading.Thread(target=_worker, ..., daemon=True)` named `owi-agent-run-<8 hex>`. Subtlety:
`started_at` is passed EXPLICITLY to the worker, so that the wall-clock deadline is anchored at
registration and never reset by re-reading a possibly evicted run state.

The `project_key`/`agent_id` arguments are the target already resolved by the server whitelist: the
worker never sees a raw key from the frontend (see [Security and validation](06-security-and-validation.md)
and [ADR-0004 - Server-side agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md)).

### `_evict_stale_locked(now)`: the TTL eviction

To be called while holding `_LOCK`. Marked stale: a finished run whose `finished_at` exceeds
`FINISHED_TTL_SECONDS`, OR any run whose `started_at` exceeds `HARD_TTL_SECONDS`. It `pop`s them then logs
`evicted N stale run(s)`. It also keeps `_LAST_START_BY_USER` bounded by removing timestamps older than
`HARD_TTL_SECONDS`. Eviction is called on every `start_run` and every `poll`, so cleanup happens
continuously without a background task.

### `_stop_reason(run_id, started_at)`: why to cut

Returns the reason to cut, otherwise `None`, with a strict priority: explicit user stop (`"stopped"`),
then wall-clock deadline (`"timeout"`), then browser-abandon cut (`"abandoned"`). Evaluated between
chunks. Central note from the comment: the official LLM Mesh stream exposes NO cancel API. A cooperative
stop (simply ceasing to iterate the generator) is therefore the only supported way to end a run early.

### `_worker(...)`: the heart

The worker runs an agent completion, streams its events into the run, then persists. It mirrors the body
of the former SSE generator but writes into the shared state instead of yielding HTTP frames.

Sequence of events emitted to the frontend: `run_started`, then the agent's own events (`agent_event` /
`answer_delta` / `generated_sql` / `usage_summary` / `narration`), then `final_answer` followed by
`run_done` (or `stopped`, or `error`).

Before the loop, the worker assembles the multi-turn payload:

1. It emits `{"type": "run_started", "exchangeId": exchange_id}`.
2. It reads the history via `chat_v5.history_messages_for_chain(user_id, parent_exchange_id, history_limit)`.
   Best-effort: if the read fails, it degrades to the current turn alone.
3. It builds the `ON SCREEN NOW` block via `_build_screen_block` (see below), placed BEFORE the language
   suffix so that the language imperative stays the last line of the turn.
4. `agent_messages = context.build_completion_messages(history, message, screen_block + (user_suffix or ""))`.
5. It iterates `for event in streaming.run_agent_streamed(...)`, and between each event calls
   `_stop_reason`, doing a `break` if a cut is requested.

Processing by event type, in the worker:

| Event type | Processing |
|---|---|
| `answer_delta` | Accumulates `text` into `answer_parts`, bounded by `MAX_ANSWER_CHARS` (beyond that: sets the `answer_truncated` flag, a single warn). The event then falls through into the live timeline. |
| `generated_sql` | Builds the persistence item `{sql, success, row_count}` plus optional trust-layer keys copied only if present; handles the `sqlIndex` enrichment (see below); the `result` key (captured rows) is REMOVED from the live copy. |
| `usage_summary` | Captures `{promptTokens, completionTokens, totalTokens, estimatedCost}` into `usage_totals` for persistence; does NOT `continue`, the event also falls through into the live timeline to display usage during the run. |
| `artifact` | Captures the spec `{kind, title, chart[, kpi]}` into `artifacts`, bounded by `MAX_ARTIFACTS_ACCUM`, then `continue`: never added to the live list (the live label was already given by the ARTIFACT `agent_event`). |
| `trace` | Captures `trace_raw` then `continue`: the RAW trace is for persistence only, never on the live timeline (it can be voluminous). |
| `narration` | No dedicated `elif` branch: falls through into the generic live-timeline append. Intentional: narration is transient, shown as a stream but never persisted in the reply. |
| anything else | Appended to the live timeline if `live_events < MAX_LIVE_EVENTS`. |

On the `generated_sql`, the worker maintains `sql_pos_by_index` (a `sqlIndex -> position` mapping in
`sql_list`). If a `generated_sql` reuses a `sqlIndex` already seen, it is not a new item: it is the
post-loop enrichment coming from the footer trace. The worker then fills the stored item's missing fields
IN PLACE and `continue`s without pushing a second live event. This is the central mechanism that avoids
duplicates on the timeline when the footer trace enriches a SQL already relayed mid-stream (see the
normalization on the `streaming.py` side).

#### Phase two: persistence (best-effort)

After the loop, the worker persists, each step being best-effort: a storage failure NEVER aborts the run,
because the user already has the reply on screen.

- `answer = "".join(answer_parts).strip()`.
- `chat_v5.save_assistant_message(exchange_id, answer, sql_list or None, usage=usage_totals)`. This is
  where `chat_v5` applies `capture.cap_sql_list` just before `json.dumps` (caps mirrored at the write
  point).
- `usage.record_usage(user_id, usage_totals)`: increments the lifetime aggregates plus the current month
  (no-op if `usage_totals` is `None`, run stopped early).
- `chat_traces.save_trace(exchange_id, trace_raw)`: persists the RAW footer trace.
- `artifacts_storage.save_artifacts(exchange_id, user_id, artifacts)` if any artifacts were emitted.

#### The terminal events and the ordering guarantee

- Always first `{"type": "final_answer", "exchangeId": exchange_id, "text": answer}`.
- If `stop_reason == "stopped"`: emits `{"type": "stopped", "exchangeId": exchange_id}`. This is NOT an
  error: the partial reply was persisted, the frontend renders a discreet marker of a stopped generation.
- If another `stop_reason` (timeout/abandoned): emits `{"type": "error", "message": "run_" + stop_reason}`
  and writes `state["error"]`.
- Otherwise: `{"type": "run_done", "status": "success"}`.

The exception handling never leaks agent/SQL/connection internals to the client: it emits
`{"type": "error", "message": "agent_unavailable"}` and sets `state["error"]`.

Finally, the `finally` block marks `done = True` and `finished_at` AFTER appending the terminal events.
This is the ordering guarantee: a poll that sees `done == True` necessarily also sees `final_answer`
followed by `run_done` (or `stopped`, or `error`). There is no lost-final-frame race.

### `_build_screen_block(...)`: screen awareness

Best-effort, never raises. Gated on the frontend's live pointer: we describe ONLY what is actually on
screen, that is, the exchange and tab the user is looking at with the Evidence panel OPEN. No read (and
no block) if the panel is closed. The artifact read is owner-scoped
(`artifacts_storage.read_artifacts(user_id, exchange_id)`). The last `answer` of the history is truncated
at the first `\n\n[SQL` before being summarized. The final block is produced by
`context.build_screen_state(arts, last_answer, active_tab)`.

On the route side, the raw input is sanitized by `_sanitize_screen_context`: a dict with `open: true`, an
`exchange_id` (str/int, bounded to 128 chars) and an `active_tab` restricted to
`("evidence", "chart", "table")`. Everything else degrades to `None`. Since the read is owner-scoped, a
forged `exchange_id` can at worst reveal only the caller's own data.

### `poll(run_id, user_id, cursor)`

Returns `{events, cursor, done, error}` or `None` if the run is unknown or not owned by `user_id` (the
route maps `None` to 404 without revealing which). The event slice AND the `done` flag are read under ONE
single lock acquisition (no lost-final-frame race). It sets `state["last_poll_at"] = now`: this is the
heartbeat the worker uses to detect an abandon. The cursor is an end index: `start` is the sanitized
`cursor` (`int >= 0`, otherwise 0), `new_events = events[start:]`, and the new cursor returned is
`len(events)`. The frontend sends this cursor back on the next poll and therefore never receives the same
event twice.

On the route side, `/chat/poll` reads `run_id` and `cursor` (default 0) from query params, bounds
`run_id` by `_MAX_RUN_ID_LENGTH` and clamps a negative cursor to 0.

### `request_stop(run_id, user_id)`

Owner-scoped and idempotent. It sets `stop_requested = True` on the caller's in-flight run; the worker
sees it between two chunks (`_stop_reason -> "stopped"`), ceases to iterate, persists the partial reply
accumulated and ends cleanly with a `stopped` event. It returns `False` if the run is unknown, already
evicted, or owned by another (the route maps `False` to 404). The stop is therefore cooperative: it kills
nothing, it politely asks the worker to stop at the next chunk boundary.

## Event normalization in `streaming.py`

`run_agent_streamed(project_key, agent_id, messages)` is a GENERATOR: it runs ONE agent completion and
yields normalized, JSON-safe event dicts (one `type` per dict). Instance safety: exactly one agent run
for a valid message, no loop, no retry. The `agent_id` arrives already resolved by the whitelist; nothing
here accepts a raw id from the frontend.

The LLM Mesh call follows the native multi-turn pattern (never `as_langchain_chat_model`, see
[ADR-0006 - Native LLM Mesh calls](../08-decisions/0006-appels-natifs-llm-mesh.md)):

```python
project = dataiku.api_client().get_project(project_key)
completion = project.get_llm(agent_id).new_completion()
for m in messages:
    completion.with_message(m["content"], m["role"])
for chunk in completion.execute_streamed():
    data = getattr(chunk, "data", {}) or {}
```

### Recognition constants

- `_TEXT_CHUNK_TYPES = ("content", "text")`: chunks carrying a reply text delta.
- `_SQL_TOOL_NAME = "semantic-model-query"`: the tool whose output carries the generated SQL. It is a
  frozen span recreated by the Code Agent against a fixed contract; any rename on the agents side would
  break the trace extraction.
- `_MAX_TRACE_DEPTH = 200`: defensive recursion bound for walking the footer trace (a pathologically deep
  trace becomes a no-extraction rather than a `RecursionError`).
- `_AGENT_DONE_KIND = "AGENT_DONE"`: orchestrator event whose `eventData` may relay mid-stream the list of
  generated SQL of the sub-agents, so that a run stopped afterward still persists its SQL.
- `_ARTIFACT_KIND = "ARTIFACT"`; `_ARTIFACT_CHART_TYPES = ("line", "bar", "pie")`.
- `_NARRATION_KIND = "NARRATION"`; `_NARRATION_MAX_CHARS = 280`.
- `_EVENT_PASSTHROUGH_KEYS = ("label", "stepIndex", "stepCount", "agentKey", "status")`: STRICT whitelist
  of `eventData` keys relayed as-is on the `agent_event`. Never the whole dict: the orchestrator payloads
  also carry `agentId / message / instruction / steps / generatedSql`, which must never reach the polled
  timeline. `_EVENT_VALUE_MAX_CHARS = 300` bounds each relayed string.

The footer is recognized by `_is_footer_chunk` either via `data.get("type") == "footer"`, or by
`isinstance(chunk, DSSLLMStreamedCompletionFooter)` when the SDK exposes the class (optional and tolerant
import).

### The yielded event types

For each chunk, `elapsed = round(time.perf_counter() - t0, 2)`. If it is the footer, it is kept and we
`continue`. Otherwise, depending on `data.get("type")`:

- `"event"`: we keep the `eventData` for the SQL fallback. If the `eventKind` is `NARRATION` with a
  non-empty text, we yield `{"type": "narration", "text": text[:280]}` then `continue`. Otherwise we
  build the `agent_event` (`eventKind`, `blockId`, `nextBlockId`, `toolName`, `elapsedSeconds`), enriched
  with the whitelisted keys, and yield it. If the `eventKind` is `AGENT_DONE`, we relay the sub-agents'
  SQL (`eventData.generatedSql`), deduplicated by SQL text. If the `eventKind` is `ARTIFACT`, we yield
  `_normalized_artifact_event(event_data)` when it is not `None`.
- `"content"` / `"text"`: we yield `{"type": "answer_delta", "text": text}` if `text`.
- unknown shape: debug log plus an `agent_event` with `eventKind = "UNKNOWN_CHUNK_TYPE:<type>"` (never
  break the stream).

### The shape of a normalized `generated_sql`

`_normalized_sql_event(item, sql_index)` produces the mandatory keys of the historical shape (`type,
sqlIndex, success, rowCount, sql`) and only adds the optional trust-layer keys (`sqlId, stepIndex,
agentKey, sourceUrl, result`) if they are present (and `result` only if it is a dict). The correlation
tags are accepted in snake_case OR camelCase via `_tag`, because the orchestrator tags in snake_case
(`sql_id/step_index/agent_key`) while the items coming from the trace walker have no correlation key.

### ARTIFACT normalization

`_normalized_artifact_event(event_data)` is strict, pure, never raises. `kind` must be in
`{chart, table, kpi}`, `title` bounded to 200 chars. The DATA is NOT there: only the SPEC travels, the
frontend reuses the `result` of the captured `generated_sql` via `/evidence/meta`. A `chart` requires a
dict `{type in (line,bar,pie), x: string, y: list of strings (max 8, <= 128 chars each)}` plus an
optional `style` (<= 24 chars); a `kpi` requires `kpi.value` string and produces
`{label, value[, delta, delta_pct]}`; a `table` carries only the title. The full artifact pipeline
(event -> normalization -> `webapp_artifacts_v1` -> `/evidence/meta` -> tabs) has its canonical home in
[Evidence Studio and artifacts](05-evidence-and-artifacts.md).

### The footer: post-loop extraction and one-shot merge

Once the footer arrives, `trace = footer_data.get("trace")` and the generator produces its final events:

- SQL: `_find_generated_sql(trace)` walks the nested trace and extracts `{success, row_count, sql[,
  result]}` per output of the `semantic-model-query` tool. `result` is optional and best-effort via
  `capture.extract_result(outputs)`: the rows key not being confirmed on the instance, the capture is
  honest or simply absent. If nothing, fallback `_find_relayed_sql_from_events(seen_event_data)` which
  reads `eventData.generatedSql` from the sub-agent events.
- One-shot merge: we strictly merge against the mid-stream `AGENT_DONE` emissions (the only entries of
  `emitted_by_sql`), consumed via `pop()`. Two DISTINCT trace spans with the same SQL text (a transient
  failure then an identical retry) must each emit their own event; only a relay duplicate is merged. When
  the trace brings the authority the relay lacked (`success`, `rowCount`, or a captured `result`), ONE
  single enrichment event is re-yielded with the SAME `sqlIndex`. On the worker side, this is exactly
  what `sql_pos_by_index` detects to update the item in place without a timeline duplicate.
- Usage: `_find_usage_metadata(trace)` collects all the nested `usageMetadata` dicts,
  `_sum_usage_metadata` sums them into `{promptTokens, completionTokens, totalTokens, estimatedCost}`, and
  we yield `{"type": "usage_summary", **totals}`.
- RAW trace: we yield `{"type": "trace", "trace": trace}` LAST OF ALL, only if a trace exists, for
  persistence only.

> IN FLUX: the exact key of the captured rows (`result`) is not confirmed on the instance.
> `capture.extract_result` is best-effort: the `result` key is simply absent when nothing recognizable is
> found (honest capture, no fabrication). On the Evidence side, this translates into a
> `result_captured: false`.

> IN FLUX: the `dataiku-agents/` folder is being edited live by another engineer. The `eventKind`s emitted
> on the agents side (NARRATION, AGENT_DONE, ARTIFACT) and the SQL correlation tags could evolve. The four
> backend files described here (`stream_manager.py`, `streaming.py`, `context.py`, `discovery.py`) were
> read as-is at the time of writing.

## `context.py`: assembling the multi-turn payload

PURE module (no `dataiku` import, testable outside the DSS runtime). The central strategy: build an
ordered list `{role, content}` made of the prior messages verbatim, then of the current user turn
carrying a compact context block APPENDED AT THE END. The reason for the suffix: small models honor an
instruction placed in the highest-recency slot (the very end of the current message) far better. Burying
the name, the date or the language at the start lets the model forget it.

### `MODEL_MODES` and mode propagation

`MODEL_MODES = ("eco", "medium", "high")`. The mode is relayed to the agent as a compact control token
`⟦owi:mode=<mode>⟧` appended to the current turn; the orchestrator parses and STRIPs it, so it never
reaches the model as part of the question. Absent or unknown, the orchestrator defaults to `"medium"`; on
the route side, an unrecognized `mode` is clamped to `"medium"`. The mode -> loop model table lives on the
agents side (see [Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md) and
[ADR-0009 - Per-mode models](../08-decisions/0009-modeles-par-mode.md)).

### `detect_prompt_language(message, default="fr")`

Deterministically guesses the language (`"fr"` / `"en"`) of the raw message. It runs on the raw current
message (no date prefix that would pollute the heuristic). The logic: if `_FR_ACCENT_RE`
(`[éèêàùçâîôœ]`) matches, it is `"fr"`; otherwise it counts the FR markers (`_FR_RE`) against EN (`_EN_RE`),
matched on WORD BOUNDARIES (`\b`) to avoid substring collisions (the FR `revenu` does not match inside the
EN `revenue`, `add` not inside `address`); a tie or a neutral message like `42` -> `default`. It is a
mirror of the agent's `_detect_lang`, ported to the 3.9 stdlib-only backend, to compute the language ONCE
on the clean message and pass it as an authoritative token.

### `build_user_suffix(...)`

```python
build_user_suffix(full_name, now_dt, webapp_lang=None, prompt_lang=None, mode=None)
```

Produces the compact context block appended at the END of the current message. It carries who is asking,
the date (`_DATE_FMT = "%A, %B %d, %Y at %H:%M"`, C locale so unambiguous English), the configured webapp
language and the carrier rule: the language of THIS message, which the agent must follow, always wins over
the earlier turns and over the webapp language. The control tokens are machine-only:
`⟦owi:mode=<mode>⟧` if `mode in MODEL_MODES`, `⟦owi:lang=<lang>⟧` if `prompt_lang in _LANG_LABEL`. The
produced shape looks like:

```
\n\n[Context - User: <name> · Today: <date> · Web app language: <label>] ⟦owi:mode=…⟧⟦owi:lang=…⟧
IMPORTANT - reply in <plabel>: the SAME language as my message above. The language of my current
message ALWAYS takes priority over earlier turns and over the web-app language.
```

The agent parses then STRIPs the `⟦…⟧` tokens, so they never reach the model as visible text, while the
human language imperative stays the last line of the turn (recency).
`_LANG_LABEL = {"fr": "French", "en": "English"}`.

> Maintenance note: these strings contain a middot character `·` and the delimiters `⟦` `⟧`
> (U+27E6/U+27E7), NOT em dashes. Any byte-level manipulation of `context.py` must be `LC_ALL=C`-safe.

### Screen awareness and multi-turn history

- `build_screen_state(artifacts, last_answer_excerpt=None, active_tab=None)`: compact, bounded description
  of what is on screen (Evidence panel artifacts plus exposed data columns plus the gist of the previous
  reply). Caps: `MAX_SCREEN_ARTIFACTS = 4`, `MAX_SCREEN_COLS = 24`, `SCREEN_ANSWER_EXCERPT_CHARS = 300`.
  The block is framed as GROUNDED PRIOR DATA so it never triggers the honesty firewall (a new figure
  always requires a specialist call).
- `build_completion_messages(history_messages, current_message, user_suffix)`: `history` verbatim plus the
  current turn `{"role": "user", "content": current_message + (user_suffix or "")}`.
- `flatten_exchanges_to_messages(rows, max_messages)`: flattens the chronological exchange rows into
  messages (user then assistant), appending a bounded SQL block (`_format_sql_context`, cap
  `MAX_SQL_CONTEXT_CHARS = 4000`) to the assistant turn when the exchange carries a decoded
  `generated_sql`.
- `exchanges_to_fetch(max_messages)`: number of EXCHANGES to read (2 messages per exchange).

These pure helpers are consumed by `chat_v5.history_messages_for_chain`, which walks the exchange's
ancestor chain via a user-scoped recursive CTE, bounded in depth and in rows (see
[Storage and data model](04-storage-and-data-model.md)). This is what excludes the other branches of the
conversation tree and everything after the branch point.

## `discovery.py`: listing the agents that can be enabled

STRICTLY READ-ONLY module: only listing calls, never create/modify/delete. It serves the admin space to
build the whitelist of agents that can be enabled.

- `AGENT_ID_PREFIX = "agent:"`: a DSS LLM is an agent when its id starts with this prefix (e.g.
  `agent:rNTZ781a`).
- `MAX_PROJECTS = 500`, `MAX_AGENTS = 200`: defensive bounds.
- `list_project_keys()`: projects the webapp identity can see, sorted, bounded (reflects the current
  identity's permissions).
- `list_project_agents(project_key)`: returns `[{agent_id, description}]` for a project's agents, filtering
  `project.list_llms()` on the `agent:`-prefixed ids; `description` is the human label, falling back to the
  id.

These listings feed the admin screen. The admin chooses the agents, persisted in `webapp_settings_v1`. At
runtime, the frontend sends an OPAQUE logical key (`ag_<hash>`) that
`storage.settings.resolve_enabled_agent` resolves into `(project_key, agent_id)`; a forged or disabled key
resolves to `None`. The frontend NEVER sends a raw `agent_id` (non-negotiable rule #4, see
[ADR-0004](../08-decisions/0004-whitelist-agents-serveur.md)).

## Reference JSON shapes

Normalized events on the live timeline (one per entry of the poll's `events[]`):

| Event | Payload |
|---|---|
| `run_started` | `{exchangeId}` |
| `agent_event` | `{eventKind, blockId, nextBlockId, toolName, elapsedSeconds[, label, stepIndex, stepCount, agentKey, status]}` |
| `answer_delta` | `{text}` |
| `narration` | `{text}` (transient, not persisted) |
| `generated_sql` | `{sqlIndex, success, rowCount, sql[, sqlId, stepIndex, agentKey, sourceUrl]}` (without `result` in live) |
| `usage_summary` | `{promptTokens, completionTokens, totalTokens, estimatedCost}` |
| `final_answer` | `{exchangeId, text}` |
| `run_done` / `stopped` / `error` | `{status:"success"}` / `{exchangeId}` / `{message}` |

`/chat/poll` response: `{status:"ok", events:[…], cursor:<int>, done:<bool>, error:<str|null>}`.

`generated_sql` persistence item (to `chat_v5`):
`{sql, success, row_count[, sql_id, step_index, agent_key, source_url, result]}`.

HTTP error codes of the `/chat/start` route: `429 rate_limited`, `503 busy`,
`404 agent_not_enabled`/`run_not_found`, `409 storage_not_configured`,
`500 storage_unavailable`/`agent_unavailable`, `401 unauthenticated`, `400 <ValidationError.code>`. The
full catalog of endpoints is in [API reference](02-api-reference.md).

## Gotchas to know

- No LLM Mesh cancel: the stop is purely cooperative (ceasing to iterate the generator), evaluated between
  chunks. An upstream call that is fully blocked is bounded only by the memory TTL. No watchdog by design.
- Final race closed by ordering: `done` is set AFTER the terminal events, and `poll` reads the slice and
  `done` under a single lock.
- Benign TOCTOU between `can_accept` and the hard cap in `start_run`: assumed and documented; `start_run`
  remains the real gate (double counting plus `CapacityError`).
- The worker has no dedicated branch for `narration`: it goes through the generic live-timeline append.
  Correct but implicit behavior.
- Observed backend = Python 3.9.23 (no FastAPI, no langchain). The Code Agents that emit the `eventKind`s
  run in a Python 3.11 env, outside the backend zip (see
  [ADR-0005](../08-decisions/0005-langgraph-code-agents-python-311.md)).

## See also
- [Runtime flow](../02-architecture/03-runtime-flows.md) - the complete chat turn, seen end to end.
- [Frontend - communication with the backend](../03-frontend/04-backend-communication.md) - the same flow on the client side (polling loop, cursor, error codes).
- [Backend - overview and structure](01-overview-and-structure.md) - where the streaming layer sits in the backend.
- [Backend - API reference](02-api-reference.md) - the HTTP contract of `/chat/start`, `/chat/poll`, `/chat/stop`.
- [Backend - storage and data model](04-storage-and-data-model.md) - the phase-two persistence (`chat_v5`, usage, traces).
- [Backend - Evidence Studio and artifacts](05-evidence-and-artifacts.md) - the artifact pipeline and the `result` capture.
- [Backend - security and validation](06-security-and-validation.md) - payload validation, whitelist, read-only guards.
- [ADR-0002 - Polling-based streaming](../08-decisions/0002-streaming-par-polling.md) - the decision and its rationale.
- [Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md) - what becomes of the `⟦owi:mode=…⟧` token on the agents side.
