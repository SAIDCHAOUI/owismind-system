# ADR-0002 - Streaming by polling (no SSE)

> Audience: developer. Last updated: 2026-06-18. Summary: why OWIsMind streams the agent's
> progress via polling-through-a-thread (`/chat/start` + `/chat/poll`) instead of SSE, given that the
> internal DSS nginx proxy buffers long HTTP responses.

## Status

Accepted and VALIDATED in DSS. This is the production chat transport. The first SSE implementation was
tested and then abandoned on the real instance.

## Context and problem

OWIsMind wants to display the agent's progress LIVE: the execution timeline of steps (routing, calling a
sub-agent, SQL execution, rendering an artifact) must appear as it happens while the Code Agent works,
not all at once at the end.

The first implementation used Server-Sent Events (SSE): a `/chat/stream` route returned a long Flask
response (`Response(stream_with_context(...), mimetype="text/event-stream")`) with the usual
anti-buffering headers (`Cache-Control: no-cache`, `X-Accel-Buffering: no`, `Connection: keep-alive`),
emitting `data: {json}\n\n` frames.

Tested in DSS, this approach failed: the response and ALL the eventKind arrived in a single block at the
end, never as they happened. Yet the backend was indeed yielding continuously (the cursor advances
correctly once on polling): it was the long HTTP transport that was being held back and delivered all at
once.

The cause: DSS places an internal nginx in front of EVERY webapp backend. This proxy buffers the
response, and the `X-Accel-Buffering: no` header is not guaranteed to be honored from a standard webapp
backend. There is no official documentation or example of SSE from a standard DSS webapp backend. The
workaround could therefore not come from a header setting.

## Decision

Drop SSE and adopt the polling-through-a-thread pattern, copied from the client's production Dash
(`old_webapp_in_dash/`) which runs on the SAME DSS instance and never has this problem: it NEVER exposes
a long HTTP response, so it bypasses buffering BY DESIGN.

The transport rests on three pieces:

1. The agent run executes inside a daemon `threading.Thread` (the `_worker` function in
   `agents/stream_manager.py`), and its progress accumulates in a module-level `_RUNS` dict protected by
   `_LOCK` (a `threading.Lock`).
2. Three short routes replace the former `/chat/stream`:
   - `POST /chat/start`: persists the user message, starts the worker, returns `{run_id, exchange_id}`;
   - `GET /chat/poll?run_id=&cursor=`: returns the events added since the `cursor` plus the
     `done`/`error` flags;
   - `POST /chat/stop`: requests a cooperative stop of the caller's run.
3. The frontend (`composables/useChatStream.js`) polls `/chat/poll` every ~500 ms
   (`POLL_INTERVAL_MS = 500`) until it receives `done`. Each poll is a short request that the proxy does
   not buffer.

The run is launched via `stream_manager.start_run(...)`: it generates an opaque `run_id` (`uuid4().hex`),
registers the state under `_LOCK`, spawns the daemon thread, and returns the `run_id`. The `agent_id` is
resolved server-side from the whitelist BEFORE this call: the `stream_manager` never receives a raw id
from the frontend (see [ADR-0004](0004-whitelist-agents-serveur.md)).

## Diagram

The canonical schema of the polling transport (thread worker + `_RUNS` dict + `/chat/poll` loop at 500 ms
+ cursor) lives in [Backend - streaming and runs](../04-backend/03-streaming-and-runs.md). This ADR does
not redraw it. In one sentence: the browser launches the run via `POST /chat/start`, the daemon worker
accumulates normalized events in `_RUNS[run_id]["events"]`, and the browser repeatedly requests the
`events[cursor:]` slice via `GET /chat/poll` until `done`.

## Rationale

- The internal DSS nginx proxy is out of our control; no header setting guarantees that a long response
  will not be buffered. The only guarantee is to NEVER expose a long HTTP response.
- The pattern is not an invention: it is PROVEN in production on the same instance by the client's Dash.
  Porting it was a minimal-risk choice rather than a gamble.
- Each poll is a short request (measured at 3-4 ms in DSS), immune to buffering. The cursor makes it
  possible to return only the new events, so the cost per poll stays constant and low.

## Guardrails added (absent from the production Dash)

The port ADDS several safety nets that the Dash version did not have, to protect the shared DSS instance.
Constants defined at the top of `agents/stream_manager.py`:

