"""Phase 0 capability probes: resolve the two undocumented schemas on THIS instance.

READ probes (run_read_probes) are strictly read-only and always safe:
- check the server exposes the client methods the factory needs,
- dump the KEY LAYOUT (never the content) of a live Code Agent's raw settings
  to locate the source-code and code-env keys inside pythonAgentSettings,
- read the live Semantic Model Query tool's type string + params (the discovery
  the tool_builder clones),
- sanity-check the project library, wiki and semantic-models API.

WRITE probes (run_write_probes) are OFF by default and require allow=True:
they create ONE throwaway PYTHON_AGENT ("zz_factory_probe") and ONE throwaway
tool clone, verify the round-trip (inject trivial code, re-read it), then
DELETE those two probe objects. That is the only deletion in the whole factory
and it only ever targets the objects the probe itself just created.

The outputs feed the factory gates:
- results["suggested_schema_hints"]  -> agent_builder.create_code_agent
- results["suggested_discovery"]     -> tool_builder.create_semantic_query_tool_like
"""

import json

from . import hub as hub_module
from . import tool_builder

_PROBE_AGENT_NAME = "zz_factory_probe"
_PROBE_TOOL_NAME = "zz_factory_probe_tool"

def _delete_probe_object(handle, expected_name, getter):
    """Delete a probe object ONLY after re-reading its name and matching it
    against the probe constant (defense in depth around the factory's single
    deletion site: a wrong handle must never delete a real object)."""
    live_name = None
    try:
        live_name = getter()
    except Exception:
        pass
    if live_name is not None and live_name != expected_name:
        raise RuntimeError("refusing to delete %r: expected probe object %r"
                           % (live_name, expected_name))
    handle.delete()


_PROBE_AGENT_CODE = (
    "# Throwaway factory probe agent: never deployed, deleted by the probe itself.\n"
    "from dataiku.llm.python import BaseLLM\n\n\n"
    "class MyLLM(BaseLLM):\n"
    "    def process(self, query, settings, trace):\n"
    "        return {\"text\": \"probe\"}\n")


# ------------------------------------------------------------------ inspection

def _walk_strings(obj, path=""):
    """Yield (path, value) for every string leaf of a nested dict/list."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            for item in _walk_strings(value, "%s.%s" % (path, key) if path else str(key)):
                yield item
    elif isinstance(obj, list):
        for index, value in enumerate(obj):
            for item in _walk_strings(value, "%s[%d]" % (path, index)):
                yield item
    elif isinstance(obj, str):
        yield (path, obj)


def _key_layout(obj, depth=0, max_depth=3):
    """Types-only view of a nested dict (safe to print: no values)."""
    if depth >= max_depth:
        return type(obj).__name__
    if isinstance(obj, dict):
        return {k: _key_layout(v, depth + 1, max_depth) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_key_layout(obj[0], depth + 1, max_depth)] if obj else []
    return type(obj).__name__


def _find_code_candidates(version_dict):
    """Locate string leaves that look like the agent's Python source."""
    candidates = []
    for path, value in _walk_strings(version_dict):
        if len(value) > 300 and ("def process" in value or "BaseLLM" in value
                                 or "import " in value):
            candidates.append({"path": path, "length": len(value),
                               "looks_like_python": "def " in value})
    return candidates


def _find_env_candidates(version_dict):
    """Locate keys that look like the code-env selection."""
    candidates = []

    def walk(obj, path=""):
        if isinstance(obj, dict):
            for key, value in obj.items():
                sub_path = "%s.%s" % (path, key) if path else str(key)
                if "env" in key.lower():
                    candidates.append({"path": sub_path,
                                       "value": value if isinstance(value, (str, dict)) else str(value)})
                walk(value, sub_path)
        elif isinstance(obj, list):
            for index, value in enumerate(obj):
                walk(value, "%s[%d]" % (path, index))

    walk(version_dict)
    return candidates


