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
# public."OWISMIND_DEV_owismind_webapp_chat_v5".
# v5 = v4 schema + per-exchange token/cost columns (usage accounting); v4 superseded,
# left inert (the prior table is never dropped by the backend — its old conversations
# simply stop surfacing, the established _vN handover, see memory L008/L014).
CHAT_V5_LOGICAL = "webapp_chat_v5"
USERS_V1_LOGICAL = "webapp_users_v1"
SETTINGS_V1_LOGICAL = "webapp_settings_v1"
# Per-(user, calendar-month) usage bucket — one PRIMARY-KEY row per month, so the
# planned per-user monthly quota is a single PK lookup and needs no reset job (each
# month is naturally its own row). chat_v5 stays the source of truth (rebuildable).
USAGE_MONTHLY_V1_LOGICAL = "webapp_usage_monthly_v1"
# Note: raw agent traces are NO LONGER stored in a backend-managed SQL table. They are
# appended to an admin-selected Flow dataset via the Dataset API (see storage/chat_traces.py),
# which keeps the large JSON out of any SQL statement text (and out of DSS CRU logs).

# One chat exchange per row, written in two phases (user message, then reply).
# Versioned _v5: over the abandoned _v4 (which added ``parent_exchange_id`` over _v3's
# per-message feedback columns, over _v2's ``generated_sql``), it adds the per-exchange
# USAGE columns — input/output/total tokens + estimated cost of the question→answer run.
# Per the no-ALTER rule, this is a brand new table (CREATE IF NOT EXISTS) — the _v4 table
# is left untouched and inert (never dropped by the backend).
# ``generated_sql`` is nullable: an agent run does not always generate SQL. When it
# does, it stores a JSON-encoded list of {sql, success, row_count} for later use.
# The feedback columns are nullable too: they stay NULL until the user rates the
# assistant reply (feedback_rating 0/1, feedback_reasons a JSON list, feedback_comment
# free text, feedback_at the rating timestamp).
# ``parent_exchange_id`` is nullable: NULL for a root/first-turn exchange, otherwise the
# exchange this one branched from (the basis for the recursive ancestor-chain context).
# The usage columns (input_tokens/output_tokens/total_tokens/estimated_cost) are nullable:
# they are filled from the run's footer ``usage_summary`` totals at phase-two write, and
# stay NULL when no footer arrived (e.g. an early-stopped run). They are the AUTHORITATIVE
# per-exchange usage record — the users + monthly aggregates are reconstructible from them.
_CHAT_V5_DDL = """
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
    parent_exchange_id TEXT,
    input_tokens       INTEGER,
    output_tokens      INTEGER,
    total_tokens       INTEGER,
    estimated_cost     DOUBLE PRECISION
)
"""

