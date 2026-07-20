"""Pure SQL text builders (NO ``dataiku`` import) - unit-testable without the DSS env.

These assemble the exact SQL text used by the storage layer from fragments that the
caller has ALREADY escaped/quoted: values via ``sql_config.sql_value`` and the table
reference via ``sql_config.full_table``. Keeping the assembly here - free of the
``dataiku`` import that the rest of ``storage`` carries - lets the test suite assert
the query SHAPE (most importantly that every read is ALWAYS scoped to a single
user_id) without a live DSS runtime. No user input is interpolated here directly;
only pre-escaped fragments and integers bounded by the caller.
"""


def build_conversation_list_query(table_ref, user_value_sql, cursor_last_at_sql,
                                  cursor_session_sql, limit, title_maxlen):
    """Names-only conversation list (one row per session), newest-active first.

    Title = first user message of the session, cleaned into a tidy one-line name:
    newlines/tabs/repeated spaces are collapsed to single spaces and the value is
    trimmed BEFORE truncating to ``title_maxlen`` (so a multi-line prompt reads as a
    short label, not a wall of text). ``[[:space:]]`` is the POSIX class - no backslash
    escapes to mangle through ``str.format``. Keyset pagination on (last_at,
    session_id). All value fragments are caller-escaped; ints coerced.
    """
    n = int(limit)
    tlen = int(title_maxlen)
    if cursor_last_at_sql is not None and cursor_session_sql is not None:
        cursor_clause = (
            "WHERE (last_at < {cl}) OR (last_at = {cl} AND session_id < {cs})"
        ).format(cl=cursor_last_at_sql, cs=cursor_session_sql)
    else:
        cursor_clause = ""
    return """
    SELECT session_id, title, last_at
    FROM (
      SELECT session_id,
             COALESCE(LEFT(BTRIM(regexp_replace((ARRAY_AGG(user_text ORDER BY created_at ASC, exchange_id ASC))[1], '[[:space:]]+', ' ', 'g')), {tlen}), '') AS title,
             MAX(created_at) AS last_at
      FROM {table}
      WHERE user_id = {user}
      GROUP BY session_id
    ) s
    {cursor_clause}
    ORDER BY last_at DESC, session_id DESC
    LIMIT {n}
    """.format(table=table_ref, user=user_value_sql, tlen=tlen, cursor_clause=cursor_clause, n=n)


def build_session_messages_query(table_ref, columns, user_value_sql, session_value_sql, cap):
    """All exchanges of ONE session, chronological, user+session scoped, bounded.

    Used by /conversation (lazy load on click). Caller escapes values; cap coerced.
    """
    c = int(cap)
    return """
    SELECT {columns}
    FROM {table}
    WHERE user_id = {user} AND session_id = {session}
    ORDER BY created_at ASC, exchange_id ASC
    LIMIT {c}
    """.format(columns=columns, table=table_ref, user=user_value_sql, session=session_value_sql, c=c)


def build_usage_monthly_upsert(table_ref, user_value_sql,
                               in_tokens_sql, out_tokens_sql, cost_sql):
    """UPSERT one user's CURRENT-MONTH usage bucket (calendar month, server clock).

    ``period_start`` is ``date_trunc('month', now())::date`` so every calendar month is
    its own PRIMARY-KEY row - the future per-user monthly quota is one PK lookup and no
    reset job is ever needed. ON CONFLICT the counters are INCREMENTED (never
    overwritten) and one request is tallied. The token/cost fragments are server-computed
    numeric literals supplied by the caller (storage/usage); the period is a fixed SQL
    expression - neither is user input. Goes in ``pre_queries`` (a COMMIT must follow).
    """
    return """
    INSERT INTO {table} AS m
      (user_id, period_start, input_tokens, output_tokens, total_cost, request_count, updated_at)
    VALUES
      ({user}, date_trunc('month', now())::date, {in_t}, {out_t}, {cost}, 1, now())
    ON CONFLICT (user_id, period_start) DO UPDATE
       SET input_tokens  = m.input_tokens  + EXCLUDED.input_tokens,
           output_tokens = m.output_tokens + EXCLUDED.output_tokens,
           total_cost    = m.total_cost    + EXCLUDED.total_cost,
           request_count = m.request_count + 1,
           updated_at    = now()
    """.format(table=table_ref, user=user_value_sql,
               in_t=in_tokens_sql, out_t=out_tokens_sql, cost=cost_sql)


