"""Read-time join of a stored workspace with the exchange's captured SQL (GET /workspace).

Nothing is re-run here: the SQL text, its captured result (50-row extract, L190) and
its success / row_count all come from the chat_v5 ``generated_sql`` items already
persisted for the exchange. The join key is ``sql_id``. Rules (same honesty rules as
/evidence/meta):
  - only an UNAMBIGUOUS sql_id (exactly one item carries it) is resolved; a missing
    or duplicated id stays unresolved, so a widget bound to it renders an honest
    empty state - never the rows of another query;
  - an ``orphan`` widget (no captured SQL in its run) never gets data;
  - the chart / KPI payloads are built by the trusted Evidence helpers
    (``evidence.chart_payload``), a donut being a pie with ``style: "donut"``.

``explain_fn`` / ``result_block_fn`` are injected by the route (the Evidence service
helpers) so this module stays importable without the DSS runtime. Never raises.
"""

import logging

from owismind.evidence import chart_payload
from owismind.workspace import protocol

logger = logging.getLogger(__name__)

# Bound on the filter steps surfaced per SQL (display chips, read-only).
MAX_FILTERS_PER_SQL = 12


def _unique_items_by_sql_id(items):
    """``{sql_id: item}`` for the ids carried by exactly ONE stored item."""
    counts, first = {}, {}
    for item in items or []:
        sid = item.get("sql_id") if isinstance(item, dict) else None
        if isinstance(sid, str) and sid:
            counts[sid] = counts.get(sid, 0) + 1
            first.setdefault(sid, item)
    return {sid: item for sid, item in first.items() if counts[sid] == 1}


def _filters(sql, explain_fn):
    """The ``filter_*`` steps of the deterministic SQL explainer (best-effort)."""
    if explain_fn is None or not sql:
        return []
    try:
        explain = explain_fn(sql) or {}
        steps = explain.get("steps") if isinstance(explain, dict) else None
        out = [s for s in steps or []
               if isinstance(s, dict) and str(s.get("kind", "")).startswith("filter")]
        return out[:MAX_FILTERS_PER_SQL]
    except Exception:
        logger.exception("workspace resolve - explain failed (non-fatal)")
        return []


def _chart_for_payload(chart):
    """The workspace chart spec in the shape ``chart_payload`` understands."""
    spec = dict(chart or {})
    if spec.get("type") == "donut":
        spec["type"] = "pie"
        spec["style"] = "donut"
    return spec


def build_resolution(state, items, explain_fn=None, result_block_fn=None):
    """Return ``(resolved, widgets_data)`` for a sanitized workspace state.

    ``resolved``     : ``{sql_id: {sql, success, row_count, agent_key, source_url,
                       filters, result}}`` for every referenced, unambiguous sql_id.
    ``widgets_data`` : ``{widget_id: payload}`` for chart / kpi / table widgets:
                       Chart.js-ready data, a KPI payload, or ``{ok: false, reason}``
                       (``orphan`` / ``no_data`` / the builder's own reasons).
    """
    resolved, widgets_data = {}, {}
    try:
        if not isinstance(state, dict):
            return resolved, widgets_data
        by_id = _unique_items_by_sql_id(items)
        referenced = list((state.get("summary") or {}).get("sql_ids") or [])
        for widget in state.get("widgets") or []:
            sid = widget.get("sql_id")
            if sid and sid not in referenced:
                referenced.append(sid)
        for sid in referenced:
            item = by_id.get(sid)
            if item is None:
                continue
            row_count = item.get("row_count")
            if isinstance(row_count, bool) or not isinstance(row_count, int):
                row_count = None
            entry = {
                "sql": item.get("sql"),
                "success": item.get("success"),
                "row_count": row_count,
                "agent_key": item.get("agent_key"),
                "source_url": item.get("source_url") or None,
                "filters": _filters(item.get("sql"), explain_fn),
            }
            if result_block_fn is not None:
                entry["result"] = result_block_fn(item)
            resolved[sid] = entry

        for widget in state.get("widgets") or []:
            kind = widget.get("kind")
            if kind not in protocol.DATA_WIDGET_KINDS:
                continue
            if widget.get("binding") == "orphan":
                widgets_data[widget["id"]] = {"ok": False, "reason": "orphan"}
                continue
            block = (resolved.get(widget.get("sql_id")) or {}).get("result")
            if kind == "chart":
                widgets_data[widget["id"]] = chart_payload.build_chart_payload(
                    block, _chart_for_payload(widget.get("chart")))
            elif kind == "kpi":
                widgets_data[widget["id"]] = chart_payload.build_kpi_payload(
                    block, widget.get("kpi"))
            else:
                captured = isinstance(block, dict) and bool(block.get("captured"))
                widgets_data[widget["id"]] = (
                    {"ok": True} if captured else {"ok": False, "reason": "no_data"})
    except Exception:
        logger.exception("workspace resolve - join failed (non-fatal)")
    return resolved, widgets_data
