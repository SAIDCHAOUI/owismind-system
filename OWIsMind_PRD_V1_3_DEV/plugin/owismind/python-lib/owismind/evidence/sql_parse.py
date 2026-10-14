"""Pure SQL analysis for Evidence Studio (NO dataiku import - unit-testable).

Turns the agent-generated SELECT stored in ``webapp_chat_v5.generated_sql`` into
a structured, re-buildable description:

    parse_select(sql) -> {
        "ok":         bool,        # False -> degraded mode (raw SQL display only)
        "reason":     str | None,  # stable code when ok is False
        "schema":     str | None,  # schema of the FIRST table found (back-compat)
        "table":      str | None,  # first table found (back-compat)
        "tables":     [{"schema", "table"}],  # ALL source tables, scan order
        "predicates": [{"id", "column", "op", "values", "editable",
                        "binding", "scope_tables"}],
        "advanced":   str | None,  # non-decomposable WHERE rest, ONE fragment
                                   # (only emitted for a plain single-table query)
    }

BEST-EFFORT extraction (user decision, supersedes the v1 strict-fidelity rule):
the parse never fails because the query is "too complex". JOINs, GROUP BY,
sub-queries, CTEs and set operations all parse - the goal is to recover the
SOURCE TABLES and every WHERE predicate that maps onto one of them, so the
Evidence panel can always show the (filtered) source data. What cannot be
mapped (aggregations, join plumbing, cross-table conditions) is simply ignored
for the exploratory view; ``ok`` is False only when the text is not one
analysable SELECT at all (not SQL, multiple statements, unknown characters).

How predicates are scoped: the statement is scanned into SELECT *scopes* (the
outer query, each `(SELECT ...)` sub-query/CTE body). Each scope records its
FROM/JOIN table refs (with aliases) and its own WHERE span. A predicate carries
``binding`` (the lower-cased table its column qualifier resolves to, or None
when unqualified) and ``scope_tables`` (the lower-cased tables of its scope) so
``predicates_for_table`` can keep exactly the ones that apply to the matched
source table - a self-join keeps both sides' filters, a different joined
table's filter is dropped.

Nothing here ever executes SQL. The service layer re-validates everything again
(columns against the live dataset schema, the fragment via validate_fragment)
before any quoting/execution, and the fragment is only ever appended to a
bounded read-only SELECT on a discovered project dataset.
"""

import re

# Hard bound on the SQL text we analyse (instance safety: the parser is O(n) but
# there is no reason to tokenize megabytes - anything bigger means degraded mode).
MAX_SQL_CHARS = 20000

# Recursion cap for nested (SELECT ...) groups: 20k chars admit ~1300 nesting
# levels, enough to blow the interpreter stack. Past this depth deeper groups
# are treated as opaque (their tables/filters are simply not extracted) so
# parse_select keeps its "never raises" contract.
MAX_SCOPE_DEPTH = 40

# Hard bound on a re-executable advanced WHERE fragment.
MAX_FRAGMENT_CHARS = 2000

# Words that must NEVER appear in a re-executed WHERE fragment (word-boundary,
# case-insensitive, with string literals masked out by the tokenizer first):
# statement starters, set ops, DML/DDL and execution primitives.
_BANNED_FRAGMENT_WORDS = frozenset((
    "select", "union", "intersect", "except", "insert", "update", "delete",
    "drop", "alter", "grant", "revoke", "copy", "create", "truncate",
    "execute", "exec", "call", "do", "set", "into", "returning", "lateral",
))


class Token(object):
    """One lexical token; start/end are offsets into the ORIGINAL text so
    fragments keep the agent's exact spelling (values with spaces, casts...)."""

    __slots__ = ("kind", "text", "start", "end")

    def __init__(self, kind, text, start, end):
        self.kind = kind
        self.text = text
        self.start = start
        self.end = end


# ':' '+' '-' '/' '%' '[' ']' are tokenized so a cast/arithmetic only makes ITS
# conjunct non-simple (-> advanced fragment) instead of failing the whole parse.
_TOKEN_RE = re.compile(
    r"""
      (?P<ws>\s+)
    | (?P<comment>--|/\*)
    | (?P<string>'(?:[^']|'')*')
    | (?P<qident>"(?:[^"]|"")*")
    | (?P<number>\d+(?:\.\d+)?)
    | (?P<op><=|>=|<>|!=|=|<|>)
    | (?P<punct>[(),;.:+\-/%*\[\]])
    | (?P<word>[A-Za-z_][A-Za-z0-9_$]*)
    """,
    re.VERBOSE,
)


