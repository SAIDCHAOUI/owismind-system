"""Source Data Explorer service - browse the RAW project datasets an agent is
configured with (admin-authored), read-only.

Stateless pipeline, mirroring the Evidence read path everywhere (same discovery
cache, same dataset column resolution, same bounded read-only execution):
  1. Resolve the opaque agent key to its enabled whitelist entry (settings API).
  2. Re-validate its admin-authored SOURCES block; index it by the client's source id.
  3. Match the source's dataset NAME against the project's discovered SQL datasets
     (evidence.service._dataset_candidates - the SAME cache, never forked).
  4. Build the executed table reference from the RESOLVED candidate (never from the
     profile text) and load the live column map, exactly like evidence._context.
  5. Rebuild a BOUNDED read-only SELECT from STRUCTURED filters + an optional free-text
     search over all columns - the client never sends SQL.

Execution runs on the matched DATASET's own connection (a fresh SQLExecutor2), with
the same transaction-scoped read-only + statement_timeout pre-queries as Evidence.
Errors reuse evidence.service.EvidenceError (stable code + HTTP status).
"""

import logging

from owismind.evidence import service as evidence_service
from owismind.evidence.service import (
    EvidenceError,
    _EVIDENCE_TIMEOUT_PRE_QUERIES,
    _quote_value,
)
from owismind.evidence.aggregate_core import build_aggregate_plan
from owismind.evidence.query_builders import (
    build_aggregate_query,
    build_distinct_query,
    build_rows_query,
    render_predicate,
)
from owismind.evidence.source_search import build_search_condition
from owismind.security.validation import validate_sources_block
from owismind.storage import settings
from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import pg_identifier

logger = logging.getLogger(__name__)

# Row-window pagination is client-driven: the validated `limit`/`offset` come in per
# request (bounded in security.validation), so there is no fixed page size here.
DISTINCT_LIMIT = 100  # picker values cap (mirror of evidence.service.DISTINCT_LIMIT)


def _quote_literal(value):
    """A standard single-quoted SQL string literal (doubles embedded quotes).

    Used only for the free-text search condition (the accent-fold constants and the
    already LIKE-escaped, server-derived needle). Kept as a plain standard-string
    quote - like the attribute-lookup tool - so the ``ESCAPE '\\'`` clause behaves
    under ``standard_conforming_strings`` (an E-string would swallow the backslash).
    """
    return "'" + str(value).replace("'", "''") + "'"


def _resolve_source(agent_key, source_id):
    """Resolve ``(agent_key, source_id)`` to an executable source context, or raise.

    Returns ``{label, dataset, table_ref, columns, colmap}``. The dataset is matched
    by NAME (case-insensitive) against the discovered project SQL datasets, and the
    executed table reference is built from the RESOLVED candidate (never the profile
    text). Raises EvidenceError with a stable code + status: 'source_not_found' (404)
    when the agent / source index does not resolve, 'no_matching_dataset' (404) when
    the source dataset is not a discovered project dataset, and the same schema/table
    codes as Evidence for a malformed live schema.
    """
    agent = settings.resolve_enabled_agent(agent_key)
    if not isinstance(agent, dict):
        raise EvidenceError("source_not_found", 404)
    profile = agent.get("profile") if isinstance(agent.get("profile"), dict) else {}
    # Re-validate the block (defense in depth): the id is the index into the SAME
    # validated list the client saw via /agents, so the ids always line up.
    sources = validate_sources_block(profile.get("sources"))
    if not (0 <= source_id < len(sources)):
        raise EvidenceError("source_not_found", 404)
    entry = sources[source_id]

    want = entry["dataset"].lower()
    match = None
    for cand in evidence_service._dataset_candidates():
        if (cand.get("name") or "").lower() == want:
            match = cand
            break
    if match is None:
        logger.info(
            "source - no_matching_dataset: agent source %r matched none of the "
            "discovered project SQL datasets", entry["dataset"],
        )
        raise EvidenceError("no_matching_dataset", 404)

    try:
        schema_name = match.get("schema")
        table_ref = (
            "{}.{}".format(pg_identifier(schema_name), pg_identifier(match["table"]))
            if schema_name else pg_identifier(match["table"])
        )
    except ValueError:
        raise EvidenceError("dataset_table_invalid")

    columns = evidence_service._dataset_columns(match["name"])  # raises EvidenceError on failure
    colmap = {}
    for c in columns:
        low = c["name"].lower()
        if low in colmap:
            # Two columns differing only by case make chip/filter resolution
            # ambiguous - refuse rather than guess (same rule as Evidence).
            raise EvidenceError("dataset_schema_invalid")
        colmap[low] = c["name"]

    return {
        "label": entry["label"],
        "dataset": match["name"],
        "table_ref": table_ref,
        "columns": columns,
        "colmap": colmap,
    }