def build_users_usage_increment(table_ref, user_value_sql,
                                in_tokens_sql, out_tokens_sql, cost_sql):
    """Increment a user's LIFETIME cumulative usage counters (never overwrite).

    Adds this run's tokens/cost to the registry row and stamps ``last_usage_at``. Scoped
    to a single ``user_id``; a no-op (0 rows) if the user row does not exist yet - in
    practice the /me registry upsert always runs first, so the row is present. The
    token/cost fragments are server-computed numeric literals (storage/usage). Goes in
    ``pre_queries`` (a COMMIT must follow).
    """
    return """
    UPDATE {table}
       SET total_input_tokens  = total_input_tokens  + {in_t},
           total_output_tokens = total_output_tokens + {out_t},
           total_cost          = total_cost          + {cost},
           last_usage_at       = now()
     WHERE user_id = {user}
    """.format(table=table_ref, user=user_value_sql,
               in_t=in_tokens_sql, out_t=out_tokens_sql, cost=cost_sql)


# --- Monthly budget / usage status -------------------------------------------
# The "month" everywhere is the calendar month on the SERVER clock
# (date_trunc('month', now())), matching the usage_monthly UPSERT bucket key, so a
# user's spend resets on its own at the 1st (a new month is a new bucket row) with no
# reset job. ``next_reset`` is the first day of the following month (shown to the user).


def build_user_usage_status_query(monthly_ref, quota_ref, users_ref, user_value_sql):
    """One row of the caller's CURRENT-MONTH usage + any active per-user override.

    LEFT JOINs the current-month bucket, the per-user quota override and the user's
    lifetime counters onto a single anchor row, so a brand-new user (no bucket, no
    override) still returns one fully-COALESCEd row (zeros). ``override_active`` is
    decided in SQL against now() (NULL expires_at = permanent). The effective limit and
    its source are resolved in Python (the global default / temp boost live in settings,
    not SQL). All fragments are caller-escaped; nothing here is user input.
    """
    return """
    SELECT
      date_trunc('month', now())::date                          AS period_start,
      (date_trunc('month', now()) + interval '1 month')::date   AS next_reset,
      COALESCE(m.total_cost, 0)                                  AS spent_usd,
      COALESCE(m.input_tokens, 0)                                AS input_tokens,
      COALESCE(m.output_tokens, 0)                               AS output_tokens,
      COALESCE(m.request_count, 0)                               AS request_count,
      q.limit_usd                                                AS override_limit,
      q.expires_at                                               AS override_expires,
      (q.user_id IS NOT NULL AND (q.expires_at IS NULL OR q.expires_at > now())) AS override_active,
      COALESCE(us.total_input_tokens, 0)                         AS lifetime_input_tokens,
      COALESCE(us.total_output_tokens, 0)                        AS lifetime_output_tokens,
      COALESCE(us.total_cost, 0)                                 AS lifetime_cost,
      us.last_usage_at                                           AS last_usage_at
    FROM (SELECT {user} AS uid) base
    LEFT JOIN {monthly} m ON m.user_id = base.uid
                         AND m.period_start = date_trunc('month', now())::date
    LEFT JOIN {quota}   q ON q.user_id = base.uid
    LEFT JOIN {users}  us ON us.user_id = base.uid
    """.format(monthly=monthly_ref, quota=quota_ref, users=users_ref, user=user_value_sql)


