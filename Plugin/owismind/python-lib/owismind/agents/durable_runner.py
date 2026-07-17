"""Durable workflow runner - the backend half of the v1.3 "Durable Step Shell".

The Flask backend OWNS every durable run: its plan, cursor, lease, retries,
deadlines and recovery live in PostgreSQL (storage.run_state); the orchestrator
Code Agent is the stateless BRAIN, invoked once per bounded command (plan /
execute / replan / review / synthesize) through the frozen machine-token
protocol (agents.context builders). One LLM Mesh call never executes a whole
run; a backend kill never loses completed steps.

Instance-safety invariants (audited):
  - ONE supervisor daemon thread, claiming at most ONE recoverable run per scan
    (amortised recovery, no restart storm);
  - a global Mesh semaphore (MAX_MESH_CALLS) so durable traffic can never exceed
    the pre-existing parallelism level of the legacy path;
  - hard caps on active workflows (global and per user) - excess stays queued;
  - retries ONLY on transient failures (backoff + jitter), NEVER on blocking
    quotas or validation errors; every failure path persists an honest partial.

ZERO langchain here (Python 3.9 backend); the LangGraph side lives in the
orchestrator Code Agent (env 3.11) and is already committed (T4).
"""
import json
import logging
import random
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone

from ..storage import artifacts as artifacts_storage
from ..storage import chat_v5, run_state, settings
from . import context, streaming

logger = logging.getLogger("owismind.durable_runner")

# --- Tunables (spec section 4; hub run_settings.json may LOWER caps later) ----------
LEASE_SECONDS = 45
HEARTBEAT_SECONDS = 10
RECOVERY_SCAN_SECONDS = 10
MAX_ACTIVE_WORKFLOWS = 8
MAX_ACTIVE_WORKFLOWS_PER_USER = 1
MAX_MESH_CALLS = 3
MAX_STEP_ATTEMPTS = 3
MAX_TOTAL_STEP_ATTEMPTS = 18
MAX_REPLANS = 2
STEP_RETRY_BACKOFF_S = (2.0, 8.0)      # attempt 1 -> 2s, attempt 2 -> 8s (+ jitter)
RETRY_JITTER_S = 0.5
EVENT_FLUSH_MAX = 20                   # buffered public events before a forced flush
COMMAND_ANSWER_MAX_CHARS = 100_000     # accumulated answer text bound per command

# Per-mode deadlines (seconds): run wall-clock, per-step budget, idle UI warning.
DURABLE_DEADLINES_BY_MODE = {
    "smart": {"run": 900, "step": 180, "idle": 60},
    "pro": {"run": 1200, "step": 300, "idle": 90},
    "claude": {"run": 1800, "step": 600, "idle": 180},
}
_DEFAULT_MODE = "smart"

# Friendly terminal error codes (mapped to i18n runError.* on the frontend).
CODE_DEADLINE = "deadline_reached"
CODE_QUOTA = "quota_blocked"
CODE_RATE = "rate_limited"
CODE_AGENT_DISABLED = "agent_disabled"
CODE_PARTIAL = "partial_result"
CODE_INTERNAL = "agent_unavailable"

# Public timeline event types persisted for the UI (frozen list, spec section 9).
EV_PLAN_READY = "PLAN_READY"
EV_STEP_STARTED = "STEP_STARTED"
EV_STEP_RETRYING = "STEP_RETRYING"
EV_STEP_COMPLETED = "STEP_COMPLETED"
EV_VERIFYING = "VERIFYING"
EV_REPLANNING = "REPLANNING"
EV_WAITING = "WAITING_UPSTREAM"
EV_PARTIAL = "PARTIAL_RESULT"
EV_DONE = "DONE"
EV_ERROR = "ERROR"

# --- Process-local registry (single-process DSS webapp backend; the SQL lease is ----
# --- the cross-process fence, this is the thread-level instance protection)      ----
_LOCK = threading.Lock()
_WORKERS = {}                 # run_id -> {"user_id": .., "thread": Thread}
_SUPERVISOR = {"thread": None, "stop": False}
_MESH_SLOTS = threading.BoundedSemaphore(MAX_MESH_CALLS)


class BusyError(Exception):
    """Raised by start_workflow when a capacity cap refuses a new durable run."""


# --- Failure classification ----------------------------------------------------------
_TRANSIENT_MARKERS = (
    "timeout", "timed out", "connection", "temporarily", "unavailable",
    "502", "503", "504", "500", "reset by peer", "rate limit", "ratelimit",
    "429", "throttl",
)
_QUOTA_MARKERS = ("quota", "budget exceeded", "cost limit", "blocking quota")


def classify_failure(err):
    """"transient" (retryable), "quota" (never retried) or "fatal" for anything else.

    Accepts an exception OR an error-code string coming back from the agent's
    control payload. ValueError/TypeError are bugs, never transient (spec 4.4)."""
    if isinstance(err, (ValueError, TypeError)):
        return "fatal"
    text = str(err or "").lower()
    for marker in _QUOTA_MARKERS:
        if marker in text:
            return "quota"
    for marker in _TRANSIENT_MARKERS:
        if marker in text:
            return "transient"
    return "fatal"


