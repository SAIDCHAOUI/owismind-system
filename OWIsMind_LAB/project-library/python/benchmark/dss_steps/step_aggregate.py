"""Scenario step 4: aggregate scores -> benchmark_summary + benchmark_breakdown.

Copy-pasteable body for a Python step of the ``Run_Benchmark`` scenario in the
DSS project ``OWIsMind_LAB``. Reads ``benchmark_runs_scored`` (by default only
the latest run_id), computes the per (run x agent x mode) KPI summary and the per
dimension-bucket breakdown via the pure ``scoring`` module, and writes the two
restitution datasets the DSS dashboard sits on.

Config read from the single ``benchmark`` project variable (run_params.py):
  - ``aggregate_all_runs`` : true to aggregate every run_id present. Default false
                             (latest run_id only).
  - ``scored_dataset`` / ``summary_dataset`` / ``breakdown_dataset`` : dataset names.

Instance safety: pure aggregation maths over a small in-memory table; no DSS LLM
calls, no agent calls.
"""

import dataiku
import pandas as pd

from benchmark import schemas, run_params
from benchmark import scoring
from benchmark import registry
from benchmark.dss_steps.history_io import write_history_dataset


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
    """Aggregate benchmark_runs_scored into BENCHMARK-level summary + breakdown datasets (v2).

    By default we aggregate the BENCHMARK of the latest run (the one just judged): scoring reduces it
    to the latest attempt of each question and emits one summary row per (benchmark_id, agent, mode).
    ``aggregate_all_runs`` recomputes every benchmark present. The write merges by ``benchmark_id`` so
    re-aggregating a benchmark replaces just its block and other benchmarks are preserved.
    """
    cfg = run_params.resolve(_get_variables())
    aggregate_all = cfg["aggregate_all_runs"]

    df = dataiku.Dataset(cfg["scored_dataset"]).get_dataframe()
    # astype(object) first so NaN -> None actually sticks on numeric columns.
    df = df.astype(object).where(pd.notnull(df), None)
    scored_rows = df.to_dict(orient="records")

    if not aggregate_all:
        # Scope to the benchmark of the most recent run (its rows + every prior attempt of the same
        # benchmark, so the latest-attempt reduction sees the whole benchmark, not just this run).
        latest_run = _latest_run_id(df)
        target_benchmark = registry.benchmark_id_of_run(scored_rows, latest_run)
        if target_benchmark:
            scored_rows = [r for r in scored_rows
                           if str(r.get("benchmark_id") or "") == target_benchmark]

    summary_rows = scoring.summarize(scored_rows)
    breakdown_rows = scoring.breakdown(scored_rows)

    # Merge by benchmark_id (NOT run_id): a summary row is the benchmark's CURRENT state over all its
    # runs, so re-aggregating replaces the benchmark's block and keeps other benchmarks. These two
    # datasets are LIGHT (a few rows per benchmark), so they are NEVER capped (keep_runs=None).
    write_history_dataset(
        cfg["summary_dataset"], _to_frame(summary_rows, schemas.SUMMARY_COLUMNS),
        keep_runs=None, key="benchmark_id")
    write_history_dataset(
        cfg["breakdown_dataset"], _to_frame(breakdown_rows, schemas.BREAKDOWN_COLUMNS),
        keep_runs=None, key="benchmark_id")


run()
