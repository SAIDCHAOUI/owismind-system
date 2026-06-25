# OWIsMind_LAB benchmark webapp - Python backend (paste into the Standard webapp Python pane).
#
# A standard DSS webapp (HTML/CSS/JS + this Python backend) inside OWIsMind_LAB. DSS provides
# the Flask ``app``; this module registers the JSON API the frontend (script.js) calls via
# getWebAppBackendUrl('api/...'). It reads the benchmark result datasets directly (same
# project), reads/writes the ``benchmark`` project variable (zero hardcode), launches the
# Run_Benchmark scenario, and (Lot 3) reads the webapp's user-suggestions cross-project +
# promotes accepted ones into the golden dataset.
#
# All shaping / validation / mapping lives in the PURE, unit-tested benchmark_webapp.views;
# this file is thin dataiku I/O. Every endpoint is best-effort: it returns a clean JSON error,
# never a 500, so the page degrades to an empty/honest state. Reads are bounded; the scenario
# launch is async + single-flight; the cross-project suggestion read is read-only + bounded.
#
# Instance safety (rule #2): no unbounded loads, no blocking scenario wait in a request, no
# write to prod chat tables (only the golden + a LAB promoted-log dataset are written).
#
# NOTE (verify on instance): the exact dataikuapi scenario method names (run_scenario / run,
# get_current_run / get_last_runs) can vary by DSS version - the launch/status endpoints are
# written defensively and degrade gracefully; if launching from the page fails, the admin can
# still Run the scenario from the DSS scenario UI.

import functools
import json
import logging
import traceback

import dataiku
import pandas as pd
from flask import request, jsonify

from benchmark import run_params, schemas
from benchmark_webapp import views

logger = logging.getLogger(__name__)

