# -*- coding: utf-8 -*-
"""attribute_lookup - Custom Python agent tool for OWIsMind sub-agents.

The FAST path for plain reads about a named thing - NO semantic model, NO
dataframe in memory. It behaves like Dataiku's "Whole data" search box: a
case-insensitive filter over EVERY text column of the dataset that returns the
matching values of the other columns (or only the column you asked for).

Examples it answers in < 1s:
  - "who is the account manager of <customer>?"  (the term is the customer)
  - "what does <account_manager> manage?"        (the term is the manager)
  - "carrier code / sales zone / parent group of <account>?"

Flow:
  1. SEARCH: SELECT * FROM <fact> WHERE (unaccent(col1) ILIKE %term% OR ...) over
     every text column - the term is matched ANYWHERE, spelling/casing/accents
     aside (both sides are accent-folded; no DB extension needed).
  2. SUMMARIZE: distinct value(s) per column from the matched rows (or only the
     requested columns), capped. 'found_in' carries flags: rows_capped (the LIMIT
     fired -> sample) and multi_column (the term spans several columns -> ambiguous).
  3. FALLBACK: if nothing matches AND no specific attribute was asked, OFFER catalog
     aliases (short names, business concepts like 'indirect' / 'roaming hub') as
     suggestions - never auto-picked.

Safety: read-only (statement_timeout + transaction_read_only), bounded by LIMIT;
only real, schema-discovered column names ever reach the SQL; nothing is loaded
into RAM. A bounded, TTL'd in-process cache absorbs repeated lookups (distinct
values only). The catalog fallback is optional - the tool works without it.

To reuse for another dataset: change FACT_DATASET (and CATALOG_DATASET if you
keep the alias fallback). No column name is hardcoded anywhere.
"""

import re
import time
import unicodedata
import difflib

import dataiku
from dataiku.llm.agent_tools import BaseAgentTool


# ============================================================
# CONFIG - change per sub-agent / dataset
# ============================================================
FACT_DATASET = "DRIVE_Revenues"
CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"   # optional alias fallback

# Catalog search domains used only by the alias fallback, in preference order.
# Catalog convention (see build_value_catalog_recipe), not a dataset column.
ENTITY_DOMAINS = ("account", "account_group", "alias")

SEARCH_SAMPLE_ROWS = 1000     # rows scanned to collect the matching values
DISTINCT_PER_COLUMN = 25      # max distinct values returned per column
MAX_ATTRIBUTES = 12           # cap on requested attributes (anti-abuse)
RESOLVE_EXACT_LIMIT = 50      # alias fallback: exact pass
RESOLVE_FUZZY_LIMIT = 60      # alias fallback: fuzzy pass
# A one-character needle ILIKE '%x%' matches almost every row of every column:
# a pathological full scan that returns pure noise. Such terms skip the broad
# search and go straight to the alias/not-found path. Two-char codes (carrier
# codes like 'DZ') are still searched.
MIN_NEEDLE_CHARS = 2
# Bounded in-process result cache (lookups repeat heavily - the same big
# accounts get asked again and again). Keyed by (needle, requested attributes);
# values are the small resolved payloads (distinct values only, never fact
# rows), so memory stays tiny. Our call, no DB load - mirrors the table cache.
CACHE_MAX_ENTRIES = 256
CACHE_TTL_SECONDS = 120

SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'",
                   "SET LOCAL transaction_read_only TO on"]

# Accent folding done in SQL WITHOUT the unaccent extension (NO INSTALL rule):
# a fixed, generic character transliteration (not a business value). ILIKE only
# folds CASE, never accents, so a stored accented value ("Societe Generale" with
# accents) would be invisible to an accent-stripped needle. translate() on the
# COLUMN side closes that gap on any PostgreSQL, extension or not. FROM/TO must be
# equal length (translate maps char-for-char); lower() is applied first. The
# needle (search_value) folds with the SAME map (str.translate) so both sides
# fold IDENTICALLY - an out-of-map glyph (e.g. Turkish s-cedilla, Nordic o-slash)
# survives on BOTH sides instead of being dropped on one and kept on the other.
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
    """The term as a LIKE needle, folded the SAME way as the column side
    (unaccent_lower_sql): lowercased, then accent-folded through the shared
    translate map. NFKD-then-ascii-ignore is deliberately NOT used: it DROPS
    out-of-map non-ASCII glyphs on the needle while translate() KEEPS them on the
    column, which would silently de-sync the two sides and miss the row."""
    return str(term or "").strip().lower().translate(_NEEDLE_TRANSLATION)