# ------------------------------------------------------------------ read probes

def run_read_probes(project):
    """Strictly read-only capability probe. Returns a JSON-safe results dict."""
    results = {"project_key": getattr(project, "project_key", "?"),
               "errors": [], "warnings": []}
    settings = hub_module.get_settings(project)
    results["settings_used"] = {k: settings.get(k) for k in
                                ("orchestrator_agent_id", "template_semantic_tool_id",
                                 "template_semantic_model_id", "sql_connection", "code_env_311")}

    # 1. Does this server's client expose the factory's methods?
    methods = ["create_agent", "list_agents", "get_agent", "new_agent_tool",
               "list_agent_tools", "get_agent_tool", "create_semantic_model",
               "get_semantic_model", "list_semantic_models", "new_managed_dataset",
               "new_recipe", "create_scenario", "init_tables_import",
               "create_llm_interaction_logging_dataset", "get_library", "get_wiki"]
    results["client_methods"] = {name: hasattr(project, name) for name in methods}

    # 2. Existing agents (ids + names + types).
    try:
        agents = []
        for item in project.list_agents():
            agents.append({"id": getattr(item, "id", None) or item.get("id"),
                           "name": getattr(item, "name", None) or item.get("name")})
        results["agents"] = agents
    except Exception as exc:
        results["agents"] = []
        results["errors"].append("list_agents failed: %s" % exc)

    # 3. THE key question: layout of a live Code Agent's raw settings.
    orchestrator_id = settings.get("orchestrator_agent_id")
    try:
        agent = project.get_agent(orchestrator_id)
        raw = agent.get_settings().get_raw()
        results["agent_raw_top_keys"] = sorted(raw.keys())
        versions = raw.get("versions") or []
        results["agent_versions_count"] = len(versions)
        if versions:
            version = versions[-1]
            for candidate in versions:
                if candidate.get("versionId") == raw.get("activeVersion"):
                    version = candidate
                    break
            results["agent_version_keys"] = sorted(version.keys())
            internal = version.get("pythonAgentSettings")
            results["python_agent_settings_present"] = internal is not None
            if isinstance(internal, dict):
                results["python_agent_settings_layout"] = _key_layout(internal)
                results["candidate_code_keys"] = _find_code_candidates(internal)
                results["candidate_env_keys"] = _find_env_candidates(internal)
            else:
                # Search the whole version if the expected key is absent.
                results["candidate_code_keys"] = _find_code_candidates(version)
                results["candidate_env_keys"] = _find_env_candidates(version)
    except Exception as exc:
        results["errors"].append("agent raw settings probe failed (%s): %s"
                                 % (orchestrator_id, exc))

    # Suggested schema_hints for agent_builder (needs human/write-probe confirmation).
    hints = None
    code_candidates = results.get("candidate_code_keys") or []
    if results.get("python_agent_settings_present") and len(code_candidates) >= 1:
        best = sorted(code_candidates, key=lambda c: -c["length"])[0]
        if "." not in best["path"] and "[" not in best["path"]:
            env_template = {}
            for env in results.get("candidate_env_keys") or []:
                if "." not in env["path"] and isinstance(env.get("value"), (str, dict)):
                    env_template[env["path"]] = env["value"]
            hints = {"internal_key": "pythonAgentSettings",
                     "code_key": best["path"],
                     "env_template": env_template or None,
                     "confirmed": False}
    results["suggested_schema_hints"] = hints

    # 4. Semantic Model Query tool discovery (type string + params).
    template_tool_id = settings.get("template_semantic_tool_id")
    try:
        discovery = tool_builder.build_discovery(project, template_tool_id,
                                                 settings.get("template_semantic_model_id"))
        results["suggested_discovery"] = discovery
        if discovery is None:
            results["warnings"].append("template tool %s not found in list_agent_tools"
                                       % template_tool_id)
    except Exception as exc:
        results["suggested_discovery"] = None
        results["errors"].append("tool discovery failed (%s): %s" % (template_tool_id, exc))

    # 5. Semantic models API.
    try:
        models = []
        for item in project.list_semantic_models():
            models.append({"id": getattr(item, "id", None), "name": getattr(item, "name", None)})
        results["semantic_models"] = models
    except Exception as exc:
        results["semantic_models"] = []
        results["errors"].append("list_semantic_models failed: %s" % exc)

    # 6. Library / wiki / hub.
    try:
        results["library_ok"] = project.get_library() is not None
        results["hub_capabilities_present"] = hub_module.read_text(
            project, hub_module.CAPABILITIES_PATH) is not None
        results["hub_template_present"] = hub_module.read_text(
            project, hub_module.TEMPLATE_AGENT_PATH) is not None
    except Exception as exc:
        results["library_ok"] = False
        results["errors"].append("library probe failed: %s" % exc)

    if not settings.get("code_env_311"):
        results["warnings"].append(
            "factory_settings.json code_env_311 is empty: fill it with the exact "
            "name of the Python 3.11 code env before creating agents/recipes")
    return results


