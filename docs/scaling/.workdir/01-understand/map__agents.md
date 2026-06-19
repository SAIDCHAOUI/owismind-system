I now have a thorough read of both files. Let me compile the comprehensive answer.

---

## Agents Architecture & Template-Ability

### (1) Orchestrator Anatomy

**LangGraph loop.** `MyLLM.process_stream` builds a `StateGraph` with three nodes: `node_agent -> route_agent -> [node_tools | node_finish]`, with `node_tools` feeding back to `node_agent`. The loop is bounded by `MAX_TOOL_LOOPS = 8`. The graph runs non-durable (no checkpointer; ephemeral per request). `OrchState` accumulates `captured` (Evidence SQL items), `artifacts`, `usage`, `statuses`, `used_caps`, and `latest` (the last result with rows).

**`build_tool_specs(caps)`** generates the full OpenAI-style function schema set at startup. It iterates `get_capabilities()` (filtering on `enabled=True`) and emits one tool per `agent` entry (`ask_<capability_key>`). Then appends four hardcoded built-ins: `show_chart`, `show_table`, `show_kpi`, `current_date`, plus `attribute_lookup` when any capability declares a `lookup_dataset`. The tool spec for a sub-agent is fully data-driven from the registry: `name`, `description = planner_description`, and a fixed one-parameter schema (`task: string`). **This is the main extension point**: adding a new sub-agent = one new dict in `CAPABILITIES`.

**`node_tools` inline dispatch.** Tool calls from the model are split into `sub_calls` (name in `self._tool_to_cap`) and `local_calls`. Local calls are dispatched inline by name in a `if name in ("show_chart", "show_table", "show_kpi")` / `elif name == "current_date"` / `elif name == LOOKUP_TOOL_NAME` chain. Sub-agent calls go to `_run_subagents`, which runs them in a `ThreadPoolExecutor` fan-out (up to `MAX_PARALLEL_AGENTS = 3`) - parallel when the model emits multiple calls on the same turn.

**Registry/manifest - CAPABILITIES dict.** Each entry carries: `kind` (`"agent"`), `agent_id` (DSS `agent:XXXX`), `domain` (one of the `BUSINESS_DOMAINS` keys), `tool_name`, `planner_description`, `block_labels`, `tool_labels`, `lookup_dataset`, `lookup_catalog`, `pass_context`, `enabled`, `source_url`. `BUSINESS_DOMAINS` separately lists all domains including un-staffed ones (tickets, satisfaction, opportunities, delivery, billing) - staffed = at least one enabled agent for that domain. The honesty firewall is built on this: `staffed_domains()` drives the "DOMAINS YOU CANNOT STAFF YET" section of the system prompt.