def resolve_durable_deadlines(mode):
    """The {run, step, idle} second budgets for a response mode (fallback smart)."""
    return DURABLE_DEADLINES_BY_MODE.get(mode) or DURABLE_DEADLINES_BY_MODE[_DEFAULT_MODE]


# --- Public entry points --------------------------------------------------------------
def start_workflow(exchange_id, session_id, user_id, agent_key, mode, question,
                   bootstrap=None):
    """Create (or idempotently recover) a durable run and spawn its worker.

    ``bootstrap`` optionally carries {"project_key", "agent_id"} resolved by the
    route (fresh-start fast path); recovery workers re-resolve from the whitelist.
    Raises BusyError when a capacity cap refuses the run (the route maps it to a
    friendly 503)."""
    # Reserve the slot UNDER the lock (no TOCTOU: concurrent /chat/start bursts
    # see the reservation immediately); the reservation is replaced by the real
    # worker entry on spawn, and dropped on any failure.
    reservation = "resv-" + str(exchange_id)
    with _LOCK:
        _reap_dead_workers_locked()
        if len(_WORKERS) >= MAX_ACTIVE_WORKFLOWS:
            raise BusyError("durable workflow capacity reached")
        actives_for_user = sum(
            1 for w in _WORKERS.values() if w.get("user_id") == user_id)
        if actives_for_user >= MAX_ACTIVE_WORKFLOWS_PER_USER:
            raise BusyError("one active analysis per user")
        _WORKERS[reservation] = {"user_id": user_id, "thread": None,
                                 "reservation": True}

    try:
        deadlines = resolve_durable_deadlines(mode)
        deadline_at = (datetime.now(timezone.utc)
                       + timedelta(seconds=deadlines["run"]))
        try:
            run_id = run_state.create_run(
                exchange_id, session_id, user_id, agent_key, mode,
                deadline_at.isoformat())
        except Exception:
            # UNIQUE(exchange_id) violation -> crashed-then-retried start: recover.
            existing = run_state.load_run_by_exchange(exchange_id, user_id)
            if existing is None:
                raise
            run_id = existing["run_id"]
            logger.info("start_workflow - recovered existing run %s for "
                        "exchange %s", run_id, exchange_id)

        lease_owner = uuid.uuid4().hex
        if run_state.claim_run(run_id, lease_owner, LEASE_SECONDS):
            _spawn_worker(run_id, lease_owner, user_id, question, bootstrap)
        # else: another worker already holds it (recovery race) - polling works.
        return {"run_id": run_id, "exchange_id": exchange_id}
    finally:
        with _LOCK:
            _WORKERS.pop(reservation, None)


def start_supervisor():
    """Start the ONE recovery supervisor thread (idempotent, daemon).

    Every RECOVERY_SCAN_SECONDS it claims AT MOST ONE recoverable run (queued or
    lease-expired) and spawns its worker - amortised recovery, never a storm."""
    with _LOCK:
        thread = _SUPERVISOR.get("thread")
        if thread is not None and thread.is_alive():
            return
        _SUPERVISOR["stop"] = False
        thread = threading.Thread(
            target=_supervisor_loop, name="owismind-wf-supervisor", daemon=True)
        _SUPERVISOR["thread"] = thread
    thread.start()


def poll_durable(run_id, user_id, cursor):
    """Poll adapter for durable runs: events from SQL + done/error, or None.

    None when the run does not exist (or is not owned): the route falls back to
    its legacy handling. Lease internals NEVER leave this projection."""
    feed = run_state.read_events(run_id, user_id, cursor)
    if feed is None:
        return None
    status = feed.get("status")
    terminal = status in ("completed", "partial", "failed", "stopped",
                          "deadline_reached", "quota_blocked")
    events = feed.get("events") or []
    # done ONLY once the feed is drained: a terminal run with a full page of
    # pending events keeps the client polling until it caught up (pagination).
    done = terminal and len(events) < 500
    error = None
    if status in ("failed", "deadline_reached", "quota_blocked"):
        run = run_state.load_run(run_id, user_id)
        error = (run or {}).get("error_code") or status
    return {"events": events, "cursor": feed.get("cursor"),
            "done": done, "error": error, "status": status}


def stop_durable(run_id, user_id):
    """Durable stop: persist stop_requested (cooperative, honest wording in UI)."""
    return run_state.request_stop(run_id, user_id)


def active_run_for_session(session_id, user_id):
    """The most recent still-active durable run of a session, projected for the UI.

    Powers GET /chat/active (reconnect after refresh). Never exposes lease fields."""
    if not session_id:
        return None
    run = run_state.find_active_run_for_session(session_id, user_id)
    if run is None:
        return None
    return project_run_public(run)


def project_run_public(run):
    """The ONLY run projection routes may return (lease internals stripped)."""
    if not isinstance(run, dict):
        return None
    return {
        "run_id": run.get("run_id"),
        "exchange_id": run.get("exchange_id"),
        "session_id": run.get("session_id"),
        "status": run.get("status"),
        "mode": run.get("mode"),
        "error_code": run.get("error_code"),
        "created_at": run.get("created_at"),
        "updated_at": run.get("updated_at"),
    }


# --- Internals ------------------------------------------------------------------------
def _reap_dead_workers_locked():
    dead = [rid for rid, w in _WORKERS.items()
            if not w.get("thread") or not w["thread"].is_alive()]
    for rid in dead:
        _WORKERS.pop(rid, None)


