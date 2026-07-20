"""Semantic model creation and configuration through the official API.

The strategy is the one this project already VALIDATED in production
(build_aligned_semantic_model.py, 2026-06): never hand-craft a full raw config
from nothing. Instead:

1. ``create_semantic_model(name)`` + ``new_version("v1")`` so the SERVER
   initializes a structurally valid empty version,
2. merge our content into that raw dict (one entity built from the base
   dataset's schema, indexing settings + embedding LLM copied from the living
   template model),
3. ``save()`` + ``set_active_version_id`` + one explicit indexing pass.

The wizard config (see wizard.py) is applied on top with apply_config():
descriptions, resolvable flags, metrics, filters, glossary, golden queries and
the SQL generation instructions.

Raw shapes were extracted from the committed v1.json dumps of the two live
models: attributes carry {name, description, dssType, type: "COLUMN", column,
distinctValuesHandlingMode: "AUTO_INDEX"|"NONE", manualValues, indexDistinctValues,
resolveInUserRequests, sqlGenerationConfig}; metrics {name, description,
pseudoSQLExpression, llmInstructions, created}; filters {name, description,
pseudoSQLExpression, created}; goldenQueries {name, question, generatedSql};
glossaryTerms {id, term, source, synonyms, ...}.
"""

import copy
import uuid


# ------------------------------------------------------------------- structure

def build_attribute(column_name, dss_type, description="", resolvable=False):
    return {
        "name": column_name,
        "description": description or "",
        "dssType": dss_type or "string",
        "type": "COLUMN",
        "column": column_name,
        "distinctValuesHandlingMode": "AUTO_INDEX" if resolvable else "NONE",
        "manualValues": [],
        "indexDistinctValues": bool(resolvable),
        "resolveInUserRequests": bool(resolvable),
        "sqlGenerationConfig": {},
    }


def build_entity(project, spec, entity_name=None, description=""):
    """One entity mapped to the base dataset, attributes from the live schema."""
    dataset = project.get_dataset(spec.base_dataset)
    schema = dataset.get_schema() or {}
    columns = schema.get("columns") or []
    attributes = [build_attribute(c.get("name"), c.get("type")) for c in columns if c.get("name")]
    return {
        "name": entity_name or ("%s_record" % spec.domain),
        "description": description or "",
        "tags": [],
        "type": "DATASET",
        "datasetRef": "%s.%s" % (project.project_key, spec.base_dataset),
        "attributes": attributes,
        "metrics": [],
        "filters": [],
        "primaryKey": {"attributes": []},
        "foreignKeys": [],
    }


def read_model_raw(project, model_id, version_id=None):
    model = project.get_semantic_model(model_id)
    if version_id is None:
        version_id = model.get_active_version_id()
    version = model.get_version(version_id)
    return version.get_settings().get_raw()


# ---------------------------------------------------------------------- seeding

def find_model_by_name(project, name):
    try:
        for item in project.list_semantic_models():
            item_name = item.name if hasattr(item, "name") else item.get("name")
            if item_name == name:
                return item.to_semantic_model() if hasattr(item, "to_semantic_model") else None
    except Exception:
        pass
    return None