def tokenize(sql):
    """Tokenize ``sql``. Returns ``(tokens, None)`` or ``(None, reason)``.

    Comments are rejected outright ('comment_unsupported'): they may not appear
    in a fragment we could re-execute. Any character the grammar does not know
    (backslash, $$-quoting, ||, ...) fails with 'tokenize_failed' - degraded mode.
    An unterminated string/quoted identifier never matches -> 'tokenize_failed'.
    """
    tokens = []
    pos = 0
    n = len(sql)
    while pos < n:
        m = _TOKEN_RE.match(sql, pos)
        if m is None:
            return None, "tokenize_failed"
        if m.lastgroup == "comment":
            return None, "comment_unsupported"
        if m.lastgroup != "ws":
            tokens.append(Token(m.lastgroup, m.group(), m.start(), m.end()))
        pos = m.end()
    return tokens, None


def validate_fragment(text):
    """True when an advanced WHERE fragment is safe to append to a read query.

    The fragment comes from the agent's OWN already-executed SQL and is only ever
    applied to a discovered project dataset inside a bounded SELECT - this is the
    final defensive gate: no second statement, no subquery/set-op/DML keyword, no
    comment, no pg_* function (pg_sleep & friends), balanced parens, bounded
    length. String literals are masked via the tokenizer before the keyword scan
    (so ``status = 'selected'`` passes).

    Trust model for function names: only ``pg_*`` and the banned-word list are
    blocked by NAME (checked on bare AND quoted identifiers). Broader safety is
    NOT name-based - it relies on the fragment being agent-authored, re-validated
    here on every request, and only ever appended to a bounded read-only SELECT
    on a project-discovered dataset.
    """
    if not isinstance(text, str) or not text.strip():
        return False
    if len(text) > MAX_FRAGMENT_CHARS:
        return False
    # Reject ANY backslash, even inside string literals: PostgreSQL
    # backslash-escape semantics are configuration-dependent
    # (standard_conforming_strings), so we refuse rather than reason about them.
    if "\\" in text:
        return False
    tokens, err = tokenize(text)
    if err:
        return False  # comments, unterminated strings, unknown characters
    depth = 0
    for t in tokens:
        if t.text == ";":
            return False
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth < 0:
                return False
        if t.kind in ("word", "qident"):
            # A quoted identifier can name a function ("pg_sleep"(10)): unquote
            # and apply the SAME banned-word / pg_ check as bare words.
            name = t.text if t.kind == "word" else t.text[1:-1].replace('""', '"')
            low = name.lower()
            if low in _BANNED_FRAGMENT_WORDS or low.startswith("pg_"):
                return False
    return depth == 0


# Clause keywords that terminate the FROM/WHERE sections we care about. GROUP BY /
# ORDER BY / LIMIT and SELECT-list aggregates are deliberately IGNORED: Evidence
# shows the agent's row SCOPE (the filtered table), not its aggregate.
_CLAUSE_ENDERS = {"GROUP", "ORDER", "LIMIT", "OFFSET", "HAVING", "FETCH", "WINDOW", "FOR"}
_JOIN_WORDS = {"JOIN", "INNER", "LEFT", "RIGHT", "FULL", "CROSS", "NATURAL", "OUTER"}
_SET_OPS = {"UNION", "EXCEPT", "INTERSECT"}
# Words that can follow a table ref but are NEVER a bare alias.
_NON_ALIAS_WORDS = (
    _CLAUSE_ENDERS | _JOIN_WORDS | _SET_OPS | {"WHERE", "ON", "USING", "AND", "OR"}
)

# Operators a chip can faithfully display; only '=' and 'IN' are value-editable
# as parsed - the UI lets the user EDIT any chip, which converts it to =/IN.
EDITABLE_OPS = ("=", "IN")
_SIMPLE_OPS = {"=", "!=", "<>", "<", "<=", ">", ">="}


def _failed(reason):
    return {"ok": False, "reason": reason, "schema": None, "table": None,
            "tables": [], "predicates": [], "advanced": None}


def _is_word(tok, word):
    return tok.kind == "word" and tok.text.upper() == word


def _read_ident(tokens, j):
    """``(name, next_index)`` for an identifier token at j, or ``(None, j)``."""
    if j < len(tokens):
        t = tokens[j]
        if t.kind == "word":
            return t.text, j + 1
        if t.kind == "qident":
            return t.text[1:-1].replace('""', '"'), j + 1
    return None, j


def _match_paren(tokens, i, hi):
    """Index of the ')' matching the '(' at ``i`` (bounded by hi), or None."""
    depth = 0
    for j in range(i, hi):
        text = tokens[j].text
        if text == "(":
            depth += 1
        elif text == ")":
            depth -= 1
            if depth == 0:
                return j
    return None


