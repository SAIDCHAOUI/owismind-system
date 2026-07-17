"""Durable agent-run ledger: runs / steps / events (Durable Step Shell, spec 2026-07-17).

The truth of a DURABLE agent run lives in PostgreSQL, never only in RAM: a backend
kill/restart resumes the run from this ledger. Three mechanisms make that safe:

  - SQL LEASE CLAIMING: ``claim_run`` is an atomic compare-and-set (``UPDATE ...
    WHERE lease expired``), so at most one worker owns a run; ``renew_lease`` keeps
    the lease alive while the worker heartbeats, and only lease EXPIRY (process
    death) frees the run for recovery - upstream idleness never does.
  - ATTEMPT FENCING: every (re)start of a step stamps a fresh ``attempt_id``;
    ``complete_step``/``fail_step`` compare-and-set on it, so a zombie worker's late
    result matches zero rows and can never overwrite a newer attempt.
  - IDEMPOTENT FINALIZATION: ``finalize_exchange_guard`` flips ``usage_accounted``
    false->true in the SAME transaction as the users/usage_monthly increments -
    usage is accounted exactly once, however many times finalization is replayed.

Storage rules (backend non-negotiables): direct SQL only, every value escaped via
``sql_value``/``nullable_value`` (numeric knobs are server-coerced ints inlined as
bare literals), PROJECT_KEY-prefixed tables via ``full_table``, ``COMMIT`` after
every write, ``statement_timeout`` on every statement, owner scoping (``user_id``
in the WHERE) wherever a user identity is given. Events never carry raw data rows;
payloads are capped at 8000 chars with a truncation marker, and the internal
OWI_WORKFLOW_CONTROL channel is never persisted.

Compare-and-set writes need the AFFECTED-ROW count (the pre_queries idiom cannot
observe it), so they run as ONE statement: a data-modifying CTE plus a top-level
``SELECT count(*)`` - still a plain result-set query for SQLExecutor2, still
committed via post_queries.
"""

import json
import logging
import uuid
from datetime import datetime

from owismind.storage.migrations import (
    AGENT_RUN_EVENTS_V1_LOGICAL,
    AGENT_RUN_STEPS_V1_LOGICAL,
    AGENT_RUNS_V1_LOGICAL,
    USAGE_MONTHLY_V1_LOGICAL,
    USERS_V1_LOGICAL,
    ensure_agent_run_events_table,
    ensure_agent_run_steps_table,
    ensure_agent_runs_table,
    ensure_usage_monthly_table,
    ensure_users_table,
)
from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    readonly_pre_queries,
    sql_value,
)

logger = logging.getLogger(__name__)

# --- Run / step state vocabulary (single source of truth for T3/T5) -----------
STATUS_QUEUED = "queued"
RUN_ACTIVE_STATUSES = (
    "queued", "planning", "executing", "replanning", "synthesizing",
)
RUN_TERMINAL_STATUSES = (
    "completed", "stopped", "partial", "failed", "deadline_reached",
    "quota_blocked",
)
RUN_STATUSES = frozenset(RUN_ACTIVE_STATUSES + RUN_TERMINAL_STATUSES)

STEP_PENDING = "pending"
STEP_RUNNING = "running"
STEP_COMPLETED = "completed"
STEP_FAILED = "failed"

# --- Caps (instance safety; the spec's hard, tested load caps) -----------------
MAX_PLAN_STEPS = 12                   # spec security invariant: 12 steps per plan
MAX_STEP_ATTEMPTS = 3                 # per-step attempt ceiling (clamp on the plan)
MAX_EVENTS_PER_APPEND = 200           # one batched INSERT stays small
MAX_EVENT_PAYLOAD_CHARS = 8_000       # public event payload cap (truncation marker)
MAX_READ_EVENTS_LIMIT = 500           # poll page cap
MAX_ACTIVITY_EVENTS = 2_000           # full-activity replay cap (per exchange)
MAX_RECOVERY_LIMIT = 50               # supervisor claims few runs per scan
MAX_LEASE_SECONDS = 3_600
MAX_PURGE_RUNS = 1_000                # spec: <= 1000 runs purged per pass
MAX_TASK_JSON_CHARS = 8_000
MAX_RESULT_SUMMARY_CHARS = 2_000
MAX_SCHEMA_JSON_CHARS = 4_000
MAX_MODEL_VIEW_JSON_CHARS = 24_000
MAX_ARTIFACTS_PER_STEP = 8
MAX_ARTIFACTS_JSON_CHARS = 16_000     # parity with storage/artifacts.py
MAX_GENERATED_SQL_JSON_CHARS = 200_000  # parity with the existing capture caps
MAX_USAGE_JSON_CHARS = 2_000
MAX_DEPENDS_JSON_CHARS = 2_000
MAX_CHECKS_JSON_CHARS = 4_000
_KEY_MAX = 128                        # bound on every id-ish TEXT value
_ERROR_CODE_MAX = 64
_EVENT_TYPE_MAX = 64
_TITLE_MAX = 200

# Internal control channel: NEVER persisted to the public event feed.
_DENIED_EVENT_TYPES = frozenset({"OWI_WORKFLOW_CONTROL"})

# Same instance-safety guard as artifacts/events: the write cannot be read-only,
# but the statement_timeout bounds it so a slow write never pins a worker thread.
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"

