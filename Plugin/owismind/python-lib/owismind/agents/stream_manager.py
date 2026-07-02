"""In-process manager for live agent runs, consumed by the browser via polling.

WHY POLLING (and not SSE)
-------------------------
DSS puts an internal nginx in front of every webapp Python backend. A long-lived
``text/event-stream`` response can be buffered by that proxy, so agent events would
reach the browser all at once at the end instead of live. The project's own Dash
WebApp (in production on the same instance) sidesteps this BY DESIGN: it never
exposes a long response to the browser. Instead it runs the agent in a background
thread, accumulates progress in a module-level dict, and the front polls that dict
on a short interval. Each poll is a normal short request the proxy never buffers.

This module ports that proven pattern to the Flask/Vue stack, and ADDS the two
safety nets the Dash version lacks: a concurrency cap (bounded threads) and a TTL
eviction (no orphaned-run memory leak).

FLOW
----
1. ``start_run`` registers a run, spawns ONE daemon worker thread, returns a run_id.
2. The worker iterates ``streaming.run_agent_streamed`` (already-normalised events),
   appends each event to the run's ``events`` list, accumulates the answer + any
   generated SQL, then persists the assistant message (phase two) and marks ``done``.
3. ``poll`` returns the events appended since the caller's cursor, plus ``done``/``error``.

Instance safety: exactly ONE agent run per call (no loop, no retry); a hard global
cap on concurrent runs; TTL eviction of finished/orphaned runs. The agent_id is
resolved server-side from the whitelist BEFORE this is ever called - nothing here
accepts a raw id from the frontend.
"""

import logging
import threading
import time
from uuid import uuid4

from owismind.agents import context, streaming
from owismind.storage import artifacts as artifacts_storage
from owismind.storage import chat_traces, chat_v5, usage

logger = logging.getLogger(__name__)

# --- tuning knobs (instance safety) ------------------------------------------
# Hard ceiling on concurrent in-flight agent runs across the whole backend
# process. A backstop the Dash version lacks: bounds live threads + open LLM Mesh
# connections. Generous for a small user base; raise if genuinely needed.
MAX_CONCURRENT_RUNS = 8

# Keep a finished run readable this long so a late/duplicate poll still gets the
# terminal events instead of a 404. The front stops polling as soon as it sees
# ``done``, so this only covers races.
FINISHED_TTL_SECONDS = 60.0

# Absolute lifetime cap for any run (even one whose browser tab was closed mid-run
# and never polled to completion). Agent runs take ~tens of seconds, so 10 min is
# far above normal and guarantees orphaned runs cannot accumulate in memory.
HARD_TTL_SECONDS = 600.0

# Per-run memory bounds (defense in depth). The run lifetime is already bounded by
# MAX_CONCURRENT_RUNS x HARD_TTL, and the large raw trace is excluded from the live
# list - but these make the per-run bound EXPLICIT so a pathological/buggy agent
# emitting an enormous answer or event flood cannot grow a single run's memory
# without limit. Both are far above any legitimate run (normal runs emit a few
# dozen events and KB-sized answers); terminal events and persistence are never
# dropped, only the live timeline / accumulated answer are capped.
MAX_LIVE_EVENTS = 5000
MAX_ANSWER_CHARS = 1_000_000
# A turn renders at most a handful of artifacts (chart/table specs); bound the
# accumulator so a buggy agent cannot grow it without limit.
MAX_ARTIFACTS_ACCUM = 8

# Cooperative run-time bounds (checked between streamed chunks):
#   - MAX_RUN_SECONDS: a hard wall-clock deadline so one run cannot occupy a worker
#     thread + LLM Mesh connection + concurrency slot indefinitely.
#   - ABANDON_AFTER_SECONDS: if the browser stopped polling (tab closed / navigated
#     away) for this long AFTER it had started polling, the run is treated as abandoned
#     and cut short so its slot is freed instead of running (and billing tokens) for no
#     consumer. A run never yet polled is bounded only by MAX_RUN_SECONDS.
# Limitation: both are evaluated between chunks, so a fully-hung upstream call that never
# yields is still bounded only by the memory TTL - a watchdog thread would be needed for
# that and is intentionally not added here (higher risk to a validated path).
MAX_RUN_SECONDS = 300.0
ABANDON_AFTER_SECONDS = 30.0

