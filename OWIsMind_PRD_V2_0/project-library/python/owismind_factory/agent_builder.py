"""Code Agent generation and creation (creation is GATED: needs Phase 0 hints).

Two independent halves:

1. generate_subagent_code(): PURE text transformation. The dataset-expert engine
   (GenAI/Agents/SalesDrive_revenue_expert.py, uploaded to the hub as
   templates/dataset_expert.py) is dataset-agnostic by design: its whole domain
   binding is the CONFIG header. The generator rewrites exactly those constants
   and refuses to proceed if any expected constant is not found exactly once
   (template drift protection).

2. create_code_agent(): ``project.create_agent(name, "PYTHON_AGENT")`` is
   official client API, but the raw layout of a Code Agent version's settings
   (where the source code and the code env live inside
   ``versions[*].pythonAgentSettings``) is NOT documented. So code injection is
   gated behind ``schema_hints`` produced by the Phase 0 probe from the LIVE
   orchestrator agent. Without hints, the factory writes the generated file to
   the hub (generated/<Agent>.py) and reports the one manual paste step.
"""

import re

from . import hub as hub_module

# CONFIG constants rewritten in the engine template. Each regex must match
# EXACTLY ONCE, else the template has drifted and we stop instead of guessing.
# HUB_DOMAIN is part of the binding (audit 2026-08-05, AG-01a): without it a
# generated expert would load the hub prompts of the REVENUE domain.
_CONFIG_PATTERNS = {
    "PROFILE_DATASET": r'^PROFILE_DATASET = "[^"]*"',
    "VALUE_INDEX_DATASET": r'^VALUE_INDEX_DATASET = "[^"]*"',
    "SEMANTIC_TOOL_ID": r'^SEMANTIC_TOOL_ID = "[^"]*"',
    "SEMANTIC_TOOL_NAME": r'^SEMANTIC_TOOL_NAME = "[^"]*"',
    "HUB_DOMAIN": r'^HUB_DOMAIN = "[^"]*"',
}

# Domain-wording regions of the engine (audit 2026-08-05, AG-01a). The engine
# carries revenue-specific vocabulary (the offer hierarchy) in a handful of
# LLM/user-facing strings, each delimited in the engine source by paired
# markers:
#     # [DOMAIN-WORDING:<key>]
#     ...statement(s) carrying the wording...
#     # [/DOMAIN-WORDING:<key>]
# generate_subagent_code(wording={key: replacement_lines}) swaps a region's
# CONTENT for a new domain; with no override every region is kept verbatim, so
# the mechanism is strictly neutral for the revenue engine itself.
WORDING_KEYS = ("disclose_note", "ambiguous_resolved", "enumerate_guidance",
                "ambiguous_deferred")

# Deploy-header identity lines, rewritten only when the caller provides
# agent_ref (see generate_subagent_code): a regenerated file must not keep the
# revenue agent's name/id in its header (mirror identity, registry.json).
_HEADER_AGENT_RE = re.compile(r"^# Code Agent: .+$", re.MULTILINE)
_HEADER_PROJECT_RE = re.compile(r"^# DEPLOY TARGET: project .+$", re.MULTILINE)


def _replace_wording(code, key, replacement):
    """Swap ONE delimited domain-wording region's content (markers kept)."""
    region_re = re.compile(
        r"([ \t]*# \[DOMAIN-WORDING:%s\]\n)(.*?)([ \t]*# \[/DOMAIN-WORDING:%s\]\n)"
        % (re.escape(key), re.escape(key)), re.S)
    if len(region_re.findall(code)) != 1:
        raise TemplateDriftError(
            "expected exactly one [DOMAIN-WORDING:%s] region in the engine "
            "template: the template drifted, update owismind_factory/"
            "agent_builder.py together with the engine" % key)
    if not replacement.endswith("\n"):
        replacement += "\n"
    return region_re.sub(lambda m: m.group(1) + replacement + m.group(3),
                         code, count=1)


class TemplateDriftError(RuntimeError):
    """The engine template no longer matches the generator's expectations."""


