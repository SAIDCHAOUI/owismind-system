# Agent Factory v1.3 - design (approved 2026-07-10, night session)

> User approved the multi-phase plan (research session 2026-07-10) and delegated the
> overnight implementation with two standing orders: (1) implement everything whose API
> is confirmed; (2) anything uncertain ships GENERIC and SAFE, gated behind the Phase 0
> probes, with a documented UI fallback. Nothing in this code may endanger the DSS
> instance. Branch: `OWIsMind_PRD_V1_3-dev` (commit + push explicitly authorized by the
> user for this session).

## 1. Goal

Make adding a new dataset-specialist sub-agent (and its whole knowledge chain) fast,
safe and mostly automatic: source table -> Flow zone + 3 knowledge recipes/datasets ->
semantic model (LLM-assisted authoring) -> Semantic Model Query tool -> Code Agent ->
orchestrator registration. Plus: centralize agent prompts outside the pasted agent code
and add a prompt-improvement loop fed by agent interaction logs.

## 2. Research verdict (all sources: official Dataiku docs + official client source)

CONFIRMED (docs and/or official `dataiku-api-client-python` source, grep-verified):
`new_managed_dataset`, `TablesImportDefinition.add_sql_table`, `flow.create_zone` /
`zone.add_item`, `new_recipe("python")` + `CodeRecipeCreator.with_script` +
`set_code_env`, `create_scenario(name, "step_based", definition)` + `raw_steps` +
`add_daily_trigger`, `create_semantic_model` / `new_version` / `get_raw()/save()` /
`start_update_distinct_values` (PROVEN: `build_aligned_semantic_model.py` already ran on
this instance), `create_agent(name, "PYTHON_AGENT")`, `new_agent_tool(type,...)` generic
creator, `create_llm_interaction_logging_dataset` + `interaction_logging_selection`,
project library file CRUD, wiki CRUD, `with_json_output(schema)`, Agent Review API.

UNKNOWN SCHEMA (exists but undocumented; needs the Phase 0 probe on the instance):
- keys inside `versions[*].pythonAgentSettings` (Code Agent source code + code env),
- the type string + `params` schema of the Semantic Model Query tool instance,
- whether the server build exposes `create_agent`/`new_agent_tool` (client master does).

## 3. Decisions taken on the user's behalf (he was asleep)

1. **Hub storage = DSS project library** under `/owismind_hub/` (editable in the DSS UI,
   git-friendly, readable via the public API from agents AND the 3.9 backend without any
   import). Variables/wiki rejected: all-or-nothing writes / weaker fit.
2. **Console = Standard webapp, SEPARATE from the plugin** (user's final word: keep agent
   management apart for now, merge into the Vue app in a later version). Pattern = LAB
   webapps (body.html + script.js + style.css + backend.py, paste-in deploy), Orange charter.
3. **Recipe code sourcing**: the factory clones the code payload of the EXISTING validated
   recipes (they are dataset-adaptive and read IO from the Flow wiring), fallback = library
   template file. Zero code duplication.
4. **Semantic model seeding**: duplicate-and-modify the raw config of an existing model
   (default `AHUh9hb`), the exact strategy `build_aligned_semantic_model.py` validated;
   embedded minimal skeleton as fallback. The raw shape was extracted from the committed
   v1.json dumps (entities/attributes/metrics/filters/goldenQueries/glossaryTerms/
   sqlGenerationConfig.instructions/indexingSettings/privateEditorData.embeddingLlmId).
5. **Gating pattern**: `agent_builder` and `tool_builder` take explicit
   `schema_hints`/`discovery` arguments produced by the probe; without them they do NOT
   touch DSS and instead emit a precise manual checklist (print-for-paste / UI clicks).
6. **No deletion code** anywhere in the factory, except the write-probe deleting the
   throwaway objects it just created (probe write section is OFF by default behind
   `RUN_WRITE_PROBES`).
7. **Instance safety**: dry-run first (pipeline builds a PLAN), idempotent ensure_*
   steps, builds only via scenario (created with auto-trigger defined but scenario left
   inactive), `DSSFuture.wait_for_result()` instead of tight polling, wizard sends
   aggregated profile metadata only (never raw rows), bounded LLM calls.