# Minimum spacing between two run starts FROM THE SAME USER (anti-spam pre-gate). The
# hard concurrency cap remains the real gate; this only avoids wasted DB writes/auth
# round-trips when a single user hammers /chat/start.
MIN_START_INTERVAL_SECONDS = 1.0

# --- shared state ------------------------------------------------------------
# run_id -> {events, done, error, user_id, started_at, finished_at, last_poll_at}.
# Guarded by _LOCK for every read/write (critical sections are tiny: list append/slice).
_LOCK = threading.Lock()
_RUNS = {}
# user_id -> monotonic timestamp of that user's last run start (per-user rate pre-gate).
_LAST_START_BY_USER = {}


class CapacityError(Exception):
    """Raised by ``start_run`` when too many runs are already in flight."""


def can_accept(user_id):
    """Cheap admission pre-check, called by the route BEFORE any DB write.

    Returns ``(ok, reason)``. It mirrors ``start_run``'s hard concurrency cap so an
    at-capacity request can be rejected before a user message is persisted (avoiding a
    wasted INSERT + auth round-trip), and adds a light per-user spacing gate against
    spam. ``start_run`` still enforces the hard cap, so this is advisory (there is a
    benign TOCTOU window): reason is ``"busy"`` (cap reached) or ``"rate_limited"``.
    """
    now = time.monotonic()
    with _LOCK:
        _evict_stale_locked(now)
        active = sum(1 for s in _RUNS.values() if not s.get("done"))
        if active >= MAX_CONCURRENT_RUNS:
            return False, "busy"
        last = _LAST_START_BY_USER.get(user_id)
        if last is not None and (now - last) < MIN_START_INTERVAL_SECONDS:
            return False, "rate_limited"
        # Reserve this user's spacing slot NOW, under the same lock, so two concurrent
        # /chat/start from the same user cannot both pass the gate (the timestamp was
        # previously written only later in start_run, leaving a race window).
        _LAST_START_BY_USER[user_id] = now
    return True, None


def _stop_reason(run_id, started_at):
    """Return why the worker should cut the run short, else None.

    Priority: an explicit user stop (``"stopped"``) wins over the wall-clock deadline
    (``"timeout"``) and the abandoned-by-browser cut (``"abandoned"``). Evaluated between
    streamed chunks - the official LLM Mesh stream exposes no cancel API, so a cooperative
    stop (simply ceasing to iterate the generator) is the supported way to end it early.
    """
    now = time.monotonic()
    with _LOCK:
        state = _RUNS.get(run_id)
        stop_requested = bool(state.get("stop_requested")) if state else False
        last_poll = state.get("last_poll_at") if state else None
    if stop_requested:
        return "stopped"
    if (now - started_at) > MAX_RUN_SECONDS:
        return "timeout"
    if last_poll is not None and (now - last_poll) > ABANDON_AFTER_SECONDS:
        return "abandoned"
    return None


def _evict_stale_locked(now):
    """Drop finished runs past their TTL and any run past the hard lifetime cap.

    Must be called while holding ``_LOCK``. ``now`` is a ``time.monotonic()`` value.
    """
    stale = []
    for run_id, state in _RUNS.items():
        finished_at = state.get("finished_at")
        started_at = state.get("started_at", now)
        if finished_at is not None and (now - finished_at) > FINISHED_TTL_SECONDS:
            stale.append(run_id)
        elif (now - started_at) > HARD_TTL_SECONDS:
            stale.append(run_id)
    for run_id in stale:
        _RUNS.pop(run_id, None)
    if stale:
        logger.info("stream_manager - evicted %d stale run(s)", len(stale))
    # Keep the per-user rate map bounded: drop timestamps older than the hard lifetime.
    for uid in [u for u, ts in _LAST_START_BY_USER.items() if (now - ts) > HARD_TTL_SECONDS]:
        _LAST_START_BY_USER.pop(uid, None)


def _append_event_locked_free(run_id, event):
    """Append one normalised event to a run's timeline (takes ``_LOCK`` briefly)."""
    with _LOCK:
        state = _RUNS.get(run_id)
        if state is not None:
            state["events"].append(event)