# ----------------------------------------------------------------- write probes

def run_write_probes(project, results, allow=False):
    """Round-trip confirmation of the undocumented schemas. GATED by allow=True.

    Creates then DELETES zz_factory_probe (agent) and zz_factory_probe_tool.
    Updates results in place: schema_hints/discovery get "confirmed": True when
    the round-trip worked.
    """
    if not allow:
        results.setdefault("warnings", []).append(
            "write probes skipped (allow=False): schema hints remain UNCONFIRMED")
        return results
    log = results.setdefault("write_probe_log", [])

    # --- agent round-trip -----------------------------------------------------
    hints = results.get("suggested_schema_hints")
    if hints:
        agent = None
        try:
            agent = project.create_agent(_PROBE_AGENT_NAME, "PYTHON_AGENT")
            log.append("created probe agent %s" % agent.id)
            settings = agent.get_settings()
            raw = settings.get_raw()
            versions = raw.get("versions") or []
            version = versions[-1] if versions else None
            if version is None:
                raise RuntimeError("probe agent has no version")
            internal = version.setdefault(hints["internal_key"], {})
            internal[hints["code_key"]] = _PROBE_AGENT_CODE
            settings.save()
            # Re-read to verify the code survived the round-trip.
            raw2 = project.get_agent(agent.id).get_settings().get_raw()
            version2 = (raw2.get("versions") or [{}])[-1]
            stored = (version2.get(hints["internal_key"]) or {}).get(hints["code_key"], "")
            if "BaseLLM" in stored:
                hints["confirmed"] = True
                log.append("code injection round-trip CONFIRMED (key %s.%s)"
                           % (hints["internal_key"], hints["code_key"]))
            else:
                log.append("code injection round-trip FAILED: stored value does not "
                           "contain the probe code")
        except Exception as exc:
            log.append("agent write probe failed: %s" % exc)
        finally:
            try:
                if agent is not None:
                    _delete_probe_object(
                        agent, _PROBE_AGENT_NAME,
                        lambda: (agent.get_settings().get_raw() or {}).get("name"))
                    log.append("probe agent deleted")
            except Exception as exc:
                log.append("PROBE CLEANUP FAILED: delete agent %s by hand (%s)"
                           % (_PROBE_AGENT_NAME, exc))
    else:
        log.append("no schema hints suggested: agent write probe skipped")

    # --- tool round-trip --------------------------------------------------------
    discovery = results.get("suggested_discovery")
    if discovery and discovery.get("type"):
        tool = None
        try:
            creator = project.new_agent_tool(discovery["type"], name=_PROBE_TOOL_NAME)
            tool = creator.create()
            log.append("created probe tool %s (type %s)" % (tool.id, discovery["type"]))
            settings = tool.get_settings()
            params = settings.params
            if isinstance(params, dict):
                params.clear()
                params.update(json.loads(json.dumps(discovery["params_template"])))
                settings.save()
                raw2 = project.get_agent_tool(tool.id).get_settings().get_raw()
                stored = raw2.get("params") if isinstance(raw2, dict) else None
                if stored:
                    discovery["confirmed"] = True
                    log.append("tool params round-trip CONFIRMED")
                else:
                    log.append("tool params round-trip FAILED: params came back empty")
        except Exception as exc:
            log.append("tool write probe failed: %s" % exc)
        finally:
            try:
                if tool is not None:
                    _delete_probe_object(
                        tool, _PROBE_TOOL_NAME,
                        lambda: (tool.get_settings().get_raw() or {}).get("name"))
                    log.append("probe tool deleted")
            except Exception as exc:
                log.append("PROBE CLEANUP FAILED: delete tool %s by hand (%s)"
                           % (_PROBE_TOOL_NAME, exc))
    else:
        log.append("no tool discovery available: tool write probe skipped")
    return results