def _split_conjuncts(toks):
    """Split WHERE tokens on top-level AND. Returns ``(conjuncts, has_top_level_or)``.
    A BETWEEN consumes its own AND (pending counter), so it never splits."""
    conjuncts, cur = [], []
    depth, between, has_or = 0, 0, False
    for t in toks:
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        if depth == 0 and t.kind == "word":
            u = t.text.upper()
            if u == "BETWEEN":
                between += 1
            elif u == "AND":
                if between:
                    between -= 1
                else:
                    if cur:
                        conjuncts.append(cur)
                    cur = []
                    continue
            elif u == "OR":
                has_or = True
        cur.append(t)
    if cur:
        conjuncts.append(cur)
    return conjuncts, has_or


def _strip_parens(toks):
    """Strip ALL paren pairs that wrap the WHOLE conjunct - one O(m) pass.

    With ``p`` leading '(' tokens, ``q`` trailing ')' tokens and ``d`` the
    minimum running depth over the span between them (after token p-1 up to
    after token n-q-1), exactly ``k = min(p, q, d)`` layers wrap the whole run:
    any deeper layer is closed-and-reopened somewhere in the middle (d caps it).
    """
    n = len(toks)
    p = 0
    while p < n and toks[p].text == "(":
        p += 1
    if p == 0 or p == n:
        return toks
    q = 0
    while q < n and toks[n - 1 - q].text == ")":
        q += 1
    if q == 0:
        return toks
    depth, d = 0, None
    for idx in range(n - q):
        t = toks[idx]
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        if idx >= p - 1 and (d is None or depth < d):
            d = depth
    k = min(p, q, d)
    return toks[k : n - k] if k > 0 else toks


def _literal(tok):
    """``(python_value, True)`` for a literal token, else ``(None, False)``."""
    if tok.kind == "string":
        return tok.text[1:-1].replace("''", "'"), True
    if tok.kind == "number":
        return (float(tok.text) if "." in tok.text else int(tok.text)), True
    if tok.kind == "word" and tok.text.upper() in ("TRUE", "FALSE"):
        return tok.text.upper() == "TRUE", True
    return None, False


def _read_literal_list(tokens, j):
    """Parse ``( literal (, literal)* )`` from j -> ``(values, next)`` or None."""
    if j >= len(tokens) or tokens[j].text != "(":
        return None
    values, j, expect_value = [], j + 1, True
    while j < len(tokens):
        t = tokens[j]
        if expect_value:
            value, ok = _literal(t)
            if not ok:
                return None
            values.append(value)
            expect_value = False
        elif t.text == ",":
            expect_value = True
        elif t.text == ")":
            return values, j + 1
        else:
            return None
        j += 1
    return None


def _try_simple(toks):
    """One conjunct -> predicate dict (with its column qualifier), or None.

    ``qualifier`` is the identifier right before the column (``r."Product"`` ->
    ``"r"``), so the caller can bind the predicate to the aliased table it
    actually constrains. None when the column is unqualified.
    """
    toks = _strip_parens(toks)
    if len(toks) < 2:
        return None
    col, j = _read_ident(toks, 0)
    if col is None:
        return None
    qualifier = None
    while j < len(toks) and toks[j].text == ".":
        nxt, j = _read_ident(toks, j + 1)  # alias.col -> keep the column part
        if nxt is None:
            return None
        qualifier, col = col, nxt
    if j >= len(toks):
        return None
    t = toks[j]
    if t.kind == "op" and t.text in _SIMPLE_OPS:
        if j + 2 != len(toks):
            return None
        value, ok = _literal(toks[j + 1])
        if not ok:
            return None
        return {"column": col, "op": "!=" if t.text == "<>" else t.text,
                "values": [value], "qualifier": qualifier}
    if t.kind != "word":
        return None
    u = t.text.upper()
    if u == "IS":
        words = [x.text.upper() for x in toks[j + 1 :]]
        if words == ["NULL"]:
            return {"column": col, "op": "IS NULL", "values": [], "qualifier": qualifier}
        if words == ["NOT", "NULL"]:
            return {"column": col, "op": "IS NOT NULL", "values": [], "qualifier": qualifier}
        return None
    negate = False
    if u == "NOT" and j + 1 < len(toks) and _is_word(toks[j + 1], "IN"):
        negate, j, u = True, j + 1, "IN"
    if u == "IN":
        parsed = _read_literal_list(toks, j + 1)
        if parsed is None:
            return None
        values, end = parsed
        if end != len(toks) or not values:
            return None
        return {"column": col, "op": "NOT IN" if negate else "IN",
                "values": values, "qualifier": qualifier}
    if u == "BETWEEN":
        if j + 4 != len(toks) or not _is_word(toks[j + 2], "AND"):
            return None
        lo, ok1 = _literal(toks[j + 1])
        hi, ok2 = _literal(toks[j + 3])
        if not (ok1 and ok2):
            return None
        return {"column": col, "op": "BETWEEN", "values": [lo, hi], "qualifier": qualifier}
    if u in ("LIKE", "ILIKE"):
        if j + 2 != len(toks) or toks[j + 1].kind != "string":
            return None
        value, _ = _literal(toks[j + 1])
        return {"column": col, "op": u, "values": [value], "qualifier": qualifier}
    return None


