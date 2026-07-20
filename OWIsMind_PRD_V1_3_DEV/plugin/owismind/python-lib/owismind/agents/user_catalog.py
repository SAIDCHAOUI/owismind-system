"""User-scoped DSS catalog discovery (Help & Support hub, "Demander un agent" tab).

The agent-request form lets a user pick one of THEIR OWN DSS projects, then some SQL
tables in it - never the admin's whitelist, never a scan of every project on the
instance. This is done via DSS *impersonation*: the caller's identity is resolved from
the browser auth headers (the documented Dataiku mechanism, spike-validated), and the
listing calls run AS that user, so the result is exactly what they themselves can see.

Instance safety - STRICTLY READ-ONLY (only listing calls), ONE impersonated listing
call per function call, on demand (only while the request form is open), and every
result is bounded (``MAX_PROJECTS`` / ``MAX_DATASETS``). Requires the DSS group the
webapp runs as to hold the "Impersonation in webapps" permission (an admin/deployment
concern, not code); its absence - or any other failure - degrades to ``{"ok": False}``
so the frontend falls back to manual entry. NEVER raises: every public function here
is called directly from a route and must not turn a listing hiccup into a 500.
"""

import logging

import dataiku

logger = logging.getLogger(__name__)

# Defensive upper bounds: a listing can never return an unbounded payload, however many
# projects/datasets the impersonated user happens to see.
MAX_PROJECTS = 300
MAX_DATASETS = 500

# Field-length bound applied to every string surfaced from a DSS listing (project key/
# label, dataset/table/connection/type names) - defense in depth, these are DSS object
# names, not free text, but a compromised/unexpected listing must never blow up a row.
_MAX_FIELD_CHARS = 200

# DSS SQL connector types considered eligible for an agent-data request. Case-insensitive
# match against the dataset's listed ``type``. Kept as a broad whitelist (rather than the
# single-connector set used by evidence/service.py) because a user's own project may sit
# on any SQL connector the instance offers, not just the one backing chat storage.
_SQL_DATASET_TYPES = frozenset(
    t.lower() for t in (
        "PostgreSQL", "MySQL", "Snowflake", "Redshift", "BigQuery", "Oracle",
        "SQLServer", "MSSQL", "Greenplum", "Teradata", "Vertica", "Synapse",
        "Databricks", "Athena",
    )
)


def _client_as_user(headers):
    """A DSS API client acting AS the calling browser user (impersonation).

    Documented Dataiku mechanism: resolve the caller's login from the authenticated
    browser headers, then ask that user's object for a client impersonating them. A
    fresh ``api_client()`` per call, same rationale as security/identity.py (thread-safe
    across Flask workers). May raise (missing authIdentifier, no impersonation
    permission, ...); every caller below catches broadly and degrades to ``ok: False``.
    """
    client = dataiku.api_client()
    auth_info = client.get_auth_info_from_browser_headers(dict(headers))
    login = auth_info["authIdentifier"]
    return client.get_user(login).get_client_as()


def _cap(value):
    """A bounded string for a DSS object name/label, or None for a blank/missing value."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:_MAX_FIELD_CHARS]


def _projects_with_labels(client):
    """``[{key, label}]`` from ONE bulk listing call, bounded + sorted by label.

    Tries ``list_projects()`` first (one call, carries the display label alongside the
    key). If that listing is unavailable under impersonation, falls back to
    ``list_project_keys()`` (also one call; label degrades to the key itself) - still a
    single impersonated call either way, per the instance-safety contract.
    """
    try:
        raw = client.list_projects() or []
    except Exception:
        logger.warning(
            "user_catalog - list_projects() unavailable, falling back to list_project_keys()"
        )
        keys = client.list_project_keys() or []
        out = [{"key": k, "label": k} for k in sorted(_cap(k) for k in keys if _cap(k))]
        return out[:MAX_PROJECTS]

    out = []
    for item in raw:
        if isinstance(item, dict):
            key = item.get("projectKey")
            label = item.get("name") or key
        else:
            key = getattr(item, "projectKey", None)
            label = getattr(item, "name", None) or key
        key = _cap(key)
        if not key:
            continue
        out.append({"key": key, "label": _cap(label) or key})
    out.sort(key=lambda p: p["label"].lower())
    return out[:MAX_PROJECTS]


def list_user_projects(headers):
    """``{"ok": True, "projects": [{"key", "label"}, ...]}`` for the calling user.

    ``projects`` are exactly the ones the impersonated user can see (their own DSS
    permissions), bounded by ``MAX_PROJECTS``. On any failure - missing impersonation
    permission, auth lookup failure, listing error - returns ``{"ok": False, "reason":
    <code>}`` so the frontend falls back to manual entry. Never raises.
    """
    try:
        client = _client_as_user(headers)
    except Exception as exc:
        logger.warning("list_user_projects - impersonation unavailable: %s", type(exc).__name__)
        return {"ok": False, "reason": "impersonation_unavailable"}
    try:
        projects = _projects_with_labels(client)
    except Exception:
        logger.exception("list_user_projects - listing failed")
        return {"ok": False, "reason": "listing_failed"}
    logger.info("list_user_projects - %d project(s) visible", len(projects))
    return {"ok": True, "projects": projects}


def list_user_sql_datasets(headers, project_key):
    """``{"ok": True, "datasets": [{"dataset","table","connection","type"}, ...]}``.

    Lists the SQL-backed datasets of ``project_key`` as seen by the impersonated caller
    (their own project access), keeping only datasets on a whitelisted SQL connector
    type and/or carrying a SQL connection + table in their params. Bounded by
    ``MAX_DATASETS``. On any failure - missing permission, unknown/inaccessible
    project, listing error - returns ``{"ok": False, "reason": <code>}``. Never raises.
    """
    key = _cap(project_key)
    if not key:
        return {"ok": False, "reason": "invalid_project_key"}
    try:
        client = _client_as_user(headers)
    except Exception as exc:
        logger.warning("list_user_sql_datasets - impersonation unavailable: %s", type(exc).__name__)
        return {"ok": False, "reason": "impersonation_unavailable"}
    try:
        items = client.get_project(key).list_datasets() or []
    except Exception:
        logger.exception("list_user_sql_datasets - list_datasets failed for project=%s", key)
        return {"ok": False, "reason": "listing_failed"}

    datasets = []
    for item in items:
        d = item if isinstance(item, dict) else {}
        name = d.get("name")
        dtype = d.get("type")
        params = d.get("params") or {}
        connection = params.get("connection")
        table = params.get("table")
        if not name:
            continue
        is_sql_type = isinstance(dtype, str) and dtype.strip().lower() in _SQL_DATASET_TYPES
        has_sql_shape = bool(connection) and bool(table)
        if not (is_sql_type or has_sql_shape):
            continue
        datasets.append({
            "dataset": _cap(name),
            "table": _cap(table),
            "connection": _cap(connection),
            "type": _cap(dtype),
        })
        if len(datasets) >= MAX_DATASETS:
            logger.warning(
                "list_user_sql_datasets - project=%s hit MAX_DATASETS=%d; list truncated",
                key, MAX_DATASETS,
            )
            break
    logger.info(
        "list_user_sql_datasets - project=%s found %d SQL dataset(s)", key, len(datasets)
    )
    return {"ok": True, "datasets": datasets}
