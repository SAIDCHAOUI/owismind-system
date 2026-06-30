"""DSS I/O helpers for the benchmark webapps (the ONE place that touches dataiku / SQL).

Recolled into the OWIsMind_LAB project library next to ``views`` (pure) and ``benchmark``.
Both webapp backends (results/launcher) import this so the dataiku reads/writes live in a
single, auditable module; all logic stays in the pure, unit-tested ``views``.

=========================== SQL SAFETY (READ + APPEND ONLY) ===========================
The LAB project's SQL connection can see EVERY table on it (incl. the OWIsMind webapp's
chat / suggestion tables). This module is therefore strict:
  - The ONLY raw SQL executed on the shared connection is ``read_pending_suggestions``: a
    bounded, READ-ONLY ``SELECT`` (transaction_read_only + statement_timeout pre-queries, an
    explicit column list, a guarded physical table name, status='pending' literal, LIMIT 500).
  - There is NO UPDATE / DELETE / DROP / TRUNCATE / INSERT / raw DML on the shared connection
    anywhere in the benchmark webapps.
  - The only WRITES are rewrites of LAB Flow datasets via the dataiku Dataset API (never raw
    SQL on the connection): APPEND-preserving for the golden + promoted-ids log, and a
    read-modify-write of the scored dataset for a human review override (``write_override``).
    The override read-modify-write has the SAME RAM profile as the normal history merge the
    judge/aggregate steps already perform, so it adds no new instance-safety risk.
Keep it that way. The security audit verifies this invariant.
=======================================================================================

DSS-only (imports dataiku / pandas at top level); not unit-tested in the NO-INSTALL env, kept
thin so the testable logic lives in ``views``.
"""

import datetime
import logging
import threading
import traceback
import uuid

import dataiku
import pandas as pd

from benchmark import run_params, schemas
from benchmark import registry
from benchmark_webapp import views

logger = logging.getLogger(__name__)

# In-process single-flight guards (the launcher webapp is one Flask backend process). PROMOTE
# serializes the golden read-modify-write so two concurrent promotions cannot lose a batch; RUN
# narrows the scenario-launch TOCTOU. Both are best-effort within ONE backend process: the
# AUTHORITATIVE cross-process guard for the scenario is "Prevent concurrent executions" on the
# Run_Benchmark scenario in DSS (see README), which these locks complement, not replace.
_PROMOTE_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()
# Serializes the scored read-modify-write so two concurrent reviewer overrides cannot lose each
# other's change (lost update); same role as _PROMOTE_LOCK for the golden.
_OVERRIDE_LOCK = threading.Lock()
# Serializes every read-modify-write of the ``benchmark`` project variable's registry (create a
# benchmark, toggle the redo flag, write a launch request), so two concurrent launcher edits
# cannot clobber each other's change. The launcher is one Flask process.
_REGISTRY_LOCK = threading.Lock()

