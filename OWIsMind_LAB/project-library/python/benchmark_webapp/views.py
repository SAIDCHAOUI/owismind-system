"""Pure view-model shaping + config validation for the benchmark webapp (PURE).

Stdlib only (plus benchmark.run_params for config validation). Turns the result datasets
(benchmark_summary / benchmark_breakdown / benchmark_runs_scored) into compact, display-ready
view-models the standard webapp renders, and validates an edited ``benchmark`` variable before
it is written back. Every function is robust to None / missing / malformed rows and never
raises - the webapp must degrade to an empty view, not a 500.

Design contract: docs/superpowers/specs/2026-06-25-benchmark-integration-design.md (section 4.1).
"""

import hashlib
import json

from benchmark import run_params, schemas
from benchmark import registry
from benchmark import scoring


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


def _int(value, default=0):
    f = _num(value)
    return int(f) if f is not None else default


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


# --- v2: benchmark selector (the Results / Review picker is BY BENCHMARK now) ----

def _row_ts(r):
    """The recency timestamp of a row: the summary's last_run_timestamp or the scored run_timestamp."""
    return _str(r.get("last_run_timestamp")) or _str(r.get("run_timestamp"))


def latest_benchmark_id(rows):
    """The most-recent benchmark_id across rows (by recency ts, then id). '' when none. Pure."""
    best_key = None
    best = ""
    for r in _rows(rows):
        bid = _str(r.get("benchmark_id"))
        if not bid:
            continue
        key = (_row_ts(r), bid)
        if best_key is None or key > best_key:
            best_key = key
            best = bid
    return best


def benchmark_options(rows):
    """Distinct (benchmark_id, benchmark_name, last_run_timestamp) for the selector, newest first.

    Accepts summary OR scored rows (reads benchmark_name + a recency timestamp from either). A row
    with no benchmark_id collapses into a single '' bucket (a legacy run predating v2). Pure.
    """
    acc = {}
    for r in _rows(rows):
        bid = _str(r.get("benchmark_id"))
        entry = acc.setdefault(bid, {"benchmark_id": bid, "benchmark_name": "", "last_run_timestamp": ""})
        name = _str(r.get("benchmark_name"))
        if name and not entry["benchmark_name"]:
            entry["benchmark_name"] = name
        ts = _row_ts(r)
        if ts > entry["last_run_timestamp"]:
            entry["last_run_timestamp"] = ts
    items = [{"benchmark_id": e["benchmark_id"],
              "benchmark_name": e["benchmark_name"] or e["benchmark_id"] or "(default)",
              "last_run_timestamp": e["last_run_timestamp"]} for e in acc.values()]
    items.sort(key=lambda it: (it["last_run_timestamp"], it["benchmark_id"]), reverse=True)
    return items


# --- restitution: summary (KPIs + agent x mode table) -----------------------

def summary_view(summary_rows, benchmark_id=None):
    """Shape benchmark_summary rows for ONE benchmark into KPI tiles + an agent x mode table (v2).

    KPIs: global accuracy (correct over scored across the benchmark, latest attempt each), question
    count, configurations (agent x mode) tested, total cost, total needs-review. The per-row table
    carries the raw numbers (for bar widths) and the formatted strings (for labels). Pure, never raises.
    """
    rows = _rows(summary_rows)
    bid = _str(benchmark_id) or latest_benchmark_id(rows)
    if bid:
        rows = [r for r in rows if _str(r.get("benchmark_id")) == bid]
    bench_name = next((_str(r.get("benchmark_name")) for r in rows
                       if _str(r.get("benchmark_name"))), "")

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
        "benchmark_id": bid,
        "benchmark_name": bench_name or bid,
        "kpis": {
            "accuracy": global_acc,
            "accuracy_pct": fmt_pct(global_acc),
            # Plain-language "X of Y answered correctly" (n_correct over the scored questions),
            # so the public page can state the verdict in words, not just a percentage.
            "n_correct": int(round(total_correct)),
            "n_ok_total": total_ok,
            "band": confidence_band(global_acc),
            "n_questions": n_questions,
            "n_configs": len(shaped),
            "total_cost": total_cost,
            "total_cost_str": fmt_money2(total_cost),
            "judge_cost_str": fmt_money2(judge_cost),
            "needs_review": needs_review,
        },
        "rows": shaped,
    }