# --------------------------------------------------------------------- reporting

def format_probe_report(results):
    """Markdown report to paste back into the repo (CAPABILITY_MATRIX.md)."""
    lines = ["# Phase 0 probe report", ""]
    lines.append("Project: `%s`" % results.get("project_key"))
    lines.append("")
    lines.append("## Client methods on this instance")
    for name, present in sorted((results.get("client_methods") or {}).items()):
        lines.append("- `%s` : %s" % (name, "YES" if present else "**MISSING**"))
    lines.append("")
    lines.append("## Code Agent raw layout")
    lines.append("- versions: %s ; version keys: %s"
                 % (results.get("agent_versions_count"), results.get("agent_version_keys")))
    lines.append("- pythonAgentSettings present: %s" % results.get("python_agent_settings_present"))
    for c in results.get("candidate_code_keys") or []:
        lines.append("- candidate CODE key: `%s` (len %d, python-like %s)"
                     % (c["path"], c["length"], c["looks_like_python"]))
    for c in results.get("candidate_env_keys") or []:
        lines.append("- candidate ENV key: `%s` = %s" % (c["path"], json.dumps(c["value"])[:120]))
    hints = results.get("suggested_schema_hints")
    lines.append("- suggested schema_hints: `%s`" % json.dumps(hints)[:300])
    lines.append("")
    lines.append("## Semantic Model Query tool discovery")
    discovery = results.get("suggested_discovery")
    if discovery:
        lines.append("- type string: `%s` ; confirmed: %s" % (discovery.get("type"),
                                                              discovery.get("confirmed", False)))
        lines.append("- params template:")
        lines.append("```json")
        lines.append(json.dumps(discovery.get("params_template"), indent=1, ensure_ascii=False)[:3000])
        lines.append("```")
    else:
        lines.append("- NOT AVAILABLE (see errors)")
    lines.append("")
    lines.append("## Hub / library")
    lines.append("- library ok: %s ; capabilities.json present: %s ; engine template present: %s"
                 % (results.get("library_ok"), results.get("hub_capabilities_present"),
                    results.get("hub_template_present")))
    lines.append("")
    lines.append("## Semantic models in the project")
    for m in results.get("semantic_models") or []:
        lines.append("- `%s` %s" % (m.get("id"), m.get("name")))
    if results.get("write_probe_log"):
        lines.append("")
        lines.append("## Write probe log")
        for entry in results["write_probe_log"]:
            lines.append("- %s" % entry)
    if results.get("warnings"):
        lines.append("")
        lines.append("## Warnings")
        for w in results["warnings"]:
            lines.append("- %s" % w)
    if results.get("errors"):
        lines.append("")
        lines.append("## Errors")
        for e in results["errors"]:
            lines.append("- %s" % e)
    return "\n".join(lines)
