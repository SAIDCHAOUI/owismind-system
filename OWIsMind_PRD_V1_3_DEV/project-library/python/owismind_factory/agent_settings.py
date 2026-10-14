"""agent_settings: the per-agent "Settings" view of the Agent Factory Console.

One call (:func:`agent_bundle`) gathers, for the orchestrator or one sub-agent,
everything an operator wants to see and change without opening agent code:

- the LLM each mode (smart / pro / claude) resolves to, and WHY (per-agent
  override, central mode model, or the id embedded in the agent);
- the editable prompt layers kept in the hub (persona + workflow prompts for the
  orchestrator, additive understanding rules for a sub-agent);
- the routing description the orchestrator reads to pick the sub-agent;
- the tools the agent can use (read-only, with the Semantic Model Query tool's own
  LLM when DSS exposes it).

Read-only toward DSS (only hub files are ever written, by the console routes),
stdlib only, defensive: every best-effort lookup degrades to ``None`` instead of
raising, so the screen always renders.
"""

from . import hub, prompt_writer

# Orchestrator prompt layers (hub files). Bounds mirror the agent loaders.
WORKFLOW_PATH = hub.HUB_ROOT + "/prompts/orchestrator_workflow.md"
PERSONA_MIN_CHARS = 500
PERSONA_MAX_CHARS = 20000
EXTRA_MAX_CHARS = 4000
WORKFLOW_MAX_CHARS = 20000
DESCRIPTION_MIN_CHARS = 20
DESCRIPTION_MAX_CHARS = 4000

# Tools the orchestrator always owns (code, not configuration): shown read-only.
ORCHESTRATOR_BUILTIN_TOOLS = (
    {"name": "attribute_lookup", "role": "Fast value read on the source tables (exact names, aliases)."},
    {"name": "recall_prior_result", "role": "Reload data already fetched earlier in the conversation."},
    {"name": "show_chart", "role": "Render the latest result as a chart in the Evidence panel."},
    {"name": "show_table", "role": "Render the latest result as a table in the Evidence panel."},
    {"name": "show_kpi", "role": "Render one headline figure as a KPI card."},
)

# What every sub-agent does itself (frozen dialect: registry.KNOWN_TOOL_NAMES).
SUBAGENT_STEPS = (
    {"name": "resolve_filter_value", "role": "Grounds the user's words on the exact values of the data (read-only SQL)."},
    {"name": "dataset_sql_query", "role": "Writes and runs the SQL through its Semantic Model Query tool."},
)


def prompt_specs(agent_key, entry=None):
    """The editable hub prompt layers of one agent (no content, just the shape)."""
    if agent_key == hub.ORCHESTRATOR_KEY:
        return [
            {"id": "persona", "label": "System prompt (persona and rules of conduct)",
             "path": hub.PERSONA_PATH, "min": PERSONA_MIN_CHARS, "max": PERSONA_MAX_CHARS,
             "help": "The main system prompt of the orchestrator: voice, honesty rules, "
                     "output contract. It replaces the built-in text when the file exists."},
            {"id": "workflow", "label": "Workflow prompts (planner, replanner, reviewer, synthesizer)",
             "path": WORKFLOW_PATH, "min": 1, "max": WORKFLOW_MAX_CHARS,
             "help": "The four prompts of the durable multi-step workflow. Keep the four "
                     "section headings (## PLANNER, ## REPLANNER, ## REVIEWER, ## SYNTHESIZER)."},
        ]
    domain = (entry or {}).get("domain")
    if not domain:
        return []
    return [
        {"id": "business_prompt", "label": "Business prompt (domain knowledge)",
         "path": prompt_writer.business_prompt_path(domain),
         "min": 0, "max": prompt_writer.PROMPT_MAX_CHARS, "ai": True,
         "help": "The real business knowledge of this sub-agent: vocabulary, definitions, how "
                 "users phrase things, disambiguation rules, traps, worked examples. It becomes "
                 "its own section of the agent's system prompt, after the technical frame "
                 "(JSON contract, intents, columns), which the factory keeps generating. "
                 "Write it with the AI, then read it and correct it."},
        {"id": "understand_extra", "label": "Extra rules (short, additive)",
         "path": "%s/prompts/%s/understand_extra.md" % (hub.HUB_ROOT, domain),
         "min": 0, "max": EXTRA_MAX_CHARS,
         "help": "A few short team rules appended at the very end of the prompt. Use it for a "
                 "quick fix; put durable knowledge in the business prompt. Empty = none."},
    ]


