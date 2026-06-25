"""Scenario step 3: judge the captured runs -> benchmark_runs_scored.

Copy-pasteable body for a Python step of the ``Run_Benchmark`` scenario in the
DSS project ``OWIsMind_LAB``. Reads ``benchmark_runs_raw`` (by default only the
latest run_id), applies the two-stage scoring per row - the deterministic
objective anchor over the COMPLETE answer, then the structured LLM judge (native
Mesh, Sonnet, with_json_output) - combines them with the deterministic
correctness rule, and writes ``benchmark_runs_scored`` (the readable detail
table).

Config read from the single ``benchmark`` project variable (run_params.py):
  - ``score_all_runs`` : true to re-judge every run_id in the raw dataset.
                         Default false (judge only the latest run_id, the common
                         case right after step_run_matrix).
  - ``judge_llm_id``   : override the judge model id. Default config.JUDGE_LLM_ID.
  - ``raw_dataset`` / ``scored_dataset`` : input / output dataset names.

Instance safety: the judge is one bounded LLM call per row over a small golden
set; agent answers are already captured, so this step makes no agent calls.
"""

import json

import dataiku
import pandas as pd

from benchmark import config, schemas, run_params
from benchmark import judge


def _get_variables():
    """Return scenario / project custom variables (never raises)."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def _latest_run_id(df):
    """Return the run_id of the most recent run (by run_timestamp, then run_id)."""
    if df.empty:
        return None
    # Require BOTH a run_id AND a run_timestamp: a row with a null timestamp would otherwise
    # sort last (na_position='last') and be wrongly selected as the latest run.
    sub = df[["run_id", "run_timestamp"]].dropna(subset=["run_id", "run_timestamp"])
    if sub.empty:
        return None
    # run_timestamp is ISO-8601, so lexical max == chronological max.
    sub = sub.sort_values(["run_timestamp", "run_id"])
    return sub.iloc[-1]["run_id"]


def _load_json(value, default):
    """Parse a JSON cell defensively; return ``default`` on any failure."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return default
    return default


def _score_row(project, row, judge_llm_id):
    """Run anchor + LLM judge + correctness for one raw row. Returns a scored dict."""
    scored = {col: row.get(col) for col in schemas.RAW_COLUMNS}

    sql_items = _load_json(row.get("generated_sql_json"), [])
    full_answer = row.get("full_answer") or ""
    expected_value = row.get("expected_value")
    expected_value_type = row.get("expected_value_type")
    question = row.get("question") or ""
    reference_answer = row.get("reference_answer") or ""
    status = row.get("status")

    # Stage 1: deterministic objective anchor over text + flattened SQL cells.
    objective_match = judge.objective_anchor(
        expected_value, expected_value_type, full_answer, sql_items,
        tolerance=config.NUMERIC_TOLERANCE,
    )

    # Stage 2: structured LLM judge. Skip the call for a failed agent run (there is
    # no answer to judge): mark the anchor as "error" so the deterministic rule
    # flags it not-correct + needs_review, and record an empty judge result.
    if status and status != "ok":
        objective_match = "error"
        judge_out = {
            "score": None,
            "verdict": None,
            "justification": "agent run did not complete (status={0})".format(status),
            "missing_facts": [],
            "hallucination": False,
            "usage": {
                "promptTokens": 0,
                "completionTokens": 0,
                "totalTokens": 0,
                "estimatedCost": 0.0,
            },
            "error": "agent status={0}".format(status),
        }
    else:
        judge_out = judge.run_llm_judge(
            project, question, reference_answer, expected_value, full_answer,
            llm_id=judge_llm_id,
        )

    final = judge.final_correctness(objective_match, judge_out)

    # The judge nests its own token usage under "usage" (mirrors extract_usage).
    usage = judge_out.get("usage") or {}
    scored["objective_match"] = objective_match
    scored["judge_score"] = judge_out.get("score")
    scored["judge_verdict"] = judge_out.get("verdict")
    scored["judge_justification"] = judge_out.get("justification")
    scored["judge_missing_facts_json"] = json.dumps(
        judge_out.get("missing_facts") or [], ensure_ascii=False
    )
    scored["judge_hallucination"] = bool(judge_out.get("hallucination"))
    scored["judge_prompt_tokens"] = usage.get("promptTokens", 0)
    scored["judge_completion_tokens"] = usage.get("completionTokens", 0)
    scored["judge_total_tokens"] = usage.get("totalTokens", 0)
    scored["judge_estimated_cost"] = usage.get("estimatedCost", 0.0)
    scored["correct"] = bool(final.get("correct"))
    scored["needs_review"] = bool(final.get("needs_review"))
    return scored


def run():
    """Judge benchmark_runs_raw and write benchmark_runs_scored."""
    cfg = run_params.resolve(_get_variables())
    score_all = cfg["score_all_runs"]
    judge_llm_id = cfg["judge_llm_id"]

    df = dataiku.Dataset(cfg["raw_dataset"]).get_dataframe()
    # astype(object) first so NaN -> None actually sticks on numeric columns
    # (an all-empty column reads as float64; None would otherwise revert to NaN).
    df = df.astype(object).where(pd.notnull(df), None)

    if not score_all:
        run_id = _latest_run_id(df)
        if run_id is not None:
            df = df[df["run_id"] == run_id]

    # The judge resolves the agent project lazily inside run_llm_judge; the project
    # handle here is the LAB project that hosts the judge LLM connection.
    project = dataiku.api_client().get_project(dataiku.default_project_key())

    scored_rows = [
        _score_row(project, row, judge_llm_id)
        for row in df.to_dict(orient="records")
    ]

    out = dataiku.Dataset(cfg["scored_dataset"])
    if scored_rows:
        frame = pd.DataFrame(
            [{col: r.get(col) for col in schemas.SCORED_COLUMNS} for r in scored_rows],
            columns=list(schemas.SCORED_COLUMNS),
        )
    else:
        frame = pd.DataFrame(columns=list(schemas.SCORED_COLUMNS))
    out.write_with_schema(frame)


run()
