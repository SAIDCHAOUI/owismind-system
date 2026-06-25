"""Aggregation and KPI computation for the benchmark Flow (PURE).

Stdlib only, no dataiku / pandas. Turns the readable detail table
``benchmark_runs_scored`` into the two restitution tables:

- ``benchmark_summary``   : one row per (run_id, agent_key, mode), the KPI block
  (accuracy, mean score, score distribution, latency p50/p95/max, ttft p50,
  cost per question, tokens, error rate, needs-review count, judge cost).
- ``benchmark_breakdown`` : one row per (run_id, agent_key, mode, dimension,
  bucket) for dimension in (category, answer_type, difficulty), with the count,
  accuracy and mean score inside each bucket.

Robustness contract: a scored row may carry None / missing fields. Errored rows
(``status`` other than "ok") have no score and no latency: they are counted in
``n_questions`` and ``n_error`` (so they raise the error rate) but excluded from
score / latency / cost / token statistics. ``accuracy`` is a fraction in [0, 1]
computed over scored (ok) questions only. Every function is pure and never raises.

Design contract: docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md
section 7 (aggregation and restitution).
"""

import json

from benchmark.schemas import (
    SUMMARY_COLUMNS,
    BREAKDOWN_COLUMNS,
    BREAKDOWN_DIMENSIONS,
)

# A scored row counts as a successful (scored) run only when its status is "ok".
# Anything else (error / timeout / blank) is an error for KPI purposes.
_OK_STATUS = "ok"

# Valid judge scores, used to build the 1..5 distribution.
_SCORE_BUCKETS = (1, 2, 3, 4, 5)


def percentile(values, p):
    """Return the ``p`` percentile of ``values`` (linear interpolation).

    ``p`` is a fraction in [0, 1] (e.g. 0.5 for the median, 0.95 for p95).
    ``values`` is an iterable of numbers; non-numeric / None entries are dropped.
    Returns a float. An empty input returns 0.0 (documented choice: the summary
    columns are numeric and a missing latency reads cleanly as 0.0 rather than a
    null that breaks downstream maths). ``p`` is clamped to [0, 1].

    Method: sort, then index = p * (n - 1) with linear interpolation between the
    two surrounding samples (the common "linear" / type-7 definition). Pure,
    never raises.
    """
    nums = _to_floats(values)
    if not nums:
        return 0.0
    nums.sort()
    n = len(nums)
    if n == 1:
        return nums[0]
    if p <= 0:
        return nums[0]
    if p >= 1:
        return nums[-1]
    pos = p * (n - 1)
    low = int(pos)
    high = low + 1
    if high >= n:
        return nums[-1]
    frac = pos - low
    return nums[low] + (nums[high] - nums[low]) * frac


def summarize(scored_rows):
    """Aggregate scored rows into ``benchmark_summary`` rows.

    Groups by (run_id, agent_key, mode) and returns one dict per group with the
    keys of ``SUMMARY_COLUMNS``. Pure, never raises. The output is ordered by
    (run_id, agent_key, mode) for stable, comparable runs.
    """
    groups = _group_by(scored_rows, _summary_key)
    out = []
    for key in sorted(groups, key=_sort_key):
        rows = groups[key]
        out.append(_summarize_group(key, rows))
    return out


def breakdown(scored_rows):
    """Aggregate scored rows into ``benchmark_breakdown`` rows.

    For each (run_id, agent_key, mode) group and each dimension in
    ``BREAKDOWN_DIMENSIONS`` (category / answer_type / difficulty), emits one row
    per non-blank bucket with the keys of ``BREAKDOWN_COLUMNS``: the bucket size
    ``n`` (scored ok rows only), the ``accuracy`` (fraction in [0, 1]) and the
    ``mean_score`` over that bucket. Errored rows are excluded from the buckets
    (they carry no score / correctness). Pure, never raises. Output is ordered by
    (run_id, agent_key, mode, dimension, bucket).
    """
    groups = _group_by(scored_rows, _summary_key)
    out = []
    for key in sorted(groups, key=_sort_key):
        rows = groups[key]
        meta = _group_meta(rows)
        ok_rows = [r for r in rows if _status(r) == _OK_STATUS]
        for dimension in BREAKDOWN_DIMENSIONS:
            buckets = _group_by(ok_rows, lambda r, d=dimension: _bucket(r, d))
            for bucket in sorted(buckets, key=lambda b: ("" if b is None else str(b))):
                if bucket is None:
                    continue  # rows with no value for this dimension are skipped
                brows = buckets[bucket]
                out.append({
                    "run_id": key[0],
                    "run_timestamp": meta["run_timestamp"],
                    "agent_key": key[1],
                    "agent_label": meta["agent_label"],
                    "mode": key[2],
                    "dimension": dimension,
                    "bucket": bucket,
                    "n": len(brows),
                    "accuracy": _accuracy(brows),
                    "mean_score": _mean_score(brows),
                })
    return _order(out, BREAKDOWN_COLUMNS)


# --- group summary ----------------------------------------------------------

