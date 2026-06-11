"""Dynamic choices for the webapp params: 'sql_connection' and 'traces_dataset'.

DSS calls do() to populate the dropdowns shown in the webapp Settings, routing each
parameter via payload['parameterName']. 'sql_connection' is built from
client.list_connections() (PostgreSQL only); 'traces_dataset' from the project's
datasets (SQL-backed, plus an explicit '(none)' entry). Nothing is hardcoded.
(Evidence Studio needs no param — it auto-discovers the project's SQL datasets at
runtime.)

list_connections() can be admin-restricted (see DSS docs: connection operations
require the "admin rights" flag) or unavailable in this param-setup context. When
that happens we surface a CLEARLY LABELLED fallback (and log the cause) instead of
a silent one, so it is obvious in the UI that the dynamic list was unavailable —
rather than pretending SQL_owi is the only real connection.

This module is strictly READ-ONLY: it only LISTS connections and datasets, never
creates, modifies or deletes anything, and runs only while the Settings form is
rendered.
"""

import logging

import dataiku

logger = logging.getLogger(__name__)

# The backend talks PostgreSQL only (Dialects.POSTGRES). Offering any other type
# here would let an admin pick a connection that then fails at runtime, so only
# PostgreSQL connections are selectable.
_SQL_TYPES = {"PostgreSQL"}

# Last-resort fallback so the webapp can still be bootstrapped when listing is
# unavailable. Always labelled explicitly so it is never mistaken for a full list.
_FALLBACK_CONNECTION = "SQL_owi"


def _iter_connections(conns):
    """Yield ``(name, type)`` for each connection, tolerant of the API shape.

    ``list_connections()`` returns a dict ``{name: {..., 'type': ...}}``; edge
    shapes may return a list of dicts or objects. All are normalised here.
    """
    items = conns.items() if isinstance(conns, dict) else enumerate(conns or [])
    for key, info in items:
        if isinstance(info, dict):
            name = info.get("name") or (key if isinstance(key, str) else None)
            ctype = info.get("type")
        else:
            name = getattr(info, "name", None)
            ctype = getattr(info, "type", None)
        if name:
            yield name, ctype


def _fallback(reason):
    """A single, explicitly-labelled fallback choice (never a silent SQL_owi)."""
    return {
        "choices": [
            {
                "value": _FALLBACK_CONNECTION,
                "label": "{} (fallback — {})".format(_FALLBACK_CONNECTION, reason),
            }
        ]
    }


# --- Trace dataset choices ---------------------------------------------------
# Only SQL-table-backed datasets are offered for the trace sink (a CSV/filesystem
# dataset could hit a per-row length limit on a large JSON trace), PLUS an explicit
# "(none)" entry so an admin can turn trace storage back OFF after selecting one.
_MAX_DATASETS = 1000
_NONE_CHOICE = {"value": "", "label": "(none — disable trace storage)"}


def _iter_datasets(items):
    """Yield ``(name, type)`` for each project dataset, tolerant of the API shape."""
    for item in (items or [])[:_MAX_DATASETS]:
        if isinstance(item, dict):
            name = item.get("name")
            dtype = item.get("type")
        else:
            name = getattr(item, "name", None)
            dtype = getattr(item, "type", None)
        if name:
            yield name, dtype


def _trace_dataset_choices():
    """'(none)' + the project's SQL-backed datasets, for the traces_dataset SELECT."""
    try:
        client = dataiku.api_client()
        project_key = dataiku.default_project_key()
        items = client.get_project(project_key).list_datasets()
    except Exception as exc:
        logger.exception("param setup — list_datasets() failed")
        # Still let the admin DISABLE trace storage even when listing is unavailable.
        return {
            "choices": [
                dict(
                    _NONE_CHOICE,
                    label="(none — disable; dataset listing failed: {})".format(
                        type(exc).__name__
                    ),
                )
            ]
        }

    pairs = list(_iter_datasets(items))
    logger.info("param setup — list_datasets saw %d dataset(s)", len(pairs))
    logger.debug(
        "param setup — dataset names/types: %s",
        sorted("{}:{}".format(n, t) for n, t in pairs),
    )

    def _choice(name, dtype):
        return {"value": name, "label": "{} ({})".format(name, dtype) if dtype else name}

    sql_choices = sorted(
        (_choice(n, t) for n, t in pairs if t in _SQL_TYPES),
        key=lambda c: c["value"].lower(),
    )
    if sql_choices:
        return {"choices": [_NONE_CHOICE] + sql_choices}

    # No dataset matched the SQL-type filter. Dataset type names can vary by DSS
    # version/connector, so rather than hide the admin's dataset, fall back to listing
    # ALL datasets (the trace write is self-protected and the description states the
    # required SQL-table schema). "(none)" still comes first.
    all_choices = sorted(
        (_choice(n, t) for n, t in pairs), key=lambda c: c["value"].lower()
    )
    return {"choices": [_NONE_CHOICE] + all_choices}


# --- DSS entry point ---------------------------------------------------------
def do(payload, config, plugin_config, inputs):
    """Return ``{'choices': [...]}`` for the SELECT param named in ``payload``.

    ``traces_dataset`` is a single-select dataset dropdown over the project's
    SQL-backed datasets (plus a '(none)' entry); everything else routes to the
    SQL-connection dropdown. (Evidence Studio needs no param: it auto-discovers
    the project's SQL datasets at runtime.)
    """
    name = (payload or {}).get("parameterName")
    if name == "traces_dataset":
        return _trace_dataset_choices()
    return _connection_choices()


def _connection_choices():
    """Return ``{'choices': [...]}`` for the sql_connection dropdown."""
    try:
        conns = dataiku.api_client().list_connections()
    except Exception as exc:
        # Do NOT swallow silently: log it, and put the error type in the label so
        # the cause is visible in the Settings dropdown without digging through logs.
        logger.exception("param setup — list_connections() failed")
        return _fallback("listing failed: {}".format(type(exc).__name__))

    pairs = list(_iter_connections(conns))
    # Log only the COUNT at INFO (a harmless diagnostic for a short dropdown). The
    # connection names/types are enumerated at DEBUG only, to avoid routinely
    # exposing the instance's connection inventory in INFO-level plugin logs.
    logger.info("param setup — list_connections saw %d connection(s)", len(pairs))
    logger.debug(
        "param setup — connection names/types: %s",
        sorted("{}:{}".format(n, t) for n, t in pairs),
    )

    choices = [
        {"value": name, "label": "{} ({})".format(name, ctype) if ctype else name}
        for name, ctype in pairs
        if ctype in _SQL_TYPES
    ]
    if choices:
        return {"choices": sorted(choices, key=lambda c: c["value"].lower())}

    # Listing worked but exposed no PostgreSQL connection in this context.
    logger.warning(
        "param setup — no PostgreSQL connection visible (saw %d total); using fallback",
        len(pairs),
    )
    return _fallback(
        "no PostgreSQL connection listed here (saw {} total)".format(len(pairs))
    )