def quote_literal(value):
    """Single-quoted SQL string literal (doubles embedded quotes)."""
    return "'" + str(value).replace("'", "''") + "'"


def quote_ident(name):
    """Double-quoted SQL identifier (doubles embedded double quotes). Only ever
    called on names already discovered from the live schema."""
    return '"' + str(name).replace('"', '""') + '"'


def like_escape(value):
    return (str(value).replace("\\", "\\\\").replace("%", "\\%")
            .replace("_", "\\_"))


def unaccent_lower_sql(col_ident):
    """SQL expression folding a column to lowercase, accent-stripped text using
    translate() - NO database extension required (the unaccent extension is a
    DBA install, out of scope). CAST(... AS text) keeps it valid whatever the
    physical type the schema reports. col_ident is an already-quoted identifier."""
    return ("translate(lower(CAST(%s AS text)), %s, %s)"
            % (col_ident, quote_literal(_ACCENTS_FROM), quote_literal(_ACCENTS_TO)))


def match_attribute_column(raw, live_columns):
    """Map a user/LLM column designation to a REAL column name, ignoring case,
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


def build_search_sql(fact_table, text_columns, term, sample=SEARCH_SAMPLE_ROWS):
    """Whole-dataset, case- AND accent-insensitive search: the term matched
    anywhere across the given text columns. Both sides are accent-folded - the
    needle by search_value(), the COLUMN by unaccent_lower_sql() - so a stored
    accented value matches an accent-stripped query. Columns are real schema
    names; the needle is a quoted, escaped literal; LIMIT bounds the scan."""
    needle = quote_literal("%" + like_escape(search_value(term)) + "%")
    ors = " OR ".join("%s ILIKE %s ESCAPE '\\'" % (unaccent_lower_sql(quote_ident(c)),
                                                   needle)
                      for c in text_columns)
    return "SELECT * FROM %s WHERE %s LIMIT %d" % (fact_table, ors, int(sample))


def find_matches(text_columns, rows, term, per_col_cap=DISTINCT_PER_COLUMN):
    """Where the term actually appears: for each text column whose value contains
    the term (accent/case-insensitive), the distinct matching value(s). This is
    the resolver answer - 'the value exists, here, with this exact spelling'.
    Returns [{column, values}] in stable column order, capped per column."""
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
    restricts to those real columns; otherwise every column is summarized. Which
    columns matter is decided from the data, never hardcoded."""
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


