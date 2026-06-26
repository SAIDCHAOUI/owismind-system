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
  - The only WRITES are APPEND-preserving rewrites of LAB Flow datasets (the golden + a
    promoted-ids log) via the dataiku Dataset API - never raw SQL on the connection.
Keep it that way. The security audit verifies this invariant.
=======================================================================================

DSS-only (imports dataiku / pandas at top level); not unit-tested in the NO-INSTALL env, kept
thin so the testable logic lives in ``views``.
"""

import logging
import threading
import traceback

import dataiku
import pandas as pd

from benchmark import run_params, schemas
from benchmark_webapp import views

logger = logging.getLogger(__name__)

# In-process single-flight guards (the launcher webapp is one Flask backend process). PROMOTE
# serializes the golden read-modify-write so two concurrent promotions cannot lose a batch; RUN
# narrows the scenario-launch TOCTOU. Both are best-effort within ONE backend process: the
# AUTHORITATIVE cross-process guard for the scenario is "Prevent concurrent executions" on the
# Run_Benchmark scenario in DSS (see README), which these locks complement, not replace.
_PROMOTE_LOCK = threading.Lock()
RUN_LOCK = threading.Lock()

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


def launch(scen):
    """Fire the scenario async (best-effort across dataikuapi versions). Returns True/False."""
    for method in ("run_scenario", "run"):
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

    Columns = the canonical lean-9 GOLDEN_COLUMNS first, then any extra columns the prepared
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


def save_golden_question(cfg, payload):
    """Create or update one golden question. Returns ``(result_or_None, errors)``.

    Read-modify-write under the SAME promote lock with a RAISING existing-read: a transient
    read failure aborts (api returns 500) rather than overwriting the human-authored golden
    with a truncated set. A payload without a question_id is a create (minted ``a_`` id);
    one with a question_id updates that row (extra columns preserved). The write goes through
    the Dataset API (a LAB Flow dataset), NEVER raw SQL on the shared connection.
    """
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
    """
    qid = question_id.strip() if isinstance(question_id, str) else ""
    if not qid:
        return None, ["question_id is required"]
    with _PROMOTE_LOCK:
        ds = dataiku.Dataset(cfg["golden_dataset"])
        df = _golden_existing(ds)  # schema-gated RAISING read (abort on a blip, not truncate)
        existing = df.to_dict("records")
        rows = views.apply_golden_delete(existing, qid)
        if len(rows) == len(existing):
            return {"deleted": False, "count": len(rows)}, []
        _write_golden(ds, rows)
        return {"deleted": True, "count": len(rows)}, []