def seed_model(ctx, spec, settings, entity_description=""):
    """Create the semantic model shell with one schema-derived entity.

    Returns the model id (or None in dry-run / on failure). Indexing settings
    and the embedding LLM are copied from the template model so the new model
    indexes exactly like the validated ones.
    """
    existing = find_model_by_name(ctx.project, spec.semantic_model_name)
    if existing is not None:
        ctx.skip("semantic_model", "model %s already exists (id %s)"
                 % (spec.semantic_model_name, getattr(existing, "id", "?")))
        return getattr(existing, "id", None)

    template_id = (settings or {}).get("template_semantic_model_id") or ""

    def _seed():
        model = ctx.project.create_semantic_model(spec.semantic_model_name)
        version_settings = model.new_version("v1")
        raw = version_settings.get_raw()

        raw["entities"] = [build_entity(ctx.project, spec, description=entity_description)]
        raw.setdefault("relationships", [])
        raw.setdefault("goldenQueries", [])
        raw.setdefault("glossaryTerms", [])
        raw.setdefault("glossaryBindings", [])
        raw.setdefault("sqlGenerationConfig", {})
        raw["sqlGenerationConfig"].setdefault("instructions", "")
        raw["sqlGenerationConfig"].setdefault("vocabularyTermIds", [])

        # Ownership marker (next to the embeddingLlmId): apply_config refuses to
        # mutate a pre-existing model that does not carry it, so a name collision
        # with a foreign model can never be silently overwritten.
        raw.setdefault("privateEditorData", {})["owismindFactory"] = {"domain": spec.domain}

        # Copy the proven indexing setup from the template model (read-only).
        if template_id:
            try:
                template_raw = read_model_raw(ctx.project, template_id)
                if template_raw.get("indexingSettings"):
                    raw["indexingSettings"] = copy.deepcopy(template_raw["indexingSettings"])
                embedding = (template_raw.get("privateEditorData") or {}).get("embeddingLlmId")
                if embedding:
                    raw.setdefault("privateEditorData", {})
                    raw["privateEditorData"]["embeddingLlmId"] = embedding
            except Exception:
                # The template is an optimization, not a requirement: the server
                # defaults remain valid without it.
                pass

        version_settings.save()
        model.set_active_version_id("v1")
        return model.id if hasattr(model, "id") else model.semantic_model_id

    return ctx.act("semantic_model",
                   "create semantic model %s (1 entity from %s schema, indexing copied "
                   "from template %s)" % (spec.semantic_model_name, spec.base_dataset,
                                          template_id or "none"),
                   _seed)


# ----------------------------------------------------------------- apply config

def _wizard_metric(m):
    return {
        "name": m.get("name") or "",
        "description": m.get("description") or "",
        "pseudoSQLExpression": m.get("pseudo_sql") or m.get("pseudoSQLExpression") or "",
        "llmInstructions": m.get("llm_instructions") or m.get("llmInstructions") or "",
        "created": {},
    }


def _wizard_filter(f):
    return {
        "name": f.get("name") or "",
        "description": f.get("description") or "",
        "pseudoSQLExpression": f.get("pseudo_sql") or f.get("pseudoSQLExpression") or "",
        "created": {},
    }


def _wizard_glossary_term(t):
    return {
        "id": str(uuid.uuid4()),
        "term": t.get("term") or "",
        "source": "MANUAL",
        "userModified": True,
        "created": {},
        "synonyms": list(t.get("synonyms") or []),
        "privateEditorData": {},
    }


def _next_backup_version_id(model):
    """First free pre-apply-backup-<n> version id (bounded like hub backups)."""
    existing = set()
    try:
        for item in model.list_versions() or []:
            vid = item.get("versionId") if isinstance(item, dict) else \
                getattr(item, "version_id", None) or getattr(item, "id", None)
            if vid:
                existing.add(vid)
    except Exception:
        # Unknown version listing API: fall back to index 1; a collision makes
        # new_version raise and the caller degrades to MANUAL (no mutation).
        pass
    index = 1
    while ("pre-apply-backup-%d" % index) in existing:
        index += 1
        if index > 200:  # bounded: never loop forever on a weird version tree
            break
    return "pre-apply-backup-%d" % index