def generate_subagent_code(template_code, spec, tool_id, deploy_project=None,
                           agent_ref=None, wording=None):
    """Rewrite the engine template's CONFIG header for a new domain (pure).

    :param str template_code: full source of the dataset-expert engine.
    :param spec: DomainSpec.
    :param str tool_id: the domain's Semantic Model Query tool id ("" = fill later).
    :param str deploy_project: project key stamped into the deploy banner.
    :param str agent_ref: OPTIONAL "agent:<id>" (or bare id) of the target Code
        Agent. When given, the deploy-header identity lines are rewritten to the
        new domain's name/id; when None the header is left untouched (the
        historical behavior, and neutral for the revenue engine).
    :param dict wording: OPTIONAL {key: replacement_lines} over WORDING_KEYS to
        swap the delimited domain-wording regions (revenue vocabulary) for a new
        domain. None keeps every region verbatim.
    """
    replacements = {
        "PROFILE_DATASET": 'PROFILE_DATASET = "%s"' % spec.profile_dataset,
        "VALUE_INDEX_DATASET": 'VALUE_INDEX_DATASET = "%s"' % spec.value_index_dataset,
        "SEMANTIC_TOOL_ID": 'SEMANTIC_TOOL_ID = "%s"' % (tool_id or "FILL_ME_TOOL_ID"),
        "SEMANTIC_TOOL_NAME": 'SEMANTIC_TOOL_NAME = "%s"' % spec.semantic_tool_name,
        "HUB_DOMAIN": 'HUB_DOMAIN = "%s"' % spec.domain,
    }
    code = template_code
    for key, pattern in _CONFIG_PATTERNS.items():
        matches = re.findall(pattern, code, flags=re.MULTILINE)
        if len(matches) != 1:
            raise TemplateDriftError(
                "expected exactly one %s assignment in the engine template, found %d: "
                "the template drifted, update owismind_factory/agent_builder.py "
                "together with the engine" % (key, len(matches)))
        code = re.sub(pattern, replacements[key].replace("\\", "\\\\"), code,
                      count=1, flags=re.MULTILINE)

    if wording:
        for key in wording:
            if key not in WORDING_KEYS:
                raise ValueError("unknown domain-wording key %r (known: %s)"
                                 % (key, list(WORDING_KEYS)))
        for key, replacement in wording.items():
            code = _replace_wording(code, key, replacement)

    if agent_ref:
        agent_id = agent_ref.split(":", 1)[1] if ":" in agent_ref else agent_ref
        for header_re, line in (
                (_HEADER_AGENT_RE,
                 "# Code Agent: %s = %s" % (spec.agent_name, agent_id)),
                (_HEADER_PROJECT_RE,
                 "# DEPLOY TARGET: project %s"
                 % (deploy_project or "<current project>"))):
            if len(header_re.findall(code)) != 1:
                raise TemplateDriftError(
                    "expected exactly one deploy-header line matching %r: the "
                    "template drifted, update owismind_factory/agent_builder.py "
                    "together with the engine" % header_re.pattern)
            code = header_re.sub(line.replace("\\", "\\\\"), code, count=1)

    banner = (
        "# ============================================================\n"
        "# GENERATED by owismind_factory for domain %r\n"
        "# Engine: dataset_expert template (SalesDrive_revenue_expert engine).\n"
        "# DEPLOY TARGET: project %s / Code Agent %s (env 3.11).\n"
        "# Review the CONFIG block below, then paste into the DSS Code Agent.\n"
        "# ============================================================\n"
        % (spec.domain, deploy_project or "<current project>", spec.agent_name))
    return banner + code


def load_engine_template(project):
    """The engine template text from the hub (uploaded by 01_push_config_hub)."""
    return hub_module.read_text(project, hub_module.TEMPLATE_AGENT_PATH)


# --------------------------------------------------------------------- creation

def read_agent_raw(project, agent_id):
    """Full raw settings of an agent (read-only; the probe's discovery source)."""
    agent = project.get_agent(agent_id)
    settings = agent.get_settings()
    return settings.get_raw()


def resolve_active_version(raw):
    """Version dict whose versionId matches activeVersion, else the last, else None.

    Public: probes, the guided preflight and notebook 01 all need the same
    "active or latest" resolution over an agent's raw settings; callers that
    treat an empty version list as fatal go through ``_resolve_version``.
    """
    versions = raw.get("versions") or []
    active = raw.get("activeVersion")
    for version in versions:
        if version.get("versionId") == active:
            return version
    return versions[-1] if versions else None


def _resolve_version(raw):
    version = resolve_active_version(raw)
    if version is None:
        raise RuntimeError("agent has no versions in its raw settings")
    return version


