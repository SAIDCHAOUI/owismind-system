"""Central SQL configuration and safety helpers for the OWIsMind WebApp backend.

Storage is configured PER WEBAPP (Agent-Hub style) through the DSS webapp settings
(see webapp.json), never hardcoded:
  - ``sql_connection`` : the DSS SQL connection (PostgreSQL) used for direct SQL;
  - ``table_prefix``   : an optional prefix inserted right after the project key;
  - ``log_level``      : backend logging verbosity.

Until an admin sets ``sql_connection``, the app reports "not configured" rather
than guessing (an emergency fallback keeps the process alive and loud-logs it).

Table naming - the project key ALWAYS leads and the ``owismind`` namespace is ALWAYS
present (memory L008). An optional prefix is inserted between them:
  - no prefix       -> ``{PROJECT_KEY}_owismind_{logical}``
  - prefix "bidule" -> ``{PROJECT_KEY}_bidule-owismind_{logical}``

Never build SQL with raw f-strings around user content: use ``sql_value`` for values
and ``pg_identifier`` for identifiers (table/column/schema names).
"""

import hashlib
import logging
import os
import re

import dataiku
from dataiku import SQLExecutor2
from dataiku.sql import Constant, Dialects, toSQL

logger = logging.getLogger(__name__)

# --- Static constants --------------------------------------------------------
SCHEMA_NAME = "public"
APP_NAMESPACE = "owismind"
DIALECT = Dialects.POSTGRES

# Webapp-config param names (must match webapp.json).
PARAM_CONNECTION = "sql_connection"
PARAM_TABLE_PREFIX = "table_prefix"
PARAM_TRACES_DATASET = "traces_dataset"
PARAM_LOG_LEVEL = "log_level"

# Project key resolution fallbacks.
FALLBACK_PROJECT_KEY = "OWISMIND_DEV"
PROJECT_KEY_ENV_VAR = "OWISMIND_PROJECT_KEY"

# Identifiers are always double-quoted, so a hyphen (from a table prefix) is safe.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
# Admin-supplied prefix ends up inside an identifier: restrict to a safe charset AND a
# bounded length, so the derived table/index names stay under PostgreSQL's 63-byte
# identifier limit (NAMEDATALEN) instead of being silently truncated (which could make
# two logical names collide on the same physical name).
_PREFIX_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")

# PostgreSQL truncates identifiers longer than this many bytes (NAMEDATALEN - 1),
# silently - so we reject over-long identifiers loudly instead.
_MAX_IDENTIFIER_BYTES = 63


# --- Webapp config (read once, cached for the process life) ------------------
_config_cache = None


def _webapp_config():
    """Return the DSS webapp config dict (params), read once and cached.

    DSS restarts the backend when the config changes, so caching is safe. Never
    raises: an unreadable config yields an empty dict (app reports not-configured).
    """
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    cfg = {}
    try:
        from dataiku.customwebapp import get_webapp_config

        cfg = get_webapp_config() or {}
    except Exception as exc:  # not in a webapp context, or no config available
        logger.warning("get_webapp_config() unavailable: %s", exc)
        cfg = {}
    _config_cache = cfg
    logger.info("webapp config keys: %s", sorted(cfg.keys()))
    return cfg


# --- Project key -------------------------------------------------------------
def _resolve_project_key():
    """Resolve the DSS project key (env -> webapp config -> default -> constant)."""
    override = os.environ.get(PROJECT_KEY_ENV_VAR)
    if override and override.strip():
        return override.strip(), "override_env"

    config_key = _webapp_config().get("project_key")
    if config_key and str(config_key).strip():
        return str(config_key).strip(), "override_config"

    try:
        key = dataiku.default_project_key()
        if key:
            return key, "dataiku_default"
    except Exception:
        pass

    return FALLBACK_PROJECT_KEY, "fallback_constant"


# Resolved once at import (does not need a SQL connection).
PROJECT_KEY, PROJECT_KEY_SOURCE = _resolve_project_key()


# --- Configured storage (connection / prefix / log level) --------------------
# The SQL connection is chosen by the webapp admin in the DSS webapp Settings via a
# real dropdown (a SELECT param populated by resource/compute_available_connections.py
# through list_connections()). Read here from get_webapp_config(); never hardcoded.
def connection_name():
    """The configured SQL connection name (from the Settings dropdown), or None."""
    val = _webapp_config().get(PARAM_CONNECTION)
    if isinstance(val, dict):  # some param shapes wrap the value
        val = val.get("name") or val.get("connection") or val.get("value")
    if val and str(val).strip():
        return str(val).strip()
    return None


# Resolved once (the webapp config is cached and DSS restarts the backend on change),
# so the validation warning for an invalid/over-long prefix is logged ONCE - not on
# every full_table() call (it was previously logged on each SQL identifier build).
_prefix_cache = None  # tuple (effective, raw_input, ignored)