def build_admin_usage_overview_query(users_ref, monthly_ref, quota_ref, cap):
    """Every registered user with their CURRENT-MONTH usage + override (admin quotas view).

    Anchored on the users registry (so users who never spent this month still appear),
    LEFT JOINing the current-month bucket and the quota override. Ordered by this month's
    spend (biggest spenders first), bounded by ``cap``. The effective limit per user is
    resolved in Python. Caller escapes nothing user-supplied here; cap is int-coerced.
    """
    n = int(cap)
    return """
    SELECT
      date_trunc('month', now())::date                          AS period_start,
      (date_trunc('month', now()) + interval '1 month')::date   AS next_reset,
      u.user_id, u.display_name, u.user_groups, u.is_admin,
      COALESCE(u.total_cost, 0)                                  AS lifetime_cost,
      u.last_usage_at,
      COALESCE(m.total_cost, 0)                                  AS spent_usd,
      COALESCE(m.input_tokens, 0)                                AS input_tokens,
      COALESCE(m.output_tokens, 0)                               AS output_tokens,
      COALESCE(m.request_count, 0)                               AS request_count,
      q.limit_usd                                                AS override_limit,
      q.expires_at                                               AS override_expires,
      q.note                                                     AS override_note,
      (q.user_id IS NOT NULL AND (q.expires_at IS NULL OR q.expires_at > now())) AS override_active
    FROM {users} u
    LEFT JOIN {monthly} m ON m.user_id = u.user_id
                         AND m.period_start = date_trunc('month', now())::date
    LEFT JOIN {quota}   q ON q.user_id = u.user_id
    ORDER BY COALESCE(m.total_cost, 0) DESC, u.user_id
    LIMIT {n}
    """.format(users=users_ref, monthly=monthly_ref, quota=quota_ref, n=n)


def build_user_quota_upsert(quota_ref, user_value_sql, limit_sql,
                            expires_days, note_sql, updated_by_sql):
    """UPSERT one user's budget override (permanent when ``expires_days`` is None).

    ``expires_days`` (int or None) is the temporary-boost duration; None stores NULL
    (permanent). When set, ``expires_at = now() + interval '1 day' * <days>`` - the days
    count is int-coerced here (never user text), so the multiplied interval is injection-
    safe and the expiry is anchored on the server clock. ``limit_sql`` is a server-computed
    numeric literal; ``user``/``note``/``updated_by`` are caller-escaped. Goes in
    ``pre_queries`` (a COMMIT must follow).
    """
    if expires_days is None:
        expires_sql = "NULL"
    else:
        d = int(expires_days)
        expires_sql = "now() + (interval '1 day' * {})".format(d)
    return """
    INSERT INTO {table} AS q
      (user_id, limit_usd, expires_at, note, updated_at, updated_by)
    VALUES ({user}, {lim}, {exp}, {note}, now(), {by})
    ON CONFLICT (user_id) DO UPDATE
       SET limit_usd  = EXCLUDED.limit_usd,
           expires_at = EXCLUDED.expires_at,
           note       = EXCLUDED.note,
           updated_at = now(),
           updated_by = EXCLUDED.updated_by
    """.format(table=quota_ref, user=user_value_sql, lim=limit_sql,
               exp=expires_sql, note=note_sql, by=updated_by_sql)


def build_user_quota_clear(quota_ref, user_values_csv_sql):
    """DELETE the override rows for a set of users (revert them to the global limit).

    ``user_values_csv_sql`` is a comma-joined list of ALREADY-escaped user_id literals
    (the caller builds it via sql_value). A no-op when no row matches. Goes in
    ``pre_queries`` (a COMMIT must follow).
    """
    return "DELETE FROM {table} WHERE user_id IN ({ids})".format(
        table=quota_ref, ids=user_values_csv_sql
    )


def build_ancestor_chain_query(table_ref, columns, user_value_sql,
                               start_exchange_sql, max_depth, cap):
    """Walk parent_exchange_id UP from a start exchange to the root (recursive CTE).

    User-scoped in BOTH the anchor and the recursive member; depth-bounded
    (anti-cycle) and LIMIT-bounded. Returns the chain newest-first (caller reverses
    to chronological, then trims to the last N messages). Values are caller-escaped;
    depth/cap are int-coerced here.
    """
    d = int(max_depth)
    c = int(cap)
    return """
    WITH RECURSIVE chain AS (
      SELECT *, 1 AS _depth FROM {table}
      WHERE exchange_id = {start} AND user_id = {user}
      UNION ALL
      SELECT t.*, chain._depth + 1 FROM {table} t
      JOIN chain ON t.exchange_id = chain.parent_exchange_id
      WHERE t.user_id = {user} AND chain._depth < {d}
    )
    SELECT {columns} FROM chain
    ORDER BY created_at DESC, exchange_id DESC
    LIMIT {c}
    """.format(table=table_ref, start=start_exchange_sql, user=user_value_sql, d=d, columns=columns, c=c)
