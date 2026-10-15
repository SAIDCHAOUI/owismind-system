"""Authoritative check of a re-run SELECT from its PostgreSQL plan (pure, no dataiku).

The token gate (``sql_parse.check_rerunnable_select``) is a cheap first filter, but a
hand-written SQL grammar can always read a statement differently from PostgreSQL
(parenthesized joins, attribute-notation function calls ``t.f``, ...). So before the
agent's stored SELECT is re-run for result paging, the service asks PostgreSQL for
``EXPLAIN (FORMAT JSON, VERBOSE)`` of the exact wrapped query - planned, NEVER
executed - and this module inspects that plan:

- every scanned relation (``Relation Name`` + ``Schema``) must be a discovered
  project dataset (the caller passes the matcher);
- no node may scan a function / table function / tuplestore (data that is not a
  project dataset);
- every function call PostgreSQL deparsed into an expression (Output, Filter, keys,
  join conditions, ...) must be an allowlisted read-only built-in.

Anything unrecognised is a violation: the re-run is refused and the table keeps the
captured excerpt with its honest caveat (fail closed, never fail open).
"""

import json
import re

# Plan node types whose rows do not come from a relation the matcher can vouch for.
_FORBIDDEN_NODE_TYPES = frozenset((
    "Function Scan", "Table Function Scan", "Named Tuplestore Scan", "Foreign Scan",
    "Custom Scan", "Sample Scan",
))
# Plan keys holding deparsed SQL expressions (strings or lists of strings).
_EXPRESSION_KEYS = frozenset((
    "Output", "Filter", "Sort Key", "Presorted Key", "Group Key", "Hash Key",
    "Hash Cond", "Merge Cond", "Join Filter", "Recheck Cond", "Index Cond",
    "One-Time Filter", "TID Cond", "Run Condition", "Cache Key", "Function Call",
    "Order By", "Grouping Sets", "Partition Key",
))
# Names PostgreSQL itself prints before '(' when deparsing allowlisted SQL: internal
# names of built-ins / casts and expression keywords.
_DEPARSE_NAMES = frozenset((
    "any", "all", "row", "array", "coalesce", "nullif", "greatest", "least", "case",
    "extract", "date_part", "btrim", "ltrim", "rtrim", "int2", "int4", "int8",
    "float4", "float8", "bool", "bpchar", "timestamptz", "normalize", "subplan",
    "initplan", "is_normalized",
    # SQL keywords PostgreSQL prints before a parenthesized operand
    "and", "or", "not", "when", "then", "else", "end", "in", "is", "as", "distinct",
    "from", "between", "like", "ilike", "similar", "to", "some", "exists", "over",
    "partition", "by", "order", "filter", "within", "group", "values", "select",
    "where", "on", "using", "null", "true", "false", "asc", "desc", "nulls", "first",
    "last", "collate", "at", "zone", "interval", "cast", "hashed",
))
# Matches an identifier (optionally schema-qualified, optionally double-quoted)
# directly followed by '(' - i.e. a call as PostgreSQL deparses it.
_CALL_RE = re.compile(
    r'((?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*)'
    r'(?:\.(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_$]*))*)\s*\('
)
# String literals are masked before the call scan ('a(b' inside a literal is data).
_LITERAL_RE = re.compile(r"'(?:[^']|'')*'")


def _unquote(name):
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        return name[1:-1].replace('""', '"')
    return name


def decode_plan(raw):
    """The plan root dict from an EXPLAIN (FORMAT JSON) cell, or None."""
    value = raw
    if isinstance(value, (bytes, bytearray)):
        value = value.decode("utf-8", "replace")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return None
    if isinstance(value, list) and value and isinstance(value[0], dict):
        value = value[0]
    if isinstance(value, dict) and isinstance(value.get("Plan"), dict):
        return value["Plan"]
    return None


def _walk(node, out):
    if isinstance(node, dict):
        out.append(node)
        for key in ("Plans",):
            for child in node.get(key) or []:
                _walk(child, out)


def _expressions(node):
    for key in _EXPRESSION_KEYS:
        value = node.get(key)
        if isinstance(value, str):
            yield value
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, str):
                    yield item


def called_names(expression):
    """Lower-cased function names called in one deparsed expression. Pure."""
    masked = _LITERAL_RE.sub("''", expression)
    names = []
    for m in _CALL_RE.finditer(masked):
        parts = [_unquote(p) for p in re.findall(r'"(?:[^"]|"")+"|[^.]+', m.group(1))]
        names.append(".".join(parts).lower())
    return names


def plan_violations(plan, relation_allowed, function_allowed):
    """List of human-readable violations (empty = the plan may be executed). Pure.

    ``relation_allowed(schema, table) -> bool`` vouches for scanned relations;
    ``function_allowed(lower_name) -> bool`` for unqualified call names. A
    schema-qualified call is allowed only for ``pg_catalog`` built-ins that the
    function check accepts (PostgreSQL may qualify a shadowed built-in).
    """
    if not isinstance(plan, dict):
        return ["no_plan"]
    nodes = []
    _walk(plan, nodes)
    violations = []
    for node in nodes:
        node_type = node.get("Node Type")
        if node_type in _FORBIDDEN_NODE_TYPES:
            violations.append("node:%s" % node_type)
        rel = node.get("Relation Name")
        if rel is not None and not relation_allowed(node.get("Schema"), rel):
            violations.append("relation:%s.%s" % (node.get("Schema"), rel))
        for expr in _expressions(node):
            for name in called_names(expr):
                if "." in name:
                    schema, _, base = name.rpartition(".")
                    if schema == "pg_catalog" and (function_allowed(base) or base in _DEPARSE_NAMES):
                        continue
                    violations.append("function:%s" % name)
                elif not (function_allowed(name) or name in _DEPARSE_NAMES):
                    violations.append("function:%s" % name)
    return violations


def strict_relation_matcher(candidates):
    """``relation_allowed`` for plan_violations: EXACT physical match. Pure.

    Stricter than ``whitelist.match_whitelist`` (case-insensitive, schema wildcard,
    built for agent-written names): a plan carries the true relation name and
    schema, so a relation passes only when a discovered dataset has that exact
    table name in that exact schema (a dataset without a known schema is taken to
    live in ``public``, the connection default).
    """
    allowed = set()
    for cand in candidates or []:
        table = cand.get("table")
        if table:
            allowed.add((cand.get("schema") or "public", table))

    def relation_allowed(schema, table):
        return (schema or "public", table) in allowed

    return relation_allowed