def _resolve_table_prefix():
    """Resolve the table prefix once: returns ``(effective, raw_input, ignored)``.

    ``effective`` is "" when no prefix is set OR the configured one is invalid/too
    long; ``raw_input`` is the admin's configured value (so the UI can show it back);
    ``ignored`` is True when a non-empty input was rejected. The warning is emitted
    here only (once), and the result is surfaced via ``storage_status`` so the Admin
    page can tell the admin the prefix was ignored instead of failing silently.
    """
    global _prefix_cache
    if _prefix_cache is not None:
        return _prefix_cache
    val = _webapp_config().get(PARAM_TABLE_PREFIX)
    raw = str(val).strip() if val and str(val).strip() else ""
    if not raw:
        _prefix_cache = ("", "", False)
    elif not _PREFIX_RE.match(raw):
        logger.warning(
            "Ignoring invalid table_prefix %r (allowed: letters, digits, _ and -; "
            "max 16 chars) - using no prefix",
            raw,
        )
        _prefix_cache = ("", raw, True)
    else:
        _prefix_cache = (raw, raw, False)
    return _prefix_cache


def table_prefix():
    """The configured (validated) table prefix, or "" if none/invalid."""
    return _resolve_table_prefix()[0]


def traces_dataset_name():
    """The DSS dataset (name) where raw agent traces are appended, or None.

    Configured via the webapp Settings 'traces_dataset' DATASET picker. The webapp
    only WRITES to it (append, via the Dataset API), never reads it back. When unset,
    trace storage is simply skipped - traces are best-effort and non-critical.
    """
    val = _webapp_config().get(PARAM_TRACES_DATASET)
    if isinstance(val, dict):  # DATASET params may arrive wrapped in a dict shape
        val = val.get("name") or val.get("dataset") or val.get("value")
    if val and str(val).strip():
        return str(val).strip()
    return None


def is_configured():
    """True once an admin has set the SQL connection in the webapp settings."""
    return connection_name() is not None


def apply_log_level():
    """Apply the configured log level to the backend loggers (default INFO)."""
    name = str(_webapp_config().get(PARAM_LOG_LEVEL) or "INFO").upper()
    level = getattr(logging, name, logging.INFO)
    logging.getLogger().setLevel(level)
    logging.getLogger("owismind").setLevel(level)
    logger.info("Log level set to %s", name)


# --- SQL execution -----------------------------------------------------------
def new_executor():
    """Return a FRESH SQLExecutor2 bound to the admin-configured connection.

    Always a new instance per call (SQLExecutor2 carries transaction state, so it
    must not be shared across Flask worker threads). Refuses to run when no
    connection is configured: we NEVER open a connection the admin did not
    explicitly select. Routes guard with is_configured() first, so this raise is a
    defensive backstop, never a normal path.
    """
    conn = connection_name()
    if conn is None:
        raise RuntimeError(
            "SQL connection not configured; select one in the webapp Settings."
        )
    return SQLExecutor2(connection=conn)


def pg_identifier(name):
    """Validate and double-quote a PostgreSQL identifier.

    Identifiers are built server-side from controlled constants and the validated
    table prefix only. Never pass user input here; never use ``sql_value`` for an
    identifier.
    """
    if not _IDENTIFIER_RE.match(name):
        raise ValueError("Invalid SQL identifier: {!r}".format(name))
    # Fail loudly rather than let PostgreSQL silently truncate (and risk a name collision).
    if len(name.encode("utf-8")) > _MAX_IDENTIFIER_BYTES:
        raise ValueError(
            "SQL identifier too long ({} bytes > {}): {!r}".format(
                len(name.encode("utf-8")), _MAX_IDENTIFIER_BYTES, name
            )
        )
    return '"' + name.replace('"', '""') + '"'


def safe_index_name(physical_name, suffix):
    """A safely-quoted index identifier for ``{physical_name}_{suffix}``, length-safe.

    A secondary-index name must be unique per table, not human-readable. The natural name
    ``{physical_name}_{suffix}`` can exceed PostgreSQL's 63-byte NAMEDATALEN limit once a long
    project key / table prefix meets a long logical name; ``pg_identifier`` REJECTS (raises) an
    over-long identifier, which would abort the whole CREATE-TABLE-and-indexes transaction. So
    when the natural name is too long we fall back to a short, collision-safe hashed name
    (``idx_<suffix>_<sha1[:16]>``) that always fits. Short names are unchanged, so existing
    indexes keep their readable names.
    """
    natural = "{}_{}".format(physical_name, suffix)
    if len(natural.encode("utf-8")) <= _MAX_IDENTIFIER_BYTES:
        return pg_identifier(natural)
    digest = hashlib.sha1(natural.encode("utf-8")).hexdigest()[:16]
    return pg_identifier("idx_{}_{}".format(suffix, digest))


def sql_value(value):
    """Escape a value for safe inlining in a PostgreSQL statement (dataiku.sql)."""
    return toSQL(Constant(value), dialect=DIALECT)