def _read_table_ref(tokens, j, hi):
    """``(ref, next_index)`` for a table reference at j, or ``(None, j)``.

    ``ref`` = {"schema", "table", "alias"} - ident(.ident)* plus an optional
    ``AS x`` / bare / quoted alias. Clause keywords are never read as an alias,
    and the transparent LATERAL/ONLY prefixes are never read as a table name.
    """
    while j < hi and tokens[j].kind == "word" and tokens[j].text.upper() in ("LATERAL", "ONLY"):
        j += 1
    parts = []
    part, j2 = _read_ident(tokens, j)
    if part is None:
        return None, j
    parts.append(part)
    while j2 < hi and tokens[j2].text == ".":
        part, j2 = _read_ident(tokens, j2 + 1)
        if part is None or len(parts) >= 3:
            return None, j2
        parts.append(part)
    alias = None
    if j2 < hi and _is_word(tokens[j2], "AS"):
        alias, j2 = _read_ident(tokens, j2 + 1)
    elif j2 < hi and tokens[j2].kind == "qident":
        alias, j2 = _read_ident(tokens, j2)
    elif j2 < hi and tokens[j2].kind == "word":
        if tokens[j2].text.upper() not in _NON_ALIAS_WORDS:
            alias, j2 = _read_ident(tokens, j2)
    return ({"schema": parts[-2] if len(parts) >= 2 else None,
             "table": parts[-1], "alias": alias}, j2)


def _scan_scopes(tokens, lo, hi, scopes, depth=0):
    """Collect SELECT scopes within ``tokens[lo:hi)`` (recursive, depth-capped).

    One scope per SELECT body: the outer statement, plus every parenthesized
    group whose first token is SELECT (sub-queries, CTE bodies, IN (...) sets).
    Non-SELECT paren groups (function args like EXTRACT(x FROM y), USING (...))
    are opaque - their content can never register tables or WHERE spans.
    Each scope records its FROM/JOIN refs and its first WHERE span (start, end).
    A set-operation keyword ends the scan: only the FIRST arm of a UNION/
    EXCEPT/INTERSECT is analysed (same rule as the top level).
    """
    scope = {"refs": [], "where": None}
    scopes.append(scope)
    where_start = None
    in_from = False  # between FROM and the next clause: scope-level ',' = comma join

    def close_where(end):
        if where_start is not None and scope["where"] is None and end > where_start:
            scope["where"] = (where_start, end)

    i = lo
    while i < hi:
        t = tokens[i]
        if t.text == "(":
            close = _match_paren(tokens, i, hi)
            if close is None:  # unbalanced - tolerated, parse_select gated it already
                i += 1
                continue
            if depth < MAX_SCOPE_DEPTH and i + 1 < close and _is_word(tokens[i + 1], "SELECT"):
                _scan_scopes(tokens, i + 1, close, scopes, depth + 1)
            i = close + 1
            continue
        if t.text == "," and in_from:
            # Comma join - also reached after a derived table: FROM (SELECT…) s, t2
            ref, j = _read_table_ref(tokens, i + 1, hi)
            if ref is not None:
                scope["refs"].append(ref)
                i = j
                continue
            i += 1
            continue
        if t.kind == "word":
            u = t.text.upper()
            if u in ("FROM", "JOIN"):
                # The FROM of the `IS [NOT] DISTINCT FROM` operator is NOT a
                # table site - it always directly follows the word DISTINCT.
                if u == "FROM" and i > lo and _is_word(tokens[i - 1], "DISTINCT"):
                    i += 1
                    continue
                in_from = True
                ref, j = _read_table_ref(tokens, i + 1, hi)
                if ref is not None:
                    scope["refs"].append(ref)
                    i = j
                    continue
                # FROM ( SELECT ... ) - the paren group is handled by the loop.
                i += 1
                continue
            if u == "WHERE":
                in_from = False
                where_start = i + 1
                i += 1
                continue
            if u in _SET_OPS:
                # First-arm-only analysis: later arms' tables and WHERE would
                # otherwise merge into THIS scope and misattribute filters.
                close_where(i)
                return
            if u in _CLAUSE_ENDERS:
                in_from = False
                close_where(i)
                where_start = None
                i += 1
                continue
        i += 1
    close_where(hi)


