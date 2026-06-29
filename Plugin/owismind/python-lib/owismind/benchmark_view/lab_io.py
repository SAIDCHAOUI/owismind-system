"""The ONLY DSS-touching module of benchmark_view: bounded cross-project SQL on the agent's table.

The plugin reads an agent's benchmark from a SQL table the ADMIN selected in the agent profile
(``benchmark.{connection, table, agent_key}``). End users never pick the table: they send an opaque
agent key, the backend resolves it to the profile, and this module reads/writes that admin-validated
table. Every statement is bounded:

  - reads: an explicit column list, a guarded (pg_identifier) physical table name, an optional
    parametrized ``agent_key`` filter, a row cap, and read-only + statement_timeout pre-queries.
  - the review override: a single parametrized UPDATE of the human_* columns on the matching
    (run_id, question_id, agent_key, mode) row, COMMITted. No generic SQL, never a client-supplied
    query. The table is the admin-configured benchmark table, never end-user input.
  - table discovery / schema check: read-only information_schema SELECTs for the admin table picker.

DSS-only (imports dataiku SQLExecutor2); kept thin so the testable logic lives in the pure modules.
"""

import logging

from dataiku import SQLExecutor2

from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import pg_identifier, sql_value, nullable_value
from owismind.benchmark_view import schema_check, schemas

logger = logging.getLogger(__name__)

# Read-only guard mirrored from storage.settings: a contended table can never pin a worker past 30s.
_READ_PRE = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]
_WRITE_TIMEOUT_PRE = "SET LOCAL statement_timeout TO '30000'"

# Backstop caps (a small benchmark table; these bound a misconfiguration, not a paginator).
MAX_SCORED_ROWS = 5000
MAX_TABLES = 2000

# The columns read for the consultation. The REQUIRED set is guaranteed present once the admin
# validates the schema; the v2 columns are OPTIONAL (benchmark dimension + reference SQL/tool), read
# only when the table actually has them - so an older table that predates a v2 re-run still reads.
_READ_COLUMNS = tuple(schema_check.REQUIRED_COLUMNS)
_DESIRED_COLUMNS = tuple(schema_check.REQUIRED_COLUMNS) + tuple(schemas.OPTIONAL_V2_COLUMNS)
_HUMAN_COLUMNS = ("human_verdict", "human_correct", "human_comment", "reviewed_by", "reviewed_at")


def _executor(connection):
    """A fresh SQLExecutor2 on the admin-selected connection (None -> not configured)."""
    if not connection:
        return None
    return SQLExecutor2(connection=connection)


def list_tables(connection):
    """Public tables on a connection for the admin table picker. Returns (names, error). Read-only."""
    ex = _executor(connection)
    if ex is None:
        return None, "no_connection"
    sql = (
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' "
        "ORDER BY table_name LIMIT {0}".format(MAX_TABLES)
    )
    try:
        rows = rows_to_json_safe(ex.query_to_df(sql, pre_queries=_READ_PRE))
    except Exception:
        logger.warning("benchmark list_tables failed on connection=%s", connection, exc_info=True)
        return None, "list_failed"
    return [r.get("table_name") for r in rows if r.get("table_name")], None


def table_columns(connection, table):
    """Column names of a public table (for the schema check). Returns (cols, error). Read-only."""
    ex = _executor(connection)
    if ex is None:
        return None, "no_connection"
    sql = (
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = {0} "
        "ORDER BY ordinal_position LIMIT 500".format(sql_value(table))
    )
    try:
        rows = rows_to_json_safe(ex.query_to_df(sql, pre_queries=_READ_PRE))
    except Exception:
        logger.warning("benchmark table_columns failed table=%s", table, exc_info=True)
        return None, "columns_failed"
    return [r.get("column_name") for r in rows if r.get("column_name")], None


