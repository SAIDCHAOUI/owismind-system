"""Design-time, append-only schema catalog for factory-created specialists.

The catalog deliberately contains metadata only. It never reads business rows or
samples, and its connection and physical-table references remain server-only.
"""

import datetime
import hashlib
import json
import re
import unicodedata

from . import flow_builder


CATALOG_DATASET_NAME = "OWIsMind_agent_catalog_v1"

# The dataset is SQL-backed, so complex metadata is serialized as JSON strings.
# Keep connection_name and physical_table in the stored schema only: callers that
# prepare context for a model must use searchable_catalog_rows().
CATALOG_SCHEMA = [
    {"name": "generation_id", "type": "string"},
    {"name": "capability_key", "type": "string"},
    {"name": "domain", "type": "string"},
    {"name": "dataset_name", "type": "string"},
    {"name": "column_name", "type": "string"},
    {"name": "column_type", "type": "string"},
    {"name": "description", "type": "string"},
    {"name": "synonyms", "type": "string"},
    {"name": "join_hints", "type": "string"},
    {"name": "search_text", "type": "string"},
    {"name": "connection_name", "type": "string"},
    {"name": "physical_table", "type": "string"},
]

_PUBLIC_FIELDS = (
    "generation_id", "capability_key", "domain", "dataset_name", "column_name",
    "column_type", "description", "synonyms", "join_hints", "search_text",
)