def start_run(project_key, agent_id, message, exchange_id, user_id, parent_exchange_id, history_limit, user_suffix, screen_context=None, prior_recall_enabled=False):
    """Register a run, spawn its worker thread, and return the new ``run_id``.

    ``project_key``/``agent_id`` are the whitelist-resolved target; ``exchange_id``
    is the chat_v5 row to fill in once the answer is ready; ``user_id`` scopes the
    run so only its owner can poll it. ``parent_exchange_id``/``history_limit``/
    ``user_suffix`` let the worker assemble the multi-turn agent context (the ANCESTOR
    CHAIN of this branch + the current turn with its end-of-prompt context block).
    Raises ``CapacityError`` if the global concurrency cap is already reached.
    """
    now = time.monotonic()
    run_id = uuid4().hex
    with _LOCK:
        _evict_stale_locked(now)
        active = sum(1 for s in _RUNS.values() if not s.get("done"))
        if active >= MAX_CONCURRENT_RUNS:
            raise CapacityError(
                "concurrent run cap reached ({})".format(MAX_CONCURRENT_RUNS)
            )
        _RUNS[run_id] = {
            "events": [],
            "done": False,
            "error": None,
            "user_id": user_id,
            "started_at": now,
            "finished_at": None,
            "last_poll_at": None,
            # Set True by request_stop (explicit user stop); the worker sees it between
            # two chunks and cuts the run short cleanly (see _stop_reason -> "stopped").
            "stop_requested": False,
        }
        _LAST_START_BY_USER[user_id] = now

    thread = threading.Thread(
        target=_worker,
        # Pass started_at explicitly so the wall-clock deadline is anchored at
        # registration and never reset by re-reading possibly-evicted run state.
        args=(run_id, project_key, agent_id, message, exchange_id, now,
              user_id, parent_exchange_id, history_limit, user_suffix, screen_context,
              prior_recall_enabled),
        name="owi-agent-run-{}".format(run_id[:8]),
        daemon=True,
    )
    thread.start()
    logger.info(
        "stream_manager - started run_id=%s exchange_id=%s agent_id=%s user_id=%s",
        run_id,
        exchange_id,
        agent_id,
        user_id,
    )
    return run_id


def _build_screen_block(user_id, history, screen_context):
    """The ON-SCREEN context block (best-effort, never raises). Gated on the
    frontend's live pointer: we only describe what is ACTUALLY on screen - the
    exchange + tab the user is viewing with the Evidence panel OPEN. No read (and no
    block) when the panel is closed: nothing is on screen then, and the prior answer
    is already in the replayed history. Owner-scoped artifact read only. Returns ''
    when there is nothing to surface."""
    try:
        if not (isinstance(screen_context, dict) and screen_context.get("open")):
            return ""
        exchange_id = screen_context.get("exchange_id")
        if exchange_id is None:
            return ""
        arts = artifacts_storage.read_artifacts(user_id, exchange_id)
        if not arts:
            return ""
        last_answer = ""
        for m in reversed(history or []):
            if m.get("role") == "assistant" and m.get("content"):
                last_answer = m["content"].split("\n\n[SQL", 1)[0]
                break
        return context.build_screen_state(arts, last_answer, screen_context.get("active_tab"))
    except Exception:
        logger.exception("screen-state assembly failed (non-fatal)")
        return ""


