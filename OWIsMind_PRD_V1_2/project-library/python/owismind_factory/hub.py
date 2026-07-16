"""Config & Prompt Hub: the /owismind_hub/ tree in the DSS project library.

The hub is the single editable home of everything the agents load at startup
(prompt overrides, the runtime CAPABILITIES registry) and everything the factory
needs at build time (settings, templates, generated files). It lives in the
PROJECT LIBRARY because that is the one store that is editable in the DSS UI,
git-friendly (DSS library git integration), and readable through the public API
from every runtime (Code Agents on 3.11, webapp backend on 3.9) WITHOUT any
import, which preserves the standalone-agent-file rule.

Layout:
    /owismind_hub/
        factory_settings.json     instance knobs (sql connection, 3.11 code env,
                                  LLM ids, template object ids)
        capabilities.json         runtime CAPABILITIES override (orchestrator)
        prompts/orchestrator_persona.md
        prompts/<domain>/understand_extra.md
        templates/dataset_expert.py     sub-agent engine template
        generated/<Agent>.py            factory output awaiting manual paste
        backups/capabilities-<n>.json   automatic backup before every write

Every write here is a design-time action performed by the factory (notebook or
console webapp); agents only READ.
"""

import json
import threading

HUB_ROOT = "/owismind_hub"

# Serializes capabilities read-modify-write cycles within one Python process
# (the console webapp runs all jobs in one process, so this closes its lost
# update window). Cross-process writers (a notebook racing the console) remain
# unsynchronized: the automatic backup is the recovery path for that rare case.
# RLock: append_capability holds it across its read-modify-write and then calls
# write_capabilities, which re-acquires it.
_CAPABILITIES_WRITE_LOCK = threading.RLock()
SETTINGS_PATH = HUB_ROOT + "/factory_settings.json"
CAPABILITIES_PATH = HUB_ROOT + "/capabilities.json"
PERSONA_PATH = HUB_ROOT + "/prompts/orchestrator_persona.md"
TEMPLATE_AGENT_PATH = HUB_ROOT + "/templates/dataset_expert.py"

# Default instance knobs. factory_settings.json overrides them; keeping the
# defaults here means a fresh hub works on the OWIsMind instance out of the box.
DEFAULT_SETTINGS = {
    # SQL connection that hosts the base + knowledge datasets (value_index MUST
    # live on the source SQL connection so the sub-agent can ground by live SQL).
    "sql_connection": "SQL_owi",
    # Name of the Python 3.11 code env used by Code Agents and, if desired, the
    # knowledge recipes. Instance-specific: CONFIRM IT in DSS before first run
    # (Administration > Code Envs). Empty string = inherit project default.
    "code_env_311": "",
    # LLM Mesh ids (mirror the agents' CONFIG). Used by the wizard and doctor.
    "llm_sonnet": "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6",
    # Existing objects used as living templates (duplicate-and-modify strategy).
    "template_semantic_model_id": "AHUh9hb",
    "template_semantic_tool_id": "v4oqA6R",
    "template_zone_recipes": {
        "profile": "compute_DRIVE_Revenues_profile",
        "value_index": "compute_DRIVE_Revenues_value_index",
        "value_catalog": "compute_DRIVE_Revenues_Value_Catalog",
    },
    # Orchestrator agent id (for probes and doctor).
    "orchestrator_agent_id": "038G7mlF",
}


# ---------------------------------------------------------------------- low level

def _library(project):
    return project.get_library()


def _ensure_folder(library, path):
    """Walk/create the folder chain for ``path`` (e.g. '/owismind_hub/prompts')."""
    parts = [p for p in path.split("/") if p]
    folder = library.root if hasattr(library, "root") else library.get_folder("/")
    walked = ""
    for part in parts:
        walked += "/" + part
        nxt = library.get_folder(walked)
        if nxt is None:
            nxt = folder.add_folder(part)
        folder = nxt
    return folder


def read_text(project, path):
    """Return the text content of a library file, or None if absent/unreadable."""
    try:
        f = _library(project).get_file(path)
        if f is None:
            return None
        return f.read()
    except Exception:
        return None


def write_text(project, path, content):
    """Create or update a library text file (folders created as needed)."""
    library = _library(project)
    f = library.get_file(path)
    if f is None:
        folder_path, _, file_name = path.rpartition("/")
        folder = _ensure_folder(library, folder_path or "/")
        f = folder.add_file(file_name)
    f.write(content)
    return path


def read_json(project, path):
    raw = read_text(project, path)
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def write_json(project, path, obj):
    return write_text(project, path, json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=False))


# ---------------------------------------------------------------------- settings

def get_settings(project):
    """DEFAULT_SETTINGS overlaid with /owismind_hub/factory_settings.json."""
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    override = read_json(project, SETTINGS_PATH)
    if isinstance(override, dict):
        for key, value in override.items():
            merged[key] = value
    return merged


# ------------------------------------------------------------------ capabilities

