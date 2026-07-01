# OWIsMind_LAB benchmark RESULTS webapp - Python backend (paste into the Standard webapp Python pane).
#
# PUBLIC consultation surface: it ONLY READS the result datasets and shapes them through the pure,
# tested benchmark_webapp.views. There is NO write route here at all (no config, no launch, no
# suggestions, no promote) - those live in the SEPARATE launcher webapp, which is not exposed to
# consultation users. DSS provides the Flask ``app``; the frontend (script.js) calls these via
# getWebAppBackendUrl('api/...'). Every endpoint is wrapped so it degrades to a clean JSON error,
# never a raw 500. Reads are bounded (heavy columns dropped on the scored detail, row cap).

import functools
import logging
import traceback

from flask import request, jsonify

from benchmark_webapp import views, dss

logger = logging.getLogger(__name__)


def _err(code, status=400, extra=None):
    body = {"status": "error", "error": code}
    if extra:
        body.update(extra)
    return jsonify(body), status


def _safe(fn):
    """Degrade any unexpected exception to a clean JSON 500 (never a raw Flask HTML 500)."""
    @functools.wraps(fn)
    def wrapped(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception:
            logger.error("%s failed\n%s", fn.__name__, traceback.format_exc())
            return _err("server_error", 500)
    return wrapped


# v2: the selector lists BENCHMARKS (not runs); summary / breakdown / detail scope by benchmark_id.
@app.route("/api/results/benchmarks", methods=["GET"])
@_safe
def api_benchmarks():
    cfg = dss.config()
    return jsonify({"status": "ok",
                    "benchmarks": views.benchmark_options(dss.read_dataset(cfg["summary_dataset"]))})


@app.route("/api/results/summary", methods=["GET"])
@_safe
def api_summary():
    cfg = dss.config()
    benchmark_id = request.args.get("benchmark_id") or None
    return jsonify({"status": "ok",
                    **views.summary_view(dss.read_dataset(cfg["summary_dataset"]), benchmark_id)})


@app.route("/api/results/breakdown", methods=["GET"])
@_safe
def api_breakdown():
    cfg = dss.config()
    benchmark_id = request.args.get("benchmark_id") or None
    return jsonify({"status": "ok",
                    **views.breakdown_view(dss.read_dataset(cfg["breakdown_dataset"]), benchmark_id)})


@app.route("/api/results/detail", methods=["GET"])
@_safe
def api_detail():
    cfg = dss.config()
    benchmark_id = request.args.get("benchmark_id") or None
    only_nr = str(request.args.get("needs_review") or "").lower() in ("1", "true", "yes")
    # Project to the LIGHT columns at read time so the heavy full_answer / SQL / artifacts blobs are
    # never materialized into RAM (the cap then bounds the LOAD, not just the post-load frame).
    rows = dss.read_dataset(cfg["scored_dataset"], keep_cols=dss.SCORED_KEEP, drop_cols=dss.SCORED_DROP)
    return jsonify({"status": "ok",
                    **views.detail_view(rows, benchmark_id, only_needs_review=only_nr)})


@app.route("/api/results/attempt", methods=["GET"])
@_safe
def api_attempt():
    """FULL detail of ONE attempt, loaded on demand: the complete agent answer + the SQL the agent
    actually generated + each query's captured result table. The per-question read above stays LIGHT;
    this fetches just the one opened row WITH its heavy columns (dss.read_scored_row_full streams one
    row, no blob is loaded en masse). Read-only, best-effort (no matching row -> ``found: false``)."""
    cfg = dss.config()
    row = dss.read_scored_row_full(
        cfg["scored_dataset"],
        request.args.get("run_id"),
        request.args.get("question_id"),
        request.args.get("agent_key"),
        request.args.get("mode"),
    )
    return jsonify({"status": "ok", **views.full_detail_view(row)})
