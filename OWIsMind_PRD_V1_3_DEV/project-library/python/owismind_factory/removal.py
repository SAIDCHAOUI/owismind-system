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
