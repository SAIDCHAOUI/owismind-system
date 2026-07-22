"""Capability removal: probe-based inventory + safe deletion executors.

The guided REMOVAL run (guided.py) deletes everything a capability owns, one
confirmed stage at a time. This module owns the two delicate halves:

- ``build_inventory``: resolve what the capability ACTUALLY owns by probing
  DSS (capability entry + naming conventions + live listings). Nothing is
  assumed from conventions alone: an object enters the inventory only when
  its existence is CONFIRMED. The SOURCE dataset (entry ``lookup_dataset``)
  is listed as PROTECTED and never deletable (user decision 2026-07-22).
- the deletion executors: delete one stage's objects with the identity gate
  (re-read the live name, match it, only then delete), verify disappearance
  by read-back, and report objects the API refused so the guided stage can
  flip to manual instructions.

No persistence and no HTTP here; guided.py drives and persists.
"""

import json

from . import hub

# Stage keys carrying deletable inventory items. catalog_cleanup and
# hub_cleanup have dedicated executors and are not item-based.
DELETE_STAGE_KEYS = ("delete_tool", "delete_agent", "delete_model",
                     "delete_scenario", "delete_recipes", "delete_datasets",
                     "delete_zone")


class RemovalRefused(RuntimeError):
    """The identity/safety gate refused a deletion (never a DSS API error)."""


def safe_delete(handle, expected_name, getter, noun="object", hint="", deleter=None):
    """Delete ``handle`` ONLY after re-reading its live name and matching it.

    Pattern extracted from probes.py (the factory's historical single deletion
    site): a wrong handle must never delete a real object. ``deleter`` lets a
    caller pass extra flags (e.g. ``delete(drop_data=True)`` for datasets).
    """
    live_name = None
    try:
        live_name = getter()
    except Exception:
        pass
    if live_name is None:
        # FAIL-CLOSED: no proof the handle still points at the expected
        # object, so the deletion must not happen.
        raise RemovalRefused(
            "could not re-read the live name of the %s (expected %r): "
            "refusing to delete%s" % (noun, expected_name, hint))
    if live_name != expected_name:
        raise RemovalRefused("refusing to delete %r: expected %s %r"
                             % (live_name, noun, expected_name))
    if deleter is not None:
        deleter()
    else:
        handle.delete()


# ------------------------------------------------------------------ inventory

def _item(kind_fr, name, where_fr, obj_id="", note_fr=""):
    return {"kind_fr": kind_fr, "name": str(name or ""), "id": str(obj_id or ""),
            "where_fr": where_fr, "note_fr": note_fr}


def conventional_spec(entry):
    """Best-effort DomainSpec derived from a capability entry (None when the
    entry cannot yield a legal spec, e.g. exotic founder fields)."""
    from .spec import DomainSpec, SpecError
    try:
        return DomainSpec(domain=entry.get("domain"),
                          base_dataset=entry.get("lookup_dataset"),
                          label_fr=entry.get("label_fr") or "domaine",
                          label_en=entry.get("label_en") or "domain")
    except SpecError:
        return None


def _listed_name_by_id(items, wanted_id):
    for item in items:
        item_id = item.id if hasattr(item, "id") else item.get("id")
        if item_id == wanted_id:
            return item.name if hasattr(item, "name") else item.get("name")
    return None