def confidence_band(accuracy):
    """A plain confidence band for an accuracy fraction: 'high' / 'medium' / 'low'.

    Drives the public results color + verdict wording (>=85% high, >=60% medium, else low). The
    thresholds are deliberately simple so a non-technical reader gets one clear signal."""
    a = _num(accuracy) or 0.0
    if a >= 0.85:
        return "high"
    if a >= 0.60:
        return "medium"
    return "low"


# --- restitution: breakdown (accuracy per category) -------------------------

def breakdown_view(breakdown_rows, benchmark_id=None):
    """Shape benchmark_breakdown rows for ONE benchmark into per (agent x mode, bucket) accuracy (v2)."""
    rows = _rows(breakdown_rows)
    bid = _str(benchmark_id) or latest_benchmark_id(rows)
    if bid:
        rows = [r for r in rows if _str(r.get("benchmark_id")) == bid]
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
    return {"benchmark_id": bid, "rows": out}


# --- restitution: per-question detail ---------------------------------------

# A short preview length for the heavy answer body (the full text is NOT shipped to the table).
_ANSWER_PREVIEW_CHARS = 280


def _shape_detail_row(r):
    """Shape one scored row into a per-question table row (effective verdict + the v2 fields)."""
    answer = _str(r.get("answer_text"))
    eff = schemas.effective_correct(r)
    return {
        "question_id": _str(r.get("question_id")),
        "question": _str(r.get("question")),
        "category": _str(r.get("category")),
        # The override match key = (run_id, question_id, agent_key, mode); agent_label is display.
        "run_id": _str(r.get("run_id")),
        "run_timestamp": _str(r.get("run_timestamp")),
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
        "latency_total_s": _num(r.get("latency_total_s")) or 0.0,
        "latency_str": fmt_secs(r.get("latency_total_s")),
        "estimated_cost": _num(r.get("estimated_cost")) or 0.0,
        # Strictness note + crisp expected value (so the review panel shows the contract).
        "notes": _str(r.get("notes")),
        "expected_value": _str(r.get("expected_value")),
        "expected_value_type": _str(r.get("expected_value_type")),
        # v2: the benchmark dimension + the reference SQL/tool vs what the agent actually used.
        "benchmark_id": _str(r.get("benchmark_id")),
        "benchmark_name": _str(r.get("benchmark_name")),
        "attempt_no": _int(r.get("attempt_no")),
        "expected_sql": _str(r.get("expected_sql")),
        "expected_tool": _str(r.get("expected_tool")),
        "actual_tools": _str(r.get("actual_tools")),
        # Human-in-the-loop override (the effective verdict is what KPIs already use).
        "human_verdict": _str(r.get("human_verdict")),
        "human_comment": _str(r.get("human_comment")),
        "reviewed_by": _str(r.get("reviewed_by")),
        "reviewed_at": _str(r.get("reviewed_at")),
        "effective_correct": eff["correct"],
        "effective_verdict": eff["verdict"],
        "overridden": eff["overridden"],
    }