def _summarize_group(key, rows):
    """Build one summary dict for a (run_id, agent_key, mode) group."""
    run_id, agent_key, mode = key
    meta = _group_meta(rows)

    n_questions = len(rows)
    ok_rows = [r for r in rows if _status(r) == _OK_STATUS]
    n_ok = len(ok_rows)
    n_error = n_questions - n_ok

    latencies = [_num(r.get("latency_total_s")) for r in ok_rows]
    ttfts = [_num(r.get("time_to_first_token_s")) for r in ok_rows]
    costs = [_num(r.get("estimated_cost")) for r in ok_rows]
    in_tokens = [_num(r.get("prompt_tokens")) for r in ok_rows]
    out_tokens = [_num(r.get("completion_tokens")) for r in ok_rows]
    judge_costs = [_num(r.get("judge_estimated_cost")) for r in rows]

    summary = {
        "run_id": run_id,
        "run_timestamp": meta["run_timestamp"],
        "agent_key": agent_key,
        "agent_label": meta["agent_label"],
        "mode": mode,
        "n_questions": n_questions,
        "n_ok": n_ok,
        "n_error": n_error,
        "error_rate": _ratio(n_error, n_questions),
        "accuracy": _accuracy(ok_rows),
        "mean_score": _mean_score(ok_rows),
        "score_dist_json": json.dumps(_score_dist(ok_rows)),
        "latency_p50_s": percentile(_drop_none(latencies), 0.5),
        "latency_p95_s": percentile(_drop_none(latencies), 0.95),
        "latency_max_s": _max(_drop_none(latencies)),
        "ttft_p50_s": percentile(_drop_none(ttfts), 0.5),
        "avg_cost_per_q": _mean(_drop_none(costs)),
        "total_cost": _sum(_drop_none(costs)),
        "avg_input_tokens": _mean(_drop_none(in_tokens)),
        "avg_output_tokens": _mean(_drop_none(out_tokens)),
        "needs_review_count": sum(1 for r in rows if _truthy(r.get("needs_review"))),
        "judge_total_cost": _sum(_drop_none(judge_costs)),
    }
    return _order_one(summary, SUMMARY_COLUMNS)


def _group_meta(rows):
    """Pick a representative run_timestamp and agent_label for a group."""
    run_timestamp = None
    agent_label = None
    for r in rows:
        if run_timestamp is None and not _blank(r.get("run_timestamp")):
            run_timestamp = r.get("run_timestamp")
        if agent_label is None and not _blank(r.get("agent_label")):
            agent_label = r.get("agent_label")
    return {"run_timestamp": run_timestamp, "agent_label": agent_label}


# --- per-bucket statistics --------------------------------------------------

def _accuracy(ok_rows):
    """Fraction of correct rows among scored ok rows, in [0, 1] (0.0 if empty)."""
    if not ok_rows:
        return 0.0
    n_correct = sum(1 for r in ok_rows if _truthy(r.get("correct")))
    return _ratio(n_correct, len(ok_rows))


def _mean_score(ok_rows):
    """Mean judge score over rows that carry a numeric score (0.0 if none)."""
    scores = _drop_none([_score(r) for r in ok_rows])
    return _mean(scores)


def _score_dist(ok_rows):
    """Counts of each judge score 1..5 over scored ok rows (json-friendly dict)."""
    dist = {str(b): 0 for b in _SCORE_BUCKETS}
    for r in ok_rows:
        s = _score(r)
        if s is not None and s in _SCORE_BUCKETS:
            dist[str(s)] += 1
    return dist


def _score(row):
    """Return the integer judge score 1..5, or None when absent / out of range."""
    raw = row.get("judge_score")
    n = _num(raw)
    if n is None:
        return None
    s = int(round(n))
    if s < 1 or s > 5:
        return None
    return s


# --- grouping helpers -------------------------------------------------------

def _summary_key(row):
    return (_str(row.get("run_id")), _str(row.get("agent_key")), _str(row.get("mode")))


def _bucket(row, dimension):
    value = row.get(dimension)
    if _blank(value):
        return None
    return _str(value)


def _group_by(rows, key_fn):
    """Group an iterable of dict rows by ``key_fn`` (order preserved per group)."""
    groups = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        key = key_fn(row)
        groups.setdefault(key, []).append(row)
    return groups


def _sort_key(key):
    # key is the (run_id, agent_key, mode) tuple; everything is already a string.
    return tuple("" if part is None else str(part) for part in key)


def _status(row):
    s = row.get("status")
    if _blank(s):
        # A blank status defaults to ok so a minimal raw->scored row still counts
        # as a successful run rather than silently inflating the error rate.
        return _OK_STATUS
    return _str(s).lower()


# --- numeric helpers --------------------------------------------------------

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


def _to_floats(values):
    """List of floats from an iterable, dropping None / non-numeric entries."""
    out = []
    for v in values or []:
        f = _num(v)
        if f is not None:
            out.append(f)
    return out


def _drop_none(values):
    return [v for v in values if v is not None]


def _mean(values):
    nums = _to_floats(values)
    if not nums:
        return 0.0
    return sum(nums) / len(nums)


def _sum(values):
    return sum(_to_floats(values))


def _max(values):
    nums = _to_floats(values)
    if not nums:
        return 0.0
    return max(nums)


def _ratio(part, whole):
    if not whole:
        return 0.0
    return part / float(whole)


# --- scalar coercion --------------------------------------------------------

def _blank(value):
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _str(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _truthy(value):
    """Bool-coerce a correctness / needs_review cell (bool / 0-1 / strings)."""
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        return s in ("true", "1", "yes", "y", "oui")
    return False


# --- output ordering --------------------------------------------------------

def _order_one(row, columns):
    """Return a dict with exactly ``columns`` keys, in order."""
    return {col: row.get(col) for col in columns}


def _order(rows, columns):
    return [_order_one(r, columns) for r in rows]