def _supervisor_loop():
    logger.info("workflow supervisor started")
    while not _SUPERVISOR.get("stop"):
        try:
            time.sleep(RECOVERY_SCAN_SECONDS)
            with _LOCK:
                _reap_dead_workers_locked()
                if len(_WORKERS) >= MAX_ACTIVE_WORKFLOWS:
                    continue
            candidates = run_state.find_recoverable_runs(limit=1)
            for run_id in candidates or []:
                with _LOCK:
                    if run_id in _WORKERS:
                        continue
                lease_owner = uuid.uuid4().hex
                if run_state.claim_run(run_id, lease_owner, LEASE_SECONDS):
                    run = run_state.load_run(run_id)
                    if run is not None:
                        logger.info("supervisor recovered run %s", run_id)
                        _spawn_worker(run_id, lease_owner,
                                      run.get("user_id"), None, None)
        except Exception:
            logger.exception("supervisor scan failed (continuing)")


def _spawn_worker(run_id, lease_owner, user_id, question, bootstrap):
    thread = threading.Thread(
        target=_worker_main, name="owismind-wf-" + run_id[:8], daemon=True,
        args=(run_id, lease_owner, question, bootstrap))
    with _LOCK:
        _WORKERS[run_id] = {"user_id": user_id, "thread": thread}
    thread.start()


def _worker_main(run_id, lease_owner, question, bootstrap):
    stop_beat = threading.Event()
    lost = threading.Event()

    def _heartbeat():
        while not stop_beat.wait(HEARTBEAT_SECONDS):
            try:
                if not run_state.renew_lease(run_id, lease_owner, LEASE_SECONDS):
                    lost.set()               # lease stolen after expiry: stand down
                    return
            except Exception:
                logger.exception("heartbeat failed for run %s", run_id)

    beat = threading.Thread(target=_heartbeat, daemon=True,
                            name="owismind-wf-beat-" + run_id[:8])
    beat.start()
    try:
        _run_workflow(run_id, lease_owner, question, bootstrap, lost)
    except Exception:
        logger.exception("workflow worker crashed for run %s", run_id)
        try:
            _finalize_failure(run_id, "failed", CODE_INTERNAL)
            _emit(run_id, [(EV_ERROR, {"code": CODE_INTERNAL})])
        except Exception:
            pass
    finally:
        stop_beat.set()
        with _LOCK:
            _WORKERS.pop(run_id, None)


class _EventBuffer(object):
    """Batching buffer over run_state.append_events (size + 1s time flush)."""

    def __init__(self, run_id):
        self.run_id = run_id
        self.pending = []
        self._last_flush = time.monotonic()

    def add(self, event_type, payload=None):
        self.pending.append({"event_type": event_type,
                             "payload": payload or {}})
        if (len(self.pending) >= EVENT_FLUSH_MAX
                or (time.monotonic() - self._last_flush) >= 1.0):
            self.flush()

    def flush(self):
        self._last_flush = time.monotonic()
        if not self.pending:
            return
        batch, self.pending = self.pending, []
        try:
            run_state.append_events(self.run_id, batch)
        except Exception:
            logger.exception("event flush failed for run %s", self.run_id)


def _emit(run_id, pairs):
    """One-shot event append (best-effort) for terminal notifications."""
    try:
        run_state.append_events(
            run_id, [{"event_type": t, "payload": p or {}} for t, p in pairs])
    except Exception:
        logger.exception("emit failed for run %s", run_id)


def _resolve_target(run, bootstrap):
    """(project_key, agent_id) from the bootstrap or the server-side whitelist."""
    if bootstrap and bootstrap.get("project_key") and bootstrap.get("agent_id"):
        return bootstrap["project_key"], bootstrap["agent_id"]
    entry = settings.resolve_enabled_agent(run.get("agent_key"))
    if not entry:
        return None, None
    return entry.get("project_key"), entry.get("agent_id")


def _recover_question(run, question):
    """The user question driving this run (bootstrap value or chat_v5 lookup)."""
    if question:
        return question
    row = chat_v5.read_exchange(run.get("user_id"), run.get("exchange_id"))
    return (row or {}).get("user_text") or ""


def _deadline_passed(run):
    raw = run.get("deadline_at")
    if not raw:
        return False
    try:
        value = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return False
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= value


def _next_pending_step(steps):
    """First actionable step by ordinal: pending, or failed WITH a scheduled retry.

    A failed step is retryable IFF ``next_retry_at`` is set (the scheduler only
    sets it for transient failures within budget); a failed step without it is
    TERMINAL and belongs to the replan-or-partial path."""
    now = datetime.now(timezone.utc)
    for step in steps:
        status = step.get("status")
        if status == "pending":
            return step, 0.0
        if status == "failed":
            raw = step.get("next_retry_at")
            if not raw or int(step.get("attempt_no") or 0) >= MAX_STEP_ATTEMPTS:
                continue
            try:
                at = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
                if at.tzinfo is None:
                    at = at.replace(tzinfo=timezone.utc)
                wait = max(0.0, (at - now).total_seconds())
            except ValueError:
                wait = 0.0
            return step, wait
    return None, 0.0


