"""Idempotent, controlled table creation for the OWIsMind WebApp backend.

DDL lives here (never inline in a public route): tables are created by a guarded,
internal helper triggered lazily on first write — never from user-supplied input
and never via a generic SQL route. ``CREATE TABLE IF NOT EXISTS`` keeps it
idempotent and concurrency-safe at the SQL level; a per-process guard avoids
re-issuing the DDL on every request.

Versioning strategy: a new message/row format means a NEW ``_vN`` table, never an
in-place ``ALTER`` of an existing one.
"""

import logging
import threading

from owismind.storage.sql_config import (
    full_table,
    new_executor,
    pg_identifier,
    physical_table,
)

logger = logging.getLogger(__name__)

# --- Logical table names (physical names are derived by full_table) -----------
# Physical names always carry the mandatory "owismind" namespace, e.g.
# public."OWISMIND_DEV_owismind_webapp_chat_v4".
# v4 = v3 schema + parent_exchange_id (conversation tree); v3 superseded, left inert.
CHAT_V4_LOGICAL = "webapp_chat_v4"
USERS_V1_LOGICAL = "webapp_users_v1"
SETTINGS_V1_LOGICAL = "webapp_settings_v1"
# Note: raw agent traces are NO LONGER stored in a backend-managed SQL table. They are
# appended to an admin-selected Flow dataset via the Dataset API (see storage/chat_traces.py),
# which keeps the large JSON out of any SQL statement text (and out of DSS CRU logs).

# One chat exchange per row, written in two phases (user message, then reply).
# Versioned _v4: over the abandoned _v3 (which added the per-message feedback columns
# over _v2, which itself added ``generated_sql`` over _v1), it adds
# ``parent_exchange_id`` to turn a conversation into a TREE: each exchange links to the
# parent it branched from (NULL for a first turn / root). Per the no-ALTER rule, this is
# a brand new table (CREATE IF NOT EXISTS) — the _v3 table is left untouched and inert
# (never dropped by the backend).
# ``generated_sql`` is nullable: an agent run does not always generate SQL. When it
# does, it stores a JSON-encoded list of {sql, success, row_count} for later use.
# The feedback columns are nullable too: they stay NULL until the user rates the
# assistant reply (feedback_rating 0/1, feedback_reasons a JSON list, feedback_comment
# free text, feedback_at the rating timestamp).
# ``parent_exchange_id`` is nullable: NULL for a root/first-turn exchange, otherwise the
# exchange this one branched from (the basis for the recursive ancestor-chain context).
_CHAT_V4_DDL = """
CREATE TABLE IF NOT EXISTS {full_table} (
    exchange_id        TEXT       PRIMARY KEY,
    session_id         TEXT,
    user_id            TEXT,
    user_display_name  TEXT,
    user_groups        TEXT,
    user_text          TEXT,
    assistant_text     TEXT,
    generated_sql      TEXT,
    agent_key          TEXT,
    created_at         TIMESTAMP  NOT NULL DEFAULT now(),
    answered_at        TIMESTAMP,
    feedback_rating    SMALLINT,
    feedback_reasons   TEXT,
    feedback_comment   TEXT,
    feedback_at        TIMESTAMP,
    parent_exchange_id TEXT
)
"""

# One row per user who has opened the webapp at least once (so admins can promote
# them by their exact user_id). The first ever user is bootstrapped as admin.
_USERS_V1_DDL = """
CREATE TABLE IF NOT EXISTS {full_table} (
    user_id       TEXT       PRIMARY KEY,
    display_name  TEXT,
    user_groups   TEXT,
    is_admin      BOOLEAN    NOT NULL DEFAULT false,
    first_seen    TIMESTAMP  NOT NULL DEFAULT now(),
    last_seen     TIMESTAMP  NOT NULL DEFAULT now()
)
"""

