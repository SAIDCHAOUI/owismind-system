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


def write_history_dataset(name, new_frame, keep_runs=None):
    """Append ``new_frame`` to dataset ``name``, preserving prior runs; idempotent per run.

    Rows of any run_id present in ``new_frame`` replace the matching prior rows (so a re-run of
    judge/aggregate for the same run is idempotent), every other historical run is kept, then the
    new rows are appended. When ``keep_runs`` is a positive int, the accumulated history is capped
    to that many most-recent runs (instance safety; applied by the caller only to the HEAVY raw /
    scored datasets - summary / breakdown are light and keep every run).

    Writes go through the Dataset API (write_with_schema), never raw SQL. Only ``new_frame`` is
    NaN-normalized (it is small and built from dicts already); the existing frame is concatenated
    as-is so the heavy prior history is not copied a second time in RAM during the rewrite.
    """
    ds = dataiku.Dataset(name)
    new_ids = set()
    if "run_id" in getattr(new_frame, "columns", []):
        new_ids = {v for v in new_frame["run_id"].tolist() if v is not None}

    existing = _existing_history(ds)
    if existing is not None:
        if "run_id" in existing.columns and new_ids:
            existing = existing[~existing["run_id"].isin(list(new_ids))]
        combined = pd.concat([existing, new_frame], ignore_index=True, sort=False)
    else:
        combined = new_frame  # first ever write: no prior history

    if keep_runs and "run_id" in getattr(combined, "columns", []):
        keep = history.runs_to_keep(combined.to_dict("records"), keep_runs)
        combined = combined[combined["run_id"].isin(list(keep))].reset_index(drop=True)

    ds.write_with_schema(combined)
