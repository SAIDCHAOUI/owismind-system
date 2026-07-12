"""End-to-end pipeline: one DomainSpec -> the full specialist chain.

Ordered, idempotent, dry-run-able. Steps whose API is probe-gated degrade to
MANUAL actions with exact instructions; nothing is guessed, nothing is deleted,
nothing heavy runs without an explicit human action (the first knowledge build
is a scenario the human triggers).

Typical use (notebook 03_create_domain.py or the console webapp):

    ctx = FactoryContext(dry_run=True)
    spec = DomainSpec(domain="satisfaction", base_dataset="CX_Surveys", ...)
    pipeline.create_domain(ctx, spec)      # review ctx.report_markdown()
    ctx = FactoryContext(dry_run=False)
    pipeline.create_domain(ctx, spec, wizard_config=config,
                           discovery=probe["suggested_discovery"],
                           schema_hints=probe["suggested_schema_hints"])
"""

from . import agent_builder, flow_builder, hub, registry, semantic_builder, tool_builder, wizard

# Ordered step names (the console renders and filters on these).
STEP_NAMES = [
    "source_dataset",
    "zone",
    "knowledge_datasets",
    "recipes",
    "scenario",
    "first_build",
    "semantic_model",
    "semantic_config",
    "semantic_index",
    "semantic_tool",
    "code_agent",
    "capability",
    "smoke",
]


def _enabled(steps, name):
    return steps is None or name in steps