def detail_view(scored_rows, benchmark_id=None, only_needs_review=False, limit=200):
    """Shape benchmark_runs_scored rows for ONE benchmark into the per-question table (v2).

    Reduces to the LATEST attempt of each question x mode (the benchmark's current state) and attaches
    each row's ``evolution`` (per-mode attempt history + delta) so the consultation can show progress.
    The heavy ``full_answer`` / ``generated_sql_json`` columns are not present (light read).
    ``only_needs_review`` keeps the priority pile; ``limit`` bounds the returned rows. Pure, never raises.
    """
    rows = _rows(scored_rows)
    bid = _str(benchmark_id) or latest_benchmark_id(rows)
    bench_rows = [r for r in rows if _str(r.get("benchmark_id")) == bid] if bid else rows
    try:
        cap = max(1, min(int(limit), 2000))
    except (TypeError, ValueError):
        cap = 200

    latest = scoring.latest_attempts(bench_rows)
    out = []
    for r in latest:
        shaped = _shape_detail_row(r)
        if only_needs_review and not shaped["needs_review"]:
            continue
        ev = evolution_for_question(bench_rows, bid, shaped["question_id"])
        # Find this row's mode entry for the delta + attempt count (the per-(question, mode) history).
        mode_ev = next((m for m in ev if m["mode"] == shaped["mode"]), None)
        shaped["n_attempts"] = len(mode_ev["attempts"]) if mode_ev else 1
        shaped["delta"] = mode_ev["delta"] if mode_ev else "first"
        shaped["attempts"] = mode_ev["attempts"] if mode_ev else []
        out.append(shaped)
    out.sort(key=lambda s: (not s["needs_review"], s["effective_correct"], s["question_id"], s["mode"]))
    out = out[:cap]
    return {"benchmark_id": bid, "count": len(out), "rows": out}


def review_view(scored_rows, benchmark_id=None, only_needs_review=False, limit=2000):
    """ALL attempts of one benchmark (NOT reduced to latest), for the launcher Review/override (v2).

    The reviewer overrides a SPECIFIC attempt (the override key is run_id/question_id/agent_key/mode),
    so this lists every attempt - newest first within a question - rather than the latest only. Pure.
    """
    rows = _rows(scored_rows)
    bid = _str(benchmark_id) or latest_benchmark_id(rows)
    bench_rows = [r for r in rows if _str(r.get("benchmark_id")) == bid] if bid else rows
    try:
        cap = max(1, min(int(limit), 5000))
    except (TypeError, ValueError):
        cap = 2000
    out = []
    for r in bench_rows:
        shaped = _shape_detail_row(r)
        if only_needs_review and not shaped["needs_review"]:
            continue
        out.append(shaped)
    # Needs-review first (the priority pile), then group a question's attempts together with the
    # newest attempt on top so the latest verdict + its evolution read at a glance.
    out.sort(key=lambda s: (not s["needs_review"], s["question_id"], s["mode"], -s["attempt_no"]))
    out = out[:cap]
    return {"benchmark_id": bid, "count": len(out), "rows": out}


# --- human-in-the-loop override (pure key match + field set) ----------------

_OVERRIDE_KEYS = ("run_id", "question_id", "agent_key", "mode")


def validate_override(payload):
    """Validate a reviewer's override request. Returns ``(ok, errors)``. Pure, never raises.

    Requires the row key (run_id, question_id, agent_key; mode may be blank for a no-mode agent)
    and a verdict that is "correct", "incorrect", or "" (blank clears a prior override).
    """
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


def _override_match(row, payload):
    """True when a scored row matches the override key (run_id, question_id, agent_key, mode)."""
    for key in _OVERRIDE_KEYS:
        if _str(row.get(key)).strip() != _str(payload.get(key)).strip():
            return False
    return True


def apply_override(scored_rows, payload):
    """Set the human_* fields on every scored row matching the override key. Pure, never raises.

    Returns ``(new_rows, matched_count)``. A blank verdict CLEARS the override (human_* reset).
    Other rows are returned unchanged. The caller (dss) persists the rewritten list and stamps
    ``reviewed_at`` (modules never read the clock).
    """
    verdict = _str(payload.get("verdict")).strip().lower()
    if verdict not in ("correct", "incorrect"):
        verdict = ""  # blank / garbage clears
    human_correct = None if verdict == "" else (verdict == "correct")
    comment = "" if verdict == "" else _str(payload.get("comment"))
    reviewer = "" if verdict == "" else _str(payload.get("reviewed_by"))
    reviewed_at = "" if verdict == "" else _str(payload.get("reviewed_at"))

    out = []
    matched = 0
    for r in (scored_rows or []):
        if isinstance(r, dict) and _override_match(r, payload):
            matched += 1
            merged = dict(r)
            merged["human_verdict"] = verdict
            merged["human_correct"] = human_correct
            merged["human_comment"] = comment
            merged["reviewed_by"] = reviewer
            merged["reviewed_at"] = reviewed_at
            out.append(merged)
        else:
            out.append(r)
    return out, matched