SCENARIO_ID = "Run_Benchmark"
# Heavy columns never shipped to the per-question table (kept in the dataset for the dashboard).
_SCORED_DROP = ("full_answer", "generated_sql_json", "artifacts_json", "config_json")
# Absolute cap on rows pulled from the (small) result datasets - a backstop, not a paginator.
_MAX_ROWS = 5000
# Read guards mirrored from the webapp storage (read-only + statement_timeout).
_READ_PRE = ["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]


# --- helpers (thin dataiku I/O) ---------------------------------------------

def _variables():
    """Merged custom variables (resolved). Never raises."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def _config():
    """Resolved benchmark config from the project variable."""
    return run_params.resolve(_variables())


def _project():
    """dataikuapi handle on THIS (LAB) project."""
    return dataiku.api_client().get_project(dataiku.default_project_key())


def _read_dataset(name, drop_cols=(), max_rows=_MAX_ROWS):
    """Read a managed dataset -> list of dicts (NaN -> None, heavy cols dropped, row-capped).

    Never raises: a missing/empty dataset yields []. Small result datasets only.
    """
    try:
        df = dataiku.Dataset(name).get_dataframe()
    except Exception:
        logger.warning("benchmark webapp - dataset %s unreadable", name)
        return []
    if df is None or len(df) == 0:
        return []
    cols = [c for c in drop_cols if c in df.columns]
    if cols:
        df = df.drop(columns=cols)
    if max_rows and len(df) > max_rows:
        df = df.head(max_rows)
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict("records")


def _err(code, status=400, extra=None):
    body = {"status": "error", "error": code}
    if extra:
        body.update(extra)
    return jsonify(body), status


def _safe(fn):
    """Wrap a handler so any unexpected exception degrades to a clean JSON 500, never a raw
    Flask HTML 500 - the "never a 500" contract is then guaranteed, not incidental on the
    pure-by-convention views."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.error("%s failed\n%s", fn.__name__, traceback.format_exc())
            return _err("server_error", 500)
    return wrapped


# --- config -----------------------------------------------------------------

@app.route("/api/config", methods=["GET"])
def api_config_get():
    """Resolved config + the raw editable variable + golden categories/ids + available runs."""
    try:
        cfg = _config()
        # Raw editable object from Local variables (so the admin edits exactly what is stored).
        raw = {}
        try:
            allvars = _project().get_variables() or {}
            raw = (allvars.get("local") or {}).get("benchmark") or {}
        except Exception:
            logger.warning("benchmark webapp - could not read raw project variable")
        golden = _read_dataset(cfg["golden_dataset"])
        categories = sorted({str(r.get("category")) for r in golden
                             if r.get("category") not in (None, "")})
        question_ids = [str(r.get("question_id")) for r in golden if r.get("question_id")]
        runs = views.runs_view(_read_dataset(cfg["summary_dataset"]))
        return jsonify({
            "status": "ok",
            "config": views.config_view(cfg),
            "raw": raw,
            "categories": categories,
            "question_count": len(question_ids),
            "runs": runs,
        })
    except Exception:
        logger.error("api_config_get failed\n%s", traceback.format_exc())
        return _err("config_unavailable", 500)


@app.route("/api/config", methods=["POST"])
def api_config_post():
    """Validate + write the ``benchmark`` project variable (Local variables)."""
    body = request.get_json(silent=True) or {}
    raw = body.get("benchmark")
    ok, cfg, errors = views.validate_config(raw)
    if not ok:
        return _err("invalid_config", 400, {"messages": errors})
    try:
        obj = raw if isinstance(raw, dict) else json.loads(raw)
        project = _project()
        allvars = project.get_variables() or {}
        allvars.setdefault("local", {})
        allvars["local"]["benchmark"] = obj
        project.set_variables(allvars)
        return jsonify({"status": "ok", "config": views.config_view(_config())})
    except Exception:
        logger.error("api_config_post failed\n%s", traceback.format_exc())
        return _err("config_write_failed", 500)


# --- run (launch + status), best-effort + single-flight ----------------------

def _scenario():
    return _project().get_scenario(SCENARIO_ID)


def _is_running(scenario):
    """Best-effort: True when a Run_Benchmark run is currently in progress. Never raises."""
    try:
        cur = scenario.get_current_run()
        if cur:
            return True
    except Exception:
        pass
    try:
        last = scenario.get_last_runs(limit=1)
        if last:
            info = last[0].get_info() if hasattr(last[0], "get_info") else {}
            running = info.get("running")
            if running is not None:
                return bool(running)
    except Exception:
        pass
    return False


@app.route("/api/run", methods=["POST"])
def api_run():
    """Launch Run_Benchmark async; refuse when a run is already in progress (single-flight)."""
    try:
        scenario = _scenario()
        if _is_running(scenario):
            return jsonify({"status": "error", "error": "already_running"}), 409
        launched = False
        for method in ("run_scenario", "run"):
            fn = getattr(scenario, method, None)
            if callable(fn):
                fn()
                launched = True
                break
        if not launched:
            return _err("launch_unsupported", 500)
        logger.info("benchmark webapp - launched scenario %s", SCENARIO_ID)
        return jsonify({"status": "ok", "launched": True})
    except Exception:
        logger.error("api_run failed\n%s", traceback.format_exc())
        return _err("launch_failed", 500)


@app.route("/api/run/status", methods=["GET"])
def api_run_status():
    """Best-effort last/current run state (running / done / unknown)."""
    try:
        scenario = _scenario()
        running = _is_running(scenario)
        last = None
        try:
            runs = scenario.get_last_runs(limit=1)
            if runs:
                info = runs[0].get_info() if hasattr(runs[0], "get_info") else {}
                last = info.get("result") or info.get("outcome") or info
        except Exception:
            last = None
        return jsonify({"status": "ok", "running": running, "last": last})
    except Exception:
        logger.error("api_run_status failed\n%s", traceback.format_exc())
        return jsonify({"status": "ok", "running": False, "last": None})


# --- restitution (read the result datasets) ---------------------------------

@app.route("/api/results/runs", methods=["GET"])
@_safe
def api_runs():
    cfg = _config()
    return jsonify({"status": "ok", "runs": views.runs_view(_read_dataset(cfg["summary_dataset"]))})


@app.route("/api/results/summary", methods=["GET"])
@_safe
def api_summary():
    cfg = _config()
    run_id = request.args.get("run_id") or None
    return jsonify({"status": "ok",
                    **views.summary_view(_read_dataset(cfg["summary_dataset"]), run_id)})


@app.route("/api/results/breakdown", methods=["GET"])
@_safe
def api_breakdown():
    cfg = _config()
    run_id = request.args.get("run_id") or None
    return jsonify({"status": "ok",
                    **views.breakdown_view(_read_dataset(cfg["breakdown_dataset"]), run_id)})


@app.route("/api/results/detail", methods=["GET"])
@_safe
def api_detail():
    cfg = _config()
    run_id = request.args.get("run_id") or None
    only_nr = str(request.args.get("needs_review") or "").lower() in ("1", "true", "yes")
    rows = _read_dataset(cfg["scored_dataset"], drop_cols=_SCORED_DROP)
    return jsonify({"status": "ok",
                    **views.detail_view(rows, run_id, only_needs_review=only_nr)})


# --- suggestions (Lot 3): cross-project read + promotion --------------------

def _suggestion_executor(conn):
    from dataiku import SQLExecutor2
    return SQLExecutor2(connection=conn)


def _read_pending_suggestions(cfg):
    """Read pending user suggestions cross-project (read-only). Returns (rows, error_code)."""
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


@app.route("/api/suggestions", methods=["GET"])
@_safe
def api_suggestions():
    cfg = _config()
    rows, err = _read_pending_suggestions(cfg)
    if err == "not_configured":
        return jsonify({"status": "ok", "configured": False, "suggestions": []})
    if err:
        return _err(err, 500)
    return jsonify({"status": "ok", "configured": True,
                    "suggestions": views.suggestions_view(rows)})


def _read_promoted_ids(cfg):
    """Already-promoted suggestion ids (LAB log dataset). [] when absent. Never raises."""
    name = run_params.suggestions_config(cfg).get("promoted_dataset")
    if not name:
        return []
    rows = _read_dataset(name)
    return [str(r.get("suggestion_id")) for r in rows if r.get("suggestion_id")]


@app.route("/api/suggestions/promote", methods=["POST"])
def api_promote():
    """Append accepted suggestions to the golden dataset + record their ids (idempotent)."""
    cfg = _config()
    body = request.get_json(silent=True) or {}
    wanted = body.get("suggestion_ids")
    if not isinstance(wanted, list) or not wanted:
        return _err("no_selection", 400)
    wanted_set = {str(x) for x in wanted}

    pending, err = _read_pending_suggestions(cfg)
    if err:
        return _err(err if err != "not_configured" else "suggestions_not_configured", 400)
    chosen = [s for s in pending if str(s.get("suggestion_id")) in wanted_set]
    promoted_before = _read_promoted_ids(cfg)
    golden_rows, used_ids = views.promotable_golden_rows(chosen, promoted_before)
    if not golden_rows:
        return jsonify({"status": "ok", "promoted": 0, "skipped": len(chosen)})

    try:
        # Append to the golden dataset, de-duping by question_id against what is already there.
        # UNCAPPED read here (max_rows=0): this is a read-modify-WRITE round-trip, so the display
        # backstop must not silently drop golden rows beyond the cap when the dataset is rewritten.
        golden_name = cfg["golden_dataset"]
        existing = _read_dataset(golden_name, max_rows=0)
        existing_qids = {str(r.get("question_id")) for r in existing}
        new_rows = [r for r in golden_rows if r["question_id"] not in existing_qids]
        if new_rows:
            cols = list(schemas.GOLDEN_COLUMNS)
            frame = pd.DataFrame(
                [{c: r.get(c) for c in cols} for r in (existing + new_rows)], columns=cols)
            dataiku.Dataset(golden_name).write_with_schema(frame)
        # Record the promoted ids in the LAB log (so they are never offered again).
        promoted_name = run_params.suggestions_config(cfg).get("promoted_dataset")
        if promoted_name:
            all_ids = sorted(set(promoted_before) | set(used_ids))
            dataiku.Dataset(promoted_name).write_with_schema(
                pd.DataFrame({"suggestion_id": all_ids}))
        return jsonify({"status": "ok", "promoted": len(new_rows),
                        "recorded": len(used_ids)})
    except Exception:
        logger.error("api_promote failed\n%s", traceback.format_exc())
        return _err("promote_failed", 500)