def apply_config(ctx, model_id, config, created_this_run=False, version_id=None):
    """Merge a wizard config (see wizard.DRAFT_SCHEMA) into the live model.

    In-place update of the active version, exactly like the validated
    update_*_semantic_model.py scripts: no re-create, no re-index here
    (indexing is its own explicit step).

    :param bool created_this_run: True when THIS run just seeded the model (it is
        empty, nothing to protect). Otherwise the model pre-exists: it is only
        mutated when it carries the factory ownership marker, and only after a
        version backup of the active raw succeeded.
    """
    if not model_id:
        ctx.manual("semantic_config",
                   "no semantic model id available: apply the wizard config by hand "
                   "(update_*_semantic_model.py pattern) once the model exists")
        return None

    # Anti-overwrite guard. Dry-run keeps planning as before without reading DSS
    # (ctx.act below records the plan and executes nothing).
    if not ctx.dry_run and not created_this_run:
        try:
            model = ctx.project.get_semantic_model(model_id)
            guard_vid = version_id or model.get_active_version_id()
            active_raw = model.get_version(guard_vid).get_settings().get_raw()
        except Exception as exc:
            ctx.manual("semantic_config",
                       "cannot read model %s to verify factory ownership (%s): "
                       "refusing to modify it, apply the wizard config by hand"
                       % (model_id, exc))
            return None
        marker = (active_raw.get("privateEditorData") or {}).get("owismindFactory")
        if not marker:
            ctx.manual("semantic_config",
                       "model %s exists but was NOT created by the factory (no "
                       "owismindFactory marker): refusing to modify it, apply the "
                       "wizard config by hand or check the model name" % model_id)
            return None
        try:
            # Version backup of the active raw BEFORE any mutation, so a re-run
            # with a stale wizard config never erases human curation for good.
            backup_settings = model.new_version(_next_backup_version_id(model))
            backup_raw = backup_settings.get_raw()
            backup_raw.clear()
            backup_raw.update(copy.deepcopy(active_raw))
            backup_settings.save()
            # new_version MAY activate the new version on some DSS builds:
            # re-pin the original active version before mutating it.
            model.set_active_version_id(guard_vid)
        except Exception as exc:
            ctx.manual("semantic_config",
                       "backup version of model %s could not be created (%s): "
                       "refusing to modify the active version without a safety "
                       "net, apply the wizard config by hand" % (model_id, exc))
            return None
        # Target the guarded version explicitly (never whatever is active now).
        version_id = guard_vid

    def _apply():
        model = ctx.project.get_semantic_model(model_id)
        vid = version_id or model.get_active_version_id()
        version_settings = model.get_version(vid).get_settings()
        raw = version_settings.get_raw()
        entities = raw.get("entities") or []
        if not entities:
            raise RuntimeError("model %s has no entity to configure" % model_id)
        entity = entities[0]

        if config.get("entity_name"):
            entity["name"] = config["entity_name"]
        if config.get("entity_description"):
            entity["description"] = config["entity_description"]
        if config.get("primary_key"):
            entity["primaryKey"] = {"attributes": list(config["primary_key"])}

        by_column = {a.get("column"): a for a in entity.get("attributes") or []}
        for att in config.get("attributes") or []:
            live = by_column.get(att.get("column") or att.get("name"))
            if live is None:
                continue
            if att.get("description"):
                live["description"] = att["description"]
            if att.get("resolvable") is not None:
                resolvable = bool(att["resolvable"])
                live["indexDistinctValues"] = resolvable
                live["resolveInUserRequests"] = resolvable
                live["distinctValuesHandlingMode"] = "AUTO_INDEX" if resolvable else "NONE"

        # "key present in config" (even empty) means APPLY, so a later config can
        # legitimately clear stale content; an absent key leaves the model as is.
        if "metrics" in config:
            entity["metrics"] = [_wizard_metric(m) for m in config.get("metrics") or []]
        if "filters" in config:
            entity["filters"] = [_wizard_filter(f) for f in config.get("filters") or []]
        if "instructions" in config:
            raw.setdefault("sqlGenerationConfig", {})
            raw["sqlGenerationConfig"]["instructions"] = config.get("instructions") or ""
        if "glossary" in config:
            raw["glossaryTerms"] = [_wizard_glossary_term(t) for t in config.get("glossary") or []]

        if "golden_queries" in config:
            golden = []
            for gq in config.get("golden_queries") or []:
                # A golden query without its SQL is not usable by the model: keep
                # only complete ones, the rest surface in the report as curation TODOs.
                if gq.get("generatedSql") or gq.get("sql"):
                    golden.append({
                        "name": gq.get("name") or (gq.get("question") or "")[:60],
                        "question": gq.get("question") or "",
                        "generatedSql": gq.get("generatedSql") or gq.get("sql"),
                    })
            raw["goldenQueries"] = golden

        version_settings.save()
        return model_id

    return ctx.act("semantic_config",
                   "apply wizard config to model %s (descriptions, resolvable flags, "
                   "metrics, filters, glossary, instructions, golden queries)" % model_id,
                   _apply)


# --------------------------------------------------------------------- indexing

def start_indexing(ctx, model_id, wait=True):
    """One explicit distinct-values indexing pass (uses the embedding LLM).

    Triggered ONCE per creation, never in a loop: indexing consumes LLM Mesh
    embedding calls and scans the dataset.
    """
    if not model_id:
        ctx.skip("semantic_index", "no model id (dry run or earlier failure)")
        return None

    def _index():
        model = ctx.project.get_semantic_model(model_id)
        version = model.get_version(model.get_active_version_id())
        future = version.start_update_distinct_values()
        if wait and future is not None:
            future.wait_for_result()
        return True

    return ctx.act("semantic_index",
                   "index distinct values of model %s (one pass, embedding LLM)" % model_id,
                   _index)
