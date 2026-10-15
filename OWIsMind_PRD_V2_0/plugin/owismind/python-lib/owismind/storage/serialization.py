"""JSON serialisation helpers shared across the storage layer.

SQLExecutor2 returns pandas DataFrames whose dtypes are not directly serialisable
by Flask's ``jsonify`` (timestamps, and all-NULL columns that pandas types as
float64). These helpers normalise query results into plain, JSON-safe Python
values before they leave the backend, so every storage module shares one correct
implementation instead of duplicating it.
"""

import json

import pandas as pd


def rows_to_json_safe(df):
    """Convert a SQLExecutor2 DataFrame into JSON-serialisable records.

    Timestamps are rendered as ISO 8601 strings and any NaN/NaT becomes None, so
    ``jsonify`` emits valid JSON the frontend can consume. Returns ``[]`` for an
    empty or missing frame.
    """
    if df is None or df.empty:
        return []
    df = df.copy()
    for col in df.select_dtypes(include=["datetime64[ns]", "datetimetz"]).columns:
        df[col] = df[col].apply(lambda v: v.isoformat() if pd.notna(v) else None)
    # Replace every remaining NA (NaN/NaT) with None so the payload is valid JSON.
    # Cast to object FIRST: in a numeric column (e.g. an all-NULL TEXT column that
    # pandas typed as float64), where(..., None) would re-coerce None back to NaN,
    # which jsonify then emits as the bare token `NaN` - invalid JSON for the client.
    mask = df.notna()
    df = df.astype(object).where(mask, None)
    return df.to_dict(orient="records")


def frame_to_json_safe_matrix(df, max_cell_chars=None):
    """``(columns, rows)`` of a DataFrame as POSITIONAL lists (JSON-safe).

    Unlike ``rows_to_json_safe`` (records keyed by name) this keeps duplicate column
    names apart, which an arbitrary agent SELECT can produce. Same NA rule (NaN/NaT
    -> None) and timestamps as ISO 8601 strings; ``max_cell_chars`` optionally bounds
    every string cell.
    """
    if df is None:
        return [], []
    columns = [str(c) for c in df.columns]
    if df.empty:
        return columns, []
    mask = df.notna()
    values = df.astype(object).where(mask, None).values.tolist()
    rows = []
    for raw in values:
        row = []
        for v in raw:
            if hasattr(v, "isoformat"):
                v = v.isoformat()
            if max_cell_chars and isinstance(v, str) and len(v) > max_cell_chars:
                v = v[:max_cell_chars]
            row.append(v)
        rows.append(row)
    return columns, rows


def parse_json_list(raw):
    """Decode a JSON-encoded list cell (e.g. ``user_groups``) back to a list.

    Tolerates NULL/empty/malformed cells by returning an empty list, so a single
    bad row can never break a whole response.
    """
    if not raw:
        return []
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return []
    return decoded if isinstance(decoded, list) else []