def create_domain(ctx, spec, wizard_config=None, discovery=None, schema_hints=None,
                  steps=None, settings=None):
    """Run (or plan) the whole chain for one domain. Returns ctx.

    :param wizard_config: output of wizard.draft_model_config (may be None: the
        semantic content then stays a curation TODO).
    :param discovery: probe discovery for the Semantic Model Query tool.
    :param schema_hints: probe hints for Code Agent code injection.
    :param steps: optional subset of STEP_NAMES to run.
    :param settings: hub.get_settings override (tests).
    """
    settings = settings or hub.get_settings(ctx.project)
    connection = settings.get("sql_connection") or "SQL_owi"
    code_env = settings.get("code_env_311") or ""

    zone = None
    model_id = None
    tool_id = None
    agent_id = None
    # Prerequisite tracking: when the base dataset could not be secured in a real
    # run, the steps that read it (recipes wiring, model schema) are BLOCKED
    # instead of attempted, so the report never looks better than reality.
    base_ready = True

    if _enabled(steps, "source_dataset"):
        base = flow_builder.ensure_source_dataset(ctx, spec)
        if not ctx.dry_run and base is None:
            base_ready = False

    if _enabled(steps, "zone"):
        zone = flow_builder.ensure_zone(ctx, spec)
        if zone is not None:
            try:
                base = ctx.project.get_dataset(spec.base_dataset)
                flow_builder.share_into_zone(ctx, zone, base, "dataset %s" % spec.base_dataset)
            except Exception:
                pass

    if _enabled(steps, "knowledge_datasets"):
        flow_builder.ensure_knowledge_datasets(ctx, spec, connection, zone=zone)

    if _enabled(steps, "recipes"):
        if base_ready:
            flow_builder.ensure_recipes(ctx, spec, settings.get("template_zone_recipes") or {},
                                        code_env=code_env, zone=zone)
        else:
            ctx.block("recipes", "base dataset %s was not secured: recipes would "
                                 "wire a missing input" % spec.base_dataset)

    if _enabled(steps, "scenario"):
        flow_builder.ensure_refresh_scenario(ctx, spec)

    if _enabled(steps, "first_build"):
        ctx.manual("first_build",
                   "run the scenario %s ONCE by hand (or flow_builder.run_scenario_now) "
                   "off-peak to build %s, then REVIEW the profile dataset before the "
                   "wizard step" % (spec.scenario_name, ", ".join(spec.knowledge_datasets)))

    if _enabled(steps, "semantic_model"):
        if base_ready:
            entity_description = (wizard_config or {}).get("entity_description") or ""
            model_id = semantic_builder.seed_model(ctx, spec, settings,
                                                   entity_description=entity_description)
        else:
            ctx.block("semantic_model", "base dataset %s was not secured: the entity "
                                        "is built from its schema" % spec.base_dataset)

    if _enabled(steps, "semantic_config"):
        if wizard_config and not wizard_config.get("error"):
            working = dict(wizard_config)
            # Offline gate: never push a golden query that is not read-only or that
            # references an invented column into the model. The read-only check
            # ALWAYS runs; only the known-column check degrades when the wizard
            # config carries no attribute columns (manual note).
            known_columns = [a.get("column") for a in (working.get("attributes") or [])
                             if isinstance(a, dict) and a.get("column")]
            verdict = wizard.validate_golden_queries(working, known_columns)
            if verdict["problems"]:
                working["golden_queries"] = verdict["ok"]
                stripped = ["[%d] %s -> %s"
                            % (p["index"], (p["question"] or "?")[:80],
                               "; ".join(p["issues"]))
                            for p in verdict["problems"]]
                ctx.manual("semantic_config_validation",
                           "%d golden query(ies) stripped before apply by the offline "
                           "validator (read-only + known-column check): fix and re-add "
                           "them by hand in the model Playground: %s"
                           % (len(verdict["problems"]), " | ".join(stripped)))
            if not known_columns:
                ctx.manual("semantic_config_validation_columns",
                           "golden query COLUMN check skipped (no attribute columns in "
                           "the wizard config); the read-only check still ran. Review "
                           "the identifiers by hand in the Playground")
            physical = wizard.get_physical_table(ctx.project, spec.base_dataset) if not ctx.dry_run else None
            ready, todo = wizard.substitute_golden_tables(working, physical)
            config = dict(working)
            config["golden_queries"] = ready
            semantic_builder.apply_config(ctx, model_id, config)
            if todo:
                ctx.manual("semantic_config_todo",
                           "%d golden queries need their SQL validated by hand in the "
                           "model Playground: %s"
                           % (len(todo), "; ".join((g.get("question") or "")[:80] for g in todo)))
        else:
            ctx.manual("semantic_config",
                       "no wizard config: describe entities/attributes, metrics, "
                       "instructions and golden queries in the model UI or run the "
                       "wizard (04_semantic_wizard.py / console) then apply_config")

    if _enabled(steps, "semantic_index"):
        semantic_builder.start_indexing(ctx, model_id, wait=True)

    if _enabled(steps, "semantic_tool"):
        description = tool_builder.build_tool_description(spec, wizard_config)
        tool_id = tool_builder.create_semantic_query_tool_like(ctx, spec, model_id,
                                                               discovery, description=description)

    if _enabled(steps, "code_agent"):
        template_code = None if ctx.dry_run else agent_builder.load_engine_template(ctx.project)
        if ctx.dry_run:
            ctx.plan("code_agent", "generate the sub-agent code from the engine template "
                                   "and create Code Agent %s" % spec.agent_name)
        elif not template_code:
            ctx.manual("code_agent",
                       "engine template missing in the hub (%s): run 01_push_config_hub.py "
                       "first, then re-run this step" % hub.TEMPLATE_AGENT_PATH)
        else:
            try:
                code = agent_builder.generate_subagent_code(
                    template_code, spec, tool_id or "",
                    deploy_project=getattr(ctx.project, "project_key", None))
                agent_id = agent_builder.create_code_agent(ctx, spec, code, schema_hints,
                                                           code_env=code_env)
            except agent_builder.TemplateDriftError as exc:
                ctx.fail("code_agent", str(exc))

    if _enabled(steps, "capability"):
        if ctx.dry_run:
            ctx.plan("capability",
                     "append capability %s to the hub capabilities.json (enabled=False "
                     "until the smoke tests pass; agent_id from the code_agent step)"
                     % spec.capability_key)
        elif agent_id:
            entry = registry.capability_entry(spec, agent_id)
            if wizard_config and wizard_config.get("planner_description"):
                entry["planner_description"] = wizard_config["planner_description"]
            ctx.act("capability",
                    "append capability %s to the hub capabilities.json (enabled=False until "
                    "the smoke tests pass; agent_id %s)" % (spec.capability_key, agent_id),
                    lambda: hub.append_capability(ctx.project, spec.capability_key, entry))
        else:
            # Never write a placeholder agent id into the runtime registry: the
            # orchestrator-side validator would reject the whole file at load time.
            ctx.manual("capability",
                       "no verified agent id in this run: once the Code Agent exists, "
                       "append capability %s with registry.capability_entry(spec, "
                       "'agent:<ID>') and hub.append_capability (or re-run the "
                       "capability step)" % spec.capability_key)

    if _enabled(steps, "smoke"):
        smoke(ctx, spec, tool_id=tool_id, agent_id=agent_id)

    return ctx


def smoke(ctx, spec, tool_id=None, agent_id=None):
    """Cheap read-only smoke checks + the human test checklist.

    Deliberately does NOT run the agent or the tool (LLM cost + instance load):
    it verifies the objects respond, and prints what to test by hand.
    """
    if tool_id:
        ctx.act("smoke_tool", "read descriptor of tool %s" % tool_id,
                lambda: ctx.project.get_agent_tool(tool_id).get_descriptor())
    else:
        ctx.skip("smoke_tool", "no tool id in this run")
    if agent_id:
        bare_id = agent_id.split(":", 1)[-1]
        ctx.act("smoke_agent", "read status of agent %s (no wake_up)" % agent_id,
                lambda: ctx.project.get_agent(bare_id).status())
    else:
        ctx.skip("smoke_agent", "no agent id in this run")
    ctx.manual("smoke_checklist",
               "HUMAN VALIDATION before enabling the capability: 1) model Playground: "
               "one counting question, one breakdown, one named-entity question; "
               "2) tool run from a notebook with one canonical question; 3) flip "
               "enabled=true on %s in the hub capabilities.json; 4) webapp: ask one "
               "question routed to %s and check the timeline + Evidence"
               % (spec.capability_key, spec.orchestrator_tool_name))
    return ctx