def _step_public(step):
    return {"id": step.get("step_id"), "title": step.get("title"),
            "status": step.get("status")}


def _plan_public(ledger):
    run = ledger.get("run") or {}
    return {"goal": run.get("final_intent") or "",
            "steps": [_step_public(s) for s in ledger.get("steps") or []]}


# --- Deterministic result checks (spec 5.3; agent-side checks are declarative) -------
def evaluate_checks(checks, payload):
    """The FAILED check name, or None when every declared check passes.

    Deterministic, zero-token gates over the step's machine payload
    (row_count / columns / summary). Unknown check names pass (the enum is
    closed agent-side; forward-compatible here) but are logged."""
    payload = payload if isinstance(payload, dict) else {}
    row_count = payload.get("row_count")
    columns = payload.get("columns") or []
    for name in checks or []:
        if name == "non_empty":
            if not isinstance(row_count, int) or row_count <= 0:
                return name
        elif name in ("metric_present", "final_metric_present"):
            if len(columns) < 2:
                return name
        elif name == "join_key_present":
            if not columns or not str(columns[0]).strip():
                return name
        elif name == "all_sources_used":
            if not payload.get("all_sources_used", True):
                return name
        else:
            logger.info("unknown plan check '%s' (passing)", name)
    return None


# --- The state machine ----------------------------------------------------------------
def _run_workflow(run_id, lease_owner, question, bootstrap, lost):
    run = run_state.load_run(run_id)
    if run is None:
        return
    if run.get("status") in ("completed", "partial", "failed", "stopped",
                             "deadline_reached", "quota_blocked"):
        return                                # terminal already (recovery race)

    project_key, agent_id = _resolve_target(run, bootstrap)
    if not agent_id:
        _finalize_failure(run_id, "failed", CODE_AGENT_DISABLED)
        _emit(run_id, [(EV_ERROR, {"code": CODE_AGENT_DISABLED})])
        return
    question = _recover_question(run, question)
    mode = run.get("mode") or _DEFAULT_MODE
    deadlines = resolve_durable_deadlines(mode)
    events = _EventBuffer(run_id)

    def _partial(status, code):
        events.flush()
        ledger = run_state.load_ledger(run_id) or {"run": run, "steps": []}
        answer = build_partial_answer(ledger.get("run") or run, ledger)
        _finalize(run_id, ledger, answer, status, code)

    # -- Recovery: re-arm steps left 'running' by a dead worker ----------------------
    # We hold the lease now, so the previous attempt is superseded: fail it with an
    # immediate retry so the loop re-executes it under a FRESH attempt_id (fencing
    # keeps any late zombie write from clobbering the new attempt).
    ledger = run_state.load_ledger(run_id)
    for stale in (ledger or {}).get("steps") or []:
        if stale.get("status") == "running" and stale.get("attempt_id"):
            run_state.fail_step(
                run_id, stale["step_id"], stale["attempt_id"], "worker_lost",
                retry_at=datetime.now(timezone.utc).isoformat())

    # -- PLAN phase (skipped on recovery when steps already exist) ------------------
    ledger = run_state.load_ledger(run_id)
    if not (ledger and ledger.get("steps")):
        run = run_state.load_run(run_id) or {}
        if run.get("stop_requested"):
            _partial("stopped", CODE_PARTIAL)
            return
        if _deadline_passed(run):
            _partial("deadline_reached", CODE_DEADLINE)
            return
        run_state.set_run_status(run_id, "planning")
        outcome = _execute_command(
            project_key, agent_id, run_id, "plan", question, mode, deadlines,
            ledger=ledger, events=events)
        if outcome["kind"] != "control":
            _fail_run(run_id, events, outcome)
            return
        plan = (outcome["payload"] or {}).get("plan")
        problem = _plan_problems(plan)
        if problem:
            events.add(EV_ERROR, {"code": CODE_INTERNAL, "detail": problem})
            events.flush()
            _finalize_failure(run_id, "failed", CODE_INTERNAL)
            return
        run_state.save_plan(run_id, plan, 1)
        ledger = run_state.load_ledger(run_id)
        events.add(EV_PLAN_READY, _plan_public(ledger))
        events.flush()
    run_state.set_run_status(run_id, "executing")

    # -- EXECUTE + REVIEW cycles (hard-bounded; a review-triggered replan loops ---------
    # -- back into the executor for the appended steps, never by recursion)     ---------
    reviewed_ok = False
    for _cycle in range(MAX_REPLANS + 2):
        # EXECUTE loop: drain every actionable step of the current plan revision.
        while True:
            if lost.is_set():
                return                        # lease stolen: the new owner drives
            run = run_state.load_run(run_id) or {}
            if run.get("stop_requested"):
                _partial("stopped", CODE_PARTIAL)
                return
            if _deadline_passed(run):
                _partial("deadline_reached", CODE_DEADLINE)
                return
            ledger = run_state.load_ledger(run_id)
            steps = (ledger or {}).get("steps") or []
            # Crash-proof budgets: BOTH counters derive from the persisted ledger
            # (a recovered worker inherits them; RAM-only counters would reset).
            total_attempts = sum(int(s.get("attempt_no") or 0) for s in steps)
            replans_used = max(int(run.get("plan_revision") or 1) - 1, 0)
            step, wait_s = _next_pending_step(steps)
            if step is None:
                exhausted = [s for s in steps if s.get("status") == "failed"]
                if exhausted:
                    if replans_used < MAX_REPLANS:
                        if not _replan(project_key, agent_id, run_id, question,
                                       mode, deadlines, ledger, exhausted[0],
                                       events):
                            _partial("partial", CODE_PARTIAL)
                            return
                        continue
                    _partial("partial", CODE_PARTIAL)
                    return
                break                         # every step completed
            if total_attempts >= MAX_TOTAL_STEP_ATTEMPTS:
                _partial("partial", CODE_PARTIAL)
                return
            if wait_s > 0:
                time.sleep(min(wait_s, 10.0))
                continue

            attempt_id = uuid.uuid4().hex
            if not run_state.start_step(run_id, step["step_id"], attempt_id):
                continue                      # raced/zombie: reload the ledger
            retrying = int(step.get("attempt_no") or 0) > 0
            events.add(EV_STEP_RETRYING if retrying else EV_STEP_STARTED,
                       _step_public(step))
            events.flush()

            outcome = _execute_command(
                project_key, agent_id, run_id, "execute", question, mode,
                deadlines, ledger=ledger, step=step, attempt_id=attempt_id,
                events=events)
            verdict = _handle_step_outcome(run_id, step, attempt_id, outcome,
                                           events)
            if verdict == "quota":
                _partial("quota_blocked", CODE_QUOTA)
                return

        # REVIEW (multi-source plans only, once per cycle).
        ledger = run_state.load_ledger(run_id)
        if reviewed_ok or not _needs_review(ledger):
            break
        events.add(EV_VERIFYING, {})
        events.flush()
        outcome = _execute_command(
            project_key, agent_id, run_id, "review", question, mode, deadlines,
            ledger=ledger, events=events)
        payload = outcome.get("payload") or {}
        # The agent wraps the verdict: {"status": "ok", "review": {...}}.
        review = payload.get("review") if isinstance(payload.get("review"),
                                                     dict) else payload
        run = run_state.load_run(run_id) or {}
        replans_used = max(int(run.get("plan_revision") or 1) - 1, 0)
        if (outcome["kind"] == "control" and review.get("sufficient") is False
                and replans_used < MAX_REPLANS):
            if _replan(project_key, agent_id, run_id, question, mode, deadlines,
                       ledger, None, events, reason=review.get("missing")):
                continue                      # execute the appended steps
        reviewed_ok = True
        break

    run_state.set_run_status(run_id, "synthesizing")
    outcome = _execute_command(
        project_key, agent_id, run_id, "synthesize", question, mode, deadlines,
        ledger=run_state.load_ledger(run_id), events=events)
    answer = ""
    if outcome["kind"] == "control":
        answer = (outcome["payload"] or {}).get("answer") or ""
    answer = answer or outcome.get("answer_text") or ""
    if not answer:
        _partial("partial", CODE_PARTIAL)
        return
    _finalize(run_id, run_state.load_ledger(run_id), answer, "completed", None)
    events.add(EV_DONE, {})
    events.flush()


