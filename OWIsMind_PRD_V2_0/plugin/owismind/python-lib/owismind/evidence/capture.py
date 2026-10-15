"""Opportunistic agent-result capture + mirrored persistence caps (trust layer).

PURE module (no dataiku / pandas import) so every bound is unit-testable without a
DSS runtime, and so ``storage.chat_v5`` can import it without an import cycle.

Three responsibilities, all deterministic and all bounded:

- ``extract_result`` - best-effort extraction of the EXACT rows a SQL tool returned,
  from the ``outputs`` dict of a ``semantic-model-query`` trace span. The exact rows
  key is NOT confirmed on this instance, so extraction is opportunistic: any shape we
  do not positively recognise yields ``None`` (absence is honest - downstream surfaces
  ``result_captured: false`` instead of inventing data).
- ``cap_result`` - MIRROR re-cap of one captured result right before persistence.
  Upstream (the orchestrator) applies the same caps independently, but the webapp
  NEVER trusts an upstream cap: everything is re-bounded here at the write point.
- ``cap_sql_list`` - bounds the whole ``generated_sql`` list (item count + global
  serialized budget) without ever dropping the ``sql``/``success``/``row_count`` core
  of any item, and never raising (persistence must not fail because of a capture).

All caps are STRUCTURAL (rows dropped, ``truncated`` flag flipped) - never a text
marker inside the JSON, which would corrupt decoding (the chat_v5 ``_bounded`` marker
must never touch this payload).
"""

import json
import logging
import math

logger = logging.getLogger(__name__)

# --- caps (frozen contract: docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md §1)
# Per-result bounds: the captured table is a PROOF EXCERPT, not a data export.
MAX_RESULT_ROWS = 200
MAX_RESULT_COLS = 50
# Any non-primitive cell (and any column name) is stringified and cut to this length.
MAX_CELL_CHARS = 256
# Serialized size of ONE captured result; beyond it trailing rows are dropped.
MAX_RESULT_JSON_CHARS = 100_000
# Newest-wins bound on the number of persisted generated_sql items.
MAX_SQL_ITEMS = 20
# Global budget for the serialized sql_list - mirrors chat_v5.MAX_PERSISTED_TEXT_CHARS
# (duplicated by value to keep this module pure / dataiku-free).
MAX_PERSISTED_TEXT_CHARS = 262_144
# Structural per-item bounds (SQL-INST-01): the sql text itself must be capped
# at the write point - anything longer is unusable by the trust layer anyway
# (sql_parse.MAX_SQL_CHARS) and would re-open the unbounded-logged-UPDATE hole
# the global budget exists to close. Truncation is flagged STRUCTURALLY
# (sql_truncated: true), never with a text marker inside the SQL itself.
MAX_ITEM_SQL_CHARS = 20_000
_MAX_TAG_CHARS = 300

# Candidate keys for the result ROWS inside a tool span's ``outputs``, probed in this
# order (first list-valued key wins). The actual key is instance-dependent.
_ROW_KEYS = ("rows", "records", "data", "result_rows", "values")
# Candidate keys for an explicit column-name list accompanying list-of-lists rows.
_COLUMN_KEYS = ("columns", "column_names", "headers")

# Core item keys that must NEVER be dropped by any cap (only ``result`` is droppable).
_CORE_ITEM_KEYS = ("sql", "success", "row_count", "sql_id", "step_index",
                   "agent_key", "source_url")


def _safe_str(value):
    """str() bounded to MAX_CELL_CHARS; never raises (hostile __str__ tolerated)."""
    try:
        return str(value)[:MAX_CELL_CHARS]
    except Exception:
        return "<unprintable>"