_MODES = ("smart", "pro", "claude")


# --- Small pure helpers --------------------------------------------------------
def _req_id(value, field, cap=_KEY_MAX):
    """A required, bounded id string; raises ValueError when missing/not a string."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("Missing required {}".format(field))
    return value.strip()[:cap]


def _opt_str(value, cap):
    """A bounded, trimmed string for a nullable column, or None (empty -> None)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:cap]


def _int_arg(value, minimum, maximum, field):
    """A server-side integer knob, clamped to [minimum, maximum]; garbage raises.

    These values are inlined as BARE numeric literals, so they must be provably
    ints (bool is rejected: True would silently become 1).
    """
    if isinstance(value, bool):
        raise ValueError("Invalid integer for {}: {!r}".format(field, value))
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise ValueError("Invalid integer for {}: {!r}".format(field, value))
    return max(minimum, min(maximum, n))


def _ts_sql(value, field):
    """Escaped ISO-8601 timestamp literal, or NULL for None; garbage raises.

    Accepts a ``datetime`` or an ISO string (trailing Z normalised for Python
    3.9's ``fromisoformat``). Re-emitting ``isoformat()`` guarantees the inlined
    literal is castable - a bad literal would abort the whole transaction.
    """
    if value is None or value == "":
        return "NULL"
    if isinstance(value, datetime):
        return sql_value(value.isoformat())
    if isinstance(value, str):
        s = value.strip()
        if s and len(s) <= 40:
            if s[-1] in ("Z", "z"):
                s = s[:-1] + "+00:00"
            try:
                return sql_value(datetime.fromisoformat(s).isoformat())
            except ValueError:
                pass
    raise ValueError("Invalid timestamp for {}: {!r}".format(field, value))


def _json_capped(value, cap):
    """JSON payload under ``cap`` chars, or None, or the truncation sentinel.

    None / empty container -> None (store SQL NULL). A string is assumed already
    serialized. Over the cap or unserializable -> ``{"_truncated": true}`` so the
    row still records that a payload existed (truncating JSON text would corrupt it).
    """
    if value is None:
        return None
    if isinstance(value, str):
        payload = value
    else:
        if isinstance(value, (dict, list)) and not value:
            return None
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return json.dumps({"_truncated": True})
    if len(payload) > cap:
        return json.dumps({"_truncated": True})
    return payload


def _capped_event_payload(value):
    """Event payload capped at MAX_EVENT_PAYLOAD_CHARS, keeping a marked head.

    Unlike step columns, the event feed is a UX surface: on overflow we keep a
    bounded head of the serialized payload behind an explicit ``_truncated``
    marker (never a silent cut that would corrupt the JSON)."""
    if value is None:
        return None
    if isinstance(value, str):
        payload = value
    else:
        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except (TypeError, ValueError):
            return json.dumps({"_truncated": True})
    if len(payload) <= MAX_EVENT_PAYLOAD_CHARS:
        return payload
    head = payload[:MAX_EVENT_PAYLOAD_CHARS - 1000]
    capped = json.dumps({"_truncated": True, "head": head}, ensure_ascii=False)
    if len(capped) > MAX_EVENT_PAYLOAD_CHARS:  # pathological escaping blow-up
        capped = json.dumps({"_truncated": True})
    return capped


def _coerce_tokens(value):
    """Non-negative int from a usage field (missing/garbage/negative -> 0)."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _coerce_cost(value):
    """Non-negative float from a usage field (missing/garbage/negative -> 0.0)."""
    try:
        f = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return f if f > 0 else 0.0


def _parse_json_dict(raw):
    """Decode a JSON-encoded dict cell; NULL/garbage/non-dict -> {}."""
    if not raw or not isinstance(raw, str):
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def _first_value(df, column, default=None):
    """First-row value of ``column`` from an executor DataFrame, else default."""
    if df is None or len(df) == 0:
        return default
    try:
        return df.iloc[0][column]
    except (KeyError, IndexError, TypeError):
        return default


def _read(sql):
    """Run a read-only SELECT (transaction_read_only + statement_timeout)."""
    return new_executor().query_to_df(sql, pre_queries=readonly_pre_queries())


def _run_cas(statement):
    """Execute a compare-and-set statement and report whether a row was hit.

    ``statement`` is a data-modifying CTE topped by ``SELECT count(*) AS n``: the
    only way to observe the affected-row count through query_to_df. Committed."""
    df = new_executor().query_to_df(
        statement,
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY],
        post_queries=["COMMIT"],
    )
    try:
        return int(_first_value(df, "n", 0)) > 0
    except (TypeError, ValueError):
        return False


def _decode_event_rows(rows):
    """Decode each event row's JSON payload in place (bad JSON stays raw text)."""
    out = []
    for row in rows:
        item = dict(row)
        payload = item.get("payload")
        if isinstance(payload, str) and payload:
            try:
                item["payload"] = json.loads(payload)
            except (TypeError, ValueError):
                pass
        out.append(item)
    return out