# ----- alias fallback (catalog) -------------------------------------------------
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
    """Alias rows (is_alias=1) to PROPOSE when no real match was found, ranked by
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
        self._cache = {}          # key -> (expires_at, payload). Bounded, TTL'd.

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
        """[(name, type)] from the schema (cheap metadata read, no scan)."""
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

    def _alias_fallback(self, term):
        """Catalog aliases to suggest when the full-text search finds nothing.
        Optional: a missing/unreadable catalog yields no suggestions, never an
        error."""
        term_norm = norm(term)
        if not term_norm:
            return []
        try:
            catalog_table = self._get_table(CATALOG_DATASET)
            _, exact = self._run_sql(
                CATALOG_DATASET,
                build_resolve_sql(catalog_table, term_norm, fuzzy=False),
                max_rows=RESOLVE_EXACT_LIMIT)
            sugg = alias_suggestions(exact, term_norm)
            if sugg:
                return sugg
            _, fuzzy = self._run_sql(
                CATALOG_DATASET,
                build_resolve_sql(catalog_table, term_norm, fuzzy=True),
                max_rows=RESOLVE_FUZZY_LIMIT)
            return alias_suggestions(fuzzy, term_norm)
        except Exception:
            logger_warn("alias fallback unavailable for %r" % term)
            return []

    # --- cache ----------------------------------------------------------------
    def _cache_key(self, term, raw_attributes):
        """Stable key: accent-folded needle + the requested attribute names
        (case/space-insensitive). Two phrasings of the same lookup share a key."""
        attrs = tuple(sorted(norm(a) for a in (raw_attributes or []) if norm(a)))
        return (search_value(term), attrs)

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
            # Drop the oldest-expiring entry (bounded, no ordering structure needed).
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
                "number, and NEVER for 'list all X' - route those to the revenue "
                "expert. Pass the term as typed (spelling/casing/accents do not "
                "matter). By default the result is 'found_in': the column(s) where "
                "the term appears with its exact value(s). To also get OTHER "
                "columns' values for the matched record (e.g. the account manager "
                "of a customer), pass 'attributes' with the wanted column names; "
                "they come back under 'attributes'. If 'found_in' spans several "
                "columns (multi_column=true) the term is ambiguous: ask the user "
                "which one. status 'suggestions' offers close aliases and "
                "'not_found' means the quick search did not pinpoint it - in both "
                "cases ask the user or hand the question to the revenue expert; "
                "never assert the data does not exist."
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

        def out(payload):
            return {"output": payload,
                    "sources": [{"id": FACT_DATASET, "type": "dataset",
                                 "name": "Dataset: %s" % FACT_DATASET}]}

        if not term:
            return out({"status": "bad_input",
                        "message": "Provide a term to search."})

        typed = self._live_columns_typed(FACT_DATASET)
        all_columns = [n for (n, _) in typed]
        text_columns = [n for (n, t) in typed if t == "string"]

        keep, unknown = (None, [])
        if raw_attributes:
            keep, unknown = map_attributes(raw_attributes, all_columns)
            if not keep:
                return out({"status": "attribute_unknown",
                            "attributes_unknown": unknown,
                            "available_columns": all_columns,
                            "message": "None of the requested attributes match a "
                                       "real column."})

        # SQL work (search + optional alias) is cacheable; the input-validation
        # branches above are not (cheap, no DB). Serve a fresh cached payload.
        cache_key = self._cache_key(term, raw_attributes)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return out(cached)

        # A 1-char needle matches almost everything: skip the broad scan and let
        # the alias/not-found path handle it (no pathological full scan, no noise).
        needle = search_value(term)
        rows, sql = [], None
        if text_columns and len(needle) >= MIN_NEEDLE_CHARS:
            fact_table = self._get_table(FACT_DATASET)
            sql = build_search_sql(fact_table, text_columns, term)
            _, rows = self._run_sql(FACT_DATASET, sql, max_rows=SEARCH_SAMPLE_ROWS)

        # What the matched rows actually yield: where the term re-confirms (exact
        # spelling) + the requested columns' values. A row can match the SQL ILIKE
        # yet not re-confirm Python-side (a column-name casing edge), so these can
        # be empty even with rows - a 'found' with nothing to show is a lie.
        found_in = find_matches(text_columns, rows, term) if rows else []
        attributes = (summarize_values(all_columns, rows, keep=keep)
                      if (rows and keep) else {})

        if not found_in and not attributes:
            # Nothing usable: no row matched, OR the matches carried neither the
            # term nor a requested attribute. Offer aliases (short names, business
            # concepts) ONLY for a bare entity search - when explicit attributes
            # were requested the caller wants a clean, fast 'not_found', not an
            # alias guess (and the catalog never indexes attribute columns anyway).
            suggestions = [] if keep else self._alias_fallback(term)
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
                                      "the question to the revenue expert." % term}
            self._cache_put(cache_key, payload)
            return out(payload)

        # Resolver answer: where the term is + its exact value(s).
        payload = {
            "status": "found",
            "term": term,
            "found_in": found_in,
            "rows_matched": len(rows),
            # The LIMIT fired: the rows above are a sample, so found_in /
            # attributes may be incomplete (the model should say "sample").
            "rows_capped": len(rows) >= SEARCH_SAMPLE_ROWS,
            # The term lives in more than one column (possibly different entities):
            # the caller should disambiguate rather than assume one.
            "multi_column": len(found_in) > 1,
            "sql": sql,
        }
        # Only when specific columns were requested do we return their values.
        if keep:
            payload["attributes"] = attributes
        if unknown:
            payload["attributes_unknown"] = unknown
        self._cache_put(cache_key, payload)
        return out(payload)


def logger_warn(message):
    """Tiny stdlib logger shim (the tool stays dependency-free)."""
    try:
        import logging
        logging.getLogger(__name__).warning(message)
    except Exception:
        pass