# Keys every capability entry must carry. MUST stay aligned with the embedded
# CAPABILITIES entries in agents/OWIsMind_orchestrator.py (anti-drift test
# tests/test_factory_registry.py compares both).
REQUIRED_CAPABILITY_KEYS = (
    "kind", "agent_id", "domain", "label_fr", "label_en", "tool_name",
    "planner_description", "block_labels", "tool_labels",
    "dataset_label_fr", "dataset_label_en", "source_url",
    "lookup_dataset", "lookup_catalog", "lookup_search_columns",
    "pass_context", "enabled",
)


def validate_capabilities(obj):
    """Validate a full capabilities mapping. Returns a list of problems (empty = valid).

    The SAME semantic checks are duplicated inside the orchestrator's hub loader
    (standalone file rule). The two validators must give the same verdict on the
    same input, otherwise the console/factory would happily write a file the
    orchestrator then silently rejects at load time: the equivalence is enforced
    by tests/test_factory_registry.py (TestValidatorsAgree), which executes the
    orchestrator's real validator side by side with this one.
    """
    from .registry import KNOWN_BLOCK_IDS, KNOWN_TOOL_NAMES

    problems = []
    if not isinstance(obj, dict) or not obj:
        return ["capabilities must be a non-empty JSON object"]
    enabled_domains = []
    for key, cap in obj.items():
        if not isinstance(cap, dict):
            problems.append("%s: entry must be an object" % key)
            continue
        for req in REQUIRED_CAPABILITY_KEYS:
            if req not in cap:
                problems.append("%s: missing key %r" % (key, req))
        if cap.get("kind") == "agent":
            agent_id = str(cap.get("agent_id") or "")
            if not agent_id.startswith("agent:"):
                problems.append("%s: agent_id must start with 'agent:', got %r" % (key, agent_id))
            elif not agent_id.split(":", 1)[1].isalnum():
                # Rejects placeholders (FILL_ME and friends) and empty suffixes:
                # real DSS agent ids are alphanumeric.
                problems.append("%s: agent_id %r is not a real DSS id "
                                "(expected agent:<alphanumeric>)" % (key, agent_id))
            if cap.get("enabled"):
                domain = cap.get("domain")
                if domain in enabled_domains:
                    problems.append("%s: domain %r already has an enabled capability "
                                    "(one enabled capability per domain)" % (key, domain))
                enabled_domains.append(domain)
            # The frozen sub-agent dialect: the timeline labels must cover exactly
            # the KNOWN block ids / tool names (same rule as the orchestrator).
            block_labels = cap.get("block_labels")
            if not isinstance(block_labels, dict) \
                    or set(block_labels.keys()) != set(KNOWN_BLOCK_IDS):
                problems.append("%s: block_labels must be an object with exactly the keys %s"
                                % (key, list(KNOWN_BLOCK_IDS)))
            tool_labels = cap.get("tool_labels")
            if not isinstance(tool_labels, dict) \
                    or set(tool_labels.keys()) != set(KNOWN_TOOL_NAMES):
                problems.append("%s: tool_labels must be an object with exactly the keys %s"
                                % (key, list(KNOWN_TOOL_NAMES)))
        else:
            for label_key in ("block_labels", "tool_labels"):
                labels = cap.get(label_key)
                if labels is not None and not isinstance(labels, dict):
                    problems.append("%s: %s must be an object" % (key, label_key))
    return problems


def read_capabilities(project):
    return read_json(project, CAPABILITIES_PATH)


def write_capabilities(project, capabilities, backup=True):
    """Validate then write capabilities.json, backing up the previous version."""
    problems = validate_capabilities(capabilities)
    if problems:
        raise ValueError("invalid capabilities: " + "; ".join(problems))
    with _CAPABILITIES_WRITE_LOCK:
        if backup:
            current = read_text(project, CAPABILITIES_PATH)
            if current is not None:
                index = 1
                while read_text(project, "%s/backups/capabilities-%d.json" % (HUB_ROOT, index)) is not None:
                    index += 1
                    if index > 200:  # bounded: never loop forever on a weird tree
                        break
                write_text(project, "%s/backups/capabilities-%d.json" % (HUB_ROOT, index), current)
        return write_json(project, CAPABILITIES_PATH, capabilities)


def write_prompt(project, path, content, backup=True):
    """Write a hub prompt file, backing up the previous version first.

    Same recovery contract as write_capabilities: the last versions of an
    overwritten prompt survive under /owismind_hub/backups/.
    """
    if backup:
        current = read_text(project, path)
        if current is not None:
            rel = path[len(HUB_ROOT) + 1:] if path.startswith(HUB_ROOT + "/") else path.lstrip("/")
            name = rel.replace("/", "-")
            index = 1
            while read_text(project, "%s/backups/%s-%d" % (HUB_ROOT, name, index)) is not None:
                index += 1
                if index > 200:  # bounded: never loop forever on a weird tree
                    break
            write_text(project, "%s/backups/%s-%d" % (HUB_ROOT, name, index), current)
    return write_text(project, path, content)


def append_capability(project, key, entry):
    """Add or replace one capability entry (validated as a whole).

    The read-modify-write cycle holds the same lock as write_capabilities so two
    concurrent in-process appends (console jobs) cannot drop each other's entry.
    """
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project) or {}
        capabilities[key] = entry
        write_capabilities(project, capabilities)
    return capabilities
