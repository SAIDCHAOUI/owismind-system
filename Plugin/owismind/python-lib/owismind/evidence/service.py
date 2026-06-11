"""Evidence Studio service — re-runs the agent's stored SELECT scope, read-only.

Stateless pipeline (everything re-derived per call, nothing new is stored):
  1. Load the exchange's stored generated_sql — ALWAYS owner-scoped on user_id.
  2. Pick the LAST successful SQL item (the agent's final refined query).
  3. Parse it (evidence.sql_parse — pure) into table + predicates + fragment.
  4. Match the table against the project's auto-discovered SQL datasets (no admin
     whitelist to configure); the executed reference comes from the resolved dataset.
  5. Read the dataset's schema (METADATA only, TTL-cached) and resolve every column.
  6. Rebuild a BOUNDED read-only SELECT from STRUCTURED filters — the client
     never sends SQL; locked chips travel as ids and are re-derived here.

Trust layer (frozen contract: docs/superpowers/specs/2026-06-10-evidence-trust-
layer-design.md §§2-3): /evidence/meta additionally carries ``source``,
``queries`` (a bounded summary of every stored SQL item), ``verification`` (an
HONEST deterministic level — never "verified because SQL ran"), ``explanation``
(business-language steps from evidence.sql_explain), ``result`` (the EXACT rows
the agent saw, when captured) and ``drilldown`` (group-key drill availability).
/evidence/rows accepts an optional ``drill`` list whose columns are RE-DERIVED
server-side from the stored SQL — the client's column list is never trusted.
No LLM is ever involved in this proof path; every block is computed by pure,
unit-tested functions below.

Execution runs on the matched DATASET's own connection
(SQLExecutor2(dataset=...)), not the chat-storage connection. Read-only:
no writes, no COMMIT, LIMIT everywhere, no unbounded COUNT(*), and the whole
transaction is forced read-only via SET LOCAL. Scope is the webapp's OWN
project's SQL datasets only.
"""

import logging
import threading
import time

import dataiku
from dataiku import SQLExecutor2

from owismind.evidence import sql_parse
from owismind.evidence.query_builders import (
    build_distinct_query,
    build_exchange_sql_query,
    build_rows_query,
    render_predicate,
)
from owismind.evidence.whitelist import match_whitelist
from owismind.storage.migrations import CHAT_V5_LOGICAL
from owismind.storage.serialization import parse_json_list, rows_to_json_safe
from owismind.storage.sql_config import (
    PROJECT_KEY,
    bool_literal,
    full_table,
    new_executor,
    pg_identifier,
    sql_value,
)

# Workstream IMPL-1 module (pure SQL explainer). Guarded import: when the module
# is not shipped yet (or fails to import) the trust layer DEGRADES honestly —
# explanation {"ok": False}, verification capped at 'source_identified', drill
# unavailable ('not_supported') — instead of crashing every /evidence/* route.
try:
    from owismind.evidence import sql_explain as _sql_explain
except ImportError:  # honest degradation, never a hard dependency
    _sql_explain = None

logger = logging.getLogger(__name__)

PAGE_SIZE = 50       # rows per page (LIMIT PAGE_SIZE+1 -> has_more, no COUNT(*))
DISTINCT_LIMIT = 100 # picker values cap

# --- Trust-layer bounds (mirrors of the frozen contract §§2-3) -----------------
# Explanation steps are display data: the explainer owns the <=15 cap, but we
# re-cap here at the trust boundary (mirrored caps, same idiom as capture.py).
MAX_EXPLANATION_STEPS = 15
# At most this many human-readable dropped-predicate strings are surfaced (the
# COUNT stays exact; only the display list is bounded).
MAX_DROPPED_DISPLAY = 10
# Each dropped-predicate display string is bounded (same cap as opaque steps).
MAX_DISPLAY_CHARS = 120
# Server-side mirror of validation.MAX_EVIDENCE_DRILL (defense in depth: the
# service must stay safe even if a future caller skips the request validator).
MAX_DRILL_CONDITIONS = 8
# Defensive bound on explain group keys before the colmap intersection.
_MAX_GROUP_KEYS = 50

# Source datasets are DISCOVERED automatically: the project's own SQL-backed
# datasets (no admin whitelist to configure). The agent's parsed FROM table must
# match one of them, otherwise Evidence stays degraded. Connector type that backs
# the chat storage (and therefore the agents' SQL datasets) on this instance.
_SQL_DATASET_TYPES = {"PostgreSQL"}
# Defensive cap on the discovery scan (instance safety on a huge project).
_MAX_EVIDENCE_DATASETS = 300

# Resolved (schema, table) of the project's SQL datasets, cached process-wide with
# a short TTL: list_datasets()/get_location_info() are metadata round-trips, and
# the dataset set + physical locations change rarely (DSS restarts the backend on a
# webapp config change, cold-starting this cache). Bounds the per-request metadata
# cost to ~0 amortized instead of a scan per /evidence/* request.
_CANDIDATES_TTL_SECONDS = 300
_candidates_lock = threading.Lock()
_candidates_cache = {"ts": 0.0, "value": None}

# Dataset schemas (read_schema is a metadata round-trip too) cached per dataset
# name with the same TTL + the same locking pattern as _candidates_cache: the
# lock only ever guards dict access, NEVER the resolution IO. Bounded by the
# discovery cap (only matched datasets are ever read), with a defensive sweep.
_SCHEMA_TTL_SECONDS = 300
_schema_lock = threading.Lock()
_schema_cache = {}  # dataset_name -> (ts, columns)