def agent_exists(project, name):
    """Return the agent id, or None when confirmed absent.

    A listing failure raises ExistenceCheckError (same contract as
    flow_builder): 'absent' must never be concluded from an API error, or a
    rerun during a DSS hiccup would attempt a duplicate agent creation.
    """
    from .flow_builder import ExistenceCheckError
    try:
        for item in project.list_agents():
            item_name = item.name if hasattr(item, "name") else item.get("name")
            if item_name == name:
                return item.id if hasattr(item, "id") else item.get("id")
        return None
    except Exception as exc:
        raise ExistenceCheckError("could not list agents: %s" % exc)


def paste_checklist(spec, generated_path):
    return (
        "Create the Code Agent BY HAND in DSS (one paste): Agents & GenAI Models > "
        "New Agent > Code Agent, name %s, Settings tab: select the Python 3.11 code "
        "env; Code tab: paste the generated file from the project library %s; save. "
        "Then note the agent id (agent:XXXX) into the capability entry."
        % (spec.agent_name, generated_path))


def create_code_agent(ctx, spec, code, schema_hints, code_env=""):
    """Create the Code Agent and inject the generated code (gated).

    :param dict schema_hints: produced by probes.run_read_probes /
        run_write_probes. Expected keys:
        - "internal_key": the per-type settings key (e.g. "pythonAgentSettings"),
        - "code_key": the key holding the Python source inside it,
        - "env_template": optional dict merged into the internal settings to
          select the 3.11 code env (copied from a live agent by the probe).
    Returns "agent:<id>" or None.
    """
    from .flow_builder import ExistenceCheckError
    try:
        existing_id = agent_exists(ctx.project, spec.agent_name)
    except ExistenceCheckError as exc:
        if ctx.dry_run:
            # Planning creates nothing: an unverifiable existence is fine here.
            existing_id = None
        else:
            ctx.fail("code_agent", "existence check failed, NOT creating: %s" % exc)
            return None
    if existing_id:
        ctx.skip("code_agent", "agent %s already exists (id %s)" % (spec.agent_name, existing_id))
        return "agent:%s" % existing_id

    generated_path = "%s/generated/%s.py" % (hub_module.HUB_ROOT, spec.agent_name)

    # The gate is enforced HERE, engine-side, not only by the console: hints must
    # carry the probe keys AND confirmed=True (write-probe round-trip verified).
    # A human can consciously override from a notebook by setting confirmed=True
    # on hints they trust; anything less falls back to the manual paste path.
    gated = (not schema_hints or not schema_hints.get("internal_key")
             or not schema_hints.get("code_key")
             or not schema_hints.get("confirmed"))
    if gated:
        # Fallback: persist the generated code where a human can copy it in one click.
        ctx.act("code_agent_file",
                "write generated agent code to the project library %s" % generated_path,
                lambda: hub_module.write_text(ctx.project, generated_path, code))
        ctx.manual("code_agent",
                   "GATED (the Code Agent raw settings schema is not probe-confirmed). "
                   + paste_checklist(spec, generated_path))
        return None

    def _create():
        agent = ctx.project.create_agent(spec.agent_name, "PYTHON_AGENT")
        settings = agent.get_settings()
        raw = settings.get_raw()
        version = _resolve_version(raw)
        internal = version.get(schema_hints["internal_key"])
        if internal is None:
            internal = {}
            version[schema_hints["internal_key"]] = internal
        internal[schema_hints["code_key"]] = code
        env_template = schema_hints.get("env_template")
        if isinstance(env_template, dict):
            for key, value in env_template.items():
                internal[key] = value
        settings.save()
        # Never wake the agent up automatically (that starts backend compute):
        # the smoke step reports status only.
        return "agent:%s" % agent.id

    result = ctx.act("code_agent",
                     "create Code Agent %s (PYTHON_AGENT) and inject %d chars of "
                     "generated code via probe-confirmed keys %s.%s%s"
                     % (spec.agent_name, len(code), schema_hints["internal_key"],
                        schema_hints["code_key"],
                        ", code env template applied" if schema_hints.get("env_template") else
                        " (code env: set it in the DSS Settings tab, hint not provided)"),
                     _create)
    if result is None and not ctx.dry_run:
        # Creation failed: fall back to the manual paste path so the night's
        # work is still usable.
        ctx.act("code_agent_file",
                "write generated agent code to the project library %s (fallback)" % generated_path,
                lambda: hub_module.write_text(ctx.project, generated_path, code))
        ctx.manual("code_agent", paste_checklist(spec, generated_path))
    return result
