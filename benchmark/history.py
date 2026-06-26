"""Pure helpers for keeping benchmark RUN HISTORY (no dataiku / pandas import).

The result datasets (raw / scored / summary / breakdown) each carry a ``run_id`` +
``run_timestamp`` on every row, so they are designed to ACCUMULATE one block of rows
per run rather than be overwritten. These pure functions decide what to keep when a
new run's rows are merged into the existing history; the DSS read/merge/write wrapper
lives in ``benchmark.dss_steps.history_io`` (which imports dataiku).

Kept stdlib-only so the merge/cap logic is unit-tested without an instance.
"""


def merge_run_history(existing, new, key="run_id"):
    """Merge ``new`` rows into ``existing``, replacing any prior rows of the same run.

    Every row carries ``key`` (run_id). Existing rows whose run_id is among the new
    batch's run_ids are dropped and superseded by ``new`` (idempotent re-runs of the
    same run_id); all other historical rows are preserved. ``new`` rows are appended
    after the kept history. Pure, never raises.
    """
    new_ids = {r.get(key) for r in (new or [])}
    kept = [r for r in (existing or []) if r.get(key) not in new_ids]
    return kept + list(new or [])


def runs_to_keep(rows, keep_runs, run_key="run_id", ts_key="run_timestamp"):
    """Return the SET of run_ids to keep: the ``keep_runs`` most-recent distinct runs.

    Runs are ranked by the max ``run_timestamp`` seen for each run_id (the run_id string
    breaks ties). A falsy / non-positive / non-integer ``keep_runs``, or a cap at least as
    large as the number of runs, keeps EVERYTHING (returns all run_ids). Used to bound the
    growth of the accumulated history (instance safety) without ever dropping a recent run.
    Pure, never raises.
    """
    latest = {}
    for r in (rows or []):
        rid = r.get(run_key)
        if rid is None:
            continue
        ts = r.get(ts_key)
        ts = "" if ts is None else str(ts)
        if rid not in latest or ts > latest[rid]:
            latest[rid] = ts
    all_ids = set(latest.keys())
    try:
        n = int(keep_runs)
    except (TypeError, ValueError):
        n = 0
    if n <= 0 or n >= len(all_ids):
        return all_ids
    ordered = sorted(all_ids, key=lambda rid: (latest[rid], str(rid)), reverse=True)
    return set(ordered[:n])