def _fail_run(run_id, events, outcome):
    code = outcome.get("code") or CODE_INTERNAL
    status = "quota_blocked" if code == CODE_QUOTA else "failed"
    events.add(EV_ERROR, {"code": code})
    events.flush()
    _finalize_failure(run_id, status, code)   # honest phase-2 on EVERY failure


def _needs_review(ledger):
    """Review only multi-source plans: any correlate, or >= 2 specialist steps."""
    specialists = 0
    for step in (ledger or {}).get("steps") or []:
        if step.get("status") != "completed":
            continue
        kind = step.get("kind")
        if kind == "correlate":
            return True
        if kind == "specialist_query":
            specialists += 1
    return specialists >= 2


def _plan_problems(plan):
    """Protocol-level plan validation (the agent already validated content)."""
    if not isinstance(plan, dict):
        return "plan_not_dict"
    steps = plan.get("steps")
    if not isinstance(steps, list) or not steps:
        return "plan_empty"
    if len(steps) > 12:
        return "plan_too_long"
    for step in steps:
        if not isinstance(step, dict):
            return "step_not_dict"
        if not step.get("id") or not step.get("kind") or not step.get("title"):
            return "step_missing_fields"
    return None


def _replan(project_key, agent_id, run_id, question, mode, deadlines, ledger,
            failed_step, events, reason=None):
    """One replan command; True when a new plan revision was accepted and saved."""
    events.add(EV_REPLANNING, {"failed_step": (failed_step or {}).get("step_id"),
                               "reason": reason})
    events.flush()
    outcome = _execute_command(
        project_key, agent_id, run_id, "replan", question, mode, deadlines,
        ledger=ledger, failed_step=failed_step, events=events)
    if outcome["kind"] != "control":
        return False
    plan = (outcome["payload"] or {}).get("plan")
    if _plan_problems(plan):
        return False
    run = run_state.load_run(run_id) or {}
    revision = int(run.get("plan_revision") or 1) + 1
    run_state.save_plan(run_id, plan, revision)
    events.add(EV_PLAN_READY, _plan_public(run_state.load_ledger(run_id) or {}))
    events.flush()
    return True


