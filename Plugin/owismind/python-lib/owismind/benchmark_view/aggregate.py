"""Shape a scored benchmark table into the plugin consultation view-model (PURE, stdlib only).

Given the scored rows of ONE agent (read cross-project by lab_io), this builds everything the
Benchmark tab renders: the headline verdict (X of Y, confidence band), per agent x mode configs,
per-category accuracy, and the per-question detail table - all on the EFFECTIVE verdict (a human
override wins). It also carries the pure override request validation + apply (used by the admin
review write-back). Robust to None / missing / malformed rows; never raises (degrade, not 500).

Bespoke (not a copy of the LAB scoring.py): the consultation needs only the headline + per-config
+ per-category + detail, so this is a small purpose-built aggregator over effective_correct.
"""

from owismind.benchmark_view import schemas

_ANSWER_PREVIEW_CHARS = 280
_OK = "ok"
_OVERRIDE_KEYS = ("run_id", "question_id", "agent_key", "mode")


# --- scalar coercion / formatting -------------------------------------------

def _num(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        f = float(value)
    elif isinstance(value, str):
        s = value.strip()
        if not s:
            return None
        try:
            f = float(s)
        except (TypeError, ValueError):
            return None
    else:
        return None
    if f != f or f in (float("inf"), float("-inf")):
        return None
    return f


def _int(value):
    f = _num(value)
    return int(f) if f is not None else 0


def _str(value):
    if value is None:
        return ""
    return value if isinstance(value, str) else str(value)


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "oui", "t")
    return False


def _rows(rows):
    return [r for r in (rows or []) if isinstance(r, dict)]


def fmt_pct(frac):
    f = _num(frac)
    return "-" if f is None else "{0:.1f} %".format(f * 100.0)


def fmt_money(value):
    f = _num(value)
    return "-" if f is None else "${0:.4f}".format(f)


def fmt_money2(value):
    f = _num(value)
    return "-" if f is None else "${0:.2f}".format(f)


def fmt_secs(value):
    f = _num(value)
    return "-" if f is None else "{0:.1f} s".format(f)


def confidence_band(accuracy):
    """A plain confidence band for an accuracy fraction: 'high' / 'medium' / 'low'."""
    a = _num(accuracy) or 0.0
    if a >= 0.85:
        return "high"
    if a >= 0.60:
        return "medium"
    return "low"


# --- run selection ----------------------------------------------------------

def latest_run_id(rows):
    best_key = None
    best_id = ""
    for r in _rows(rows):
        rid = _str(r.get("run_id"))
        if not rid:
            continue
        key = (_str(r.get("run_timestamp")), rid)
        if best_key is None or key > best_key:
            best_key = key
            best_id = rid
    return best_id


def runs_view(rows):
    seen = {}
    for r in _rows(rows):
        rid = _str(r.get("run_id"))
        if not rid or rid in seen:
            continue
        seen[rid] = _str(r.get("run_timestamp"))
    items = [{"run_id": rid, "run_timestamp": ts} for rid, ts in seen.items()]
    items.sort(key=lambda it: (it["run_timestamp"], it["run_id"]), reverse=True)
    return items


# --- detail (per-question) --------------------------------------------------

def _detail_row(r):
    answer = _str(r.get("answer_text"))
    eff = schemas.effective_correct(r)
    return {
        "question_id": _str(r.get("question_id")),
        "question": _str(r.get("question")),
        "category": _str(r.get("category")),
        "agent_key": _str(r.get("agent_key")),
        "agent_label": _str(r.get("agent_label")) or _str(r.get("agent_key")),
        "mode": _str(r.get("mode")),
        "status": _str(r.get("status")),
        "objective_match": _str(r.get("objective_match")),
        "judge_score": _int(r.get("judge_score")),
        "judge_verdict": _str(r.get("judge_verdict")),
        "judge_comment": _str(r.get("judge_comment")),
        "correct": _truthy(r.get("correct")),
        "needs_review": _truthy(r.get("needs_review")),
        "reference_answer": _str(r.get("reference_answer")),
        "answer_preview": answer[:_ANSWER_PREVIEW_CHARS],
        "notes": _str(r.get("notes")),
        "expected_value": _str(r.get("expected_value")),
        "expected_value_type": _str(r.get("expected_value_type")),
        "human_verdict": _str(r.get("human_verdict")),
        "human_comment": _str(r.get("human_comment")),
        "reviewed_by": _str(r.get("reviewed_by")),
        "reviewed_at": _str(r.get("reviewed_at")),
        "effective_correct": eff["correct"],
        "effective_verdict": eff["verdict"],
        "overridden": eff["overridden"],
        "latency_str": fmt_secs(r.get("latency_total_s")),
        "estimated_cost": _num(r.get("estimated_cost")) or 0.0,
    }


# --- the consultation view-model --------------------------------------------