def nullable_value(value):
    """SQL fragment for a nullable column value.

    Returns the bare ``NULL`` keyword for None/empty input, otherwise the escaped
    value via ``sql_value`` - so an optional field (e.g. a missing display name)
    stores SQL NULL rather than an empty string.
    """
    if value is None or value == "":
        return "NULL"
    return sql_value(value)


def bool_literal(value):
    """Inline a Python bool as a bare SQL boolean keyword (``true``/``false``).

    Callers pass either server-side booleans or values already type-checked as
    ``bool`` (e.g. evidence filter values gated by ``isinstance(value, bool)``),
    so a bare keyword is safe and avoids depending on ``Constant(bool)``
    escaping behaviour.
    """
    return "true" if value else "false"


# --- Table naming ------------------------------------------------------------
def _namespace():
    """Namespace segment: ``owismind`` or ``{prefix}-owismind`` when a prefix is set."""
    prefix = table_prefix()
    return "{}-{}".format(prefix, APP_NAMESPACE) if prefix else APP_NAMESPACE


def _shorten_identifier(natural):
    """Return ``natural`` unchanged when it fits NAMEDATALEN, else a deterministic,
    collision-safe shortened form that fits.

    A physical table name is ``{PROJECT_KEY}_{namespace}_{logical}``. A long project key
    plus an admin ``table_prefix`` (up to 16 chars) meeting a long logical name (e.g. the
    28-char ``webapp_golden_suggestions_v1``) can exceed PostgreSQL's 63-byte identifier
    limit - and ``pg_identifier`` then REJECTS (raises) the name, aborting the whole
    create-table transaction. So we keep a readable head and append a short hash of the
    FULL natural name: same input -> same output (required, tables are create-if-not-exist
    so the name must be stable) and collision-safe (two distinct logical names cannot land
    on one physical name). Names that already fit are returned UNCHANGED, so every table
    that was creatable under the old code keeps the exact same name - no data is orphaned.
    """
    raw = natural.encode("utf-8")
    if len(raw) <= _MAX_IDENTIFIER_BYTES:
        return natural
    digest = hashlib.sha1(raw).hexdigest()[:10]
    keep = _MAX_IDENTIFIER_BYTES - 1 - len(digest)  # room for "_" + digest
    head = raw[:keep].decode("utf-8", "ignore").rstrip("_-")
    return "{}_{}".format(head, digest)


def physical_table(logical):
    """Physical table name: ``{PROJECT_KEY}_{namespace}_{logical}`` (length-safe).

    e.g. ``webapp_chat_v5`` -> ``OWISMIND_DEV_owismind_webapp_chat_v5`` (no prefix)
    or ``OWISMIND_DEV_bidule-owismind_webapp_chat_v5`` (prefix "bidule").

    When the natural name would exceed PostgreSQL's 63-byte limit (a long project key +
    admin prefix + long logical name), it is deterministically shortened so it always fits
    and ``pg_identifier`` never raises (see ``_shorten_identifier``). Names that fit are
    unchanged. This same name is what ``storage_status`` exposes for the admin to paste
    into the LAB benchmark config, so the cross-project read stays consistent.
    """
    return _shorten_identifier("{}_{}_{}".format(PROJECT_KEY, _namespace(), logical))


def full_table(logical):
    """Fully-qualified, safely-quoted table reference, e.g.
    ``public."OWISMIND_DEV_owismind_webapp_chat_v5"``."""
    return "{}.{}".format(SCHEMA_NAME, pg_identifier(physical_table(logical)))


# --- Introspection / discovery ----------------------------------------------
def storage_status():
    """Resolved storage configuration, for the admin space (admin-gated route)."""
    effective_prefix, raw_prefix, prefix_ignored = _resolve_table_prefix()
    return {
        "configured": is_configured(),
        "connection": connection_name(),
        "project_key": PROJECT_KEY,
        "project_key_source": PROJECT_KEY_SOURCE,
        "table_prefix": effective_prefix,
        # Surface the raw input + whether it was rejected, so the Admin page can warn
        # that an over-long/invalid prefix was ignored (instead of failing silently).
        "table_prefix_input": raw_prefix,
        "table_prefix_ignored": prefix_ignored,
        "namespace": _namespace(),
        # Raw traces no longer live in a backend-managed SQL table: they are appended
        # to an admin-selected Flow dataset (write-only), so expose its name, not a table.
        "traces_dataset": traces_dataset_name(),
        "tables": {
            "chat": physical_table("webapp_chat_v5"),
            "users": physical_table("webapp_users_v1"),
            "settings": physical_table("webapp_settings_v1"),
            "usage_monthly": physical_table("webapp_usage_monthly_v1"),
            "user_quota": physical_table("webapp_user_quota_v1"),
            # Exposed so the admin can paste the EXACT physical name into the LAB benchmark
            # webapp's `benchmark.suggestions.table` config (it reads this table cross-project).
            "golden_suggestions": physical_table("webapp_golden_suggestions_v1"),
        },
    }