# Per-query execution budget on the evidence dataset's connection: a slow scan
# must never pin a worker thread of the mono-process polling backend. SET LOCAL
# (not SET) so both settings are TRANSACTION-scoped: a pooled JDBC connection can
# never carry them over to other workloads on this instance. If the executor ever
# ran pre_queries outside a transaction, SET LOCAL degrades to a no-op warning
# (setting simply not applied) rather than polluting the session.
# transaction_read_only is defense in depth: every query built here is already a
# bare SELECT, but a read-only transaction makes any future regression (or an
# unexpected fragment behaviour) fail loudly instead of writing.
_EVIDENCE_TIMEOUT_PRE_QUERIES = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]


def _quote_value(value):
    """sql_value, with bools routed to bare true/false keywords.

    The parser yields Python bools for TRUE/FALSE literals and boolean dataset
    columns legitimately filter on them, but ``Constant(bool)`` escaping is not
    a documented guarantee (see sql_config.bool_literal) — render the keyword.
    """
    if isinstance(value, bool):
        return bool_literal(value)
    return sql_value(value)


class EvidenceError(Exception):
    """Service-level failure with a stable, frontend-safe code + HTTP status."""

    def __init__(self, code, status=409):
        self.code = code
        self.status = status
        super().__init__(code)


# ============================================================================
# PURE trust-layer helpers (NO dataiku use — unit-tested without a DSS runtime,
# the project's TEST-01 idiom). They only consume plain dicts/lists and the two
# injected quoting callables, so every honesty rule is provable in tests.
# ============================================================================

# Defensive projection of an explain_select result: every key the trust layer
# reads, with HONEST defaults (False/empty) so a missing or partial explainer
# can only ever UNDER-claim, never over-claim (frozen honesty rules §9).
_EXPLAIN_DEFAULTS = {
    "ok": False,
    "reason": None,
    "steps": [],
    "where_complete": False,
    "dropped_where": [],
    "group_keys": [],
    "single_source": False,
    "select_understood": False,
    "has_set_op": False,
    "has_recursive_cte": False,
    "calc_resolved": False,
}


def normalize_explain(raw):
    """Project a raw explain_select result onto the keys the trust layer reads.

    Pure + defensive: booleans are coerced, lists are type-filtered and bounded,
    anything malformed degrades to the honest defaults. This is the single
    adapter between IMPL-1's explainer and this service — if the explainer's
    shape drifts, the verification level can only go DOWN, never up.
    """
    out = dict(_EXPLAIN_DEFAULTS)
    if not isinstance(raw, dict):
        return out
    for key in ("ok", "where_complete", "single_source", "select_understood",
                "has_set_op", "has_recursive_cte", "calc_resolved"):
        out[key] = bool(raw.get(key))
    reason = raw.get("reason")
    out["reason"] = reason if isinstance(reason, str) else None
    steps = []
    raw_steps = raw.get("steps")
    if isinstance(raw_steps, list):
        for step in raw_steps[:MAX_EXPLANATION_STEPS]:
            # A step is only kept when it positively matches the frozen shape
            # {kind: str, params: list}; params items are display strings owned
            # by the explainer (column names verbatim, never invented here).
            if isinstance(step, dict) and isinstance(step.get("kind"), str):
                params = step.get("params")
                steps.append({
                    "kind": step["kind"],
                    "params": list(params) if isinstance(params, (list, tuple)) else [],
                })
    out["steps"] = steps
    raw_keys = raw.get("group_keys")
    if isinstance(raw_keys, list):
        out["group_keys"] = [k for k in raw_keys[:_MAX_GROUP_KEYS] if isinstance(k, str)]
    raw_dropped = raw.get("dropped_where")
    if isinstance(raw_dropped, list):
        # NOT length-capped here: the COUNT in verification must stay exact;
        # only the display list (build_dropped_display) is bounded.
        out["dropped_where"] = [s for s in raw_dropped if isinstance(s, str)]
    return out


def safe_explain(sql):
    """explain_select via the IMPL-1 module when available; never raises.

    Returns the normalized explain dict. When the explainer is absent or blows
    up, the result is the honest not-ok shape — verification then caps at
    'source_identified' and drill-down stays unavailable ('not_supported').
    """
    if _sql_explain is None:
        return dict(_EXPLAIN_DEFAULTS, reason="explain_unavailable")
    try:
        return normalize_explain(_sql_explain.explain_select(sql))
    except Exception:
        logger.exception("evidence — explain_select failed; degrading honestly")
        return dict(_EXPLAIN_DEFAULTS, reason="explain_failed")


def effective_where_complete(explain, colmap_dropped):
    """Frozen formula (§2): explain.where_complete AND zero colmap-dropped predicate.

    ``colmap_dropped`` counts predicates that DID apply to the matched table but
    did not resolve on its LIVE schema — each one silently widens the rebuilt
    scope, so any of them breaks completeness regardless of what explain says.
    """
    return bool(explain.get("where_complete")) and int(colmap_dropped or 0) == 0


