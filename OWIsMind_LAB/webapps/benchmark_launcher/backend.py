# OWIsMind_LAB benchmark LAUNCHER webapp - Python backend (paste into the Standard webapp Python pane).
#
# Configure + launch the benchmark and review/promote user-suggested questions. This is a SEPARATE
# webapp from the public results one, so the launch surface is simply not exposed to consultation
# users (no admin gating needed). DSS provides the Flask ``app``; the frontend (script.js, a real
# FORM, not a JSON editor) calls these via getWebAppBackendUrl('api/...').
#
# Writes are minimal + safe: the ``benchmark`` project variable (Local variables) and, on
# promotion, APPEND-only writes to LAB Flow datasets (the golden + a promoted-ids log) via the
# Dataset API. There is NO raw SQL write anywhere - the single cross-project SQL read is read-only
# (see benchmark_webapp/dss.read_pending_suggestions). Every endpoint degrades to a clean JSON error.

import datetime
import functools
import logging
import traceback

from flask import request, jsonify

from benchmark_webapp import views, dss

logger = logging.getLogger(__name__)

# Bounded sentinel for reconcile_redo_after_run single-flight gate (max 50 benchmarks).
_RECONCILED = []
_RECONCILED_MAX = 50


def _now_iso():
    """UTC timestamp for the review audit (the Flask backend owns the clock, not the pure libs)."""
    return datetime.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _reviewer():
    """Best-effort identity of the reviewer for the audit field. The launcher is a SEPARATE,
    admin-only webapp (not exposed to consultation users), so this is an audit label, not an
    access control. Reads a DSS-injected header when present, else a neutral fallback."""
    for header in ("X-DKU-AuthIdentifier", "X-Dku-User", "X-Forwarded-User"):
        val = request.headers.get(header)
        if val and val.strip():
            return val.strip()[:120]
    return "launcher"


def _err(code, status=400, extra=None):
    body = {"status": "error", "error": code}
    if extra:
        body.update(extra)
    return jsonify(body), status


def _safe(fn):
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.error("%s failed\n%s", fn.__name__, traceback.format_exc())
            return _err("server_error", 500)
    return wrapped


# --- agents: curated catalog + on-demand discovery (pick a project, list its agents) --------

@app.route("/api/agents", methods=["GET"])
@_safe
def api_agents():
    """The curated agent catalog (the agents the admin has added), stored in the variable."""
    return jsonify({"status": "ok", "agents": dss.agents_catalog()})


@app.route("/api/agents/projects", methods=["GET"])
@_safe
def api_agents_projects():
    """DSS projects visible to this webapp's identity (for the add-agent picker). Read-only."""
    return jsonify({"status": "ok", "projects": dss.list_projects()})


@app.route("/api/agents/project-agents", methods=["GET"])
@_safe
def api_agents_project_agents():
    """The agents (id + friendly name) inside one project. Read-only, bounded."""
    project_key = request.args.get("project_key") or ""
    return jsonify({"status": "ok", "agents": dss.list_project_agents(project_key)})


