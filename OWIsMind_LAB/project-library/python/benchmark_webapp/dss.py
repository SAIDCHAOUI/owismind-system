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


# --- agent catalog + read-only discovery ------------------------------------
# The launcher curates its agent list ON DEMAND: pick a DSS project, list the agents inside it
# (LLM Mesh ids that start with "agent:"), then add the selected ones. Discovery is STRICTLY
# READ-ONLY (list calls only) and BOUNDED, so a handler can never trigger heavy/unbounded work on
# the instance. The chosen agents are stored in the ``agents`` key of the ``benchmark`` variable
# (no new dataset, no code change to add an agent). Writes go through _persist_agents under the
# shared registry lock (same variable), mirroring how the benchmark registry is persisted.

AGENT_ID_PREFIX = "agent:"
_MAX_PROJECTS = 500
_MAX_AGENTS = 200


def agents_catalog():
    """The curated catalog (the agents the admin has added) from the variable. Never raises -> []."""
    return registry.parse_agents(read_raw_benchmark_var().get("agents"))


def list_projects():
    """``[{project_key, name}]`` for projects this identity can see (sorted, bounded). Read-only.

    Reflects the running identity's permissions. One cheap catalog call for names when the DSS
    version supports it, else keys only. Never raises -> [].
    """
    try:
        client = dataiku.api_client()
    except Exception:
        return []
    try:
        out = []
        for s in (client.list_projects() or []):
            if not isinstance(s, dict):
                continue
            pk = str(s.get("projectKey") or "").strip()
            if pk:
                out.append({"project_key": pk, "name": (str(s.get("name") or pk).strip() or pk)})
        if out:
            out.sort(key=lambda p: p["name"].lower())
            return out[:_MAX_PROJECTS]
    except Exception:
        pass
    try:
        keys = sorted(str(k) for k in (client.list_project_keys() or []))
        return [{"project_key": k, "name": k} for k in keys[:_MAX_PROJECTS]]
    except Exception:
        logger.warning("benchmark webapp - could not list projects")
        return []


def _llm_name(llm, llm_id):
    """Best-effort human-friendly name for an LLM/agent list item; falls back to the id."""
    try:
        raw = llm.get_raw() if hasattr(llm, "get_raw") else None
    except Exception:
        raw = None
    if isinstance(raw, dict):
        for key in ("friendlyName", "name", "label", "description"):
            val = raw.get(key)
            if val and str(val).strip():
                return str(val).strip()
    val = getattr(llm, "description", None)
    if val and str(val).strip() and str(val).strip() != llm_id:
        return str(val).strip()
    return llm_id


def list_project_agents(project_key):
    """``[{agent_id, name}]`` for the agents in one project (LLMs with id 'agent:'). Read-only, bounded.

    Only projects visible to this identity are honored. Never raises -> [].
    """
    pk = str(project_key or "").strip()
    if not pk:
        return []
    try:
        client = dataiku.api_client()
        if pk not in {str(k) for k in (client.list_project_keys() or [])}:
            return []  # not visible to this identity
        proj = client.get_project(pk)
    except Exception:
        logger.warning("benchmark webapp - could not open project %s", pk)
        return []
    agents = []
    try:
        for llm in (proj.list_llms() or []):
            llm_id = getattr(llm, "id", None)
            if not llm_id or not str(llm_id).startswith(AGENT_ID_PREFIX):
                continue
            agents.append({"agent_id": str(llm_id), "name": _llm_name(llm, str(llm_id))})
            if len(agents) >= _MAX_AGENTS:
                logger.warning("benchmark webapp - project=%s hit MAX_AGENTS; list truncated", pk)
                break
    except Exception:
        logger.warning("benchmark webapp - could not list agents for %s", pk)
        return []
    agents.sort(key=lambda a: a["name"].lower())
    return agents


def _persist_agents(agents_list):
    """Write the ``agents`` catalog back into the variable, preserving all other keys. Caller holds lock."""
    raw = read_raw_benchmark_var()
    raw = dict(raw) if isinstance(raw, dict) else {}
    raw["agents"] = registry.serialize_agents(agents_list)
    write_benchmark_var(raw)


