"""Scenario step 4: aggregate scores -> benchmark_summary + benchmark_breakdown.

Copy-pasteable body for a Python step of the ``Run_Benchmark`` scenario in the
DSS project ``OWIsMind_LAB``. Reads ``benchmark_runs_scored`` (by default only
the latest run_id), computes the per (run x agent x mode) KPI summary and the per
dimension-bucket breakdown via the pure ``scoring`` module, and writes the two
restitution datasets the DSS dashboard sits on.

Scenario variables read (optional):
  - ``bench_aggregate_all_runs`` : "true" to aggregate every run_id present.
                                   Default false (latest run_id only).

Input dataset : benchmark_runs_scored
Output datasets: benchmark_summary, benchmark_breakdown

Instance safety: pure aggregation maths over a small in-memory table; no DSS LLM
calls, no agent calls.
"""

import dataiku
import pandas as pd

from benchmark import schemas
from benchmark import scoring


SCORED_DATASET = "benchmark_runs_scored"
SUMMARY_DATASET = "benchmark_summary"
BREAKDOWN_DATASET = "benchmark_breakdown"


def _get_variables():
    """Return scenario / project custom variables (never raises)."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def _as_bool(value):
    """Coerce a string-ish scenario variable to bool."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("true", "1", "yes", "y", "oui")
    return bool(value)


def _latest_run_id(df):
    """Return the run_id of the most recent run (by run_timestamp, then run_id)."""
    if df.empty:
        return None
    sub = df[["run_id", "run_timestamp"]].dropna(subset=["run_id"])
    if sub.empty:
        return None
    sub = sub.sort_values(["run_timestamp", "run_id"])
    return sub.iloc[-1]["run_id"]


def _to_frame(rows, columns):
    """Build a DataFrame with exactly ``columns`` (missing keys -> None)."""
    if rows:
        return pd.DataFrame(
            [{col: r.get(col) for col in columns} for r in rows],
            columns=list(columns),
        )
    return pd.DataFrame(columns=list(columns))


def run():
    """Aggregate benchmark_runs_scored into summary + breakdown datasets."""
    variables = _get_variables()
    aggregate_all = _as_bool(variables.get("bench_aggregate_all_runs"))

    df = dataiku.Dataset(SCORED_DATASET).get_dataframe()
    df = df.where(pd.notnull(df), None)

    if not aggregate_all:
        run_id = _latest_run_id(df)
        if run_id is not None:
            df = df[df["run_id"] == run_id]

    scored_rows = df.to_dict(orient="records")

    summary_rows = scoring.summarize(scored_rows)
    breakdown_rows = scoring.breakdown(scored_rows)

    dataiku.Dataset(SUMMARY_DATASET).write_with_schema(
        _to_frame(summary_rows, schemas.SUMMARY_COLUMNS)
    )
    dataiku.Dataset(BREAKDOWN_DATASET).write_with_schema(
        _to_frame(breakdown_rows, schemas.BREAKDOWN_COLUMNS)
    )


run()