def _normalize_cell(value):
    """Keep JSON-safe primitives as-is; stringify (bounded) everything else.

    ``bool`` is checked before ``int`` (bool is an int subclass) so True/False are
    preserved instead of degrading to 1/0. Non-finite floats (nan/inf) are NOT valid
    JSON numbers, so they are stringified like any other non-primitive.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _safe_str(value)
    return _safe_str(value)


def _json_len(obj):
    """Serialized length used by every budget check (same dumps defaults as chat_v5)."""
    return len(json.dumps(obj, default=str))


def _fit_result_budget(result):
    """Drop trailing rows until the serialized result fits MAX_RESULT_JSON_CHARS.

    Row sizes are accumulated greedily (per-row dumps + the ", " separator), which
    slightly over-counts and therefore never overshoots the budget. Idempotent: a
    result that already fits is returned unchanged.
    """
    if _json_len(result) <= MAX_RESULT_JSON_CHARS:
        return result
    base = {"columns": result["columns"], "rows": [], "truncated": True}
    budget = MAX_RESULT_JSON_CHARS - _json_len(base)
    kept = []
    used = 0
    for row in result["rows"]:
        row_len = _json_len(row) + 2  # +2 for the ", " list separator
        if used + row_len > budget:
            break
        kept.append(row)
        used += row_len
    base["rows"] = kept
    return base


def _conform_row(cells, n_cols):
    """Normalize one row to EXACTLY n_cols cells (cut when wider, pad with None).

    Returns ``(row, was_cut)`` so the caller can flip the honest ``truncated`` flag
    when declared columns are narrower than the data.
    """
    was_cut = len(cells) > n_cols
    row = [_normalize_cell(c) for c in list(cells)[:n_cols]]
    if len(row) < n_cols:
        row = row + [None] * (n_cols - len(row))
    return row, was_cut


def extract_result(outputs):
    """Opportunistically extract ``{"columns", "rows", "truncated"}`` from tool outputs.

    Accepted shapes for the first list-valued candidate key (probed in _ROW_KEYS
    order):
      - list of lists/tuples - column names come from a separate _COLUMN_KEYS entry
        when present, else synthetic ``col_1..col_n`` (n = widest row);
      - list of dicts - columns are the FIRST dict's keys in insertion order (stable),
        later dicts are projected onto those keys.
    ANY other shape (mixed lists, scalars, no candidate key, non-dict outputs) returns
    ``None``: an honestly-absent capture, never a guess. All caps applied here are
    re-applied at the write point (``cap_result``) - never trusted downstream.
    """
    if not isinstance(outputs, dict):
        return None

    raw_rows = None
    for key in _ROW_KEYS:
        candidate = outputs.get(key)
        if isinstance(candidate, list):
            raw_rows = candidate
            break
    if raw_rows is None:
        return None

    explicit_columns = None
    for key in _COLUMN_KEYS:
        candidate = outputs.get(key)
        if isinstance(candidate, (list, tuple)) and candidate:
            explicit_columns = [_safe_str(c) for c in candidate]
            break

    truncated = False
    if len(raw_rows) > MAX_RESULT_ROWS:
        raw_rows = raw_rows[:MAX_RESULT_ROWS]
        truncated = True

    if not raw_rows:
        # Empty result set: only meaningful when the columns are explicitly declared
        # (a dict-shaped result with zero rows has unknowable columns -> no capture).
        if explicit_columns is None:
            return None
        if len(explicit_columns) > MAX_RESULT_COLS:
            explicit_columns = explicit_columns[:MAX_RESULT_COLS]
            truncated = True
        return {"columns": explicit_columns, "rows": [], "truncated": truncated}

    if all(isinstance(r, dict) for r in raw_rows):
        # list-of-dicts: columns = first dict's keys, insertion order (stable).
        source_keys = list(raw_rows[0].keys())
        if len(source_keys) > MAX_RESULT_COLS:
            source_keys = source_keys[:MAX_RESULT_COLS]
            truncated = True
        columns = [_safe_str(k) for k in source_keys]
        rows = [[_normalize_cell(r.get(k)) for k in source_keys] for r in raw_rows]
        return _fit_result_budget(
            {"columns": columns, "rows": rows, "truncated": truncated}
        )

    if all(isinstance(r, (list, tuple)) for r in raw_rows):
        if explicit_columns is not None:
            columns = explicit_columns
        else:
            width = max(len(r) for r in raw_rows)
            if width > MAX_RESULT_COLS:
                truncated = True
            columns = [
                "col_{}".format(i + 1) for i in range(min(width, MAX_RESULT_COLS))
            ]
        if len(columns) > MAX_RESULT_COLS:
            columns = columns[:MAX_RESULT_COLS]
            truncated = True
        n_cols = len(columns)
        rows = []
        for raw in raw_rows:
            row, was_cut = _conform_row(raw, n_cols)
            truncated = truncated or was_cut
            rows.append(row)
        return _fit_result_budget(
            {"columns": columns, "rows": rows, "truncated": truncated}
        )

    # Mixed / unrecognised row shapes: capture honestly absent.
    return None


def cap_result(result):
    """MIRROR re-cap of one captured result at the write point. Returns dict or None.

    NEVER trusts an upstream cap: rows/cols/cell bounds and the serialized-size budget
    are all re-applied here even when the input claims to be capped already. A result
    that is not positively ``{"columns": list, "rows": list-of-lists}`` is dropped
    (``None``) - a malformed capture must never reach storage.
    """
    if not isinstance(result, dict):
        return None
    columns = result.get("columns")
    rows = result.get("rows")
    if not isinstance(columns, (list, tuple)) or not isinstance(rows, (list, tuple)):
        return None

    truncated = bool(result.get("truncated"))
    columns = list(columns)
    if len(columns) > MAX_RESULT_COLS:
        columns = columns[:MAX_RESULT_COLS]
        truncated = True
    columns = [_safe_str(c) for c in columns]
    n_cols = len(columns)

    rows = list(rows)
    if len(rows) > MAX_RESULT_ROWS:
        rows = rows[:MAX_RESULT_ROWS]
        truncated = True

    out_rows = []
    for raw in rows:
        if not isinstance(raw, (list, tuple)):
            return None
        row, was_cut = _conform_row(raw, n_cols)
        truncated = truncated or was_cut
        out_rows.append(row)

    return _fit_result_budget(
        {"columns": columns, "rows": out_rows, "truncated": truncated}
    )


def _strip_results_fallback(items):
    """Last-resort projection used if cap_sql_list itself fails: core keys only."""
    try:
        projected = []
        for item in items:
            if isinstance(item, dict):
                projected.append(
                    {k: item.get(k) for k in _CORE_ITEM_KEYS if k in item}
                )
        return projected[-MAX_SQL_ITEMS:]
    except Exception:
        return []


def cap_sql_list(items):
    """Bound a whole generated_sql list right before persistence. NEVER raises.

    In order:
      1. each item's ``result`` is re-capped via ``cap_result`` (mirror - the upstream
         cap is never trusted); an uncappable/absent result loses its key (honest);
         legacy items without ``result`` pass through byte-identical;
      2. the list is bounded to the NEWEST ``MAX_SQL_ITEMS`` items (oldest dropped);
      3. the serialized list is fitted under ``MAX_PERSISTED_TEXT_CHARS`` by removing
         ``result`` from the OLDEST items first, preserving the LAST successful item's
         result for as long as possible (it is the proof the trust layer shows);
         ``sql``/``success``/``row_count`` (and correlation tags) are NEVER removed.

    Idempotent: cap_sql_list(cap_sql_list(x)) == cap_sql_list(x).
    """
    try:
        if not isinstance(items, list):
            return []
        capped = []
        for item in items:
            if not isinstance(item, dict):
                continue  # undecodable entry: structural drop, never a crash
            out = dict(item)  # shallow copy - the caller's list is never mutated
            # Per-item structural bounds: sql text + correlation tags (the only
            # unbounded string fields an upstream source could inflate).
            sql = out.get("sql")
            if isinstance(sql, str) and len(sql) > MAX_ITEM_SQL_CHARS:
                out["sql"] = sql[:MAX_ITEM_SQL_CHARS]
                out["sql_truncated"] = True
            for tag in ("sql_id", "step_index", "agent_key", "source_url"):
                tv = out.get(tag)
                if isinstance(tv, str) and len(tv) > _MAX_TAG_CHARS:
                    out[tag] = tv[:_MAX_TAG_CHARS]
            if "result" in out:
                fitted = cap_result(out.get("result"))
                if fitted is None:
                    out.pop("result", None)
                else:
                    out["result"] = fitted
            capped.append(out)

        if len(capped) > MAX_SQL_ITEMS:
            capped = capped[-MAX_SQL_ITEMS:]

        if _json_len(capped) <= MAX_PERSISTED_TEXT_CHARS:
            return capped

        # Over budget: shed results oldest-first. The LAST successful item's result is
        # removed only as the very last resort (priority preservation, frozen contract).
        protected = None
        for i in range(len(capped) - 1, -1, -1):
            if capped[i].get("success") and "result" in capped[i]:
                protected = i
                break
        removal_order = [
            i for i in range(len(capped)) if i != protected and "result" in capped[i]
        ]
        if protected is not None:
            removal_order.append(protected)
        for i in removal_order:
            capped[i].pop("result", None)
            if _json_len(capped) <= MAX_PERSISTED_TEXT_CHARS:
                return capped
        # Still over budget after every result is shed (sql texts alone exceed
        # it, theoretically possible up to 20 x 20k chars): drop the OLDEST
        # items until the list fits - kept items keep sql/success/row_count
        # whole, and the budget guarantee holds (SQL-INST-01).
        while len(capped) > 1 and _json_len(capped) > MAX_PERSISTED_TEXT_CHARS:
            capped.pop(0)
        return capped
    except Exception:
        logger.exception("cap_sql_list - unexpected failure; persisting without results")
        return _strip_results_fallback(items)