def connect_agents(project_key, selections):
    """Add the selected agents of ``project_key`` to the catalog. Returns ``(result, errors)``.

    ``selections`` is a list of ``{agent_id, agent_label, modes}``; agent_key is derived
    deterministically. Existing entries (same key) are updated (label / modes). RMW under the lock.
    """
    pk = str(project_key or "").strip()
    if not pk:
        return None, ["a project is required"]
    items = [s for s in (selections or [])
             if isinstance(s, dict) and str(s.get("agent_id") or "").strip()]
    if not items:
        return None, ["select at least one agent"]
    new_agents = [{
        "project_key": pk,
        "agent_id": s.get("agent_id"),
        "agent_label": s.get("agent_label"),
        "modes": bool(s.get("modes", True)),
    } for s in items]
    with _REGISTRY_LOCK:
        catalog = registry.upsert_agents(agents_catalog(), new_agents)
        _persist_agents(catalog)
    return {"agents": catalog}, []


def remove_agent_from_catalog(agent_key):
    """Remove one agent from the catalog by agent_key. Returns ``(result, errors)``. RMW under the lock."""
    akey = str(agent_key or "").strip()
    if not akey:
        return None, ["agent_key is required"]
    with _REGISTRY_LOCK:
        catalog = registry.remove_agent(agents_catalog(), akey)
        _persist_agents(catalog)
    return {"agents": catalog, "removed": akey}, []


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


# The 4 columns that identify ONE attempt (the override key + the full-detail lookup key).
_ATTEMPT_KEYS = ("run_id", "question_id", "agent_key", "mode")
# Backstop on rows streamed when looking up ONE attempt's full detail. A benchmark holds at most a
# few thousand scored rows; this only prevents a pathological unbounded scan, it is not a paginator.
_FULL_ROW_SCAN_CAP = 50000


def _key_str(value):
    """Trimmed string form of a match key (None -> '')."""
    if value is None:
        return ""
    return (value if isinstance(value, str) else str(value)).strip()


def read_scored_row_full(dataset_name, run_id, question_id, agent_key, mode):
    """Stream the scored dataset and return ONE attempt's FULL row (heavy columns kept), or None.

    The per-question table reads LIGHT columns only (``SCORED_KEEP`` drops the ~100k-char JSON blobs).
    When a reviewer opens one attempt we need its heavy ``generated_sql_json`` / ``answer_text`` to show
    the SQL the agent actually generated + the captured result table + the full answer. Rather than pull
    every row's blobs into RAM just to keep one, this STREAMS the dataset row by row (``iter_rows``) and
    returns the FIRST row whose (run_id, question_id, agent_key, mode) match, then stops.

    Instance-safe (SQL invariant preserved): NO raw SQL on the shared connection - this reads through the
    dataiku Dataset API only, one row in RAM at a time, early-exit on match, a hard scan backstop. This is
    strictly LIGHTER on RAM than the existing history merge / override read-modify-write, so it adds no new
    instance risk. Best-effort: a missing dataset / read error / no match -> None (caller shows "not found").
    """
    want = {k: _key_str(v) for k, v in
            (("run_id", run_id), ("question_id", question_id), ("agent_key", agent_key), ("mode", mode))}
    if not want["run_id"] or not want["question_id"]:
        return None
    try:
        ds = dataiku.Dataset(dataset_name)
        scanned = 0
        for row in ds.iter_rows():
            scanned += 1
            if scanned > _FULL_ROW_SCAN_CAP:
                break
            record = row if isinstance(row, dict) else dict(row)
            if all(_key_str(record.get(k)) == want[k] for k in _ATTEMPT_KEYS):
                return record
    except Exception:
        logger.warning("benchmark webapp - scored full-row read failed for %s", dataset_name)
        return None
    return None


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
    """Best-effort last/current run state for the status poll.

    Returns {running, benchmark_id, scored, total, run_request, last}. benchmark_id and total
    are derived from the stored run_request; scored counts rows written since requested_at.
    Never raises.
    """
    running = is_running(scen)
    last = None
    try:
        runs = scen.get_last_runs(limit=1)
        if runs:
            info = runs[0].get_info() if hasattr(runs[0], "get_info") else {}
            last = info.get("result") or info.get("outcome") or info
    except Exception:
        last = None
    # Enrich with run_request fields for the frontend progress poll.
    benchmark_id = ""
    run_request = None
    total_cells = 0
    scored_count = 0
    try:
        raw = read_raw_benchmark_var()
        rr = raw.get("run_request") if isinstance(raw, dict) else None
        if isinstance(rr, dict):
            run_request = rr
            benchmark_id = str(rr.get("benchmark_id") or "").strip()
            total_cells = int(rr.get("total_cells") or 0)
            requested_at = str(rr.get("requested_at") or "").strip()
            if benchmark_id and requested_at:
                try:
                    cfg = config()
                    scored_name = cfg.get("scored_dataset")
                    if scored_name:
                        rows = read_dataset(scored_name,
                                            keep_cols=["benchmark_id", "run_timestamp"])
                        scored_count = sum(
                            1 for r in rows
                            if isinstance(r, dict)
                            and str(r.get("benchmark_id") or "").strip() == benchmark_id
                            and str(r.get("run_timestamp") or "") >= requested_at
                        )
                except Exception:
                    scored_count = 0
    except Exception:
        pass
    return {
        "running": running,
        "benchmark_id": benchmark_id,
        "scored": scored_count,
        "total": total_cells,
        "run_request": run_request,
        "last": last,
    }


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
        # Stamp total_cells + requested_at for the status poll progress indicator.
        with _REGISTRY_LOCK:
            reg = read_registry()
            if benchmark_id not in reg:
                return None, "unknown_benchmark"
            entity = reg[benchmark_id]
            try:
                cfg = config()
                golden_rows = read_dataset(cfg.get("golden_dataset", ""),
                                           keep_cols=["question_id", "agent_key", "active"])
                scored_rows = read_dataset(cfg.get("scored_dataset", ""),
                                           keep_cols=["benchmark_id", "question_id",
                                                      "mode", "agent_key"])
                golden_ids = views._agent_tagged_active_ids(golden_rows,
                                                             entity.get("agent_key"))
                plan = registry.resolve_to_run(entity, golden_ids, scored_rows,
                                               req["launch_mode"])
                req["total_cells"] = sum(len(v) for v in plan.values())
            except Exception:
                req["total_cells"] = 0
            req["requested_at"] = _now_iso()
            _persist_registry(reg, run_request=req)
        launch(scen)
        logger.info("benchmark launcher - launched benchmark %s (%s)", benchmark_id,
                    req["launch_mode"])
        return {"launched": True, "benchmark_id": benchmark_id,
                "launch_mode": req["launch_mode"]}, None
    finally:
        RUN_LOCK.release()


