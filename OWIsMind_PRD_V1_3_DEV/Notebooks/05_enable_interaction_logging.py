# =============================================================================
# 05_enable_interaction_logging.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK inside the OWIsMind project whose agents you want
# to observe. It turns on LLM interaction logging for the orchestrator and every
# sub-agent, routing each turn (input, output, tool calls) to ONE managed logging
# dataset. The prompt doctor (06_prompt_doctor.py) then reads that dataset to
# propose prompt improvements.
#
# Read-only by default: DRY_RUN=True prints the PLAN, nothing is created or
# changed. Flip DRY_RUN=False to apply. Documented public API only:
#   project.create_llm_interaction_logging_dataset(name, connection)
#   agent.get_settings().get_version_settings(v).interaction_logging_selection
#       .enable(dataset);  settings.save()
#
# NOTE: DSS BUFFERS logging writes and flushes them asynchronously, so the dataset
# lags live traffic by a few minutes - do not expect a row to appear instantly.
# =============================================================================

import dataiku
from owismind_factory import hub
from owismind_factory.fctx import FactoryContext

# --------------------------------------------------------------------------- CONFIG
DRY_RUN = True                     # True = preview only; flip to False to apply
LOGGING_DATASET = "owismind_agent_logs"
CONNECTION = None                  # None -> hub factory_settings["sql_connection"]
AGENT_IDS = None                   # None -> discover (orchestrator + capabilities.json)

# --------------------------------------------------------------------------- resolve project + settings
client = dataiku.api_client()
project = client.get_default_project()
settings = hub.get_settings(project)
connection = CONNECTION or settings.get("sql_connection")

# --------------------------------------------------------------------------- discover agent ids
def discover_agent_ids():
    """Orchestrator + every capabilities.json agent (agent: prefix stripped);
    fall back to the project's agent list if the hub is empty."""
    ids = []
    orchestrator = settings.get("orchestrator_agent_id")
    if orchestrator:
        ids.append(str(orchestrator).replace("agent:", ""))
    capabilities = hub.read_capabilities(project) or {}
    for cap in capabilities.values():
        agent_id = cap.get("agent_id") if isinstance(cap, dict) else None
        if agent_id:
            ids.append(str(agent_id).replace("agent:", ""))
    if not ids:
        try:
            for handle in project.list_agents():
                agent_id = handle.get("id") if isinstance(handle, dict) else getattr(handle, "id", None)
                if agent_id:
                    ids.append(str(agent_id).replace("agent:", ""))
        except Exception as exc:
            print("could not list agents:", exc)
    seen, unique = set(), []
    for agent_id in ids:
        if agent_id and agent_id not in seen:
            seen.add(agent_id)
            unique.append(agent_id)
    return unique


agent_ids = AGENT_IDS or discover_agent_ids()
ctx = FactoryContext(project, dry_run=DRY_RUN)

# --------------------------------------------------------------------------- 1. logging dataset
def dataset_exists(name):
    try:
        for handle in project.list_datasets():
            existing = handle.get("name") if isinstance(handle, dict) else getattr(handle, "name", None)
            if existing == name:
                return True
    except Exception:
        pass
    return False


if dataset_exists(LOGGING_DATASET):
    ctx.skip("logging_dataset", "%s already exists" % LOGGING_DATASET)
else:
    ctx.act("logging_dataset",
            "create LLM interaction logging dataset %s on connection %s"
            % (LOGGING_DATASET, connection),
            lambda: project.create_llm_interaction_logging_dataset(LOGGING_DATASET, connection))

# --------------------------------------------------------------------------- 2. enable per agent
def enable_logging(agent_id):
    agent = project.get_agent(agent_id)
    agent_settings = agent.get_settings()
    active = getattr(agent_settings, "active_version", None)
    version = active or agent_settings.get_version_ids()[-1]
    version_settings = agent_settings.get_version_settings(version)
    version_settings.interaction_logging_selection.enable(LOGGING_DATASET)
    agent_settings.save()
    return version


for agent_id in agent_ids:
    ctx.act("enable_logging.%s" % agent_id,
            "route agent %s interactions to %s" % (agent_id, LOGGING_DATASET),
            lambda agent_id=agent_id: enable_logging(agent_id))

# --------------------------------------------------------------------------- report
print(ctx.report_markdown("Enable interaction logging"))
print("\nAgents targeted:", agent_ids or "(none discovered - set AGENT_IDS)")
print("Reminder: DSS buffers logging writes; the dataset lags live traffic by a few minutes.")
if DRY_RUN:
    print("\nDRY_RUN=True -> nothing was created or changed. Review the plan, then set "
          "DRY_RUN=False and re-run.")
