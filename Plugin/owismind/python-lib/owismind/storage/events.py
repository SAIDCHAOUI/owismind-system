"""Best-effort usage-analytics event capture (direct SQL, no DSS Flow).

The frontend batches small product-analytics events (navigation, chat lifecycle, UI
toggles, evidence/source interactions, feedback, errors) and POSTs a batch to /track,
often via ``navigator.sendBeacon``. This module is the validation + storage layer
behind that route.

Design rules (mirroring storage/usage.py + storage/artifacts.py):
  - Best-effort ALWAYS: a tracking failure is logged and swallowed, never surfaced to
    the user (analytics must never affect the product experience).
  - Direct SQL only, values escaped via ``sql_value`` / ``nullable_value`` (no f-strings
    around content). COMMIT after the write; ensure-table lazily; caps at the write point.
  - ``user_id`` is resolved SERVER-SIDE by the route and passed in; it is never read from
    the event body. ``ts`` (authoritative) is stamped by the DB (``now()``) at write time;
    the client-supplied ``client_ts`` + ``seq`` are kept only for intra-session ordering.

``EVENT_CATEGORIES`` is the single source of truth for the accepted event names and their
category. An event whose name is not in the map is dropped silently (forward-compatible:
an old backend simply ignores a new client event it does not know yet).
"""

import json
import logging
from datetime import datetime

from owismind.storage.migrations import EVENTS_V1_LOGICAL, ensure_events_table
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)

# --- Caps (server enforces; the client mirrors these) ------------------------
MAX_EVENTS_PER_BATCH = 40      # events beyond this are dropped (server caps the batch)
MAX_PROPS_JSON_CHARS = 2000    # serialized props over this become {"_truncated": true}
MAX_EVENT_ID_CHARS = 64        # event id over this drops the whole event

# Column widths (must match the VARCHAR sizes in migrations._EVENTS_V1_DDL).
_USER_ID_MAX = 128
_APP_SESSION_MAX = 64
_VIEW_MAX = 64
_CONVERSATION_MAX = 64
_AGENT_KEY_MAX = 64
_MODE_MAX = 16

# Longest sane ISO8601 timestamp we will even try to parse (guards a pathological input).
_MAX_CLIENT_TS_CHARS = 40
# Accepted response modes (anything else -> NULL, so analytics stays clean).
_MODES = ("smart", "pro", "claude")

# Single source of truth: whitelisted event name -> category. The /track route drops any
# event whose name is absent here (unknown / forged names never reach the table).
EVENT_CATEGORIES = {
    # nav
    "webapp_opened": "nav",
    "page_viewed": "nav",
    # chat
    "conversation_created": "chat",
    "conversation_opened": "chat",
    "question_sent": "chat",
    "answer_received": "chat",
    "answer_stopped": "chat",
    "question_edited": "chat",
    "answer_regenerated": "chat",
    "answer_version_switched": "chat",
    "cell_value_added_to_prompt": "chat",
    "cell_value_removed_from_prompt": "chat",
    "screen_context_offered": "chat",
    "screen_context_included": "chat",
    "screen_context_dismissed": "chat",
    # ui
    "mode_changed": "ui",
    "agent_changed": "ui",
    "theme_changed": "ui",
    "sidebar_toggled": "ui",
    # evidence
    "evidence_panel_opened": "evidence",
    "evidence_panel_closed": "evidence",
    "evidence_filter_added": "evidence",
    "evidence_filter_removed": "evidence",
    "evidence_row_drilled": "evidence",
    "evidence_searched": "evidence",
    # evidence tab views (one first-class name per tab, so dashboards read
    # feature usage directly; evidence_tab_viewed is the fallback for future tabs)
    "evidence_proof_viewed": "evidence",
    "source_data_viewed": "evidence",
    "chart_viewed": "evidence",
    "table_viewed": "evidence",
    "kpi_viewed": "evidence",
    "evidence_tab_viewed": "evidence",
    # source
    "source_explorer_opened": "source",
    "source_dataset_switched": "source",
    "source_filter_added": "source",
    "source_filter_removed": "source",
    "source_searched": "source",
    "source_cell_clicked": "source",
    # feedback
    "feedback_submitted": "feedback",
    # benchmark
    "benchmark_suggestion_sent": "benchmark",
    # error
    "error_frontend": "error",
    "error_backend": "error",
}

# Instance-safety guard (mirrors the Evidence / artifacts writes): a statement_timeout
# bounds the small multi-row INSERT so a slow write can never hang a worker thread. The
# write persists rows, so it cannot be read-only.
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"