def _handle_step_outcome(run_id, step, attempt_id, outcome, events):
    """Persist one step attempt's outcome; returns "ok", "retry" or "quota"."""
    step_id = step["step_id"]
    if outcome["kind"] == "control":
        payload = outcome.get("payload") or {}
        status = payload.get("status")
        if status in ("ok", "ready", "no_data", "clarify"):
            checks = _decode_checks(step)
            failed_check = None
            if status in ("ok", "ready"):
                failed_check = evaluate_checks(checks, payload)
            if failed_check:
                # A deterministic check failure is a VALIDATION error, never
                # transient: an identical retry cannot heal it - the replan
                # path (with the error in context) is the repair mechanism.
                _schedule_retry(run_id, step, attempt_id,
                                "check_failed:" + failed_check, events,
                                transient=False)
                return "retry"
            result = {
                "result_status": status,
                "summary": payload.get("summary"),
                "schema": payload.get("schema"),
                "model_view": payload.get("model_view"),
                "generated_sql": payload.get("generated_sql"),
                "artifacts": payload.get("artifacts"),
                "usage": payload.get("usage"),
                "output_ref": payload.get("output_ref"),
            }
            if run_state.complete_step(run_id, step_id, attempt_id, result):
                events.add(EV_STEP_COMPLETED, {"id": step_id,
                                               "summary": payload.get("summary")})
                events.flush()
            return "ok"
        # structured refusal from the agent (validation error, not transient)
        _schedule_retry(run_id, step, attempt_id,
                        str(payload.get("error") or "step_rejected"), events,
                        transient=False)
        return "retry"
    # transport-level failure; a blocking quota terminates the whole run
    if outcome.get("failure") == "quota":
        run_state.fail_step(run_id, step_id, attempt_id, CODE_QUOTA)
        return "quota"
    code = outcome.get("code") or CODE_INTERNAL
    _schedule_retry(run_id, step, attempt_id, code, events,
                    transient=(outcome.get("failure") == "transient"))
    return "retry"


def _decode_checks(step):
    raw = step.get("checks_json")
    if isinstance(raw, list):
        return raw
    try:
        value = json.loads(raw) if raw else []
        return value if isinstance(value, list) else []
    except (ValueError, TypeError):
        return []


def _schedule_retry(run_id, step, attempt_id, error_code, events, transient=True):
    """Fail the attempt; schedule a backoff retry only while budget remains."""
    attempt_no = int(step.get("attempt_no") or 0) + 1   # start_step incremented it
    retry_at = None
    if transient and attempt_no < MAX_STEP_ATTEMPTS:
        backoff = STEP_RETRY_BACKOFF_S[min(attempt_no - 1,
                                           len(STEP_RETRY_BACKOFF_S) - 1)]
        backoff += random.uniform(0, RETRY_JITTER_S)
        retry_at = (datetime.now(timezone.utc)
                    + timedelta(seconds=backoff)).isoformat()
    run_state.fail_step(run_id, step["step_id"], attempt_id,
                        str(error_code)[:64], retry_at=retry_at)
    events.add(EV_STEP_RETRYING if retry_at else EV_ERROR,
               {"id": step["step_id"], "code": str(error_code)[:64]})
    events.flush()