# --- Run lifecycle --------------------------------------------------------------
def create_run(exchange_id, session_id, user_id, agent_key, mode, deadline_at):
    """INSERT a fresh durable run in status 'queued' and return its run_id (uuid4).

    ``exchange_id`` is UNIQUE (one durable run per chat exchange): a duplicate
    raises from the executor, which the caller treats as "run already exists".
    ``agent_key`` is the OPAQUE whitelist key (never an agent_id). ``deadline_at``
    is the server-computed hard deadline (datetime/ISO string, or None)."""
    exchange_id = _req_id(exchange_id, "exchange_id")
    user_id = _req_id(user_id, "user_id")
    agent_key = _req_id(agent_key, "agent_key")
    mode_value = mode if isinstance(mode, str) and mode in _MODES else None
    deadline_sql = _ts_sql(deadline_at, "deadline_at")
    run_id = str(uuid.uuid4())

    ensure_agent_runs_table()
    insert = (
        "INSERT INTO {table} (run_id, exchange_id, session_id, user_id, agent_key, "
        "mode, status, deadline_at, created_at, updated_at) "
        "VALUES ({run_id}, {exchange_id}, {session_id}, {user_id}, {agent_key}, "
        "{mode}, {status}, {deadline}, now(), now())"
    ).format(
        table=full_table(AGENT_RUNS_V1_LOGICAL),
        run_id=sql_value(run_id),
        exchange_id=sql_value(exchange_id),
        session_id=nullable_value(_opt_str(session_id, _KEY_MAX)),
        user_id=sql_value(user_id),
        agent_key=sql_value(agent_key),
        mode=nullable_value(mode_value),
        status=sql_value(STATUS_QUEUED),
        deadline=deadline_sql,
    )
    new_executor().query_to_df(
        "SELECT 1 AS run_created",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, insert],
        post_queries=["COMMIT"],
    )
    logger.info("create_run - run_id=%s exchange_id=%s user_id=%s", run_id,
                exchange_id, user_id)
    return run_id


def claim_run(run_id, lease_owner, lease_seconds):
    """Atomically claim (or re-claim) a run's lease; True when this owner holds it.

    The compare-and-set only matches when the run is still ACTIVE and its lease is
    free, expired, or already ours - a valid lease held by ANOTHER worker is never
    stolen. This is the sole entry point for both first claim and recovery."""
    run_id = _req_id(run_id, "run_id")
    lease_owner = _req_id(lease_owner, "lease_owner")
    seconds = _int_arg(lease_seconds, 1, MAX_LEASE_SECONDS, "lease_seconds")
    ensure_agent_runs_table()
    statement = (
        "WITH w AS ("
        " UPDATE {table} SET"
        " lease_owner = {owner},"
        " lease_until = now() + ({seconds} * interval '1 second'),"
        " worker_heartbeat_at = now(),"
        " updated_at = now()"
        " WHERE run_id = {run_id}"
        " AND status IN ({active})"
        " AND (lease_owner IS NULL OR lease_owner = {owner}"
        " OR lease_until IS NULL OR lease_until < now())"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        table=full_table(AGENT_RUNS_V1_LOGICAL),
        owner=sql_value(lease_owner),
        seconds=seconds,
        run_id=sql_value(run_id),
        active=", ".join(sql_value(s) for s in RUN_ACTIVE_STATUSES),
    )
    return _run_cas(statement)


def renew_lease(run_id, lease_owner, lease_seconds):
    """Extend OUR lease + heartbeat; False when the lease changed hands.

    Scoped on ``lease_owner``: after a recovery claim by another worker, the old
    owner's renewal matches zero rows - its next heartbeat learns it lost the run."""
    run_id = _req_id(run_id, "run_id")
    lease_owner = _req_id(lease_owner, "lease_owner")
    seconds = _int_arg(lease_seconds, 1, MAX_LEASE_SECONDS, "lease_seconds")
    ensure_agent_runs_table()
    statement = (
        "WITH w AS ("
        " UPDATE {table} SET"
        " lease_until = now() + ({seconds} * interval '1 second'),"
        " worker_heartbeat_at = now(),"
        " updated_at = now()"
        " WHERE run_id = {run_id} AND lease_owner = {owner}"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        table=full_table(AGENT_RUNS_V1_LOGICAL),
        seconds=seconds,
        run_id=sql_value(run_id),
        owner=sql_value(lease_owner),
    )
    return _run_cas(statement)


def load_run(run_id, user_id=None):
    """The run row as a dict, or None (unknown run, or not owned when user_id given).

    Owner-scoped whenever a user identity is supplied: a non-owner gets the same
    None as a missing run (logical 404, no existence oracle)."""
    if not run_id or not isinstance(run_id, str):
        return None
    ensure_agent_runs_table()
    where = "run_id = {0}".format(sql_value(run_id.strip()[:_KEY_MAX]))
    if user_id is not None:
        where += " AND user_id = {0}".format(sql_value(str(user_id)[:_KEY_MAX]))
    sql = "SELECT * FROM {table} WHERE {where}".format(
        table=full_table(AGENT_RUNS_V1_LOGICAL), where=where
    )
    rows = rows_to_json_safe(_read(sql))
    return rows[0] if rows else None


