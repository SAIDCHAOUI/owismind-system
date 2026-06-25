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

import functools
import logging
import traceback

from flask import request, jsonify

from benchmark import config as bench_config
from benchmark_webapp import views, dss

logger = logging.getLogger(__name__)


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


# --- config: read (form prefill) + write (from the form, never raw JSON) -----

@app.route("/api/config", methods=["GET"])
@_safe
def api_config_get():
    """The current config as form fields + the live golden categories (filter picker) + runs."""
    cfg = dss.config()
    golden = dss.read_dataset(cfg["golden_dataset"])
    categories = sorted({str(r.get("category")) for r in golden
                         if r.get("category") not in (None, "")})
    return jsonify({
        "status": "ok",
        "config": views.config_view(cfg),
        "categories": categories,
        "question_count": len([r for r in golden if r.get("question_id")]),
        "mode_options": list(bench_config.MODES),
        "runs": views.runs_view(dss.read_dataset(cfg["summary_dataset"])),
    })


@app.route("/api/config", methods=["POST"])
@_safe
def api_config_post():
    """Save the config from the FORM fields. The form manages agents/modes/filter/concurrency/
    language; every other key (datasets, judge, suggestions block) is preserved server-side."""
    form = request.get_json(silent=True) or {}
    merged = views.build_config_object(dss.read_raw_benchmark_var(), form)
    ok, cfg, errors = views.validate_config(merged)
    if not ok:
        return _err("invalid_config", 400, {"messages": errors})
    try:
        dss.write_benchmark_var(merged)
    except Exception:
        logger.error("api_config_post write failed\n%s", traceback.format_exc())
        return _err("config_write_failed", 500)
    return jsonify({"status": "ok", "config": views.config_view(dss.config())})


# --- run (launch async + single-flight, status poll) -------------------------

@app.route("/api/run", methods=["POST"])
@_safe
def api_run():
    # Single-flight (in-process): a non-blocking lock around the is_running -> launch pair closes
    # the TOCTOU window where two near-simultaneous requests both observe no run and both fire the
    # whole agent x mode matrix (double Mesh load + racing dataset writes). The AUTHORITATIVE
    # cross-process guard is "Prevent concurrent executions" on the Run_Benchmark scenario in DSS.
    if not dss.RUN_LOCK.acquire(blocking=False):
        return jsonify({"status": "error", "error": "already_running"}), 409
    try:
        scen = dss.scenario()
        if dss.is_running(scen):
            return jsonify({"status": "error", "error": "already_running"}), 409
        if not dss.launch(scen):
            return _err("launch_unsupported", 500)
        logger.info("benchmark launcher - launched scenario %s", dss.SCENARIO_ID)
        return jsonify({"status": "ok", "launched": True})
    finally:
        dss.RUN_LOCK.release()


@app.route("/api/run/status", methods=["GET"])
@_safe
def api_run_status():
    return jsonify({"status": "ok", **dss.last_status(dss.scenario())})


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
