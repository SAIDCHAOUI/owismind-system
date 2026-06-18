"""Monthly per-user budget: limits, resolution, enforcement (direct SQL, no DSS Flow).

Every user gets a rolling monthly credit (default $50). Spend is the LLM-Mesh estimated
cost already accumulated per calendar month in ``webapp_usage_monthly_v1`` (server clock,
``date_trunc('month', now())``), so it resets on its own on the 1st - a new month is a new
bucket row, no reset job. The amounts are US dollars, matching the per-message cost the
chat already shows (the trace ``estimatedCost``).

Two layers set a user's effective monthly limit, resolved here:
  - the GLOBAL config (``webapp_settings_v1`` key ``monthly_budget``): the default limit,
    an on/off switch for enforcement, and an optional time-boxed GLOBAL boost;
  - a PER-USER override (``webapp_user_quota_v1``): a custom limit, permanent or temporary,
    that wins over the global one while it is active.

Resolution order for one user: an ACTIVE per-user override > an ACTIVE global temp boost >
the global default. "Active" is a plain ``expires_at > now()`` test (NULL = permanent). The
per-user override's active test runs in SQL (against the DB clock); the global temp boost
is a settings JSON value compared in Python (against the app clock) - both are "now" on
their own clock, and a sub-second skew is irrelevant at month/day budget granularity.

This module is the SINGLE source of truth for the limit math. The enforcement gate
(``has_budget``) is consulted by /chat/start BEFORE a run starts; it fails OPEN by contract
(the caller swallows an error and lets the answer through - the spend is still recorded, so
the next request is gated once the read recovers). Reads are owner-scoped or admin-gated by
the route; amounts are inlined as server-computed numeric literals and user ids escaped.
"""

import logging
import math
import time
from datetime import datetime, timedelta

from owismind.storage import settings
from owismind.storage.migrations import (
    USAGE_MONTHLY_V1_LOGICAL,
    USER_QUOTA_V1_LOGICAL,
    USERS_V1_LOGICAL,
    ensure_usage_monthly_table,
    ensure_user_quota_table,
    ensure_users_table,
)
from owismind.storage.serialization import parse_json_list, rows_to_json_safe
from owismind.storage.sql_builders import (
    build_admin_usage_overview_query,
    build_user_quota_clear,
    build_user_quota_upsert,
    build_user_usage_status_query,
)
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)

# The default rolling monthly credit, in US dollars (user decision 2026-06-18).
DEFAULT_MONTHLY_LIMIT_USD = 50.0

# Settings key holding the global budget config JSON (in webapp_settings_v1).
SETTING_BUDGET = "monthly_budget"

# Currency tag surfaced to the frontend (the cost trace is in USD).
CURRENCY = "USD"

# Bound the admin overview so one request can never pull an unbounded result.
MAX_OVERVIEW_USERS = 1000

# Defense-in-depth (mirrors evidence/service.py + storage/artifacts.py): every budget
# READ runs in a transaction-scoped read-only transaction with a statement_timeout, and
# every WRITE caps its own runtime - so a contended connection or a degraded plan can
# never pin a backend worker thread indefinitely. The budget queries are O(1) PK lookups,
# so this is a safety bound, not a perf necessity.
_READ_PRE_QUERIES = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"


# --- Coercion helpers --------------------------------------------------------
def _money(value):
    """A non-negative float from a DB/JSON numeric (missing/garbage/NaN -> 0.0)."""
    try:
        f = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(f) or f < 0:
        return 0.0
    return f