def _run_source_query(ctx, query, op_name):
    """Execute one bounded read-only query on the matched dataset's connection.

    Fresh executor, transaction-scoped timeout + read-only pre-queries, JSON-safe
    rows, stable 'query_failed' on any DB error (mirror of _run_evidence_query).
    """
    try:
        df = evidence_service._evidence_executor(ctx["dataset"]).query_to_df(
            query,
            pre_queries=list(_EVIDENCE_TIMEOUT_PRE_QUERIES),
        )
    except Exception:
        logger.exception("%s - query failed (dataset=%s)", op_name, ctx["dataset"])
        raise EvidenceError("query_failed")
    return rows_to_json_safe(df)


def source_meta(agent_key, source_id):
    """The descriptor of one configured source: its label + live column list.

    ``{"label", "columns": [{"name", "type"}]}``; ``type`` is best-effort from the
    live schema ("" when unknown). Raises EvidenceError on an unresolved source.
    """
    ctx = _resolve_source(agent_key, source_id)
    return {
        "label": ctx["label"],
        "columns": [{"name": c["name"], "type": c.get("type") or ""} for c in ctx["columns"]],
    }


def _source_conditions(ctx, q, filters):
    """The WHERE conditions for a source query: structured filters + free-text search.

    Shared by ``source_rows`` and ``source_aggregate`` so both paths build byte-identical
    predicates over the SAME filtered set. Each ``{column, op, values}`` filter is
    resolved against the LIVE colmap (unknown column -> 'invalid_filter_column'). A
    ``BETWEEN`` chip (validated upstream to exactly 2 values, /source/* only) is rendered
    as-is - a date-range low/high whose bounds both quote through the same ``_quote_value``;
    any other op is normalized exactly as the row window does (a single ``=`` value stays
    ``=``, otherwise ``IN``). ``q`` adds one accent-folded ILIKE over ALL columns (empty /
    too-short -> no search). Returns a list of pre-rendered, caller-escaped conditions.
    """
    conditions = []
    for f in filters:
        column = ctx["colmap"].get(f["column"].lower())
        if column is None:
            raise EvidenceError("invalid_filter_column", 400)
        if f["op"] == "BETWEEN":
            op = "BETWEEN"
        else:
            op = "=" if (f["op"] == "=" and len(f["values"]) == 1) else "IN"
        conditions.append(render_predicate(
            {"column": column, "op": op, "values": f["values"]},
            pg_identifier, _quote_value,
        ))
    search = build_search_condition(
        [c["name"] for c in ctx["columns"]], q, pg_identifier, _quote_literal,
    )
    if search:
        conditions.append(search)
    return conditions


