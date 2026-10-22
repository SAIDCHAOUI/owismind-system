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

A CARRIED widget (Studio continuity, ``origin`` set) resolves against the items of
its origin exchange only: its ``sql_id`` (``s1q1``...) is minted per run and would
otherwise match this exchange's own query.

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


def _resolve_entries(referenced, items, explain_fn, result_block_fn):
    """``{sql_id: entry}`` for the referenced ids carried by exactly one item."""
    resolved = {}
    by_id = _unique_items_by_sql_id(items)
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
    return resolved


def _widget_data(widget, resolved):
    """The render payload of ONE data widget against ``resolved`` (its own exchange)."""
    kind = widget.get("kind")
    if widget.get("binding") == "orphan":
        return {"ok": False, "reason": "orphan"}
    block = (resolved.get(widget.get("sql_id")) or {}).get("result")
    if kind == "chart":
        return chart_payload.build_chart_payload(block, _chart_for_payload(widget.get("chart")))
    if kind == "kpi":
        return chart_payload.build_kpi_payload(block, widget.get("kpi"))
    captured = isinstance(block, dict) and bool(block.get("captured"))
    return {"ok": True} if captured else {"ok": False, "reason": "no_data"}


def resolve_workspace(state, items, explain_fn=None, result_block_fn=None,
                      origin_items=None, origin_prov=None):
    """Return ``(resolved, widgets_data, origins)`` for a sanitized workspace state.

    ``resolved``     : ``{sql_id: {sql, success, row_count, agent_key, source_url,
                       filters, result}}`` for every referenced, unambiguous sql_id of
                       THIS exchange (carried widgets excluded).
    ``widgets_data`` : ``{widget_id: payload}`` for chart / kpi / table widgets:
                       Chart.js-ready data, a KPI payload, or ``{ok: false, reason}``
                       (``orphan`` / ``no_data`` / the builder's own reasons).
    ``origins``      : ``{origin_exchange_id: {resolved, provenance}}`` for the
                       CARRIED widgets (``origin`` set): resolved against the items
                       of their origin exchange only (``origin_items``:
                       ``{exchange_id: items}``, owner-scoped by the caller), with
                       that exchange's provenance (``origin_prov``). A carried data
                       widget whose origin was not read is ``orphan``.
    """
    resolved, widgets_data, origins = {}, {}, {}
    try:
        if not isinstance(state, dict):
            return resolved, widgets_data, origins
        widgets = [w for w in state.get("widgets") or [] if isinstance(w, dict)]
        own = [w for w in widgets if not w.get("origin")]
        carried = [w for w in widgets if w.get("origin")]
        referenced = list((state.get("summary") or {}).get("sql_ids") or [])
        for widget in own:
            sid = widget.get("sql_id")
            if sid and sid not in referenced:
                referenced.append(sid)
        resolved = _resolve_entries(referenced, items, explain_fn, result_block_fn)
        for widget in own:
            if widget.get("kind") in protocol.DATA_WIDGET_KINDS:
                widgets_data[widget["id"]] = _widget_data(widget, resolved)

        origin_items = origin_items if isinstance(origin_items, dict) else {}
        origin_prov = origin_prov if isinstance(origin_prov, dict) else {}
        by_origin = {}
        for widget in carried:
            by_origin.setdefault(widget["origin"], []).append(widget)
        for origin, group in by_origin.items():
            if origin not in origin_items:
                for widget in group:
                    if widget.get("kind") in protocol.DATA_WIDGET_KINDS:
                        widgets_data[widget["id"]] = {"ok": False, "reason": "orphan"}
                continue
            sids = []
            for widget in group:
                sid = widget.get("sql_id")
                if sid and sid not in sids:
                    sids.append(sid)
            o_resolved = _resolve_entries(sids, origin_items.get(origin), explain_fn,
                                          result_block_fn)
            prov = origin_prov.get(origin) if isinstance(origin_prov.get(origin), dict) else {}
            origins[origin] = {
                "resolved": o_resolved,
                "provenance": {sid: prov[sid] for sid in sids if sid in prov},
            }
            for widget in group:
                if widget.get("kind") in protocol.DATA_WIDGET_KINDS:
                    widgets_data[widget["id"]] = _widget_data(widget, o_resolved)
    except Exception:
        logger.exception("workspace resolve - join failed (non-fatal)")
    return resolved, widgets_data, origins


def build_resolution(state, items, explain_fn=None, result_block_fn=None):
    """``(resolved, widgets_data)`` of ``resolve_workspace`` without origin data (a
    carried data widget then reads as ``orphan``, never this exchange's rows)."""
    resolved, widgets_data, _origins = resolve_workspace(
        state, items, explain_fn=explain_fn, result_block_fn=result_block_fn)
    return resolved, widgets_data


def origin_exchange_ids(state):
    """The distinct ``origin`` exchange ids of the carried widgets (bounded)."""
    out = []
    for widget in (state or {}).get("widgets") or []:
        origin = widget.get("origin") if isinstance(widget, dict) else None
        if origin and origin not in out:
            out.append(origin)
    return out[:protocol.MAX_WIDGETS]