def results_view(scored_rows, run_id=None, detail_limit=500):
    """Build the full consultation view-model for ONE run. Pure, never raises.

    ``{run_id, runs, kpis, configs, categories, detail}``. KPIs and breakdowns use the EFFECTIVE
    verdict (a human override wins). Errored rows (status != ok) are excluded from accuracy but
    counted as errors. ``run_id`` selects the run (latest by default).
    """
    all_rows = _rows(scored_rows)
    rid = _str(run_id) or latest_run_id(all_rows)
    rows = [r for r in all_rows if _str(r.get("run_id")) == rid] if rid else []

    ok_rows = [r for r in rows if _str(r.get("status")) == _OK]
    n_correct = sum(1 for r in ok_rows if schemas.effective_correct(r)["correct"])
    n_scored = len(ok_rows)
    accuracy = (float(n_correct) / n_scored) if n_scored else 0.0
    total_cost = sum(_num(r.get("estimated_cost")) or 0.0 for r in ok_rows)
    needs_review = sum(1 for r in rows if _truthy(r.get("needs_review")))
    question_ids = {_str(r.get("question_id")) for r in rows if _str(r.get("question_id"))}

    kpis = {
        "accuracy": accuracy,
        "accuracy_pct": fmt_pct(accuracy),
        "n_correct": n_correct,
        "n_scored": n_scored,
        "band": confidence_band(accuracy),
        "n_questions": len(question_ids),
        "n_configs": len({(_str(r.get("agent_key")), _str(r.get("mode"))) for r in rows}),
        "total_cost": total_cost,
        "total_cost_str": fmt_money2(total_cost),
        "needs_review": needs_review,
    }

    return {
        "run_id": rid,
        "runs": runs_view(all_rows),
        "kpis": kpis,
        "configs": _configs_view(rows),
        "categories": _categories_view(ok_rows),
        "detail": _detail_view(rows, detail_limit),
    }


def _configs_view(rows):
    groups = {}
    for r in rows:
        key = (_str(r.get("agent_key")), _str(r.get("mode")))
        groups.setdefault(key, []).append(r)
    out = []
    for (agent_key, mode), grp in groups.items():
        ok_rows = [r for r in grp if _str(r.get("status")) == _OK]
        n_ok = len(ok_rows)
        n_correct = sum(1 for r in ok_rows if schemas.effective_correct(r)["correct"])
        acc = (float(n_correct) / n_ok) if n_ok else 0.0
        scores = [_num(r.get("judge_score")) for r in ok_rows]
        scores = [s for s in scores if s is not None]
        latencies = [_num(r.get("latency_total_s")) for r in ok_rows]
        latencies = [s for s in latencies if s is not None]
        costs = [_num(r.get("estimated_cost")) for r in ok_rows]
        costs = [s for s in costs if s is not None]
        out.append({
            "agent_key": agent_key,
            "agent_label": next((_str(r.get("agent_label")) for r in grp
                                 if _str(r.get("agent_label"))), agent_key),
            "mode": mode,
            "n_questions": len(grp),
            "n_ok": n_ok,
            "n_error": len(grp) - n_ok,
            "accuracy": acc,
            "accuracy_pct": fmt_pct(acc),
            "mean_score": (sum(scores) / len(scores)) if scores else 0.0,
            "avg_latency_str": fmt_secs((sum(latencies) / len(latencies)) if latencies else None),
            "avg_cost_str": fmt_money((sum(costs) / len(costs)) if costs else None),
            "needs_review": sum(1 for r in grp if _truthy(r.get("needs_review"))),
        })
    out.sort(key=lambda c: (-c["accuracy"], c["agent_label"], c["mode"]))
    return out


def _categories_view(ok_rows):
    groups = {}
    for r in ok_rows:
        bucket = _str(r.get("category"))
        if not bucket:
            continue
        groups.setdefault(bucket, []).append(r)
    out = []
    for bucket, grp in groups.items():
        n_correct = sum(1 for r in grp if schemas.effective_correct(r)["correct"])
        acc = (float(n_correct) / len(grp)) if grp else 0.0
        out.append({
            "bucket": bucket,
            "n": len(grp),
            "accuracy": acc,
            "accuracy_pct": fmt_pct(acc),
        })
    out.sort(key=lambda c: (-c["accuracy"], c["bucket"]))
    return out


def _detail_view(rows, limit):
    try:
        cap = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        cap = 500
    out = [_detail_row(r) for r in rows]
    # needs-review first, then effective-incorrect, then by question id; sort BEFORE the cap.
    out.sort(key=lambda s: (not s["needs_review"], s["effective_correct"], s["question_id"]))
    return out[:cap]


# --- human override request (pure validate + apply) -------------------------

def validate_override(payload):
    """Validate a reviewer's override request. Returns ``(ok, errors)``. Pure, never raises."""
    errors = []
    if not isinstance(payload, dict):
        return False, ["override payload must be an object"]
    for field in ("run_id", "question_id", "agent_key"):
        if not _str(payload.get(field)).strip():
            errors.append("missing required field: {0}".format(field))
    verdict = _str(payload.get("verdict")).strip().lower()
    if verdict not in ("correct", "incorrect", ""):
        errors.append("verdict must be 'correct', 'incorrect' or '' (to clear)")
    return (len(errors) == 0), errors