def verification_level(explain, matched, mapped_count, where_complete):
    """The deterministic verification ladder (frozen contract §2). Pure.

    - declared          : parse failed / no dataset matched (degraded panel).
    - source_identified : matched but the WHERE could not be assessed (explain
                          not ok), or nothing mapped without completeness.
    - scope_partial     : matched + >=1 predicate mapped, completeness broken.
    - scope_exact       : complete WHERE + single source + no set operation.
    - calc_decomposed   : scope_exact + the SELECT computation fully understood
                          (group/order/having resolved, CTE DAG complete).
    """
    if not matched:
        return "declared"
    if not explain.get("ok"):
        return "source_identified"
    if (where_complete and explain.get("single_source")
            and not explain.get("has_set_op")):
        if explain.get("select_understood") and explain.get("calc_resolved"):
            return "calc_decomposed"
        return "scope_exact"
    return "scope_partial" if mapped_count >= 1 else "source_identified"


def predicate_display(pred):
    """One parsed predicate -> a short human-readable string (display only).

    Column names are kept verbatim (never translated/invented); the whole
    string is length-bounded so a pathological IN-list cannot bloat the meta.
    """
    column = pred.get("column") or "?"
    op = pred.get("op") or "?"
    values = pred.get("values") or []
    if op in ("IS NULL", "IS NOT NULL"):
        text = "{} {}".format(column, op)
    else:
        text = "{} {} {}".format(column, op, ", ".join(str(v) for v in values))
    return text[:MAX_DISPLAY_CHARS]


def build_dropped_display(dropped_predicates, dropped_where):
    """The bounded display list of everything the rebuilt scope DROPPED. Pure.

    Honesty rule §9: dropped elements are LISTED, not hidden — but the list is
    display data, so it is capped (the exact count travels separately).
    """
    out = [predicate_display(p) for p in dropped_predicates or []]
    for text in dropped_where or []:
        if isinstance(text, str):
            out.append(text[:MAX_DISPLAY_CHARS])
    return out[:MAX_DROPPED_DISPLAY]


def compute_verification(explain, matched, parsed_predicates, kept_predicates,
                         colmap_dropped, result_captured):
    """The ``verification`` block of /evidence/meta (frozen contract §2). Pure.

    Wraps the explainer's view with the REAL drops observed by this service:
      - dropped_predicates = (parsed - kept) + explain's non-decomposed conjuncts;
      - where_complete     = explain.where_complete AND zero colmap drop;
      - level              = the deterministic ladder (verification_level).
    ``result_captured`` is ORTHOGONAL: stored rows present for the active item.
    """
    parsed_predicates = parsed_predicates or []
    kept_predicates = kept_predicates or []
    kept_ids = set(p.get("id") for p in kept_predicates)
    dropped_preds = [p for p in parsed_predicates if p.get("id") not in kept_ids]
    dropped_where = [s for s in (explain.get("dropped_where") or [])
                     if isinstance(s, str)]
    where_complete = effective_where_complete(explain, colmap_dropped)
    return {
        "level": verification_level(
            explain, matched, len(kept_predicates), where_complete
        ),
        "result_captured": bool(result_captured),
        "dropped_predicates": len(dropped_preds) + len(dropped_where),
        "dropped_display": build_dropped_display(dropped_preds, dropped_where),
        "single_source": bool(explain.get("single_source")),
        "where_complete": where_complete,
        "select_understood": bool(explain.get("select_understood")),
    }


def has_captured_result(item):
    """True when the stored item carries a positively well-formed result capture."""
    result = item.get("result") if isinstance(item, dict) else None
    return (isinstance(result, dict)
            and isinstance(result.get("columns"), list)
            and isinstance(result.get("rows"), list))


def build_result_block(item):
    """The ``result`` block of /evidence/meta for the ACTIVE item (§2). Pure.

    ``row_count`` is ALWAYS the agent-declared count from the stored item (the
    captured rows may be truncated); absence of a capture is surfaced honestly
    as ``captured: false`` — never invented rows.
    """
    item = item if isinstance(item, dict) else {}
    row_count = item.get("row_count")
    if isinstance(row_count, bool) or not isinstance(row_count, int):
        row_count = None
    if not has_captured_result(item):
        return {"captured": False, "row_count": row_count}
    result = item["result"]
    return {
        "captured": True,
        "columns": result.get("columns"),
        "rows": result.get("rows"),
        "row_count": row_count,
        "truncated": bool(result.get("truncated")),
    }


def item_matches_candidates(sql, candidates):
    """True when one stored item's SQL reads at least one discovered dataset.

    Pure + bounded: reuses the existing parse (O(n), 20k-char cap) and the
    existing matcher — never raises, a non-parsable item simply does not match.
    """
    try:
        parsed = sql_parse.parse_select(sql)
    except Exception:  # parse_select never raises by contract; pure defense
        return False
    if not parsed.get("ok"):
        return False
    for ref in parsed.get("tables") or []:
        if match_whitelist(ref.get("table"), ref.get("schema"), candidates) is not None:
            return True
    return False