def _render_fragment(sql, toks, alias_map):
    """Fragment text from a token run, with known table qualifiers stripped.

    The rebuilt evidence query targets the bare source table (no alias), so a
    verbatim ``r."amount" > 100`` would not execute - drop the WHOLE qualifier
    chain (``alias.`` or ``schema.table.``) whenever the part right before the
    column resolves in the scope's alias map; an unknown qualifier keeps the
    chain untouched (never a partial strip). Everything kept is emitted as
    VERBATIM slices of the original text (consecutive kept tokens stay one
    slice), so literal spelling, casts (``::``) and spacing survive.
    """
    runs = []  # inclusive [first, last] token-index runs to keep
    i, n = 0, len(toks)
    while i < n:
        t = toks[i]
        if t.kind in ("word", "qident") and i + 2 < n and toks[i + 1].text == ".":
            # Maximal dotted identifier chain toks[i], toks[i+2], ..., toks[j].
            j = i
            while j + 2 < n and toks[j + 1].text == "." and toks[j + 2].kind in ("word", "qident"):
                j += 2
            if j > i:
                qual = toks[j - 2]
                name = qual.text if qual.kind == "word" else qual.text[1:-1].replace('""', '"')
                if name.lower() in alias_map:
                    i = j  # drop the full qualifier chain; keep the column token
        if runs and runs[-1][1] == i - 1:
            runs[-1][1] = i
        else:
            runs.append([i, i])
        i += 1
    return " ".join(sql[toks[a].start : toks[b].end] for a, b in runs)


def parse_select(sql):
    """Best-effort analysis of one agent-generated statement. Never raises.

    ``ok`` is False only when the text is not ONE analysable statement at all
    (empty, oversized, unknown characters, comments, multiple statements, or not
    a SELECT/WITH). Everything else parses: JOINs, GROUP BY, sub-queries, CTEs;
    a top-level set operation analyses its FIRST arm.
    """
    if not isinstance(sql, str) or not sql.strip():
        return _failed("invalid_sql")
    if len(sql) > MAX_SQL_CHARS:
        return _failed("sql_too_long")
    tokens, err = tokenize(sql)
    if err:
        return _failed(err)
    # One trailing semicolon is tolerated; any other means multiple statements.
    if tokens and tokens[-1].text == ";":
        tokens = tokens[:-1]
    if any(t.text == ";" for t in tokens):
        return _failed("multi_statement")
    if not tokens or not (_is_word(tokens[0], "SELECT") or _is_word(tokens[0], "WITH")):
        return _failed("not_select")
    # Balanced parens (the scope scanner relies on it).
    depth = 0
    for t in tokens:
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth < 0:
                return _failed("unbalanced_parens")
    if depth != 0:
        return _failed("unbalanced_parens")
    # Top-level set operation: analyse the FIRST arm only (best-effort).
    depth, cut = 0, len(tokens)
    for idx, t in enumerate(tokens):
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
        elif depth == 0 and t.kind == "word" and t.text.upper() in _SET_OPS:
            cut = idx
            break
    tokens = tokens[:cut]

    scopes = []
    _scan_scopes(tokens, 0, len(tokens), scopes)

    # Source-table candidates, scan order, deduped - the service matches them
    # against the project's discovered datasets (first match = source table).
    tables, seen = [], set()
    for scope in scopes:
        for ref in scope["refs"]:
            key = ((ref["schema"] or "").lower(), ref["table"].lower())
            if key not in seen:
                seen.add(key)
                tables.append({"schema": ref["schema"], "table": ref["table"]})

    # The advanced fragment is only re-executable when the statement is one
    # plain single-table SELECT (a fragment sliced out of a join/sub-query can
    # reference other relations and would not run against the source table).
    single = len(scopes) == 1 and len(scopes[0]["refs"]) == 1

    predicates, fragments, pid = [], [], 0
    for scope in scopes:
        if scope["where"] is None:
            continue
        # Two passes so an EXPLICIT alias always wins over another ref's bare
        # table name (FROM a x JOIN x … is invalid SQL anyway; aliases are the
        # deliberate signal): self-names first, aliases override.
        alias_map, scope_tables = {}, []
        for ref in scope["refs"]:
            low = ref["table"].lower()
            if low not in scope_tables:
                scope_tables.append(low)
            alias_map.setdefault(low, low)
        for ref in scope["refs"]:
            if ref["alias"]:
                alias_map[ref["alias"].lower()] = ref["table"].lower()
        where_toks = tokens[scope["where"][0] : scope["where"][1]]
        conjuncts, has_or = _split_conjuncts(where_toks)
        if has_or:
            # Top-level OR: the conjuncts are not independent - the whole WHERE
            # is one fragment (usable only in the single-table case).
            if single:
                fragments.append(_render_fragment(sql, where_toks, alias_map))
            continue
        for conj in conjuncts:
            pred = _try_simple(conj)
            if pred is None:
                if single:
                    fragments.append(_render_fragment(sql, conj, alias_map))
                pid += 1
                continue
            qualifier = pred.pop("qualifier", None)
            pred["id"] = pid
            pred["editable"] = pred["op"] in EDITABLE_OPS
            # binding: the table this predicate's qualifier resolves to (lower-
            # cased); an unknown qualifier stays as-is and simply never matches.
            pred["binding"] = alias_map.get(qualifier.lower(), qualifier.lower()) if qualifier else None
            pred["scope_tables"] = scope_tables
            predicates.append(pred)
            pid += 1

    advanced = " AND ".join(f for f in fragments if f) if fragments else None
    primary = tables[0] if tables else {"schema": None, "table": None}
    return {"ok": True, "reason": None, "schema": primary["schema"],
            "table": primary["table"], "tables": tables,
            "predicates": predicates, "advanced": advanced}


