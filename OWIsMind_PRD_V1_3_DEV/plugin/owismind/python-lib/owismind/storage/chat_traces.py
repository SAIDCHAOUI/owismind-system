"""Write-only persistence of raw agent traces to a Flow DATASET (no direct SQL).

One row per chat exchange whose agent run returned a footer trace: the RAW
end-of-stream run trace (the artefact the LLM Mesh agent emits at the very end of
the stream - nested spans, tool outputs, usage), serialised as JSON text and
APPENDED to an admin-selected dataset.

Why a Dataset append and NOT a direct SQL INSERT (the CONFIRMED mechanism)
--------------------------------------------------------------------------
DSS LOGS every ``SQLExecutor2`` query (the full statement text). Because SQLExecutor2 has
no server-side bind (official Python API reference), a value is ALWAYS inlined into that
text - so a direct ``INSERT INTO ... VALUES ('<huge JSON>')`` would write the entire trace
blob into a logged SQL statement. On this instance a scenario materialises those query logs
into a dataset, where an over-long SQL cell trips DSS's row-length limit ("row too long",
in-memory) - the observed warning.

``dataiku.Dataset(...).write_with_schema(...)`` does NOT go through SQLExecutor2 query
logging: the row is written by the dataset writer, so the trace blob never lands in a
logged SQL statement. This is the confirmed fix (and mirrors the production Dash app).

Dataset choice: use a SQL-TABLE-backed dataset (the observed setup; works). Avoid a
CSV/filesystem-format dataset - its OWN per-row character limit could be exceeded by a
large JSON row (``ERR_FORMAT_LINE_TOO_LARGE``). ``MAX_TRACE_BYTES`` caps the row regardless.
(Note: the SQL-text-capture chain is not described on the official CRU doc page, but it is
empirically confirmed on this instance via SQLExecutor2 query logging.)

Write-only by design
---------------------
The webapp NEVER reads these traces back (loading the raw blob per request would slow
the app): they exist purely for offline analysis in the Flow. Best-effort - a failure
here never affects the answer already on screen. When no dataset is configured, trace
storage is skipped entirely.
"""

import json
import logging
import threading
from datetime import datetime

import dataiku
import pandas as pd

from owismind.storage.sql_config import traces_dataset_name

logger = logging.getLogger(__name__)

# Hard cap on the persisted trace size (instance safety): a runaway trace must not
# write a multi-megabyte row. Real traces are tens of KB, so this is well above
# normal; beyond it, a small marker is stored instead of the blob (and logged).
MAX_TRACE_BYTES = 4_000_000

# Serialise concurrent appends: write_with_schema(append) must not be called from
# multiple Flask worker threads at once on the same dataset. Trace writes are rare
# (one per run completion) and tiny, so a single process-wide lock is cheap. This
# assumes a mono-process backend (the same assumption as the polling model).
_WRITE_LOCK = threading.Lock()

# Canonical content of one trace row. The DataFrame is written in the EXISTING
# dataset's column order (see _column_order) so an admin can create the dataset's
# columns in ANY order without tripping write_with_schema's positional schema check.
CANONICAL_COLUMNS = ["exchange_id", "trace", "created_at"]


def _column_order(dataset):
    """Return the column order to write in, matching the dataset's existing schema.

    write_with_schema aligns a DataFrame to a pre-existing SQL table BY POSITION, not
    by name. So if the admin created the dataset's columns in a different order than
    CANONICAL_COLUMNS, the write fails with "Name/Type mismatch for column N". We
    therefore read the dataset's declared schema and, when it holds exactly our three
    columns (in any order), write in THAT order so the positional write lines up.
    Falls back to CANONICAL_COLUMNS when the schema is empty/unreadable or has a
    different column set (an empty dataset's schema is then defined by the first write).
    """
    try:
        existing = [c.get("name") for c in (dataset.read_schema() or [])]
    except Exception as exc:
        logger.info(
            "save_trace - could not read dataset schema (%s); using default column order",
            exc,
        )
        existing = []
    if len(existing) == len(CANONICAL_COLUMNS) and set(existing) == set(CANONICAL_COLUMNS):
        return existing
    return list(CANONICAL_COLUMNS)


def save_trace(exchange_id, trace):
    """Append the raw end-of-stream footer trace for one exchange. Best-effort.

    ``trace`` is the raw trace object (typically a dict) the agent returned in its
    footer, or None when the run produced no footer/trace (then nothing is stored).
    It is JSON-encoded and written as one row ``(exchange_id, trace, created_at)`` to
    the configured Flow dataset via the Dataset API (append). An oversized trace is
    replaced by a small marker so a single run can never write an unbounded row.
    Skipped silently when no trace dataset is configured.
    """
    if not trace:
        logger.info("save_trace - no trace to record for exchange_id=%s", exchange_id)
        return

    dataset_name = traces_dataset_name()
    if not dataset_name:
        logger.info(
            "save_trace - no trace dataset configured; skipping exchange_id=%s",
            exchange_id,
        )
        return

    try:
        trace_json = json.dumps(trace, ensure_ascii=False, default=str)
    except (TypeError, ValueError) as exc:
        logger.warning(
            "save_trace - trace not serialisable for exchange_id=%s: %s", exchange_id, exc
        )
        return

    if len(trace_json) > MAX_TRACE_BYTES:
        logger.warning(
            "save_trace - trace too large (%d bytes) for exchange_id=%s; storing marker",
            len(trace_json),
            exchange_id,
        )
        trace_json = json.dumps(
            {"_truncated": True, "_original_bytes": len(trace_json)}, ensure_ascii=False
        )

    # One row, stable content (string/string/datetime). created_at is a naive UTC
    # timestamp for Flow-side ordering. The DataFrame is built in the dataset's own
    # column order just before the write (see _column_order), so column ordering in
    # the admin-created dataset is irrelevant.
    row = {
        "exchange_id": str(exchange_id),
        "trace": trace_json,
        "created_at": datetime.utcnow(),
    }

    logger.info(
        "save_trace - append to dataset %s exchange_id=%s trace_bytes=%d",
        dataset_name,
        exchange_id,
        len(trace_json),
    )
    # Append one row to the admin-selected dataset.
    #   - We build the DataFrame in the dataset's EXISTING column order so the
    #     positional SQL write lines up regardless of how the admin ordered the
    #     columns (otherwise write_with_schema fails with "Name/Type mismatch for
    #     column N" - the observed failure mode).
    #   - appendMode=True turns write_with_schema's default overwrite into an append
    #     (no TRUNCATE), so prior rows are preserved.
    #   - ignore_flow=True only affects RECIPE execution context; in a webapp backend
    #     it is harmless/explicit.
    # The whole write is SELF-CONTAINED best-effort: any failure (missing/incompatible
    # dataset, schema/type mismatch, writer error) is logged on ONE short line and
    # swallowed HERE, so a trace write can NEVER affect the answer already on screen -
    # independently of how the caller invokes this function.
    # MUST be validated in DSS: that rows ACCUMULATE (not overwritten) and that the
    # dataset is SQL-table-backed (NOT CSV/filesystem, which has a per-row length limit).
    try:
        with _WRITE_LOCK:
            dataset = dataiku.Dataset(dataset_name, ignore_flow=True)
            df = pd.DataFrame([row], columns=_column_order(dataset))
            dataset.spec_item["appendMode"] = True
            dataset.write_with_schema(df)
        logger.info("save_trace - appended exchange_id=%s", exchange_id)
    except Exception as exc:
        logger.warning(
            "save_trace - could not append trace for exchange_id=%s (trace skipped): %s",
            exchange_id,
            exc,
        )
