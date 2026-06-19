# -*- coding: utf-8 -*-
"""attribute_lookup - Custom Python agent tool.

A whole-dataset value search. It behaves like Dataiku's "Whole data" search box:
a case- and accent-insensitive filter over every text column that returns the
matching values of the other columns (or only the requested column).

Answers:
  - "who is the account manager of <customer>?"  (the term is the customer)
  - "what does <account_manager> manage?"        (the term is the manager)
  - "carrier code / sales zone / parent group of <account>?"

Flow:
  1. SEARCH one ILIKE over an accent-folded concat_ws of every text column (a
     single predicate; casing via lower()/ILIKE, accents via a translate() map):
     SELECT * FROM <fact> WHERE <folded concat> ILIKE '%term%' LIMIT <n>.
  2. SUMMARIZE distinct value(s) per matched column (or only the requested ones),
     capped. 'found_in' carries rows_capped (LIMIT hit, so a sample) and
     multi_column (the term appears in several columns).
  3. FALLBACK: nothing matched and no attribute requested -> query the value
     catalog for close aliases and return them as suggestions.

Execution is read-only (statement_timeout + transaction_read_only) and bounded by
LIMIT; only schema-discovered column names reach the SQL; rows are streamed, not
loaded into a dataframe. A bounded, TTL'd in-process cache holds recent results.

To reuse for another dataset, change FACT_DATASET (and CATALOG_DATASET for the
alias fallback) or pass `dataset` / `catalog` at call time. Optionally pass
`searchable_columns` to restrict the broad search to named-entity / id columns
(keeping long free-text columns out of a noisy match). No column name is hardcoded.
"""

import re
import time
import unicodedata
import difflib

import dataiku
from dataiku.llm.agent_tools import BaseAgentTool


# ============================================================
# CONFIG
# ============================================================
FACT_DATASET = "DRIVE_Revenues"
CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"   # value catalog (alias fallback)

# Catalog search domains for the alias fallback, in preference order. A catalog
# convention (build_value_catalog_recipe), not a dataset column.
ENTITY_DOMAINS = ("account", "account_group", "alias")

SEARCH_SAMPLE_ROWS = 1000     # rows scanned to collect the matching values
DISTINCT_PER_COLUMN = 25      # max distinct values returned per column
MAX_ATTRIBUTES = 12           # cap on requested attributes
RESOLVE_EXACT_LIMIT = 50      # alias fallback: exact pass
RESOLVE_FUZZY_LIMIT = 60      # alias fallback: fuzzy pass
# A 1-char needle ILIKE '%x%' matches almost every row; such terms skip the broad
# search and go to the alias/not-found path. Two-char codes are still searched.
MIN_NEEDLE_CHARS = 2
# In-process result cache, keyed by (dataset, needle, attributes). Bounded and
# TTL'd; values are the small resolved payloads (distinct values only).
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 120

SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'",
                   "SET LOCAL transaction_read_only TO on"]

# Lowercase + accent-fold map, applied char-for-char by SQL translate() on the
# column side and by str.translate() on the needle/Python re-filter, so both
# sides fold identically. FROM/TO must be the same length. Folding happens at
# query time only; the stored data is not modified.
_ACCENTS_FROM = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿ"
_ACCENTS_TO = "aaaaaaceeeeiiiinooooouuuuyy"
_NEEDLE_TRANSLATION = str.maketrans(_ACCENTS_FROM, _ACCENTS_TO)


# ============================================================
# PURE HELPERS (DSS-free, unit-tested)
# ============================================================
def norm(value):
    """Accent-insensitive lowercase, punctuation -> space, whitespace collapsed.
    Matches build_value_catalog_recipe.norm() (used by the alias fallback)."""
    if value is None:
        return ""
    s = str(value).strip().lower()
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def search_value(term):
    """The term as a LIKE needle: lowercased then accent-folded through the shared
    translate map, so it folds the same way as the SQL column side."""
    return str(term or "").strip().lower().translate(_NEEDLE_TRANSLATION)