def agent_name_by_id(project, agent_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_agents(), agent_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list agents: %s" % exc)


def tool_name_by_id(project, tool_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_agent_tools(), tool_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list agent tools: %s" % exc)


def model_name_by_id(project, model_id):
    from .flow_builder import ExistenceCheckError
    try:
        return _listed_name_by_id(project.list_semantic_models(), model_id)
    except Exception as exc:
        raise ExistenceCheckError("could not list semantic models: %s" % exc)


def resolve_model(project, spec, tool_id):
    """(model_id, model_name): convention name first, then the tool's params
    (founder models predate the naming conventions; their semantic-query tool
    knows the real model id)."""
    from . import semantic_builder, tool_builder
    if spec is not None:
        model = semantic_builder.find_model_by_name(project, spec.semantic_model_name)
        if model is not None:
            model_id = getattr(model, "id", None) or getattr(model, "semantic_model_id", None)
            if model_id:
                return model_id, spec.semantic_model_name
    if tool_id:
        try:
            try:
                info = tool_builder.describe_existing_tool(project, tool_id)
            except (AttributeError, TypeError):
                settings = project.get_agent_tool(tool_id).get_settings()
                raw = settings.get_raw() if hasattr(settings, "get_raw") else {}
                params = settings.params if hasattr(settings, "params") else (raw.get("params") or {})
                info = {"params": params}
            blob = json.dumps(info.get("params") or {})
            for item in project.list_semantic_models():
                item_id = item.id if hasattr(item, "id") else item.get("id")
                if item_id and str(item_id) in blob:
                    name = item.name if hasattr(item, "name") else item.get("name")
                    return item_id, name
        except Exception:
            pass
    return None, None


def hub_paths(entry, spec, agent_name):
    """Hub files/folders the domain owns (existence re-checked at cleanup)."""
    domain = str(entry.get("domain") or "")
    file_agent = (spec.agent_name if spec is not None else "") or agent_name or ""
    paths = ["%s/wizard/%s-config.json" % (hub.HUB_ROOT, domain),
             "%s/prompts/%s" % (hub.HUB_ROOT, domain)]
    if file_agent:
        paths.append("%s/generated/%s.py" % (hub.HUB_ROOT, file_agent))
    return paths


def template_conflicts(settings, stages):
    """French warnings when the domain's objects serve as factory templates."""
    conflicts = []
    settings = settings or {}
    tool_ids = [i["id"] for i in stages.get("delete_tool", [])]
    model_ids = [i["id"] for i in stages.get("delete_model", [])]
    recipe_names = [i["name"] for i in stages.get("delete_recipes", [])]
    template_tool = str(settings.get("template_semantic_tool_id") or "")
    template_model = str(settings.get("template_semantic_model_id") or "")
    if template_tool and template_tool in tool_ids:
        conflicts.append(
            "le tool %s est le TEMPLATE tool de l'usine "
            "(factory_settings.json : template_semantic_tool_id)" % template_tool)
    if template_model and template_model in model_ids:
        conflicts.append(
            "le modèle %s est le TEMPLATE de modèle sémantique de l'usine "
            "(factory_settings.json : template_semantic_model_id)" % template_model)
    for label, recipe in sorted((settings.get("template_zone_recipes") or {}).items()):
        if recipe in recipe_names:
            conflicts.append(
                "la recette %s est la recette TEMPLATE %r de l'usine "
                "(factory_settings.json : template_zone_recipes)" % (recipe, label))
    return conflicts


def build_inventory(project, capability_key, entry, settings):
    """Probe what the capability ACTUALLY owns. Returns (inventory, problems).

    problems non-empty means a LISTING failed: the inventory is partial and
    the caller must fail its stage (deleting on a partial inventory is
    forbidden). Absent candidates never enter ``stages``; they land in
    ``notes`` so the operator sees "déjà absent" instead of a silent hole.
    """
    from . import flow_builder, tool_builder
    from .catalog import CATALOG_DATASET_NAME
    from .flow_builder import ExistenceCheckError

    problems, notes = [], []
    stages = {key: [] for key in DELETE_STAGE_KEYS}
    spec = conventional_spec(entry)
    domain = str(entry.get("domain") or "")
    base_dataset = str(entry.get("lookup_dataset") or "")
    zone_name = spec.zone_name if spec is not None else ""
    where_flow = "Flow%s" % ((", zone %s" % zone_name) if zone_name else "")

    # Tool (the <domain>_semantic_query convention holds for founders too).
    tool_name = "%s_semantic_query" % domain
    tool_id = None
    try:
        tool_id = tool_builder.tool_exists(project, tool_name)
    except ExistenceCheckError as exc:
        problems.append("Impossible de lister les tools (%s) : réessaie." % exc)
    if tool_id:
        stages["delete_tool"].append(_item(
            "Tool Semantic Model Query", tool_name,
            "Agents & GenAI Models > Tools", tool_id))
    else:
        notes.append("Tool %s : déjà absent." % tool_name)

    # Code Agent (id from the entry, live name from the listing).
    agent_ref = str(entry.get("agent_id") or "")
    agent_id = agent_ref.split(":", 1)[1] if ":" in agent_ref else agent_ref
    agent_name = None
    if agent_id:
        try:
            agent_name = agent_name_by_id(project, agent_id)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les agents (%s) : réessaie." % exc)
    if agent_name:
        stages["delete_agent"].append(_item(
            "Code Agent", agent_name, "Agents & GenAI Models > Agents", agent_id))
    else:
        notes.append("Code Agent %s : déjà absent." % (agent_id or "(id inconnu)"))

    # Semantic model (convention name, else resolved through the tool params).
    model_id, model_name = resolve_model(project, spec, tool_id)
    if model_id:
        stages["delete_model"].append(_item(
            "Modèle sémantique", model_name or model_id,
            "Agents & GenAI Models > Semantic models", model_id))
    else:
        notes.append("Modèle sémantique : introuvable (déjà absent, ou nom hors "
                     "convention sans tool pour le retrouver).")

    # Refresh scenario (Refresh_<Domain> convention).
    if spec is not None:
        scenario_id = None
        try:
            scenario_id = flow_builder.scenario_id_by_name(project, spec.scenario_name)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les scénarios (%s) : réessaie." % exc)
        if scenario_id:
            stages["delete_scenario"].append(_item(
                "Scénario", spec.scenario_name, "Scenarios", scenario_id))
        else:
            notes.append("Scénario %s : déjà absent." % spec.scenario_name)

    # Knowledge datasets: profile + value_index by convention, catalog from the
    # entry (it carries the REAL name, founders included). The SOURCE dataset
    # (lookup_dataset) is PROTECTED: never deletable (user decision 2026-07-22).
    candidates = []
    if spec is not None:
        candidates = [spec.profile_dataset, spec.value_index_dataset]
    lookup_catalog = str(entry.get("lookup_catalog") or "")
    if lookup_catalog and lookup_catalog not in candidates:
        candidates.append(lookup_catalog)
    for name in candidates:
        if name == base_dataset:
            continue  # belt and braces: the source is never a candidate
        try:
            found = flow_builder.dataset_exists(project, name)
        except ExistenceCheckError as exc:
            problems.append("Impossible de lister les datasets (%s) : réessaie." % exc)
            continue
        if found:
            stages["delete_datasets"].append(_item(
                "Dataset de connaissance", name, where_flow,
                note_fr="sa table SQL dérivée sera supprimée (reconstructible)"))
            recipe = "compute_%s" % name
            try:
                if flow_builder.recipe_exists(project, recipe):
                    stages["delete_recipes"].append(_item(
                        "Recette Python", recipe, where_flow))
                else:
                    notes.append("Recette %s : déjà absente." % recipe)
            except ExistenceCheckError as exc:
                problems.append("Impossible de lister les recettes (%s) : réessaie." % exc)
        else:
            notes.append("Dataset %s : déjà absent." % name)

    # Flow zone (deleted only if EMPTY at its stage's turn).
    if zone_name:
        zone = None
        try:
            zone = flow_builder._zone_by_name(project.get_flow(), zone_name)
        except Exception:
            zone = None
        if zone is not None:
            stages["delete_zone"].append(_item(
                "Zone du Flow", zone_name, "Flow",
                note_fr="supprimée SEULEMENT si vide (le dataset source, jamais "
                        "touché, peut la garder en vie)"))
        else:
            notes.append("Zone %s : déjà absente." % zone_name)

    protected = []
    if base_dataset:
        protected.append(_item("Dataset SOURCE (protégé)", base_dataset, "Flow",
                               note_fr="JAMAIS supprimé par ce run"))

    inventory = {
        "stages": stages,
        "protected": protected,
        "notes": notes,
        "template_conflicts": template_conflicts(settings, stages),
        "capability_key": capability_key,
        "domain": domain,
        "hub_paths": hub_paths(entry, spec, agent_name),
        "catalog": {"dataset": CATALOG_DATASET_NAME, "capability_key": capability_key},
    }
    return inventory, problems


# ------------------------------------------------------------------ executors

def scenario_is_running(project, scenario_id):
    """True/False when provable, None when unknown (never a verdict)."""
    try:
        return project.get_scenario(scenario_id).get_current_run() is not None
    except Exception:
        return None


def _delete_tool_item(project, item):
    from . import tool_builder
    if not tool_builder.tool_exists(project, item["name"]):
        return "absent"
    handle = project.get_agent_tool(item["id"])
    safe_delete(handle, item["name"],
                lambda: tool_name_by_id(project, item["id"]), noun="tool")
    return "deleted" if not tool_builder.tool_exists(project, item["name"]) \
        else "still_there"


def _delete_agent_item(project, item):
    if agent_name_by_id(project, item["id"]) is None:
        return "absent"
    handle = project.get_agent(item["id"])
    safe_delete(handle, item["name"],
                lambda: agent_name_by_id(project, item["id"]), noun="agent")
    return "deleted" if agent_name_by_id(project, item["id"]) is None \
        else "still_there"


def _delete_model_item(project, item):
    if model_name_by_id(project, item["id"]) is None:
        return "absent"
    handle = project.get_semantic_model(item["id"])
    safe_delete(handle, item["name"],
                lambda: model_name_by_id(project, item["id"]),
                noun="semantic model")
    return "deleted" if model_name_by_id(project, item["id"]) is None \
        else "still_there"


def _delete_scenario_item(project, item):
    from . import flow_builder
    if flow_builder.scenario_id_by_name(project, item["name"]) is None:
        return "absent"
    if scenario_is_running(project, item["id"]) is True:
        raise RemovalRefused("le scénario tourne en ce moment : attends la fin "
                             "de son run avant de le supprimer")
    handle = project.get_scenario(item["id"])

    def _live_name():
        listed = flow_builder.scenario_id_by_name(project, item["name"])
        return item["name"] if listed == item["id"] else None

    safe_delete(handle, item["name"], _live_name, noun="scenario")
    return "deleted" \
        if flow_builder.scenario_id_by_name(project, item["name"]) is None \
        else "still_there"


def _delete_recipe_item(project, item):
    from . import flow_builder
    if not flow_builder.recipe_exists(project, item["name"]):
        return "absent"
    handle = project.get_recipe(item["name"])
    safe_delete(handle, item["name"],
                lambda: item["name"]
                if flow_builder.recipe_exists(project, item["name"]) else None,
                noun="recipe")
    return "deleted" if not flow_builder.recipe_exists(project, item["name"]) \
        else "still_there"


def _delete_dataset_item(project, item):
    from . import flow_builder
    if not flow_builder.dataset_exists(project, item["name"]):
        return "absent"
    handle = project.get_dataset(item["name"])
    safe_delete(handle, item["name"],
                lambda: item["name"]
                if flow_builder.dataset_exists(project, item["name"]) else None,
                noun="dataset",
                deleter=lambda: handle.delete(drop_data=True))
    return "deleted" if not flow_builder.dataset_exists(project, item["name"]) \
        else "still_there"


def _delete_zone_item(project, item):
    from . import flow_builder
    zone = flow_builder._zone_by_name(project.get_flow(), item["name"])
    if zone is None:
        return "absent"
    contents = getattr(zone, "items", None)
    if contents is None:
        raise RemovalRefused("impossible de lire le contenu de la zone : "
                             "vide-la et supprime-la à la main si tu la veux partie")
    if len(contents) > 0:
        return "kept"
    zone.delete()
    return "deleted" \
        if flow_builder._zone_by_name(project.get_flow(), item["name"]) is None \
        else "still_there"


_STAGE_EXECUTORS = {
    "delete_tool": _delete_tool_item,
    "delete_agent": _delete_agent_item,
    "delete_model": _delete_model_item,
    "delete_scenario": _delete_scenario_item,
    "delete_recipes": _delete_recipe_item,
    "delete_datasets": _delete_dataset_item,
    "delete_zone": _delete_zone_item,
}


def execute_delete_stage(project, stage_key, items, ctx):
    """Delete one stage's confirmed items. Returns (manual_items, problems).

    - already-absent items are journaled and skipped (idempotent relaunch);
    - a deletion the API (or the identity gate) refuses lands in manual_items:
      the guided stage flips to manual instructions;
    - a deletion that seems to succeed but whose object is STILL listed after
      is a problem: never advance on an unverified deletion.
    """
    executor = _STAGE_EXECUTORS[stage_key]
    manual, problems = [], []
    for item in items:
        try:
            status = executor(project, item)
        except Exception as exc:  # noqa: BLE001 refusal -> manual fallback
            manual.append(dict(item, reason_fr=str(exc)[:200]))
            ctx.skip(stage_key, "%s %s: refused (%s), manual fallback"
                     % (item["kind_fr"], item["name"], exc))
            continue
        if status == "absent":
            ctx.skip(stage_key, "%s %s already absent"
                     % (item["kind_fr"], item["name"]))
        elif status == "deleted":
            ctx.done(stage_key, "deleted %s %s (verified absent)"
                     % (item["kind_fr"], item["name"]))
        elif status == "kept":
            ctx.skip(stage_key, "%s %s kept (not empty)"
                     % (item["kind_fr"], item["name"]))
        else:
            problems.append("%s %s toujours présent après la suppression : "
                            "réessaie." % (item["kind_fr"], item["name"]))
    return manual, problems


# --------------------------------------------------------------- verification

def _tool_leftover(project, item):
    from . import tool_builder
    return bool(tool_builder.tool_exists(project, item["name"]))


def _agent_leftover(project, item):
    return agent_name_by_id(project, item["id"]) is not None


def _model_leftover(project, item):
    return model_name_by_id(project, item["id"]) is not None


def _scenario_leftover(project, item):
    from . import flow_builder
    return flow_builder.scenario_id_by_name(project, item["name"]) is not None


def _recipe_leftover(project, item):
    from . import flow_builder
    return flow_builder.recipe_exists(project, item["name"])


def _dataset_leftover(project, item):
    from . import flow_builder
    return flow_builder.dataset_exists(project, item["name"])


def _zone_leftover(project, item):
    """A zone kept because it is NOT empty is a decision, not a leftover."""
    from . import flow_builder
    zone = flow_builder._zone_by_name(project.get_flow(), item["name"])
    if zone is None:
        return False
    contents = getattr(zone, "items", None) or []
    return len(contents) == 0


_STAGE_LEFTOVER_CHECKS = {
    "delete_tool": _tool_leftover,
    "delete_agent": _agent_leftover,
    "delete_model": _model_leftover,
    "delete_scenario": _scenario_leftover,
    "delete_recipes": _recipe_leftover,
    "delete_datasets": _dataset_leftover,
    "delete_zone": _zone_leftover,
}


def verify_stage_absent(project, stage_key, items):
    """Re-probe one stage's items. Returns (leftovers, problems)."""
    check = _STAGE_LEFTOVER_CHECKS[stage_key]
    leftovers, problems = [], []
    for item in items:
        try:
            if check(project, item):
                leftovers.append(item)
        except Exception as exc:  # noqa: BLE001 listing error -> retryable
            problems.append("Vérification impossible pour %s %s (%s) : réessaie."
                            % (item["kind_fr"], item["name"], exc))
    return leftovers, problems


# ------------------------------------------------------- catalog + hub cleanup

def delete_catalog_rows(project, connection, capability_key, executor_factory=None):
    """Parametrized DELETE of the capability's shared-catalog rows + COMMIT.

    Returns "deleted", "no_dataset" (nothing to clean) or "unknown_table"
    (physical table unreadable: surfaced as a note, cleanup by hand).
    """
    from . import flow_builder, guided_store, wizard
    from .catalog import CATALOG_DATASET_NAME
    try:
        if not flow_builder.dataset_exists(project, CATALOG_DATASET_NAME):
            return "no_dataset"
    except flow_builder.ExistenceCheckError:
        return "unknown_table"
    table = None
    try:
        table = wizard.get_physical_table(project, CATALOG_DATASET_NAME)
    except Exception:
        table = None
    if not table:
        return "unknown_table"
    statement = "DELETE FROM %s WHERE capability_key = %s" % (
        guided_store.quote_table(table), guided_store._sql_value(capability_key))
    if executor_factory is not None:
        executor = executor_factory()
    else:
        import dataiku
        executor = dataiku.SQLExecutor2(connection=connection)
    executor.query_to_df("SELECT 1 AS ok",
                         pre_queries=[statement], post_queries=["COMMIT"])
    return "deleted"


def cleanup_hub(project, capability_key, paths, ctx):
    """Delete the domain's hub files then its capabilities.json entry.

    Returns (manual_paths, capability_status): manual_paths lists files the
    API refused (guided flips to manual); capability_status comes from
    hub.remove_capability ("removed" / "kept_disabled" / "absent").
    """
    manual = []
    for path in paths:
        try:
            existed = hub.delete_path(project, path)
        except Exception as exc:  # noqa: BLE001 refusal -> manual fallback
            manual.append({"path": path, "reason_fr": str(exc)[:200]})
            ctx.skip("hub_cleanup", "%s: refused (%s), manual fallback" % (path, exc))
            continue
        if existed:
            ctx.done("hub_cleanup", "deleted %s" % path)
        else:
            ctx.skip("hub_cleanup", "%s already absent" % path)
    status, _caps = hub.remove_capability(project, capability_key)
    ctx.done("hub_cleanup", "capability entry %s: %s" % (capability_key, status))
    return manual, status
