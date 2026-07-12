"""Semantic Model Query tool creation (GATED: needs Phase 0 discovery).

The generic creator API is official (project.new_agent_tool(type, name).create()
then settings.params / save), but the Semantic Model Query tool's literal type
string and params schema are NOT documented anywhere. So this module never
guesses: creation requires a ``discovery`` dict produced by the Phase 0 probe
from the LIVE template tool (revenue_semantic_query, v4oqA6R):

    discovery = {
        "type": "<literal type string of the template tool>",
        "params_template": { ...deep copy of the template tool's params... },
        "template_model_id": "AHUh9hb",
    }

The clone strategy is duplicate-and-modify: copy the validated params verbatim
and swap every occurrence of the template semantic model id for the new model's
id. Anything else stays exactly as validated in production. Without discovery,
the factory degrades to the precise UI checklist from the playbook.
"""

import json


def describe_existing_tool(project, tool_id):
    """Read type + params of an existing tool (the probe's discovery source)."""
    tool_type = None
    tool_name = None
    for item in project.list_agent_tools():
        item_id = item.id if hasattr(item, "id") else item.get("id")
        if item_id == tool_id:
            tool_type = item.type if hasattr(item, "type") else item.get("type")
            tool_name = item.name if hasattr(item, "name") else item.get("name")
            break
    tool = project.get_agent_tool(tool_id)
    settings = tool.get_settings()
    raw = settings.get_raw() if hasattr(settings, "get_raw") else {}
    params = settings.params if hasattr(settings, "params") else (raw.get("params") or {})
    return {
        "tool_id": tool_id,
        "type": tool_type,
        "name": tool_name,
        "params": params,
        "raw_keys": sorted(raw.keys()) if isinstance(raw, dict) else [],
        "description": raw.get("description") if isinstance(raw, dict) else None,
    }


def build_discovery(project, template_tool_id, template_model_id):
    """Assemble the discovery dict from the live template tool (read-only)."""
    info = describe_existing_tool(project, template_tool_id)
    if not info.get("type"):
        return None
    return {
        "type": info["type"],
        "params_template": json.loads(json.dumps(info.get("params") or {})),
        "template_model_id": template_model_id,
    }


def _swap_model_id(obj, old_id, new_id):
    """Deep string swap of the semantic model id inside the params clone."""
    if isinstance(obj, dict):
        return {k: _swap_model_id(v, old_id, new_id) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_swap_model_id(v, old_id, new_id) for v in obj]
    if isinstance(obj, str) and old_id and old_id in obj:
        return obj.replace(old_id, new_id)
    return obj


def tool_exists(project, name):
    """Return the tool id, or None when confirmed absent.

    A listing failure raises ExistenceCheckError (same contract as
    flow_builder): 'absent' must never be concluded from an API error, or a
    rerun during a DSS hiccup would create a duplicate tool.
    """
    from .flow_builder import ExistenceCheckError
    try:
        for item in project.list_agent_tools():
            item_name = item.name if hasattr(item, "name") else item.get("name")
            if item_name == name:
                return item.id if hasattr(item, "id") else item.get("id")
        return None
    except Exception as exc:
        raise ExistenceCheckError("could not list agent tools: %s" % exc)


def ui_checklist(spec, model_id):
    """The manual fallback: exact clicks, from the validated playbook."""
    return (
        "Create the Semantic Model Query tool BY HAND in DSS (2 minutes): "
        "Agents & GenAI Models > Tools > New tool > Semantic Model Query; "
        "name it %s; bind it to the semantic model %s (id %s); Agent mode OFF "
        "(simple linear pipeline); LLM vertex_ai/claude-sonnet-4-6; access "
        "datasets as the calling user; paste the generated 'Description for "
        "LLM'. Then note the tool id and put it into the capability entry "
        "(semantic tool id) and the generated sub-agent CONFIG."
        % (spec.semantic_tool_name, spec.semantic_model_name, model_id or "?"))


def create_semantic_query_tool_like(ctx, spec, model_id, discovery, description=None):
    """Create the domain's Semantic Model Query tool by cloning the template.

    Returns the new tool id, or None (dry-run / gated / failed).
    """
    from .flow_builder import ExistenceCheckError
    try:
        existing_id = tool_exists(ctx.project, spec.semantic_tool_name)
    except ExistenceCheckError as exc:
        if ctx.dry_run:
            # Planning creates nothing: an unverifiable existence is fine here.
            existing_id = None
        else:
            ctx.fail("semantic_tool", "existence check failed, NOT creating: %s" % exc)
            return None
    if existing_id:
        ctx.skip("semantic_tool", "tool %s already exists (id %s)"
                 % (spec.semantic_tool_name, existing_id))
        return existing_id

    if not model_id:
        ctx.manual("semantic_tool", ui_checklist(spec, model_id))
        return None

    if not discovery or not discovery.get("type") or not isinstance(discovery.get("params_template"), dict):
        ctx.manual("semantic_tool",
                   "GATED (no probe discovery for the tool params schema). " + ui_checklist(spec, model_id))
        return None

    def _create():
        params = _swap_model_id(json.loads(json.dumps(discovery["params_template"])),
                                discovery.get("template_model_id") or "",
                                model_id)
        creator = ctx.project.new_agent_tool(discovery["type"], name=spec.semantic_tool_name)
        tool = creator.create()
        settings = tool.get_settings()
        live_params = settings.params
        if isinstance(live_params, dict):
            live_params.clear()
            live_params.update(params)
        if description:
            try:
                settings.description = description
            except Exception:
                raw = settings.get_raw()
                if isinstance(raw, dict):
                    raw["description"] = description
        settings.save()
        return tool.id if hasattr(tool, "id") else None

    return ctx.act("semantic_tool",
                   "create Semantic Model Query tool %s (type %s cloned from template, "
                   "model id swapped %s -> %s). REVIEW ITS SETTINGS IN DSS before use."
                   % (spec.semantic_tool_name, discovery["type"],
                      discovery.get("template_model_id"), model_id),
                   _create)


def build_tool_description(spec, config=None):
    """The 'Description for LLM' text of the new tool (same shape as the live ones)."""
    planner = (config or {}).get("planner_description") or spec.planner_description
    return (
        "Answers natural-language questions about the %s dataset by writing and "
        "executing SQL through its semantic model. Give it ONE clear question in "
        "plain language, with exact data values when known. It returns the computed "
        "result rows. %s" % (spec.base_dataset, planner))