def source_rows(agent_key, source_id, q, filters, limit, offset, sort):
    """One bounded window of the source dataset, filtered + optionally searched. Read-only.

    ``limit``/``offset`` (validated + clamped upstream) define the row window: a LIMIT
    of ``limit + 1`` yields ``has_more`` without a COUNT(*). ``filters`` (validated
    upstream) are resolved against the LIVE schema (unknown column ->
    'invalid_filter_column'); ``q`` adds one accent-folded ILIKE over ALL columns
    (empty / too-short -> no search). Default order is the first schema column ASC; an
    explicit ``sort`` column is validated against the schema ('invalid_sort_column').
    Returns ``{"rows", "has_more", "offset"}``.
    """
    ctx = _resolve_source(agent_key, source_id)
    conditions = _source_conditions(ctx, q, filters)

    if sort:
        order_col = ctx["colmap"].get(sort["column"].lower())
        if order_col is None:
            raise EvidenceError("invalid_sort_column", 400)
        order_dir = sort["dir"]
    else:
        # Deterministic default: OFFSET pagination needs a stable ORDER BY (same
        # accepted trade-off as Evidence - the first column may be non-sortable).
        order_col, order_dir = ctx["columns"][0]["name"], "asc"

    query = build_rows_query(
        table_ref=ctx["table_ref"],
        column_idents=[pg_identifier(c["name"]) for c in ctx["columns"]],
        conditions=conditions,
        order_ident=pg_identifier(order_col),
        order_dir=order_dir,
        limit=limit + 1,              # one extra row -> has_more without COUNT(*)
        offset=offset,
    )
    rows = _run_source_query(ctx, query, "source_rows")
    has_more = len(rows) > limit
    logger.info(
        "source_rows - agent=%s source=%d dataset=%s limit=%d offset=%d conditions=%d returned=%d",
        agent_key, source_id, ctx["dataset"], limit, offset, len(conditions),
        min(len(rows), limit),
    )
    return {"rows": rows[:limit], "has_more": has_more, "offset": offset}


def source_distinct(agent_key, source_id, column, q=None, filters=None, scope_q=None):
    """Bounded distinct values of ONE column (the CASCADING filter-chip picker).

    Unlike Evidence there are no locked agent predicates, but the picker is still
    CASCADING: it only offers values that co-occur with the OTHER currently-active
    filters + the table-level search, so a business user can never pick a value with
    zero rows under an active filter. ``filters`` (the OTHER chips, the client omits the
    one being edited) + ``scope_q`` (the table-level search over ALL columns) scope the
    picker through the SHARED ``_source_conditions`` - byte-identical to the predicates
    the row window builds. On top of that scope, the picker's OWN free-text ``q`` narrows
    it to values of THAT column matching the term (one accent-folded ILIKE over the single
    resolved column; empty / too-short -> no column search). With no filters and no
    scope_q this is byte-identical to the old picker. Raises 'invalid_filter_column'
    (400) when the picked column (or any filter column) is not on the live schema.
    """
    ctx = _resolve_source(agent_key, source_id)
    resolved_col = ctx["colmap"].get(column.lower())
    if resolved_col is None:
        raise EvidenceError("invalid_filter_column", 400)
    # Cascading scope: the OTHER filters + the table-level search over ALL columns
    # (scope_q travels as the shared conditions' q). Empty scope -> no conditions.
    conditions = _source_conditions(ctx, scope_q or "", filters or [])
    # The picker's OWN search on the TARGET column only, appended last (as before).
    search = build_search_condition(
        [resolved_col], q, pg_identifier, _quote_literal,
    )
    if search:
        conditions.append(search)
    query = build_distinct_query(
        table_ref=ctx["table_ref"],
        column_ident=pg_identifier(resolved_col),
        limit=DISTINCT_LIMIT + 1,     # one extra value -> truncated without a false positive
        conditions=conditions,
    )
    values = [r["value"] for r in _run_source_query(ctx, query, "source_distinct")]
    truncated = len(values) > DISTINCT_LIMIT
    logger.info(
        "source_distinct - agent=%s source=%d dataset=%s column=%s search=%s conditions=%d returned=%d truncated=%s",
        agent_key, source_id, ctx["dataset"], resolved_col, search is not None,
        len(conditions), min(len(values), DISTINCT_LIMIT), truncated,
    )
    return {"values": values[:DISTINCT_LIMIT], "truncated": truncated}