def summarize_queries(items, matched_flags):
    """The ``queries`` block of /evidence/meta: one summary per stored item. Pure.

    1-based ``index`` (display ordinal), coerced ``success``, the agent-declared
    ``row_count`` (None when absent/malformed), the pre-computed ``matched``
    flag, correlation tags ONLY when present, and a per-item result_captured
    flag. Never the SQL text itself (the active SQL travels separately).
    """
    matched_flags = matched_flags or []
    out = []
    for i, item in enumerate(items or []):
        if not isinstance(item, dict):
            continue
        row_count = item.get("row_count")
        if isinstance(row_count, bool) or not isinstance(row_count, int):
            row_count = None
        entry = {
            "index": i + 1,
            "success": bool(item.get("success")),
            "row_count": row_count,
            "matched": bool(matched_flags[i]) if i < len(matched_flags) else False,
            "result_captured": has_captured_result(item),
        }
        step_index = item.get("step_index")
        if isinstance(step_index, int) and not isinstance(step_index, bool):
            entry["step_index"] = step_index
        agent_key = item.get("agent_key")
        if isinstance(agent_key, str) and agent_key:
            entry["agent_key"] = agent_key[:64]
        out.append(entry)
    return out


def build_explanation(explain):
    """The ``explanation`` block of /evidence/meta (§2). Pure.

    Steps come pre-normalized (bounded list of {kind, params}); the frontend
    renders them via ``ev.exp.<kind>`` with an opaque fallback for unknown kinds.
    """
    return {
        "ok": bool(explain.get("ok")),
        "steps": list(explain.get("steps") or [])[:MAX_EXPLANATION_STEPS],
    }


def derive_drilldown(explain, colmap, where_complete):
    """The ``drilldown`` block: availability + drillable columns + reason. Pure.

    Gates (frozen contract §3) — drill-down is offered ONLY when it is provably
    reliable: explainer ok, no recursive CTE, no set operation, a single source
    (a self-join does NOT qualify), a COMPLETE rebuilt WHERE, and at least one
    GROUP BY identity key resolved on the LIVE schema (live casing returned).
    ``reason`` is a stable code for the refusal, never free text.
    """
    if not explain.get("ok") or explain.get("has_recursive_cte"):
        return {"available": False, "columns": [], "reason": "not_supported"}
    if explain.get("has_set_op"):
        return {"available": False, "columns": [], "reason": "set_op"}
    if not explain.get("single_source"):
        return {"available": False, "columns": [], "reason": "multi_source"}
    if not where_complete:
        return {"available": False, "columns": [], "reason": "incomplete_where"}
    colmap = colmap or {}
    columns = []
    for key in explain.get("group_keys") or []:
        if not isinstance(key, str):
            continue
        live = colmap.get(key.lower())
        if live is not None and live not in columns:
            columns.append(live)
    if not columns:
        return {"available": False, "columns": [], "reason": "no_group_keys"}
    if len(columns) > MAX_DRILL_CONDITIONS:
        # A drill that cannot constrain EVERY group key would show a SUPERSET
        # of the group's rows under a "source rows" banner — refuse instead
        # (CONTRACT-01: the ≤8 request cap must never silently truncate keys).
        return {"available": False, "columns": [], "reason": "not_supported"}
    return {"available": True, "columns": columns, "reason": None}


def build_drill_conditions(drill, allowed_columns, colmap, quote_ident, quote_value):
    """Render validated drill labels into SQL conditions (§3). Pure.

    Every drill column MUST belong to the SERVER-derived drillable set (live
    casing, compared case-insensitively) — anything else is 'invalid_drill'
    (400), because the client list is never trusted. ``value None`` renders an
    IS NULL test; every other value renders a strict equality. The entry count
    is re-bounded here (mirror of the request validator's cap).
    """
    drill = drill or []
    if len(drill) > MAX_DRILL_CONDITIONS:
        raise EvidenceError("invalid_drill", 400)
    allowed_lower = set()
    for name in allowed_columns or []:
        if isinstance(name, str):
            allowed_lower.add(name.lower())
    conditions = []
    for entry in drill:
        column = entry.get("column") if isinstance(entry, dict) else None
        if not isinstance(column, str) or column.lower() not in allowed_lower:
            raise EvidenceError("invalid_drill", 400)
        live = (colmap or {}).get(column.lower())
        if live is None:  # allowed set is derived from colmap — pure defense
            raise EvidenceError("invalid_drill", 400)
        value = entry.get("value")
        if value is None:
            pred = {"column": live, "op": "IS NULL", "values": []}
        else:
            pred = {"column": live, "op": "=", "values": [value]}
        conditions.append(render_predicate(pred, quote_ident, quote_value))
    return conditions


# ============================================================================
# Dataiku-bound pipeline (owner-scoped reads, discovery, live schema, execution)
# ============================================================================


def _load_sql_item(user_id, exchange_id):
    """``(active_item_or_None, all_items, active_index_or_None)`` for the exchange.

    Owner-scoped read on the chat table. The ACTIVE item is the LAST successful
    one (the agent's final refined query); ``active_index`` is its position in
    ``items`` (0-based) so callers can correlate with the queries[] summary.
    Items may carry the optional trust-layer keys (``result`` / ``sql_id`` /
    ``step_index`` / ``agent_key``) persisted by the stream manager.
    Raises 404 when the exchange does not exist OR belongs to another user
    (without revealing which); 'no_sql' (409) when it stored no SQL at all.
    """
    query = build_exchange_sql_query(
        table_ref=full_table(CHAT_V5_LOGICAL),
        user_value_sql=sql_value(user_id),
        exchange_value_sql=sql_value(exchange_id),
    )
    df = new_executor().query_to_df(query)
    rows = rows_to_json_safe(df)
    if not rows:
        raise EvidenceError("exchange_not_found", 404)
    items = [it for it in parse_json_list(rows[0].get("generated_sql"))
             if isinstance(it, dict) and it.get("sql")]
    if not items:
        raise EvidenceError("no_sql")
    active_index = None
    for i in range(len(items) - 1, -1, -1):
        if items[i].get("success"):
            active_index = i
            break
    active = items[active_index] if active_index is not None else None
    return active, items, active_index