**Model-by-mode.** `LOOP_LLM_BY_MODE = {eco: Gemini Flash-Lite, medium: Gemini Flash, high: Sonnet}`. `parse_mode` reads the `⟦owi:mode=…⟧` control token (last occurrence wins for security) and strips all `⟦owi:…⟧` tokens before replay. Narration (the model's live lead-in) is off in `eco` (narrate-and-stop risk on small models); the deterministic ticker covers the wait instead. The nudge guard (`_looks_like_premature_stop`) fires once per run.

**Honesty firewall.** `PERSONA` explicitly bans the orchestrator from asserting any business figure. `build_system_prompt` generates a "DOMAINS YOU CANNOT STAFF YET" block for every domain in `BUSINESS_DOMAINS` without an enabled agent - so adding a new domain to that dict immediately gets honest "no agent yet" handling even before building the sub-agent.

**What is generic vs revenue-specific in the orchestrator:**

- **Generic machinery**: LangGraph state, `LoopChat`, `node_agent` loop, narrate-and-stop guard, `node_finish` fallback renderer, `build_tool_specs` (data-driven), `node_tools` dispatch for `show_chart/table/kpi/current_date/attribute_lookup`, `_run_subagents` parallel fan-out, `_find_generated_sql`/`_find_usage` trace walkers, all event emission logic, `_subagent_tool_output`, `parse_mode`/`parse_lang`.
- **Revenue-specific**: `CAPABILITIES["revenue_expert"]` dict (hardcoded `agent_id`, domain, labels, `lookup_dataset = "DRIVE_Revenues"`, `planner_description`), `LOOKUP_SOURCE_CAP = "revenue_expert"`, `BUSINESS_DOMAINS` content, `PERSONA` mentioning "OWI customer revenue expert" and "€" formatting rules and scope transparency. The money/transparency section of `PERSONA` is revenue-domain-flavored but not structurally revenue-specific.

---

### (2) Sub-Agent Anatomy

**Pipeline: UNDERSTAND -> RESOLVE -> QUERY -> RENDER** (LangGraph `StateGraph` in `SalesDrive_revenue_expert.py`).

**UNDERSTAND**: One LLM call with `with_json_output` (forced, unlike the orchestrator - safe here because no reasoning flag on this model). The prompt is entirely **generated from the `Profile` object** via `build_understand_prompt(profile, ...)` - metric names, scenario column and values, time coverage, groupable axes with synonyms and enum values, all from the profile dataset. `validate_understanding` validates/degrades the parse purely against profile structure (no hardcoded business values per rule P3). Output: `intent` (one of 11 KNOWN_INTENTS), `metric`, `scenarios`, `period`, `group_by`, `terms`, etc.

**RESOLVE**: Inline read-only SQL on `VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"` (exact -> normalized -> fuzzy). `rank_candidates`, `refine_ambiguous`, `defer_multicolumn_offer_terms` are generic algorithms driven by the profile's `column_priority`. No business values hardcoded.

**QUERY** (COMPOSE + QUERY): `build_semantic_question(u, profile, filters)` composes a fully deterministic natural-language message for the Semantic Model Query tool (`revenue_semantic_query`, id `v4oqA6R`). The question always starts with `USER QUESTION ... : "{instruction}"`, then appends deterministic intent hints (generic templates per intent), grounded filter hints, scenario/period hints. The tool runs the SQL; `extract_semantic_payload` extracts the result from the agent-mode transcript (last-occurrence wins). On tool failure: falls back to `build_sql(u, profile, filters, table)` - 9 deterministic SQL templates - plus a guarded LLM fallback for `custom` intent (`guard_custom_sql` enforces read-only + single table + LIMIT).

**RENDER**: `format_cell`/`format_number` driven by `profile.metric.format` and `metric_unit` (currency derived from column name, e.g. `amount_eur -> €`). `_scope_label` derives a `[Scope] / [Périmètre]` line from profile-provided scenario/period labels. With `SUBAGENT_LLM_HEADLINE = False` (default), the orchestrator writes the user-facing analysis; the sub-agent emits the result table + scope line only.

**Generic machinery vs revenue-domain-specific:**

- **Generic**: `Profile` loader and all accessors, `build_understand_prompt` (fully profile-generated), `validate_understanding` (profile-driven), resolver (`rank_candidates`, `refine_ambiguous`, `defer_multicolumn_offer_terms`), all 9 SQL templates in `build_sql`, `guard_custom_sql`, `build_semantic_question` (intent templates), `extract_semantic_payload`, `shape_result`, `format_cell`/`format_number`, all user-facing bilingual text constants.
- **Revenue-specific hardcoded values**: `PROFILE_DATASET = "DRIVE_Revenues_profile"`, `VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"`, `SEMANTIC_TOOL_ID = "v4oqA6R"`, `SEMANTIC_TOOL_NAME = "revenue_semantic_query"`, `TARGET_DATASET = ""` (defaults to profile's `dataset_name`). Also the `OUT_OF_SCOPE_TEXT` uses `{label}` from the profile description, so it is generic at runtime. The offer-hierarchy logic (`AMBIGUOUS OFFER TERM`, `defer_multicolumn_offer_terms`, `DISCLOSE_NOTE`) is coded generically (decision is by number of distinct candidate columns, not by column name), but the semantic model instructions (in DSS, not in this file) carry the specific offer hierarchy (`Product > Solution > SolutionLine > sirano_product`).

---

### (3) The Template Question: What Blocks Clean Copy-Paste

To add a sub-agent (e.g. tickets, billing, opportunities), here is every item that must change:

**In the orchestrator (`OWIsMind_orchestrator.py`)**:
1. `CAPABILITIES` dict: add one entry with `agent_id`, `domain`, `tool_name`, `planner_description`, `block_labels` (must match the new sub-agent's `KNOWN_BLOCK_IDS`), `tool_labels` (must match `KNOWN_TOOL_NAMES`), `lookup_dataset`, `lookup_catalog`, `enabled`.
2. `BUSINESS_DOMAINS`: add the new domain key if not already listed.
3. `PERSONA`: currently says "sales managers, business-development leads and executives" and "OWI customer revenue expert" - must be broadened or made generic for a multi-domain assistant.
4. The money/scope transparency block in `PERSONA` (the `€`, "ACTUALS/BUDGET/FORECAST" scope language, `[Scope]` line phrasing) is revenue-flavored. It would need either a domain-neutral rewrite or a per-domain variant injected at system-prompt generation time.
5. `LOOKUP_SOURCE_CAP = "revenue_expert"` - a hardcoded fallback for the lookup Evidence `agent_key`; benign if the new capability declares its own `lookup_dataset`.

**In the sub-agent (create `<domain>_expert.py` by copying `SalesDrive_revenue_expert.py`)**:
1. `PROFILE_DATASET`, `VALUE_INDEX_DATASET`: point to the new domain's profile and value index datasets.
2. `SEMANTIC_TOOL_ID`, `SEMANTIC_TOOL_NAME`: the new domain's Semantic Model Query tool (a separate DSS object with its own model, entities, golden queries).
3. `KNOWN_BLOCK_IDS` / `KNOWN_TOOL_NAMES`: these are frozen contracts between the sub-agent and the orchestrator's `block_labels`/`tool_labels` in the registry. They must match exactly (an anti-drift test `test_langgraph_agents.py` guards this). For a new sub-agent, define new KNOWN_* constants and update the registry entry to match.
4. The `OUT_OF_SCOPE_TEXT`/`PROFILE_MISSING_TEXT` etc. are generic (`{label}` from profile) - no change needed there.
5. `SUBAGENT_LLM_HEADLINE`, `SUBAGENT_MAX_PARALLEL`, SQL caps: copy verbatim, adjust if the new domain's data has different cardinality.

**In DSS (infrastructure)**:
1. Run the three Flow recipes (`profile_dataset_recipe.py`, `build_value_index_recipe.py`, `build_value_catalog_recipe.py`) pointed at the new source dataset - these are fully dataset-agnostic.
2. Create a new Semantic Model Query tool in DSS with its own model.
3. Register the new Code Agent in DSS (env 3.11), paste the adapted file.

**In `build_value_index_recipe.py` / `build_value_catalog_recipe.py`**: these are generic - the only config is `INPUT_DATASET` / `OUTPUT_DATASET` at the top. No change to logic.

**Remaining hardcoded revenue-specific blockers** (exact strings/values that would bleed into a second domain if copied naively):
- `DRIVE_Revenues`, `DRIVE_Revenues_profile`, `DRIVE_Revenues_value_index`, `DRIVE_Revenues_Value_Catalog` (3 constants to change at the top of the file).
- `SEMANTIC_TOOL_ID = "v4oqA6R"`, `SEMANTIC_TOOL_NAME = "revenue_semantic_query"` (2 constants).
- The offer-hierarchy wording in `build_semantic_question` (`"prefer the most granular BUSINESS level - Product, then Solution..."`, `"NEVER default to sirano_product"`) is injected into the deferred-term block. This is a revenue-domain prompt fragment. For a tickets agent it would be irrelevant (no offer hierarchy), but it only fires when `u.get("offer_terms_for_model")` is non-empty - which it would not be for a non-offer domain. So it silently no-ops; not a blocker, but dead weight.

---

### (4) What a Config-Driven "Agent Definition" Would Need

For "adding an agent = editing config + prompt + pointing at a dataset", a declarative definition per sub-agent would need to capture:

```
domain:              (key in BUSINESS_DOMAINS)
agent_id:            DSS "agent:XXXX"
label_fr / label_en: human display names
planner_description: orchestrator routing description (determines when the model calls this agent)
datasets:
  profile:     <PROFILE_DATASET>
  value_index: <VALUE_INDEX_DATASET>
  value_catalog: <optional VALUE_CATALOG_DATASET>
  source:      <FACT_DATASET> (for attribute_lookup)
semantic_tool:
  id:   <SEMANTIC_TOOL_ID>
  name: <SEMANTIC_TOOL_NAME>
block_labels:        { blockId -> {fr, en} }  (must match KNOWN_BLOCK_IDS in the sub-agent code)
tool_labels:         { toolName -> {fr, en} } (must match KNOWN_TOOL_NAMES)
source_url:          optional Dataiku link for Evidence
lookup_dataset:      dataset for attribute_lookup
lookup_catalog:      alias catalog for attribute_lookup
pass_context:        bool
enabled:             bool
```

The sub-agent code itself (the UNDERSTAND-RESOLVE-QUERY-RENDER pipeline) would become a **shared library** `dataset_expert_base.py` importable by all domain agents, with the five config constants (`PROFILE_DATASET`, `VALUE_INDEX_DATASET`, `SEMANTIC_TOOL_ID`, `SEMANTIC_TOOL_NAME`, `TARGET_DATASET`) injected at instantiation. The only per-domain artifact would be the profile dataset content (built by Flow recipes) and the Semantic Model configuration (DSS object). **Note**: the standalone-file constraint (no plugin imports, pasted into DSS Code Agent) currently prevents this sharing pattern - it would require either relaxing that constraint (packaging `dataset_expert_base` as a library accessible to the 3.11 env) or accepting per-domain file duplication with a shared section clearly marked.

---

### (5) Frozen Contracts That Constrain Change

These must never be renamed, only extended:

- **Orchestrator event kinds** (`START`, `PLANNING`, `CALLING_AGENT`, `AGENT_DONE`, `RUNNING_TOOL`, `TOOL_DONE`, `ARTIFACT`, `WRITING_ANSWER`, `DONE`, `ERROR`, `NARRATION`, `SUB_AGENT_*`): consumed by `python-lib/owismind/agents/streaming.py` and the frontend timeline reducer.
- **Sub-agent block contract** (`KNOWN_BLOCK_IDS`): `resolve`, `run_sql`, `format_output`, `clarify_user`, `out_of_scope_msg`, `about_data`. These are the `blockId` values in `AGENT_BLOCK_START` events; the registry's `block_labels` dict keys must match exactly. A test in `test_langgraph_agents.py` guards this anti-drift.
- **Sub-agent tool contract** (`KNOWN_TOOL_NAMES`): `resolve_filter_value`, `dataset_sql_query` - these are now only event labels (no live tools with those names), but the frozen contract shapes the timeline event labels emitted by the sub-agent and displayed in the UI.
- **`AGENT_RESULT` event** `{status, language, intent, resolvedFilters, sqlCount, rowCount, attempts}`: consumed by the orchestrator (`status` drives error handling; `intent` drives the rendering hint passed to `_subagent_tool_output`).
- **`semantic-model-query` span shape**: `{sql, success, row_count, rows, columns, source_url}` in `trace.subspan("semantic-model-query").outputs`. The webapp's Evidence capture reads this exact span name and output keys from the footer trace. The `sql_id` format `s{step}q{n}` / `s{step}lk{n}` is also frozen (Evidence deduplication).
- **Profile contract v1**: `{key, payload}` row format, `__dataset__` sentinel key, the payload schema (`dataset_name`, `metrics`, `scenario`, `time`, `grain`, columns with `role`/`indexed`/`groupable`/`synonyms`/`display_column`/`is_enum`/`values`). Changing this would break both the sub-agent and the `profile_dataset_recipe.py`.
- **`CAPABILITIES` registry keys and `tool_name` values** (`ask_revenue_expert`): the frontend sends a logical agent key, the backend resolves it to the orchestrator; the orchestrator exposes `tool_name` to the model. These identifiers must stay stable across deploys.