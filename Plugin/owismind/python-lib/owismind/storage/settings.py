"""Webapp-global settings registry (key-value, direct SQL, no DSS Flow).

Stores webapp-WIDE admin configuration - not per-user (that is the users table).
Each setting is one row keyed by a stable ``setting_key``; ``setting_value`` holds
a JSON-encoded payload, so new global settings never require a new table.

The enabled-agents whitelist lives here under ``SETTING_ENABLED_AGENTS``. It is the
server-side source of truth for which agents the chat front may reference, and only
ever by their opaque ``logical_key`` (a raw agent_id is never exposed to the chat
front). Values are escaped via ``sql_value``; identifiers come from controlled
constants via ``full_table``; every write COMMITs explicitly.
"""

import json
import logging

from owismind.storage.migrations import SETTINGS_V1_LOGICAL, ensure_settings_table
from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)

# Stable key for the enabled-agents whitelist payload (a JSON list of agent dicts).
SETTING_ENABLED_AGENTS = "enabled_agents"

# Defense-in-depth (mirrors storage/artifacts.py + evidence/service.py): the settings
# reads run on the synchronous chat hot path (the agent-whitelist resolution on every
# /chat/start, and the budget config), so bound them with a read-only transaction +
# statement_timeout - a contended/locked settings row can then never pin a worker thread
# past 30s. The write caps its own runtime the same way. All are single-row PK ops.
_READ_PRE_QUERIES = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"


def get_setting(key, default=None):
    """Return the JSON-decoded value for ``key``, or ``default`` if absent/invalid.

    A malformed stored value never breaks a request: it is logged and ``default``
    is returned instead.
    """
    ensure_settings_table()
    table = full_table(SETTINGS_V1_LOGICAL)
    sql = "SELECT setting_value FROM {table} WHERE setting_key = {key}".format(
        table=table, key=sql_value(key)
    )
    rows = rows_to_json_safe(new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES))
    if not rows:
        return default
    raw = rows[0].get("setting_value")
    if raw is None:
        return default
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        logger.warning("get_setting - malformed JSON for key=%s; returning default", key)
        return default


def set_setting(key, value, updated_by=None):
    """Upsert ``key`` with a JSON-encoded ``value``; stamp updated_at/updated_by.

    Idempotent UPSERT on the primary key; the write is COMMITted explicitly.
    """
    ensure_settings_table()
    table = full_table(SETTINGS_V1_LOGICAL)
    payload = json.dumps(value)
    upsert_sql = """
    INSERT INTO {table} (setting_key, setting_value, updated_at, updated_by)
    VALUES ({key}, {val}, now(), {by})
    ON CONFLICT (setting_key) DO UPDATE
       SET setting_value = EXCLUDED.setting_value,
           updated_at    = now(),
           updated_by    = EXCLUDED.updated_by
    """.format(
        table=table,
        key=sql_value(key),
        val=sql_value(payload),
        by=nullable_value(updated_by),
    )
    new_executor().query_to_df(
        "SELECT 1 AS setting_saved",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, upsert_sql],
        post_queries=["COMMIT"],
    )
    logger.info(
        "set_setting - key=%s updated_by=%s value_len=%d", key, updated_by, len(payload)
    )


# --- Enabled-agents whitelist (typed helpers over the generic store) ---------
def get_enabled_agents():
    """Return the admin-enabled agents list, or ``[]`` if none configured.

    Each item is ``{logical_key, project_key, agent_id, label, profile}`` (``profile``
    is the admin-authored display copy: tagline / description / capabilities / tools /
    icon / badge). This is the server-side whitelist; the chat front references an
    agent only by logical_key.
    """
    value = get_setting(SETTING_ENABLED_AGENTS, default=[])
    return value if isinstance(value, list) else []


def set_enabled_agents(agents, updated_by=None):
    """Persist the enabled-agents whitelist (already validated by the caller)."""
    set_setting(SETTING_ENABLED_AGENTS, agents, updated_by=updated_by)


def resolve_enabled_agent(logical_key):
    """Resolve a chat-supplied logical key to its enabled whitelist entry, or None.

    This is the whitelist ENFORCEMENT point for the chat path: the frontend sends
    only an opaque ``logical_key`` (never a raw agent_id). We look it up in the
    currently-enabled list and return the whole entry (``{logical_key, project_key,
    agent_id, label, profile}``) only if it matches a real, still-enabled agent; the
    chat path uses just project_key/agent_id (the ``profile`` is display-only). A forged
    or stale key matches nothing and yields None, so it can never resolve to an agent to run.
    """
    if not logical_key:
        return None
    for agent in get_enabled_agents():
        if agent.get("logical_key") == logical_key:
            return agent
    return None