def _sub_project_key(value):
    """Substitute the managed-dataset ${projectKey} placeholder, else passthrough."""
    if isinstance(value, str) and value:
        return value.replace("${projectKey}", PROJECT_KEY)
    return value


def _resolve_via_settings_api(name):
    """Fallback: physical (table, schema) from the DSS dataset settings params.

    Some SQL connectors do not carry the table in ``get_location_info()``; the
    dataset's own settings (``params.table`` / ``params.schema``) do. Best-effort
    and read-only (no execution) — returns (None, None) on any failure.
    """
    try:
        client = dataiku.api_client()
        raw = client.get_project(PROJECT_KEY).get_dataset(name).get_settings().get_raw()
        params = (raw or {}).get("params", {}) or {}
        return params.get("table"), params.get("schema")
    except Exception:
        logger.exception("evidence — settings-API table resolution failed for %r", name)
        return None, None


def _resolve_physical_table(name):
    """Physical ``(table, schema)`` of a discovered dataset, or ``(None, None)``.

    Primary path: ``get_location_info()['info']`` (metadata, no execution). The
    actual ``info`` shape is LOGGED so a connector whose keys differ is visible in
    the backend log instead of silently failing. Fallback: the DSS settings API.
    ``${projectKey}`` is substituted; an unresolved ``${...}`` skips the dataset.
    """
    info = {}
    try:
        info = dataiku.Dataset(name).get_location_info().get("info", {}) or {}
    except Exception:
        logger.exception("evidence — get_location_info failed for %r", name)
    # Diagnostic: surface the REAL shape so a key mismatch is debuggable from logs.
    logger.info(
        "evidence — dataset %r location_info.info keys=%s table=%r schema=%r",
        name, sorted(info.keys()), info.get("table"), info.get("schema"),
    )
    table, schema = info.get("table"), info.get("schema")
    if not table:
        # Connector did not expose a table in location info — try the settings API.
        table, schema = _resolve_via_settings_api(name)
        logger.info("evidence — dataset %r settings-API fallback table=%r schema=%r",
                    name, table, schema)
    table, schema = _sub_project_key(table), _sub_project_key(schema)
    if not table or "${" in str(table):
        logger.warning(
            "evidence — dataset %r has no resolved physical table; skipped "
            "(it must be a SQL-backed dataset)", name,
        )
        return None, None
    if schema and "${" in str(schema):
        schema = None  # unresolved schema variable -> fall back to wildcard match
    return str(table), (str(schema) if schema else None)


def _list_project_sql_datasets():
    """``[(name, params_dict), ...]`` of THIS project's SQL-backed datasets.

    Auto-discovery (no admin whitelist): only datasets on a SQL connector are
    considered, scoped to the webapp's OWN project. Best-effort and read-only;
    returns [] on any failure (Evidence then stays degraded, never crashes).
    """
    try:
        client = dataiku.api_client()
        items = client.get_project(PROJECT_KEY).list_datasets()
    except Exception:
        logger.exception("evidence — list_datasets failed for project %s", PROJECT_KEY)
        return []
    out = []
    for it in (items or []):
        d = it if isinstance(it, dict) else {}
        name = d.get("name")
        dtype = d.get("type")
        if name and dtype in _SQL_DATASET_TYPES:
            out.append((name, d.get("params") or {}))
    return out


def _resolve_dataset_candidates():
    """The project's SQL datasets resolved to their physical (schema, table).

    No admin whitelist: any SQL dataset in the webapp's own project is a candidate,
    so the agent's FROM table can be matched automatically. The table is taken from
    the dataset's listing ``params`` when present (no extra call), else resolved via
    ``_resolve_physical_table`` (get_location_info / settings API). Bounded + logged.
    """
    pairs = _list_project_sql_datasets()
    if not pairs:
        logger.warning(
            "evidence — no SQL-backed dataset found in project %s; Evidence Studio "
            "stays degraded (an agent answer's table must map to a project dataset).",
            PROJECT_KEY,
        )
        return []
    if len(pairs) > _MAX_EVIDENCE_DATASETS:
        logger.warning("evidence — dataset discovery capped at %d (project has %d)",
                       _MAX_EVIDENCE_DATASETS, len(pairs))
        pairs = pairs[:_MAX_EVIDENCE_DATASETS]
    candidates = []
    for name, params in pairs:
        table = _sub_project_key(params.get("table"))
        schema = _sub_project_key(params.get("schema"))
        if not table or "${" in str(table):
            # Listing did not carry a usable table -> resolve it explicitly.
            table, schema = _resolve_physical_table(name)
        if table and "${" not in str(table):
            candidates.append({
                "name": name,
                "table": str(table),
                "schema": (str(schema) if schema and "${" not in str(schema) else None),
            })
    logger.info(
        "evidence — discovered %d SQL dataset candidate(s) in project %s: %s",
        len(candidates), PROJECT_KEY, [(c["schema"], c["table"]) for c in candidates],
    )
    return candidates


