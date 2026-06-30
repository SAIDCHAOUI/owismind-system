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
from benchmark import config
from benchmark.agent_capture import (
    MAX_RESULT_ROWS,
    MAX_RESULT_COLS,
    MAX_CELL_CHARS,
    MAX_SQL_ITEMS,
    MAX_ITEM_SQL_CHARS,
)

# --- enum tuples (frozen vocabulary shared across the package) --------------
# Single source of truth: the canonical mode names live in config (Smart / Pro / Claude),
# which is what is actually written to the 'mode' column. Re-export rather than duplicate, so
# a future membership check against schemas.MODES matches the real stored values.
MODES = config.MODES
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
    "agent_key",             # nullable: the LOGICAL agent this question tests (membership tag)
    # --- reference SQL / tool (v2): a soft signal for the judge + training data ----------
    # Nullable. NOT scored as a hard metric: stored, displayed beside the agent's ACTUAL
    # generated SQL / tool, and passed to the judge as a non-binding hint (the assistant may
    # legitimately use a different but equally valid query / tool). See judge.build_judge_prompt.
    "expected_sql",          # nullable: a reference SQL that could answer the question
    "expected_tool",         # nullable: a reference tool key (e.g. show_chart / show_table / none)
)

# Columns that must be present and non-empty on every golden row.
_REQUIRED_GOLDEN = (
    "question_id",
    "question",
    "reference_answer",
)

# --- benchmark_runs_raw (section 4) -----------------------------------------
# One row per (run_id, question_id, agent_key, mode): the captured run + metrics. v2 adds the
# benchmark dimension (benchmark_id / benchmark_name / attempt_no) so runs accumulate into a named,
# per-agent benchmark; plus the denormalized reference SQL / tool and the agent's actual tools used.
RAW_COLUMNS = (
    "run_id",
    "run_timestamp",
    "config_json",           # snapshot of the run config (json string)
    # --- benchmark dimension (v2): the named, per-agent benchmark this run belongs to ---------
    "benchmark_id",          # the benchmark container id (uuid hex); blank on legacy rows
    "benchmark_name",        # the benchmark's human label
    "attempt_no",            # 1-based attempt index per (benchmark_id, question_id, agent_key, mode)
    "question_id",
    "question",
    "category",
    "language",
    "reference_answer",
    "expected_value",
    "expected_value_type",
    "notes",                 # human strictness note (governs the judge's numeric exactness)
    "expected_sql",          # reference SQL (soft judge signal + display), denormalized from golden
    "expected_tool",         # reference tool key (soft judge signal + display)
    "agent_key",
    "agent_label",
    "project_key",
    "agent_id",
    "agent_key_tag",         # the golden agent tag carried for display/breakdown (logical key)
    "mode",
    "status",                # ok / error / timeout
    "error_type",
    "error_message",
    "answer_text",           # final assistant text only
    "full_answer",           # text + serialized SQL tables + artifacts (judge input)
    "generated_sql_json",    # json of the sql_items list (proof / debug)
    "artifacts_json",        # json of the artifacts list
    "actual_tools",          # comma list of artifact kinds the agent actually used (e.g. "chart,table")
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
    "judge_comment",         # concise one-line reason for the decision (shown as a column)
    "judge_justification",
    "judge_missing_facts_json",
    "judge_hallucination",   # boolean
    "judge_prompt_tokens",
    "judge_completion_tokens",
    "judge_total_tokens",
    "judge_estimated_cost",
    "correct",               # boolean (machine correctness rule, pre-override)
    "needs_review",          # boolean
    # --- human-in-the-loop override (survives re-runs: scored accumulates by run_id) -----
    "human_verdict",         # "" / correct / incorrect (a reviewer's decision)
    "human_correct",         # boolean nullable (machine mirror of human_verdict)
    "human_comment",         # the reviewer's free note
    "reviewed_by",           # reviewer user_id
    "reviewed_at",           # ISO timestamp of the review
)

# --- benchmark_summary (section 7) - one row per (benchmark_id, agent_key, mode) ----
# v2: a summary row is BENCHMARK-level (over the LATEST attempt of every question in the benchmark),
# not per single run. ``last_run_*`` + ``n_runs`` describe the runs that built the benchmark.
SUMMARY_COLUMNS = (
    "benchmark_id",
    "benchmark_name",
    "agent_key",
    "agent_label",
    "mode",
    "n_questions",
    "n_ok",
    "n_error",
    "error_rate",
    "accuracy",              # % correct among scored questions (latest attempt each)
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
    "last_run_id",           # most recent run that contributed to this benchmark
    "last_run_timestamp",
    "n_runs",                # distinct runs that contributed to this benchmark
)

# --- benchmark_breakdown (section 7) - one row per dimension bucket -----------
BREAKDOWN_COLUMNS = (
    "benchmark_id",
    "benchmark_name",
    "last_run_timestamp",
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


def effective_correct(row):
    """Final correctness of a scored row once a human override is applied. Pure, never raises.

    A reviewer's ``human_verdict`` of "correct" / "incorrect" WINS over the machine ``correct``
    column (the override is the human-in-the-loop decision). Any other / blank human_verdict
    leaves the machine verdict in place. Returns
    ``{"correct": bool, "overridden": bool, "verdict": "correct"|"incorrect"}``.
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