# --- One bounded agent command ---------------------------------------------------------
def _execute_command(project_key, agent_id, run_id, command, question, mode,
                     deadlines, ledger=None, step=None, attempt_id=None,
                     failed_step=None, events=None):
    """ONE run_agent_streamed call carrying one workflow command; bounded + fenced.

    Returns {"kind": "control", "payload": ..., "answer_text": ...} on a machine
    result, or {"kind": "error", "failure": transient|quota|fatal, "code": ...}.
    The message layout follows the FROZEN contract: prose first (question +
    [WORKFLOW PROGRESS] recitation), then every ⟦owi:*⟧ token grouped at the tail.
    """
    prose_parts = [question or ""]
    progress = context.build_progress_block(ledger, mode)
    if progress:
        prose_parts.append(progress)
    tokens = []
    if step is not None and step.get("kind") == "render":
        prior = _render_prior_block(ledger, step)
        if prior:
            prose_parts.append(prior)         # block prose + its own tail token
    step_id = (step or {}).get("step_id")
    tokens.append(context.build_workflow_token(
        command, run_id, step_id=step_id, attempt_id=attempt_id))
    if command == "execute" and step is not None:
        tokens.append(context.build_wfstep_token(_step_spec(step)))
    if command == "replan":
        done_ids = [s.get("step_id") for s in (ledger or {}).get("steps") or []
                    if s.get("status") == "completed"]
        tokens.append(context.build_wfdone_token(done_ids))
        if failed_step is not None:
            prose_parts.append(
                "[FAILED STEP] {0}: {1}".format(
                    failed_step.get("step_id"),
                    (failed_step.get("error_code") or "unknown")[:200]))
    message = context.build_workflow_message("\n\n".join(
        p for p in prose_parts if p), tokens)

    control = None
    answer_parts = []
    answer_len = 0
    collected_sql = []
    collected_artifacts = []
    collected_usage = None
    mode_token = "⟦owi:mode={0}⟧".format(mode) if mode in context.MODEL_MODES else ""
    if mode_token:
        message = message + mode_token        # mode rides the same tail block
    started = time.monotonic()
    step_budget = deadlines["step"]
    idle_budget = deadlines.get("idle") or 60
    # Bounded wait for a Mesh slot: a stuck upstream call must not queue new
    # commands forever behind it (its own thread cannot be killed - no Mesh
    # cancel - but fresh work fails fast as transient instead of piling up).
    if not _MESH_SLOTS.acquire(timeout=min(step_budget, 60)):
        return {"kind": "error", "failure": "transient", "code": CODE_RATE}
    try:
        last_chunk = time.monotonic()
        idle_warned = False
        for event in streaming.run_agent_streamed(
                project_key, agent_id,
                [{"role": "user", "content": message}]):
            now = time.monotonic()
            if (not idle_warned and events is not None
                    and (now - last_chunk) > idle_budget):
                # Best-effort (observed between chunks): the UI learns the
                # upstream stayed silent for a long stretch.
                events.add(EV_WAITING, {"seconds": int(now - last_chunk)})
                idle_warned = True
            last_chunk = now
            etype = event.get("type")
            kind_raw = str(event.get("eventKind") or "")
            if kind_raw == "OWI_WORKFLOW_CONTROL" and etype != "workflow_control":
                # Pre-T5 leak guard: the raw control chunk may still surface as a
                # generic agent_event; NEVER forward it to the public feed under
                # any (renamed) type - consume it as the machine result instead.
                payload = event.get("eventData") or event.get("payload") or {}
                if isinstance(payload, dict):
                    control = {"payload": payload.get("payload") or payload}
                continue
            if etype == "workflow_control":
                control = event
            elif etype == "answer_delta":
                text = event.get("text") or ""
                if answer_len < COMMAND_ANSWER_MAX_CHARS:
                    answer_parts.append(text)
                    answer_len += len(text)
            elif etype == "generated_sql":
                collected_sql.append({k: event.get(k) for k in
                                      ("sql", "success", "rowCount", "sqlId")
                                      if k in event})
                if events is not None:
                    events.add("AGENT_GENERATED_SQL",
                               _public_event_payload(event))
            elif etype == "usage_summary":
                collected_usage = event.get("usage") or event.get("payload")
            elif etype == "artifact":
                collected_artifacts.append(event.get("artifact")
                                           or event.get("payload") or {})
            elif etype == "agent_event" and events is not None:
                events.add("AGENT_" + kind_raw.upper()[:40] if kind_raw
                           else "AGENT_EVENT", _public_event_payload(event))
            if (time.monotonic() - started) > step_budget:
                # Cooperative per-command budget: stop consuming; the fenced
                # attempt_id makes any late server-side result harmless.
                logger.warning("command %s on run %s exceeded step budget",
                               command, run_id)
                return {"kind": "error", "failure": "transient",
                        "code": CODE_DEADLINE}
    except Exception as exc:                  # Mesh/network failure
        failure = classify_failure(exc)
        code = {"quota": CODE_QUOTA, "transient": CODE_RATE}.get(
            failure, CODE_INTERNAL)
        logger.warning("command %s failed on run %s: %s", command, run_id, exc)
        return {"kind": "error", "failure": failure, "code": code}
    finally:
        _MESH_SLOTS.release()

    if control is not None:
        payload = dict(control.get("payload") or {})
        # The agent's REAL side-channels (SQL spans, usage footer, artifacts)
        # arrive as stream events, not inside the control payload: attach them
        # so the step result and the finalisation never lose them.
        if collected_sql and not payload.get("generated_sql"):
            payload["generated_sql"] = collected_sql
        if collected_usage and not payload.get("usage"):
            payload["usage"] = collected_usage
        if collected_artifacts and not payload.get("artifacts"):
            payload["artifacts"] = collected_artifacts
        return {"kind": "control", "payload": payload,
                "answer_text": "".join(answer_parts)}
    if answer_parts:                          # prose-only reply (defensive)
        return {"kind": "control", "payload": {},
                "answer_text": "".join(answer_parts)}
    return {"kind": "error", "failure": "fatal", "code": CODE_INTERNAL}


def _public_event_payload(event):
    """Bounded projection of a normalised stream event for the durable feed."""
    out = {}
    for key in ("eventKind", "blockId", "toolName", "label", "sqlIndex",
                "success", "rowCount"):
        if key in event:
            out[key] = event[key]
    return out


def _step_spec(step):
    """The wfstep token body rebuilt from the persisted step row."""
    spec = {"id": step.get("step_id"), "kind": step.get("kind"),
            "title": step.get("title")}
    task = step.get("task_json")
    if isinstance(task, str):
        try:
            task = json.loads(task)
        except ValueError:
            task = {"task": task}
    if isinstance(task, dict):
        spec.update({k: v for k, v in task.items()
                     if k in ("task", "capability_keys", "args", "produces",
                              "checks", "depends_on")})
    return spec