def _int(value):
    """A non-negative int from a DB/JSON numeric (missing/garbage -> 0)."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _not_expired(iso_ts):
    """True if ``iso_ts`` (an ISO-8601 string) is in the future per the app clock.

    A missing or unparseable timestamp is treated as expired (False) so a malformed
    setting can never silently grant an unbounded boost.
    """
    if not iso_ts or not isinstance(iso_ts, str):
        return False
    try:
        return datetime.now() < datetime.fromisoformat(iso_ts)
    except (TypeError, ValueError):
        return False


# --- Global config -----------------------------------------------------------
# In-process TTL cache for the global config. The config is read on the SYNCHRONOUS chat
# hot path (every /chat/start budget gate) and on every /usage; caching it removes that
# second DB round-trip per call so the hot path does ONE indexed read, not two. A short
# TTL bounds staleness if the backend ever runs multiple processes (a slightly stale
# monthly limit for a few seconds is harmless), and set_budget_config busts it so an
# admin sees their change immediately in this process. Lock-free on purpose: a redundant
# read or a few-second-stale value is harmless, and tuple assignment is atomic under the
# GIL - no lock contention added to the hot path.
_config_cache = None  # (config_dict, monotonic_ts) or None
_CONFIG_TTL_SECONDS = 30.0


def _invalidate_config_cache():
    """Drop the cached global config (called after a config write, and by tests)."""
    global _config_cache
    _config_cache = None


def get_budget_config():
    """Return the sanitized global budget config (defaults applied).

    Shape: ``{limit_usd, enabled, temp_limit_usd, temp_expires_at}``. A malformed stored
    value degrades field-by-field to the safe default (never raises). The temp boost is
    only carried when BOTH a finite non-negative amount and an expiry string are present.
    Served from a short-TTL in-process cache (a fresh dict copy each call, so callers can
    never mutate the cache) to keep the chat hot path to a single DB read.
    """
    global _config_cache
    cached = _config_cache
    if cached is not None and (time.time() - cached[1]) < _CONFIG_TTL_SECONDS:
        return dict(cached[0])
    raw = settings.get_setting(SETTING_BUDGET, default=None)
    cfg = {
        "limit_usd": DEFAULT_MONTHLY_LIMIT_USD,
        "enabled": True,
        "temp_limit_usd": None,
        "temp_expires_at": None,
    }
    if isinstance(raw, dict):
        lim = raw.get("limit_usd")
        if isinstance(lim, (int, float)) and not isinstance(lim, bool) and math.isfinite(lim) and lim >= 0:
            cfg["limit_usd"] = float(lim)
        cfg["enabled"] = bool(raw.get("enabled", True))
        tl = raw.get("temp_limit_usd")
        te = raw.get("temp_expires_at")
        if (isinstance(tl, (int, float)) and not isinstance(tl, bool)
                and math.isfinite(tl) and tl >= 0 and isinstance(te, str) and te):
            cfg["temp_limit_usd"] = float(tl)
            cfg["temp_expires_at"] = te
    _config_cache = (cfg, time.time())
    return dict(cfg)


def _global_effective(config):
    """``(limit_usd, source, expires_iso)`` for the GLOBAL limit, honoring a live boost.

    A temp boost wins only while not expired; otherwise the plain default applies.
    """
    temp = config.get("temp_limit_usd")
    temp_exp = config.get("temp_expires_at")
    if temp is not None and _not_expired(temp_exp):
        return float(temp), "global_temp", temp_exp
    return float(config["limit_usd"]), "default", None


def set_budget_config(limit_usd, enabled, temp_limit_usd=None, temp_days=None,
                      clear_temp=False, preserve_temp=False, updated_by=None):
    """Persist the global budget config; return the stored config dict.

    ``limit_usd``/``enabled`` set the default cap and the enforcement switch (always
    written). The temp boost is handled INDEPENDENTLY so that saving the default limit
    never disturbs an active boost:
      - ``clear_temp`` True              -> the boost is removed;
      - ``temp_limit_usd`` + ``temp_days`` -> a fresh boost is armed (expiry stamped from
        the app clock, ``now() + temp_days``);
      - ``preserve_temp`` True (neither of the above) -> the EXISTING boost is kept as-is
        (this is the "edit just the default limit" path);
      - otherwise the boost is cleared.
    Inputs are pre-validated by the route.
    """
    cfg = {
        "limit_usd": float(limit_usd),
        "enabled": bool(enabled),
        "temp_limit_usd": None,
        "temp_expires_at": None,
    }
    if clear_temp:
        pass  # boost removed
    elif temp_limit_usd is not None and temp_days:
        cfg["temp_limit_usd"] = float(temp_limit_usd)
        cfg["temp_expires_at"] = (datetime.now() + timedelta(days=int(temp_days))).isoformat()
    elif preserve_temp:
        existing = get_budget_config()
        cfg["temp_limit_usd"] = existing.get("temp_limit_usd")
        cfg["temp_expires_at"] = existing.get("temp_expires_at")
    settings.set_setting(SETTING_BUDGET, cfg, updated_by=updated_by)
    # Bust the in-process cache so the admin sees their change on the very next read.
    _invalidate_config_cache()
    logger.info(
        "set_budget_config - limit=%.4f enabled=%s temp=%s by=%s",
        cfg["limit_usd"], cfg["enabled"], cfg["temp_limit_usd"], updated_by,
    )
    return cfg


# --- Per-user override -------------------------------------------------------
def set_user_quotas(user_ids, limit_usd, expires_days, note, updated_by=None):
    """UPSERT a custom monthly limit for one or more users; return the count written.

    ``expires_days`` None = permanent; an int = a temporary boost that lapses on its own.
    All upserts run in ONE committed transaction. Inputs are pre-validated by the route.
    """
    if not user_ids:
        return 0
    ensure_user_quota_table()
    quota = full_table(USER_QUOTA_V1_LOGICAL)
    lim_sql = "{:.6f}".format(float(limit_usd))
    note_sql = nullable_value(note or None)
    by_sql = nullable_value(updated_by)
    pre = [_WRITE_TIMEOUT_PRE_QUERY] + [
        build_user_quota_upsert(quota, sql_value(uid), lim_sql, expires_days, note_sql, by_sql)
        for uid in user_ids
    ]
    new_executor().query_to_df(
        "SELECT 1 AS quota_saved", pre_queries=pre, post_queries=["COMMIT"]
    )
    # Count USERS written (pre also carries the statement_timeout pre-query, so len(pre)
    # would be off by one).
    n_users = len(user_ids)
    logger.info(
        "set_user_quotas - %d user(s) limit=%s expires_days=%s by=%s",
        n_users, lim_sql, expires_days, updated_by,
    )
    return n_users


def clear_user_quotas(user_ids, updated_by=None):
    """DELETE the override rows for these users (revert them to the global limit)."""
    if not user_ids:
        return 0
    ensure_user_quota_table()
    quota = full_table(USER_QUOTA_V1_LOGICAL)
    csv = ", ".join(sql_value(uid) for uid in user_ids)
    sql = build_user_quota_clear(quota, csv)
    new_executor().query_to_df(
        "SELECT 1 AS quota_cleared",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, sql],
        post_queries=["COMMIT"],
    )
    logger.info("clear_user_quotas - %d user(s) by=%s", len(user_ids), updated_by)
    return len(user_ids)


# --- Resolution + status -----------------------------------------------------
def _resolve_limit(spent, override_active, override_limit, override_expires, config):
    """Resolve the effective limit + derived gate fields for one user.

    Returns ``{limit_usd, limit_source, limit_expires_at, enforced, remaining_usd,
    blocked, default_limit_usd, currency}``. ``blocked`` is True only when enforcement is
    enabled AND the spend has reached the effective limit (>=, so exactly-at-limit blocks).
    """
    enforced = bool(config.get("enabled", True))
    if override_active and override_limit is not None:
        limit = float(override_limit)
        source = "user_temp" if override_expires else "user_permanent"
        expires = override_expires
    else:
        limit, source, expires = _global_effective(config)
    remaining = max(0.0, round(limit - spent, 6))
    blocked = enforced and spent >= limit
    return {
        "limit_usd": limit,
        "limit_source": source,
        "limit_expires_at": expires,
        "enforced": enforced,
        "remaining_usd": remaining,
        "blocked": blocked,
        "default_limit_usd": float(config["limit_usd"]),
        "currency": CURRENCY,
    }


def _status_from_row(row, config):
    """Build the public usage-status dict from one status-query row + the global config."""
    spent = _money(row.get("spent_usd"))
    in_tok = _int(row.get("input_tokens"))
    out_tok = _int(row.get("output_tokens"))
    lt_in = _int(row.get("lifetime_input_tokens"))
    lt_out = _int(row.get("lifetime_output_tokens"))
    resolved = _resolve_limit(
        spent,
        bool(row.get("override_active")),
        row.get("override_limit"),
        row.get("override_expires"),
        config,
    )
    status = {
        "period_start": row.get("period_start"),
        "next_reset": row.get("next_reset"),
        "spent_usd": spent,
        "input_tokens": in_tok,
        "output_tokens": out_tok,
        "total_tokens": in_tok + out_tok,
        "request_count": _int(row.get("request_count")),
        "lifetime": {
            "input_tokens": lt_in,
            "output_tokens": lt_out,
            "total_tokens": lt_in + lt_out,
            "cost_usd": _money(row.get("lifetime_cost")),
            "last_usage_at": row.get("last_usage_at"),
        },
    }
    status.update(resolved)
    return status


def usage_status(user_id):
    """The caller's CURRENT-MONTH usage + resolved limit (one owner-scoped read).

    Returns the public status dict (spend, tokens, request count, effective limit + its
    source/expiry, remaining, whether enforcement is on and whether the user is blocked,
    plus the lifetime counters and the reset date). Never returns None - a brand-new user
    yields an all-zero status against the resolved limit.
    """
    ensure_usage_monthly_table()
    ensure_user_quota_table()
    ensure_users_table()
    sql = build_user_usage_status_query(
        full_table(USAGE_MONTHLY_V1_LOGICAL),
        full_table(USER_QUOTA_V1_LOGICAL),
        full_table(USERS_V1_LOGICAL),
        sql_value(user_id),
    )
    rows = rows_to_json_safe(new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES))
    row = rows[0] if rows else {}
    return _status_from_row(row, get_budget_config())


def has_budget(user_id):
    """Enforcement gate: ``(ok, status)`` for ``user_id``.

    ``ok`` is False only when enforcement is on and the user has reached their effective
    monthly limit. Raises on a storage error (the caller fails OPEN: an answer is more
    important than a perfectly-timed block, and the spend is still recorded for next time).
    """
    status = usage_status(user_id)
    return (not status["blocked"]), status


# --- Admin overview ----------------------------------------------------------
def admin_overview():
    """Global config + every registered user's current-month usage & resolved limit.

    Powers the admin Quotas tab. One bounded query joins the users registry, the
    current-month bucket and the per-user overrides; the effective limit/source/remaining
    is resolved per user in Python. Admin-gated by the route.
    """
    ensure_users_table()
    ensure_usage_monthly_table()
    ensure_user_quota_table()
    config = get_budget_config()
    sql = build_admin_usage_overview_query(
        full_table(USERS_V1_LOGICAL),
        full_table(USAGE_MONTHLY_V1_LOGICAL),
        full_table(USER_QUOTA_V1_LOGICAL),
        MAX_OVERVIEW_USERS,
    )
    rows = rows_to_json_safe(new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES))
    period_start = next_reset = None
    users = []
    for r in rows:
        period_start = r.get("period_start")
        next_reset = r.get("next_reset")
        spent = _money(r.get("spent_usd"))
        resolved = _resolve_limit(
            spent,
            bool(r.get("override_active")),
            r.get("override_limit"),
            r.get("override_expires"),
            config,
        )
        users.append({
            "user_id": r.get("user_id"),
            "display_name": r.get("display_name"),
            "user_groups": parse_json_list(r.get("user_groups")),
            "is_admin": bool(r.get("is_admin")),
            "spent_usd": spent,
            "input_tokens": _int(r.get("input_tokens")),
            "output_tokens": _int(r.get("output_tokens")),
            "request_count": _int(r.get("request_count")),
            "lifetime_cost": _money(r.get("lifetime_cost")),
            "last_usage_at": r.get("last_usage_at"),
            "override_active": bool(r.get("override_active")),
            "override_limit": (
                _money(r.get("override_limit")) if r.get("override_limit") is not None else None
            ),
            "override_expires": r.get("override_expires"),
            "override_note": r.get("override_note") or "",
            "limit_usd": resolved["limit_usd"],
            "limit_source": resolved["limit_source"],
            "limit_expires_at": resolved["limit_expires_at"],
            "remaining_usd": resolved["remaining_usd"],
            "blocked": resolved["blocked"],
        })
    base_eff, base_src, _ = _global_effective(config)
    return {
        "config": {
            "limit_usd": config["limit_usd"],
            "enabled": config["enabled"],
            "temp_limit_usd": config["temp_limit_usd"],
            "temp_expires_at": config["temp_expires_at"],
            "default_limit_usd": DEFAULT_MONTHLY_LIMIT_USD,
            "global_effective_usd": base_eff,
            "global_source": base_src,
            "currency": CURRENCY,
        },
        "period_start": period_start,
        "next_reset": next_reset,
        "users": users,
    }