def _dataset_candidates():
    """Project SQL datasets resolved to (schema, table), TTL-cached process-wide."""
    now = time.time()
    with _candidates_lock:
        cached = _candidates_cache["value"]
        if cached is not None and (now - _candidates_cache["ts"]) < _CANDIDATES_TTL_SECONDS:
            return cached
    # Resolve OUTSIDE the lock (metadata round-trips are slow; never hold the lock
    # during IO). A cold-cache burst may resolve a few times concurrently — harmless.
    resolved = _resolve_dataset_candidates()
    with _candidates_lock:
        _candidates_cache["value"] = resolved
        _candidates_cache["ts"] = now
    return resolved


def _read_dataset_columns(name):
    """The dataset's columns (METADATA only), keeping only pg-safe identifiers."""
    try:
        schema = dataiku.Dataset(name).read_schema()
    except Exception:
        logger.exception("evidence — read_schema failed for %r", name)
        raise EvidenceError("dataset_unavailable")
    columns = []
    for col in schema:
        col_name = col.get("name") if isinstance(col, dict) else getattr(col, "name", None)
        col_type = col.get("type") if isinstance(col, dict) else getattr(col, "type", None)
        if not col_name:
            continue
        try:
            pg_identifier(col_name)
        except ValueError:
            logger.warning("evidence — column %r is not a safe identifier; hidden", col_name)
            continue
        columns.append({"name": col_name, "type": col_type or ""})
    if not columns:
        raise EvidenceError("dataset_schema_invalid")
    return columns


def _dataset_columns(name):
    """``_read_dataset_columns`` with a per-dataset TTL cache (read-only data).

    Same pattern as _dataset_candidates: the lock guards dict access only, the
    metadata round-trip happens OUTSIDE it (a cold-cache burst may read the
    schema a few times concurrently — harmless). Failures are NEVER cached, so
    a transient DSS hiccup does not stick for a whole TTL. Callers treat the
    returned list as read-only (it is shared between requests).
    """
    now = time.time()
    with _schema_lock:
        cached = _schema_cache.get(name)
        if cached is not None and (now - cached[0]) < _SCHEMA_TTL_SECONDS:
            return cached[1]
    columns = _read_dataset_columns(name)  # raises EvidenceError on failure
    with _schema_lock:
        if len(_schema_cache) >= _MAX_EVIDENCE_DATASETS:
            # Defensive sweep: matched dataset names are naturally bounded by the
            # discovery cap, so this should never trigger in practice.
            _schema_cache.clear()
        _schema_cache[name] = (time.time(), columns)
    return columns


def _evidence_executor(dataset_name):
    """A FRESH executor on the MATCHED dataset's own connection (read-only)."""
    return SQLExecutor2(dataset=dataiku.Dataset(dataset_name))


def _context(user_id, exchange_id):
    """Everything the interactive view needs; raises EvidenceError otherwise.

    Best-effort mapping (user decision): the FIRST parsed source table that
    matches a discovered project dataset wins, and only the predicates that
    BOTH apply to that table (sql_parse.predicates_for_table) AND resolve on
    its live schema are kept — anything unmappable (join plumbing, other
    tables' filters, renamed columns) is dropped instead of degrading the view.
    The drop counts are kept on the context so the trust layer can surface them
    honestly (verification / drill-down gates).
    """
    item, items, active_index = _load_sql_item(user_id, exchange_id)
    if item is None:
        raise EvidenceError("no_successful_sql")
    parsed = sql_parse.parse_select(item["sql"])
    if not parsed["ok"]:
        raise EvidenceError(parsed["reason"] or "parse_failed")
    candidates = _dataset_candidates()
    # match_whitelist resolves an agent FROM/JOIN table to a discovered project
    # dataset (the executed reference is rebuilt from the RESOLVED candidate).
    match, matched_ref = None, None
    for ref in parsed["tables"]:
        match = match_whitelist(ref["table"], ref["schema"], candidates)
        if match is not None:
            matched_ref = ref
            break
    if match is None:
        # Diagnostic: show the agent's tables vs the discovered candidates so the
        # mismatch (no SQL dataset in the project vs a name/schema difference) is
        # clear in the backend log.
        logger.info(
            "evidence — no_matching_dataset: agent tables=%s matched none of "
            "%d project dataset(s) %s",
            [(t["schema"], t["table"]) for t in parsed["tables"]],
            len(candidates), [(c["schema"], c["table"]) for c in candidates],
        )
        raise EvidenceError("no_matching_dataset")
    columns = _dataset_columns(match["name"])
    colmap = {}
    for c in columns:
        low = c["name"].lower()
        if low in colmap:
            # Two columns differing only by case would make chip/filter column
            # resolution ambiguous — refuse rather than guess.
            raise EvidenceError("dataset_schema_invalid")
        colmap[low] = c["name"]
    table_predicates = sql_parse.predicates_for_table(
        parsed["predicates"], matched_ref["table"]
    )
    predicates = [
        pred for pred in table_predicates
        if pred["column"].lower() in colmap  # not on the live schema -> dropped
    ]
    # The advanced fragment is kept only when it passes the defensive gate;
    # an unsafe/unsupported fragment is dropped, never a blocker.
    advanced = parsed["advanced"]
    if advanced and not sql_parse.validate_fragment(advanced):
        logger.info("evidence — advanced fragment dropped (failed validation)")
        advanced = None
    try:
        schema_name = match.get("schema")
        table_ref = (
            "{}.{}".format(pg_identifier(schema_name), pg_identifier(match["table"]))
            if schema_name else pg_identifier(match["table"])
        )
    except ValueError:
        raise EvidenceError("dataset_table_invalid")
    return {
        "sql": item["sql"],
        "predicates": predicates,
        "advanced": advanced,
        "dataset": match["name"],
        "table_ref": table_ref,
        "columns": columns,
        "colmap": colmap,
        # --- trust-layer context (additive) ---------------------------------
        "item": item,                    # the ACTIVE stored item (may carry result)
        "items": items,                  # every stored item, storage order
        "active_index": active_index,    # 0-based position of the active item
        "candidates": candidates,        # discovered datasets (for queries[].matched)
        "source_schema": match.get("schema"),
        "source_table": match["table"],
        "parsed_predicates": parsed["predicates"],
        # Predicates that applied to the matched table but are NOT on the live
        # schema: the only drops that break the frozen where_complete formula.
        "colmap_dropped": len(table_predicates) - len(predicates),
    }


