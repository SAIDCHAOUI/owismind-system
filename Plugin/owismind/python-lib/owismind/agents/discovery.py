"""Read-only discovery of DSS projects and their AI agents (LLM Mesh).

The admin space uses this to build the enabled-agents whitelist: list the projects
this webapp's identity can see, then list the agents inside a chosen project (the
LLMs whose id starts with ``agent:``, per the DSS Agents API).

Instance safety — this module is STRICTLY READ-ONLY: only listing calls
(``list_project_keys`` / ``get_project`` / ``list_llms``), never create/modify/
delete. Calls are made ON DEMAND (one project at a time, only while an admin is
configuring) and the results are bounded, so a handler can never trigger heavy or
unbounded work against the instance.
"""

import logging

import dataiku

logger = logging.getLogger(__name__)

# A DSS LLM is an agent when its id starts with this prefix, e.g. "agent:rNTZ781a".
AGENT_ID_PREFIX = "agent:"

# Defensive upper bounds: a listing can never return an unbounded payload, however
# many projects/LLMs the instance happens to expose.
MAX_PROJECTS = 500
MAX_AGENTS = 200


def _client():
    """Fresh DSS API client (same handle used for identity); lightweight per call."""
    return dataiku.api_client()


def list_project_keys():
    """Return the project keys this webapp's identity can see (sorted, bounded).

    Reflects the running identity's permissions: only projects it may access are
    listed. Read-only.
    """
    keys = _client().list_project_keys() or []
    keys = sorted(str(k) for k in keys)[:MAX_PROJECTS]
    logger.info("list_project_keys — %d project(s) visible", len(keys))
    return keys


def list_project_agents(project_key):
    """Return ``[{agent_id, description}]`` for the agents in one project.

    Filters ``list_llms()`` to ids starting with ``agent:`` (DSS Agents API).
    Read-only and bounded by MAX_AGENTS. The caller is expected to have already
    checked that ``project_key`` is visible (see ``list_project_keys``).
    """
    project = _client().get_project(project_key)
    agents = []
    for llm in project.list_llms() or []:
        llm_id = getattr(llm, "id", None)
        if not llm_id or not str(llm_id).startswith(AGENT_ID_PREFIX):
            continue
        agents.append(
            {
                "agent_id": llm_id,
                # description is the human-friendly label; fall back to the id.
                "description": getattr(llm, "description", None) or llm_id,
            }
        )
        if len(agents) >= MAX_AGENTS:
            logger.warning(
                "list_project_agents — project=%s hit MAX_AGENTS=%d; list truncated",
                project_key,
                MAX_AGENTS,
            )
            break
    logger.info(
        "list_project_agents — project=%s found %d agent(s)", project_key, len(agents)
    )
    return agents