@app.route("/api/agents/connect", methods=["POST"])
@_safe
def api_agents_connect():
    """Add the selected agents of a project to the catalog (id + editable label + modes flag)."""
    body = request.get_json(silent=True) or {}
    result, errors = dss.connect_agents(body.get("project_key"), body.get("agents"))
    if errors:
        return _err("invalid_agent", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/agents/remove", methods=["POST"])
@_safe
def api_agents_remove():
    """Remove one agent from the catalog by agent_key (benchmarks/results are untouched)."""
    body = request.get_json(silent=True) or {}
    result, errors = dss.remove_agent_from_catalog(body.get("agent_key"))
    if errors:
        return _err("invalid_agent", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


# --- per-agent benchmark list -----------------------------------------------

@app.route("/api/agent/benchmarks", methods=["GET"])
@_safe
def api_agent_benchmarks():
    """All benchmarks for one agent (registry-based view with derived status counts)."""
    agent_key = request.args.get("agent_key") or ""
    cfg = dss.config()
    reg = dss.read_registry()
    golden = dss.read_dataset(cfg["golden_dataset"])
    scored = dss.read_dataset(cfg["scored_dataset"], keep_cols=dss.SCORED_KEEP)
    summary = dss.read_dataset(cfg["summary_dataset"])
    result = views.agent_benchmarks_view(reg, agent_key, golden, scored, summary)
    return jsonify({"status": "ok", **result})


# --- golden questions: manage the golden set (read + create/update/delete) ---

@app.route("/api/golden", methods=["GET"])
@_safe
def api_golden_get():
    """Golden questions filtered by agent_key and scope ('agent' / 'untagged' / 'all').

    Returns ``questions`` (the shaped golden rows) plus ``agents`` (the catalog the tagging form
    dropdown needs) - the same shape the launcher MOCK serves for offline preview.
    """
    cfg = dss.config()
    agent_key = request.args.get("agent_key") or None
    scope = request.args.get("scope") or "all"
    raw = dss.read_dataset(cfg["golden_dataset"])
    result = views.golden_tag_view(raw, agent_key=agent_key, scope=scope)
    return jsonify({"status": "ok", "agents": dss.agents_catalog(), **result})


@app.route("/api/golden/save", methods=["POST"])
@_safe
def api_golden_save():
    """Create (no question_id) or update (with question_id) one golden question.

    Validation lives in views.prepare_golden_save; the read-modify-write of the golden Flow
    dataset is locked + RAISING (a read blip aborts to a 500 rather than truncating the golden).
    Payload may carry agent_key to tag the question to a specific agent.
    """
    cfg = dss.config()
    payload = request.get_json(silent=True) or {}
    try:
        result, errors = dss.save_golden_question(cfg, payload)
    except Exception:
        logger.error("api_golden_save failed\n%s", traceback.format_exc())
        return _err("golden_write_failed", 500)
    if errors:
        return _err("invalid_question", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/golden/delete", methods=["POST"])
@_safe
def api_golden_delete():
    """Hard-delete one golden question by id (past run results are untouched)."""
    cfg = dss.config()
    body = request.get_json(silent=True) or {}
    qid = body.get("question_id")
    if not isinstance(qid, str) or not qid.strip():
        return _err("no_question_id", 400)
    try:
        result, errors = dss.delete_golden_question(cfg, qid)
    except Exception:
        logger.error("api_golden_delete failed\n%s", traceback.format_exc())
        return _err("golden_write_failed", 500)
    if errors:
        return _err("invalid_request", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


# --- benchmark lifecycle: create, delete, modes, redo, rename, launch --------

def _scored_light(cfg):
    """The scored dataset projected to the light columns (for cell verdicts). [] when absent."""
    return dss.read_dataset(cfg["scored_dataset"], keep_cols=dss.SCORED_KEEP)


@app.route("/api/benchmark/create", methods=["POST"])
@_safe
def api_benchmark_create():
    """Create a named benchmark pinned to one agent (from the catalog).

    Body: ``{name, agent_key, modes}``. Membership is AUTO-DERIVED at run time from the golden
    rows tagged to the agent_key - no seeding. Gate: the agent must have at least one active
    tagged golden question (400 no_tagged_questions when none). Modes list defaults to ['default']
    when absent or empty. The agent snapshot (agent_key, agent_label, project_key, agent_id) is
    read from the catalog and baked into the registry entry; the frontend only sends a logical key.
    """
    body = request.get_json(silent=True) or {}
    agent_key = str(body.get("agent_key") or "").strip()
    catalog = dss.agents_catalog()
    agent = next((a for a in catalog if a.get("agent_key") == agent_key), None)
    if not agent:
        return _err("unknown_agent", 400)
    # Gate: the agent must have at least one active tagged golden question.
    # Use the canonical active check from views._agent_tagged_active_ids logic.
    cfg = dss.config()
    golden_raw = dss.read_dataset(cfg["golden_dataset"])
    reg = dss.read_registry()
    scored = _scored_light(cfg)
    bench_view = views.agent_benchmarks_view(reg, agent_key, golden_raw, scored)
    n_tagged = bench_view.get("n_tagged", 0)
    if n_tagged == 0:
        return _err("no_tagged_questions", 400)
    name = body.get("name")
    modes_raw = body.get("modes")
    if isinstance(modes_raw, list):
        modes = [str(m).strip() for m in modes_raw if str(m).strip()]
    else:
        modes = []
    if not modes:
        modes = ["default"]
    result, errors = dss.create_benchmark(name, agent, modes, _reviewer())
    if errors:
        return _err("invalid_benchmark", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/benchmark/delete", methods=["POST"])
@_safe
def api_benchmark_delete():
    """Hard-delete a benchmark from the registry (scored rows are untouched)."""
    body = request.get_json(silent=True) or {}
    bid = body.get("benchmark_id") or ""
    result, errors = dss.delete_benchmark(bid)
    if errors:
        return _err("invalid_request", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/benchmark/detail", methods=["GET"])
@_safe
def api_benchmark_detail():
    """One benchmark's per-mode cell table (membership + tested/pending/redo per question)."""
    bid = request.args.get("benchmark_id") or ""
    cfg = dss.config()
    reg = dss.read_registry()
    entity = reg.get(bid)
    if not entity:
        return _err("unknown_benchmark", 404)
    golden = dss.read_dataset(cfg["golden_dataset"])
    scored = _scored_light(cfg)
    detail = views.benchmark_detail_view(entity, golden, scored)
    return jsonify({"status": "ok", **detail})


@app.route("/api/benchmark/modes", methods=["POST"])
@_safe
def api_benchmark_modes():
    """Update the modes list on a benchmark."""
    body = request.get_json(silent=True) or {}
    bid = body.get("benchmark_id") or ""
    modes = body.get("modes")
    if not isinstance(modes, list):
        return _err("modes_required", 400)
    result, errors = dss.set_benchmark_modes(bid, modes)
    if errors:
        return _err("invalid_request", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/benchmark/redo", methods=["POST"])
@_safe
def api_benchmark_redo():
    """Set / clear the 'redo at next run' flag on one member question.

    The flag value is the ``value`` field (the frontend + MOCK contract); ``include_next`` is
    accepted as a legacy alias. Reading the wrong field silently forced every toggle to False,
    so the redo intent was never stored and append runs found "nothing to run".
    """
    body = request.get_json(silent=True) or {}
    flag = body.get("value")
    if flag is None:
        flag = body.get("include_next")
    result, errors = dss.set_question_redo(
        body.get("benchmark_id") or "", body.get("question_id") or "", bool(flag))
    if errors:
        return _err("invalid_request", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


@app.route("/api/benchmark/rename", methods=["POST"])
@_safe
def api_benchmark_rename():
    """Rename a benchmark (name must stay unique per agent)."""
    body = request.get_json(silent=True) or {}
    result, errors = dss.rename_benchmark(
        body.get("benchmark_id") or "", body.get("name") or "")
    if errors:
        return _err("invalid_request", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


# Map a launch error code to an HTTP status (409 for the single-flight conflict, else 400/500).
_LAUNCH_STATUS = {"already_running": 409, "unknown_benchmark": 404, "bad_request": 400,
                  "launch_unsupported": 500}


@app.route("/api/benchmark/launch", methods=["POST"])
@_safe
def api_benchmark_launch():
    """Launch a benchmark: write the run_request (benchmark_id + launch_mode), fire.

    Body: ``{benchmark_id, launch_mode}`` where launch_mode is 'append' (pending + redo,
    default) or 'full' (re-run every member question). Redo flags are cleared AFTER the run
    by reconcile_redo_after_run (called on the status poll), not here, so a rejected launch
    never silently drops the redo intent.
    """
    body = request.get_json(silent=True) or {}
    result, err = dss.launch_benchmark(
        body.get("benchmark_id") or "", body.get("launch_mode") or "append")
    if err:
        return _err(err, _LAUNCH_STATUS.get(err, 400))
    return jsonify({"status": "ok", **result})


# --- run: status poll + reset ------------------------------------------------

@app.route("/api/run/status", methods=["GET"])
@_safe
def api_run_status():
    """Scenario run status. Calls reconcile_redo_after_run on completion (best-effort).

    Returns {running, benchmark_id, scored, total, run_request, last} as provided by
    dss.last_status. On completion, reconcile_redo_after_run is called once per
    (benchmark_id, requested_at) pair (keyed sentinel so idle polls are cheap). The reconcile
    reads the scored dataset to clear redo flags for questions that ran in the latest run.
    """
    scen = dss.scenario()
    st = dss.last_status(scen)
    if not st.get("running"):
        # Best-effort: reconcile redo flags for the benchmark that just finished.
        try:
            bid = st.get("benchmark_id") or ""
            rr = st.get("run_request")
            requested_at = str((rr or {}).get("requested_at") or "").strip() \
                if isinstance(rr, dict) else ""
            # Key on (bid, requested_at); fall back to total_cells if requested_at absent.
            sentinel = (bid, requested_at or str(st.get("total") or 0))
            if bid and sentinel not in _RECONCILED:
                dss.reconcile_redo_after_run(bid)
                _RECONCILED.append(sentinel)
                if len(_RECONCILED) > _RECONCILED_MAX:
                    del _RECONCILED[0]
        except Exception:
            logger.warning("api_run_status - reconcile best-effort failed\n%s",
                           traceback.format_exc())
    return jsonify({"status": "ok", **st})


@app.route("/api/run/reset", methods=["POST"])
@_safe
def api_run_reset():
    """Clear the run_request from the variable (only when the scenario is idle)."""
    result, errors = dss.reset_run_request()
    if errors:
        return _err(errors[0] if errors else "reset_failed", 400)
    return jsonify({"status": "ok", **result})


# --- settings (global benchmark keys in the variable) -----------------------

@app.route("/api/settings", methods=["GET"])
@_safe
def api_settings_get():
    """The current benchmark settings (dataset names, judge llm, concurrency, language)."""
    return jsonify({"status": "ok", "settings": dss.read_settings()})


@app.route("/api/settings", methods=["POST"])
@_safe
def api_settings_post():
    """Save the benchmark settings (validates golden dataset + writes to the variable)."""
    form = request.get_json(silent=True) or {}
    result, errors = dss.save_settings(form)
    if errors:
        return _err("invalid_settings", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


# --- review + override: human-in-the-loop correction of the judge verdict ----

@app.route("/api/review", methods=["GET"])
@_safe
def api_review():
    """Every attempt of ONE benchmark for human review (judge verdict + comment + per-attempt override).

    v2: a reviewer overrides a SPECIFIC attempt, so this lists ALL attempts of the benchmark (not the
    latest only) via views.review_view. ``benchmark_id`` selects the benchmark (latest by default);
    ``only_needs_review=1`` keeps the priority pile."""
    cfg = dss.config()
    benchmark_id = request.args.get("benchmark_id") or None
    only_nr = request.args.get("only_needs_review") in ("1", "true", "yes")
    scored = dss.read_dataset(cfg["scored_dataset"], keep_cols=dss.SCORED_KEEP)
    review = views.review_view(scored, benchmark_id=benchmark_id, only_needs_review=only_nr, limit=2000)
    return jsonify({
        "status": "ok",
        "benchmarks": views.benchmark_options(scored),
        **review,
    })


@app.route("/api/review/attempt", methods=["GET"])
@_safe
def api_review_attempt():
    """FULL detail of ONE attempt for the reviewer, loaded on demand: the complete agent answer + the
    SQL the agent actually generated + each query's captured result table. The review list stays LIGHT;
    this fetches just the opened row WITH its heavy columns so the reviewer can decide the override with
    full context. Read-only, best-effort (no matching row -> ``found: false``)."""
    cfg = dss.config()
    row = dss.read_scored_row_full(
        cfg["scored_dataset"],
        request.args.get("run_id"),
        request.args.get("question_id"),
        request.args.get("agent_key"),
        request.args.get("mode"),
    )
    return jsonify({"status": "ok", **views.full_detail_view(row)})


@app.route("/api/override", methods=["POST"])
@_safe
def api_override():
    """Apply (or clear) a reviewer override of the judge verdict on one scored row.

    The reviewer marks a row correct/incorrect (or sends a blank verdict to clear). The write is a
    locked read-modify-write of the scored dataset (dss.write_override); the override survives every
    future run (scored accumulates by run_id)."""
    cfg = dss.config()
    payload = request.get_json(silent=True) or {}
    payload = dict(payload)
    payload["reviewed_by"] = _reviewer()
    try:
        result, errors = dss.write_override(cfg, payload, _now_iso())
    except Exception:
        logger.error("api_override failed\n%s", traceback.format_exc())
        return _err("override_failed", 500)
    if errors:
        return _err("invalid_override", 400, {"messages": errors})
    return jsonify({"status": "ok", **result})


# --- suggestions: review (read-only cross-project) + promote (Flow append) ---

@app.route("/api/suggestions", methods=["GET"])
@_safe
def api_suggestions():
    cfg = dss.config()
    rows, err = dss.read_pending_suggestions(cfg)
    if err == "not_configured":
        return jsonify({"status": "ok", "configured": False, "suggestions": []})
    if err:
        return _err(err, 500)
    # Drop already-promoted suggestions by checking the GOLDEN (the source of truth) for their
    # minted question_id - fail-open (a golden read blip shows MORE pending, never hides a genuinely
    # new one and never corrupts). The separate promoted-ids dataset is only a best-effort audit log.
    golden_qids = dss.read_golden_question_ids(cfg)
    excluded = [s.get("suggestion_id") for s in rows
                if views.minted_question_id(s.get("suggestion_id")) in golden_qids]
    return jsonify({"status": "ok", "configured": True,
                    "suggestions": views.suggestions_view(rows, exclude_ids=excluded)})


@app.route("/api/suggestions/promote", methods=["POST"])
@_safe
def api_promote():
    cfg = dss.config()
    body = request.get_json(silent=True) or {}
    wanted = body.get("suggestion_ids")
    if not isinstance(wanted, list) or not wanted:
        return _err("no_selection", 400)
    wanted_set = {str(x) for x in wanted}

    pending, err = dss.read_pending_suggestions(cfg)
    if err:
        return _err("suggestions_not_configured" if err == "not_configured" else err, 400)
    chosen = [s for s in pending if str(s.get("suggestion_id")) in wanted_set]
    # Already-promoted = present in the golden (source of truth), not the audit log. The append
    # also de-dups by question_id under the promote lock, so this is belt-and-suspenders.
    golden_qids = dss.read_golden_question_ids(cfg)
    already = [s.get("suggestion_id") for s in chosen
               if views.minted_question_id(s.get("suggestion_id")) in golden_qids]
    golden_rows, used_ids = views.promotable_golden_rows(chosen, already)
    if not golden_rows:
        return jsonify({"status": "ok", "promoted": 0, "skipped": len(chosen)})
    try:
        result = dss.append_golden_and_record(cfg, golden_rows, used_ids)
    except Exception:
        logger.error("api_promote failed\n%s", traceback.format_exc())
        return _err("promote_failed", 500)
    return jsonify({"status": "ok", **result})