def _find_llm_id(node, depth=0):
    """First plausible LLM id found in a tool's raw settings (None when absent)."""
    if depth > 6:
        return None
    if isinstance(node, dict):
        for key, value in node.items():
            if isinstance(value, str) and "llm" in str(key).lower() and hub.valid_llm_id(value):
                return value
        for value in node.values():
            found = _find_llm_id(value, depth + 1)
            if found:
                return found
    elif isinstance(node, list):
        for value in node:
            found = _find_llm_id(value, depth + 1)
            if found:
                return found
    return None


def semantic_tool_info(project, domain):
    """Name / id / LLM of the domain's Semantic Model Query tool (best effort)."""
    name = "%s_semantic_query" % domain
    info = {"name": name, "id": None, "llm": None, "role":
            "Semantic Model Query tool: writes and runs the SQL. Its LLM is set in DSS "
            "(Agents & GenAI Models > Tools), not in this file."}
    try:
        for item in project.list_agent_tools():
            item_name = item.name if hasattr(item, "name") else item.get("name")
            if item_name == name:
                info["id"] = item.id if hasattr(item, "id") else item.get("id")
                break
        if info["id"]:
            raw = project.get_agent_tool(info["id"]).get_settings().get_raw()
            info["llm"] = _find_llm_id(raw)
    except Exception:
        pass
    return info


def agent_bundle(project, agent_key, capabilities, settings):
    """Everything the Settings panel shows for ``agent_key`` (orchestrator or a capability key)."""
    models = hub.read_models(project)
    if agent_key == hub.ORCHESTRATOR_KEY:
        entry = None
        model_key = hub.ORCHESTRATOR_KEY
        label = "OWIsMind orchestrator"
        agent_id = settings.get("orchestrator_agent_id") or ""
        tools = [dict(t, kind="built-in") for t in ORCHESTRATOR_BUILTIN_TOOLS]
        for key, cap in (capabilities or {}).items():
            if isinstance(cap, dict) and cap.get("kind") == "agent":
                tools.append({
                    "name": cap.get("tool_name"), "kind": "sub-agent",
                    "role": cap.get("planner_description") or "",
                    "enabled": bool(cap.get("enabled")), "capability": key,
                })
    else:
        entry = (capabilities or {}).get(agent_key)
        if not isinstance(entry, dict):
            raise KeyError(agent_key)
        model_key = entry.get("domain") or agent_key
        label = entry.get("label_en") or entry.get("label_fr") or model_key
        agent_id = entry.get("agent_id") or ""
        tools = [dict(t, kind="step") for t in SUBAGENT_STEPS]
        tool = semantic_tool_info(project, model_key)
        tool["kind"] = "semantic tool"
        tools.append(tool)

    prompts = []
    for spec in prompt_specs(agent_key, entry):
        text = hub.read_text(project, spec["path"])
        prompts.append(dict(spec, exists=text is not None, content=text or ""))

    return {
        "key": agent_key,
        "model_key": model_key,
        "label": label,
        "agent_id": agent_id,
        "models": hub.effective_models(models, model_key),
        "models_file": models is not None,
        "own_overrides": dict(((models or {}).get("agents") or {}).get(model_key) or {}),
        "prompts": prompts,
        "routing_description": (entry or {}).get("planner_description") if entry else None,
        "description_limits": {"min": DESCRIPTION_MIN_CHARS, "max": DESCRIPTION_MAX_CHARS},
        "tools": tools,
    }


def set_planner_description(project, agent_key, text):
    """Replace one capability's routing description (validated, backed-up write)."""
    text = (text or "").strip()
    if not DESCRIPTION_MIN_CHARS <= len(text) <= DESCRIPTION_MAX_CHARS:
        raise ValueError("description must be %d to %d characters"
                         % (DESCRIPTION_MIN_CHARS, DESCRIPTION_MAX_CHARS))
    caps = hub.read_capabilities(project)
    if not isinstance(caps, dict) or agent_key not in caps:
        raise KeyError(agent_key)
    caps[agent_key]["planner_description"] = text
    hub.write_capabilities(project, caps)
    return caps