def reconcile_redo_after_run(benchmark_id, run_id=None):
    """Clear redo flags for questions that ran in the LATEST scored run for this benchmark.

    ``run_id`` is accepted for call-site compat but IGNORED: DSS scenario run ids never match
    the step's uuid-based run_id, so filtering by run_id would always clear zero flags. Instead
    this reads the scored dataset (light: benchmark_id, question_id, run_timestamp), finds the
    LATEST run by max run_timestamp, collects its question_ids, and under _REGISTRY_LOCK clears
    the intersection with the entity's current redo set via registry.reset_redo_for. Idempotent -
    clearing an already-clear flag is a no-op. Never raises.
    """
    cfg = config()
    scored_name = cfg.get("scored_dataset")
    if not scored_name:
        return {"benchmark_id": benchmark_id, "cleared": 0}
    scored = read_dataset(scored_name,
                          keep_cols=["benchmark_id", "question_id", "run_timestamp"])
    bid = str(benchmark_id).strip()
    bench_rows = [
        r for r in scored
        if isinstance(r, dict)
        and str(r.get("benchmark_id") or "").strip() == bid
        and r.get("question_id")
    ]
    if not bench_rows:
        return {"benchmark_id": benchmark_id, "cleared": 0}
    # Find max run_timestamp to identify the latest run (any tie: all are included).
    latest_ts = max(str(r.get("run_timestamp") or "") for r in bench_rows)
    latest_qids = list({
        str(r.get("question_id") or "").strip()
        for r in bench_rows
        if str(r.get("run_timestamp") or "") == latest_ts
    })
    with _REGISTRY_LOCK:
        reg = read_registry()
        if benchmark_id not in reg:
            return {"benchmark_id": benchmark_id, "cleared": 0}
        entity = reg[benchmark_id]
        redo_set = set(entity.get("redo") or [])
        to_clear = [q for q in latest_qids if q in redo_set]
        reg = registry.reset_redo_for(reg, benchmark_id, to_clear)
        _persist_registry(reg)
    return {"benchmark_id": benchmark_id, "cleared": len(to_clear)}


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


# NOTE: the old dump-all discovery (discover_agents / connect_agent / _llm_label) was replaced by
# the curated add-agent flow at the top of this module (agents_catalog / list_projects /
# list_project_agents / connect_agents / remove_agent_from_catalog). Nothing lives here anymore.