def _worker(run_id, project_key, agent_id, message, exchange_id, started_at,
            user_id, parent_exchange_id, history_limit, user_suffix, screen_context=None,
            prior_recall_enabled=False):
    """Run one agent completion, stream its events into the run, then persist.

    Mirrors the old SSE generator's body but writes into the shared run state
    instead of yielding HTTP frames. Emits the SAME normalised event sequence the
    frontend already understands: run_started, then the agent's own events
    (agent_event / answer_delta / generated_sql / usage_summary), then final_answer
    + run_done - or error. The streamed ``trace`` event (the RAW footer trace) is
    captured for storage but never added to the live timeline. Phase two persists the
    answer + any generated SQL AND that raw trace for later lazy reads; a storage
    failure there never aborts the run (the user still gets the answer). The agent_id
    is never surfaced to the client.
    """
    answer_parts = []
    answer_chars = 0
    answer_truncated = False
    live_events = 0
    sql_list = []
    # Chart/table specs the orchestrator asked the UI to render (persistence-only:
    # surfaced after the run via /evidence/meta, never on the live polled timeline).
    artifacts = []
    # sqlIndex -> position in sql_list. A generated_sql event re-using an already-seen
    # sqlIndex is streaming's post-loop ENRICHMENT (trace authority merged into an item
    # first relayed mid-stream by AGENT_DONE): it updates the stored item in place and
    # is NEVER appended to the live timeline a second time.
    sql_pos_by_index = {}
    trace_raw = None
    # The run's footer token/cost totals, captured for persistence (chat_v5 columns +
    # the users/monthly aggregates). Stays None on an early-stopped run (no footer).
    usage_totals = None
    stop_reason = None
    _append_event_locked_free(run_id, {"type": "run_started", "exchangeId": exchange_id})
    # Assemble the multi-turn payload: the ancestor chain of THIS branch (verbatim) + the
    # current user turn with its end-of-prompt context block (name/date/language). The
    # chain walks up from the parent exchange, so messages after the branch point (or in
    # other branches) are excluded.
    # Best-effort: if the history read fails, degrade to the current turn alone (never
    # break the chat).
    try:
        history, prior_results = chat_v5.chain_context_for_agent(
            user_id, parent_exchange_id, history_limit
        )
    except Exception:
        logger.exception("history assembly failed; sending current turn only")
        history, prior_results = [], []
    # Screen awareness: a bounded "ON SCREEN NOW" block (the artifacts the user is
    # viewing + the gist of the last answer) so follow-ups like "explain the chart" /
    # "add the forecast" are grounded. Only when the Evidence panel is actually open
    # (one owner-scoped O(1) read, skipped otherwise). Placed BEFORE the language
    # suffix so the reply-language imperative stays the last line of the turn (recency).
    screen_block = _build_screen_block(user_id, history, screen_context)
    # Prior-results recall: a short [PRIOR DATA] index for the model + the
    # machine token the orchestrator parses (and strips before any LLM call).
    # Gated per agent (same opt-in as the mode token): for a non-token-aware
    # agent the payload would leak into its prompt as raw text.
    # Best-effort: on failure the turn simply behaves as before the feature.
    prior_block = ""
    if prior_recall_enabled:
        try:
            prior_block = context.build_prior_data_block(prior_results)
        except Exception:
            logger.exception("prior-data block assembly failed (non-fatal)")
    agent_messages = context.build_completion_messages(
        history, message, screen_block + prior_block + (user_suffix or ""))
    try:
        for event in streaming.run_agent_streamed(project_key, agent_id, agent_messages):
            # Cooperative stop between chunks: hard deadline reached, or the browser
            # abandoned the run (stopped polling). Frees the slot/thread/LLM connection.
            stop_reason = _stop_reason(run_id, started_at)
            if stop_reason:
                logger.warning(
                    "stream_manager - cutting run_id=%s short (%s)", run_id, stop_reason
                )
                break
            etype = event.get("type")
            if etype == "answer_delta":
                # Accumulate for persistence, but cap total size so a runaway agent
                # cannot grow this string (and the stored column) without bound.
                text = event.get("text", "") or ""
                if answer_chars < MAX_ANSWER_CHARS:
                    answer_parts.append(text)
                    answer_chars += len(text)
                elif not answer_truncated:
                    answer_truncated = True
                    logger.warning(
                        "stream_manager - answer exceeded %d chars, truncating run_id=%s",
                        MAX_ANSWER_CHARS,
                        run_id,
                    )
            elif etype == "generated_sql":
                # Persistence path - the ENRICHED item (correlation tags + captured
                # result when present). Bounded at the write point: chat_v5 applies
                # capture.cap_sql_list right before json.dumps (mirror caps).
                item = {
                    "sql": event.get("sql"),
                    "success": event.get("success"),
                    "row_count": event.get("rowCount"),
                }
                # Optional trust-layer keys - copied only when present, so items from
                # pre-trust-layer runs keep their exact historical shape.
                for event_key, item_key in (
                    ("sqlId", "sql_id"),
                    ("stepIndex", "step_index"),
                    ("agentKey", "agent_key"),
                    ("sourceUrl", "source_url"),
                    ("result", "result"),
                ):
                    value = event.get(event_key)
                    if value is not None:
                        item[item_key] = value
                index = event.get("sqlIndex")
                position = sql_pos_by_index.get(index)
                if position is not None:
                    # Enrichment re-emission (same sqlIndex): fill the fields the
                    # stored item lacked; no new entry, no second live timeline push.
                    stored = sql_list[position]
                    for key, value in item.items():
                        if value is not None and stored.get(key) is None:
                            stored[key] = value
                    continue
                if index is not None:
                    sql_pos_by_index[index] = len(sql_list)
                sql_list.append(item)
                # The live, polled copy stays LIGHT: captured result rows are
                # persistence-only (read back via /evidence/meta, never /chat/poll).
                event = {k: v for k, v in event.items() if k != "result"}
            elif etype == "usage_summary":
                # Capture the run's token/cost totals for persistence. Does NOT
                # continue: the event still falls through to the live timeline so the
                # front shows the usage during the run (the reducer already reads it).
                usage_totals = {
                    "promptTokens": event.get("promptTokens"),
                    "completionTokens": event.get("completionTokens"),
                    "totalTokens": event.get("totalTokens"),
                    "estimatedCost": event.get("estimatedCost"),
                }
            elif etype == "artifact":
                # Chart/table SPEC (kind/title/chart) the orchestrator emitted. The
                # ARTIFACT agent_event already gave the live timeline label; here we
                # only capture the spec for persistence (the rows are surfaced via
                # /evidence/meta after the run). Bounded; not added to the live list.
                if len(artifacts) < MAX_ARTIFACTS_ACCUM:
                    spec = {
                        "kind": event.get("kind"),
                        "title": event.get("title"),
                        "chart": event.get("chart"),
                    }
                    if event.get("kpi") is not None:
                        spec["kpi"] = event.get("kpi")
                    # Optional metadata + per-artifact SQL binding (additive).
                    for key in ("description", "sql_id"):
                        if event.get(key) is not None:
                            spec[key] = event.get(key)
                    artifacts.append(spec)
                continue
            elif etype == "trace":
                # The RAW footer trace is for PERSISTENCE only - capture it but do
                # NOT add it to the live timeline (it can be large; the front shows
                # only the ephemeral eventKind steps live, never the stored trace).
                trace_raw = event.get("trace")
                continue
            # Live timeline append, bounded: stop growing the polled list past the
            # cap (the terminal events below are always appended). Normal runs emit a
            # few dozen events, far under MAX_LIVE_EVENTS.
            if live_events < MAX_LIVE_EVENTS:
                _append_event_locked_free(run_id, event)
                live_events += 1

        answer = "".join(answer_parts).strip()
        # Phase two: persist whatever we have (full answer on a normal run, partial on an
        # early stop), including the run's token/cost usage (None on an early stop with no
        # footer). A storage failure here must not abort the run - the user already has the
        # answer on screen.
        try:
            chat_v5.save_assistant_message(
                exchange_id, answer, sql_list or None, usage=usage_totals
            )
        except Exception:
            logger.exception(
                "stream_manager - failed to persist assistant message run_id=%s", run_id
            )

        # Increment the per-user lifetime + current-month usage aggregates. The per-exchange
        # usage on chat_v5 (just written) is the source of truth; these denormalised
        # accelerators power the per-user monthly quota. Best-effort: a failure here is
        # logged and swallowed - it must never affect the answer, and the aggregates can be
        # rebuilt from chat_v5. No-op when no usage was captured (early-stopped run).
        try:
            usage.record_usage(user_id, usage_totals)
        except Exception:
            logger.exception(
                "stream_manager - failed to record usage aggregates run_id=%s", run_id
            )

        # Persist the RAW end-of-stream footer trace for this exchange. Also best-effort:
        # a storage failure here must never affect the answer on screen (the trace is
        # simply lost). On an early stop the footer never arrived, so trace_raw is None.
        try:
            chat_traces.save_trace(exchange_id, trace_raw)
        except Exception:
            logger.exception(
                "stream_manager - failed to persist trace (trace lost) run_id=%s", run_id
            )

        # Persist this exchange's rendered-artifact specs (chart/table) so the panel
        # can show them on reload via /evidence/meta. Best-effort: a failure here must
        # never affect the answer on screen. No-op when the run emitted no artifact.
        try:
            if artifacts:
                artifacts_storage.save_artifacts(exchange_id, user_id, artifacts)
        except Exception:
            logger.exception(
                "stream_manager - failed to persist artifacts run_id=%s", run_id
            )

        _append_event_locked_free(
            run_id, {"type": "final_answer", "exchangeId": exchange_id, "text": answer}
        )
        if stop_reason == "stopped":
            # Explicit USER stop: NOT an error. The partial answer was just persisted;
            # emit a clean terminal `stopped` event so the front renders the partial
            # answer + a discreet "generation stopped" marker (never an error toast).
            _append_event_locked_free(
                run_id, {"type": "stopped", "exchangeId": exchange_id}
            )
            logger.info(
                "stream_manager - stopped by user run_id=%s exchange_id=%s answer_len=%d sql_count=%d",
                run_id,
                exchange_id,
                len(answer),
                len(sql_list),
            )
        elif stop_reason:
            # Cut short by a safety bound (timeout/abandoned): surface a terminal error so
            # a still-watching client stops cleanly, and record it on the run state.
            _append_event_locked_free(
                run_id, {"type": "error", "message": "run_" + stop_reason}
            )
            with _LOCK:
                state = _RUNS.get(run_id)
                if state is not None:
                    state["error"] = "run_" + stop_reason
            logger.info(
                "stream_manager - ended run_id=%s exchange_id=%s early (%s) answer_len=%d sql_count=%d",
                run_id,
                exchange_id,
                stop_reason,
                len(answer),
                len(sql_list),
            )
        else:
            _append_event_locked_free(run_id, {"type": "run_done", "status": "success"})
            logger.info(
                "stream_manager - done run_id=%s exchange_id=%s answer_len=%d sql_count=%d",
                run_id,
                exchange_id,
                len(answer),
                len(sql_list),
            )
    except Exception:
        # Never leak agent/SQL/connection internals to the client.
        logger.exception(
            "stream_manager - agent run failed run_id=%s exchange_id=%s",
            run_id,
            exchange_id,
        )
        _append_event_locked_free(run_id, {"type": "error", "message": "agent_unavailable"})
        with _LOCK:
            state = _RUNS.get(run_id)
            if state is not None:
                state["error"] = "agent_unavailable"
    finally:
        # Mark terminal AFTER the terminal events are appended, so a poll that sees
        # done == True is guaranteed to also see final_answer/run_done (or error).
        with _LOCK:
            state = _RUNS.get(run_id)
            if state is not None:
                state["done"] = True
                state["finished_at"] = time.monotonic()


