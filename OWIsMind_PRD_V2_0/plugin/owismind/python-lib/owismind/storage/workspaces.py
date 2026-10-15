"""Per-exchange V2.0 WORKSPACE documents (plan, notes, widgets, provenance).

The worker reduces the run's ``workspace`` events (owismind.workspace.reducer) and
writes the final reduced state here ONCE, at the end of the run. The document never
contains data rows: widgets reference captured SQL by ``sql_id`` and GET /workspace
joins them with the exchange's chat_v5 ``generated_sql`` at read time.

Storage rules (backend non-negotiables):
  - Direct SQL only, parametrized via ``sql_value`` (no f-strings around values).
  - ``COMMIT`` after the write; ``statement_timeout`` on every statement; reads run
    read-only. No Flow at runtime, no generic SQL route, no ALTER.
  - Owner-scoped on every read (``user_id`` in the WHERE).
  - Best-effort / never-raises: a storage failure never affects the answer.
"""

import json
import logging

from owismind.evidence.query_builders import build_exchange_sql_query
from owismind.storage.migrations import (
    CHAT_V5_LOGICAL,
    WORKSPACES_V1_LOGICAL,
    ensure_workspaces_table,
)
from owismind.storage.serialization import parse_json_list
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    readonly_pre_queries,
    sql_value,
)
from owismind.workspace import protocol, reducer

logger = logging.getLogger(__name__)

MAX_WORKSPACE_JSON_CHARS = protocol.MAX_WORKSPACE_JSON_CHARS
# Upper bound on the exchange ids checked in one has_workspace lookup (a session read
# is itself capped at chat_v5.SESSION_MESSAGES_CAP = 500 rows).
MAX_LOOKUP_IDS = 500

_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"


def save_workspace(exchange_id, user_id, session_id, state):
    """UPSERT the reduced workspace of one exchange. Best-effort, owner-stamped.

    Re-projected through ``reducer.sanitize`` before write; skipped (warning) when
    the state is empty, malformed, or its JSON exceeds MAX_WORKSPACE_JSON_CHARS.
    Returns True when the row was written, False otherwise. Never raises.
    """
    try:
        doc = reducer.sanitize(state)
        if doc is None or reducer.is_empty(doc):
            return False
        payload = json.dumps(doc, ensure_ascii=False, separators=(",", ":"))
        if len(payload) > MAX_WORKSPACE_JSON_CHARS:
            logger.warning(
                "save_workspace - document too large (%d chars) exchange_id=%s; skipping",
                len(payload), exchange_id,
            )
            return False
        ensure_workspaces_table()
        table = full_table(WORKSPACES_V1_LOGICAL)
        # The conflict branch only fires for the SAME exchange (server-generated
        # ids) and is guarded on the owner, so a row can never change hands.
        upsert = """
        INSERT INTO {table} AS ws (exchange_id, user_id, session_id, protocol_version,
                                   status, workspace, created_at)
        VALUES ({exchange_id}, {user_id}, {session_id}, {version}, {status}, {workspace}, now())
        ON CONFLICT (exchange_id) DO UPDATE SET
            session_id       = EXCLUDED.session_id,
            protocol_version = EXCLUDED.protocol_version,
            status           = EXCLUDED.status,
            workspace        = EXCLUDED.workspace
        WHERE ws.user_id = EXCLUDED.user_id
        """.format(
            table=table,
            exchange_id=sql_value(exchange_id),
            user_id=sql_value(user_id),
            session_id=sql_value(session_id) if session_id else "NULL",
            version=int(protocol.PROTOCOL_VERSION),
            status=sql_value(doc["status"]),
            workspace=sql_value(payload),
        )
        new_executor().query_to_df(
            "SELECT 1 AS workspace_saved",
            pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, upsert],
            post_queries=["COMMIT"],
        )
        logger.info(
            "save_workspace - stored exchange_id=%s status=%s widgets=%d notes=%d chars=%d",
            exchange_id, doc["status"], len(doc["widgets"]), len(doc["notes"]), len(payload),
        )
        return True
    except Exception:
        logger.exception("save_workspace - could not store workspace exchange_id=%s", exchange_id)
        return False


def read_workspace(user_id, exchange_id):
    """The sanitized workspace of an exchange the caller OWNS, else None.

    PRIMARY-KEY lookup + owner check, read-only + statement_timeout. Never raises:
    a missing table / row, bad JSON or an executor error all read as None.
    """
    try:
        ensure_workspaces_table()
        sql = (
            "SELECT workspace FROM {table} "
            "WHERE exchange_id = {exchange_id} AND user_id = {user_id} LIMIT 1"
        ).format(
            table=full_table(WORKSPACES_V1_LOGICAL),
            exchange_id=sql_value(exchange_id),
            user_id=sql_value(user_id),
        )
        df = new_executor().query_to_df(sql, pre_queries=readonly_pre_queries())
        if df is None or len(df) == 0:
            return None
        raw = df.iloc[0]["workspace"]
        if not raw or not isinstance(raw, str) or len(raw) > MAX_WORKSPACE_JSON_CHARS:
            return None
        return reducer.sanitize(json.loads(raw))
    except Exception:
        logger.exception("read_workspace - failed for exchange_id=%s", exchange_id)
        return None


def workspace_exchange_ids(user_id, exchange_ids):
    """The subset of ``exchange_ids`` (owned by the caller) that have a workspace.

    One bounded, read-only query (``exchange_id IN (...)`` on the primary key, owner
    in the WHERE), used to flag ``has_workspace`` on a conversation without N calls.
    Never raises: any failure reads as "no workspace" (empty set).
    """
    try:
        ids = []
        seen = set()
        for value in exchange_ids or []:
            if isinstance(value, str) and value and value not in seen:
                seen.add(value)
                ids.append(value)
            if len(ids) >= MAX_LOOKUP_IDS:
                break
        if not ids:
            return set()
        ensure_workspaces_table()
        sql = (
            "SELECT exchange_id FROM {table} "
            "WHERE user_id = {user_id} AND exchange_id IN ({ids})"
        ).format(
            table=full_table(WORKSPACES_V1_LOGICAL),
            user_id=sql_value(user_id),
            ids=", ".join(sql_value(v) for v in ids),
        )
        df = new_executor().query_to_df(sql, pre_queries=readonly_pre_queries())
        if df is None or len(df) == 0:
            return set()
        return {str(v) for v in df["exchange_id"].tolist() if v is not None}
    except Exception:
        logger.exception("workspace_exchange_ids - lookup failed (non-fatal)")
        return set()


def read_exchange_sql_items(user_id, exchange_id):
    """The stored ``generated_sql`` items (with captured results) of an owned exchange.

    Owner-scoped, read-only, primary-key lookup on chat_v5. Returns [] when the
    exchange stored no SQL or cannot be read (never raises): the workspace still
    renders, its data widgets showing an honest empty state.
    """
    try:
        sql = build_exchange_sql_query(
            table_ref=full_table(CHAT_V5_LOGICAL),
            user_value_sql=sql_value(user_id),
            exchange_value_sql=sql_value(exchange_id),
        )
        df = new_executor().query_to_df(sql, pre_queries=readonly_pre_queries())
        if df is None or len(df) == 0:
            return []
        raw = df.iloc[0]["generated_sql"]
        return [it for it in parse_json_list(raw) if isinstance(it, dict) and it.get("sql")]
    except Exception:
        logger.exception("read_exchange_sql_items - failed for exchange_id=%s", exchange_id)
        return []
