"""Pure view-model shaping + config validation for the benchmark webapp (PURE).

Stdlib only (plus benchmark.run_params for config validation). Turns the result datasets
(benchmark_summary / benchmark_breakdown / benchmark_runs_scored) into compact, display-ready
view-models the standard webapp renders, and validates an edited ``benchmark`` variable before
it is written back. Every function is robust to None / missing / malformed rows and never
raises - the webapp must degrade to an empty view, not a 500.

Design contract: docs/superpowers/specs/2026-06-25-benchmark-integration-design.md (section 4.1).
"""

import json

from benchmark import run_params


# --- scalar coercion / formatting -------------------------------------------

def _num(value):
    """Coerce to float, or None when not a finite number. Never raises."""
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
    if isinstance(value, str):
        return value
    return str(value)


def _truthy(value):
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "oui", "t")
    return False


def fmt_pct(frac):
    """A [0,1] fraction as a percentage string, e.g. 0.825 -> '82.5 %'. None -> '-'."""
    f = _num(frac)
    if f is None:
        return "-"
    return "{0:.1f} %".format(f * 100.0)


def fmt_money(value):
    """A dollar amount, e.g. 1.2345 -> '$1.2345'. Small per-question costs keep precision."""
    f = _num(value)
    if f is None:
        return "-"
    return "${0:.4f}".format(f)


def fmt_money2(value):
    """A dollar total with 2 decimals, e.g. 12.5 -> '$12.50'."""
    f = _num(value)
    if f is None:
        return "-"
    return "${0:.2f}".format(f)


def fmt_secs(value):
    """Seconds with one decimal, e.g. 1.43 -> '1.4 s'. None -> '-'."""
    f = _num(value)
    if f is None:
        return "-"
    return "{0:.1f} s".format(f)


# --- run selector -----------------------------------------------------------

def _rows(rows):
    return [r for r in (rows or []) if isinstance(r, dict)]


def latest_run_id(rows):
    """The newest run_id across rows (by run_timestamp then run_id, lexical). '' when none."""
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
    """Distinct (run_id, run_timestamp) for the run selector, newest first."""
    seen = {}
    for r in _rows(rows):
        rid = _str(r.get("run_id"))
        if not rid or rid in seen:
            continue
        seen[rid] = _str(r.get("run_timestamp"))
    items = [{"run_id": rid, "run_timestamp": ts} for rid, ts in seen.items()]
    items.sort(key=lambda it: (it["run_timestamp"], it["run_id"]), reverse=True)
    return items


# --- restitution: summary (KPIs + agent x mode table) -----------------------

def summary_view(summary_rows, run_id=None):
    """Shape benchmark_summary rows for ONE run into KPI tiles + an agent x mode table.

    KPIs: global accuracy (correct over scored across the run), question count, configurations
    (agent x mode) tested, total cost, total needs-review. The per-row table carries the raw
    numbers (for bar widths) and the formatted strings (for labels). Pure, never raises.
    """
    rows = _rows(summary_rows)
    rid = _str(run_id) or latest_run_id(rows)
    if rid:
        rows = [r for r in rows if _str(r.get("run_id")) == rid]

    shaped = []
    total_correct = 0.0
    total_ok = 0
    total_cost = 0.0
    n_questions = 0
    needs_review = 0
    judge_cost = 0.0
    for r in rows:
        n_ok = _int(r.get("n_ok"))
        acc = _num(r.get("accuracy")) or 0.0
        total_correct += acc * n_ok
        total_ok += n_ok
        total_cost += _num(r.get("total_cost")) or 0.0
        judge_cost += _num(r.get("judge_total_cost")) or 0.0
        n_questions = max(n_questions, _int(r.get("n_questions")))
        needs_review += _int(r.get("needs_review_count"))
        shaped.append({
            "agent_label": _str(r.get("agent_label")) or _str(r.get("agent_key")),
            "mode": _str(r.get("mode")),
            "n_questions": _int(r.get("n_questions")),
            "n_ok": n_ok,
            "n_error": _int(r.get("n_error")),
            "error_rate": _num(r.get("error_rate")) or 0.0,
            "error_rate_str": fmt_pct(r.get("error_rate")),
            "accuracy": acc,
            "accuracy_pct": fmt_pct(acc),
            "mean_score": _num(r.get("mean_score")) or 0.0,
            "latency_p50_s": _num(r.get("latency_p50_s")) or 0.0,
            "latency_p50_str": fmt_secs(r.get("latency_p50_s")),
            "latency_p95_s": _num(r.get("latency_p95_s")) or 0.0,
            "latency_p95_str": fmt_secs(r.get("latency_p95_s")),
            "avg_cost_per_q": _num(r.get("avg_cost_per_q")) or 0.0,
            "avg_cost_per_q_str": fmt_money(r.get("avg_cost_per_q")),
            "total_cost": _num(r.get("total_cost")) or 0.0,
            "needs_review_count": _int(r.get("needs_review_count")),
        })

    # Order by accuracy desc, then agent/mode for a stable, comparable table.
    shaped.sort(key=lambda s: (-s["accuracy"], s["agent_label"], s["mode"]))
    global_acc = (total_correct / total_ok) if total_ok else 0.0
    return {
        "run_id": rid,
        "kpis": {
            "accuracy": global_acc,
            "accuracy_pct": fmt_pct(global_acc),
            "n_questions": n_questions,
            "n_configs": len(shaped),
            "total_cost": total_cost,
            "total_cost_str": fmt_money2(total_cost),
            "judge_cost_str": fmt_money2(judge_cost),
            "needs_review": needs_review,
        },
        "rows": shaped,
    }


