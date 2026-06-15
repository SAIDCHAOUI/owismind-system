"""Per-exchange webapp ARTIFACT specs (chart / table the orchestrator rendered).

The orchestrator agent can ask the web app to display the latest data result as a
chart or a full table (tools ``show_chart`` / ``show_table``). Only the small SPEC
is stored here — kind, title, and the chart axes — never the rows: the chart/table
DATA is the already-captured ``generated_sql`` result, reused by the frontend via
``/evidence/meta``. So an artifact costs a few hundred bytes per exchange.

Storage rules (backend non-negotiables):
  - Direct SQL only, parametrized via ``sql_value`` (no f-strings around values).
  - ``COMMIT`` after the write; no Flow at runtime; no generic SQL route.
  - Owner-scoped on read (``user_id`` in the WHERE), like every chat reader.
  - Best-effort everywhere: a storage failure must never affect the answer.
"""

import json
import logging

from owismind.storage.migrations import ARTIFACTS_V1_LOGICAL, ensure_artifacts_table
from owismind.storage.sql_config import full_table, new_executor, sql_value

logger = logging.getLogger(__name__)

# Bounds (instance safety): a turn produces at most a handful of artifacts, and the
# spec is tiny. These cap a pathological/buggy agent so a single exchange can never
# write an unbounded row.
MAX_ARTIFACTS = 8
MAX_ARTIFACTS_JSON_CHARS = 16_000
MAX_Y_SERIES = 8
_CHART_TYPES = ("line", "bar", "pie")
_ARTIFACT_KINDS = ("chart", "table", "kpi")

# Instance-safety guards (mirror the Evidence reads). The read runs in a
# transaction-scoped READ-ONLY transaction with a statement_timeout, so the
# SELECT can never write and a runaway read is killed. The write cannot be
# read-only (it persists), but the same statement_timeout bounds the tiny
# single-row UPSERT so it can never hang a worker thread.
_READ_PRE_QUERIES = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"


def _sanitize(artifacts):
    """Project an artifacts list onto the strict stored/served shape.

    Applied on BOTH write and read (defense in depth): drops anything unrecognized,
    bounds strings, and keeps at most ``MAX_ARTIFACTS`` well-formed specs. A chart
    keeps {type, x, y[]}; a table keeps no chart block; a KPI keeps {value[,delta,
    delta_pct]}. Pure, never raises."""
    out = []
    for a in artifacts or []:
        if not isinstance(a, dict):
            continue
        kind = a.get("kind")
        if kind not in _ARTIFACT_KINDS:
            continue
        spec = {"kind": kind, "title": str(a.get("title") or "")[:200]}
        if kind == "chart":
            chart = a.get("chart")
            if not isinstance(chart, dict):
                continue
            ctype = chart.get("type")
            x = chart.get("x")
            y = chart.get("y")
            if ctype not in _CHART_TYPES or not isinstance(x, str):
                continue
            if isinstance(y, str):
                y = [y]
            if not isinstance(y, list):
                continue
            y = [str(c)[:128] for c in y if isinstance(c, str) and c][:MAX_Y_SERIES]
            if not y:
                continue
            chart_spec = {"type": ctype, "x": x[:128], "y": y}
            style = chart.get("style")
            if isinstance(style, str) and style.strip():
                chart_spec["style"] = style.strip()[:24]
            spec["chart"] = chart_spec
        elif kind == "kpi":
            kpi = a.get("kpi")
            if not isinstance(kpi, dict) or not isinstance(kpi.get("value"), str):
                continue
            kpi_spec = {"label": str(kpi.get("label") or "")[:120],
                        "value": kpi["value"][:128]}
            for key in ("delta", "delta_pct"):
                v = kpi.get(key)
                if isinstance(v, str) and v:
                    kpi_spec[key] = v[:128]
            spec["chart"] = None
            spec["kpi"] = kpi_spec
        else:
            spec["chart"] = None
        out.append(spec)
        if len(out) >= MAX_ARTIFACTS:
            break
    return out


def save_artifacts(exchange_id, user_id, artifacts):
    """UPSERT the artifact specs for one exchange. Best-effort, owner-stamped.

    No-op when nothing well-formed is provided. The whole write is self-contained
    best-effort: a failure is logged on one line and swallowed so it can never
    affect the answer already on screen."""
    specs = _sanitize(artifacts)
    if not specs:
        return
    payload = json.dumps(specs, ensure_ascii=False)
    if len(payload) > MAX_ARTIFACTS_JSON_CHARS:
        logger.warning("save_artifacts — payload too large (%d) for exchange_id=%s; skipping",
                       len(payload), exchange_id)
        return
    try:
        ensure_artifacts_table()
        table = full_table(ARTIFACTS_V1_LOGICAL)
        upsert = """
        INSERT INTO {table} (exchange_id, user_id, artifacts, created_at)
        VALUES ({exchange_id}, {user_id}, {artifacts}, now())
        ON CONFLICT (exchange_id) DO UPDATE SET
            artifacts = EXCLUDED.artifacts,
            user_id   = EXCLUDED.user_id
        """.format(
            table=table,
            exchange_id=sql_value(exchange_id),
            user_id=sql_value(user_id),
            artifacts=sql_value(payload),
        )
        new_executor().query_to_df(
            "SELECT 1 AS artifacts_saved",
            pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, upsert],
            post_queries=["COMMIT"],
        )
        logger.info("save_artifacts — stored %d artifact(s) exchange_id=%s", len(specs), exchange_id)
    except Exception:
        logger.exception("save_artifacts — could not store artifacts exchange_id=%s", exchange_id)


def read_artifacts(user_id, exchange_id):
    """Return the stored artifact specs for an exchange the caller OWNS, else [].

    Owner-scoped (user_id in the WHERE), read-only. Never raises: any problem
    (table absent, bad JSON, executor error) degrades to an empty list."""
    try:
        ensure_artifacts_table()
        table = full_table(ARTIFACTS_V1_LOGICAL)
        sql = (
            "SELECT artifacts FROM {table} "
            "WHERE exchange_id = {exchange_id} AND user_id = {user_id}"
        ).format(table=table, exchange_id=sql_value(exchange_id), user_id=sql_value(user_id))
        # Read-only + statement_timeout (defense in depth): the SELECT cannot
        # write and a runaway read is killed. The lookup is a PRIMARY-KEY hit on
        # exchange_id -> O(1) index access, never a full scan. user_id is the
        # owner-scope check on that single row.
        df = new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES)
        if df is None or len(df) == 0:
            return []
        raw = df.iloc[0]["artifacts"]
        if not raw:
            return []
        data = json.loads(raw)
        return _sanitize(data) if isinstance(data, list) else []
    except Exception:
        logger.exception("read_artifacts — failed for exchange_id=%s", exchange_id)
        return []