def _generation_date():
    """Return the UTC calendar date used in stable generation identifiers."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")


def _schema_columns(dataset_schema):
    if isinstance(dataset_schema, dict):
        columns = dataset_schema.get("columns") or []
    elif isinstance(dataset_schema, list):
        columns = dataset_schema
    else:
        columns = []
    return [dict(column) for column in columns if isinstance(column, dict)
            and column.get("name")]


def _text_list(value):
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _normalise_search_text(parts):
    text = " ".join(str(part or "") for part in parts)
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", text).strip().lower()


def _stable_sequence(spec, wizard_config, columns, physical_table):
    """Derive a repeatable three-digit suffix without looking at catalog rows.

    The suffix is sha256(payload) % 1000, so it always fits the NNN contract
    (000..999). Tradeoff: two DIFFERENT same-day generations of one domain can
    collide with probability ~1/1000 and would share a generation_id in the
    append-only catalog. Accepted on purpose: the id stays fully deterministic
    without reading existing catalog rows to allocate a sequence.
    """
    payload = {
        "domain": spec.domain,
        "base_dataset": spec.base_dataset,
        "columns": columns,
        "wizard": wizard_config or {},
        "physical_table": physical_table or "",
    }
    encoded = json.dumps(payload, ensure_ascii=True, sort_keys=True,
                         separators=(",", ":"), default=str).encode("utf-8")
    return int(hashlib.sha256(encoded).hexdigest()[:8], 16) % 1000


def _attributes_by_column(wizard_config):
    attributes = {}
    for attribute in (wizard_config or {}).get("attributes") or []:
        if not isinstance(attribute, dict):
            continue
        column = attribute.get("column") or attribute.get("name")
        if column:
            attributes[str(column)] = attribute
    return attributes


def _join_hints_by_column(wizard_config):
    hints = {}
    for hint in (wizard_config or {}).get("join_hints") or []:
        if not isinstance(hint, dict):
            continue
        column = hint.get("column")
        if column:
            hints.setdefault(str(column), []).append({
                "hint": str(hint.get("hint") or hint.get("description") or "").strip(),
                "target_dataset": str(hint.get("target_dataset") or "").strip(),
                "target_column": str(hint.get("target_column") or "").strip(),
            })
    return hints


def ensure_catalog_dataset(ctx, connection, zone=None):
    """Ensure the shared catalog dataset exists on ``connection``.

    Creation is idempotent and routed through FactoryContext.act, so dry-runs
    never create a dataset or write its schema.
    """
    try:
        if flow_builder.dataset_exists(ctx.project, CATALOG_DATASET_NAME):
            dataset = ctx.project.get_dataset(CATALOG_DATASET_NAME)
            ctx.skip("catalog_dataset", "dataset %s already exists" % CATALOG_DATASET_NAME)
            return dataset
    except flow_builder.ExistenceCheckError as exc:
        if not ctx.dry_run:
            ctx.fail("catalog_dataset", "existence check failed, NOT creating: %s" % exc)
            return None

    def _create():
        # Lazy import: only the DSS runtime has dataiku (never the test env).
        import dataiku

        builder = ctx.project.new_managed_dataset(CATALOG_DATASET_NAME)
        builder.with_store_into(connection)
        dataset = builder.create()
        # The dataikuapi handle owns creation/settings only; schema and data
        # writes go through the in-process dataiku.Dataset API (a dataikuapi
        # DSSDataset has no write_schema). ignore_flow: this runs outside a
        # recipe (notebook or webapp backend).
        dataiku.Dataset(CATALOG_DATASET_NAME, ignore_flow=True).write_schema(CATALOG_SCHEMA)
        return dataset

    dataset = ctx.act("catalog_dataset",
                      "create managed dataset %s on connection %s"
                      % (CATALOG_DATASET_NAME, connection), _create)
    if dataset is not None and zone is not None:
        flow_builder.move_into_zone(ctx, zone, dataset,
                                    "dataset %s" % CATALOG_DATASET_NAME)
    return dataset


def build_catalog_generation(spec, wizard_config, dataset_schema, physical_table):
    """Build metadata-only rows for one deterministic catalog generation.

    Only schema names and types plus explicit wizard descriptions, synonyms and
    join hints are used. Unknown wizard keys, including samples and values, are
    intentionally ignored.
    """
    wizard_config = dict(wizard_config or {})
    columns = _schema_columns(dataset_schema)
    sequence = _stable_sequence(spec, wizard_config, columns, physical_table)
    generation_id = "%s-%s-%03d" % (spec.domain, _generation_date(), sequence)
    attributes = _attributes_by_column(wizard_config)
    hints = _join_hints_by_column(wizard_config)
    connection_name = str(wizard_config.get("connection_key")
                          or wizard_config.get("connection_name") or "")
    dataset_description = str(wizard_config.get("entity_description") or "").strip()
    rows = []
    for column in columns:
        column_name = str(column["name"])
        attribute = attributes.get(column_name, {})
        description = str(attribute.get("description") or dataset_description or
                          "%s column in %s" % (column_name, spec.label_en)).strip()
        synonyms = _text_list(attribute.get("synonyms"))
        join_hints = hints.get(column_name, [])
        rows.append({
            "generation_id": generation_id,
            "capability_key": spec.capability_key,
            "domain": spec.domain,
            "dataset_name": spec.base_dataset,
            "column_name": column_name,
            "column_type": str(column.get("type") or "string"),
            "description": description,
            "synonyms": synonyms,
            "join_hints": join_hints,
            "search_text": _normalise_search_text([
                spec.domain, spec.label_fr, spec.label_en, spec.base_dataset,
                column_name, column.get("type"), description,
            ] + synonyms + [hint.get("hint") for hint in join_hints]),
            "connection_name": connection_name,
            "physical_table": str(physical_table or ""),
        })
    return {"generation_id": generation_id, "rows": rows}


def _storage_row(row, capability_key):
    stored = dict(row)
    stored["capability_key"] = capability_key
    stored["synonyms"] = json.dumps(_text_list(stored.get("synonyms")), ensure_ascii=False)
    stored["join_hints"] = json.dumps(stored.get("join_hints") or [], ensure_ascii=False,
                                        sort_keys=True)
    return {field["name"]: stored.get(field["name"], "") for field in CATALOG_SCHEMA}


def publish_catalog_generation(ctx, capability_key, generation):
    """Append one generation to the catalog without any delete or overwrite path."""
    rows = list((generation or {}).get("rows") or [])
    if not rows:
        ctx.skip("catalog_publish", "generation has no schema rows to publish")
        return None

    def _append():
        # Lazy imports (lesson L089): the DSS-free test env may lack pandas at
        # import time and substitutes a fake dataiku module via sys.modules.
        import dataiku
        import pandas as pd

        # Proven append pattern (plugin chat_traces.save_trace): a fresh writer
        # session on a dataiku.Dataset OVERWRITES the table, so appendMode MUST
        # be set on the spec BEFORE write_with_schema. Columns follow the exact
        # CATALOG_SCHEMA order so the positional SQL write always lines up.
        frame = pd.DataFrame(
            [_storage_row(row, capability_key) for row in rows],
            columns=[field["name"] for field in CATALOG_SCHEMA])
        dataset = dataiku.Dataset(CATALOG_DATASET_NAME, ignore_flow=True)
        dataset.spec_item["appendMode"] = True
        dataset.write_with_schema(frame)
        return generation.get("generation_id")

    return ctx.act("catalog_publish",
                   "append generation %s for capability %s to %s (%d schema rows)"
                   % (generation.get("generation_id") or "?", capability_key,
                      CATALOG_DATASET_NAME, len(rows)), _append)


def searchable_catalog_rows(generation):
    """Return model-safe rows, excluding every server-only physical reference."""
    out = []
    for row in (generation or {}).get("rows") or []:
        if not isinstance(row, dict):
            continue
        # search_text is already normalized at build time, it passes through.
        public = {key: row.get(key) for key in _PUBLIC_FIELDS}
        out.append(public)
    return out