# --- restitution: breakdown (accuracy per category) -------------------------

def breakdown_view(breakdown_rows, run_id=None):
    """Shape benchmark_breakdown rows for ONE run into per (agent x mode, bucket) accuracy."""
    rows = _rows(breakdown_rows)
    rid = _str(run_id) or latest_run_id(rows)
    if rid:
        rows = [r for r in rows if _str(r.get("run_id")) == rid]
    out = []
    for r in rows:
        out.append({
            "agent_label": _str(r.get("agent_label")) or _str(r.get("agent_key")),
            "mode": _str(r.get("mode")),
            "dimension": _str(r.get("dimension")),
            "bucket": _str(r.get("bucket")),
            "n": _int(r.get("n")),
            "accuracy": _num(r.get("accuracy")) or 0.0,
            "accuracy_pct": fmt_pct(r.get("accuracy")),
            "mean_score": _num(r.get("mean_score")) or 0.0,
        })
    out.sort(key=lambda s: (s["agent_label"], s["mode"], s["bucket"]))
    return {"run_id": rid, "rows": out}


# --- restitution: per-question detail ---------------------------------------

# A short preview length for the heavy answer body (the full text is NOT shipped to the table).
_ANSWER_PREVIEW_CHARS = 280


def detail_view(scored_rows, run_id=None, only_needs_review=False, limit=200):
    """Shape benchmark_runs_scored rows for ONE run into the per-question table.

    The heavy ``full_answer`` / ``generated_sql_json`` columns are dropped (a short answer
    preview is kept). ``only_needs_review`` keeps the priority re-read pile; ``limit`` bounds
    the returned rows. Pure, never raises.
    """
    rows = _rows(scored_rows)
    rid = _str(run_id) or latest_run_id(rows)
    if rid:
        rows = [r for r in rows if _str(r.get("run_id")) == rid]
    try:
        cap = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        cap = 200

    out = []
    for r in rows:
        needs_review = _truthy(r.get("needs_review"))
        if only_needs_review and not needs_review:
            continue
        answer = _str(r.get("answer_text"))
        out.append({
            "question_id": _str(r.get("question_id")),
            "question": _str(r.get("question")),
            "category": _str(r.get("category")),
            "agent_label": _str(r.get("agent_label")) or _str(r.get("agent_key")),
            "mode": _str(r.get("mode")),
            "status": _str(r.get("status")),
            "objective_match": _str(r.get("objective_match")),
            "judge_score": _int(r.get("judge_score")),
            "judge_verdict": _str(r.get("judge_verdict")),
            "correct": _truthy(r.get("correct")),
            "needs_review": needs_review,
            "reference_answer": _str(r.get("reference_answer")),
            "answer_preview": answer[:_ANSWER_PREVIEW_CHARS],
            "latency_total_s": _num(r.get("latency_total_s")) or 0.0,
            "latency_str": fmt_secs(r.get("latency_total_s")),
            "estimated_cost": _num(r.get("estimated_cost")) or 0.0,
        })
    # Needs-review first, then incorrect, then the rest - the eye lands on the problems. Sort
    # the FULL filtered list BEFORE capping, so a needs-review row beyond the cap is never
    # dropped from view (the cap bounds the table, the sort surfaces the problems within it).
    out.sort(key=lambda s: (not s["needs_review"], s["correct"], s["question_id"]))
    out = out[:cap]
    return {"run_id": rid, "count": len(out), "rows": out}


# --- config edit + validation -----------------------------------------------

def validate_config(raw):
    """Validate an edited ``benchmark`` variable value before it is written back.

    ``raw`` is the WHOLE ``benchmark`` object (a dict, or a JSON string of it). Returns
    ``(ok, resolved, errors)`` where ``resolved`` is the normalized run_params config (the
    same the steps will read) and ``errors`` is a list of human messages. Never raises.
    """
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return False, None, ["the configuration is empty"]
        try:
            obj = json.loads(text)
        except Exception:
            return False, None, ["invalid JSON: check the syntax (commas, quotes, braces)"]
    elif isinstance(raw, dict):
        obj = raw
    else:
        return False, None, ["the configuration must be a JSON object"]

    if not isinstance(obj, dict):
        return False, None, ["the configuration must be a JSON object"]

    # resolve expects the merged custom-variables dict; the variable lives under "benchmark".
    cfg = run_params.resolve({"benchmark": obj})
    errors = []
    if not cfg.get("agents"):
        errors.append(
            "no valid agent: 'agents' must list at least one "
            "{agent_key, project_key, agent_id}"
        )
    if not cfg.get("modes"):
        errors.append("no valid mode in 'modes'")
    return (len(errors) == 0), cfg, errors