def read_scored(block, max_rows=MAX_SCORED_ROWS):
    """Read the scored rows for an agent's benchmark (bounded, read-only). Returns (rows, error).

    ``block`` is the validated agent-profile benchmark block ({connection, table, agent_key}). The
    table identifier is guarded (pg_identifier); the agent_key filter is parametrized.
    """
    connection = (block or {}).get("connection")
    table = (block or {}).get("table")
    agent_key = (block or {}).get("agent_key")
    if not connection or not table:
        return None, "not_configured"
    ex = _executor(connection)
    if ex is None:
        return None, "not_configured"
    try:
        ident = pg_identifier(table)  # validates charset + length, double-quotes
    except ValueError:
        return None, "bad_table"
    # Read the INTERSECTION of the desired columns and the table's LIVE columns: the required set is
    # guaranteed (the admin validated it), and the v2 columns are read only when present, so a table
    # that predates the v2 re-run never makes the SELECT fail on a missing column. A failed column
    # probe falls back to the required-only set (the previous, always-safe behavior).
    present, cerr = table_columns(connection, table)
    if cerr or present is None:
        read_cols = list(_READ_COLUMNS)
    else:
        have = {c.strip().lower() for c in present if isinstance(c, str) and c.strip()}
        read_cols = [c for c in _DESIRED_COLUMNS if c.lower() in have]
        if not read_cols:
            read_cols = list(_READ_COLUMNS)  # defensive: never read zero columns
    cols = ", ".join(pg_identifier(c) for c in read_cols)
    where = ""
    if agent_key:
        where = " WHERE {0} = {1}".format(pg_identifier("agent_key"), sql_value(agent_key))
    sql = 'SELECT {cols} FROM public.{ident}{where} LIMIT {cap}'.format(
        cols=cols, ident=ident, where=where, cap=int(max_rows))
    try:
        rows = rows_to_json_safe(ex.query_to_df(sql, pre_queries=_READ_PRE))
    except Exception:
        logger.warning("benchmark read_scored failed table=%s", table, exc_info=True)
        return None, "read_failed"
    return rows, None


def write_override(block, payload, reviewer, reviewed_at):
    """Apply one reviewer override via a parametrized UPDATE of the human_* columns. COMMITted.

    Matches the row on (run_id, question_id, agent_key, mode). A blank verdict CLEARS the override.
    Returns (result, error). The table is the admin-configured benchmark table; the values are all
    parametrized. Because the LAB scored table accumulates by run_id, the override survives runs.
    """
    connection = (block or {}).get("connection")
    table = (block or {}).get("table")
    if not connection or not table:
        return None, "not_configured"
    ex = _executor(connection)
    if ex is None:
        return None, "not_configured"
    try:
        ident = pg_identifier(table)
    except ValueError:
        return None, "bad_table"

    verdict = str(payload.get("verdict") or "").strip().lower()
    if verdict not in ("correct", "incorrect"):
        verdict = ""
    human_correct = None if verdict == "" else (verdict == "correct")
    comment = "" if verdict == "" else str(payload.get("comment") or "")
    rev = "" if verdict == "" else str(reviewer or "")
    rev_at = "" if verdict == "" else str(reviewed_at or "")

    sets = "{hv} = {v}, {hc} = {c}, {hm} = {m}, {rb} = {by}, {ra} = {at}".format(
        hv=pg_identifier("human_verdict"), v=sql_value(verdict),
        hc=pg_identifier("human_correct"), c=nullable_value(human_correct),
        hm=pg_identifier("human_comment"), m=sql_value(comment),
        rb=pg_identifier("reviewed_by"), by=sql_value(rev),
        ra=pg_identifier("reviewed_at"), at=sql_value(rev_at),
    )
    where = (
        "{rid} = {rv} AND {qid} = {qv} AND {ak} = {av} AND {md} = {mv}".format(
            rid=pg_identifier("run_id"), rv=sql_value(str(payload.get("run_id") or "")),
            qid=pg_identifier("question_id"), qv=sql_value(str(payload.get("question_id") or "")),
            ak=pg_identifier("agent_key"), av=sql_value(str(payload.get("agent_key") or "")),
            md=pg_identifier("mode"), mv=sql_value(str(payload.get("mode") or "")),
        )
    )
    update_sql = "UPDATE public.{ident} SET {sets} WHERE {where}".format(
        ident=ident, sets=sets, where=where)
    try:
        ex.query_to_df(
            "SELECT 1 AS override_saved",
            pre_queries=[_WRITE_TIMEOUT_PRE, update_sql],
            post_queries=["COMMIT"],
        )
    except Exception:
        logger.warning("benchmark write_override failed table=%s", table, exc_info=True)
        return None, "override_failed"
    return {"ok": True}, None