def load_ledger(run_id):
    """The full working memory of a run: {"run": dict, "steps": [by ordinal]}.

    None when the run does not exist. Backend-internal (no owner scope): the
    worker/supervisor reads it to resume at the first unfinished step."""
    run = load_run(run_id)
    if run is None:
        return None
    ensure_agent_run_steps_table()
    sql = (
        "SELECT * FROM {table} WHERE run_id = {run_id} "
        "ORDER BY ordinal ASC LIMIT {cap}"
    ).format(
        table=full_table(AGENT_RUN_STEPS_V1_LOGICAL),
        run_id=sql_value(run["run_id"]),
        cap=MAX_PLAN_STEPS * (MAX_STEP_ATTEMPTS + 1) * 4,  # generous, still bounded
    )
    steps = rows_to_json_safe(_read(sql))
    return {"run": run, "steps": steps}


# --- Plan persistence -------------------------------------------------------------
def save_plan(run_id, plan_dict, plan_revision):
    """Replace the run's NON-completed steps with the new plan, in ONE transaction.

    Completed steps are never deleted nor re-inserted (``ON CONFLICT DO NOTHING``
    keeps them intact when a replan reuses their step_id), so recovery never
    replays finished work. The plan is capped at MAX_PLAN_STEPS; every *_json
    payload is capped with a truncation sentinel. Also stamps the run's
    ``plan_revision`` and progress timestamps."""
    run_id = _req_id(run_id, "run_id")
    revision = _int_arg(plan_revision, 0, 1_000_000, "plan_revision")
    ensure_agent_runs_table()
    ensure_agent_run_steps_table()

    rows = []
    seen = set()
    for raw in ((plan_dict or {}).get("steps") or [])[:MAX_PLAN_STEPS * 4]:
        if len(rows) >= MAX_PLAN_STEPS:
            break
        if not isinstance(raw, dict):
            continue
        step_id = raw.get("step_id") or raw.get("id")
        if not isinstance(step_id, str) or not step_id.strip():
            continue
        step_id = step_id.strip()[:_KEY_MAX]
        if step_id in seen:
            continue
        seen.add(step_id)
        max_attempts = 3
        if raw.get("max_attempts") is not None:
            try:
                max_attempts = _int_arg(
                    raw.get("max_attempts"), 1, MAX_STEP_ATTEMPTS, "max_attempts"
                )
            except ValueError:
                max_attempts = 3
        rows.append(
            "({run_id}, {step_id}, {ordinal}, {revision}, {kind}, {title}, "
            "{task}, {depends}, {checks}, {output_ref}, {max_attempts}, {status})".format(
                run_id=sql_value(run_id),
                step_id=sql_value(step_id),
                ordinal=len(rows),
                revision=revision,
                kind=nullable_value(_opt_str(raw.get("kind"), 32)),
                title=nullable_value(_opt_str(raw.get("title"), _TITLE_MAX)),
                task=nullable_value(_json_capped(raw.get("task"), MAX_TASK_JSON_CHARS)),
                depends=nullable_value(
                    _json_capped(raw.get("depends_on"), MAX_DEPENDS_JSON_CHARS)
                ),
                checks=nullable_value(
                    _json_capped(raw.get("checks"), MAX_CHECKS_JSON_CHARS)
                ),
                output_ref=nullable_value(_opt_str(raw.get("output_ref"), _TITLE_MAX)),
                max_attempts=max_attempts,
                status=sql_value(STEP_PENDING),
            )
        )

    steps_table = full_table(AGENT_RUN_STEPS_V1_LOGICAL)
    run_value = sql_value(run_id)
    delete = (
        "DELETE FROM {table} WHERE run_id = {run_id} AND status <> {completed}"
    ).format(table=steps_table, run_id=run_value, completed=sql_value(STEP_COMPLETED))
    update_run = (
        "UPDATE {table} SET plan_revision = {revision}, last_progress_at = now(), "
        "updated_at = now() WHERE run_id = {run_id}"
    ).format(
        table=full_table(AGENT_RUNS_V1_LOGICAL), revision=revision, run_id=run_value
    )
    pre = [_WRITE_TIMEOUT_PRE_QUERY, delete]
    if rows:
        pre.append(
            "INSERT INTO {table} (run_id, step_id, ordinal, plan_revision, kind, "
            "title, task_json, depends_on_json, checks_json, output_ref, "
            "max_attempts, status) VALUES {rows} "
            "ON CONFLICT (run_id, step_id) DO NOTHING".format(
                table=steps_table, rows=", ".join(rows)
            )
        )
    pre.append(update_run)
    new_executor().query_to_df(
        "SELECT 1 AS plan_saved", pre_queries=pre, post_queries=["COMMIT"]
    )
    logger.info("save_plan - run_id=%s revision=%d steps=%d", run_id, revision,
                len(rows))


