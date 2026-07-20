"""Agent-data requests (Help & Support hub, "Demander un agent" tab).

A signed-in user can request a new agent with capabilities over one of THEIR OWN DSS
projects: they pick a project, some SQL tables in that project (via agents/user_catalog.py,
an impersonated read), describe the business case, and submit. Each request is one
owner-stamped row in ``webapp_agent_requests_v1``. Admin response is v1 read-only: an
admin answers by editing the table directly in DSS (no in-app reply route yet, see the
v1.3 design spec) - this module only handles the WRITE (a deliberate user action) and the
owner-scoped "my requests" read.

Storage rules (backend non-negotiables, mirror storage/suggestions.py):
  - Direct SQL only, parametrized via ``sql_value`` / ``nullable_value`` (no f-strings around values).
  - ``COMMIT`` after the write; no Flow at runtime; no generic SQL route.
  - Owner-scoped on read (``user_id`` in the WHERE), like every chat reader.
  - Bounded: every user-supplied string (and the ``datasets`` list) is length-capped before
    it reaches SQL, and the write/read run under a ``statement_timeout`` (the read
    additionally READ-ONLY), so a single request can never write an unbounded row nor a
    runaway read pin a worker thread.
"""

import json
import logging
from uuid import uuid4

from owismind.storage.migrations import (
    AGENT_REQUESTS_V1_LOGICAL,
    ensure_agent_requests_table,
)
from owismind.storage.serialization import parse_json_list, rows_to_json_safe
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    readonly_pre_queries,
    sql_value,
)

logger = logging.getLogger(__name__)

# Per-field bounds (instance safety): the stored row stays small and the INSERT statement
# text (which DSS logs in full) stays bounded.
MAX_PROJECT_KEY_CHARS = 200
MAX_PROJECT_LABEL_CHARS = 300
MAX_BUSINESS_CASE_CHARS = 8_000
MAX_USE_CASES_CHARS = 4_000
MAX_IMPORTANCE_CHARS = 120

# The ``datasets`` list ({dataset, table, connection} per entry): bounded on the number
# of entries AND on each entry's own field length, so a pathological payload can never
# grow the serialized JSON column (or the INSERT statement text) unbounded.
MAX_DATASETS = 25
MAX_DATASET_FIELD_CHARS = 200
# Defence-in-depth backstop on the whole serialized JSON blob (should never be hit given
# the per-entry/count caps above, but guards against a future change to the entry shape).
MAX_DATASETS_JSON_CHARS = 20_000

# Defensive cap on how many of the caller's own requests one read returns.
DEFAULT_MY_LIMIT = 100
MAX_MY_LIMIT = 500

# Instance-safety guards (mirror storage/suggestions.py). The read runs READ-ONLY with a
# statement_timeout; the write is bounded by the same timeout so a single-row INSERT can
# never hang a worker thread.
_READ_PRE_QUERIES = readonly_pre_queries()
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"

# Columns returned by the owner-scoped "my requests" read.
_MY_COLUMNS = (
    "request_id, project_key, project_label, datasets_json, business_case, "
    "use_cases, importance, status, admin_response, responded_at, created_at"
)


def _cap(value, max_chars):
    """Trimmed, length-capped string for a nullable text column, or None when blank."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_chars]


def _cap_dataset_entry(entry):
    """One bounded ``{dataset, table, connection}`` dict, or None for a malformed entry."""
    if not isinstance(entry, dict):
        return None
    dataset = _cap(entry.get("dataset"), MAX_DATASET_FIELD_CHARS)
    if not dataset:
        return None
    return {
        "dataset": dataset,
        "table": _cap(entry.get("table"), MAX_DATASET_FIELD_CHARS),
        "connection": _cap(entry.get("connection"), MAX_DATASET_FIELD_CHARS),
    }


def _serialize_datasets(datasets):
    """Bounded, capped ``datasets`` list serialized to a JSON string (or None if empty).

    Never raises: a malformed input (wrong type, bad entries) degrades to fewer/no
    entries rather than aborting the whole request.
    """
    if not datasets:
        return None
    if not isinstance(datasets, (list, tuple)):
        return None
    capped = []
    for entry in datasets[:MAX_DATASETS]:
        item = _cap_dataset_entry(entry)
        if item is not None:
            capped.append(item)
    if not capped:
        return None
    blob = json.dumps(capped)
    return blob[:MAX_DATASETS_JSON_CHARS]


def save_agent_request(
    user_id,
    project_key,
    project_label,
    datasets,
    business_case,
    use_cases,
    importance,
):
    """Persist one agent-data request (owner-stamped) and return its id.

    Strings are trimmed + length-capped here (defense in depth, primary validation is
    security/validation.py upstream); ``datasets`` is bounded and JSON-serialized.
    ``status`` is always 'open' at write. Raises on a storage error (a request is a
    deliberate user action, so the route surfaces a clean error rather than swallowing it).
    """
    request_id = uuid4().hex
    datasets_json = _serialize_datasets(datasets)

    ensure_agent_requests_table()
    table = full_table(AGENT_REQUESTS_V1_LOGICAL)
    insert = """
    INSERT INTO {table}
      (request_id, user_id, project_key, project_label, datasets_json, business_case,
       use_cases, importance, status, created_at)
    VALUES ({request_id}, {user_id}, {project_key}, {project_label}, {datasets_json},
       {business_case}, {use_cases}, {importance}, 'open', now())
    """.format(
        table=table,
        request_id=sql_value(request_id),
        user_id=sql_value(user_id),
        project_key=nullable_value(_cap(project_key, MAX_PROJECT_KEY_CHARS)),
        project_label=nullable_value(_cap(project_label, MAX_PROJECT_LABEL_CHARS)),
        datasets_json=nullable_value(datasets_json),
        business_case=nullable_value(_cap(business_case, MAX_BUSINESS_CASE_CHARS)),
        use_cases=nullable_value(_cap(use_cases, MAX_USE_CASES_CHARS)),
        importance=nullable_value(_cap(importance, MAX_IMPORTANCE_CHARS)),
    )
    logger.info(
        "save_agent_request - INSERT into %s request_id=%s user_id=%s project_key=%s",
        table, request_id, user_id, project_key,
    )
    # The full INSERT text is not logged: it inlines the business case / datasets body.
    new_executor().query_to_df(
        "SELECT 1 AS agent_request_saved",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, insert],
        post_queries=["COMMIT"],
    )
    logger.info("save_agent_request - COMMITTED request_id=%s", request_id)
    return request_id


def list_my_agent_requests(user_id, limit=DEFAULT_MY_LIMIT):
    """Return the caller's OWN agent requests (newest first), owner-scoped + bounded.

    ``datasets_json`` is re-parsed into a plain list (a malformed/NULL cell degrades to
    an empty list, never breaking the whole read). Read-only + statement_timeout. Never
    raises: any problem degrades to an empty list.
    """
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_MY_LIMIT
    n = max(1, min(n, MAX_MY_LIMIT))
    try:
        ensure_agent_requests_table()
        table = full_table(AGENT_REQUESTS_V1_LOGICAL)
        sql = (
            "SELECT {cols} FROM {table} WHERE user_id = {user_id} "
            "ORDER BY created_at DESC LIMIT {limit}"
        ).format(cols=_MY_COLUMNS, table=table, user_id=sql_value(user_id), limit=int(n))
        df = new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES)
        rows = rows_to_json_safe(df)
        for row in rows:
            row["datasets"] = parse_json_list(row.pop("datasets_json", None))
        return rows
    except Exception:
        logger.exception("list_my_agent_requests - failed for user_id=%s", user_id)
        return []