8. **Factory code = stdlib + `dataiku` only, Python 3.9 compatible** (runs in notebooks
   and in the Standard webapp backend).
9. Agent files keep their embedded prompts/CAPABILITIES as DEFAULTS; hub overrides load
   once at module import, validate, and silently fall back on any error. Frozen
   contracts untouched.

## 4. Repo layout (all inside the DSS project mirror folder)

```
OWIsMind_PRD_V1_3_DEV/
  project-library/python/owismind_factory/   # the engine (pasted into DSS project library)
    __init__.py  fctx.py  spec.py  hub.py  registry.py
    flow_builder.py  semantic_builder.py  wizard.py
    tool_builder.py  agent_builder.py  probes.py  pipeline.py
  notebooks/            # thin runners: 00_probe .. 06_prompt_doctor
  hub/                  # files pushed to the project library /owismind_hub/
    capabilities.json   prompts/orchestrator_persona.md  README.md
  webapps/agent-factory-console/   # Standard webapp (body.html/script.js/style.css/backend.py)
  factory-docs/         # README + DEPLOY guide + CAPABILITY_MATRIX template
```

## 5. Module interfaces (summary)

- `fctx.FactoryContext(project=None, dry_run=True)` - plan/done/skip/fail/manual action
  log + `report_markdown()`.
- `spec.DomainSpec` - validated domain spec + derived names (`<base>_profile`, ...).
- `hub` - `read_text/write_text/read_json/write_json/append_capability/validate_capabilities`
  against `/owismind_hub/...` (backup file before every capabilities write).
- `flow_builder` - `ensure_source_dataset`, `ensure_zone`, `ensure_knowledge_datasets`,
  `ensure_recipes(template_from_existing=...)`, `ensure_refresh_scenario`,
  `run_scenario_now` (explicit only).
- `semantic_builder` - `seed_model_from_existing`, `apply_config`, `start_indexing(wait)`.
- `wizard` - `draft_model_config(profile, answers)` via LLM Mesh `with_json_output`
  (JSON schema: entities, attributes, metrics, filters, glossary, instructions,
  golden_queries, planner_description, clarifying `questions[]`), `merge_answers`,
  `draft_profile_overrides`. Pure logic separated for DSS-free tests.
- `tool_builder` - `describe_existing_tool` (discovery), `create_semantic_query_tool_like`
  (gated), `ui_checklist` (fallback).
- `agent_builder` - `generate_subagent_code` (pure CONFIG-header rewrite of the template
  engine file), `create_code_agent` (gated: needs probe `schema_hints`), fallback writes
  the generated file to the hub for manual paste.
- `probes` - `run_read_probes` (always safe) + `run_write_probes` (flag-gated) +
  markdown report to paste back into the repo.
- `pipeline.create_domain(ctx, spec, ...)` - ordered steps, each idempotent, each
  recorded; gated steps degrade to MANUAL entries with exact instructions.

## 6. Agent-file changes (the only edits to existing runtime code)

Each of the 3 Code Agents gets one additive `CONFIG HUB` block:
- `_hub_text(path)` / `_hub_json(path)`: public-API read of the project library,
  module-level cache, every failure returns None (fallback to embedded defaults).
- Orchestrator: `PERSONA` override (`prompts/orchestrator_persona.md`), `CAPABILITIES`
  override (`capabilities.json`, strictly validated: required keys, label dicts, one
  enabled capability per domain; invalid -> embedded default).
- Sub-agents: optional additive `prompts/<domain>/understand_extra.md` appended to the
  UNDERSTAND system prompt; nothing else changes.
- Anti-drift tests extended: hub validator required-keys must match the embedded
  CAPABILITIES entries and registry.json.

## 7. Out of scope tonight

Merging the console into the Vue plugin app; auto-applying prompt-doctor output; Agent
Review wiring (documented as option); deletion tooling; running anything against DSS
(user runs the probes tomorrow and reports back).
