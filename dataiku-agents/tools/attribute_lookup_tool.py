# -*- coding: utf-8 -*-
"""attribute_lookup - Custom Python agent tool for OWIsMind sub-agents.

Answers "what is the <attribute> of <entity>?" (e.g. "the account manager of
Algerie Telecom") with one targeted, read-only SQL lookup - NO semantic model,
NO dataframe loaded in memory. It is the FAST path for plain attribute reads,
which the semantic model handles slowly (and sometimes wrongly).

Two short SQL steps:
  1. RESOLVE the entity name to an exact (column, value) filter by querying the
     value catalog on its normalized_value (exact pass -> fuzzy LIKE pass).
  2. READ the attribute(s):
     SELECT DISTINCT <attr cols> FROM <fact> WHERE <entity col> = <value> LIMIT N.

The attribute names the user/LLM passes are mapped to the REAL column names of
the fact table (case/underscore-insensitive), so "account manager",
"Account_Manager" and "account_manager" all resolve to the same real column -
the spelling never breaks the query.

Safety: every query is read-only (statement_timeout + transaction_read_only) and
bounded by LIMIT; only column names that EXIST in the live fact schema are ever
put in the SQL; nothing is loaded into RAM. Safe under concurrent load.

To reuse for another dataset: change FACT_DATASET / CATALOG_DATASET below.
"""

import re
import unicodedata
import difflib

import dataiku
from dataiku.llm.agent_tools import BaseAgentTool


# ============================================================
# CONFIG - change per sub-agent / dataset
# ============================================================
FACT_DATASET = "DRIVE_Revenues"
CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"

# Catalog search domains an *entity* (the thing we read an attribute FOR) lives
# in, in PREFERENCE ORDER (most precise first). This is the catalog's own
# convention (see build_value_catalog_recipe), NOT a dataset column name - so it
# stays universal: point the tool at another dataset + its catalog and only this
# tuple may need adjusting. Domains not listed here (offers, scenarios) are never
# treated as entities.
ENTITY_DOMAINS = ("account", "account_group", "alias")

RESOLVE_EXACT_LIMIT = 50      # candidates pulled on the exact pass
RESOLVE_FUZZY_LIMIT = 60      # candidates pulled on the fuzzy LIKE pass
FUZZY_MIN_RATIO = 0.78        # difflib ratio floor to accept a fuzzy entity
FUZZY_MARGIN = 0.06           # winner must beat the runner-up by this margin
MAX_RESULT_ROWS = 50          # cap on the attribute result
MAX_ATTRIBUTES = 8            # cap on requested attributes (anti-abuse)

SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'",
                   "SET LOCAL transaction_read_only TO on"]