def predicates_for_table(predicates, table):
    """The predicates that apply to ONE matched source table (best-effort keep).

    Keep a predicate when (a) its SELECT scope actually reads the matched table
    and (b) its column qualifier - if any - binds to that table. Unqualified
    predicates in a multi-table scope are kept: the service still checks the
    column against the live dataset schema before use.
    """
    t = (table or "").lower()
    out = []
    for pred in predicates or []:
        if t not in (pred.get("scope_tables") or ()):
            continue
        binding = pred.get("binding")
        if binding is not None and binding != t:
            continue
        out.append(pred)
    return out


# --- Result re-run gate (full result paging) ------------------------------------
# The Evidence "result" tables page through the agent's OWN final SELECT, re-run
# server-side wrapped in a bounded outer SELECT (COUNT / LIMIT-OFFSET). The statement
# was authored by the agent and already executed once; this gate is the defensive
# layer on top of the read-only transaction + statement timeout. It is a SECURITY
# gate, so unlike the best-effort ``_scan_scopes`` it never treats anything as
# opaque: every FROM / JOIN / comma-join site at EVERY nesting depth (function
# arguments and doubly-parenthesized sub-queries included) yields a relation, and
# the service requires each of them to be a discovered project dataset. CTEs are
# accepted only as ONE top-level WITH list (no RECURSIVE, no nested WITH), and a
# CTE name only shadows a relation where PostgreSQL scoping makes it visible: in
# the main query, or in the body of a LATER CTE - never inside its own body or an
# earlier one (``WITH t AS (SELECT * FROM t)`` reads the real table t).
_BANNED_RERUN_WORDS = frozenset((
    "insert", "update", "delete", "merge", "upsert", "drop", "alter", "grant",
    "revoke", "copy", "create", "truncate", "execute", "exec", "call", "do", "into",
    "returning", "lock", "vacuum", "analyze", "refresh", "listen", "notify",
    "union", "intersect", "except", "recursive", "set_config", "ts_stat",
    "ts_rewrite",
))
# Function families that touch files / other databases / session state, or run a
# query given as TEXT (query_to_xml, table_to_xml, ... read relations the table
# check below cannot see).
_BANNED_RERUN_PREFIXES = ("pg_", "lo_", "dblink", "query_to_", "table_to_",
                          "schema_to_", "database_to_", "cursor_to_")
# Bare words banned only as KEYWORDS (a quoted identifier of that name is a column):
# ``(TABLE x)`` is a sub-query reading relation x without any FROM.
_BANNED_RERUN_KEYWORDS = frozenset(("table",))
# SQL-standard functions whose argument list uses FROM as a separator, not a table site.
_FROM_ARG_FUNCTIONS = frozenset(("EXTRACT", "SUBSTRING", "SUBSTR", "TRIM", "OVERLAY",
                                 "POSITION"))
# Words that end a FROM list at the current depth (a later ',' is a select/group list).
_FROM_LIST_ENDERS = _CLAUSE_ENDERS | {"WHERE", "SELECT"}