# --- Step transitions (attempt-fenced) ---------------------------------------------
def start_step(run_id, step_id, attempt_id):
    """CAS pending/failed -> running, stamping a FRESH attempt_id. True on success.

    The new ``attempt_id`` becomes the fencing token every later completion or
    failure must present. Also advances the run's ``step_cursor`` and progress
    stamps in the same transaction."""
    run_id = _req_id(run_id, "run_id")
    step_id = _req_id(step_id, "step_id")
    attempt_id = _req_id(attempt_id, "attempt_id")
    ensure_agent_runs_table()
    ensure_agent_run_steps_table()
    statement = (
        "WITH w AS ("
        " UPDATE {steps} SET"
        " status = {running},"
        " attempt_id = {attempt},"
        " attempt_no = attempt_no + 1,"
        " started_at = COALESCE(started_at, now()),"
        " next_retry_at = NULL,"
        " error_code = NULL,"
        " updated_at = now()"
        " WHERE run_id = {run_id} AND step_id = {step_id}"
        " AND status IN ({pending}, {failed})"
        " RETURNING ordinal"
        "), r AS ("
        " UPDATE {runs} AS ru SET"
        " step_cursor = w.ordinal, last_progress_at = now(), updated_at = now()"
        " FROM w WHERE ru.run_id = {run_id}"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        steps=full_table(AGENT_RUN_STEPS_V1_LOGICAL),
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        running=sql_value(STEP_RUNNING),
        attempt=sql_value(attempt_id),
        run_id=sql_value(run_id),
        step_id=sql_value(step_id),
        pending=sql_value(STEP_PENDING),
        failed=sql_value(STEP_FAILED),
    )
    return _run_cas(statement)


def complete_step(run_id, step_id, attempt_id, result):
    """FENCED completion: only the step's CURRENT attempt may complete it.

    ``WHERE attempt_id = {ours}`` is the fence - a superseded (zombie) attempt
    matches zero rows and gets False, so a late result never overwrites a newer
    attempt. Re-completing the same attempt is idempotent (True). ``result`` is a
    dict of bounded fields; every payload is capped, NEVER raw data rows."""
    run_id = _req_id(run_id, "run_id")
    step_id = _req_id(step_id, "step_id")
    attempt_id = _req_id(attempt_id, "attempt_id")
    result = result if isinstance(result, dict) else {}
    ensure_agent_runs_table()
    ensure_agent_run_steps_table()

    artifacts = result.get("artifacts")
    if isinstance(artifacts, list):
        artifacts = artifacts[:MAX_ARTIFACTS_PER_STEP]
    sets = [
        "status = {0}".format(sql_value(STEP_COMPLETED)),
        "result_status = {0}".format(
            nullable_value(_opt_str(result.get("result_status"), 32))
        ),
        "result_summary = {0}".format(
            nullable_value(_opt_str(result.get("summary"), MAX_RESULT_SUMMARY_CHARS))
        ),
        "result_schema_json = {0}".format(
            nullable_value(_json_capped(result.get("schema"), MAX_SCHEMA_JSON_CHARS))
        ),
        "model_view_json = {0}".format(
            nullable_value(
                _json_capped(result.get("model_view"), MAX_MODEL_VIEW_JSON_CHARS)
            )
        ),
        "generated_sql_json = {0}".format(
            nullable_value(
                _json_capped(
                    result.get("generated_sql"), MAX_GENERATED_SQL_JSON_CHARS
                )
            )
        ),
        "artifacts_json = {0}".format(
            nullable_value(_json_capped(artifacts, MAX_ARTIFACTS_JSON_CHARS))
        ),
        "usage_json = {0}".format(
            nullable_value(_json_capped(result.get("usage"), MAX_USAGE_JSON_CHARS))
        ),
        "error_code = NULL",
        "next_retry_at = NULL",
        "finished_at = COALESCE(finished_at, now())",
        "updated_at = now()",
    ]
    output_ref = _opt_str(result.get("output_ref"), _TITLE_MAX)
    if output_ref is not None:  # keep the planned ref when the result has none
        sets.insert(1, "output_ref = {0}".format(sql_value(output_ref)))

    statement = (
        "WITH w AS ("
        " UPDATE {steps} SET {sets}"
        " WHERE run_id = {run_id} AND step_id = {step_id}"
        " AND attempt_id = {attempt}"
        " AND status IN ({running}, {completed})"
        " RETURNING 1"
        "), r AS ("
        " UPDATE {runs} AS ru SET last_progress_at = now(), updated_at = now()"
        " FROM w WHERE ru.run_id = {run_id}"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        steps=full_table(AGENT_RUN_STEPS_V1_LOGICAL),
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        sets=", ".join(sets),
        run_id=sql_value(run_id),
        step_id=sql_value(step_id),
        attempt=sql_value(attempt_id),
        running=sql_value(STEP_RUNNING),
        completed=sql_value(STEP_COMPLETED),
    )
    return _run_cas(statement)


def fail_step(run_id, step_id, attempt_id, error_code, retry_at=None):
    """FENCED failure: mark the CURRENT attempt failed, optionally scheduling a retry.

    Same attempt_id compare-and-set as ``complete_step`` (a stale attempt gets
    False). ``retry_at`` (datetime/ISO, or None) fills ``next_retry_at`` for the
    step-level backoff; None means no retry is scheduled."""
    run_id = _req_id(run_id, "run_id")
    step_id = _req_id(step_id, "step_id")
    attempt_id = _req_id(attempt_id, "attempt_id")
    ensure_agent_run_steps_table()
    statement = (
        "WITH w AS ("
        " UPDATE {steps} SET"
        " status = {failed},"
        " error_code = {error_code},"
        " next_retry_at = {retry_at},"
        " updated_at = now()"
        " WHERE run_id = {run_id} AND step_id = {step_id}"
        " AND attempt_id = {attempt}"
        " AND status IN ({running}, {failed})"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        steps=full_table(AGENT_RUN_STEPS_V1_LOGICAL),
        failed=sql_value(STEP_FAILED),
        error_code=nullable_value(_opt_str(error_code, _ERROR_CODE_MAX)),
        retry_at=_ts_sql(retry_at, "retry_at"),
        run_id=sql_value(run_id),
        step_id=sql_value(step_id),
        attempt=sql_value(attempt_id),
        running=sql_value(STEP_RUNNING),
    )
    return _run_cas(statement)


