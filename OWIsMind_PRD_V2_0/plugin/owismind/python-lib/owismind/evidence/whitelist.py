"""Dataset matching for Evidence Studio (pure part - NO dataiku import).

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
    (its resolved physical schema/table), never from the parsed (schema, table) -
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


def foreign_project_tables(tables, candidates, project_key):
    """Agent tables that look like a CLONE RESIDUE: ``<OTHER_KEY>_<dataset>``
    where this project owns a candidate ``<project_key>_<dataset>`` for the same
    dataset suffix (case-insensitive). Diagnostic ONLY: the caller must not remap
    the query onto the local candidate (the agent read another project's data).

    ``tables``: parsed refs ``[{"table": ..., "schema": ...}]``; returns
    ``[{"table": agent_table, "foreign_key": key, "dataset": candidate_name}]``,
    empty when ``project_key`` is blank or nothing qualifies.
    """
    key = (project_key or "").lower()
    if not key:
        return []
    local = {}
    for cand in candidates or []:
        ct = (cand.get("table") or "").lower()
        if ct.startswith(key + "_") and len(ct) > len(key) + 1:
            local.setdefault(ct[len(key) + 1:], cand.get("name"))
    if not local:
        return []
    out = []
    for ref in tables or []:
        table = (ref or {}).get("table") or ""
        probe = table.lower()
        # Project keys contain underscores ("OWISMIND_PRD_V2_0"), so walk every
        # underscore boundary and keep the first suffix this project owns.
        hit = None
        idx = probe.find("_")
        while idx != -1:
            suffix = probe[idx + 1:]
            if suffix in local:
                hit = (probe[:idx], suffix)
                break
            idx = probe.find("_", idx + 1)
        if hit is None or hit[0] == key:
            continue
        out.append({"table": table, "foreign_key": hit[0], "dataset": local[hit[1]]})
    return out