def quote_literal(value):
    """Single-quoted SQL string literal (doubles embedded quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_ident(name):
    """Double-quoted SQL identifier (doubles embedded double quotes). Only called
    on names already discovered from the live schema."""
    return '"' + str(name).replace('"', '""') + '"'


def like_escape(value):
    return (str(value).replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def accent_fold_sql(col_expr):
    """SQL expression: text lowercased and accent-folded via translate(). CAST(...
    AS text) keeps it valid for any physical type. col_expr is an already-quoted
    identifier or a text expression (e.g. a concat)."""
    return ("translate(lower(CAST(%s AS text)), %s, %s)"
            % (col_expr, quote_literal(_ACCENTS_FROM), quote_literal(_ACCENTS_TO)))


def match_attribute_column(raw, live_columns):
    """Map a column designation to a real column name, ignoring case, spaces and
    underscores ('account manager' -> 'account_manager'). None when no column
    matches; live_columns is authoritative."""
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


def resolve_search_columns(text_columns, requested):
    """The text columns the broad search may scan: the requested allowlist
    intersected with the live string columns (case/space/underscore-insensitive),
    in live schema order. An empty allowlist - or one that matches no live column -
    falls back to EVERY text column, so the search never runs on an empty column
    set (which would be a broken predicate). The allowlist only narrows the SEARCH;
    any column is still returnable as an attribute."""
    if not requested:
        return list(text_columns)
    wanted = set()
    for raw in requested:
        col = match_attribute_column(raw, text_columns)
        if col:
            wanted.add(col)
    if not wanted:
        return list(text_columns)
    return [c for c in text_columns if c in wanted]


def build_search_sql(fact_table, text_columns, term, sample=SEARCH_SAMPLE_ROWS):
    """One ILIKE over an accent-folded concatenation of every text column: the
    term matched anywhere in a single predicate. find_matches() then pinpoints the
    exact column(s) Python-side, filtering out a match that straddles two columns
    in the concatenation. concat_ws converts its arguments to text and skips NULLs;
    the needle is a quoted, escaped literal."""
    needle = quote_literal("%" + like_escape(search_value(term)) + "%")
    concat = "concat_ws(' ', %s)" % ", ".join(quote_ident(c) for c in text_columns)
    return ("SELECT * FROM %s WHERE %s ILIKE %s ESCAPE '\\' LIMIT %d"
            % (fact_table, accent_fold_sql(concat), needle, int(sample)))


def find_matches(text_columns, rows, term, per_col_cap=DISTINCT_PER_COLUMN):
    """For each text column whose value contains the term (accent/case-
    insensitive), the distinct matching value(s) with their exact spelling.
    Returns [{column, values}] in schema order, capped per column."""
    needle = search_value(term)
    if not needle:
        return []
    found, truncated = {}, set()
    for r in rows or []:
        for c in text_columns:
            v = r.get(c) if isinstance(r, dict) else None
            if v is None or v == "":
                continue
            if needle in search_value(v):
                bucket = found.setdefault(c, [])
                sv = str(v)[:200]
                if sv not in bucket:
                    if len(bucket) >= per_col_cap:
                        truncated.add(c)
                    else:
                        bucket.append(sv)
    out = []
    for c in text_columns:                       # stable, schema order
        if c in found:
            vals = found[c] + (["..."] if c in truncated else [])
            out.append({"column": c, "values": vals})
    return out


def summarize_values(columns, rows, keep=None, per_col_cap=DISTINCT_PER_COLUMN):
    """Distinct, non-null value(s) per column from the matched rows. One value ->
    scalar; several -> list (capped, with a trailing '...' when truncated). `keep`
    restricts to those real columns; otherwise every column is summarized."""
    targets = keep if keep is not None else columns
    out = {}
    for col in targets:
        if col not in columns:
            continue
        order, seen, truncated = [], set(), False
        for r in rows or []:
            v = r.get(col) if isinstance(r, dict) else None
            if v is None or v == "":
                continue
            sv = str(v)[:200]
            if sv not in seen:
                seen.add(sv)
                order.append(sv)
            if len(order) > per_col_cap:
                order.pop()
                truncated = True
                break
        if not order:
            continue
        if len(order) == 1 and not truncated:
            out[col] = order[0]
        else:
            out[col] = order + (["..."] if truncated else [])
    return out


# ----- alias fallback (value catalog) -------------------------------------------
def _domain_rank(row):
    dom = str(row.get("search_domain") or "")
    return ENTITY_DOMAINS.index(dom) if dom in ENTITY_DOMAINS else len(ENTITY_DOMAINS)


def _entity_sort_key(row):
    return (int(row.get("is_alias") or 0), _domain_rank(row),
            -int(row.get("frequency") or 0))


def _display_key(row):
    return norm(row.get("display_value") or row.get("target_value"))


def build_resolve_sql(catalog_table, term_norm, fuzzy):
    """SQL over the value catalog (alias fallback only). Exact pass matches
    normalized_value; fuzzy pass uses an escaped LIKE."""
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


def alias_suggestions(rows, term_norm):
    """Alias rows (is_alias=1) to propose when no real match was found, ranked by
    closeness to the term and de-duplicated by display name (at most 5)."""
    aliases = [r for r in (rows or [])
               if int(r.get("is_alias") or 0) == 1
               and r.get("target_column") and r.get("target_value")]
    if not aliases:
        return []

    def rank(r):
        ratio = difflib.SequenceMatcher(
            None, term_norm, norm(r.get("normalized_value"))).ratio()
        return (-ratio,) + _entity_sort_key(r)

    aliases.sort(key=rank)
    out, seen = [], set()
    for r in aliases:
        k = _display_key(r)
        if k not in seen:
            seen.add(k)
            out.append(r)
        if len(out) >= 5:
            break
    return out


# ============================================================
# AGENT TOOL
# ============================================================
class MyAgentTool(BaseAgentTool):
    """Search a term across the whole dataset and return the matching values."""

    def __init__(self):
        self._tables = {}
        self._cache = {}          # key -> (expires_at, payload)

    # --- DSS access (overridden in tests) -------------------------------------
    def _get_table(self, dataset_name):
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

    def _live_columns_typed(self, dataset_name):
        """[(name, type)] from the schema (metadata read, no scan)."""
        schema = dataiku.Dataset(dataset_name).read_schema()
        out = []
        for c in schema:
            if isinstance(c, dict):
                name, typ = c.get("name"), str(c.get("type") or "")
            else:
                name, typ = getattr(c, "name", None), str(getattr(c, "type", "") or "")
            if name:
                out.append((name, typ))
        return out

    def _run_sql(self, dataset_name, sql, max_rows=SEARCH_SAMPLE_ROWS):
        """Read-only execution -> (columns, list-of-dict rows). Streaming reader
        first (no pandas), query_to_df fallback."""
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

    def _alias_fallback(self, term, catalog):
        """Catalog aliases to suggest when the search finds nothing. A missing,
        empty or unreadable catalog yields no suggestions and never raises."""
        term_norm = norm(term)
        if not term_norm or not catalog:
            return []
        try:
            catalog_table = self._get_table(catalog)
            _, exact = self._run_sql(
                catalog,
                build_resolve_sql(catalog_table, term_norm, fuzzy=False),
                max_rows=RESOLVE_EXACT_LIMIT)
            sugg = alias_suggestions(exact, term_norm)
            if sugg:
                return sugg
            _, fuzzy = self._run_sql(
                catalog,
                build_resolve_sql(catalog_table, term_norm, fuzzy=True),
                max_rows=RESOLVE_FUZZY_LIMIT)
            return alias_suggestions(fuzzy, term_norm)
        except Exception:
            logger_warn("alias fallback unavailable for %r" % term)
            return []

    # --- cache ----------------------------------------------------------------
    def _cache_key(self, dataset, term, raw_attributes, search_columns=None):
        """Key: dataset + accent-folded needle + requested attribute names + the
        resolved search-column allowlist (case/space-insensitive). The allowlist
        is part of the key because it changes which columns are scanned."""
        attrs = tuple(sorted(n for n in (norm(a) for a in raw_attributes or []) if n))
        scols = tuple(sorted(search_columns or []))
        return (dataset, search_value(term), attrs, scols)

    def _cache_get(self, key):
        hit = self._cache.get(key)
        if not hit:
            return None
        expires_at, payload = hit
        if expires_at < time.time():
            self._cache.pop(key, None)
            return None
        return payload

    def _cache_put(self, key, payload):
        if len(self._cache) >= CACHE_MAX_ENTRIES:
            oldest = min(self._cache, key=lambda k: self._cache[k][0])
            self._cache.pop(oldest, None)
        self._cache[key] = (time.time() + CACHE_TTL_SECONDS, payload)

    # --- contract -------------------------------------------------------------
    def get_descriptor(self, tool):
        return {
            "description": (
                "Look up an EXISTING value in the data: does a NAMED thing exist, "
                "in WHICH column it is, its EXACT spelling, and a named record's "
                "plain attribute (the account manager / carrier code / sales zone "
                "OF a named account). It is a fast case- and accent-insensitive "
                "search across every text column (like the dataset's search box). "
                "Use it ONLY for a who/what-is question about a SINGLE named thing: "
                "'is there a customer/account manager named X?', 'who is the "
                "account manager of <customer>?', 'carrier code of <account>?'. "
                "NEVER use it for a sum, total, count, average, ranking, top-N, "
                "share, trend, period or scenario comparison, or any COMPUTED "
                "number, and NEVER for 'list all X' - route those to the "
                "specialist. Pass the term as typed (spelling/casing/accents do "
                "not matter). By default the result is 'found_in': the column(s) "
                "where the term appears with its exact value(s). To also get OTHER "
                "columns' values for the matched record (e.g. the account manager "
                "of a customer), pass 'attributes' with the wanted column names; "
                "they come back under 'attributes'. If 'found_in' spans several "
                "columns (multi_column=true) the term is ambiguous: ask the user "
                "which one. status 'suggestions' offers close aliases and "
                "'not_found' means the quick search did not pinpoint it - in both "
                "cases ask the user or hand the question to the specialist; never "
                "assert the data does not exist."
            ),
            "inputSchema": {
                "$id": "https://owismind/tools/attribute_lookup/input",
                "title": "AttributeLookupInput",
                "type": "object",
                "properties": {
                    "entity": {
                        "type": "string",
                        "description": (
                            "Term to search anywhere in the dataset, as the user "
                            "typed it (e.g. 'Algerie Telecom', 'blanchard')."
                        ),
                    },
                    "attributes": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "OPTIONAL. Return only these column(s) (e.g. "
                            "['account manager']). Omit to get every column's "
                            "matching value(s). Case and underscores do not matter."
                        ),
                    },
                    "dataset": {
                        "type": "string",
                        "description": (
                            "OPTIONAL, set by the caller: the Dataiku dataset to "
                            "search. Defaults to the configured fact dataset."
                        ),
                    },
                    "catalog": {
                        "type": "string",
                        "description": (
                            "OPTIONAL, set by the caller: the value-catalog dataset "
                            "for the alias fallback. Defaults to the configured one."
                        ),
                    },
                    "searchable_columns": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "OPTIONAL, set by the caller: restrict the broad search "
                            "to these text column(s). Omit / empty to search every "
                            "text column. Only narrows the SEARCH; any column is "
                            "still returnable as an attribute."
                        ),
                    },
                },
                "required": ["entity"],
            },
        }

    def invoke(self, input, trace):
        args = input.get("input", {}) or {}
        term = (args.get("entity") or "").strip()
        raw_attributes = args.get("attributes") or []
        if isinstance(raw_attributes, str):
            raw_attributes = [raw_attributes]
        # OPTIONAL caller-set allowlist of columns the broad search may scan
        # (server-side; the model never names a column). Empty = search all text.
        raw_search_columns = args.get("searchable_columns") or []
        if isinstance(raw_search_columns, str):
            raw_search_columns = [raw_search_columns]
        # Optional target dataset + value catalog; default to the configured ones.
        dataset = (args.get("dataset") or "").strip() or FACT_DATASET
        catalog = args.get("catalog")
        catalog = (catalog.strip() if isinstance(catalog, str) else "") or CATALOG_DATASET

        def out(payload):
            return {"output": payload,
                    "sources": [{"id": dataset, "type": "dataset",
                                 "name": "Dataset: %s" % dataset}]}

        if not term:
            return out({"status": "bad_input",
                        "message": "Provide a term to search."})

        typed = self._live_columns_typed(dataset)
        all_columns = [n for (n, _) in typed]
        text_columns = [n for (n, t) in typed if t == "string"]
        # Narrow the broad search to the caller's allowlist when given (e.g. only
        # named-entity / id columns, never long free-text columns). Falls back to
        # every text column when empty or unmatched.
        search_columns = resolve_search_columns(text_columns, raw_search_columns)

        keep, unknown = (None, [])
        if raw_attributes:
            keep, unknown = map_attributes(raw_attributes, all_columns)
            if not keep:
                return out({"status": "attribute_unknown",
                            "attributes_unknown": unknown,
                            "available_columns": all_columns,
                            "message": "None of the requested attributes match a "
                                       "real column."})

        # The SQL work below is cacheable; the validation branches above are not.
        cache_key = self._cache_key(dataset, term, raw_attributes, search_columns)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return out(cached)

        # Skip the broad scan for a 1-char needle (it matches almost everything).
        needle = search_value(term)
        rows, sql = [], None
        if search_columns and len(needle) >= MIN_NEEDLE_CHARS:
            fact_table = self._get_table(dataset)
            sql = build_search_sql(fact_table, search_columns, term)
            _, rows = self._run_sql(dataset, sql, max_rows=SEARCH_SAMPLE_ROWS)

        # Where the term re-confirms + the requested columns' values. A row can
        # match the SQL ILIKE yet not re-confirm Python-side (e.g. a column-name
        # casing edge), so both can be empty even with rows.
        found_in = find_matches(search_columns, rows, term) if rows else []
        attributes = (summarize_values(all_columns, rows, keep=keep)
                      if (rows and keep) else {})

        if not found_in and not attributes:
            # No usable result. Offer catalog aliases only for a bare entity
            # search; an attribute lookup returns a clean not_found instead.
            suggestions = [] if keep else self._alias_fallback(term, catalog)
            if suggestions:
                payload = {"status": "suggestions", "term": term,
                           "candidates": [{"column": r.get("target_column"),
                                           "value": r.get("target_value"),
                                           "display": r.get("display_value")}
                                          for r in suggestions],
                           "message": "No exact match for '%s'. Did you mean one "
                                      "of these?" % term}
            else:
                payload = {"status": "not_found", "term": term,
                           "message": "The quick lookup did not pinpoint '%s'. Ask "
                                      "the user to confirm the spelling, or hand "
                                      "the question to the specialist." % term}
            self._cache_put(cache_key, payload)
            return out(payload)

        payload = {
            "status": "found",
            "term": term,
            "found_in": found_in,
            "rows_matched": len(rows),
            "rows_capped": len(rows) >= SEARCH_SAMPLE_ROWS,   # LIMIT hit -> sample
            "multi_column": len(found_in) > 1,                # term in >1 column
            "sql": sql,
        }
        if keep:
            payload["attributes"] = attributes
        if unknown:
            payload["attributes_unknown"] = unknown
        self._cache_put(cache_key, payload)
        return out(payload)


def logger_warn(message):
    """Minimal stdlib logger; keeps the tool dependency-free."""
    try:
        import logging
        logging.getLogger(__name__).warning(message)
    except Exception:
        pass