# --- Event feed ---------------------------------------------------------------------
def append_events(run_id, events):
    """Append a BATCH of public events; returns the run's new next_event_seq.

    ONE committed transaction: the run's ``next_event_seq`` is bumped by the batch
    size (the row lock serialises concurrent appenders), then a single multi-row
    INSERT (the events.py batch pattern) writes seq = base + offset - the feed is
    strictly monotonic per run. Payloads are capped at 8000 chars with a
    truncation marker; OWI_WORKFLOW_CONTROL (internal control channel) and raw
    data rows never land here. None when nothing storable (or unknown run)."""
    run_id = _req_id(run_id, "run_id")
    cleaned = []
    for event in (events or [])[:MAX_EVENTS_PER_APPEND]:
        if not isinstance(event, dict):
            continue
        event_type = event.get("event_type") or event.get("type")
        if not isinstance(event_type, str) or not event_type.strip():
            continue
        event_type = event_type.strip()[:_EVENT_TYPE_MAX]
        if event_type in _DENIED_EVENT_TYPES:
            continue
        cleaned.append((
            event_type,
            _opt_str(event.get("attempt_id"), _KEY_MAX),
            _capped_event_payload(event.get("payload")),
        ))
    if not cleaned:
        return None

    ensure_agent_runs_table()
    ensure_agent_run_events_table()
    runs_table = full_table(AGENT_RUNS_V1_LOGICAL)
    run_value = sql_value(run_id)
    count = len(cleaned)
    bump = (
        "UPDATE {runs} SET next_event_seq = next_event_seq + {count}, "
        "updated_at = now() WHERE run_id = {run_id}"
    ).format(runs=runs_table, count=count, run_id=run_value)
    values = ", ".join(
        "({offset}, {attempt}, {event_type}, {payload})".format(
            offset=offset,
            attempt=nullable_value(attempt),
            event_type=sql_value(event_type),
            payload=nullable_value(payload),
        )
        for offset, (event_type, attempt, payload) in enumerate(cleaned)
    )
    insert = (
        "INSERT INTO {events} (run_id, seq, attempt_id, event_type, payload, "
        "created_at) "
        "SELECT {run_id}, r.next_event_seq - {count} + v.off, v.attempt_id, "
        "v.event_type, v.payload, now() "
        "FROM {runs} r, (VALUES {values}) AS v(off, attempt_id, event_type, payload) "
        "WHERE r.run_id = {run_id}"
    ).format(
        events=full_table(AGENT_RUN_EVENTS_V1_LOGICAL),
        run_id=run_value,
        count=count,
        runs=runs_table,
        values=values,
    )
    df = new_executor().query_to_df(
        "SELECT next_event_seq AS n FROM {runs} WHERE run_id = {run_id}".format(
            runs=runs_table, run_id=run_value
        ),
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, bump, insert],
        post_queries=["COMMIT"],
    )
    next_seq = _first_value(df, "n")
    if next_seq is None:
        return None  # unknown run: the bump matched nothing
    return int(next_seq)


def read_events(run_id, user_id, cursor, limit=500):
    """Owner-scoped poll of the event feed from ``cursor`` (a seq), page-capped.

    A missing run OR a non-owner both yield the same logical 404 shape (no
    existence oracle). ``done`` is True only once the run is TERMINAL and the
    cursor caught up with ``next_event_seq``; ``error`` surfaces the run's
    error_code (or 'not_found'). Payloads come back JSON-decoded."""
    try:
        cursor = max(0, int(cursor or 0))
    except (TypeError, ValueError):
        cursor = 0
    limit = _int_arg(limit or MAX_READ_EVENTS_LIMIT, 1, MAX_READ_EVENTS_LIMIT,
                     "limit")
    run = load_run(run_id, user_id=user_id)
    if run is None:
        return {"events": [], "cursor": cursor, "done": True,
                "error": "not_found", "status": None}
    ensure_agent_run_events_table()
    sql = (
        "SELECT seq, attempt_id, event_type, payload, created_at FROM {events} "
        "WHERE run_id = {run_id} AND seq >= {cursor} "
        "ORDER BY seq ASC LIMIT {limit}"
    ).format(
        events=full_table(AGENT_RUN_EVENTS_V1_LOGICAL),
        run_id=sql_value(run["run_id"]),
        cursor=cursor,
        limit=limit,
    )
    events = _decode_event_rows(rows_to_json_safe(_read(sql)))
    next_cursor = (int(events[-1]["seq"]) + 1) if events else cursor
    try:
        total = int(run.get("next_event_seq") or 0)
    except (TypeError, ValueError):
        total = 0
    done = run.get("status") in RUN_TERMINAL_STATUSES and next_cursor >= total
    return {
        "events": events,
        "cursor": next_cursor,
        "done": done,
        "error": run.get("error_code"),
        "status": run.get("status"),
    }


