"""Dataset matching for Evidence Studio (pure part — NO dataiku import).

The service auto-discovers the webapp project's SQL datasets and resolves each to
its physical (schema, table); this module matches the table parsed from the
agent's SQL against those candidates (no admin whitelist to configure).
Comparison is case-insensitive (unquoted PostgreSQL identifiers fold), and a
missing schema on EITHER side is a wildcard (agent SQL often writes the bare
table name).
"""


def match_whitelist(table, schema, candidates):
    """First candidate matching ``(schema, table)``, or None.

    ``candidates``: [{"name": dataset_name, "table": physical, "schema": s|None}].

    Callers must build the executed table reference from the RETURNED candidate
    (its resolved physical schema/table), never from the parsed (schema, table) —
    the schema-wildcard match is only safe under that rule.
    """
    if not table:
        return None
    t = table.lower()
    s = schema.lower() if schema else None
    for cand in candidates or []:
        ct = (cand.get("table") or "").lower()
        if not ct or ct != t:
            continue
        cs = (cand.get("schema") or "").lower() or None
        if s is None or cs is None or s == cs:
            return cand
    return None
