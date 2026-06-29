"""DSS read/merge/write helper that ACCUMULATES benchmark run history.

Imported by the three scenario steps so a new run APPENDS its rows to the result
datasets instead of overwriting them (each row already carries run_id / run_timestamp).
DSS-only (imports dataiku / pandas), never imported by the stdlib-only unit tests; the
keep/cap decision lives in the pure ``benchmark.history`` module (which is tested).

Data-safety (mirrors the webapp promotion path): the existing history is read schema-gated
and ABORT-SAFE. A never-built dataset (its schema reads back empty, the very first run)
legitimately has no history and starts fresh. A BUILT dataset is read with a RAISING
get_dataframe so a transient read failure RAISES and aborts the step (the scenario fails
loudly) rather than overwriting the accumulated history with just the new run. A schema-read
failure is AMBIGUOUS, so it falls through to the raising read (abort-safe) - it never assumes
empty on a blip.
"""

import dataiku
import pandas as pd

from benchmark import history


def _existing_history(ds):
    """Existing rows of a result dataset for a read-modify-write, or None when never built.

    Schema-gated + abort-safe: an empty schema means the dataset was never written (first run)
    -> None. Otherwise (built, OR a schema-read that itself failed and is therefore ambiguous)
    read with a RAISING get_dataframe so a transient error aborts instead of truncating history.
    """
    schema = None
    try:
        schema = ds.read_schema()
    except Exception:
        schema = None  # ambiguous -> fall through to the raising read (never assume empty)
    if schema is not None and not schema:
        return None  # definitively never built: no prior history
    return ds.get_dataframe()  # RAISES on a transient error -> abort (no truncation)


def read_history_rows(name, columns=None):
    """Read a result dataset as a list of dicts for the run resolver. [] when never built / unreadable.

    Used by step_run_matrix to know which questions of a benchmark were already attempted (done) and
    at which attempt number. Schema-gated like ``_existing_history`` but FAIL-OPEN here (a read blip
    returns [] -> the launch falls back to running the resolved-pending set as if no prior history;
    it never aborts the run and never truncates anything, since this read does not write). Only the
    light resolver columns are needed, so pass ``columns`` to project at the source.
    """
    ds = dataiku.Dataset(name)
    try:
        schema = ds.read_schema()
    except Exception:
        schema = None
    if schema is not None and not schema:
        return []  # never built: no prior attempts
    try:
        if columns:
            df = ds.get_dataframe(columns=list(columns))
        else:
            df = ds.get_dataframe()
    except TypeError:
        try:
            df = ds.get_dataframe()
        except Exception:
            return []
    except Exception:
        return []
    if df is None or len(df) == 0:
        return []
    df = df.astype(object).where(pd.notnull(df), None)
    return df.to_dict("records")


def write_history_dataset(name, new_frame, keep_runs=None, key="run_id"):
    """Append ``new_frame`` to dataset ``name``, preserving prior blocks; idempotent per ``key``.

    Rows of any ``key`` value present in ``new_frame`` replace the matching prior rows, every other
    historical block is kept, then the new rows are appended. ``key`` is ``run_id`` for the raw /
    scored history (a re-run of the same run replaces just its rows) and ``benchmark_id`` for the v2
    benchmark-level summary / breakdown (re-aggregating a benchmark replaces just its block, keeping
    other benchmarks). When ``keep_runs`` is a positive int the accumulated history is capped to that
    many most-recent runs (instance safety; only the HEAVY raw / scored datasets pass it - summary /
    breakdown are light and keep everything; capping is always by run_id).

    Writes go through the Dataset API (write_with_schema), never raw SQL. Only ``new_frame`` is
    NaN-normalized (it is small and built from dicts already); the existing frame is concatenated
    as-is so the heavy prior history is not copied a second time in RAM during the rewrite.
    """
    ds = dataiku.Dataset(name)
    new_ids = set()
    if key in getattr(new_frame, "columns", []):
        new_ids = {v for v in new_frame[key].tolist() if v is not None}

    existing = _existing_history(ds)
    if existing is not None:
        if key in existing.columns and new_ids:
            existing = existing[~existing[key].isin(list(new_ids))]
        combined = pd.concat([existing, new_frame], ignore_index=True, sort=False)
    else:
        combined = new_frame  # first ever write: no prior history

    if keep_runs and "run_id" in getattr(combined, "columns", []):
        keep = history.runs_to_keep(combined.to_dict("records"), keep_runs)
        combined = combined[combined["run_id"].isin(list(keep))].reset_index(drop=True)

    ds.write_with_schema(combined)