# One row per user who has opened the webapp at least once (so admins can promote
# them by their exact user_id). The first ever user is bootstrapped as admin.
# The LIFETIME usage counters (total_input_tokens/total_output_tokens/total_cost +
# last_usage_at) are denormalised running totals incremented once per agent response
# (storage/usage.record_usage) — a cheap per-user lifetime view. They are listed both
# here (fresh instances) AND in _ALTERS_BY_LOGICAL (existing instances get them via
# ADD COLUMN IF NOT EXISTS) — the ONE place the no-ALTER rule is intentionally relaxed
# (explicit user authorization, 2026-06-11), because additive counters on the existing
# registry must not lose the rows it already carries (admin flags, first_seen).
_USERS_V1_DDL = """
CREATE TABLE IF NOT EXISTS {full_table} (
    user_id              TEXT             PRIMARY KEY,
    display_name         TEXT,
    user_groups          TEXT,
    is_admin             BOOLEAN          NOT NULL DEFAULT false,
    first_seen           TIMESTAMP        NOT NULL DEFAULT now(),
    last_seen            TIMESTAMP        NOT NULL DEFAULT now(),
    total_input_tokens   BIGINT           NOT NULL DEFAULT 0,
    total_output_tokens  BIGINT           NOT NULL DEFAULT 0,
    total_cost           DOUBLE PRECISION NOT NULL DEFAULT 0,
    last_usage_at        TIMESTAMP
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

# Per-(user, calendar-month) usage bucket. PRIMARY KEY (user_id, period_start) means
# each user gets exactly one row per month: ON CONFLICT increments it (never overwrites),
# so the future per-user monthly quota check is a single PK lookup
# (WHERE user_id=? AND period_start = date_trunc('month', now())::date) with no reset job
# — a new month is simply a new row. ``period_start`` is the first day of the month
# (server clock, set by the UPSERT via date_trunc). Counters default to 0 so the first
# INSERT and every increment share one numeric path.
_USAGE_MONTHLY_V1_DDL = """
CREATE TABLE IF NOT EXISTS {full_table} (
    user_id        TEXT             NOT NULL,
    period_start   DATE             NOT NULL,
    input_tokens   BIGINT           NOT NULL DEFAULT 0,
    output_tokens  BIGINT           NOT NULL DEFAULT 0,
    total_cost     DOUBLE PRECISION NOT NULL DEFAULT 0,
    request_count  INTEGER          NOT NULL DEFAULT 0,
    updated_at     TIMESTAMP        NOT NULL DEFAULT now(),
    PRIMARY KEY (user_id, period_start)
)
"""

# Map each logical table to its DDL so a single generic helper can ensure any of
# them. Adding a table = one entry here plus a thin wrapper below.
_DDL_BY_LOGICAL = {
    CHAT_V5_LOGICAL: _CHAT_V5_DDL,
    USERS_V1_LOGICAL: _USERS_V1_DDL,
    SETTINGS_V1_LOGICAL: _SETTINGS_V1_DDL,
    USAGE_MONTHLY_V1_LOGICAL: _USAGE_MONTHLY_V1_DDL,
}

# Idempotent ADD COLUMN clauses applied (in the same ensure transaction, after the
# CREATE) to tables that gained columns AFTER first release — the ONLY relaxation of
# the no-ALTER rule, used for additive counters on the existing users registry whose
# rows (admin flags, first_seen) must be preserved. ``ADD COLUMN IF NOT EXISTS`` makes
# each clause a no-op once applied, so it is safe on every process start AND on a fresh
# table that already has the column from its CREATE DDL. Each entry is a bare clause
# (the "ALTER TABLE <t> " prefix is added by _ensure_table).
_ALTERS_BY_LOGICAL = {
    USERS_V1_LOGICAL: [
        "ADD COLUMN IF NOT EXISTS total_input_tokens  BIGINT NOT NULL DEFAULT 0",
        "ADD COLUMN IF NOT EXISTS total_output_tokens BIGINT NOT NULL DEFAULT 0",
        "ADD COLUMN IF NOT EXISTS total_cost          DOUBLE PRECISION NOT NULL DEFAULT 0",
        "ADD COLUMN IF NOT EXISTS last_usage_at       TIMESTAMP",
    ],
}

# Secondary indexes per logical table. CREATE INDEX IF NOT EXISTS is additive and
# idempotent — it is NOT an ALTER of the table structure, so it respects the no-ALTER
# rule. chat_v5 is read with WHERE user_id + ORDER BY created_at DESC (the sidebar
# conversation list and per-session reads); on a table shared by all users this index
# turns a full scan + sort into an index scan. The ancestor-chain walk (recursive CTE)
# is by PRIMARY KEY ``exchange_id``, so no extra index is needed for it. Each entry is
# (index_suffix, column_list).
_INDEXES_BY_LOGICAL = {
    CHAT_V5_LOGICAL: [
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
        # Additive ADD COLUMN IF NOT EXISTS clauses (existing tables that gained
        # columns post-release) — same transaction, idempotent, no-op once applied.
        for clause in _ALTERS_BY_LOGICAL.get(logical, []):
            pre.append("ALTER TABLE {tbl} {clause}".format(tbl=table, clause=clause))
            logger.info("ensure_table — ALTER TABLE %s %s", table, clause)
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


def ensure_chat_table():
    """Ensure the current chat table (v5) exists (create-if-missing), once per process."""
    _ensure_table(CHAT_V5_LOGICAL)


def ensure_users_table():
    """Ensure the users/admin registry exists + carries the usage counters, once per process.

    The same call applies the additive ADD COLUMN IF NOT EXISTS usage clauses, so an
    instance whose users table predates the usage feature gains the counters on the
    first post-deploy backend start (the registry rows are preserved).
    """
    _ensure_table(USERS_V1_LOGICAL)


def ensure_settings_table():
    """Ensure the webapp settings table exists (create-if-missing), once per process."""
    _ensure_table(SETTINGS_V1_LOGICAL)


def ensure_usage_monthly_table():
    """Ensure the per-(user, month) usage bucket exists (create-if-missing), once per process."""
    _ensure_table(USAGE_MONTHLY_V1_LOGICAL)
