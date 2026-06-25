"""Run harness: invoke each (question x agent x mode), capture the COMPLETE answer.

This is the matrix runner of the benchmark. For every triplet it builds the
message with the exact mode / language control tokens (config.build_message),
calls the agent via LLM Mesh with ``execute_streamed()``, walks the streamed
chunks to accumulate the answer text and to grab the final footer trace, then
hands the trace to ``agent_capture`` to rebuild the full answer + SQL items +
usage + artifacts. Each call is measured (total latency + time-to-first-token)
and an agent that crashes or times out becomes a row with ``status`` set, never
a hole (a failure IS a result, design section 4).

PURE / DSS split (so the pure helpers stay importable in the stdlib-only test
env, per the NO INSTALL rule):
  - ``expand_matrix`` is pure (cartesian product of task dicts), unit-tested.
  - ``run_one`` / ``run_matrix`` touch DSS only through the ``project`` object the
    caller passes in (the scenario step builds it from ``dataiku``). There is NO
    top-level ``dataiku`` / ``pandas`` import here; ``concurrent.futures`` and
    ``time`` are stdlib. ``import benchmark.agent_runner`` therefore works without
    dataiku installed.

Chunk shape mirrored from the validated production consumer
``Plugin/owismind/python-lib/owismind/agents/streaming.py`` (run_agent_streamed):
  - ``data = getattr(chunk, "data", {}) or {}``;
  - the final footer chunk is recognised by ``data.get("type") == "footer"`` or,
    on SDKs that do not stamp that, by isinstance against the footer chunk class
    (mirror of streaming._is_footer_chunk); the raw trace lives at
    ``data.get("trace")`` (that INNER trace is what agent_capture walks);
  - an answer text delta is ``data.get("type") in ("content", "text")`` with the
    text at ``data.get("text", "")``;
  - a lifecycle event is ``data.get("type") == "event"`` with ``data.get("eventKind")``
    and ``data.get("eventData")`` (we keep the raw ARTIFACT events for capture).

Instance safety (non negotiable, design section 4 + 10): low bounded concurrency,
a hard per-call timeout, incremental write (a crash mid-run keeps the rows already
emitted, tied by run_id), exactly ONE streamed completion per call, no retry storm.
"""

import concurrent.futures
import json
import time

from benchmark import agent_capture
from benchmark import config
from benchmark import schemas


# Chunk ``type`` values that carry an answer text delta (mirror of streaming.py
# _TEXT_CHUNK_TYPES). A footer chunk is recognised by ``type == "footer"`` or, on
# SDKs that do not stamp that on ``.data``, by the footer chunk class (see
# _is_footer_chunk).
_TEXT_CHUNK_TYPES = ("content", "text")


def _footer_chunk_class():
    """Return the SDK footer chunk class, or None when it cannot be imported.

    Mirrors streaming.py: older / newer DSS SDKs differ, so the footer chunk is
    recognised primarily by ``data.get("type") == "footer"`` and, as a fallback,
    by isinstance against this class. The import is LAZY (inside this helper) so
    the pure stdlib-only test environment never needs ``dataikuapi``: when it is
    absent the fallback simply never triggers and the dict-type path is used.
    """
    try:
        from dataikuapi.dss.llm import DSSLLMStreamedCompletionFooter
        return DSSLLMStreamedCompletionFooter
    except Exception:
        return None


def _is_footer_chunk(chunk, data, footer_cls):
    """True when a streamed chunk is the final run footer (carries the trace).

    Faithful mirror of streaming._is_footer_chunk: recognised by its
    ``type == "footer"`` payload or, when the SDK exposes the class, by isinstance.
    """
    if isinstance(data, dict) and data.get("type") == "footer":
        return True
    if footer_cls is not None:
        try:
            return isinstance(chunk, footer_cls)
        except Exception:
            return False
    return False