def read_activity(exchange_id, user_id):
    """The full (bounded) event feed of an exchange's run, OWNER-scoped via JOIN.

    Powers the 'what happened while I was away' replay: events join their run on
    exchange_id, and the run's user_id must match the caller. Empty when the
    exchange is unknown, not owned, or has no durable run."""
    if not exchange_id or not user_id:
        return []
    ensure_agent_runs_table()
    ensure_agent_run_events_table()
    sql = (
        "SELECT e.seq, e.attempt_id, e.event_type, e.payload, e.created_at "
        "FROM {events} e JOIN {runs} r ON r.run_id = e.run_id "
        "WHERE r.exchange_id = {exchange_id} AND r.user_id = {user_id} "
        "ORDER BY e.seq ASC LIMIT {cap}"
    ).format(
        events=full_table(AGENT_RUN_EVENTS_V1_LOGICAL),
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        exchange_id=sql_value(str(exchange_id)[:_KEY_MAX]),
        user_id=sql_value(str(user_id)[:_KEY_MAX]),
        cap=MAX_ACTIVITY_EVENTS,
    )
    return _decode_event_rows(rows_to_json_safe(_read(sql)))


# --- Stop / recovery / status ----------------------------------------------------
def request_stop(run_id, user_id):
    """Durably flag the run for cooperative stop; OWNER-scoped, idempotent.

    True whenever the caller owns the run (repeat clicks stay True); False for an
    unknown run or a non-owner. The worker honours the flag at its next checkpoint
    (no Mesh-call cancellation exists by design)."""
    run_id = _req_id(run_id, "run_id")
    user_id = _req_id(user_id, "user_id")
    ensure_agent_runs_table()
    statement = (
        "WITH w AS ("
        " UPDATE {runs} SET stop_requested = true, updated_at = now()"
        " WHERE run_id = {run_id} AND user_id = {user_id}"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM w"
    ).format(
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        run_id=sql_value(run_id),
        user_id=sql_value(user_id),
    )
    return _run_cas(statement)


def find_recoverable_runs(limit=1):
    """run_ids of ACTIVE runs whose lease is free or expired, oldest-touched first.

    The supervisor's scan: default limit 1 = at most ONE run recovered per pass
    (amortised recovery, no thundering herd). Read-only - the actual takeover is
    ``claim_run`` (atomic), so two scanners can never both win a run."""
    limit = _int_arg(limit, 1, MAX_RECOVERY_LIMIT, "limit")
    ensure_agent_runs_table()
    sql = (
        "SELECT run_id FROM {runs} "
        "WHERE status IN ({active}) "
        "AND (lease_until IS NULL OR lease_until < now()) "
        "ORDER BY updated_at ASC LIMIT {limit}"
    ).format(
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        active=", ".join(sql_value(s) for s in RUN_ACTIVE_STATUSES),
        limit=limit,
    )
    rows = rows_to_json_safe(_read(sql))
    return [row["run_id"] for row in rows if row.get("run_id")]


def set_run_status(run_id, status, error_code=None):
    """Move the run to ``status`` (validated against the closed vocabulary).

    A terminal status stamps ``finished_at`` once (COALESCE keeps the first).
    ``error_code`` is only written when provided, so a later transition never
    blanks an earlier diagnostic. Unknown statuses raise (programming error)."""
    run_id = _req_id(run_id, "run_id")
    if status not in RUN_STATUSES:
        raise ValueError("Unknown run status: {!r}".format(status))
    ensure_agent_runs_table()
    sets = ["status = {0}".format(sql_value(status)), "updated_at = now()"]
    if error_code is not None:
        sets.append("error_code = {0}".format(
            sql_value(str(error_code)[:_ERROR_CODE_MAX])
        ))
    if status in RUN_TERMINAL_STATUSES:
        sets.append("finished_at = COALESCE(finished_at, now())")
    update = "UPDATE {runs} SET {sets} WHERE run_id = {run_id}".format(
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        sets=", ".join(sets),
        run_id=sql_value(run_id),
    )
    new_executor().query_to_df(
        "SELECT 1 AS status_set",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, update],
        post_queries=["COMMIT"],
    )
    logger.info("set_run_status - run_id=%s status=%s error_code=%s", run_id,
                status, error_code)