| Guardrail | Constant / mechanism | Effect |
|---|---|---|
| Concurrency cap | `MAX_CONCURRENT_RUNS = 8` | Global ceiling of in-flight runs; beyond it, `/chat/start` returns 503 `busy`. |
| Eviction of finished runs | `FINISHED_TTL_SECONDS = 60.0` | A finished run stays readable for 60 s (covers a late/duplicate poll) then is evicted. |
| Eviction of orphan runs | `HARD_TTL_SECONDS = 600.0` | Absolute lifetime cap: a tab closed mid-run never leaks in memory. |
| Owner scoping | `user_id` field in `_RUNS[run_id]` | A run is only pollable by its owner; otherwise `poll` returns `None` (404 at the route, without revealing the cause). |
| No loss of the final frame | `done` set AFTER the terminal events, slice+done read under ONE lock | A poll that sees `done == True` is guaranteed to also see `final_answer`/`run_done` (or `error`). |
| Per-user pre-gate | `MIN_START_INTERVAL_SECONDS = 1.0` (`can_accept`) | Minimum spacing between two `start` calls from the same user (anti-spam), reserved under lock to close the race. |
| Per-run memory bounds | `MAX_LIVE_EVENTS = 5000`, `MAX_ANSWER_CHARS = 1_000_000`, `MAX_ARTIFACTS_ACCUM = 8` | A buggy agent cannot grow a run without limit (the terminal events are always still emitted). |
| Deadline and abandonment | `MAX_RUN_SECONDS = 300.0`, `ABANDON_AFTER_SECONDS = 30.0` | Hard wall-clock limit, and a cutoff if the browser stopped polling after having started (frees the slot/thread/connection). |

The clock used everywhere is `time.monotonic()` (never a wall-clock date): the TTLs and deadlines stay
correct even if the system time shifts. The concurrency cap is re-validated live in `start_run`
(`can_accept` is only an advisory pre-check, with a benign TOCTOU window).

## Cooperative stop

The LLM Mesh stream API exposes NO cancellation API. The stop is therefore cooperative: `request_stop`
sets `stop_requested = True` on the caller's run; the worker observes this flag BETWEEN two streamed
chunks (`_stop_reason` returns `"stopped"`), stops iterating the generator, persists the partial already
accumulated, then terminates cleanly with a `stopped` terminal event (not an error). A direct consequence
of the transport: the stop can only cut between two chunks, not in the middle of a blocking call.

The instant feel on the user's side comes from the frontend: `chat.stopGeneration()` applies an optimistic
`stopping`/`stopped` state right away and sends `POST /chat/stop` on a best-effort basis, while the
backend persists its own partial. The detail of this stop loop lives in
[Backend - streaming and runs](../04-backend/03-streaming-and-runs.md) and
[Frontend - communication with the backend](../03-frontend/04-backend-communication.md).

## Frontend-side resilience

`useChatStream.js` treats a failed poll as transient: the DSS proxy can blip on an isolated poll while the
worker continues. A failure is retried with backoff (`MAX_POLL_FAILURES = 5`,
`MAX_BACKOFF_MS = 5000`). Only the TERMINAL codes (`run_not_found`, `invalid_run_id`, `unauthenticated`)
stop the loop cleanly (for example after a backend restart that loses the in-memory `_RUNS`, the run is
treated as recoverable, not as a crash).

## Consequences

Positive:
- Transport proven in DSS: `/chat/poll` responds in 3-4 ms (zero buffering), the cursor advances during
  the run (`0 -> 1 -> 3 -> 5 -> ...`), the multi-agent flow works.
- No long HTTP response exposed, hence no proxy buffering surface; the guardrails above make the run
  bounded and safe for the shared instance.

Negative:
- No word-by-word typing for the text answer. The agent is structured and its prose often lands in a block
  at the end: the live content that is genuinely usable is the TIMELINE of steps, not the prose typing out
  letter by letter.
- The cooperative stop can only cut between two chunks (see above).
- The `_RUNS` state lives in the backend process memory: a backend restart loses the in-flight runs (the
  frontend handles it via the terminal code `run_not_found` / `run_lost`).

> IN FLUX: the polling model + in-memory `_RUNS` assumes a single webapp backend process. Scaling up to
> multi-process or multi-instance would require shared run storage (not implemented).

## Rejected alternatives

- SSE (`text/event-stream` + `X-Accel-Buffering: no`): buffered by the internal DSS nginx, everything
  arrives in a block at the end. This was the initial implementation, abandoned after the DSS test.
- `EventSource` on the browser side: limited to GET, and the start message (with the turn context) is too
  long for a URL. The frontend therefore reads via `fetch` (POST `/chat/start`, then GET `/chat/poll`),
  never via `EventSource`.
- WebSockets: not supported by the standard DSS webapp backend model (same transport constraint as SSE, a
  larger surface, no official example). The polling pattern, by contrast, is already validated in
  production on the same instance.

## See also

- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - the canonical home of
  the polling diagram, the detail of `stream_manager` (worker, `_RUNS`, caps, stop).
- [Runtime flows overview](../02-architecture/03-runtime-flows.md) - the full chat turn, from the
  frontend to the worker and back.
- [Frontend - communication with the backend](../03-frontend/04-backend-communication.md) - the
  client-side polling loop, the error codes, the optimistic stop.
- [Backend - API reference](../04-backend/02-api-reference.md) - the exact payloads of `/chat/start`,
  `/chat/poll`, `/chat/stop`.
- [ADR-0004 - Server-side agent whitelist](0004-whitelist-agents-serveur.md) - why the `agent_id` is
  resolved server-side before the worker starts.
- [ADR index](README.md) - back to the list of architecture decisions.
