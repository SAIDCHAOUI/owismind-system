"""Footer-trace capture: rebuild the COMPLETE agent answer from a streamed run.

This is the keystone of the benchmark. The intern harness kept only ``.text`` and
threw away the SQL, the result rows and the artifacts, so a question whose answer
lives in a table was scored blind. Here we walk the run footer the way the
production webapp does and rebuild the full answer (final text + serialized SQL
result tables + a short artifacts summary). That full string is the operational
definition of "the agent answer" handed to the judge.

PURE module: it operates on plain dict / list footer traces and event lists. No
``dataiku`` and no ``pandas`` import, at top level or anywhere - the package runs
as a project library in a DSS project where the webapp python-lib is NOT on the
path, and the NO INSTALL test environment has the stdlib only.

Faithful reimplementation (parity verified by tests on synthetic fixtures shaped
like the real DSS footer) of:
  - Plugin/owismind/python-lib/owismind/agents/streaming.py
    (_find_generated_sql, _find_usage_metadata, _sum_usage_metadata, the
    _SQL_TOOL_NAME / _MAX_TRACE_DEPTH constants, the ARTIFACT event shape)
  - Plugin/owismind/python-lib/owismind/evidence/capture.py
    (extract_result, cap_result, the MAX_RESULT_* caps)
We copy that logic instead of importing it because the benchmark package must be
standalone (a future webapp refactor could delegate to this module - not required
here, see the design spec section 3).
"""

import json
import math

# --- caps (mirrored by value from evidence/capture.py - this module is standalone)
# Per-result bounds: the captured table is a PROOF EXCERPT, not a data export.
MAX_RESULT_ROWS = 200
MAX_RESULT_COLS = 50
# Any non-primitive cell (and any column name) is stringified and cut to this length.
MAX_CELL_CHARS = 256
# Serialized size of ONE captured result; beyond it trailing rows are dropped.
MAX_RESULT_JSON_CHARS = 100_000
# Newest-wins bound on the number of captured generated_sql items.
MAX_SQL_ITEMS = 20
# Per-item structural bound on the SQL text itself.
MAX_ITEM_SQL_CHARS = 20_000

# Defensive recursion bound for walking the footer trace (mirrors streaming.py).
# Real traces nest a handful of levels; 200 is far above any legitimate shape.
_MAX_TRACE_DEPTH = 200

# The tool whose output holds a generated SQL query (semantic-model based agents).
_SQL_TOOL_NAME = "semantic-model-query"

# Candidate keys for the result ROWS inside a tool span's ``outputs`` (first
# list-valued key wins). The actual key is instance-dependent.
_ROW_KEYS = ("rows", "records", "data", "result_rows", "values")
# Candidate keys for an explicit column-name list accompanying list-of-lists rows.
_COLUMN_KEYS = ("columns", "column_names", "headers")

# ARTIFACT event shape (mirror of streaming.py _normalized_artifact_event).
_ARTIFACT_KIND = "ARTIFACT"
_ARTIFACT_CHART_TYPES = ("line", "bar", "pie")

# Readable serialization bounds for assemble_full_answer (judge input must be
# bounded but rich enough to carry the answer that lives in a table).
_FULL_ANSWER_MAX_TABLE_ROWS = 50
_FULL_ANSWER_CELL_CHARS = 80


# ---------------------------------------------------------------------------
# Result extraction (mirror of evidence/capture.py extract_result)
# ---------------------------------------------------------------------------
def _safe_str(value, limit=MAX_CELL_CHARS):
    """str() bounded to ``limit``; never raises (hostile __str__ tolerated)."""
    try:
        return str(value)[:limit]
    except Exception:
        return "<unprintable>"


def _normalize_cell(value):
    """Keep JSON-safe primitives as-is; stringify (bounded) everything else.

    ``bool`` is checked before ``int`` (bool is an int subclass) so True/False are
    preserved instead of degrading to 1/0. Non-finite floats (nan/inf) are NOT
    valid JSON numbers, so they are stringified like any other non-primitive.
    """
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else _safe_str(value)
    return _safe_str(value)