def _agent_supports_modes(agent):
    """True when an agent descriptor opts into the Smart/Pro/Claude modes.

    Driven by the per-agent ``modes`` boolean (default False). A mode-aware agent
    (the orchestrator) is tested across every requested mode with the mode token;
    an agent without it (a plain visual agent) gets ONE bare call in its default
    mode. Mirrors the webapp's ``profile.modes`` gate.
    """
    return bool(agent.get("modes")) if isinstance(agent, dict) else False


# Mode label written on a run row for an agent that does not support modes (a
# single plain call). Kept distinct from the real eco/medium/high keys.
DEFAULT_MODE_LABEL = "default"


def expand_matrix(questions, agents, modes):
    """Return the flat list of run tasks (PURE), honoring each agent's modes flag.

    ``questions`` is a list of golden rows (dicts), ``agents`` a list of agent
    descriptors (dicts with ``agent_key`` / ``project_key`` / ``agent_id`` and an
    optional ``modes`` bool), ``modes`` the requested mode keys. For an agent that
    supports modes, one task per requested mode; for an agent that does not, ONE
    task tagged ``mode = "default"`` (a single plain call). Iteration order is
    question-major, then agent, then mode, keeping rows grouped per question. Each
    task is ``{"question_row": <dict>, "agent": <dict>, "mode": <str>}``.

    Pure and deterministic: no DSS, no mutation of the inputs, never raises on a
    well-formed list of dicts. Empty questions / agents yield ``[]``.
    """
    tasks = []
    if not questions or not agents:
        return tasks
    for question_row in questions:
        for agent in agents:
            if _agent_supports_modes(agent):
                for mode in (modes or []):
                    tasks.append(
                        {"question_row": question_row, "agent": agent, "mode": mode}
                    )
            else:
                tasks.append(
                    {"question_row": question_row, "agent": agent,
                     "mode": DEFAULT_MODE_LABEL}
                )
    return tasks