# --- Idempotent finalization guard --------------------------------------------------
def finalize_exchange_guard(run_id):
    """CAS ``usage_accounted`` false->true AND account usage, in ONE transaction.

    True exactly ONCE per run: the flip and the users/usage_monthly increments are
    a single statement (data-modifying CTEs), so a crash-replayed finalization can
    never double-count (spec section 10). Usage totals are summed from the steps'
    ``usage_json`` (the run's own ``usage_json`` is the fallback) and stamped back
    on the run. False when the run is unknown or already accounted."""
    ledger = load_ledger(run_id)
    if ledger is None:
        return False
    run = ledger["run"]

    tokens_in = tokens_out = 0
    cost = 0.0
    found = False
    for step in ledger["steps"]:
        usage = _parse_json_dict(step.get("usage_json"))
        if not usage:
            continue
        found = True
        tokens_in += _coerce_tokens(usage.get("promptTokens"))
        tokens_out += _coerce_tokens(usage.get("completionTokens"))
        cost += _coerce_cost(usage.get("estimatedCost"))
    if not found:
        usage = _parse_json_dict(run.get("usage_json"))
        tokens_in = _coerce_tokens(usage.get("promptTokens"))
        tokens_out = _coerce_tokens(usage.get("completionTokens"))
        cost = _coerce_cost(usage.get("estimatedCost"))

    ensure_agent_runs_table()
    has_usage = tokens_in > 0 or tokens_out > 0 or cost > 0.0
    flip_sets = ["usage_accounted = true", "updated_at = now()"]
    if has_usage:
        totals_json = json.dumps({
            "promptTokens": tokens_in,
            "completionTokens": tokens_out,
            "estimatedCost": cost,
        })
        flip_sets.insert(1, "usage_json = {0}".format(sql_value(totals_json)))
    flip = (
        "WITH w AS ("
        " UPDATE {runs} SET {sets}"
        " WHERE run_id = {run_id} AND usage_accounted = false"
        " RETURNING user_id"
        ")"
    ).format(
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        sets=", ".join(flip_sets),
        run_id=sql_value(_req_id(run_id, "run_id")),
    )
    if has_usage:
        # Server-computed numeric literals (cost with fixed decimals, never
        # scientific notation) - the same convention as storage/usage.py.
        ensure_users_table()
        ensure_usage_monthly_table()
        in_sql = str(tokens_in)
        out_sql = str(tokens_out)
        cost_sql = "{:.10f}".format(cost)
        increments = (
            ", monthly AS ("
            " INSERT INTO {monthly} AS m"
            " (user_id, period_start, input_tokens, output_tokens, total_cost,"
            " request_count, updated_at)"
            " SELECT w.user_id, date_trunc('month', now())::date, {in_t}, {out_t},"
            " {cost}, 1, now() FROM w WHERE w.user_id IS NOT NULL"
            " ON CONFLICT (user_id, period_start) DO UPDATE SET"
            " input_tokens  = m.input_tokens  + EXCLUDED.input_tokens,"
            " output_tokens = m.output_tokens + EXCLUDED.output_tokens,"
            " total_cost    = m.total_cost    + EXCLUDED.total_cost,"
            " request_count = m.request_count + 1,"
            " updated_at    = now()"
            "), lifetime AS ("
            " UPDATE {users} AS u SET"
            " total_input_tokens  = u.total_input_tokens  + {in_t},"
            " total_output_tokens = u.total_output_tokens + {out_t},"
            " total_cost          = u.total_cost          + {cost},"
            " last_usage_at       = now()"
            " FROM w WHERE u.user_id = w.user_id"
            " RETURNING 1"
            ")"
        ).format(
            monthly=full_table(USAGE_MONTHLY_V1_LOGICAL),
            users=full_table(USERS_V1_LOGICAL),
            in_t=in_sql,
            out_t=out_sql,
            cost=cost_sql,
        )
    else:
        increments = ""
    statement = flip + increments + " SELECT count(*) AS n FROM w"
    accounted = _run_cas(statement)
    logger.info(
        "finalize_exchange_guard - run_id=%s accounted=%s in=%d out=%d cost=%.6f",
        run_id, accounted, tokens_in, tokens_out, cost,
    )
    return accounted


# --- Retention -----------------------------------------------------------------------
def purge_finished_runs(older_than_days=14, max_runs=1000):
    """Delete TERMINAL runs (with their steps + events) finished long ago. Bounded.

    One committed statement: a LIMITed victims CTE (never a full-table delete)
    feeds three DELETEs, so a pass can never remove more than ``max_runs`` runs -
    an internal maintenance task, NEVER on the hot request path. Returns the
    number of runs purged."""
    days = _int_arg(older_than_days, 1, 3650, "older_than_days")
    cap = _int_arg(max_runs, 1, MAX_PURGE_RUNS, "max_runs")
    ensure_agent_runs_table()
    ensure_agent_run_steps_table()
    ensure_agent_run_events_table()
    statement = (
        "WITH victims AS ("
        " SELECT run_id FROM {runs}"
        " WHERE status IN ({terminal})"
        " AND finished_at IS NOT NULL"
        " AND finished_at < now() - ({days} * interval '1 day')"
        " ORDER BY finished_at ASC LIMIT {cap}"
        "), de AS ("
        " DELETE FROM {events} WHERE run_id IN (SELECT run_id FROM victims)"
        " RETURNING 1"
        "), ds AS ("
        " DELETE FROM {steps} WHERE run_id IN (SELECT run_id FROM victims)"
        " RETURNING 1"
        "), dr AS ("
        " DELETE FROM {runs} WHERE run_id IN (SELECT run_id FROM victims)"
        " RETURNING 1"
        ") SELECT count(*) AS n FROM dr"
    ).format(
        runs=full_table(AGENT_RUNS_V1_LOGICAL),
        steps=full_table(AGENT_RUN_STEPS_V1_LOGICAL),
        events=full_table(AGENT_RUN_EVENTS_V1_LOGICAL),
        terminal=", ".join(sql_value(s) for s in RUN_TERMINAL_STATUSES),
        days=days,
        cap=cap,
    )
    df = new_executor().query_to_df(
        statement,
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY],
        post_queries=["COMMIT"],
    )
    try:
        purged = int(_first_value(df, "n", 0))
    except (TypeError, ValueError):
        purged = 0
    logger.info("purge_finished_runs - purged=%d (days=%d cap=%d)", purged, days,
                cap)
    return purged
