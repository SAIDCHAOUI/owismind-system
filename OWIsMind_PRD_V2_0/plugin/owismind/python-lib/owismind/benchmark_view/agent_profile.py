"""Validate + bound the ``benchmark`` block of an admin-authored agent profile (PURE).

The block tells the plugin WHERE an agent's benchmark lives so the consultation can read it:
``{enabled, connection, table, agent_key}``. It is admin input, so it is clamped (never raised):
an invalid table name is blanked (which disables consultation for that agent) rather than failing
the whole profile save. The table name is later interpolated into a SQL identifier, so it is
restricted to a plain identifier charset here, before it is ever stored.
"""

import re

# A physical SQL table name: letters, digits, underscore and hyphen (DSS managed-dataset names use
# the hyphen for an admin table prefix). Anything else -> blanked. Mirrors the LAB safe_table_name.
_TABLE_RE = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
# A SQL connection name (admin-selected from the real connection list).
_CONNECTION_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,120}$")
# An agent_key filter value (the LAB benchmark's logical agent key, e.g. "owismind").
_AGENT_KEY_RE = re.compile(r"^[A-Za-z0-9_.:\-]{1,120}$")

DEFAULT_CONNECTION = "SQL_owi"


def _clamp(value, pattern, default=""):
    if isinstance(value, str) and pattern.match(value.strip()):
        return value.strip()
    return default


def validate_benchmark_block(raw):
    """Return a bounded, safe ``benchmark`` block. Never raises (clamps, never fails the save).

    ``{enabled: bool, connection: str, table: str, agent_key: str}``. A missing/garbage table
    blanks the table (consultation treats the agent as having no benchmark). ``enabled`` is a
    strict bool. The default connection is SQL_owi (the webapp's usual connection).
    """
    if not isinstance(raw, dict):
        raw = {}
    enabled = raw.get("enabled")
    if isinstance(enabled, str):
        enabled = enabled.strip().lower() in ("true", "1", "yes", "y", "oui")
    else:
        enabled = bool(enabled)
    connection = _clamp(raw.get("connection"), _CONNECTION_RE, DEFAULT_CONNECTION)
    table = _clamp(raw.get("table"), _TABLE_RE, "")
    agent_key = _clamp(raw.get("agent_key"), _AGENT_KEY_RE, "")
    return {
        "enabled": enabled,
        "connection": connection or DEFAULT_CONNECTION,
        "table": table,
        "agent_key": agent_key,
    }


def is_configured(block):
    """True when an agent profile's benchmark block is usable (enabled + a valid table)."""
    if not isinstance(block, dict):
        return False
    return bool(block.get("enabled")) and bool(_clamp(block.get("table"), _TABLE_RE, ""))