# --- suggestions promotion (Lot 3) ------------------------------------------

import re as _re

# A physical table name comes from the admin config (benchmark.suggestions.table), not from an
# end user, but it is interpolated into a cross-project SELECT identifier, so it is restricted
# to a plain identifier charset (letters, digits, _ and -) before use. Anything else -> None.
_TABLE_RE = _re.compile(r"^[A-Za-z0-9_-]{1,200}$")

_EXPECTED_VALUE_TYPES = ("numeric", "currency", "date", "string", "list")


def minted_question_id(suggestion_id):
    """The deterministic golden question_id a suggestion would get when promoted.

    Stable + idempotent (same suggestion_id -> same question_id). The GOLDEN is the source of
    truth for "already promoted": a suggestion is already in the golden iff this id is one of the
    golden's question_ids (so the review list / dedup never depend on a separate corruptible log).
    """
    sid = _str(suggestion_id).strip()
    return ("u_" + sid[:24]) if sid else ""


def safe_table_name(name):
    """The physical table name when it is a plain identifier, else None. Never raises."""
    if isinstance(name, str) and _TABLE_RE.match(name.strip()):
        return name.strip()
    return None


def suggestions_view(rows, exclude_ids=None):
    """Shape pending user-suggestion rows (cross-project read) for the review table.

    Keeps a light projection (no heavy agent answer / SQL body). ``exclude_ids`` drops rows whose
    suggestion_id was already promoted (their source row stays status='pending' forever, so the
    LAB promoted-ids log is what filters them out of the review list). Pure, never raises.
    """
    excl = set(str(x) for x in (exclude_ids or []))
    out = []
    for r in _rows(rows):
        sid = _str(r.get("suggestion_id"))
        if sid and sid in excl:
            continue
        out.append({
            "suggestion_id": sid,
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
        "question_id": minted_question_id(sid),
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


# --- golden question management (admin CRUD from the launcher) ---------------

def golden_view(rows):
    """Shape golden rows for the management table (all 9 columns, normalized, sorted).

    Rows missing a question_id are skipped (they cannot be edited/deleted without a key).
    ``active`` is surfaced as a real bool (default True when absent). Sorted by category then
    question_id for a stable, grouped list. Pure, never raises.
    """
    out = []
    for r in _rows(rows):
        qid = _str(r.get("question_id")).strip()
        if not qid:
            continue
        act = r.get("active")
        out.append({
            "question_id": qid,
            "question": _str(r.get("question")),
            "reference_answer": _str(r.get("reference_answer")),
            "expected_value": _str(r.get("expected_value")),
            "expected_value_type": _str(r.get("expected_value_type")),
            "category": _str(r.get("category")),
            "language": _str(r.get("language")) or "fr",
            "active": True if act is None else _truthy(act),
            "notes": _str(r.get("notes")),
            # v2: reference SQL / tool (soft judge signal + training data), editable in the launcher.
            "expected_sql": _str(r.get("expected_sql")),
            "expected_tool": _str(r.get("expected_tool")),
        })
    out.sort(key=lambda g: ((g["category"] or "~"), g["question_id"]))
    return out


def mint_admin_question_id(question, existing_ids):
    """A stable, unique golden question_id for an admin-authored question.

    Prefix ``a_`` (distinct from the ``u_`` user-suggestion ids), derived from a hash of the
    question text so the same question yields the same id; a numeric suffix breaks the (rare)
    collision against ``existing_ids``. Pure, never raises.
    """
    digest = hashlib.sha1(_str(question).strip().encode("utf-8")).hexdigest()[:16]
    base = "a_" + digest
    existing = set(str(x) for x in (existing_ids or []))
    if base not in existing:
        return base
    n = 2
    while "{0}_{1}".format(base, n) in existing:
        n += 1
    return "{0}_{1}".format(base, n)


def prepare_golden_save(payload, existing_ids):
    """Validate + normalize an admin create/update of a golden question.

    Returns ``(clean_row, errors, is_new)``. A payload WITHOUT a question_id is a create: a
    fresh ``a_`` id is minted (unique vs ``existing_ids``). A payload WITH a question_id is an
    update of that row. ``clean_row`` carries the 9 golden columns; ``errors`` is a list of
    human messages ([] when valid, via schemas.validate_golden_row). Pure, never raises.
    """
    row = schemas.normalize_golden_row(payload if isinstance(payload, dict) else {})
    qid = _str(row.get("question_id")).strip()
    is_new = not qid
    if is_new:
        row["question_id"] = mint_admin_question_id(row.get("question"), existing_ids)
    ok, errors = schemas.validate_golden_row(row)
    return row, errors, is_new


def apply_golden_upsert(existing_rows, clean_row):
    """Return the full golden list with ``clean_row`` inserted or replacing its question_id.

    On update, the existing row's EXTRA columns (any the prepared golden carries beyond the
    lean 9) are preserved and only the 9 golden fields are overwritten, so editing never
    narrows the dataset. Pure, never raises.
    """
    qid = _str(clean_row.get("question_id")).strip()
    out = []
    replaced = False
    for r in (existing_rows or []):
        if _str(r.get("question_id")).strip() == qid and qid:
            merged = dict(r)
            merged.update(clean_row)
            out.append(merged)
            replaced = True
        else:
            out.append(r)
    if not replaced:
        out.append(dict(clean_row))
    return out


def apply_golden_delete(existing_rows, question_id):
    """Return the golden list without the row whose question_id matches. Pure, never raises."""
    qid = _str(question_id).strip()
    if not qid:
        return list(existing_rows or [])
    return [r for r in (existing_rows or []) if _str(r.get("question_id")).strip() != qid]


# --- agent-first view-models (v2: registry-based, per-agent) ----------------

def _agent_tagged_active_ids(golden_rows, agent_key):
    """Ordered active golden question_ids tagged to ``agent_key``. Pure, never raises."""
    out = []
    for g in (golden_rows or []):
        if not isinstance(g, dict):
            continue
        act = g.get("active")
        if act is not None and not _truthy(act):
            continue
        if (g.get("agent_key") or None) == (agent_key or None):
            qid = g.get("question_id")
            if qid:
                out.append(qid)
    return out


def _last_run_ts(scored_rows, benchmark_id):
    """Max run_timestamp among rows of this benchmark, or None. Pure, never raises."""
    bid = _str(benchmark_id) if benchmark_id else None
    best = None
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if bid and _str(r.get("benchmark_id")) != bid:
            continue
        ts = _str(r.get("run_timestamp"))
        if ts and (best is None or ts > best):
            best = ts
    return best


def _accuracy_pct(summary_rows, scored_rows, benchmark_id):
    """Accuracy as a fraction [0,1] or None when nothing tested. Pure, never raises.

    Prefers the summary rows for the benchmark; falls back to latest-attempt effective_correct
    per (question, mode) in scored_rows. Returns None when there is nothing tested.
    """
    bid = _str(benchmark_id) if benchmark_id else None
    # Prefer summary rows when available.
    if summary_rows:
        total_correct = 0.0
        total_ok = 0
        for r in (summary_rows or []):
            if not isinstance(r, dict):
                continue
            if bid and _str(r.get("benchmark_id")) != bid:
                continue
            n_ok = _int(r.get("n_ok"))
            total_correct += (_num(r.get("accuracy")) or 0.0) * n_ok
            total_ok += n_ok
        if total_ok:
            return total_correct / total_ok
    # Fall back to scored rows: latest attempt per (question_id, mode).
    if not scored_rows:
        return None
    latest = {}
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if bid and _str(r.get("benchmark_id")) != bid:
            continue
        qid = _str(r.get("question_id"))
        mode = _str(r.get("mode"))
        if not qid:
            continue
        key = (qid, mode)
        attempt = _int(r.get("attempt_no"), 0)
        ts = _str(r.get("run_timestamp") or "")
        if key not in latest or (attempt, ts) > (latest[key][0], latest[key][1]):
            latest[key] = (attempt, ts, r)
    if not latest:
        return None
    n_correct = sum(1 for _, _, r in latest.values()
                    if schemas.effective_correct(r)["correct"])
    return n_correct / len(latest)


def agent_benchmarks_view(reg, agent_key, golden_rows, scored_rows, summary_rows=None):
    """Per-agent benchmark list with derived status counts. Pure, never raises.

    ``reg`` is the parsed registry ({benchmark_id: entity}).
    Returns {agent_key, n_tagged, benchmarks: [{benchmark_id, name, modes, n_questions,
    n_cells, n_tested, n_pending, n_redo, last_run_timestamp, accuracy_pct}]}.
    Archived benchmarks are excluded.
    """
    member_ids = _agent_tagged_active_ids(golden_rows, agent_key)
    benchmarks = []
    for entity in (reg or {}).values():
        if not isinstance(entity, dict):
            continue
        if (entity.get("agent_key") or None) != (agent_key or None):
            continue
        if (entity.get("status") or "active") == "archived":
            continue
        bid = entity.get("benchmark_id")
        modes = [m for m in (entity.get("modes") or []) if m] or [registry.DEFAULT_MODE]
        done = registry.done_cells(scored_rows, bid, agent_key)
        n_cells = len(member_ids) * len(modes)
        n_tested = sum(1 for q in member_ids for m in modes if (q, m) in done)
        redo = set(entity.get("redo") or [])
        benchmarks.append({
            "benchmark_id": bid,
            "name": entity.get("name"),
            "modes": modes,
            "n_questions": len(member_ids),
            "n_cells": n_cells,
            "n_tested": n_tested,
            "n_pending": n_cells - n_tested,
            "n_redo": sum(1 for q in member_ids if q in redo),
            "last_run_timestamp": _last_run_ts(scored_rows, bid),
            "accuracy_pct": _accuracy_pct(summary_rows, scored_rows, bid),
        })
    benchmarks.sort(key=lambda b: (b.get("name") or "").lower())
    return {"agent_key": agent_key, "n_tagged": len(member_ids), "benchmarks": benchmarks}


# --- attempt history (used by detail_view and review_view) ------------------

def _attempt_brief(r):
    """A compact per-attempt record (effective verdict wins) for the evolution view."""
    eff = schemas.effective_correct(r)
    return {
        "attempt_no": _int(r.get("attempt_no")),
        "run_timestamp": _str(r.get("run_timestamp")),
        "mode": _str(r.get("mode")),
        "status": _str(r.get("status")),
        "judge_score": _int(r.get("judge_score")),
        "judge_verdict": _str(r.get("judge_verdict")),
        "verdict": eff["verdict"],
        "correct": eff["correct"],
        "overridden": eff["overridden"],
    }


def evolution_for_question(scored_rows, benchmark_id, question_id):
    """Per-mode attempt history of one question in one benchmark. Pure, never raises.

    Returns a list (one entry per mode) of ``{mode, attempts: [brief...], latest, delta}`` where
    ``attempts`` is ordered by attempt_no, ``latest`` is the most recent attempt's brief, and
    ``delta`` is 'improved' / 'regressed' / 'same' / 'first' comparing the latest correct flag to the
    previous attempt's (the "evolution / regression" signal).
    """
    bid = _str(benchmark_id)
    qid = _str(question_id)
    by_mode = {}
    for r in _rows(scored_rows):
        if _str(r.get("benchmark_id")) != bid or _str(r.get("question_id")) != qid:
            continue
        by_mode.setdefault(_str(r.get("mode")), []).append(_attempt_brief(r))
    out = []
    for mode in sorted(by_mode):
        attempts = sorted(by_mode[mode], key=lambda a: (a["attempt_no"], a["run_timestamp"]))
        latest = attempts[-1] if attempts else None
        delta = "first"
        if len(attempts) >= 2:
            prev, cur = attempts[-2]["correct"], attempts[-1]["correct"]
            delta = "same" if prev == cur else ("improved" if cur and not prev else "regressed")
        out.append({"mode": mode, "attempts": attempts, "latest": latest, "delta": delta})
    return out


# --- per-mode benchmark detail (replaces the old membership-map detail) -----

def _latest_cell_verdict(scored_rows, benchmark_id, question_id, mode):
    """Latest-attempt effective verdict for a (benchmark, question, mode) cell, or None if untested."""
    best = None
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if r.get("benchmark_id") != benchmark_id or r.get("question_id") != question_id:
            continue
        if (r.get("mode") or "") != (mode or ""):
            continue
        key = (_int(r.get("attempt_no"), 0), str(r.get("run_timestamp") or ""))
        if best is None or key > best[0]:
            best = (key, r)
    if best is None:
        return None
    return "OK" if schemas.effective_correct(best[1])["correct"] else "MISS"


def benchmark_detail_view(entity, golden_rows, scored_rows):
    """The per-mode cell table for ONE benchmark. Pure, never raises.

    ``entity`` is one registry entity; ``golden_rows`` the golden pool (for question text +
    active/agent_key membership + reference SQL/tool); ``scored_rows`` a light scored projection
    of this benchmark.

    Returns {benchmark_id, name, agent{...}, modes, ledger{tested, pending, redo},
    runnable, accuracy_pct, questions:[{question_id, question, category, expected_sql,
    expected_tool, redo, cells:[{mode, status, verdict}]}]}.
    """
    entity = entity if isinstance(entity, dict) else {}
    bid = entity.get("benchmark_id")
    agent_key = entity.get("agent_key")
    modes = [m for m in (entity.get("modes") or []) if m] or [registry.DEFAULT_MODE]
    redo = set(entity.get("redo") or [])
    # Membership = active golden rows tagged to this agent.
    members = [g for g in (golden_rows or [])
               if isinstance(g, dict)
               and (g.get("active") is None or _truthy(g.get("active")))
               and (g.get("agent_key") or None) == (agent_key or None)
               and g.get("question_id")]
    questions = []
    tested = 0
    runnable = 0
    for g in members:
        qid = g.get("question_id")
        cells = []
        for m in modes:
            verdict = _latest_cell_verdict(scored_rows, bid, qid, m)
            is_tested = verdict is not None
            if is_tested:
                tested += 1
            if not is_tested or qid in redo:
                runnable += 1
            cells.append({"mode": m,
                          "status": "tested" if is_tested else "pending",
                          "verdict": verdict})
        questions.append({
            "question_id": qid,
            "question": g.get("question"),
            "category": g.get("category"),
            "expected_sql": g.get("expected_sql"),
            "expected_tool": g.get("expected_tool"),
            "redo": qid in redo,
            "cells": cells,
        })
    n_cells = len(members) * len(modes)
    return {
        "benchmark_id": bid,
        "name": entity.get("name"),
        "agent": {
            "agent_key": agent_key,
            "agent_label": entity.get("agent_label"),
            "project_key": entity.get("project_key"),
            "agent_id": entity.get("agent_id"),
        },
        "modes": modes,
        "ledger": {
            "tested": tested,
            "pending": n_cells - tested,
            "redo": sum(1 for q in members if q.get("question_id") in redo),
        },
        "runnable": runnable,
        "accuracy_pct": _accuracy_pct(None, scored_rows, bid),
        "questions": questions,
    }


def build_launch_request(benchmark_id, launch_mode):
    """The ``run_request`` block to write into the variable before firing. None when invalid. Pure."""
    bid = _str(benchmark_id).strip()
    if not bid:
        return None
    mode = _str(launch_mode).strip().lower()
    if mode not in (registry.LAUNCH_APPEND, registry.LAUNCH_FULL):
        mode = registry.LAUNCH_APPEND
    return {"benchmark_id": bid, "launch_mode": mode}


# --- task-9: golden tag view + benchmark settings validation ----------------

def golden_tag_view(golden_rows, agent_key=None, scope="agent"):
    """Shape golden rows filtered by agent_key scope. Pure, never raises.

    scope (the value the frontend / launcher MOCK send):
        "agent"    - rows whose agent_key matches (tagged to this agent). "this" is an alias.
        "untagged" - rows with a blank / None agent_key.
        "all"      - all rows regardless of tag.

    Returns ``{"questions": [...]}`` (the key the frontend reads). Each row carries the golden
    columns the launcher needs, including agent_key and the reference SQL / tool fields.
    """
    akey = _str(agent_key).strip() if agent_key else ""
    out = []
    for r in (golden_rows or []):
        if not isinstance(r, dict):
            continue
        row_key = _str(r.get("agent_key")).strip()
        if scope in ("agent", "this"):
            if row_key != akey:
                continue
        elif scope == "untagged":
            if row_key:
                continue
        # scope == "all" passes everything
        out.append({
            "question_id": _str(r.get("question_id")),
            "question": _str(r.get("question")),
            "reference_answer": _str(r.get("reference_answer")),
            "expected_value": _str(r.get("expected_value")),
            "expected_value_type": _str(r.get("expected_value_type")),
            "category": _str(r.get("category")),
            "language": _str(r.get("language")) or "fr",
            "active": True if r.get("active") is None else _truthy(r.get("active")),
            "notes": _str(r.get("notes")),
            "expected_sql": _str(r.get("expected_sql")),
            "expected_tool": _str(r.get("expected_tool")),
            "agent_key": _str(r.get("agent_key")),
        })
    return {"questions": out}


def validate_benchmark_name(name, taken_names):
    """Validate a new benchmark name. Wraps registry.validate_benchmark_name. Pure, never raises.

    Returns ``(ok, error_or_None)``: non-blank, <=80 chars, unique case-insensitively.
    """
    return registry.validate_benchmark_name(name, taken_names)


def settings_view(cfg):
    """Shape the resolved config into the settings view-model for the Settings tab. Pure."""
    c = cfg if isinstance(cfg, dict) else {}
    return {
        "golden_dataset": _str(c.get("golden_dataset")),
        "judge_llm_id": _str(c.get("judge_llm_id")),
        "concurrency": _int(c.get("concurrency")) or 3,
        "language": _str(c.get("language")) or "fr",
        "raw_dataset": _str(c.get("raw_dataset")),
        "scored_dataset": _str(c.get("scored_dataset")),
        "summary_dataset": _str(c.get("summary_dataset")),
        "breakdown_dataset": _str(c.get("breakdown_dataset")),
    }


def validate_settings(form):
    """Validate a benchmark settings form submission. Returns ``(ok, normalized)`` or
    ``(False, [error strings])``. Pure, never raises.

    Mandatory: golden_dataset non-blank. concurrency int 1..8. language 'en' or 'fr'.
    Dataset names (raw/scored/summary/breakdown) must be non-blank when provided.
    """
    if not isinstance(form, dict):
        return False, ["settings must be an object"]
    errors = []
    normalized = {}

    golden_dataset = _str(form.get("golden_dataset")).strip()
    if not golden_dataset:
        errors.append("golden_dataset is required")
    else:
        normalized["golden_dataset"] = golden_dataset

    normalized["judge_llm_id"] = _str(form.get("judge_llm_id"))

    concurrency_raw = form.get("concurrency")
    if concurrency_raw is not None:
        try:
            concurrency = int(float(_str(concurrency_raw)))
            if not (1 <= concurrency <= 8):
                errors.append("concurrency must be between 1 and 8")
            else:
                normalized["concurrency"] = concurrency
        except (TypeError, ValueError):
            errors.append("concurrency must be an integer")

    lang = _str(form.get("language")).strip().lower()
    if lang and lang not in ("en", "fr"):
        errors.append("language must be 'en' or 'fr'")
    else:
        normalized["language"] = lang or "fr"

    for field in ("raw_dataset", "scored_dataset", "summary_dataset", "breakdown_dataset"):
        if field in form:
            val = _str(form.get(field)).strip()
            if not val:
                errors.append("{0} must not be blank".format(field))
            else:
                normalized[field] = val

    if errors:
        return False, errors
    return True, normalized
