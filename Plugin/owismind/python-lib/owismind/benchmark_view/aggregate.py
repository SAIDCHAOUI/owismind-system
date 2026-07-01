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


# --- v2: benchmark selection + latest-attempt reduction + evolution ----------

def _attempt(r):
    n = _num(r.get("attempt_no"))
    return int(n) if n is not None else 0


def latest_attempts(rows):
    """Keep the latest attempt of each (benchmark_id, question_id, agent_key, mode). Pure, never raises.

    Mirrors the LAB scoring.latest_attempts: a question re-run several times counts only by its most
    recent attempt, so the consultation's accuracy reflects the agent's current state.
    """
    best = {}
    for r in _rows(rows):
        key = (_str(r.get("benchmark_id")), _str(r.get("question_id")),
               _str(r.get("agent_key")), _str(r.get("mode")))
        rank = (_attempt(r), _str(r.get("run_timestamp")), _str(r.get("run_id")))
        if key not in best or rank > best[key][0]:
            best[key] = (rank, r)
    return [v[1] for v in best.values()]


def benchmarks_list(rows):
    """Distinct (benchmark_id, benchmark_name) for the consultation selector, newest first. Pure.

    Carries the last run timestamp and the question count so the picker can show recency + size.
    Rows without a benchmark_id collapse into a single '' bucket (a legacy table not yet v2-run).
    """
    acc = {}
    for r in _rows(rows):
        bid = _str(r.get("benchmark_id"))
        entry = acc.setdefault(bid, {"benchmark_id": bid, "benchmark_name": "",
                                     "last_run_timestamp": "", "questions": set()})
        name = _str(r.get("benchmark_name"))
        if name and not entry["benchmark_name"]:
            entry["benchmark_name"] = name
        ts = _str(r.get("run_timestamp"))
        if ts > entry["last_run_timestamp"]:
            entry["last_run_timestamp"] = ts
        qid = _str(r.get("question_id"))
        if qid:
            entry["questions"].add(qid)
    out = [{"benchmark_id": e["benchmark_id"],
            "benchmark_name": e["benchmark_name"] or e["benchmark_id"] or "(default)",
            "last_run_timestamp": e["last_run_timestamp"],
            "n_questions": len(e["questions"])} for e in acc.values()]
    out.sort(key=lambda b: (b["last_run_timestamp"], b["benchmark_id"]), reverse=True)
    return out


def _attempt_brief(r):
    eff = schemas.effective_correct(r)
    return {
        "attempt_no": _int(r.get("attempt_no")),
        "run_timestamp": _str(r.get("run_timestamp")),
        "judge_score": _int(r.get("judge_score")),
        "verdict": eff["verdict"],
        "correct": eff["correct"],
        "overridden": eff["overridden"],
    }


def _evolution_map(rows):
    """Map ``(question_id, mode) -> {attempts: [brief...], n, delta}`` for the per-question history."""
    by_key = {}
    for r in _rows(rows):
        key = (_str(r.get("question_id")), _str(r.get("mode")))
        by_key.setdefault(key, []).append(_attempt_brief(r))
    out = {}
    for key, briefs in by_key.items():
        briefs.sort(key=lambda a: (a["attempt_no"], a["run_timestamp"]))
        delta = "first"
        if len(briefs) >= 2:
            prev, cur = briefs[-2]["correct"], briefs[-1]["correct"]
            delta = "same" if prev == cur else ("improved" if cur and not prev else "regressed")
        out[key] = {"attempts": briefs, "n": len(briefs), "delta": delta}
    return out


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
        # v2: the run identity of THIS attempt (the override key) + the benchmark dimension + the
        # reference SQL/tool vs the tools the agent actually used (the training-data comparison).
        "run_id": _str(r.get("run_id")),
        "run_timestamp": _str(r.get("run_timestamp")),
        "benchmark_id": _str(r.get("benchmark_id")),
        "attempt_no": _int(r.get("attempt_no")),
        "expected_sql": _str(r.get("expected_sql")),
        "expected_tool": _str(r.get("expected_tool")),
        "actual_tools": _str(r.get("actual_tools")),
    }


# --- the consultation view-model --------------------------------------------

def results_view(scored_rows, benchmark_id=None, detail_limit=500):
    """Build the consultation view-model for ONE benchmark (v2). Pure, never raises.

    ``{benchmark_id, benchmark_name, benchmarks, kpis, configs, categories, detail}``. A benchmark is
    selected (the most recent by default); its rows are reduced to the LATEST attempt of each question
    (so accuracy reflects the current state), and each detail row carries its per-(question, mode)
    ``evolution`` (the attempt history). KPIs / breakdowns use the EFFECTIVE verdict (a human override
    wins). Errored rows are excluded from accuracy but counted as errors.
    """
    all_rows = _rows(scored_rows)
    benchmarks = benchmarks_list(all_rows)
    bid = _str(benchmark_id)
    if not bid:
        bid = benchmarks[0]["benchmark_id"] if benchmarks else ""
    bench_rows = [r for r in all_rows if _str(r.get("benchmark_id")) == bid]
    bench_name = next((_str(r.get("benchmark_name")) for r in bench_rows
                       if _str(r.get("benchmark_name"))), "")

    # The CURRENT state = the latest attempt of each question x mode; the full history feeds evolution.
    latest = latest_attempts(bench_rows)
    evolution = _evolution_map(bench_rows)

    ok_rows = [r for r in latest if _str(r.get("status")) == _OK]
    n_correct = sum(1 for r in ok_rows if schemas.effective_correct(r)["correct"])
    n_scored = len(ok_rows)
    accuracy = (float(n_correct) / n_scored) if n_scored else 0.0
    total_cost = sum(_num(r.get("estimated_cost")) or 0.0 for r in ok_rows)
    needs_review = sum(1 for r in latest if _truthy(r.get("needs_review")))
    question_ids = {_str(r.get("question_id")) for r in latest if _str(r.get("question_id"))}

    kpis = {
        "accuracy": accuracy,
        "accuracy_pct": fmt_pct(accuracy),
        "n_correct": n_correct,
        "n_scored": n_scored,
        "band": confidence_band(accuracy),
        "n_questions": len(question_ids),
        "n_configs": len({(_str(r.get("agent_key")), _str(r.get("mode"))) for r in latest}),
        "total_cost": total_cost,
        "total_cost_str": fmt_money2(total_cost),
        "needs_review": needs_review,
    }

    return {
        "benchmark_id": bid,
        "benchmark_name": bench_name or bid,
        "benchmarks": benchmarks,
        "kpis": kpis,
        "configs": _configs_view(latest),
        "categories": _categories_view(ok_rows),
        "detail": _detail_view(latest, detail_limit, evolution),
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


def _detail_view(rows, limit, evolution=None):
    try:
        cap = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        cap = 500
    evolution = evolution or {}
    out = []
    for r in rows:
        row = _detail_row(r)
        ev = evolution.get((_str(r.get("question_id")), _str(r.get("mode"))))
        # Attach the per-(question, mode) attempt history so the table can show the evolution inline.
        row["n_attempts"] = ev["n"] if ev else 1
        row["delta"] = ev["delta"] if ev else "first"
        row["attempts"] = ev["attempts"] if ev else []
        out.append(row)
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