# --- Field coercion (pure, never raises) -------------------------------------
def _opt_str(value, cap):
    """A bounded, trimmed string for a NULLABLE column, or None (empty -> None)."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:cap]


def _req_str(value, cap):
    """A bounded string for a NOT NULL column (missing -> empty string, never None)."""
    if value is None:
        return ""
    return str(value)[:cap]


def _coerce_seq(value):
    """The monotonic per-session counter as an int, or None (bool rejected)."""
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coerce_mode(value):
    """One of the three response modes, or None (keeps the analytics column clean)."""
    if isinstance(value, str) and value in _MODES:
        return value
    return None


def _parse_client_ts(value):
    """Return a PostgreSQL-castable ISO8601 timestamp string, or None on any problem.

    The client sends ``Date#toISOString()`` (trailing ``Z``); Python 3.9's
    ``datetime.fromisoformat`` rejects the ``Z``, so it is normalised to ``+00:00``
    first. Re-emitting ``dt.isoformat()`` guarantees the value the write inlines is a
    valid timestamp literal (a bad literal would abort the whole multi-row INSERT).
    """
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s or len(s) > _MAX_CLIENT_TS_CHARS:
        return None
    if s[-1] in ("Z", "z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return None
    return dt.isoformat()


def _serialize_props(value):
    """Serialize the small props object under the char cap.

    Not a dict / empty -> None (nothing to store). Over the cap or unserializable ->
    the sentinel ``{"_truncated": true}`` so the row still records that props existed.
    """
    if not isinstance(value, dict) or not value:
        return None
    try:
        payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError):
        return json.dumps({"_truncated": True})
    if len(payload) > MAX_PROPS_JSON_CHARS:
        return json.dumps({"_truncated": True})
    return payload


def _int_literal(value):
    """A bare integer SQL literal (already coerced to int/None) - injection-safe."""
    return "NULL" if value is None else str(int(value))


# --- Validation --------------------------------------------------------------
def validate_events(raw):
    """Project a raw client batch onto the strict list of clean stored events.

    Pure, NEVER raises. Caps the batch at ``MAX_EVENTS_PER_BATCH``, drops non-dict
    items, events with an unknown/missing name, and events with a missing/oversized id;
    truncates strings to their column widths; parses ``client_ts`` safely (invalid ->
    None); coerces ``seq``/``mode``; serializes props under the cap. Deduplicates by
    event id within the batch (a sendBeacon retry can re-send the same id, and a
    duplicate primary key in one multi-row INSERT would otherwise be a hazard).
    """
    out = []
    if not isinstance(raw, list):
        return out
    seen = set()
    for item in raw[:MAX_EVENTS_PER_BATCH]:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        category = EVENT_CATEGORIES.get(name) if isinstance(name, str) else None
        if category is None:
            continue  # unknown / forged event name -> dropped silently
        event_id = item.get("id")
        if not isinstance(event_id, str):
            continue
        event_id = event_id.strip()
        if not event_id or len(event_id) > MAX_EVENT_ID_CHARS:
            continue  # missing / oversized id -> drop the whole event
        if event_id in seen:
            continue  # de-duplicate within the batch (idempotency key)
        seen.add(event_id)
        out.append({
            "id": event_id,
            "name": name,
            "category": category,
            "client_ts": _parse_client_ts(item.get("client_ts")),
            "seq": _coerce_seq(item.get("seq")),
            "app_session_id": _req_str(item.get("app_session_id"), _APP_SESSION_MAX),
            "view": _opt_str(item.get("view"), _VIEW_MAX),
            "conversation_id": _opt_str(item.get("conversation_id"), _CONVERSATION_MAX),
            "agent_key": _opt_str(item.get("agent_key"), _AGENT_KEY_MAX),
            "mode": _coerce_mode(item.get("mode")),
            "props": _serialize_props(item.get("props")),
        })
    return out


# --- Storage -----------------------------------------------------------------
def record_events(user_id, events):
    """INSERT a validated batch in ONE committed multi-row statement. Best-effort.

    ``user_id`` is the SERVER-resolved identity (bounded to the column width here);
    ``events`` is the output of ``validate_events``. Returns the number of events
    accepted (the batch size) on success, or 0 when there is nothing to store or the
    write fails. NEVER raises to the caller: any failure is logged on one line and
    swallowed so it can never affect the user experience (the aggregates are
    non-critical and the client will not retry).
    """
    if not user_id or not events:
        return 0
    try:
        ensure_events_table()
        table = full_table(EVENTS_V1_LOGICAL)
        user_sql = sql_value(str(user_id)[:_USER_ID_MAX])
        # One VALUES tuple per event. ``ts`` = now() (authoritative server receive time);
        # all client-supplied values are escaped (sql_value / nullable_value) or a bare
        # integer literal (seq, already coerced) - never inlined raw.
        rows = []
        for e in events:
            rows.append(
                "({eid}, now(), {cts}, {seq}, {uid}, {asid}, {name}, {cat}, "
                "{view}, {conv}, {agent}, {mode}, {props})".format(
                    eid=sql_value(e["id"]),
                    cts=nullable_value(e["client_ts"]),
                    seq=_int_literal(e["seq"]),
                    uid=user_sql,
                    asid=sql_value(e["app_session_id"]),
                    name=sql_value(e["name"]),
                    cat=sql_value(e["category"]),
                    view=nullable_value(e["view"]),
                    conv=nullable_value(e["conversation_id"]),
                    agent=nullable_value(e["agent_key"]),
                    mode=nullable_value(e["mode"]),
                    props=nullable_value(e["props"]),
                )
            )
        insert = (
            "INSERT INTO {table} (event_id, ts, client_ts, seq, user_id, app_session_id, "
            "event_name, event_category, view_name, conversation_id, agent_key, mode, props) "
            "VALUES {rows} ON CONFLICT (event_id) DO NOTHING"
        ).format(table=table, rows=", ".join(rows))
        # statement_timeout bounds the tiny write; COMMIT is mandatory after an INSERT.
        new_executor().query_to_df(
            "SELECT 1 AS events_recorded",
            pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, insert],
            post_queries=["COMMIT"],
        )
        logger.info("record_events - stored up to %d event(s) user_id=%s", len(events), user_id)
        return len(events)
    except Exception:
        logger.exception("record_events - could not store events user_id=%s", user_id)
        return 0