def _degraded_sql(user_id, exchange_id):
    """Best-effort raw SQL for the degraded panel (never raises 409)."""
    try:
        item, items, _active_index = _load_sql_item(user_id, exchange_id)
        chosen = item or items[-1]
        return chosen.get("sql")
    except EvidenceError:
        return None


# --- shared condition builders (meta/rows/distinct light refactor) -----------


def _locked_condition(ctx, pred):
    """Render one server-derived (locked) predicate against the LIVE schema."""
    resolved = dict(pred, column=ctx["colmap"][pred["column"].lower()])
    return render_predicate(resolved, pg_identifier, _quote_value)


def _advanced_condition(ctx):
    """The advanced fragment as a parenthesized condition, re-gated every time.

    Defense in depth: _context validated the fragment already; it is re-checked
    here before every single use (the gate is cheap and pure).
    """
    fragment = ctx["advanced"]
    if not sql_parse.validate_fragment(fragment):
        raise EvidenceError("fragment_rejected")
    return "(" + fragment + ")"


def _drill_conditions(ctx, drill):
    """Server-derived drill gate + rendering for /evidence/rows (§3).

    The drillable columns are RE-DERIVED from the stored SQL on every call
    (explain + the same gates as /evidence/meta) — the client's drill columns
    are only ever matched against that server-side set, never trusted.
    """
    explain = safe_explain(ctx["sql"])
    drilldown = derive_drilldown(
        explain, ctx["colmap"],
        effective_where_complete(explain, ctx["colmap_dropped"]),
    )
    if not drilldown["available"]:
        raise EvidenceError("invalid_drill", 400)
    return build_drill_conditions(
        drill, drilldown["columns"], ctx["colmap"], pg_identifier, _quote_value
    )


def _run_evidence_query(ctx, query, op_name):
    """Execute one bounded read-only query on the matched dataset's connection.

    Shared by rows/distinct: fresh executor, transaction-scoped timeout +
    read-only pre-queries, JSON-safe rows, stable 'query_failed' on any DB error.
    """
    try:
        df = _evidence_executor(ctx["dataset"]).query_to_df(
            query,
            pre_queries=list(_EVIDENCE_TIMEOUT_PRE_QUERIES),
        )
    except Exception:
        logger.exception("%s — query failed (dataset=%s)", op_name, ctx["dataset"])
        raise EvidenceError("query_failed")
    return rows_to_json_safe(df)


# --- public service entry points ----------------------------------------------


def evidence_meta(user_id, exchange_id):
    """The interactive descriptor for one exchange, or an HONEST degraded shape.

    'exchange_not_found' (404) propagates; every other EvidenceError degrades to
    ``available: False`` + the stable reason (the panel then shows the raw SQL).
    The v1 fields (dataset/columns/chips/advanced/sql) are unchanged; the trust
    layer adds source/queries/verification/explanation/result/drilldown (§2),
    all computed by the pure helpers above — deterministic, no LLM involved.
    """
    try:
        ctx = _context(user_id, exchange_id)
    except EvidenceError as exc:
        if exc.code == "exchange_not_found":
            raise
        return {
            "available": False,
            "reason": exc.code,
            "sql": _degraded_sql(user_id, exchange_id),
            # Degraded panel: the agent's number is a CLAIM — nothing was
            # re-verified and no captured result is surfaced here (§2).
            "verification": {"level": "declared", "result_captured": False},
        }

    explain = safe_explain(ctx["sql"])
    result_block = build_result_block(ctx["item"])
    verification = compute_verification(
        explain,
        True,  # matched: _context only succeeds on a matched dataset
        ctx["parsed_predicates"],
        ctx["predicates"],
        ctx["colmap_dropped"],
        result_block["captured"],
    )
    # matched flag per stored item: same matcher as the main pipeline, bounded
    # (parse is O(n) with a 20k-char cap; the item list is capped at write time).
    matched_flags = [
        item_matches_candidates(it.get("sql"), ctx["candidates"])
        for it in ctx["items"]
    ]
    drilldown = derive_drilldown(
        explain, ctx["colmap"],
        effective_where_complete(explain, ctx["colmap_dropped"]),
    )
    return {
        "available": True,
        "dataset": ctx["dataset"],
        "columns": ctx["columns"],
        "chips": [
            {"id": p["id"],
             # The chip shows the LIVE schema casing (what rows/distinct will use).
             "column": ctx["colmap"][p["column"].lower()],
             "op": p["op"], "values": p["values"], "editable": p["editable"]}
            for p in ctx["predicates"]
        ],
        "advanced": {"present": bool(ctx["advanced"]), "display": ctx["advanced"]},
        "sql": ctx["sql"],
        # --- trust layer (additive, frozen contract §2) ----------------------
        "source": {
            "dataset": ctx["dataset"],
            "schema": ctx["source_schema"],
            "table": ctx["source_table"],
        },
        "queries": summarize_queries(ctx["items"], matched_flags),
        "verification": verification,
        "explanation": build_explanation(explain),
        "result": result_block,
        "drilldown": drilldown,
    }


