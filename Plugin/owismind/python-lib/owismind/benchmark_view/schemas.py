"""Scored-table column contracts + the effective-verdict rule (PURE, stdlib only).

PORTED FROM OWIsMind_LAB/project-library/python/benchmark/schemas.py - keep in sync.
Only the slice the plugin's READ side needs is copied (the column list, the light projection,
the modes, and effective_correct). The plugin never runs the judge or the scoring step; it only
reads a scored table and recomputes the consultation view-model from it.
"""

# The canonical mode names the LAB benchmark stores in the 'mode' column.
MODES = ("Smart", "Pro", "Claude")

# Heavy columns the consultation never needs (kept in the table for the LAB dashboard). The plugin
# read projects to LIGHT_COLUMNS so a cross-project SELECT never materializes ~100k-char answer/SQL
# blobs just to drop them.
_HEAVY_COLUMNS = ("full_answer", "generated_sql_json", "artifacts_json", "config_json")

# Every scored column the consultation + review consume (no heavy blobs). This is also the schema
# the agent-profile table picker validates against (schema_check.REQUIRED_COLUMNS derives from it).
LIGHT_COLUMNS = (
    "run_id", "run_timestamp", "question_id", "question", "category", "language",
    "agent_key", "agent_label", "mode", "status",
    "reference_answer", "answer_text", "expected_value", "expected_value_type", "notes",
    "n_sql", "total_rows", "latency_total_s", "time_to_first_token_s",
    "prompt_tokens", "completion_tokens", "total_tokens", "estimated_cost",
    "objective_match", "judge_score", "judge_verdict", "judge_comment",
    "judge_estimated_cost", "correct", "needs_review",
    "human_verdict", "human_correct", "human_comment", "reviewed_by", "reviewed_at",
)


def _as_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "oui", "t"):
            return True
        if s in ("false", "0", "no", "n", "non", "f", ""):
            return False
    return default


def effective_correct(row):
    """Final correctness of a scored row once a human override is applied. Pure, never raises.

    A reviewer's ``human_verdict`` of "correct" / "incorrect" WINS over the machine ``correct``
    column. Returns ``{"correct": bool, "overridden": bool, "verdict": "correct"|"incorrect"}``.
    """
    if not isinstance(row, dict):
        return {"correct": False, "overridden": False, "verdict": "incorrect"}
    hv = row.get("human_verdict")
    hv = hv.strip().lower() if isinstance(hv, str) else ""
    if hv in ("correct", "incorrect"):
        correct = (hv == "correct")
        return {"correct": correct, "overridden": True,
                "verdict": "correct" if correct else "incorrect"}
    machine = _as_bool(row.get("correct"), default=False)
    return {"correct": machine, "overridden": False,
            "verdict": "correct" if machine else "incorrect"}