# ALLOWLIST of callable names (a word or quoted identifier directly followed by '(').
# A deny-list of dangerous functions can never be complete (server-side file or
# network access, functions running a query given as text, user-defined functions),
# so the re-run gate only accepts plain read-only built-ins an analytics SELECT uses;
# anything else - including any schema-qualified call - refuses the re-run (the table
# then keeps the captured excerpt with an honest caveat).
_SAFE_FUNCTIONS = frozenset((
    # aggregates
    "sum", "count", "avg", "min", "max", "stddev", "stddev_pop", "stddev_samp",
    "variance", "var_pop", "var_samp", "string_agg", "array_agg", "bool_and",
    "bool_or", "every", "percentile_cont", "percentile_disc", "mode", "corr",
    "covar_pop", "covar_samp", "regr_slope", "regr_intercept", "json_agg", "jsonb_agg",
    # window
    "row_number", "rank", "dense_rank", "percent_rank", "cume_dist", "ntile", "lag",
    "lead", "first_value", "last_value", "nth_value",
    # conditional / casts / types
    "coalesce", "nullif", "greatest", "least", "cast", "numeric", "decimal", "varchar",
    "char", "character", "int", "integer", "bigint", "smallint", "float", "real",
    "timestamp", "timestamptz", "time", "interval", "date", "text", "boolean",
    # math
    "round", "trunc", "floor", "ceil", "ceiling", "abs", "sign", "mod", "power", "sqrt",
    "exp", "ln", "log", "div", "width_bucket",
    # strings
    "lower", "upper", "initcap", "length", "char_length", "character_length",
    "octet_length", "trim", "btrim", "ltrim", "rtrim", "lpad", "rpad", "substring",
    "substr", "left", "right", "replace", "concat", "concat_ws", "split_part", "strpos",
    "position", "overlay", "repeat", "reverse", "translate", "to_char", "to_number",
    "to_date", "to_timestamp", "regexp_replace", "unaccent",
    # dates
    "date_trunc", "date_part", "extract", "age", "make_date", "make_timestamp",
    "make_interval", "justify_days", "justify_hours", "date_bin",
    # arrays / json read-only
    "array_length", "cardinality", "array_to_string", "string_to_array",
    "json_build_object", "jsonb_build_object",
))
# Keywords that legitimately precede '(' (sub-queries, lists, window clauses, ...).
_PAREN_KEYWORDS = frozenset((
    "IN", "EXISTS", "AS", "VALUES", "OVER", "FILTER", "GROUP", "ANY", "ALL", "SOME",
    "ARRAY", "ROW", "AND", "OR", "NOT", "ON", "USING", "WHERE", "FROM", "JOIN",
    "SELECT", "BY", "HAVING", "WHEN", "THEN", "ELSE", "DISTINCT", "BETWEEN", "LIKE",
    "ILIKE", "IS", "LATERAL", "MATERIALIZED", "CASE", "END", "WITHIN",
))


def _parse_top_level_ctes(tokens):
    """``(ctes, main_start)`` for a statement starting with WITH, else ``([], 0)``.

    ``ctes`` = [(lower_name, body_lo, body_hi)] in declaration order (body bounds
    are token indexes inside the CTE's parentheses). Returns ``(None, None)`` when
    the WITH list is not the simple ``name [ (cols) ] AS [ [NOT] MATERIALIZED ] (...)``
    shape - the gate then refuses rather than guesses.
    """
    if not tokens or not _is_word(tokens[0], "WITH"):
        return [], 0
    n = len(tokens)
    ctes = []
    i = 1
    while True:
        if i >= n or tokens[i].kind not in ("word", "qident"):
            return None, None
        tok = tokens[i]
        name = tok.text if tok.kind == "word" else tok.text[1:-1].replace('""', '"')
        i += 1
        if i < n and tokens[i].text == "(":
            close = _match_paren(tokens, i, n)
            if close is None:
                return None, None
            i = close + 1
        if not (i < n and _is_word(tokens[i], "AS")):
            return None, None
        i += 1
        if i < n and _is_word(tokens[i], "NOT"):
            i += 1
        if i < n and _is_word(tokens[i], "MATERIALIZED"):
            i += 1
        if not (i < n and tokens[i].text == "("):
            return None, None
        close = _match_paren(tokens, i, n)
        if close is None:
            return None, None
        ctes.append((name.lower(), i + 1, close))
        i = close + 1
        if i < n and tokens[i].text == ",":
            i += 1
            continue
        return ctes, i


def cte_names(tokens):
    """Lower-cased names of the top-level CTEs of a token list (empty when none)."""
    ctes, _main = _parse_top_level_ctes(tokens)
    return {c[0] for c in ctes or []}


