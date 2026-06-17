"""Per-user token/cost usage accounting (direct SQL, no DSS Flow).

``webapp_chat_v5`` holds the AUTHORITATIVE per-exchange tokens/cost (written with the
answer in ``chat_v5.save_assistant_message``). This module maintains the two
DENORMALISED accelerators that make usage control cheap:
  - ``webapp_users_v1`` LIFETIME cumulative counters (incremented once per response);
  - ``webapp_usage_monthly_v1`` per-(user, calendar-month) bucket - a single
    PRIMARY-KEY row per month, so the planned per-user monthly quota is one PK lookup
    and needs no reset job (a new month is naturally a new row).

Both are reconstructible by summing chat_v5, which stays the source of truth: a failed
increment here is logged and swallowed by the caller, never blocking the user's answer.
The two increments run in ONE committed transaction so the lifetime cumulative and the
monthly bucket never diverge from each other.

All values written here are SERVER-COMPUTED (LLM Mesh trace totals + the auth-resolved
user_id) - strictly coerced to non-negative numbers and inlined as numeric literals,
with the user_id escaped via ``sql_value``; nothing is taken from the request body.
"""

import logging

from owismind.storage.migrations import (
    USAGE_MONTHLY_V1_LOGICAL,
    USERS_V1_LOGICAL,
    ensure_usage_monthly_table,
    ensure_users_table,
)
from owismind.storage.sql_builders import (
    build_usage_monthly_upsert,
    build_users_usage_increment,
)
from owismind.storage.sql_config import full_table, new_executor, sql_value

logger = logging.getLogger(__name__)


def _coerce_int(value):
    """Non-negative int from a trace value (missing/garbage/negative -> 0)."""
    try:
        n = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def _coerce_cost(value):
    """Non-negative float from a trace cost (missing/garbage/negative -> 0.0)."""
    try:
        f = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return f if f > 0 else 0.0


def record_usage(user_id, usage):
    """Add ONE run's token/cost totals to the user's lifetime + current-month buckets.

    ``usage`` is the worker's captured ``usage_summary`` totals
    (``promptTokens``/``completionTokens``/``estimatedCost``); non-positive/missing
    values coerce to 0. No-op when there is nothing meaningful to record (an
    early-stopped run with no footer) or no user_id. Called exactly once per agent run
    (right after the assistant message is persisted), so each exchange increments the
    aggregates exactly once. Best-effort by contract: the caller wraps this in a
    try/except - a failure here never affects the answer already on screen, and the
    aggregates can be rebuilt from chat_v5.
    """
    if not user_id or not isinstance(usage, dict):
        return
    in_tokens = _coerce_int(usage.get("promptTokens"))
    out_tokens = _coerce_int(usage.get("completionTokens"))
    cost = _coerce_cost(usage.get("estimatedCost"))
    if in_tokens == 0 and out_tokens == 0 and cost == 0.0:
        return  # nothing to record (e.g. a run stopped before the usage footer arrived)

    ensure_users_table()
    ensure_usage_monthly_table()

    user_sql = sql_value(user_id)
    # Server-computed numerics inlined as bare literals (cost with fixed decimals to
    # avoid scientific notation) - never user input, so this mirrors bool_literal.
    in_sql = str(in_tokens)
    out_sql = str(out_tokens)
    cost_sql = "{:.10f}".format(cost)

    monthly_sql = build_usage_monthly_upsert(
        full_table(USAGE_MONTHLY_V1_LOGICAL), user_sql, in_sql, out_sql, cost_sql
    )
    users_sql = build_users_usage_increment(
        full_table(USERS_V1_LOGICAL), user_sql, in_sql, out_sql, cost_sql
    )
    # ONE transaction: the monthly bucket and the lifetime cumulative move together.
    new_executor().query_to_df(
        "SELECT 1 AS usage_recorded",
        pre_queries=[monthly_sql, users_sql],
        post_queries=["COMMIT"],
    )
    logger.info(
        "record_usage - user_id=%s in=%d out=%d cost=%.6f",
        user_id,
        in_tokens,
        out_tokens,
        cost,
    )