def poll(run_id, user_id, cursor):
    """Return events appended since ``cursor`` for a run the caller owns.

    Returns ``{events, cursor, done, error}`` or ``None`` if the run is unknown or
    not owned by ``user_id`` (the route maps None to a 404 without revealing which).
    The events slice and the ``done`` flag are read under one lock acquisition, so a
    ``done`` result always includes every terminal event (no lost-final-frame race).
    """
    now = time.monotonic()
    with _LOCK:
        _evict_stale_locked(now)
        state = _RUNS.get(run_id)
        if state is None or state.get("user_id") != user_id:
            return None
        # Heartbeat: the worker uses this to detect an abandoned run (poll stopped).
        state["last_poll_at"] = now
        events = state["events"]
        start = cursor if isinstance(cursor, int) and cursor >= 0 else 0
        new_events = events[start:]
        return {
            "events": list(new_events),
            "cursor": len(events),
            "done": bool(state.get("done")),
            "error": state.get("error"),
        }


def request_stop(run_id, user_id):
    """Flag a run for cooperative early stop, owner-scoped. Returns True if applied.

    Sets ``stop_requested`` on the caller's OWN in-flight run; the worker sees it between
    two streamed chunks (``_stop_reason`` -> ``"stopped"``), stops iterating, persists
    whatever partial answer accumulated, and ends the run cleanly with a terminal
    ``stopped`` event. Returns False when the run is unknown, already evicted, or owned by
    someone else (the route maps False to a 404 without revealing which) - all safe
    no-ops, since such a run is already finished or never the caller's. Idempotent.
    """
    with _LOCK:
        state = _RUNS.get(run_id)
        if state is None or state.get("user_id") != user_id:
            return False
        state["stop_requested"] = True
    logger.info("stream_manager - stop requested run_id=%s user_id=%s", run_id, user_id)
    return True
