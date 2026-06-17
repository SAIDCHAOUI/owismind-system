"""Pure SQL text builders for Evidence Studio (NO dataiku import - unit-testable).

Same contract as storage/sql_builders.py: callers pass PRE-ESCAPED fragments
(values via sql_config.sql_value, identifiers via sql_config.pg_identifier) and
integer bounds - never raw user input. ``render_predicate`` takes the two quoting
functions as ARGUMENTS so the rendering logic itself stays import-free and
testable with stub quoters.
"""


def build_exchange_sql_query(table_ref, user_value_sql, exchange_value_sql):
    """The stored generated_sql of ONE exchange - ALWAYS owner-scoped."""
    return """
    SELECT generated_sql
    FROM {table}
    WHERE exchange_id = {exchange} AND user_id = {user}
    LIMIT 1
    """.format(table=table_ref, exchange=exchange_value_sql, user=user_value_sql)


def build_rows_query(table_ref, column_idents, conditions, order_ident, order_dir,
                     limit, offset):
    """One bounded, deterministic, read-only page of the evidence table.

    ORDER BY is mandatory (OFFSET pagination is non-deterministic without it);
    the direction is normalized here (anything not DESC becomes ASC).
    Each condition is parenthesized here so a fragment containing a top-level OR
    can never change the AND-conjunction's meaning.
    """
    n = int(limit)
    o = int(offset)
    direction = "DESC" if str(order_dir).upper() == "DESC" else "ASC"
    where = ("WHERE " + " AND ".join("({})".format(c) for c in conditions)) if conditions else ""
    return """
    SELECT {columns}
    FROM {table}
    {where}
    ORDER BY {order} {direction}
    LIMIT {n} OFFSET {o}
    """.format(columns=", ".join(column_idents), table=table_ref, where=where,
               order=order_ident, direction=direction, n=n, o=o)


def build_distinct_query(table_ref, column_ident, limit, conditions=None):
    """Bounded DISTINCT values of one column (the filter-chip picker).

    ``conditions`` (optional, pre-rendered, caller-escaped) scope the picker to the
    agent's locked predicates so it shows values within the agent's evidence, not the
    whole table. The DISTINCT+LIMIT runs in a subquery and only the bounded result is
    sorted - avoids forcing a full sort of every distinct value on a large table.
    """
    n = int(limit)
    where = ["{} IS NOT NULL".format(column_ident)]
    if conditions:
        where.extend("({})".format(c) for c in conditions)
    return """
    SELECT value FROM (
      SELECT DISTINCT {col} AS value
      FROM {table}
      WHERE {where}
      LIMIT {n}
    ) s
    ORDER BY value
    """.format(col=column_ident, table=table_ref, where=" AND ".join(where), n=n)


def render_predicate(pred, quote_ident, quote_value):
    """One predicate dict -> one SQL condition string.

    Raises ValueError on an unknown op - defensive only: ops are whitelisted by
    the parser (stored SQL) and the request validator (client filters) upstream.
    values arity (1 for binary/LIKE, 2 for BETWEEN, >= 1 for IN) is enforced
    upstream; on violation this raises IndexError or yields invalid SQL - it
    never silently widens scope.
    """
    col = quote_ident(pred["column"])
    op = pred["op"]
    values = pred.get("values") or []
    if op in ("=", "!=", "<", "<=", ">", ">="):
        return "{} {} {}".format(col, op, quote_value(values[0]))
    if op in ("IN", "NOT IN"):
        return "{} {} ({})".format(col, op, ", ".join(quote_value(v) for v in values))
    if op == "BETWEEN":
        return "{} BETWEEN {} AND {}".format(col, quote_value(values[0]), quote_value(values[1]))
    if op in ("LIKE", "ILIKE"):
        return "{} {} {}".format(col, op, quote_value(values[0]))
    if op == "IS NULL":
        return "{} IS NULL".format(col)
    if op == "IS NOT NULL":
        return "{} IS NOT NULL".format(col)
    raise ValueError("unsupported predicate op: {!r}".format(op))