def source_aggregate(agent_key, source_id, q, filters, group, measures, limit):
    """Database-EXACT aggregates over the FULL filtered set of a source dataset. Read-only.

    The row window is only a page; this computes exact totals the database evaluates over
    every matching row. The SAME ``filters`` + free-text ``q`` as ``source_rows`` scope
    the set (shared ``_source_conditions``), so the aggregation matches what the user sees
    filtered. ``measures`` are whitelisted aggregate functions (validated upstream), typed
    against the LIVE schema here (sum/avg/median need a numeric column). ``group`` is optional:

      - ``group is None``: one ungrouped totals row over the whole filtered set (a single
        bounded query, LIMIT 1); ``totals`` is None, ``truncated`` is False.
      - ``group`` set: the group column (optionally DATE_TRUNC'd by a whitelisted calendar
        ``bucket`` - which requires a TEMPORAL column, 'invalid_group_bucket' otherwise) is
        ranked by the first measure (ORDER BY m0 DESC) or, when bucketed, chronologically
        (ORDER BY key ASC). The group list is CAPPED at ``limit`` (LIMIT ``limit + 1`` to
        flag truncation without a COUNT) and a SECOND bounded query returns the ungrouped
        ``totals`` over the same WHERE, so the caller can compute exact shares of total.

    Instance safety: read-only + statement_timeout pre-queries are inherited from
    ``_run_source_query``; a request runs at most TWO bounded queries and a grouped result
    is always capped, so no unbounded scan or result set can pin the dataset connection.
    Returns ``{"rows", "totals", "truncated"}`` (rows/totals are JSON-safe).
    """
    ctx = _resolve_source(agent_key, source_id)
    conditions = _source_conditions(ctx, q, filters)
    # Shared engine: the SAME measure/group/bucket rendering + type gates the Evidence
    # aggregate path uses (one implementation, byte-identical SQL fragments).
    plan = build_aggregate_plan(ctx["columns"], ctx["colmap"], group, measures)

    if group is None:
        # Ungrouped: an aggregate with no GROUP BY always yields exactly one row (COUNT 0 /
        # SUM NULL over an empty set), so LIMIT 1 is the whole result and no totals query
        # or cap is needed.
        query = build_aggregate_query(
            table_ref=ctx["table_ref"], select_exprs=plan["select_exprs"],
            conditions=conditions, group_exprs=plan["group_exprs"],
            order_expr=plan["order_expr"], order_dir=plan["order_dir"], limit=1,
        )
        rows = _run_source_query(ctx, query, "source_aggregate")
        logger.info(
            "source_aggregate - agent=%s source=%d dataset=%s grouped=False "
            "measures=%d conditions=%d",
            agent_key, source_id, ctx["dataset"], len(measures), len(conditions),
        )
        return {"rows": rows, "totals": None, "truncated": False}

    # Grouped: the plan aliases (and optionally buckets) the group column; two bounded queries.
    group_query = build_aggregate_query(
        table_ref=ctx["table_ref"], select_exprs=plan["select_exprs"], conditions=conditions,
        group_exprs=plan["group_exprs"], order_expr=plan["order_expr"],
        order_dir=plan["order_dir"],
        limit=limit + 1,          # one extra group -> truncated without a COUNT
    )
    grouped_rows = _run_source_query(ctx, group_query, "source_aggregate")
    truncated = len(grouped_rows) > limit

    totals_query = build_aggregate_query(
        table_ref=ctx["table_ref"], select_exprs=plan["measure_exprs"], conditions=conditions,
        group_exprs=[], order_expr=None, order_dir=None, limit=1,
    )
    totals_rows = _run_source_query(ctx, totals_query, "source_aggregate")
    totals = totals_rows[0] if totals_rows else None

    logger.info(
        "source_aggregate - agent=%s source=%d dataset=%s grouped=True bucket=%s "
        "measures=%d conditions=%d groups=%d truncated=%s",
        agent_key, source_id, ctx["dataset"], group["bucket"], len(measures), len(conditions),
        min(len(grouped_rows), limit), truncated,
    )
    return {"rows": grouped_rows[:limit], "totals": totals, "truncated": truncated}


def list_source_dataset_names():
    """Sorted NAMES of the project's discovered SQL datasets (the admin picker).

    Reuses the SAME TTL-cached discovery as Evidence (never forks it); returns [] when
    none are discovered. Callers scope this behind the admin guard.
    """
    return sorted(c["name"] for c in evidence_service._dataset_candidates())