def evidence_rows(user_id, exchange_id, filters, kept_ids, include_advanced,
                  page, sort, drill=None):
    """One bounded page of the (re-)filtered evidence table. Read-only.

    ``drill`` (optional, validated upstream) narrows the page to ONE result
    group: every drill column is re-derived from the STORED SQL server-side
    (never trusted from the client) and rendered as an equality / IS NULL
    condition ADDED to the standard ones. Everything else is unchanged.
    """
    ctx = _context(user_id, exchange_id)
    conditions = []
    kept = set(kept_ids)
    for pred in ctx["predicates"]:
        # Editable chips travel as client `filters` (their CURRENT state); locked
        # chips are re-derived HERE from the stored SQL and only kept by id.
        if pred["editable"] or pred["id"] not in kept:
            continue
        conditions.append(_locked_condition(ctx, pred))
    for f in filters:
        column = ctx["colmap"].get(f["column"].lower())
        if column is None:
            raise EvidenceError("invalid_filter_column", 400)
        op = "=" if (f["op"] == "=" and len(f["values"]) == 1) else "IN"
        conditions.append(render_predicate(
            {"column": column, "op": op, "values": f["values"]},
            pg_identifier, _quote_value,
        ))
    if include_advanced and ctx["advanced"]:
        conditions.append(_advanced_condition(ctx))
    if drill:
        conditions.extend(_drill_conditions(ctx, drill))

    if sort:
        order_col = ctx["colmap"].get(sort["column"].lower())
        if order_col is None:
            raise EvidenceError("invalid_sort_column", 400)
        order_dir = sort["dir"]
    else:
        # Deterministic default: OFFSET pagination needs a stable ORDER BY.
        # Caveat (accepted v1 trade-off): the first schema column may be of a
        # non-sortable SQL type (the query then fails with the stable
        # 'query_failed' code), and ties on it can repeat rows across OFFSET
        # pages.
        order_col, order_dir = ctx["columns"][0]["name"], "asc"

    query = build_rows_query(
        table_ref=ctx["table_ref"],
        column_idents=[pg_identifier(c["name"]) for c in ctx["columns"]],
        conditions=conditions,
        order_ident=pg_identifier(order_col),
        order_dir=order_dir,
        limit=PAGE_SIZE + 1,           # one extra row -> has_more without COUNT(*)
        offset=page * PAGE_SIZE,
    )
    rows = _run_evidence_query(ctx, query, "evidence_rows")
    has_more = len(rows) > PAGE_SIZE
    logger.info(
        "evidence_rows — user_id=%s exchange_id=%s dataset=%s page=%d conditions=%d returned=%d",
        user_id, exchange_id, ctx["dataset"], page, len(conditions), min(len(rows), PAGE_SIZE),
    )
    return {"rows": rows[:PAGE_SIZE], "has_more": has_more, "page": page}


def evidence_distinct(user_id, exchange_id, column, exclude_id=None):
    """Bounded distinct values of one column (the filter-chip picker).

    The picker shows values WITHIN the agent's remaining scope: the =/IN
    predicates and the advanced fragment still apply, but the predicate the
    user is currently EDITING (``exclude_id``, the chip's server id) never
    self-scopes its own picker — every chip is editable in the UI, so a
    comparison chip (>=, BETWEEN…) must be able to widen past its own bound.
    """
    ctx = _context(user_id, exchange_id)
    resolved_col = ctx["colmap"].get(column.lower())
    if resolved_col is None:
        raise EvidenceError("invalid_filter_column", 400)
    conditions = []
    for pred in ctx["predicates"]:
        if pred["editable"]:
            continue  # =/IN chips are what the user is picking — don't self-scope
        if exclude_id is not None and pred["id"] == exclude_id:
            continue  # the chip being edited must not filter its own picker
        conditions.append(_locked_condition(ctx, pred))
    if ctx["advanced"]:
        conditions.append(_advanced_condition(ctx))
    query = build_distinct_query(
        table_ref=ctx["table_ref"],
        column_ident=pg_identifier(resolved_col),
        limit=DISTINCT_LIMIT + 1,      # one extra value -> truncated without a false positive
        conditions=conditions,
    )
    values = [r["value"] for r in _run_evidence_query(ctx, query, "evidence_distinct")]
    truncated = len(values) > DISTINCT_LIMIT
    values = values[:DISTINCT_LIMIT]
    logger.info(
        "evidence_distinct — user_id=%s exchange_id=%s dataset=%s column=%s returned=%d truncated=%s",
        user_id, exchange_id, ctx["dataset"], resolved_col, len(values), truncated,
    )
    return {"values": values, "truncated": truncated}
