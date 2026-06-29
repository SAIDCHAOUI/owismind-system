"""Validate a candidate benchmark table's columns against what the consultation needs (PURE).

When an admin points an agent at a SQL table that is supposed to hold its benchmark, the table
must carry the columns the results page reads. ``check_columns`` compares a table's column names
(case-insensitive) against ``REQUIRED_COLUMNS`` and returns the missing ones in plain language, so
the admin sees exactly what is wrong instead of a runtime failure later.
"""

from owismind.benchmark_view import schemas

# The columns the consultation + review genuinely DEPEND on. A subset of LIGHT_COLUMNS: the keys
# read by the aggregator (verdict / accuracy / per-config / per-category / detail) and the override.
# Optional-but-nice columns (language, total_rows, token counts, time_to_first_token_s) are NOT
# required, so a leaner table still validates.
REQUIRED_COLUMNS = (
    "run_id", "run_timestamp", "question_id", "question", "category",
    "agent_key", "agent_label", "mode", "status",
    "reference_answer", "answer_text", "expected_value", "expected_value_type", "notes",
    "latency_total_s", "estimated_cost",
    "objective_match", "judge_score", "judge_verdict", "judge_comment",
    "correct", "needs_review",
    "human_verdict", "human_correct", "human_comment", "reviewed_by", "reviewed_at",
)


def check_columns(present_columns):
    """Compare a table's column names against REQUIRED_COLUMNS. Pure, never raises.

    Returns ``{"ok": bool, "missing": [names], "present_count": int}``. The comparison is
    case-insensitive (PostgreSQL folds unquoted identifiers to lower case); extra columns are fine.
    """
    have = set()
    for c in (present_columns or []):
        if isinstance(c, str) and c.strip():
            have.add(c.strip().lower())
    missing = [col for col in REQUIRED_COLUMNS if col.lower() not in have]
    return {"ok": (len(missing) == 0), "missing": missing, "present_count": len(have)}