SCENARIO_ID = "Run_Benchmark"
# Heavy columns never shipped to the per-question table (kept in the dataset for the dashboard).
SCORED_DROP = ("full_answer", "generated_sql_json", "artifacts_json", "config_json")
# The LIGHT keep-list for the public per-question read: every scored column EXCEPT the heavy JSON
# blobs above, so the read projects at the source (the heavy columns are never materialized).
SCORED_KEEP = tuple(c for c in schemas.SCORED_COLUMNS if c not in SCORED_DROP)
# Absolute cap on rows pulled from the (small) result datasets - a backstop, not a paginator.
MAX_ROWS = 5000
# Read guards mirrored from the webapp storage (read-only + statement_timeout).
_READ_PRE = ["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]


# --- config / variables -----------------------------------------------------

def variables():
    """Merged custom variables (resolved). Never raises."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def config():
    """Resolved benchmark config from the project variable."""
    return run_params.resolve(variables())


def project():
    """dataikuapi handle on THIS (LAB) project."""
    return dataiku.api_client().get_project(dataiku.default_project_key())


def read_raw_benchmark_var():
    """The raw editable ``benchmark`` object from Local variables ({} when absent)."""
    try:
        allvars = project().get_variables() or {}
        return (allvars.get("local") or {}).get("benchmark") or {}
    except Exception:
        logger.warning("benchmark webapp - could not read raw project variable")
        return {}


def write_benchmark_var(obj):
    """Write the ``benchmark`` object to Local variables (overwrites only that key)."""
    proj = project()
    allvars = proj.get_variables() or {}
    allvars.setdefault("local", {})
    allvars["local"]["benchmark"] = obj
    proj.set_variables(allvars)


# --- dataset reads (bounded, NaN-safe) --------------------------------------

def read_dataset(name, drop_cols=(), keep_cols=None, max_rows=MAX_ROWS):
    """Read a managed dataset -> list of dicts (NaN -> None, projected, row-capped).

    Pushes the column projection + the row cap INTO the read (get_dataframe(columns=..., limit=...))
    so the heavy columns (full_answer / SQL / artifacts JSON, up to ~100k chars/row on the scored
    table) are never materialized into RAM just to be dropped - the cap then actually bounds the
    LOAD, not only the post-load frame. ``keep_cols`` is an explicit keep-list (preferred for the
    heavy scored table); ``drop_cols`` is the legacy exclude-list. Falls back to a plain read +
    drop/head on a DSS version that rejects the kwargs. Never raises: a missing/empty dataset -> [].
    """
    ds = dataiku.Dataset(name)
    df = None
    if keep_cols is not None:
        try:
            df = ds.get_dataframe(columns=list(keep_cols), sampling="head", limit=max_rows)
        except TypeError:
            df = None  # older DSS: kwargs unsupported -> fall back below
        except Exception:
            logger.warning("benchmark webapp - dataset %s unreadable", name)
            return []
    if df is None:
        try:
            df = ds.get_dataframe()
        except Exception:
            logger.warning("benchmark webapp - dataset %s unreadable", name)
            return []
        if df is None or len(df) == 0:
            return []
        drop = [c for c in drop_cols if c in df.columns]
        if drop:
            df = df.drop(columns=drop)
        if keep_cols is not None:
            df = df[[c for c in keep_cols if c in df.columns]]
    if df is None or len(df) == 0:
        return []
    if max_rows and len(df) > max_rows:
        df = df.head(max_rows)
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict("records")


# --- scenario (launch + status), best-effort + single-flight ----------------

def scenario():
    return project().get_scenario(SCENARIO_ID)


def is_running(scen):
    """Best-effort: True when a Run_Benchmark run is currently in progress. Never raises."""
    try:
        if scen.get_current_run():
            return True
    except Exception:
        pass
    try:
        last = scen.get_last_runs(limit=1)
        if last:
            info = last[0].get_info() if hasattr(last[0], "get_info") else {}
            running = info.get("running")
            if running is not None:
                return bool(running)
    except Exception:
        pass
    return False


_LAUNCH_METHODS = ("run_scenario", "run")


def _can_launch(scen):
    """True when this dataikuapi version exposes a way to fire the scenario (without firing it).

    Lets launch_benchmark detect a launch_unsupported deploy BEFORE it mutates the registry, so a
    rejected launch never consumes the redo intent.
    """
    return any(callable(getattr(scen, m, None)) for m in _LAUNCH_METHODS)


def launch(scen):
    """Fire the scenario async (best-effort across dataikuapi versions). Returns True/False."""
    for method in _LAUNCH_METHODS:
        fn = getattr(scen, method, None)
        if callable(fn):
            fn()
            return True
    return False


def last_status(scen):
    """Best-effort last/current run state for the status poll."""
    running = is_running(scen)
    last = None
    try:
        runs = scen.get_last_runs(limit=1)
        if runs:
            info = runs[0].get_info() if hasattr(runs[0], "get_info") else {}
            last = info.get("result") or info.get("outcome") or info
    except Exception:
        last = None
    return {"running": running, "last": last}


# --- suggestions: the ONLY raw SQL on the shared connection (READ-ONLY) ------

def _suggestion_executor(conn):
    from dataiku import SQLExecutor2
    return SQLExecutor2(connection=conn)


def read_pending_suggestions(cfg):
    """Read pending user suggestions cross-project (READ-ONLY). Returns (rows, error_code).

    The ONLY raw SQL the benchmark webapps run on the shared connection. It is a bounded,
    read-only SELECT: an explicit column list, a GUARDED physical table name (plain identifier
    only, via views.safe_table_name), the status='pending' literal, LIMIT 500, and the
    read-only + statement_timeout pre-queries. The connection name is an admin-config value
    passed as a SQLExecutor2 API parameter, never interpolated into SQL.
    """
    sug = run_params.suggestions_config(cfg)
    conn = sug.get("connection")
    table = views.safe_table_name(sug.get("table"))
    if not conn or not table:
        return None, "not_configured"
    sql = (
        'SELECT suggestion_id, user_id, source, question, reference_answer, '
        'answer_is_correct, missing_explanation, expected_value, expected_value_type, '
        'category, language, created_at '
        'FROM public."{0}" WHERE status = \'pending\' ORDER BY created_at DESC LIMIT 500'
    ).format(table)
    try:
        df = _suggestion_executor(conn).query_to_df(sql, pre_queries=_READ_PRE)
    except Exception:
        logger.error("read suggestions failed\n%s", traceback.format_exc())
        return None, "read_failed"
    if df is None or len(df) == 0:
        return [], None
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict("records"), None


def read_promoted_ids(cfg):
    """Already-promoted suggestion ids (LAB log dataset). [] when absent. Never raises.

    This is the best-effort AUDIT log only; the authoritative "already promoted" signal is the
    golden's question_ids (read_golden_question_ids), so a stale/empty log can never hide a
    genuinely new suggestion nor corrupt the golden.
    """
    name = run_params.suggestions_config(cfg).get("promoted_dataset")
    if not name:
        return []
    rows = read_dataset(name)
    return [str(r.get("suggestion_id")) for r in rows if r.get("suggestion_id")]


def read_golden_question_ids(cfg):
    """The set of question_ids already in the golden dataset. Fail-open ({} on any read error).

    The SOURCE OF TRUTH for "already promoted": a suggestion is already in the golden iff its
    minted question_id (views.minted_question_id) is in this set. Fail-open is the safe direction:
    a read failure shows MORE pending suggestions (re-promotion is idempotent + de-duped), never
    hides a new one and never corrupts anything.
    """
    name = cfg.get("golden_dataset")
    if not name:
        return set()
    rows = read_dataset(name, keep_cols=["question_id"])
    return {str(r.get("question_id")) for r in rows if r.get("question_id")}


def _golden_existing(ds):
    """Existing golden frame for a read-modify-write, schema-gated + abort-safe (NaN -> None).

    A never-built golden (its schema reads back empty) returns an EMPTY frame so the FIRST
    question can be created through the launcher (parity with the history step's gate). A BUILT
    golden is read with a RAISING get_dataframe so a transient blip ABORTS the write (lesson
    L104: never overwrite the human-authored golden with a truncated set). A schema-read failure
    is AMBIGUOUS, so it falls through to the raising read - it never assumes empty on a blip.
    """
    schema = None
    try:
        schema = ds.read_schema()
    except Exception:
        schema = None  # ambiguous -> fall through to the raising read (never assume empty)
    if schema is not None and not schema:
        return pd.DataFrame()  # definitively never built: legitimate empty start
    df = ds.get_dataframe()  # RAISES on a transient error -> abort (no truncation)
    return df.astype(object).where(pd.notnull(df), None)


# --- promotion: APPEND to LAB Flow datasets ONLY (Dataset API, never raw SQL) ----

def append_golden_and_record(cfg, golden_rows, used_ids):
    """Append promoted suggestions to the golden dataset + record their ids. Returns counts.

    APPEND-preserving. CRITICAL data-safety: the existing-golden read here uses a RAISING read
    (dataiku.Dataset(...).get_dataframe()), NOT the error-swallowing read_dataset() - a transient
    read failure (SQL blip, statement timeout, a concurrent rebuild) MUST abort the rewrite
    (api_promote then returns 500), so an empty result from a real error can never overwrite the
    human-authored golden with only the few new rows. New rows are de-duped by question_id against
    what is already there; the union is written via the Dataset API (a LAB Flow dataset, NOT raw
    SQL). pandas concat preserves any EXTRA columns the prepared golden carries beyond the lean-9
    schema, so the rewrite never narrows the dataset. The promoted-ids log is rewritten with the
    union of old + newly used ids (idempotent).
    """
    from benchmark import schemas
    # Serialize the whole read-modify-write under one process lock: two concurrent promotions each
    # reading the same N existing rows would otherwise have the later write clobber the earlier and
    # silently drop a batch (lost update). The lock makes the second promotion read the first one's
    # committed golden, so its de-dup is correct. (Cross-process: see the DSS scenario note + RUN_LOCK.)
    with _PROMOTE_LOCK:
        golden_name = cfg["golden_dataset"]
        ds = dataiku.Dataset(golden_name)
        df_existing = _golden_existing(ds)  # schema-gated RAISING read (abort on a blip, not truncate)
        existing_qids = set()
        if "question_id" in df_existing.columns:
            existing_qids = {str(v) for v in df_existing["question_id"].tolist() if v is not None}
        new_rows = [r for r in golden_rows if r["question_id"] not in existing_qids]
        if new_rows:
            cols = list(schemas.GOLDEN_COLUMNS)
            new_df = pd.DataFrame([{c: r.get(c) for c in cols} for r in new_rows], columns=cols)
            # concat unions columns: any extra existing columns survive (None for the new rows),
            # so promotion never drops bookkeeping/import columns the prepared golden may carry.
            combined = pd.concat([df_existing, new_df], ignore_index=True, sort=False)
            ds.write_with_schema(combined)
        # Best-effort AUDIT log of promoted ids (NON-authoritative: the golden's question_ids are
        # the source of truth for "already promoted", see read_golden_question_ids). NEVER truncate
        # it from a swallowed read: read with a RAISING read and SKIP the update on any failure (the
        # golden already records the promotion via question_id), so a blip cannot wipe the history.
        promoted_name = run_params.suggestions_config(cfg).get("promoted_dataset")
        if promoted_name and used_ids:
            try:
                prev = dataiku.Dataset(promoted_name).get_dataframe()
                prev = prev.astype(object).where(pd.notnull(prev), None)
                before = ([str(v) for v in prev["suggestion_id"].tolist() if v is not None]
                          if "suggestion_id" in prev.columns else [])
                all_ids = sorted(set(before) | set(used_ids))
                dataiku.Dataset(promoted_name).write_with_schema(
                    pd.DataFrame({"suggestion_id": all_ids}))
            except Exception:
                logger.warning("benchmark promote: promoted-ids audit log update skipped "
                               "(read/write failed); the golden question_ids stay the source of truth")
        return {"promoted": len(new_rows), "recorded": len(used_ids)}


# --- golden CRUD: admin management of the golden dataset (Dataset API only) ------

def read_golden_rows(cfg):
    """All golden rows shaped for the management table (views.golden_view). Never raises -> []."""
    return views.golden_view(read_dataset(cfg["golden_dataset"]))


def _write_golden(ds, rows):
    """Write the full golden row list via the Dataset API, preserving any extra columns.

    Columns = the canonical GOLDEN_COLUMNS first, then any extra columns the prepared
    golden carries (kept after the canonical ones), so a rewrite never narrows the dataset.
    """
    cols = list(schemas.GOLDEN_COLUMNS)
    extra = []
    for r in rows:
        for key in r.keys():
            if key not in cols and key not in extra:
                extra.append(key)
    all_cols = cols + extra
    df = pd.DataFrame([{c: r.get(c) for c in all_cols} for r in rows], columns=all_cols)
    ds.write_with_schema(df)


def _ensure_golden_agent_key_column(dataset_name):
    """Idempotent: add the agent_key column to the golden dataset schema if missing. Best-effort.

    Uses the dataiku.Dataset schema API: read_schema() returns a list of column dicts;
    write_schema() persists the updated list. Wrapped in try/except so a schema-evolution
    failure never blocks a golden write - the data will carry the column regardless.

    NEEDS INSTANCE VERIFICATION: dataiku.Dataset.read_schema() and write_schema() shapes.
    """
    try:
        ds = dataiku.Dataset(dataset_name)
        schema = ds.read_schema()
        if not isinstance(schema, list):
            return
        col_names = {c.get("name") for c in schema if isinstance(c, dict)}
        if "agent_key" not in col_names:
            new_schema = list(schema)
            new_schema.append({"name": "agent_key", "type": "string"})
            ds.write_schema(new_schema)
    except Exception:
        logger.warning("benchmark webapp - could not evolve golden schema for agent_key (%s)",
                       dataset_name)


def save_golden_question(cfg, payload):
    """Create or update one golden question. Returns ``(result_or_None, errors)``.

    Read-modify-write under the SAME promote lock with a RAISING existing-read: a transient
    read failure aborts (api returns 500) rather than overwriting the human-authored golden
    with a truncated set. A payload without a question_id is a create (minted ``a_`` id);
    one with a question_id updates that row (extra columns preserved). The write goes through
    the Dataset API (a LAB Flow dataset), NEVER raw SQL on the shared connection.
    Ensures the agent_key column exists in the schema (best-effort) before writing.
    """
    _ensure_golden_agent_key_column(cfg["golden_dataset"])
    with _PROMOTE_LOCK:
        ds = dataiku.Dataset(cfg["golden_dataset"])
        df = _golden_existing(ds)  # schema-gated: empty on a never-built golden, RAISES on a blip
        existing = df.to_dict("records")
        existing_ids = [r.get("question_id") for r in existing if r.get("question_id") is not None]
        clean_row, errors, is_new = views.prepare_golden_save(payload, existing_ids)
        if errors:
            return None, errors
        rows = views.apply_golden_upsert(existing, clean_row)
        _write_golden(ds, rows)
        return {"question_id": clean_row["question_id"], "created": is_new, "count": len(rows)}, []


def delete_golden_question(cfg, question_id):
    """Hard-delete one golden question by id. Returns ``(result_or_None, errors)``.

    Locked + RAISING read (same data-safety as save). Removing a question never touches the
    PAST run results (raw/scored keep their own rows by question_id), only the golden set.
    Ensures the agent_key column exists in the schema (best-effort) before writing.
    """
    qid = question_id.strip() if isinstance(question_id, str) else ""
    if not qid:
        return None, ["question_id is required"]
    _ensure_golden_agent_key_column(cfg["golden_dataset"])
    with _PROMOTE_LOCK:
        ds = dataiku.Dataset(cfg["golden_dataset"])
        df = _golden_existing(ds)  # schema-gated RAISING read (abort on a blip, not truncate)
        existing = df.to_dict("records")
        rows = views.apply_golden_delete(existing, qid)
        if len(rows) == len(existing):
            return {"deleted": False, "count": len(rows)}, []
        _write_golden(ds, rows)
        return {"deleted": True, "count": len(rows)}, []


# --- human-in-the-loop override: read-modify-write of the scored dataset ----------

def write_override(cfg, payload, reviewed_at):
    """Apply one reviewer override into benchmark_runs_scored. Returns ``(result, errors)``.

    Read-modify-write under _OVERRIDE_LOCK, schema-gated + abort-safe (the same RAISING read as
    the golden, so a transient blip aborts rather than truncating the scored history). Sets the
    human_* fields on the row(s) matching (run_id, question_id, agent_key, mode) and rewrites the
    FULL scored schema (plus any extra columns) so the heavy answer/SQL columns are preserved.
    Because scored accumulates by run_id, the override survives every future run untouched.
    ``reviewed_at`` is stamped by the caller (the DSS layer owns the clock).
    """
    ok, errors = views.validate_override(payload)
    if not ok:
        return None, errors
    stamped = dict(payload)
    stamped["reviewed_at"] = reviewed_at
    with _OVERRIDE_LOCK:
        ds = dataiku.Dataset(cfg["scored_dataset"])
        df = _golden_existing(ds)  # schema-gated RAISING read (abort on a blip, never truncate)
        if df.empty:
            return None, ["no scored results to override yet"]
        rows, matched = views.apply_override(df.to_dict("records"), stamped)
        if matched == 0:
            return {"matched": 0}, []
        cols = list(schemas.SCORED_COLUMNS)
        seen = set(cols)
        extra = []
        for r in rows:
            for key in r.keys():
                if key not in seen:
                    seen.add(key)
                    extra.append(key)
        all_cols = cols + extra
        out = pd.DataFrame([{c: r.get(c) for c in all_cols} for r in rows], columns=all_cols)
        ds.write_with_schema(out)
        return {"matched": matched}, []


# --- v2: named per-agent benchmarks (registry in the variable + launch) ----------
# The registry + the per-question "redo at next run" intent live IN the ``benchmark`` project
# variable (no new dataset). Every mutation is a read-modify-write of that variable serialized by
# _REGISTRY_LOCK; the clock + uuid live here (the pure registry/views modules never read them).

def _now_iso():
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _new_benchmark_id():
    return uuid.uuid4().hex


def read_registry():
    """The parsed registry ({benchmark_id: entity}) from the variable. Never raises -> {}."""
    return registry.parse_registry(read_raw_benchmark_var().get("benchmarks"))


def _persist_registry(reg, run_request="__keep__"):
    """Write the registry (and optionally the run_request) back into the variable, preserving all
    other keys. ``run_request="__keep__"`` leaves the existing run_request untouched; pass None to
    clear it or a dict to set it. Caller holds _REGISTRY_LOCK."""
    raw = read_raw_benchmark_var()
    raw = dict(raw) if isinstance(raw, dict) else {}
    raw["benchmarks"] = registry.serialize_registry(reg)
    if run_request != "__keep__":
        raw["run_request"] = run_request
    write_benchmark_var(raw)


def benchmark_agents_catalog(cfg):
    """The agent catalog (from benchmark.agents) the launcher offers when creating a benchmark."""
    return views.config_view(cfg).get("agents", [])


# --- registry mutations (all RMW under _REGISTRY_LOCK) -----------------------

def create_benchmark(name, agent, modes, created_by=""):
    """Create a new benchmark in the registry. Returns ``(result, errors)``.

    ``agent`` is ``{agent_key, agent_label, project_key, agent_id}`` (from the catalog). ``modes``
    is the mode list (e.g. ["Smart","Pro","Claude"] or ["default"]). Name uniqueness is checked
    PER AGENT (case-insensitive): two different agents may each have a benchmark named "Q4".
    Membership is AUTO-DERIVED at run time from the golden rows tagged to the agent_key, so no
    question seeding happens here. Gating on the tagged-question count is done in the backend
    route, not here.
    """
    with _REGISTRY_LOCK:
        reg = read_registry()
        agent_key = (agent or {}).get("agent_key", "") if isinstance(agent, dict) else ""
        ok, err = views.validate_benchmark_name(name, registry.names_for_agent(reg, agent_key))
        if not ok:
            return None, [err]
        bid = _new_benchmark_id()
        reg = registry.create_benchmark(reg, bid, name, agent, modes, _now_iso(), created_by)
        _persist_registry(reg)
        return {"benchmark_id": bid, "name": name}, []


def delete_benchmark(benchmark_id):
    """Hard-delete a benchmark from the registry. Returns ``(result, errors)``. Locked.

    Scored rows for this benchmark_id are untouched (they accumulate in the dataset and remain
    readable; the deletion only removes the registry entry so the benchmark no longer appears
    in the active list). Irreversible - no soft-delete / archive in the v2 model.
    """
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return None, ["unknown benchmark"]
        reg = registry.delete_benchmark(reg, benchmark_id)
        _persist_registry(reg)
        return {"benchmark_id": benchmark_id, "deleted": True}, []


def set_benchmark_modes(benchmark_id, modes):
    """Update the modes list on a benchmark. Returns ``(result, errors)``. Locked.

    ``modes`` is a list of mode strings; passing [] sets the benchmark to the single default
    mode (the step falls back to registry.DEFAULT_MODE). No registry module function exists for
    this mutation, so it is done inline on the normalized entity dict.
    """
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return None, ["unknown benchmark"]
        entity = dict(reg[benchmark_id])
        entity["modes"] = [m for m in (modes or []) if isinstance(m, str) and m.strip()]
        reg = dict(reg)
        reg[benchmark_id] = entity
        _persist_registry(reg)
        return {"benchmark_id": benchmark_id, "modes": entity["modes"]}, []


def set_question_redo(benchmark_id, question_id, value):
    """Set/clear the 'redo at next run' flag on a question in this benchmark's redo list.

    Returns ``(result, errors)``. Locked RMW.
    """
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return None, ["unknown benchmark"]
        reg = registry.set_redo(reg, benchmark_id, question_id, bool(value))
        _persist_registry(reg)
        return {"benchmark_id": benchmark_id, "question_id": question_id,
                "redo": bool(value)}, []


def rename_benchmark(benchmark_id, name):
    """Rename a benchmark (name must stay unique per agent). Returns ``(result, errors)``. Locked."""
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return None, ["unknown benchmark"]
        entity = reg[benchmark_id]
        agent_key = entity.get("agent_key", "")
        # Exclude this benchmark's own current name from the uniqueness check.
        current_lower = str(entity.get("name") or "").strip().lower()
        taken = registry.names_for_agent(reg, agent_key) - {current_lower}
        ok, err = views.validate_benchmark_name(name, taken)
        if not ok:
            return None, [err]
        reg = registry.rename_benchmark(reg, benchmark_id, name)
        _persist_registry(reg)
        return {"benchmark_id": benchmark_id, "name": name}, []


def launch_benchmark(benchmark_id, launch_mode):
    """Write the launch request and fire the scenario. Returns (result, err).

    Sets ``run_request`` = {benchmark_id, launch_mode} in the variable so step_run_matrix runs
    exactly this benchmark, then fires the scenario under the single-flight RUN_LOCK (the
    authoritative cross-process guard is the scenario's "Prevent concurrent executions").
    The redo flags are NOT consumed here: they are cleared by ``reconcile_redo_after_run`` AFTER
    the run's scored rows land (so a rejected launch - 409 already running - never silently drops
    the redo intent). The error code mirrors api_run.
    """
    req = views.build_launch_request(benchmark_id, launch_mode)
    if not req:
        return None, "bad_request"
    # Validate the benchmark exists WITHOUT mutating the registry (rejected launch leaves redo
    # flags intact).
    if benchmark_id not in read_registry():
        return None, "unknown_benchmark"
    if not RUN_LOCK.acquire(blocking=False):
        return None, "already_running"
    try:
        scen = scenario()
        if is_running(scen):
            return None, "already_running"
        if not _can_launch(scen):
            return None, "launch_unsupported"
        # Write run_request now (the scenario step reads it fresh at its start).
        with _REGISTRY_LOCK:
            reg = read_registry()
            if benchmark_id not in reg:
                return None, "unknown_benchmark"
            _persist_registry(reg, run_request=req)
        launch(scen)
        logger.info("benchmark launcher - launched benchmark %s (%s)", benchmark_id,
                    req["launch_mode"])
        return {"launched": True, "benchmark_id": benchmark_id,
                "launch_mode": req["launch_mode"]}, None
    finally:
        RUN_LOCK.release()


def reconcile_redo_after_run(benchmark_id, run_id):
    """Clear redo flags for questions that landed a scored row in this run. Idempotent, locked.

    Called by the backend route/poll after a run finishes. Reads the scored dataset to find
    question_ids present for this run_id + benchmark_id, then resets their redo flags so the next
    append launch does not re-run them again. Safe to call multiple times (reset_redo_for is a
    no-op for questions not in the redo list).
    """
    cfg = config()
    scored_name = cfg.get("scored_dataset")
    if not scored_name:
        return {"benchmark_id": benchmark_id, "cleared": 0}
    scored = read_dataset(scored_name, keep_cols=["run_id", "benchmark_id", "question_id"])
    rid = str(run_id).strip()
    bid = str(benchmark_id).strip()
    done_qids = list({
        str(r.get("question_id", "")).strip()
        for r in scored
        if str(r.get("run_id", "")).strip() == rid
        and str(r.get("benchmark_id", "")).strip() == bid
        and r.get("question_id")
    })
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return {"benchmark_id": benchmark_id, "cleared": 0}
        reg = registry.reset_redo_for(reg, benchmark_id, done_qids)
        _persist_registry(reg)
    return {"benchmark_id": benchmark_id, "cleared": len(done_qids)}


# --- settings (global benchmark keys in the variable) -----------------------

def read_settings():
    """Read the global benchmark settings (dataset names, judge llm, concurrency, language).

    Returns the settings view-model shaped by views.settings_view. Never raises -> defaults.
    """
    try:
        cfg = config()
        return views.settings_view(cfg)
    except Exception:
        logger.warning("benchmark webapp - could not read settings")
        return views.settings_view({})


def _validate_golden_dataset(name):
    """Check the golden dataset exists and has the minimum schema (question + reference_answer).

    Also bootstraps the agent_key column if missing (best-effort). Returns (ok, errors).
    NEEDS INSTANCE VERIFICATION: dataiku.Dataset.read_schema() shape.
    """
    if not name or not str(name).strip():
        return False, ["golden_dataset is required"]
    try:
        ds = dataiku.Dataset(name)
        schema = ds.read_schema()
    except Exception:
        return False, ["golden dataset '{0}' not found or not readable".format(name)]
    if not isinstance(schema, list):
        return False, ["could not read schema for golden dataset '{0}'".format(name)]
    col_names = {c.get("name") for c in schema if isinstance(c, dict)}
    missing = []
    for required in ("question", "reference_answer"):
        if required not in col_names:
            missing.append(required)
    if missing:
        return False, ["golden dataset missing required columns: {0}".format(", ".join(missing))]
    # Bootstrap agent_key best-effort (does not count as a validation failure).
    if "agent_key" not in col_names:
        try:
            ds.write_schema(list(schema) + [{"name": "agent_key", "type": "string"}])
        except Exception:
            pass
    return True, []


def save_settings(form):
    """Validate and persist the global benchmark settings. Returns ``(result, errors)``.

    Validates with views.validate_settings, validates the golden dataset schema (must exist +
    have question + reference_answer), then writes the normalized keys into the raw variable
    (preserving all other keys like suggestions / benchmarks / agents / run_request).
    Never auto-creates datasets.
    """
    ok, result = views.validate_settings(form)
    if not ok:
        return None, result  # result is a list of error strings
    normalized = result
    golden_name = normalized.get("golden_dataset", "")
    if golden_name:
        ds_ok, ds_errors = _validate_golden_dataset(golden_name)
        if not ds_ok:
            return None, ds_errors
    with _REGISTRY_LOCK:
        raw = read_raw_benchmark_var()
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw.update(normalized)
        write_benchmark_var(raw)
    return {"saved": True}, []


def reset_run_request():
    """Clear run_request ONLY when the scenario is verifiably idle. Returns (result, errors).

    A running scenario means the run_request is still being consumed by the step; clearing it
    mid-run would confuse the step. Returns ``{error: "run_active"}`` when a run is in progress.
    """
    try:
        scen = scenario()
        if is_running(scen):
            return None, ["run_active"]
    except Exception:
        # If we cannot determine status, refuse to clear (safe direction: assume running).
        return None, ["run_active"]
    with _REGISTRY_LOCK:
        raw = read_raw_benchmark_var()
        raw = dict(raw) if isinstance(raw, dict) else {}
        raw["run_request"] = None
        write_benchmark_var(raw)
    return {"cleared": True}, []


# --- agent catalog: discovery + manual connect --------------------------------

def agents_catalog():
    """The cached agent catalog from the variable (no discovery call). Returns list. Never raises."""
    try:
        raw = read_raw_benchmark_var()
        agents = raw.get("agents")
        if isinstance(agents, list):
            return [a for a in agents if isinstance(a, dict)]
        return []
    except Exception:
        return []


def connect_agent(agent_key, agent_label, project_key, agent_id, modes=True):
    """Upsert one agent entry into the variable's agents catalog by agent_key. Returns (result, errors).

    Creates a new entry when agent_key is unknown; updates the existing entry when it already
    exists. RMW under _REGISTRY_LOCK so concurrent calls cannot clobber each other.
    """
    akey = str(agent_key).strip() if agent_key else ""
    if not akey:
        return None, ["agent_key is required"]
    entry = {
        "agent_key": akey,
        "agent_label": str(agent_label or "").strip() or akey,
        "project_key": str(project_key or "").strip(),
        "agent_id": str(agent_id or "").strip(),
        "modes": bool(modes),
    }
    with _REGISTRY_LOCK:
        raw = read_raw_benchmark_var()
        raw = dict(raw) if isinstance(raw, dict) else {}
        existing = raw.get("agents")
        catalog = [a for a in (existing or []) if isinstance(a, dict)]
        replaced = False
        updated = []
        for a in catalog:
            if str(a.get("agent_key", "")).strip() == akey:
                updated.append(entry)
                replaced = True
            else:
                updated.append(a)
        if not replaced:
            updated.append(entry)
        raw["agents"] = updated
        write_benchmark_var(raw)
    return {"agent_key": akey, "created": not replaced}, []


def _accessible_project_keys(client):
    """Best-effort list of project keys accessible via the API client. Never raises."""
    try:
        return client.list_project_keys()
    except Exception:
        pass
    try:
        return [p.project_key for p in client.list_projects()]
    except Exception:
        return []


def _llm_label(llm):
    """Best-effort human label from an LLM object (dict or object with attributes). Never raises."""
    if isinstance(llm, dict):
        return (llm.get("label") or llm.get("name") or llm.get("id") or "")
    for attr in ("label", "name", "id"):
        val = getattr(llm, attr, None)
        if val:
            return str(val)
    return ""


def discover_agents():
    """Enumerate LLM-based agents across accessible DSS projects (best-effort, cached).

    Iterates every accessible project and lists its LLMs via the dataikuapi client, collecting
    entries whose id starts with "agent:". Writes the discovered catalog into the variable under
    "agents" with a discovery timestamp. On ANY exception (permission denied, API not available,
    unknown dataikuapi version) degrades gracefully to the manual catalog (agents_catalog()).

    NEEDS INSTANCE VERIFICATION:
      - dataikuapi Project.list_llms() existence and return type (list of dicts or objects).
      - The shape of each LLM entry (id field vs attribute, label/name field).
      - client.list_project_keys() vs client.list_projects() for project enumeration.
    """
    try:
        client = dataiku.api_client()
        found = []
        for pkey in _accessible_project_keys(client):
            try:
                proj = client.get_project(pkey)
                for llm in (proj.list_llms() or []):
                    lid = None
                    if isinstance(llm, dict):
                        lid = llm.get("id")
                    else:
                        lid = getattr(llm, "id", None)
                    if not lid or not str(lid).startswith("agent:"):
                        continue
                    label = _llm_label(llm) or str(lid)
                    found.append({
                        "project_key": pkey,
                        "agent_id": str(lid),
                        "agent_label": label,
                        "agent_key": registry.slug_agent_key(label),
                        "modes": True,
                    })
            except Exception:
                continue
        with _REGISTRY_LOCK:
            raw = read_raw_benchmark_var()
            raw = dict(raw) if isinstance(raw, dict) else {}
            raw["agents"] = found
            raw["agents_discovered_at"] = _now_iso()
            write_benchmark_var(raw)
        return {"status": "ok", "discovery": "ok", "agents": found}
    except Exception:
        logger.warning("benchmark webapp - agent discovery failed; using cached catalog\n%s",
                       traceback.format_exc())
        return {"status": "ok", "discovery": "unavailable", "agents": agents_catalog()}
