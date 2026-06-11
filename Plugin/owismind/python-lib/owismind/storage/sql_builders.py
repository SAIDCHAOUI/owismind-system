"""Pure SQL text builders (NO ``dataiku`` import) — unit-testable without the DSS env.

These assemble the exact SQL text used by the storage layer from fragments that the
caller has ALREADY escaped/quoted: values via ``sql_config.sql_value`` and the table
reference via ``sql_config.full_table``. Keeping the assembly here — free of the
``dataiku`` import that the rest of ``storage`` carries — lets the test suite assert
the query SHAPE (most importantly that every read is ALWAYS scoped to a single
user_id) without a live DSS runtime. No user input is interpolated here directly;
only pre-escaped fragments and integers bounded by the caller.
"""


def build_conversation_list_query(table_ref, user_value_sql, cursor_last_at_sql,
                                  cursor_session_sql, limit, title_maxlen):
    """Names-only conversation list (one row per session), newest-active first.

    Title = first user message of the session, server-truncated. Keyset pagination
    on (last_at, session_id). All value fragments are caller-escaped; ints coerced.
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
             COALESCE(LEFT((ARRAY_AGG(user_text ORDER BY created_at ASC, exchange_id ASC))[1], {tlen}), '') AS title,
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