def _json_len(obj):
    """Serialized length used by the per-result budget check."""
    return len(json.dumps(obj, default=str))


def _fit_result_budget(result):
    """Drop trailing rows until the serialized result fits MAX_RESULT_JSON_CHARS."""
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
      - list of dicts - columns are the FIRST dict's keys in insertion order,
        later dicts projected onto those keys.
    ANY other shape returns ``None`` (honestly-absent capture, never a guess). All
    caps applied here mirror the write-point caps of the webapp.
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
        # Empty result set: only meaningful when columns are explicitly declared
        # (a dict-shaped result with zero rows has unknowable columns).
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


# ---------------------------------------------------------------------------
# Footer walk: generated SQL (mirror of streaming.py _find_generated_sql)
# ---------------------------------------------------------------------------
def _walk_generated_sql(obj, _depth=0):
    """Collect ``{success, row_count, sql[, result]}`` per SQL-tool output in a trace.

    Walks the (possibly deeply nested) trace looking for ``semantic-model-query``
    tool outputs that carry a generated SQL string. ``result`` (the captured rows)
    is OPTIONAL - absent when nothing recognisable is found (honest no-capture).
    """
    out = []
    if _depth > _MAX_TRACE_DEPTH:
        return out
    if isinstance(obj, dict):
        outputs = obj.get("outputs", {}) or {}
        if obj.get("name") == _SQL_TOOL_NAME and isinstance(outputs, dict):
            sql = outputs.get("sql")
            if sql:
                entry = {
                    "sql": sql,
                    "success": outputs.get("success"),
                    "row_count": outputs.get("row_count"),
                }
                result = extract_result(outputs)
                if result is not None:
                    entry["result"] = result
                out.append(entry)
        for value in obj.values():
            out.extend(_walk_generated_sql(value, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            out.extend(_walk_generated_sql(item, _depth + 1))
    return out


def _normalize_sql_item(entry):
    """Project one walked entry onto the frozen public item shape with bounds.

    Item shape: ``{"sql": str, "success": bool, "row_count": int,
    "result": {"columns": [...], "rows": [...]} | None}``. ``success`` is coerced
    to bool, ``row_count`` to int (0 when absent / unparseable), ``sql`` capped.
    """
    sql = entry.get("sql") or ""
    if isinstance(sql, str) and len(sql) > MAX_ITEM_SQL_CHARS:
        sql = sql[:MAX_ITEM_SQL_CHARS]
    success = entry.get("success")
    success = bool(success) if success is not None else False
    row_count = entry.get("row_count")
    try:
        row_count = int(row_count) if row_count is not None else 0
    except (TypeError, ValueError):
        row_count = 0
    result = entry.get("result")
    if isinstance(result, dict):
        # Keep only the public {columns, rows} surface for the item contract.
        result = {
            "columns": result.get("columns") or [],
            "rows": result.get("rows") or [],
        }
    else:
        result = None
    return {
        "sql": _safe_str(sql, MAX_ITEM_SQL_CHARS),
        "success": success,
        "row_count": row_count,
        "result": result,
    }


def extract_generated_sql(footer_trace):
    """Return the list of generated-SQL items found in a footer trace.

    Mirrors the webapp footer walk: finds every ``semantic-model-query`` tool
    output, keeps the SQL + success + row_count + (best-effort) result rows.

    Returns ``list[dict]``, each:
        {
          "sql": str,
          "success": bool,
          "row_count": int,
          "result": {"columns": list[str], "rows": list[list]} | None,
        }
    Bounded NEWEST-WINS to MAX_SQL_ITEMS (the last items in trace order are kept,
    mirroring the webapp's newest-wins persistence cap). Best-effort and never
    raises: an unwalkable trace yields ``[]``.
    """
    try:
        walked = _walk_generated_sql(footer_trace)
    except Exception:
        return []
    items = [_normalize_sql_item(e) for e in walked]
    if len(items) > MAX_SQL_ITEMS:
        items = items[-MAX_SQL_ITEMS:]  # newest wins
    return items


# ---------------------------------------------------------------------------
# Footer walk: usage metadata (mirror of streaming.py _find/_sum_usage_metadata)
# ---------------------------------------------------------------------------
def _walk_usage_metadata(obj, _depth=0):
    """Collect every ``usageMetadata`` dict nested anywhere inside the trace."""
    found = []
    if _depth > _MAX_TRACE_DEPTH:
        return found
    if isinstance(obj, dict):
        if isinstance(obj.get("usageMetadata"), dict):
            found.append(obj["usageMetadata"])
        for value in obj.values():
            found.extend(_walk_usage_metadata(value, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_walk_usage_metadata(item, _depth + 1))
    return found


def extract_usage(footer_trace):
    """Sum every ``usageMetadata`` dict in the footer trace into one totals dict.

    Returns:
        {
          "promptTokens": int,
          "completionTokens": int,
          "totalTokens": int,
          "estimatedCost": float,
        }
    Missing / null fields count as zero. Best-effort and never raises.
    """
    total = {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "estimatedCost": 0.0,
    }
    try:
        usages = _walk_usage_metadata(footer_trace)
    except Exception:
        return total
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        total["promptTokens"] += usage.get("promptTokens", 0) or 0
        total["completionTokens"] += usage.get("completionTokens", 0) or 0
        total["totalTokens"] += usage.get("totalTokens", 0) or 0
        total["estimatedCost"] += usage.get("estimatedCost", 0.0) or 0.0
    return total


# ---------------------------------------------------------------------------
# Artifacts (mirror of streaming.py _normalized_artifact_event, best-effort)
# ---------------------------------------------------------------------------
def _normalize_artifact(event_data):
    """Build one normalized artifact dict from an ARTIFACT eventData, or None.

    Strict-ish shape: kind in {chart, table, kpi}, bounded title; a chart carries
    a {type, x, y[]} block, a KPI a {value[,label,delta,delta_pct]} block. Only
    the SPEC travels (the data is the captured SQL result). Pure, never raises.
    """
    if not isinstance(event_data, dict):
        return None
    kind = event_data.get("kind")
    if kind not in ("chart", "table", "kpi"):
        return None
    out = {"kind": kind, "title": str(event_data.get("title") or "")[:200]}
    if kind == "chart":
        chart = event_data.get("chart")
        if not isinstance(chart, dict):
            return None
        ctype = chart.get("type")
        x = chart.get("x")
        y = chart.get("y")
        if ctype not in _ARTIFACT_CHART_TYPES or not isinstance(x, str):
            return None
        if isinstance(y, str):
            y = [y]
        if not isinstance(y, list):
            return None
        y = [str(c)[:128] for c in y if isinstance(c, str) and c][:8]
        if not y:
            return None
        out["chart"] = {"type": ctype, "x": x[:128], "y": y}
    elif kind == "kpi":
        kpi = event_data.get("kpi")
        if not isinstance(kpi, dict) or not isinstance(kpi.get("value"), str):
            return None
        kpi_out = {"label": str(kpi.get("label") or "")[:120],
                   "value": kpi["value"][:128]}
        for key in ("delta", "delta_pct"):
            v = kpi.get(key)
            if isinstance(v, str) and v:
                kpi_out[key] = v[:128]
        out["kpi"] = kpi_out
    return out


def extract_artifacts(events):
    """Return the list of artifact specs found in the run's normalized events.

    ``events`` is the list of normalized stream events (each a dict). An artifact
    is recognised either as a normalized ``{"type": "artifact", ...}`` event or as
    a raw ``ARTIFACT`` event carrying ``eventData``. Best-effort: returns ``[]``
    when nothing recognisable is present. Never raises.
    """
    out = []
    if not isinstance(events, list):
        return out
    for ev in events:
        if not isinstance(ev, dict):
            continue
        # Normalized artifact event (already shaped by a streaming layer).
        if ev.get("type") == "artifact" and ev.get("kind") in ("chart", "table", "kpi"):
            data = {k: ev.get(k) for k in ("kind", "title", "chart", "kpi")}
            norm = _normalize_artifact(data)
            if norm is not None:
                out.append(norm)
            continue
        # Raw ARTIFACT lifecycle event carrying eventData.
        if ev.get("eventKind") == _ARTIFACT_KIND:
            norm = _normalize_artifact(ev.get("eventData"))
            if norm is not None:
                out.append(norm)
    return out


# ---------------------------------------------------------------------------
# Flatten + assemble: the single string the judge sees
# ---------------------------------------------------------------------------
def flatten_result_cells(sql_items):
    """Return every result cell of every SQL item, stringified, as a flat list.

    Used by the objective anchor (does the expected value appear anywhere in the
    captured data?) and by ``assemble_full_answer``. Column headers are NOT
    included (they are field names, not answer values). Never raises.
    """
    cells = []
    if not isinstance(sql_items, list):
        return cells
    for item in sql_items:
        if not isinstance(item, dict):
            continue
        result = item.get("result")
        if not isinstance(result, dict):
            continue
        rows = result.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, (list, tuple)):
                continue
            for cell in row:
                cells.append(_safe_str(cell))
    return cells


def _serialize_table(sql_item, index):
    """Render one SQL item's result as a compact, bounded text table for the judge."""
    lines = []
    result = sql_item.get("result") if isinstance(sql_item, dict) else None
    row_count = sql_item.get("row_count") if isinstance(sql_item, dict) else None
    if not isinstance(result, dict):
        lines.append("[Result {0}: no rows captured]".format(index))
        return "\n".join(lines)
    columns = result.get("columns") or []
    rows = result.get("rows") or []
    header = " | ".join(_safe_str(c, _FULL_ANSWER_CELL_CHARS) for c in columns)
    total = row_count if isinstance(row_count, int) else len(rows)
    lines.append("[Result {0}: {1} row(s)]".format(index, total))
    if header:
        lines.append(header)
    shown = rows[:_FULL_ANSWER_MAX_TABLE_ROWS]
    for row in shown:
        if isinstance(row, (list, tuple)):
            lines.append(" | ".join(
                _safe_str(c, _FULL_ANSWER_CELL_CHARS) for c in row))
    if len(rows) > len(shown):
        lines.append("... ({0} more row(s) omitted)".format(len(rows) - len(shown)))
    return "\n".join(lines)


def _artifact_phrase(artifact):
    """One short human phrase describing an artifact spec, or '' when empty."""
    if not isinstance(artifact, dict):
        return ""
    kind = artifact.get("kind")
    title = (artifact.get("title") or "").strip()
    if kind == "chart":
        ch = artifact.get("chart") or {}
        desc = "a {0} chart".format(ch.get("type") or "")
        if title:
            desc += ' "{0}"'.format(title[:120])
        x, ys = ch.get("x"), (ch.get("y") or [])
        if x:
            desc += " (x={0}, y={1})".format(x, ",".join(str(y) for y in ys))
        return desc
    if kind == "kpi":
        kpi = artifact.get("kpi") or {}
        return 'a KPI card "{0}" ({1})'.format(
            (kpi.get("label") or title or "")[:120], kpi.get("value") or "")
    if kind == "table":
        return "a table" + (' "{0}"'.format(title[:120]) if title else "")
    return ""


def assemble_full_answer(text, sql_items, artifacts):
    """Build THE single string the judge sees = the complete agent answer.

    Concatenates, in this order:
      1. the final assistant text;
      2. a readable, bounded serialization of EACH captured SQL result table
         (headers + rows, truncated) - this is the key fix: the answer is not
         text-only, the figures that live in a table are made visible to the judge;
      3. a short artifacts summary (chart / table / KPI specs rendered).

    Sections that are empty are omitted. Never raises.
    """
    parts = []
    clean_text = (text or "").strip()
    if clean_text:
        parts.append(clean_text)

    tables = []
    if isinstance(sql_items, list):
        for i, item in enumerate(sql_items, start=1):
            if isinstance(item, dict) and isinstance(item.get("result"), dict):
                tables.append(_serialize_table(item, i))
    if tables:
        parts.append("--- Data results ---\n" + "\n\n".join(tables))

    phrases = [p for p in (_artifact_phrase(a) for a in (artifacts or [])) if p]
    if phrases:
        parts.append("--- Displayed ---\n" + "; ".join(phrases) + ".")

    return "\n\n".join(parts)