# --- suggestions promotion (Lot 3) ------------------------------------------

import re as _re

# A physical table name comes from the admin config (benchmark.suggestions.table), not from an
# end user, but it is interpolated into a cross-project SELECT identifier, so it is restricted
# to a plain identifier charset (letters, digits, _ and -) before use. Anything else -> None.
_TABLE_RE = _re.compile(r"^[A-Za-z0-9_-]{1,200}$")

_EXPECTED_VALUE_TYPES = ("numeric", "currency", "date", "string", "list")


def safe_table_name(name):
    """The physical table name when it is a plain identifier, else None. Never raises."""
    if isinstance(name, str) and _TABLE_RE.match(name.strip()):
        return name.strip()
    return None


def suggestions_view(rows):
    """Shape pending user-suggestion rows (cross-project read) for the review table.

    Keeps a light projection (no heavy agent answer / SQL body). Pure, never raises.
    """
    out = []
    for r in _rows(rows):
        out.append({
            "suggestion_id": _str(r.get("suggestion_id")),
            "user_id": _str(r.get("user_id")),
            "source": _str(r.get("source")),
            "question": _str(r.get("question")),
            "reference_answer": _str(r.get("reference_answer")),
            "answer_is_correct": r.get("answer_is_correct"),
            "missing_explanation": _str(r.get("missing_explanation")),
            "expected_value": _str(r.get("expected_value")),
            "expected_value_type": _str(r.get("expected_value_type")),
            "category": _str(r.get("category")),
            "language": _str(r.get("language")) or "fr",
            "created_at": _str(r.get("created_at")),
        })
    out.sort(key=lambda s: s["created_at"], reverse=True)
    return out


def suggestion_to_golden(sug):
    """Map one user-suggestion row onto a golden lean-9 row, or None when not promotable.

    A suggestion is promotable only when it carries a reference answer (the human-validated
    truth a golden row needs). The question_id is minted DETERMINISTICALLY from the
    suggestion_id so re-promoting the same suggestion would yield the same id (idempotent).
    The expected_value is kept only with a valid type. Pure, never raises.
    """
    if not isinstance(sug, dict):
        return None
    question = _str(sug.get("question")).strip()
    reference = _str(sug.get("reference_answer")).strip()
    if not question or not reference:
        return None
    sid = _str(sug.get("suggestion_id")).strip()
    if not sid:
        return None
    expected_value = _str(sug.get("expected_value")).strip() or None
    expected_type = _str(sug.get("expected_value_type")).strip().lower() or None
    if expected_value is None or expected_type not in _EXPECTED_VALUE_TYPES:
        expected_value = None
        expected_type = None
    language = _str(sug.get("language")).strip().lower()
    if language not in ("fr", "en"):
        language = "fr"
    category = _str(sug.get("category")).strip() or None
    return {
        "question_id": "u_" + sid[:24],
        "question": question,
        "reference_answer": reference,
        "expected_value": expected_value,
        "expected_value_type": expected_type,
        "category": category,
        "language": language,
        "active": True,
        "notes": "promoted from user suggestion {0} (source={1})".format(
            sid, _str(sug.get("source")) or "manual"),
    }


def promotable_golden_rows(suggestions, already_promoted_ids):
    """Map a list of suggestions onto golden rows, skipping non-promotable + already-promoted.

    Returns ``(golden_rows, used_suggestion_ids)``. De-dups by minted question_id so two
    suggestions that collide on the id keep only the first. Pure, never raises.
    """
    promoted = set(str(x) for x in (already_promoted_ids or []))
    golden_rows = []
    used_ids = []
    seen_qids = set()
    for sug in (suggestions or []):
        sid = _str(sug.get("suggestion_id")).strip() if isinstance(sug, dict) else ""
        if not sid or sid in promoted:
            continue
        row = suggestion_to_golden(sug)
        if not row:
            continue
        qid = row["question_id"]
        if qid in seen_qids:
            continue
        seen_qids.add(qid)
        golden_rows.append(row)
        used_ids.append(sid)
    return golden_rows, used_ids


def config_view(resolved):
    """A compact, display-ready view of the resolved config (for the config page summary)."""
    cfg = resolved or {}
    agents = cfg.get("agents") or []
    return {
        "agents": [
            {
                "agent_key": _str(a.get("agent_key")),
                "agent_label": _str(a.get("agent_label")) or _str(a.get("agent_key")),
                "project_key": _str(a.get("project_key")),
                "agent_id": _str(a.get("agent_id")),
                "modes": bool(a.get("modes")),
            }
            for a in agents if isinstance(a, dict)
        ],
        "modes": list(cfg.get("modes") or []),
        "language": _str(cfg.get("language")),
        "concurrency": _int(cfg.get("concurrency")),
        "golden_dataset": _str(cfg.get("golden_dataset")),
        "question_filter": cfg.get("question_filter") or {},
        "judge_llm_id": _str(cfg.get("judge_llm_id")),
        "suggestions": run_params.suggestions_config(cfg),
    }
