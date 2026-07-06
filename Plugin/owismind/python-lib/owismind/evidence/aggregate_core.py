"""Shared aggregate engine for the Evidence + Source Data exact-totals paths.

Both /source/aggregate (raw dataset exploration) and /evidence/aggregate (the
per-exchange table pre-filtered by the answer's stored SQL) build the SAME
structured aggregation over a WHERE the caller assembles: an optional grouping
(optionally DATE_TRUNC'd by a whitelisted calendar bucket) plus 1..N whitelisted
measures. This module is the SINGLE implementation of the SELECT / GROUP BY /
ORDER BY pieces + the type gates, so the two services differ only in how they
resolve their table + conditions, never in how a measure or a bucket renders.

Pure text + gates (NO dataiku import): callers pass the LIVE column list (each a
``{"name", "type"}`` dict) + colmap (lowercased real name -> real name) their own
context already resolved, and get back pre-rendered, caller-escaped fragments to
hand to ``query_builders.build_aggregate_query``. Gates raise
``evidence.service.EvidenceError`` with the same stable codes the source explorer
has always used.
"""

from owismind.evidence.service import EvidenceError
from owismind.storage.sql_config import is_numeric_type, is_temporal_type, pg_identifier

# Frozen aggregate templates: only these whitelisted functions ever reach SQL, keyed by
# the fn the validator already whitelisted. ``{col}`` is filled with a ``pg_identifier``
# (COUNT(*) takes none). Building from a frozen dict (never from raw input) means an
# unexpected fn can never render an arbitrary function call.
#
# ``median`` is PERCENTILE_CONT(0.5), an ORDERED-SET aggregate: PostgreSQL sorts the
# filtered set to find the interpolated 50th percentile, so it is costlier than the plain
# streaming aggregates (SUM/AVG/COUNT) on a large unindexed scan. It stays whitelisted for
# the exact-total use case (business users want a true median, not an average skewed by
# outliers); the inherited 30s statement_timeout (applied by each service's bounded
# executor) is the backstop that bounds the worst case, exactly as for every other query.
_AGG_TEMPLATES = {
    "count": "COUNT(*)",
    "count_distinct": "COUNT(DISTINCT {col})",
    "sum": "SUM({col})",
    "avg": "AVG({col})",
    "median": "PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY {col})",
    "min": "MIN({col})",
    "max": "MAX({col})",
}
# Frozen DATE_TRUNC units keyed by the validated bucket, so only a whitelisted calendar
# unit is ever inlined into the query (never a raw client string).
_BUCKET_UNITS = {"month": "month", "quarter": "quarter", "year": "year"}


def _measure_select_exprs(columns, colmap, measures):
    """Render the whitelisted measures into aliased select expressions ``m0..mN``.

    Each measure ``{fn, column}`` (validated + whitelisted upstream) becomes one
    ``<AGG> AS mI`` projection. ``count`` is COUNT(*) (no column). Every other fn
    resolves its column against the LIVE ``colmap``: an unknown column ->
    'invalid_aggregate_column'; ``sum``/``avg``/``median`` additionally require a NUMERIC
    column ('invalid_aggregate_column' otherwise), while ``count_distinct``/``min``/``max``
    accept any existing column. The type gate reads the LIVE ``columns`` (real name ->
    live type). Returns the list of pre-rendered, caller-escaped select expressions.
    """
    typemap = {c["name"]: (c.get("type") or "") for c in columns}
    exprs = []
    for i, m in enumerate(measures):
        fn = m["fn"]
        if fn == "count":
            expr = _AGG_TEMPLATES["count"]
        else:
            col = colmap.get(m["column"].lower())
            if col is None:
                raise EvidenceError("invalid_aggregate_column", 400)
            if fn in ("sum", "avg", "median") and not is_numeric_type(typemap.get(col, "")):
                raise EvidenceError("invalid_aggregate_column", 400)
            expr = _AGG_TEMPLATES[fn].format(col=pg_identifier(col))
        exprs.append("{} AS m{}".format(expr, i))
    return exprs


def build_aggregate_plan(columns, colmap, group, measures):
    """The SQL pieces both aggregate services need, gated against the LIVE schema.

    ``columns`` is the live column list (``{"name", "type"}`` dicts), ``colmap`` its
    lowercased-name -> real-name map, ``group`` an optional ``{column, bucket}`` and
    ``measures`` the validated whitelist of ``{fn, column}``. Measures are rendered (and
    type-gated) FIRST, so a bad measure is caught before any group work - mirroring the
    source explorer's evaluation order. Returns
    ``{measure_exprs, select_exprs, group_exprs, order_expr, order_dir}``:

      - ``group is None`` (ungrouped totals): ``select_exprs`` are the bare measures,
        ``group_exprs`` empty, no ORDER BY (an aggregate with no GROUP BY is one row).
      - ``group`` set: the group column (optionally DATE_TRUNC'd by a whitelisted calendar
        ``bucket`` - which requires a TEMPORAL column, 'invalid_group_bucket' otherwise; an
        unknown group column -> 'invalid_filter_column') is aliased ``key`` and prepended
        to the measures; ranked by the first measure (``m0`` DESC) or, when bucketed,
        chronologically (``key`` ASC). The caller applies the row cap / totals query.

    Raises ``EvidenceError`` with the stable source-explorer codes on any gate failure.
    """
    measure_exprs = _measure_select_exprs(columns, colmap, measures)
    if group is None:
        return {
            "measure_exprs": measure_exprs,
            "select_exprs": measure_exprs,
            "group_exprs": [],
            "order_expr": None,
            "order_dir": None,
        }
    group_col = colmap.get(group["column"].lower())
    if group_col is None:
        raise EvidenceError("invalid_filter_column", 400)
    ident = pg_identifier(group_col)
    bucket = group["bucket"]
    if bucket is None:
        group_expr = ident
        order_expr, order_dir = "m0", "desc"     # rank groups by the first measure
    else:
        typemap = {c["name"]: (c.get("type") or "") for c in columns}
        if not is_temporal_type(typemap.get(group_col, "")):
            raise EvidenceError("invalid_group_bucket", 400)
        # Unit comes from the frozen dict (never the raw bucket string).
        group_expr = "DATE_TRUNC('{}', {})".format(_BUCKET_UNITS[bucket], ident)
        # DESC so the group CAP keeps the MOST RECENT buckets on a long history
        # (ASC would keep the earliest 50 months and silently drop this year).
        # The frontend re-sorts the returned buckets chronologically for display.
        order_expr, order_dir = "key", "desc"
    return {
        "measure_exprs": measure_exprs,
        "select_exprs": ["{} AS key".format(group_expr)] + measure_exprs,
        "group_exprs": [group_expr],
        "order_expr": order_expr,
        "order_dir": order_dir,
    }