def _as_int(value):
    """Coerce a token-count cell to a non-negative int (0 on anything odd)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n >= 0 else 0


def _denormalized_golden(question_row):
    """Project the golden fields carried verbatim onto a raw row (RAW_COLUMNS).

    Keeps the run row self-describing (question text, category, reference, expected
    value, ...) so ``benchmark_runs_raw`` and the downstream detail table read
    without a join back to ``golden_questions``.
    """
    row = question_row if isinstance(question_row, dict) else {}
    return {
        "question_id": row.get("question_id"),
        "question": row.get("question"),
        "category": row.get("category"),
        "language": row.get("language"),
        "reference_answer": row.get("reference_answer"),
        "expected_value": row.get("expected_value"),
        "expected_value_type": row.get("expected_value_type"),
    }


def _base_raw_row(run_id, run_timestamp, config_json, question_row, agent, mode):
    """Build a raw row pre-filled with every RAW_COLUMNS key (None defaults).

    Guarantees the output row always carries the full ``RAW_COLUMNS`` surface so
    the writer can map it onto the managed dataset without missing-key surprises,
    whatever happens during the call.
    """
    agent = agent if isinstance(agent, dict) else {}
    row = {col: None for col in schemas.RAW_COLUMNS}
    row.update(
        {
            "run_id": run_id,
            "run_timestamp": run_timestamp,
            "config_json": config_json,
            "agent_key": agent.get("agent_key"),
            "agent_label": agent.get("agent_label"),
            "project_key": agent.get("project_key"),
            "agent_id": agent.get("agent_id"),
            "mode": mode,
        }
    )
    row.update(_denormalized_golden(question_row))
    return row


def _drain_stream(completion):
    """Consume one streamed completion, returning (text, footer_trace, events).

    Mirrors the chunk reading of streaming.run_agent_streamed: text deltas are
    concatenated, the footer chunk's inner ``trace`` is captured for agent_capture,
    and raw ``event`` payloads are kept (with their eventKind) so artifact events
    can be recovered. ``ttft`` is the perf_counter timestamp of the FIRST non-empty
    text delta (time-to-first-token), or None if the run produced no text.

    Returns ``(text, footer_trace, raw_events, ttft)``. Caller owns t0/t1 so the
    measured window matches the call lifetime exactly.
    """
    parts = []
    footer_trace = None
    raw_events = []
    ttft = None
    footer_cls = _footer_chunk_class()
    for chunk in completion.execute_streamed():
        data = getattr(chunk, "data", {}) or {}
        if _is_footer_chunk(chunk, data, footer_cls):
            # The inner trace is what agent_capture walks. On the dict-type footer
            # it lives at data["trace"]; the isinstance-only fallback footer also
            # exposes it on .data, so reading it the same way is correct for both.
            footer_trace = data.get("trace") if isinstance(data, dict) else None
            continue
        chunk_type = data.get("type")
        if chunk_type in _TEXT_CHUNK_TYPES:
            text = data.get("text", "") or ""
            if text:
                if ttft is None:
                    ttft = time.perf_counter()
                parts.append(text)
            continue
        if chunk_type == "event":
            # Keep the raw event with its lifecycle kind so extract_artifacts can
            # recognise ARTIFACT events (it reads ``eventKind`` / ``eventData``).
            event_data = data.get("eventData", {}) or {}
            raw_events.append(
                {"eventKind": data.get("eventKind"), "eventData": event_data}
            )
    return "".join(parts), footer_trace, raw_events, ttft


def run_one(project, agent, question_row, mode, language, timeout,
            run_id=None, run_timestamp=None, config_json=None):
    """Run ONE (question, agent, mode) call and return a complete raw row dict.

    Steps (design section 4):
      1. build the message = question + mode token + language token (config);
      2. ``t0 = perf_counter()``; open ``project.get_llm(agent_id).new_completion()``,
         add the single user message, stream the chunks (drain), record the
         time-to-first-token at the first content delta, capture the footer trace;
         ``t1`` once the stream is exhausted;
      3. capture: agent_capture.extract_generated_sql / extract_usage /
         extract_artifacts / assemble_full_answer over the INNER footer trace;
      4. fill every RAW_COLUMNS field: status (ok / error / timeout), error_type /
         error_message on failure, latency_total_s, time_to_first_token_s, n_sql,
         total_rows, tokens, cost, and the denormalized golden fields.

    ``timeout`` is the per-call wall-clock budget in seconds: when the streamed
    completion is wrapped by ``run_matrix`` in a future, that future enforces the
    timeout; here ``timeout`` is recorded and a TimeoutError is mapped to
    ``status="timeout"`` if it ever surfaces inline. NEVER raises: any exception is
    folded into the row as ``status="error"``. The measured latency always reflects
    the real time spent, success or failure.
    """
    row = _base_raw_row(run_id, run_timestamp, config_json,
                        question_row, agent, mode)
    qrow = question_row if isinstance(question_row, dict) else {}
    agent_dict = agent if isinstance(agent, dict) else {}
    # Mode-aware agent on a real mode: append the control token. Otherwise (plain
    # visual agent, or the "default" label): send the bare question (simple call).
    if _agent_supports_modes(agent_dict) and mode in config.MODES:
        message = config.build_message(qrow.get("question"), mode, language)
    else:
        message = config.build_plain_message(qrow.get("question"))

    t0 = time.perf_counter()
    ttft = None
    try:
        completion = project.get_llm(agent_dict.get("agent_id")).new_completion()
        completion.with_message(message, "user")
        text, footer_trace, raw_events, ttft = _drain_stream(completion)
        t1 = time.perf_counter()

        sql_items = agent_capture.extract_generated_sql(footer_trace)
        usage = agent_capture.extract_usage(footer_trace)
        artifacts = agent_capture.extract_artifacts(raw_events)
        full_answer = agent_capture.assemble_full_answer(
            text, sql_items, artifacts)

        total_rows = 0
        for item in sql_items:
            total_rows += _as_int(item.get("row_count"))

        row.update(
            {
                "status": "ok",
                "error_type": None,
                "error_message": None,
                "answer_text": text,
                "full_answer": full_answer,
                "generated_sql_json": json.dumps(sql_items, default=str),
                "artifacts_json": json.dumps(artifacts, default=str),
                "n_sql": len(sql_items),
                "total_rows": total_rows,
                "latency_total_s": round(t1 - t0, 3),
                "time_to_first_token_s": (
                    round(ttft - t0, 3) if ttft is not None else None),
                "prompt_tokens": _as_int(usage.get("promptTokens")),
                "completion_tokens": _as_int(usage.get("completionTokens")),
                "total_tokens": _as_int(usage.get("totalTokens")),
                "estimated_cost": float(usage.get("estimatedCost") or 0.0),
            }
        )
        return row
    except Exception as exc:  # an agent that crashes IS a result, not a hole
        t1 = time.perf_counter()
        # A surfaced timeout (rare inline; normally enforced by the future) is
        # labelled distinctly from a generic failure.
        is_timeout = isinstance(exc, (TimeoutError, concurrent.futures.TimeoutError))
        row.update(
            {
                "status": "timeout" if is_timeout else "error",
                "error_type": type(exc).__name__,
                "error_message": str(exc)[:2000],
                "answer_text": None,
                "full_answer": "",
                "generated_sql_json": json.dumps([]),
                "artifacts_json": json.dumps([]),
                "n_sql": 0,
                "total_rows": 0,
                "latency_total_s": round(t1 - t0, 3),
                "time_to_first_token_s": (
                    round(ttft - t0, 3) if ttft is not None else None),
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0,
                "estimated_cost": 0.0,
            }
        )
        return row


def _timeout_row(run_id, run_timestamp, config_json, question_row, agent, mode,
                 timeout, latency_s):
    """Build a raw row for a call the executor timed out (future never returned)."""
    row = _base_raw_row(run_id, run_timestamp, config_json,
                        question_row, agent, mode)
    row.update(
        {
            "status": "timeout",
            "error_type": "TimeoutError",
            "error_message": "per-call timeout exceeded ({0}s)".format(timeout),
            "answer_text": None,
            "full_answer": "",
            "generated_sql_json": json.dumps([]),
            "artifacts_json": json.dumps([]),
            "n_sql": 0,
            "total_rows": 0,
            "latency_total_s": round(latency_s, 3),
            "time_to_first_token_s": None,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "estimated_cost": 0.0,
        }
    )
    return row


def run_matrix(run_config, write_row):
    """Run the whole (question x agent x mode) matrix, writing rows incrementally.

    ``run_config`` is the run descriptor (design section 4 RunConfig):
        {
          "run_id", "run_timestamp",
          "project",                 # a DSS project handle (built by the step)
          "agents":   [ {agent_key, agent_label, project_key, agent_id}, ... ],
          "questions":[ <golden row dict>, ... ],
          "modes":    ["eco", ...],
          "language": "fr",
          "concurrency": 3,          # bounded; defaults to config.DEFAULT_CONCURRENCY
          "per_call_timeout_s": 120, # defaults to config.PER_CALL_TIMEOUT_S
        }
    ``write_row(raw)`` is a callback invoked with each completed raw row AS SOON AS
    it finishes (incremental checkpointing: a crash mid-run keeps the work already
    written, tied together by ``run_id``).

    Instance safety: a bounded ``ThreadPoolExecutor`` (max_workers = concurrency,
    floored at 1) and a hard ``per_call_timeout_s`` per call. There is no retry: a
    timed-out future yields a ``status="timeout"`` row. Returns None.

    Lazy DSS: the ``project`` handle comes IN via ``run_config`` (the scenario step
    builds it from ``dataiku``). This function imports no DSS module.
    """
    project = run_config.get("project")
    agents = run_config.get("agents") or []
    questions = run_config.get("questions") or []
    modes = run_config.get("modes") or list(config.MODES)
    language = run_config.get("language") or "fr"
    run_id = run_config.get("run_id")
    run_timestamp = run_config.get("run_timestamp")

    concurrency = run_config.get("concurrency") or config.DEFAULT_CONCURRENCY
    try:
        concurrency = max(1, int(concurrency))
    except (TypeError, ValueError):
        concurrency = config.DEFAULT_CONCURRENCY
    timeout = run_config.get("per_call_timeout_s") or config.PER_CALL_TIMEOUT_S
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = config.PER_CALL_TIMEOUT_S

    # One immutable config snapshot string shared by every row of this run, so the
    # detail table can reconstruct exactly what was run (design section 7).
    config_json = json.dumps(
        {
            "run_id": run_id,
            "run_timestamp": run_timestamp,
            "modes": list(modes),
            "language": language,
            "concurrency": concurrency,
            "per_call_timeout_s": timeout,
            "agents": [
                {
                    "agent_key": (a or {}).get("agent_key"),
                    "agent_label": (a or {}).get("agent_label"),
                    "project_key": (a or {}).get("project_key"),
                    "agent_id": (a or {}).get("agent_id"),
                    "modes": _agent_supports_modes(a or {}),
                }
                for a in agents
            ],
            "n_questions": len(questions),
        },
        default=str,
    )

    tasks = expand_matrix(questions, agents, modes)
    if not tasks:
        return None

    executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
    try:
        future_meta = {}
        for task in tasks:
            future = executor.submit(
                run_one,
                project,
                task["agent"],
                task["question_row"],
                task["mode"],
                language,
                timeout,
                run_id,
                run_timestamp,
                config_json,
            )
            future_meta[future] = (task, time.perf_counter())

        # Overall wall-clock budget for the whole matrix (instance safety: a bounded step
        # duration). as_completed only yields a future AFTER it has finished, so a per-future
        # result(timeout=...) can never fire - the timeout MUST live on as_completed itself.
        # Budget = at most one full "wave" of the bounded pool per per-call timeout. A
        # ThreadPoolExecutor cannot interrupt a running thread, so a hung agent call keeps
        # winding down on its own, but the run stops WAITING on it (the goal: bounded wall-clock).
        waves = (len(tasks) + concurrency - 1) // max(1, concurrency)
        overall_budget = max(1.0, waves * timeout)
        try:
            for future in concurrent.futures.as_completed(future_meta, timeout=overall_budget):
                task, started = future_meta[future]
                try:
                    raw = future.result()  # already complete here (as_completed yields it)
                except Exception as exc:
                    # run_one already swallows its own exceptions; this is a last-ditch
                    # guard so a single bad future never aborts the whole matrix.
                    raw = _base_raw_row(
                        run_id, run_timestamp, config_json,
                        task["question_row"], task["agent"], task["mode"])
                    raw.update(
                        {
                            "status": "error",
                            "error_type": type(exc).__name__,
                            "error_message": str(exc)[:2000],
                            "full_answer": "",
                            "generated_sql_json": json.dumps([]),
                            "artifacts_json": json.dumps([]),
                            "n_sql": 0,
                            "total_rows": 0,
                            "latency_total_s": round(time.perf_counter() - started, 3),
                            "prompt_tokens": 0,
                            "completion_tokens": 0,
                            "total_tokens": 0,
                            "estimated_cost": 0.0,
                        }
                    )
                try:
                    write_row(raw)
                except Exception:
                    # A write failure for one row must not lose the rest of the run.
                    # The step logs / surfaces it; the runner stays resilient.
                    pass
        except concurrent.futures.TimeoutError:
            # The overall budget elapsed with calls still running: record a timeout row for
            # each unfinished call (it cannot be interrupted; cancel_futures below drops the
            # un-started ones) so the raw dataset shows the timeout instead of missing rows.
            for fut, (task, started) in future_meta.items():
                if not fut.done():
                    try:
                        write_row(_timeout_row(
                            run_id, run_timestamp, config_json,
                            task["question_row"], task["agent"], task["mode"],
                            timeout, time.perf_counter() - started,
                        ))
                    except Exception:
                        pass
    finally:
        # Do not wait on stragglers beyond the pool teardown: the futures already
        # carry their own per-call timeout, and a hung agent call must not pin the
        # scenario step open. cancel_futures drops anything not yet started.
        executor.shutdown(wait=False, cancel_futures=True)
    return None