def _render_prior_block(ledger, step):
    """[PRIOR DATA] block whose entry 0 is the render step's input dependency."""
    deps = []
    raw = step.get("depends_on_json")
    try:
        deps = json.loads(raw) if isinstance(raw, str) and raw else (raw or [])
    except ValueError:
        deps = []
    by_id = {s.get("step_id"): s for s in (ledger or {}).get("steps") or []}
    for dep_id in deps:
        dep = by_id.get(dep_id)
        if not dep or dep.get("status") != "completed":
            continue
        view = dep.get("model_view_json")
        try:
            view = json.loads(view) if isinstance(view, str) and view else view
        except ValueError:
            view = None
        if not isinstance(view, dict):
            continue
        entry = {"question": dep.get("title") or dep_id,
                 "columns": view.get("columns") or [],
                 "rows": view.get("rows") or [],
                 "row_count": view.get("row_count")}
        return context.build_prior_data_block([entry])
    return ""


# --- Finalisation ----------------------------------------------------------------------
def build_partial_answer(run, ledger):
    """Honest FR/EN-neutral partial: what was completed, referenced by step."""
    lines = []
    for step in (ledger or {}).get("steps") or []:
        if step.get("status") != "completed":
            continue
        summary = (step.get("result_summary") or "").strip()
        if summary:
            lines.append("- {0}: {1}".format(step.get("title") or
                                             step.get("step_id"), summary))
    if not lines:
        return ("L'analyse n'a pas pu aboutir. / The analysis could not be "
                "completed.")
    return ("Analyse incomplete - resultats des etapes terminees / Partial "
            "analysis - completed steps:\n" + "\n".join(lines))


def _merge_step_results(ledger):
    """(generated_sql list, artifacts list, usage dict) merged across steps."""
    sql_all, artifacts_all = [], []
    tokens_in = tokens_out = 0
    cost = 0.0
    for step in (ledger or {}).get("steps") or []:
        raw_sql = step.get("generated_sql_json")
        try:
            items = json.loads(raw_sql) if isinstance(raw_sql, str) and raw_sql \
                else (raw_sql or [])
        except ValueError:
            items = []
        if isinstance(items, list):
            sql_all.extend(items)
        raw_art = step.get("artifacts_json")
        try:
            arts = json.loads(raw_art) if isinstance(raw_art, str) and raw_art \
                else (raw_art or [])
        except ValueError:
            arts = []
        if isinstance(arts, list):
            artifacts_all.extend(arts)
        raw_usage = step.get("usage_json")
        try:
            u = json.loads(raw_usage) if isinstance(raw_usage, str) and raw_usage \
                else (raw_usage or {})
        except ValueError:
            u = {}
        if isinstance(u, dict):
            tokens_in += int(u.get("promptTokens") or 0)
            tokens_out += int(u.get("completionTokens") or 0)
            try:
                cost += float(u.get("estimatedCost") or 0.0)
            except (TypeError, ValueError):
                pass
    usage = None
    if tokens_in or tokens_out or cost:
        usage = {"promptTokens": tokens_in, "completionTokens": tokens_out,
                 "totalTokens": tokens_in + tokens_out, "estimatedCost": cost}
    return sql_all[:24], artifacts_all[:8], usage


def _finalize_failure(run_id, status, code):
    """Honest phase-2 for failure paths outside the normal flow (best-effort).

    EVERY failure path must leave the exchange with a truthful partial answer,
    not just a status flip (spec 4.4): planner failures, disabled agents,
    invalid plans and worker crashes all land here."""
    try:
        ledger = run_state.load_ledger(run_id)
    except Exception:
        ledger = None
    if ledger is None:
        run_state.set_run_status(run_id, status, error_code=code)
        return
    answer = build_partial_answer(ledger.get("run") or {}, ledger)
    _finalize(run_id, ledger, answer, status, code)


def _finalize(run_id, ledger, answer, status, error_code):
    """Idempotent exchange finalisation (crash-replayable, spec section 10).

    Order: artifacts UPSERT -> chat_v5 UPDATE -> usage CAS (finalize_exchange_guard
    flips usage_accounted and accounts in ONE transaction) -> terminal status."""
    run = (ledger or {}).get("run") or {}
    exchange_id = run.get("exchange_id")
    user_id = run.get("user_id")
    sql_all, artifacts_all, usage = _merge_step_results(ledger)
    try:
        if artifacts_all and exchange_id and user_id:
            artifacts_storage.save_artifacts(exchange_id, user_id, artifacts_all)
    except Exception:
        logger.exception("artifact save failed for run %s", run_id)
    try:
        if exchange_id:
            chat_v5.save_assistant_message(exchange_id, answer,
                                           generated_sql=sql_all, usage=usage)
    except Exception:
        logger.exception("assistant save failed for run %s", run_id)
    try:
        run_state.finalize_exchange_guard(run_id)
    except Exception:
        logger.exception("usage finalisation failed for run %s", run_id)
    # Surface the answer on the DURABLE FEED too (chunked under the payload cap):
    # a live viewer, or one reconnecting after refresh, sees the text without
    # waiting for a conversation reload - chat_v5 stays the persistent truth.
    if answer:
        chunks = [answer[i:i + 7000] for i in range(0, min(len(answer),
                                                           70000), 7000)]
        _emit(run_id, [("FINAL_ANSWER",
                        {"text": part, "part": i + 1, "parts": len(chunks)})
                       for i, part in enumerate(chunks)])
    run_state.set_run_status(run_id, status, error_code=error_code)
    if status != "completed":
        _emit(run_id, [(EV_PARTIAL, {"code": error_code or CODE_PARTIAL})])