def _relation_sites(tokens):
    """Every relation reference ``(ref, token_index)`` at ANY depth. Pure.

    A site is the token after FROM / JOIN, or after a comma that sits in a FROM list
    of the same parenthesis depth. Each '(' opens a fresh state (so commas of a
    function's argument list are never mistaken for comma joins); the FROM of
    EXTRACT/SUBSTRING/TRIM/OVERLAY/POSITION argument lists and of IS DISTINCT FROM
    is not a site. A site that is not an identifier (a sub-query paren) yields
    nothing: the sub-query's own sites are reached by the same flat scan.
    """
    sites = []
    stack = [{"in_from": False, "func_from": False}]
    n = len(tokens)
    for i, t in enumerate(tokens):
        top = stack[-1]
        if t.text == "(":
            prev = tokens[i - 1] if i > 0 else None
            func = bool(prev is not None and prev.kind == "word"
                        and prev.text.upper() in _FROM_ARG_FUNCTIONS)
            stack.append({"in_from": False, "func_from": func})
            continue
        if t.text == ")":
            if len(stack) > 1:
                stack.pop()
            continue
        site = False
        if t.kind == "word":
            u = t.text.upper()
            if u in ("FROM", "JOIN"):
                if u == "FROM" and (top["func_from"]
                                    or (i > 0 and _is_word(tokens[i - 1], "DISTINCT"))):
                    continue
                top["in_from"] = True
                site = True
            elif u in _FROM_LIST_ENDERS:
                top["in_from"] = False
        elif t.text == "," and top["in_from"]:
            site = True
        if site and i + 1 < n:
            ref, _j = _read_table_ref(tokens, i + 1, n)
            if ref is not None:
                sites.append((ref, i + 1))
    return sites


def check_rerunnable_select(sql):
    """Gate one stored agent SELECT before it is re-run for result paging. Never raises.

    Returns ``{"ok", "reason", "sql", "tables"}``: ``sql`` is the statement without
    its optional trailing semicolon (ready to be wrapped as a sub-query) and
    ``tables`` lists every relation the statement reads that is NOT a visible CTE
    (``{"schema", "table"}``) - the service requires each of them to resolve to a
    discovered project dataset.
    """
    def fail(reason):
        return {"ok": False, "reason": reason, "sql": None, "tables": []}

    if not isinstance(sql, str) or not sql.strip():
        return fail("invalid_sql")
    if len(sql) > MAX_SQL_CHARS:
        return fail("sql_too_long")
    if "\\" in sql:
        return fail("backslash_unsupported")
    tokens, err = tokenize(sql)
    if err:
        return fail(err)
    body_end = len(sql)
    if tokens and tokens[-1].text == ";":
        body_end = tokens[-1].start
        tokens = tokens[:-1]
    if not tokens or not (_is_word(tokens[0], "SELECT") or _is_word(tokens[0], "WITH")):
        return fail("not_select")
    depth = 0
    for idx, t in enumerate(tokens):
        if t.text == ";":
            return fail("multi_statement")
        if t.text == "(":
            depth += 1
        elif t.text == ")":
            depth -= 1
            if depth < 0:
                return fail("unbalanced_parens")
        if t.kind in ("word", "qident"):
            name = t.text if t.kind == "word" else t.text[1:-1].replace('""', '"')
            low = name.lower()
            if low in _BANNED_RERUN_WORDS or low.startswith(_BANNED_RERUN_PREFIXES):
                return fail("unsafe_sql")
            if t.kind == "word" and low in _BANNED_RERUN_KEYWORDS:
                return fail("unsafe_sql")
            if t.kind == "word" and low == "with" and idx != 0:
                return fail("nested_with_unsupported")
    if depth != 0:
        return fail("unbalanced_parens")
    ctes, main_start = _parse_top_level_ctes(tokens)
    if ctes is None:
        return fail("cte_unsupported")
    # Callable allowlist: every name followed by '(' is a known keyword, an allowed
    # built-in, or a CTE header ``name (cols) AS``; a qualified call (x.f(...)) never is.
    cte_set = {c[0] for c in ctes}
    for idx in range(len(tokens) - 1):
        t = tokens[idx]
        if tokens[idx + 1].text != "(" or t.kind not in ("word", "qident"):
            continue
        if idx > 0 and tokens[idx - 1].text == ".":
            return fail("unsafe_function")
        if t.kind == "word" and t.text.upper() in _PAREN_KEYWORDS:
            continue
        name = (t.text if t.kind == "word" else t.text[1:-1].replace('""', '"')).lower()
        if name in _SAFE_FUNCTIONS:
            continue
        if name in cte_set and idx < main_start:
            continue
        return fail("unsafe_function")
    tables, seen = [], set()
    for ref, pos in _relation_sites(tokens):
        if ref["schema"] is None:
            visible = [c[0] for c in ctes] if pos >= main_start else []
            for k, (_name, lo, hi) in enumerate(ctes):
                if lo <= pos < hi:
                    visible = [c[0] for c in ctes[:k]]  # only EARLIER CTEs
                    break
            if ref["table"].lower() in visible:
                continue
        key = ((ref["schema"] or "").lower(), ref["table"].lower())
        if key not in seen:
            seen.add(key)
            tables.append({"schema": ref["schema"], "table": ref["table"]})
    if not tables:
        return fail("no_source_table")
    return {"ok": True, "reason": None, "sql": sql[:body_end].strip(), "tables": tables}
