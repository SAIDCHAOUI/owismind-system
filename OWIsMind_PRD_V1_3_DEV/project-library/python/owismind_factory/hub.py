"""Config & Prompt Hub: the /python/owismind_hub/ tree in the DSS project library.

The hub is the single editable home of everything the agents load at startup
(prompt overrides, the runtime CAPABILITIES registry) and everything the factory
needs at build time (settings, templates, generated files). It lives in the
PROJECT LIBRARY because that is the one store that is editable in the DSS UI,
git-friendly (DSS library git integration), and readable through the public API
from every runtime (Code Agents on 3.11, webapp backend on 3.9) WITHOUT any
import, which preserves the standalone-agent-file rule.

Layout:
    /python/owismind_hub/
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
import re
import threading

HUB_ROOT = "/python/owismind_hub"

# Capability registry caps, enforced at the SINGLE write point
# (write_capabilities); the console route relays the same constants so its 400
# stays readable. A write that SHRINKS an already-oversized registry always
# passes, so disable / remove / cleanup can still recover it.
CAPABILITIES_MAX_ENTRIES = 50
CAPABILITIES_MAX_BYTES = 200 * 1024

# Same shapes as spec._DOMAIN_RE / spec._DATASET_RE, duplicated here because the
# orchestrator's standalone hub loader mirrors this validator verbatim (no
# cross-import allowed in a Code Agent file).
_DOMAIN_FORM_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
_DATASET_FORM_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")


def safe_hub_path(path):
    """Fail-closed gate for every hub WRITE/DELETE path; returns the path.

    These are VIRTUAL DSS library paths, so never os.path (which could resolve
    '..'): reject any traversal or separator trick ('..', '//', a backslash)
    and require the hub prefix, so a crafted path can never escape the hub
    subtree even if the library API resolves '..'. The console's prompt-path
    gate delegates here and adds its narrower prompts/ prefix.
    """
    if not isinstance(path, str) or not path.startswith(HUB_ROOT + "/"):
        raise ValueError("path %r is outside the hub subtree %s" % (path, HUB_ROOT))
    if ".." in path or "//" in path or "\\" in path:
        raise ValueError("path %r contains a forbidden segment" % (path,))
    return path

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
MODELS_PATH = HUB_ROOT + "/models.json"

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
    # LLM ids live in models.json ONLY (see the "models" section below).
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
    """Walk/create the folder chain for ``path`` (e.g. '/python/owismind_hub/prompts')."""
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
    """Create or update a library text file (folders created as needed).

    Fail-closed on any path outside the hub subtree (every legitimate caller
    writes under HUB_ROOT; symmetric with delete_path, defense in depth).
    """
    safe_hub_path(path)
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
    """DEFAULT_SETTINGS overlaid with /python/owismind_hub/factory_settings.json.

    The overlay is STRICT: only keys declared in DEFAULT_SETTINGS may be
    overridden. An unknown key in the hub file is ignored, so a stray or
    injected entry can never ride through here and get republished (the
    console's /api/state exposes this dict verbatim).
    """
    merged = json.loads(json.dumps(DEFAULT_SETTINGS))
    override = read_json(project, SETTINGS_PATH)
    if isinstance(override, dict):
        for key, value in override.items():
            if key in DEFAULT_SETTINGS:
                merged[key] = value
    return merged


# ---------------------------------------------------------------------- models
# ONE file, /python/owismind_hub/models.json, is the ONLY source of every LLM Mesh
# id used by OWIsMind: the model of each mode (smart / pro / claude) for the agents,
# optional per-agent overrides, and the models the factory itself uses. Nothing is
# embedded anywhere else and nothing falls back: agents, the native engine, the
# factory and the Flow recipes all read this file and stop with an explicit error
# when it is missing or invalid (user decision 2026-10-15). Agents re-read it
# every few seconds, so a save from the console applies without a restart.
#
# Resolution order for agent A in mode M:  agents[A][M]  >  modes[M]  >  error.

MODEL_MODES = ("smart", "pro", "claude")
# The orchestrator's key in "agents"; a sub-agent's key is its domain.
ORCHESTRATOR_KEY = "orchestrator"
# factory.default: wizard, Improve review, prompt writer, doctor.
# factory.wizard: optional dedicated model for the wizard ("" = default).
# factory.profile_enrich: LLM pass of the profile recipes ("" = skip that pass).
FACTORY_PURPOSES = ("default", "wizard", "profile_enrich")
_LLM_ID_RE = re.compile(r"^[A-Za-z0-9_.:/@+\-]{3,200}$")
_AGENT_KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
MODELS_MAX_AGENTS = 50
MODELS_MAX_BYTES = 20000
MODELS_TOP_KEYS = ("version", "modes", "agents", "factory")


def valid_llm_id(value):
    return isinstance(value, str) and bool(_LLM_ID_RE.match(value))


def validate_models(obj):
    """Validate a full models mapping. Returns a list of problems (empty = valid).

    The agents' standalone loader applies the same shape rules per entry (an
    invalid entry is skipped there instead of rejecting the file).
    """
    problems = []
    if not isinstance(obj, dict):
        return ["models must be an object"]
    for key in obj:
        if key not in MODELS_TOP_KEYS:
            problems.append("unknown key %r (allowed: %s)" % (key, ", ".join(sorted(MODELS_TOP_KEYS))))
    if len(json.dumps(obj, ensure_ascii=False)) > MODELS_MAX_BYTES:
        problems.append("models file too large (max %d characters)" % MODELS_MAX_BYTES)
    modes = obj.get("modes")
    if not isinstance(modes, dict):
        problems.append("modes must be an object")
    else:
        for mode in MODEL_MODES:
            if not valid_llm_id(modes.get(mode)):
                problems.append("modes.%s must be a valid LLM id" % mode)
        for mode in modes:
            if mode not in MODEL_MODES:
                problems.append("modes.%s is not a known mode" % mode)
    agents = obj.get("agents", {})
    if not isinstance(agents, dict):
        problems.append("agents must be an object")
    else:
        if len(agents) > MODELS_MAX_AGENTS:
            problems.append("too many agents (max %d)" % MODELS_MAX_AGENTS)
        for key, per_mode in agents.items():
            if key != ORCHESTRATOR_KEY and not _AGENT_KEY_RE.match(str(key)):
                problems.append("agents key %r is not a valid agent key" % (key,))
                continue
            if not isinstance(per_mode, dict):
                problems.append("agents.%s must be an object" % key)
                continue
            for mode, llm in per_mode.items():
                if mode not in MODEL_MODES:
                    problems.append("agents.%s.%s is not a known mode" % (key, mode))
                elif not valid_llm_id(llm):
                    problems.append("agents.%s.%s must be a valid LLM id" % (key, mode))
    factory = obj.get("factory", {})
    if not isinstance(factory, dict):
        problems.append("factory must be an object")
    else:
        for name in factory:
            if name not in FACTORY_PURPOSES:
                problems.append("factory.%s is not a known purpose" % name)
        for name in FACTORY_PURPOSES:
            value = factory.get(name, "")
            if value not in ("", None) and not valid_llm_id(value):
                problems.append("factory.%s must be empty or a valid LLM id" % name)
        if not valid_llm_id(factory.get("default")):
            problems.append("factory.default must be a valid LLM id")
    return problems


def read_models(project):
    """The stored models.json, or None when absent / unreadable / invalid."""
    obj = read_json(project, MODELS_PATH)
    if obj is None or validate_models(obj):
        return None
    return obj


def models_problems(project):
    """Why models.json is unusable: [] when valid, else a list of readable problems."""
    raw = read_text(project, MODELS_PATH)
    if raw is None:
        return ["%s is missing: save the models from the console (Settings)" % MODELS_PATH]
    try:
        obj = json.loads(raw)
    except Exception as exc:
        return ["%s is not valid JSON: %s" % (MODELS_PATH, exc)]
    return validate_models(obj)


def empty_models():
    """A blank mapping for the console form when models.json does not exist yet."""
    return {"version": 1, "modes": dict((m, "") for m in MODEL_MODES), "agents": {},
            "factory": dict((p, "") for p in FACTORY_PURPOSES)}


def factory_llm(project, purpose="default"):
    """The factory's own LLM id: factory.<purpose>, else factory.default.

    Raises ValueError when models.json is unusable or has no id for the purpose
    (no embedded fallback). ``purpose`` "profile_enrich" may legitimately be ""
    (skip the LLM pass): callers that accept that use ``factory_llm_or_empty``.
    """
    llm_id = factory_llm_or_empty(project, purpose)
    if not llm_id:
        raise ValueError("%s has no LLM for factory.%s: set it from the console (Settings)"
                         % (MODELS_PATH, purpose))
    return llm_id


def factory_llm_or_empty(project, purpose="default"):
    """factory.<purpose> if set, else factory.default; raises ValueError when the
    file itself is missing or invalid."""
    problems = models_problems(project)
    if problems:
        raise ValueError("; ".join(problems))
    factory = read_models(project).get("factory") or {}
    return factory.get(purpose) or factory.get("default") or ""


def write_models(project, models):
    """Validate then write models.json (previous version backed up first)."""
    problems = validate_models(models)
    if problems:
        raise ValueError("invalid models: " + "; ".join(problems))
    payload = json.dumps(models, indent=2, ensure_ascii=False, sort_keys=False)
    with _CAPABILITIES_WRITE_LOCK:
        current = read_text(project, MODELS_PATH)
        if current is not None:
            pattern = HUB_ROOT + "/backups/models-%d.json"
            write_text(project, pattern % _next_free_index(project, pattern), current)
        return write_text(project, MODELS_PATH, payload)


def effective_models(models, agent_key):
    """Per-mode view for one agent: {mode: {"llm": id or None, "source": ...}}.

    ``models`` is the stored mapping or None. source is "agent" (per-agent
    override), "mode" (central mode model) or "missing" (the agent refuses to run
    in that mode until models.json provides an id).
    """
    stored = models if isinstance(models, dict) else None
    out = {}
    for mode in MODEL_MODES:
        override = ((stored or {}).get("agents") or {}).get(agent_key, {}).get(mode)
        central = ((stored or {}).get("modes") or {}).get(mode)
        if valid_llm_id(override):
            out[mode] = {"llm": override, "source": "agent"}
        elif valid_llm_id(central):
            out[mode] = {"llm": central, "source": "mode"}
        else:
            out[mode] = {"llm": None, "source": "missing"}
    return out


def list_available_llms(project):
    """LLM Mesh models of the project, for the pickers ([] on any failure)."""
    try:
        rows = project.list_llms()
    except Exception:
        return []
    out = []
    for row in rows or []:
        llm_id = row.get("id") if isinstance(row, dict) else getattr(row, "id", None)
        if not valid_llm_id(llm_id):
            continue
        name = (row.get("friendlyName") if isinstance(row, dict)
                else getattr(row, "friendly_name", None)) or llm_id
        kind = (row.get("type") if isinstance(row, dict) else getattr(row, "type", "")) or ""
        out.append({"id": llm_id, "name": str(name), "type": str(kind)})
    return out


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
            # Form gates (defense in depth, mirrored in the orchestrator loader):
            # domain feeds hub paths and lookup_dataset / lookup_catalog feed the
            # removal inventory and end up as SQL identifiers, so exotic shapes
            # are refused at the door (same regexes as spec._DOMAIN_RE /
            # spec._DATASET_RE).
            domain_name = str(cap.get("domain") or "")
            if not _DOMAIN_FORM_RE.match(domain_name):
                problems.append("%s: domain %r is not snake_case "
                                "([a-z][a-z0-9_]{1,30})" % (key, domain_name))
            for field in ("lookup_dataset", "lookup_catalog"):
                value = str(cap.get(field) or "")
                if value and not _DATASET_FORM_RE.match(value):
                    problems.append("%s: %s %r is not a legal dataset name"
                                    % (key, field, value))
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


# Last backup index used per path pattern, per process. Probing restarts from
# max(memo, 1) and STILL walks forward confirming emptiness, so the produced
# names match the historical from-1 probe whenever the tree was not edited
# underneath; a busy console process just stops re-reading every existing
# backup on every write (the probe was O(number of backups) API calls).
# Inter-process writers keep the same contract as before (hub.py header):
# a backup may be overwritten, never the live file.
_BACKUP_INDEX_MEMO = {}


def _next_free_index(project, pattern, cap=200):
    """First free index for ``pattern``, resuming from the memo when valid.

    The memoized index is trusted only if its file STILL exists (stable tree);
    otherwise the probe restarts from 1, producing exactly the historical
    from-1 names on a fresh or hand-edited tree.
    """
    index = _BACKUP_INDEX_MEMO.get(pattern, 0)
    if index < 1 or read_text(project, pattern % index) is None:
        index = 1
    while read_text(project, pattern % index) is not None:
        index += 1
        if index > cap:  # bounded: never loop forever on a weird tree
            break
    _BACKUP_INDEX_MEMO[pattern] = index
    return index


def wizard_config_path(domain):
    """Hub path of a domain's wizard draft: the SINGLE convention shared by the
    guided machine, the console, the removal inventory and notebook 04."""
    return "%s/wizard/%s-config.json" % (HUB_ROOT, domain)


def read_capabilities(project):
    return read_json(project, CAPABILITIES_PATH)


def write_capabilities(project, capabilities, backup=True):
    """Validate then write capabilities.json, backing up the previous version.

    Size caps live HERE (the single write point): a payload beyond
    CAPABILITIES_MAX_ENTRIES / CAPABILITIES_MAX_BYTES is refused with ValueError
    UNLESS it shrinks the registry vs the current file, so recovery writes
    (disable, remove, cleanup) always pass on a registry already out of bounds.
    """
    problems = validate_capabilities(capabilities)
    if problems:
        raise ValueError("invalid capabilities: " + "; ".join(problems))
    payload = json.dumps(capabilities, indent=2, ensure_ascii=False, sort_keys=False)
    payload_bytes = len(payload.encode("utf-8"))
    oversized = (len(capabilities) > CAPABILITIES_MAX_ENTRIES
                 or payload_bytes > CAPABILITIES_MAX_BYTES)
    with _CAPABILITIES_WRITE_LOCK:
        current = read_text(project, CAPABILITIES_PATH)
        if oversized and (current is None or len(payload) >= len(current)):
            raise ValueError(
                "capabilities registry beyond caps (%d entries / %d bytes; caps "
                "%d entries / %d bytes) and the write does not shrink it"
                % (len(capabilities), payload_bytes,
                   CAPABILITIES_MAX_ENTRIES, CAPABILITIES_MAX_BYTES))
        if backup and current is not None:
            pattern = HUB_ROOT + "/backups/capabilities-%d.json"
            write_text(project, pattern % _next_free_index(project, pattern), current)
        return write_text(project, CAPABILITIES_PATH, payload)


def write_prompt(project, path, content, backup=True):
    """Write a hub prompt file, backing up the previous version first.

    Same recovery contract as write_capabilities: the last versions of an
    overwritten prompt survive under /python/owismind_hub/backups/.
    """
    if backup:
        current = read_text(project, path)
        if current is not None:
            rel = path[len(HUB_ROOT) + 1:] if path.startswith(HUB_ROOT + "/") else path.lstrip("/")
            pattern = "%s/backups/%s-%%d" % (HUB_ROOT, rel.replace("/", "-"))
            write_text(project, pattern % _next_free_index(project, pattern), current)
    return write_text(project, path, content)


def append_capability(project, key, entry):
    """Add or replace one capability entry (validated as a whole).

    The read-modify-write cycle holds the same lock as write_capabilities so two
    concurrent in-process appends (console jobs) cannot drop each other's entry.
    """
    from . import guardrails  # local import: guardrails is stdlib-only, avoids any cycle
    if guardrails.has_high(guardrails.scan(json.dumps(entry, ensure_ascii=False))) \
            and not (isinstance(entry, dict) and entry.get("_risks_acknowledged")):
        raise ValueError("suspicious_content: the capability text looks like an injection attempt")
    if isinstance(entry, dict):
        entry = {k: v for k, v in entry.items() if k != "_risks_acknowledged"}
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project) or {}
        capabilities[key] = entry
        write_capabilities(project, capabilities)
    return capabilities


def set_capability_enabled(project, key, enabled):
    """Flip one capability's ``enabled`` flag (validated, backed-up write).

    Raises ``KeyError`` when the key is unknown and ``ValueError`` when the
    resulting registry would be invalid (e.g. two enabled capabilities on the
    same domain): the caller surfaces both as-is.
    """
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project)
        if not isinstance(capabilities, dict) or key not in capabilities:
            raise KeyError(key)
        capabilities[key]["enabled"] = bool(enabled)
        write_capabilities(project, capabilities)
        return capabilities


def remove_capability(project, key):
    """Remove one capability entry. Returns ``(status, capabilities)``.

    status is ``"removed"``, ``"absent"``, or ``"kept_disabled"``: the LAST
    entry is never removed, only disabled, because an empty capabilities.json
    is invalid and would make the orchestrator fall back to its embedded
    defaults (the removed expert could then silently REAPPEAR).
    """
    with _CAPABILITIES_WRITE_LOCK:
        capabilities = read_capabilities(project) or {}
        if key not in capabilities:
            return "absent", capabilities
        if len(capabilities) == 1:
            capabilities[key]["enabled"] = False
            write_capabilities(project, capabilities)
            return "kept_disabled", capabilities
        del capabilities[key]
        write_capabilities(project, capabilities)
        return "removed", capabilities


def path_exists(project, path):
    """True/False when the library file or folder provably exists/does not,
    None when the library itself cannot be read (callers treat None as
    "unknown", never as a verdict)."""
    try:
        library = _library(project)
        if library.get_file(path) is not None:
            return True
        return library.get_folder(path) is not None
    except Exception:
        return None


def delete_path(project, path):
    """Delete a library file or folder. True when something was deleted,
    False when already absent. API refusals raise (caller flips to manual).

    Fail-closed on any path outside the hub subtree: removal hub_paths are built
    from registry-supplied strings, so the gate here guarantees a crafted domain
    or agent name can never turn into a deletion above HUB_ROOT (the raise lands
    in the caller's manual-fallback path, never an impasse).
    """
    safe_hub_path(path)
    library = _library(project)
    f = library.get_file(path)
    if f is not None:
        f.delete()
        return True
    folder = library.get_folder(path)
    if folder is not None:
        folder.delete()
        return True
    return False
