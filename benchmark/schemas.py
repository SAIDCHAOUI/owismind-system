"""Dataset schemas + golden-row validation for the benchmark Flow (PURE).

Stdlib only, no dataiku / pandas. Holds the canonical column lists for every
benchmark dataset (golden_questions, benchmark_runs_raw, benchmark_runs_scored,
benchmark_summary, benchmark_breakdown), the enum tuples, and the golden-row
validator / normalizer. The DSS steps build managed datasets whose schemas map
later onto SQL ``benchmark_*_v1`` tables read by the webapp.

Design contract: docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md
sections 5 (golden schema), 7 (summary / breakdown columns).
"""

# Caps mirrored from agent_capture (single source of truth: those values come
# from the webapp evidence/capture.py). Re-exported here so dependent modules can
# read them from the schema layer too.
from benchmark.agent_capture import (
    MAX_RESULT_ROWS,
    MAX_RESULT_COLS,
    MAX_CELL_CHARS,
    MAX_SQL_ITEMS,
    MAX_ITEM_SQL_CHARS,
)

# --- enum tuples (frozen vocabulary shared across the package) --------------
MODES = ("eco", "medium", "high")
EXPECTED_VALUE_TYPES = ("numeric", "currency", "date", "string", "list")
LANGUAGES = ("fr", "en")

# --- golden_questions (section 5) -------------------------------------------
# The human-authored / Excel-fed golden set, kept deliberately lean: the
# question, the human-validated true answer, and (when a crisp fact exists) the
# exact value to anchor on. ``question_id`` is the stable key.
GOLDEN_COLUMNS = (
    "question_id",
    "question",
    "reference_answer",      # the human-validated true answer
    "expected_value",        # nullable: the crisp fact/number for the objective anchor
    "expected_value_type",   # nullable enum (EXPECTED_VALUE_TYPES), required iff expected_value set
    "category",              # nullable: theme for the breakdown (revenus, tickets, ...)
    "language",              # enum (LANGUAGES), default 'fr'
    "active",                # boolean, default True
    "notes",                 # nullable: free human note
)

# Columns that must be present and non-empty on every golden row.
_REQUIRED_GOLDEN = (
    "question_id",
    "question",
    "reference_answer",
)

# --- benchmark_runs_raw (section 4) -----------------------------------------
# One row per (run_id, question_id, agent_key, mode): the captured run + metrics.
RAW_COLUMNS = (
    "run_id",
    "run_timestamp",
    "config_json",           # snapshot of the run config (json string)
    "question_id",
    "question",
    "category",
    "language",
    "reference_answer",
    "expected_value",
    "expected_value_type",
    "agent_key",
    "agent_label",
    "project_key",
    "agent_id",
    "mode",
    "status",                # ok / error / timeout
    "error_type",
    "error_message",
    "answer_text",           # final assistant text only
    "full_answer",           # text + serialized SQL tables + artifacts (judge input)
    "generated_sql_json",    # json of the sql_items list (proof / debug)
    "artifacts_json",        # json of the artifacts list
    "n_sql",
    "total_rows",
    "latency_total_s",
    "time_to_first_token_s",
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "estimated_cost",
)

# --- benchmark_runs_scored (section 6) - the readable detail table -----------
SCORED_COLUMNS = RAW_COLUMNS + (
    "objective_match",       # hit / miss / n/a
    "judge_score",           # 1..5
    "judge_verdict",         # correct / incorrect
    "judge_justification",
    "judge_missing_facts_json",
    "judge_hallucination",   # boolean
    "judge_prompt_tokens",
    "judge_completion_tokens",
    "judge_total_tokens",
    "judge_estimated_cost",
    "correct",               # boolean (final correctness rule)
    "needs_review",          # boolean
)

# --- benchmark_summary (section 7) - one row per (run_id, agent_key, mode) ----
SUMMARY_COLUMNS = (
    "run_id",
    "run_timestamp",
    "agent_key",
    "agent_label",
    "mode",
    "n_questions",
    "n_ok",
    "n_error",
    "error_rate",
    "accuracy",              # % correct among scored questions
    "mean_score",
    "score_dist_json",       # json of the 1..5 counts
    "latency_p50_s",
    "latency_p95_s",
    "latency_max_s",
    "ttft_p50_s",
    "avg_cost_per_q",
    "total_cost",
    "avg_input_tokens",
    "avg_output_tokens",
    "needs_review_count",
    "judge_total_cost",
)

# --- benchmark_breakdown (section 7) - one row per dimension bucket -----------
BREAKDOWN_COLUMNS = (
    "run_id",
    "run_timestamp",
    "agent_key",
    "agent_label",
    "mode",
    "dimension",             # category (the one breakdown axis kept)
    "bucket",
    "n",
    "accuracy",
    "mean_score",
)

# Dimensions broken down in benchmark_breakdown (must exist as golden columns).
BREAKDOWN_DIMENSIONS = ("category",)


def _is_blank(value):
    """True when a cell is missing, a float NaN (pandas empty), or a blank string."""
    if value is None:
        return True
    if isinstance(value, float) and value != value:  # NaN
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _as_bool(value, default=True):
    """Coerce a cell (bool / 0-1 / common truthy-falsey strings) to bool."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "oui"):
            return True
        if s in ("false", "0", "no", "n", "non"):
            return False
    return default


def validate_golden_row(row):
    """Validate one golden_questions row against the canonical schema.

    Checks: required fields present and non-blank (question_id, question,
    reference_answer); ``language`` and ``expected_value_type`` valid when
    provided. When ``expected_value`` is provided, ``expected_value_type`` must be
    too (the objective anchor needs the type to normalize).

    Returns ``(ok: bool, errors: list[str])``. Pure, never raises.
    """
    errors = []
    if not isinstance(row, dict):
        return False, ["row is not a dict"]

    for field in _REQUIRED_GOLDEN:
        if _is_blank(row.get(field)):
            errors.append("missing required field: {0}".format(field))

    language = row.get("language")
    if not _is_blank(language) and language not in LANGUAGES:
        errors.append("invalid language: {0!r}".format(language))

    evt = row.get("expected_value_type")
    if not _is_blank(evt) and evt not in EXPECTED_VALUE_TYPES:
        errors.append("invalid expected_value_type: {0!r}".format(evt))

    if not _is_blank(row.get("expected_value")) and _is_blank(evt):
        errors.append("expected_value set without expected_value_type")

    return (len(errors) == 0), errors


def normalize_golden_row(row):
    """Return a normalized copy of a golden row (trim, defaults).

    String fields are trimmed; ``active`` defaults to True; ``language`` defaults
    to 'fr'; blank nullable fields become None. Does NOT validate (call
    ``validate_golden_row`` separately). Pure, never raises.
    """
    if not isinstance(row, dict):
        return {}
    out = {}
    for col in GOLDEN_COLUMNS:
        value = row.get(col)
        if isinstance(value, float) and value != value:  # pandas NaN -> None
            value = None
        elif isinstance(value, str):
            value = value.strip()
            if value == "":
                value = None
        out[col] = value

    if out.get("language") is None:
        out["language"] = "fr"
    out["active"] = _as_bool(row.get("active"), default=True)
    return out