# Webapp-global settings as a generic key-value store (NOT per-user): the admin's
# choices (e.g. the enabled-agents whitelist) live here as JSON, so new global
# settings never need a new table. setting_value holds a JSON-encoded payload.
_SETTINGS_V1_DDL = """
CREATE TABLE IF NOT EXISTS {full_table} (
    setting_key    TEXT       PRIMARY KEY,
    setting_value  TEXT,
    updated_at     TIMESTAMP  NOT NULL DEFAULT now(),
    updated_by     TEXT
)
"""

# Map each logical table to its DDL so a single generic helper can ensure any of
# them. Adding a table = one entry here plus a thin wrapper below.
_DDL_BY_LOGICAL = {
    CHAT_V4_LOGICAL: _CHAT_V4_DDL,
    USERS_V1_LOGICAL: _USERS_V1_DDL,
    SETTINGS_V1_LOGICAL: _SETTINGS_V1_DDL,
}

# Secondary indexes per logical table. CREATE INDEX IF NOT EXISTS is additive and
# idempotent — it is NOT an ALTER of the table structure, so it respects the no-ALTER
# rule. chat_v4 is read with WHERE user_id + ORDER BY created_at DESC (the sidebar
# conversation list and per-session reads); on a table shared by all users this index
# turns a full scan + sort into an index scan. The ancestor-chain walk (recursive CTE)
# is by PRIMARY KEY ``exchange_id``, so no extra index is needed for it. Each entry is
# (index_suffix, column_list).
_INDEXES_BY_LOGICAL = {
    CHAT_V4_LOGICAL: [
        ("uc_idx", "(user_id, created_at DESC)"),
        # Per-session reads (agent-context window + /conversation): (user_id, session_id, created_at).
        ("usc_idx", "(user_id, session_id, created_at DESC)"),
    ],
}

# Per-process idempotency guard: run each table's DDL at most once per backend
# process. A single lock cleanly serialises creation across all tables.
_ensured_tables = set()
_lock = threading.Lock()


def _ensure_table(logical):
    """Ensure ``logical`` exists (create-if-missing), at most once per process.

    Safe to call on every write: the in-process guard avoids redundant DDL, and
    ``CREATE TABLE IF NOT EXISTS`` + COMMIT stays idempotent if two requests race.
    """
    if logical in _ensured_tables:
        return
    with _lock:
        if logical in _ensured_tables:
            return
        table = full_table(logical)
        ddl = _DDL_BY_LOGICAL[logical].format(full_table=table)
        logger.info("ensure_table — CREATE TABLE IF NOT EXISTS %s", table)
        # Side-effecting DDL goes in pre_queries; COMMIT is mandatory. Any secondary
        # indexes are created in the same transaction (also idempotent).
        pre = [ddl]
        for suffix, columns in _INDEXES_BY_LOGICAL.get(logical, []):
            index_name = pg_identifier("{}_{}".format(physical_table(logical), suffix))
            pre.append(
                "CREATE INDEX IF NOT EXISTS {idx} ON {tbl} {cols}".format(
                    idx=index_name, tbl=table, cols=columns
                )
            )
            logger.info("ensure_table — CREATE INDEX IF NOT EXISTS %s ON %s", index_name, table)
        new_executor().query_to_df(
            "SELECT 1 AS table_creation_committed",
            pre_queries=pre,
            post_queries=["COMMIT"],
        )
        _ensured_tables.add(logical)
        logger.info("ensure_table — ensured (committed) %s", table)


def ensure_chat_v4_table():
    """Ensure the chat_v4 table exists (create-if-missing), once per process."""
    _ensure_table(CHAT_V4_LOGICAL)


def ensure_users_table():
    """Ensure the users/admin registry exists (create-if-missing), once per process."""
    _ensure_table(USERS_V1_LOGICAL)


def ensure_settings_table():
    """Ensure the webapp settings table exists (create-if-missing), once per process."""
    _ensure_table(SETTINGS_V1_LOGICAL)