# ============================================================
# PURE HELPERS (DSS-free, unit-tested)
# ============================================================
def norm(value):
    """Accent-insensitive lowercase, punctuation -> space, whitespace collapsed.

    FROZEN: this MUST match build_value_catalog_recipe.norm() so the user term
    matches the catalog's normalized_value column.
    """
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def quote_literal(value):
    """Single-quoted SQL string literal (doubles embedded quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_ident(name):
    """Double-quoted SQL identifier (doubles embedded double quotes). Only ever
    called on names already validated against the live schema."""
    return '"' + str(name).replace('"', '""') + '"'


def like_escape(value):
    return (str(value).replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def match_attribute_column(raw, live_columns):
    """Map a user/LLM attribute designation to a REAL column name, ignoring case,
    spaces and underscores ('account manager' -> 'account_manager'). None when no
    column matches. live_columns wins over guesses: spelling never breaks it."""
    if not raw:
        return None
    key = norm(raw)
    flat = re.sub(r"[\s_]+", "", key)
    if not flat:
        return None
    for name in live_columns or []:
        n = norm(name)
        if n == key or re.sub(r"[\s_]+", "", n) == flat:
            return name
    return None


def map_attributes(raw_attributes, live_columns):
    """(resolved_real_columns, unknown_raw_names), de-duplicated, order-preserved,
    capped at MAX_ATTRIBUTES."""
    resolved, unknown, seen = [], [], set()
    for raw in (raw_attributes or [])[:MAX_ATTRIBUTES]:
        col = match_attribute_column(raw, live_columns)
        if col is None:
            unknown.append(str(raw))
        elif col not in seen:
            seen.add(col)
            resolved.append(col)
    return resolved, unknown


def build_resolve_sql(catalog_table, term_norm, fuzzy):
    """SQL over the value catalog for one entity term. Exact pass matches
    normalized_value; fuzzy pass uses an escaped LIKE. Both restrict to entity
    domains and order so the best candidate surfaces first."""
    domains = ", ".join(quote_literal(d) for d in ENTITY_DOMAINS)
    cols = ("search_domain, source_column, target_column, target_value, "
            "display_value, normalized_value, frequency, is_alias")
    if fuzzy:
        pattern = "%" + like_escape(term_norm) + "%"
        where = "normalized_value LIKE %s ESCAPE '\\'" % quote_literal(pattern)
        limit = RESOLVE_FUZZY_LIMIT
    else:
        where = "normalized_value = %s" % quote_literal(term_norm)
        limit = RESOLVE_EXACT_LIMIT
    return ("SELECT %s FROM %s WHERE %s AND search_domain IN (%s) "
            "ORDER BY is_alias ASC, frequency DESC LIMIT %d"
            % (cols, catalog_table, where, domains, limit))


def _domain_rank(row):
    """Preference rank of a catalog row's search_domain (lower = preferred), from
    the position in ENTITY_DOMAINS. Generic: no dataset column name involved."""
    dom = str(row.get("search_domain") or "")
    return ENTITY_DOMAINS.index(dom) if dom in ENTITY_DOMAINS else len(ENTITY_DOMAINS)


def _entity_sort_key(row):
    is_alias = int(row.get("is_alias") or 0)
    freq = -int(row.get("frequency") or 0)
    return (is_alias, _domain_rank(row), freq)


def pick_exact_entity(rows):
    """From exact-match catalog rows, return ('resolved', row),
    ('ambiguous', rows) or ('none', None).

    Rows that all point at the SAME (target_column, target_value) collapse to one
    pick. Across DISTINCT targets, a strictly more-precise search_domain wins (per
    ENTITY_DOMAINS order); otherwise it is genuinely ambiguous and handed back to
    the caller to clarify. Ranking uses only generic catalog signals
    (search_domain, is_alias, frequency) - never a hardcoded dataset column."""
    rows = [r for r in (rows or []) if r.get("target_column") and r.get("target_value")]
    if not rows:
        return ("none", None)
    targets = {(str(r["target_column"]), str(r["target_value"])) for r in rows}
    if len(targets) == 1:
        return ("resolved", sorted(rows, key=_entity_sort_key)[0])
    ranked = sorted(rows, key=_entity_sort_key)
    top, second = ranked[0], ranked[1]
    # A strictly dominant domain (more precise) wins; a tie between two different
    # real entities is genuinely ambiguous.
    if _domain_rank(top) < _domain_rank(second):
        return ("resolved", top)
    # de-dup ambiguous candidates by (column, value) for a clean clarification.
    uniq, seen = [], set()
    for r in ranked:
        k = (str(r["target_column"]), str(r["target_value"]))
        if k not in seen:
            seen.add(k)
            uniq.append(r)
    return ("ambiguous", uniq[:5])


def pick_fuzzy_entity(term_norm, rows):
    """Rank fuzzy candidates by difflib ratio on normalized_value. Returns
    ('resolved', row) only when the best clears FUZZY_MIN_RATIO AND beats the next
    distinct target by FUZZY_MARGIN; else ('none', None)."""
    scored = []
    for r in rows or []:
        if not (r.get("target_column") and r.get("target_value")):
            continue
        ratio = difflib.SequenceMatcher(
            None, term_norm, norm(r.get("normalized_value"))).ratio()
        scored.append((ratio, r))
    if not scored:
        return ("none", None)
    scored.sort(key=lambda x: (-x[0], _entity_sort_key(x[1])))
    best_ratio, best = scored[0]
    if best_ratio < FUZZY_MIN_RATIO:
        return ("none", None)
    # find the next candidate pointing at a DIFFERENT target
    best_target = (str(best["target_column"]), str(best["target_value"]))
    for ratio, r in scored[1:]:
        if (str(r["target_column"]), str(r["target_value"])) != best_target:
            if best_ratio - ratio < FUZZY_MARGIN:
                return ("none", None)
            break
    return ("resolved", best)


def build_attribute_sql(fact_table, entity_col, entity_val, attr_cols):
    """SELECT DISTINCT of the requested attributes for the resolved entity.
    entity_col and attr_cols are REAL, schema-validated column names; the value is
    a quoted literal. Bounded by LIMIT."""
    select_cols = ", ".join(quote_ident(c) for c in attr_cols)
    return ("SELECT DISTINCT %s FROM %s WHERE %s = %s LIMIT %d"
            % (select_cols, fact_table,
               quote_ident(entity_col), quote_literal(entity_val),
               MAX_RESULT_ROWS))


# ============================================================
# AGENT TOOL
# ============================================================
class MyAgentTool(BaseAgentTool):
    """Read a named entity's attribute(s) with one fast, read-only SQL lookup."""

    def __init__(self):
        self._tables = {}

    # --- DSS access (overridden in tests) -------------------------------------
    def _get_table(self, dataset_name):
        """Fully-qualified quoted table name (cached by name)."""
        cached = self._tables.get(dataset_name)
        if cached:
            return cached
        info = dataiku.Dataset(dataset_name).get_location_info().get("info", {})
        table = info.get("quotedResolvedTableName")
        if not table:
            schema_name, table_name = info.get("schema"), info.get("table")
            if not table_name:
                raise RuntimeError("cannot resolve SQL table for %s" % dataset_name)
            table = ('"%s"."%s"' % (schema_name, table_name) if schema_name
                     else '"%s"' % table_name)
        self._tables[dataset_name] = table
        return table

    def _live_columns(self, dataset_name):
        """Current column names from the schema (cheap metadata read, no scan)."""
        schema = dataiku.Dataset(dataset_name).read_schema()
        out = []
        for c in schema:
            col = c.get("name") if isinstance(c, dict) else getattr(c, "name", None)
            if col:
                out.append(col)
        return out

    def _run_sql(self, dataset_name, sql, max_rows=MAX_RESULT_ROWS):
        """Read-only execution -> (columns, list-of-dict rows). Tries the
        streaming reader first (no pandas), falls back to query_to_df."""
        executor = dataiku.SQLExecutor2(dataset=dataiku.Dataset(dataset_name))
        try:
            reader = executor.query_to_iter(sql, pre_queries=list(SQL_PRE_QUERIES))
            schema = reader.get_schema()
            columns = [c.get("name") if isinstance(c, dict)
                       else getattr(c, "name", str(c)) for c in schema]
            rows = []
            for i, t in enumerate(reader.iter_tuples()):
                if i >= max_rows:
                    break
                rows.append(dict(zip(columns, t)))
            return columns, rows
        except AttributeError:
            pass
        df = executor.query_to_df(sql, pre_queries=list(SQL_PRE_QUERIES))
        columns = [str(c) for c in df.columns]
        rows = [dict(zip(columns, r))
                for r in df.head(max_rows).itertuples(index=False, name=None)]
        return columns, rows

    # --- resolution -----------------------------------------------------------
    def _resolve_entity(self, raw_entity):
        """Resolve a raw entity name to a catalog row. Returns
        (status, row_or_candidates) with status in
        {'resolved', 'ambiguous', 'not_found'}. The catalog TABLE goes in the
        FROM clause; the catalog DATASET name drives the SQL executor."""
        term_norm = norm(raw_entity)
        if not term_norm:
            return ("not_found", None)
        catalog_table = self._get_table(CATALOG_DATASET)
        _, exact_rows = self._run_sql(
            CATALOG_DATASET, build_resolve_sql(catalog_table, term_norm, fuzzy=False),
            max_rows=RESOLVE_EXACT_LIMIT)
        status, payload = pick_exact_entity(exact_rows)
        if status in ("resolved", "ambiguous"):
            return (status, payload)
        _, fuzzy_rows = self._run_sql(
            CATALOG_DATASET, build_resolve_sql(catalog_table, term_norm, fuzzy=True),
            max_rows=RESOLVE_FUZZY_LIMIT)
        status, payload = pick_fuzzy_entity(term_norm, fuzzy_rows)
        if status == "resolved":
            return (status, payload)
        return ("not_found", None)

    # --- contract -------------------------------------------------------------
    def get_descriptor(self, tool):
        return {
            "description": (
                "Read one or more plain attributes of a single named entity "
                "(account, customer, partner) directly from the dataset, with a "
                "fast read-only SQL lookup. Use this for simple field reads such "
                "as 'who is the account manager of <customer>?', 'what is the "
                "carrier code / parent group / sales zone of <account>?'. Do NOT "
                "use it for sums, totals, rankings, comparisons or any "
                "aggregation - use the semantic model query tool for those. "
                "Pass the entity name as typed and the attribute(s) to read; the "
                "tool resolves the exact entity value and the real column names "
                "itself (spelling and casing do not matter). Returns the distinct "
                "attribute value(s), the resolved entity, and the SQL used. "
                "status 'entity_not_found' or 'entity_ambiguous' means you should "
                "ask the user to clarify instead of guessing."
            ),
            "inputSchema": {
                "$id": "https://owismind/tools/attribute_lookup/input",
                "title": "AttributeLookupInput",
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": (
                            "Name of the entity to read an attribute of, as the "
                            "user typed it (e.g. 'Algerie Telecom', 'Telesat')."
                        ),
                    },
                    "attributes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Attribute(s) / column(s) to return (e.g. "
                            "['account manager'], ['carrier code','sales zone']). "
                            "Case and underscores do not matter."
                        ),
                    },
                },
                "required": ["entity", "attributes"],
            },
        }

    def invoke(self, input, trace):
        args = input.get("input", {}) or {}
        raw_entity = (args.get("entity") or "").strip()
        raw_attributes = args.get("attributes") or []
        if isinstance(raw_attributes, str):
            raw_attributes = [raw_attributes]

        def out(payload):
            return {"output": payload,
                    "sources": [{"id": FACT_DATASET, "type": "dataset",
                                 "name": "Dataset: %s" % FACT_DATASET}]}

        if not raw_entity or not raw_attributes:
            return out({"status": "bad_input", "message":
                        "Provide both 'entity' and at least one 'attributes' name."})

        # 1) Map requested attributes to REAL columns (spelling-proof).
        live_columns = self._live_columns(FACT_DATASET)
        attr_cols, unknown = map_attributes(raw_attributes, live_columns)
        if not attr_cols:
            return out({"status": "attribute_unknown",
                        "attributes_unknown": unknown,
                        "available_columns": live_columns,
                        "message": "None of the requested attributes match a real "
                                   "column."})

        # 2) Resolve the entity to an exact (column, value) filter.
        status, payload = self._resolve_entity(raw_entity)
        if status == "not_found":
            return out({"status": "entity_not_found", "entity": {"raw": raw_entity},
                        "message": "Could not find '%s' in the data." % raw_entity})
        if status == "ambiguous":
            return out({"status": "entity_ambiguous", "entity": {"raw": raw_entity},
                        "candidates": [{"column": r.get("target_column"),
                                        "value": r.get("target_value"),
                                        "display": r.get("display_value")}
                                       for r in payload],
                        "message": "'%s' matches several entities; ask the user "
                                   "which one." % raw_entity})

        entity_col = str(payload.get("target_column"))
        entity_val = str(payload.get("target_value"))
        # 3) Safety: only query a column that EXISTS in the live fact schema.
        if entity_col not in live_columns:
            return out({"status": "entity_not_found", "entity": {"raw": raw_entity},
                        "message": "Resolved column '%s' is not in %s (catalog out "
                                   "of sync)." % (entity_col, FACT_DATASET)})

        # 4) Read the attribute(s).
        fact_table = self._get_table(FACT_DATASET)
        sql = build_attribute_sql(fact_table, entity_col, entity_val, attr_cols)
        columns, rows = self._run_sql(FACT_DATASET, sql, max_rows=MAX_RESULT_ROWS)

        result = {
            "status": "ok" if rows else "no_value",
            "entity": {"raw": raw_entity, "column": entity_col, "value": entity_val,
                       "display": payload.get("display_value") or entity_val},
            "attributes_resolved": attr_cols,
            "attributes_unknown": unknown,
            "columns": columns,
            "rows": [[r.get(c) for c in columns] for r in rows],
            "row_count": len(rows),
            "sql": sql,
        }
        if not rows:
            result["message"] = ("No value found for %s = %s."
                                 % (entity_col, entity_val))
        return out(result)
