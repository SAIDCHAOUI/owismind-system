# OWIsMind_PRD_V1_2 - the OWIsMind agent system (production)

> **What this folder is.** The complete, self-contained **repo mirror** of the
> Dataiku DSS **production** project `OWIsMind_PRD_V1_2` (project key
> `OWISMIND_PRD_V1_2`): the orchestrator + two specialist sub-agents, the Flow
> recipes that build their knowledge, the two semantic models that write the SQL,
> the `attribute_lookup` tool, and the DSS-free tests. This folder is the **source
> of truth**: every change is made HERE, then pasted back into the DSS objects
> (never the other way around). Treat it like a small repo.
>
> **DSS project description.** "Multi-agent AI system for OWI customer intelligence
> - orchestrates specialist agents (CX surveys, incidents, revenues, opportunities)
> to deliver instant, data-backed business insights via natural language."
>
> **How this project came to be.** It is a **duplicate of the DEV project
> `OWISMIND_DEV`**, so every DSS object id is the **DEV id, preserved by the
> duplication**. Production launched 2026-07, demoed and in active use. There is no
> separate "promote to a second project" step anymore: prod IS the clone (see
> **Git model** below).
>
> **Before changing an agent, read the skill** `agentique-python-dataiku`
> (`.claude/skills/agentique-python-dataiku/SKILL.md`): the engineering reference
> for LangChain / LangGraph / Dataiku DSS (abstraction choice, Code Agents + LLM
> Mesh, tool design, structured output, tracing, safety, the Python 3.9 vs 3.11
> dual path).

---

## 0. Read order for a new Claude session

1. [`CLAUDE.md`](CLAUDE.md) (this folder) - orientation, the live inventory, frozen contracts, the rules you must not break.
2. This `README.md` - the full repo <-> DSS map plus the architecture.
3. The skill `agentique-python-dataiku` - how to build / audit DSS agents safely.
4. `memory/PROJECT_STATE.md` + `memory/LESSONS.md` (repo root) - canonical ids and what really works (these PRIME over the cadrage guides).
5. Sub-folder docs for detail: [`flow/README.md`](flow/README.md) + [`flow/DATASETS.md`](flow/DATASETS.md) (the Flow recipes + column inventory), [`semantic-models/README.md`](semantic-models/README.md) + [`semantic-models/MODEL.md`](semantic-models/MODEL.md) (the SQL brain).
6. [`registry.json`](registry.json) (the single spec: ids, dataset names, model + tool binding, lookup config, guardrails) - the source of truth for "which datasets / columns / tools / agents / ids exist". To add an agent, follow [`PLAYBOOK_ADD_AGENT.md`](PLAYBOOK_ADD_AGENT.md).

To navigate the code ("where is X handled?"), query the knowledge graph first
(`graphify query "..."`), not a full re-read.

---

## 1. Repo <-> DSS mapping

Every file / folder in this mirror and the live DSS object it reflects. Ids are the
preserved DEV ids (this project is a clone of `OWISMIND_DEV`).

### Code Agents (Agents zone, Python 3.11 code env)

| Repo file | DSS Code Agent | Id |
|---|---|---|
| `agents/OWIsMind_orchestrator.py` | **OWIsMind_orchestrator** | `038G7mlF` (`agent:038G7mlF`) |
| `agents/SalesDrive_revenue_expert.py` | **SalesDrive_revenue_expert** | `bHrWLyOL` (`agent:bHrWLyOL`) |
| `agents/CSSO_Trouble_Tickets_Expert.py` | **CSSO_Trouble_Tickets_Expert** | `NcE9LD2i` (`agent:NcE9LD2i`) |

### DSS agent tools

| Repo file | DSS tool | Type | Id | Called by |
|---|---|---|---|---|
| `tools/attribute_lookup_tool.py` | **attribute_lookup_tool** | InlinePython (Custom) | `UUoynaL` | the orchestrator (built-in) |
| (no code mirror: config object) | **revenue_semantic_query** | Custom_agent_tool (semantic-models-lab) | `v4oqA6R` | the revenue sub-agent (QUERY) |
| (no code mirror: config object) | **tickets_semantic_query** | Custom_agent_tool (semantic-models-lab) | `nEirlso` | the tickets sub-agent (QUERY) |
| (no code mirror: legacy) | **Drive_Revenues_resolve_filter_value** | InlinePython (Custom) | `aNxeOc4` | nobody - **legacy, pending DSS deletion** |

`revenue_semantic_query` and `tickets_semantic_query` are configuration objects of
the `semantic-models-lab` plugin (they point at a semantic model, no custom Python
to mirror). `Drive_Revenues_resolve_filter_value` is superseded by
`attribute_lookup_tool`, wired to nothing, still listed in DSS as of 2026-07-09:
delete it in DSS by hand. Do NOT confuse this dead tool with the frozen
timeline-event labels `resolve_filter_value` / `dataset_sql_query`, which live only
as `KNOWN_TOOL_NAMES` inside the sub-agent code (event names, not tool calls).

### Semantic models

| Repo file | DSS semantic model | Id |
|---|---|---|
| `semantic-models/Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.v1.json` | **Drive_Revenues_Semantic_Model** | `AHUh9hb` |
| `semantic-models/TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.v1.json` | **TroubleTickets_Semantic_Model** | `dM4jA4G` |

The `.v1.json` files are `get_raw()` snapshots of the live models (no transcription
drift). `semantic-models/scripts/` holds the build / update / dump / remap / repoint
notebooks (documented in [`semantic-models/README.md`](semantic-models/README.md)).

### Flow recipes (design time -> the datasets read at runtime)

The 6 recipe files hold the SAME code pasted verbatim into DSS (3 generic sources,
each pasted into two zones). Dataset IO comes from the DSS Flow wiring
(`dataiku.recipe.get_inputs_as_datasets()` / `get_outputs_as_datasets()`), NOT from
code constants (the fallback constants inside are only for standalone runs and are
intentionally identical across copies).

| Repo file | Flow zone | DSS recipe | Output dataset |
|---|---|---|---|
| `flow/SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_profile.py` | SalesDrive_Revenue_Expert | `compute_DRIVE_Revenues_profile` | `DRIVE_Revenues_profile` |
| `flow/SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_value_index.py` | SalesDrive_Revenue_Expert | `compute_DRIVE_Revenues_value_index` | `DRIVE_Revenues_value_index` |
| `flow/SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_Value_Catalog.py` | SalesDrive_Revenue_Expert | `compute_DRIVE_Revenues_Value_Catalog` | `DRIVE_Revenues_Value_Catalog` |
| `flow/CSC_ticket_AI_Agent/compute_TroubleTickets_year_profile.py` | CSC_ticket_AI_Agent | `compute_TroubleTickets_year_profile` | `TroubleTickets_year_profile` |
| `flow/CSC_ticket_AI_Agent/compute_TroubleTickets_year_value_index.py` | CSC_ticket_AI_Agent | `compute_TroubleTickets_year_value_index` | `TroubleTickets_year_value_index` |
| `flow/CSC_ticket_AI_Agent/compute_TroubleTickets_year_value_catalogue.py` | CSC_ticket_AI_Agent | `compute_TroubleTickets_year_value_catalogue` | `TroubleTickets_year_value_catalogue` |

The two base datasets are Flow inputs: `DRIVE.Revenues` -> sync -> `DRIVE_Revenues`
(SalesDrive_Revenue_Expert zone); `IC_DATA.TroubleTickets_year` -> sync ->
`TroubleTickets_year` (CSC_ticket_AI_Agent zone).

### Webapp Zone (runtime datasets, not built by this folder)

`flow/Webapp_Zone/` mirrors the DSS **Webapp Zone**, which holds
`OWISMIND_PRD_V1_2_beta_owismind_webapp_events_v1` (usage analytics events, written
by the plugin webapp at runtime) and `beta-owismind_webapp_traces_v2` (agent
traces). These are runtime outputs of the plugin backend, not products of the Flow
recipes.

### Docs and tests

| Repo path | What |
|---|---|
| `README.md`, `CLAUDE.md` | This map + the session-orientation doc. |
| `PLAYBOOK_ADD_AGENT.md` | Ordered runbook to add a specialist (worked for tickets). The v1.3 **agent factory** automates most of it: see `factory-docs/README.md`. |
| `registry.json` | The single manifest: ids, file paths, dataset names, model + tool binding, lookup config, guardrails. NOT imported at runtime. |
| `project-library/python/owismind_factory/` | **v1.3 agent factory engine** (pasted into the DSS project library): probe, flow/semantic/tool/agent builders, wizard, pipeline, clone aligner, prompt doctor. |
| `notebooks/` | Factory runners 00-06 (probe, hub push, align clone, create domain, wizard, logging, doctor). |
| `hub/` | Repo seeds of the DSS Config & Prompt Hub (`/owismind_hub/` in the project library): prompts + runtime CAPABILITIES, loaded by the agents at start with embedded fallback. |
| `webapps/agent-factory-console/` | Standard webapp (separate from the Vue plugin app) driving the factory: probe / plan / execute / wizard / prompt editing. |
| `factory-docs/` | Factory architecture (`README.md`), the v1.3-dev deployment guide (`DEPLOY_V1_3_DEV.md`), the Phase 0 capability matrix. |
| `flow/README.md`, `flow/DATASETS.md` | The Flow recipes explained + the canonical column inventory per dataset. |
| `semantic-models/README.md`, `MODEL.md`, `TOOL_DESCRIPTIONS.md` | The SQL brain: scripts index, readable model snapshot, ready-to-paste tool "Description for LLM". |
| `tests/` | DSS-free unit tests (profiler + dataset-expert + langgraph + attribute_lookup). Run: `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests`. |

### Legacy / not mirrored

- **SalesDrive_AI_Agent** (`rNTZ781a`): an early agent, still listed in DSS, NOT in
  the runtime chain, no code mirror in this repo. Ignore it.
- **Drive_Revenues_resolve_filter_value** (`aNxeOc4`): dead tool, pending DSS
  deletion (see the tools table above).

---

## 2. The system in one picture

```
DESIGN TIME (Flow - built once, refreshed by a scenario)
  DRIVE_Revenues ──► [compute_..._profile]        ──► DRIVE_Revenues_profile        the "business brain": metrics, scenarios, axes, synonyms   << sub-agent reads
                 ──► [compute_..._value_index]     ──► DRIVE_Revenues_value_index    the exact-value index used for grounding                   << sub-agent reads (SQL)
                 ──► [compute_..._Value_Catalog]   ──► DRIVE_Revenues_Value_Catalog  rich alias / variant catalog                               << attribute_lookup fallback reads
  (the tickets zone builds TroubleTickets_year_{profile,value_index,value_catalogue} the same way)

RUNTIME (one chat turn)
  Vue web app ──► python-lib Flask backend ──► (agent whitelist resolves the id) ──► OWIsMind_orchestrator  (Code Agent, LangGraph, env 3.11)
                                                                                        │  agentic loop: REASON -> call tool(s) -> REASON -> ... -> write the answer
                                                                                        │  tools: ask_revenue_expert | ask_tickets_expert | attribute_lookup | show_chart | show_table | show_kpi | current_date
                                                                  ┌─────────────────────┴─────────────────────┐
                                            (fast value read)     ▼                                            ▼  (computed figures)
                                       attribute_lookup  (Custom Python tool, UUoynaL)             SalesDrive_revenue_expert / CSSO_Trouble_Tickets_Expert  (Code Agents, env 3.11)
                                            │  one ILIKE over the base text columns                    │  1. UNDERSTAND   1 LLM (strict JSON), prompt GENERATED from the profile
                                            │  + Value_Catalog alias fallback                          │  2. RESOLVE      ground terms by INLINE SQL on value_index (exact -> fuzzy) + ambiguity policy
                                            ▼                                                          │  3. QUERY        hand a grounded question to the semantic-query tool (it writes + runs the SQL);
                                       PostgreSQL (read-only)                                          │                  technical failure -> FALLBACK to own read-only SQL templates
                                                                                                       │  4. RENDER       table + figures formatted BY CODE; "[Scope]" line; about_data answered from profile (0 SQL)
                                                                                                       ▼
                                                                   revenue_semantic_query (v4oqA6R) / tickets_semantic_query (nEirlso)
                                                                                                       ▼
                                                     Drive_Revenues_Semantic_Model (AHUh9hb) / TroubleTickets_Semantic_Model (dM4jA4G) ──► PostgreSQL (read-only)
```

**How a turn reaches the orchestrator.** The Vue front sends a logical agent key
(never a raw agent id) to the `python-lib` Flask backend; the backend resolves it
against a server-side whitelist to the `OWIsMind_orchestrator` Code Agent and
invokes it over LLM Mesh, streaming timeline events back (polling-via-thread). The
agents in this folder are the Code Agent code; the backend, SQL storage and
streaming live in `python-lib/owismind/` (repo root). See the root `CLAUDE.md`.

The orchestrator never holds business data: every figure comes from a sub-agent
(SQL-grounded) or from `attribute_lookup` (a read), so it structurally cannot
invent a number. The work shows live on the webapp timeline and the executed SQL
surfaces in the Evidence panel.

---

## 3. The agents

| Agent | File | DSS Code Agent (id) | Role |
|---|---|---|---|
| Orchestrator | `agents/OWIsMind_orchestrator.py` | **OWIsMind_orchestrator** (`038G7mlF`, env 3.11) | Chats, reasons, routes to specialist sub-agent(s), runs the `attribute_lookup` built-in for fast reads, renders chart/table/KPI, writes the analysis. Honesty firewall: never denies that data exists, never invents a figure. Bounded parallel fan-out (`MAX_PARALLEL_AGENTS = 3`). |
| Revenue sub-agent | `agents/SalesDrive_revenue_expert.py` | **SalesDrive_revenue_expert** (`agent:bHrWLyOL`, env 3.11) | Expert of `DRIVE_Revenues`. UNDERSTAND -> RESOLVE -> QUERY -> RENDER. Owns ALL revenue figures across every Phase (ACTUALS / BUDGET / FORECAST / Q3F / HLF). |
| Tickets sub-agent | `agents/CSSO_Trouble_Tickets_Expert.py` | **CSSO_Trouble_Tickets_Expert** (`agent:NcE9LD2i`, env 3.11) | Expert of `TroubleTickets_year`. SAME engine, tickets CONFIG. Ticket counts (`COUNT(DISTINCT id)`), resolution durations, status / priority / category breakdowns. Included in the clone by duplication; curation finishing (see [`PLAYBOOK_ADD_AGENT.md`](PLAYBOOK_ADD_AGENT.md)). |

Both sub-agents are **standalone files** (stdlib + `dataiku` + `langgraph` only, no
plugin import) pasted into a DSS Code Agent on the **Python 3.11 code env**
(LangGraph needs >= 3.10). LLM calls use the **native LLM Mesh** completion API so
the model's reasoning and tool-calling are honored (see the skill for why we never
force `with_json_output` on the orchestrator, and why we DO force it on the
sub-agent's UNDERSTAND).

---

## 4. The design-time Flow (detail: [`flow/README.md`](flow/README.md) + [`flow/DATASETS.md`](flow/DATASETS.md))

Per domain, four datasets built by three recipes. Each output is read by a
different runtime consumer.

| Dataset | Built by | Read at runtime by | Role |
|---|---|---|---|
| `DRIVE_Revenues` | source (Flow input, sync from `DRIVE.Revenues`) | semantic model (SQL); `attribute_lookup` (fact search) | The revenue base: Phase, offer hierarchy, account, amount_eur, year_month, ... |
| `DRIVE_Revenues_profile` | `compute_DRIVE_Revenues_profile` | the **sub-agent** (UNDERSTAND + about_data) | The business brain: metrics, scenario column, time column, axes, synonyms, display pairs. Human-reviewable via an editable overrides dataset. |
| `DRIVE_Revenues_value_index` | `compute_DRIVE_Revenues_value_index` | the **sub-agent** (RESOLVE, inline SQL) | Every distinct groundable value + normalized form. **Must live on the source SQL connection** (`SQL_owi`). |
| `DRIVE_Revenues_Value_Catalog` | `compute_DRIVE_Revenues_Value_Catalog` | `attribute_lookup` (alias fallback) | Rich alias / variant catalog. Queried for "suggestions" when the fast search finds no exact match. |

The tickets zone (`CSC_ticket_AI_Agent`) mirrors this on `TroubleTickets_year`
(source synced from `IC_DATA.TroubleTickets_year`), producing
`TroubleTickets_year_profile`, `TroubleTickets_year_value_index`, and
`TroubleTickets_year_value_catalogue`.

The profile recipe sends the LLM **aggregated metadata only** (schema, stats,
low-cardinality enum values, a few samples), never raw rows.

**`DRIVE_Revenues` columns (20).** The offer hierarchy is `SolutionLine > Solution >
Product`: the **`Solution` column was re-added on 2026-07-08** (script
`semantic-models/scripts/add_solution_and_repoint_prod_clone.py`) alongside the
19 base columns `Phase`, `booking_type`, `SolutionLine`, `Product`, `Account_name`,
`Account_partner`, `distribution_type`, `Parent_Group`, `carrier_code`,
`year_month` (date), `amount_eur` (decimal), `sales_entity`, `sales_zone`,
`account_manager` (email), `area_manager` (email), `sales_director` (email),
`diamond_id`, `sirano_product`, `original_dataset`. Full column inventory (both
domains) is in [`flow/DATASETS.md`](flow/DATASETS.md).

---

## 5. Which model where (modes)

Model-agnostic by design: one model drives the whole turn, picked by the user's
mode. No mid-turn escalation. The same mode is propagated to the sub-agent.

| Mode | Model id (LLM Mesh) | Notes |
|---|---|---|
| `smart` (default) | `...vertex_ai/gemini-3.1-flash-lite` | Cheap, fast, good. Live narration OFF (the deterministic ticker covers the wait). |
| `pro` | `...vertex_ai/gemini-3.5-flash` | Stronger; narrates alongside tool calls. |
| `claude` | `...vertex_ai/claude-sonnet-4-6` | Orchestrator AND sub-agent. Max quality. |

All ids carry the connection prefix `openai:LLM-7064-revforecast:`. Configure them
in `LOOP_LLM_BY_MODE` (orchestrator) and `LLM_BY_MODE` (sub-agent) - they must
match an id exposed by the LLM Mesh connection; **verify `GEMINI_FLASH_LITE_ID`
and `GEMINI_FLASH_ID` before deploy** (a wrong smart id breaks the default mode).

The **Semantic Model Query tools** keep writing the SQL on Sonnet in EVERY mode
(`SEMANTIC_TOOL_ID_BY_MODE` maps all three modes to the domain's tool id:
`v4oqA6R` for revenue, `nEirlso` for tickets), so offer/column resolution stays
strong regardless of the orchestration tier. Each runs on its own DSS-configured
strong model (`vertex_ai/claude-sonnet-4-6`) in **linear pipeline mode (Agent mode
OFF)**. Live config and the corrected "Description for LLM" to paste are in
[`semantic-models/TOOL_DESCRIPTIONS.md`](semantic-models/TOOL_DESCRIPTIONS.md).

Grounding inside a sub-agent is **not** a tool: it runs inline read-only SQL on the
domain's `value_index`. The timeline labels `resolve_filter_value` /
`dataset_sql_query` are frozen EVENT names (not tool calls).

---

## 6. Frozen contracts (the webapp / Evidence depend on these - never rename, only add)

- **Orchestrator event kinds**: `START, PLANNING, CALLING_AGENT, AGENT_DONE,
  RUNNING_TOOL, TOOL_DONE, ARTIFACT, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*`,
  plus transient `NARRATION`.
- **Sub-agent collaboration dialect**: `KNOWN_BLOCK_IDS`
  (`resolve, run_sql, format_output, clarify_user, out_of_scope_msg, about_data`);
  `KNOWN_TOOL_NAMES` (`resolve_filter_value, dataset_sql_query`) = timeline EVENT
  labels, NOT live tool calls; one final `AGENT_RESULT`
  `{status, language, intent, resolvedFilters, sqlCount, rowCount, attempts}`
  (status: `ready | need_clarification | out_of_scope | no_data | error`).
- **SQL span** named `semantic-model-query` per executed SQL, outputs
  `{sql, success, row_count}` (+ `rows, columns` on the successful one). Frozen
  `sql_id` format `s{step}q{n}` (sub-agent) / `s{step}lk{n}` (orchestrator lookup).
  The orchestrator appends the sub-agent trace to its own so Evidence capture +
  usage work unchanged.
- **Registry anti-drift**: the orchestrator's `block_labels` / `tool_labels` keys
  must match the sub-agent's `KNOWN_BLOCK_IDS` / `KNOWN_TOOL_NAMES`
  (test `tests/test_langgraph_agents.py`).
- **Profile contract v1**: `{key, payload}` rows, `__dataset__` table-level +
  one row per column (see the profile recipe docstring).
- **Result caps** mirrored across files: 50 rows x 50 cols x 256 chars/cell x 64k JSON.
- **One enabled capability per business domain** (a second revenue agent must
  flip the first to `enabled=False`).

---

## 7. The DSS tools

Four tool objects live in DSS, with two distinct callers.

| Tool (instance) | Type | Id | Called by | Status |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query (Custom_agent_tool) | `v4oqA6R` | the **revenue sub-agent** (QUERY) | live - the SQL engine |
| `tickets_semantic_query` | Semantic Model Query (Custom_agent_tool) | `nEirlso` | the **tickets sub-agent** (QUERY) | included in the clone; repoint pending (see below) |
| `attribute_lookup_tool` | Custom Python (`tools/attribute_lookup_tool.py`) | `UUoynaL` | the **orchestrator** (built-in) | live, wired as an orchestrator built-in |
| `Drive_Revenues_resolve_filter_value` | Custom Python | `aNxeOc4` | nobody | **legacy - pending DSS deletion** (superseded by `attribute_lookup_tool`) |

- Each Semantic Model Query tool runs on its **OWN DSS-configured strong model**
  (`vertex_ai/claude-sonnet-4-6`) in **linear pipeline mode (Agent mode OFF)**, so
  offer/column resolution stays strong in every orchestration tier. It writes AND
  runs the SQL against its semantic model.
- `attribute_lookup_tool` is an **orchestrator built-in** (appended in
  `build_tool_specs`, dispatched inline in `node_tools`), so it touches NO frozen
  `KNOWN_*` contract and the sub-agents are UNCHANGED. The model passes a logical
  DOMAIN, the orchestrator resolves it to a whitelisted dataset via the registry.
- `dataset_lookup` (managed, `9FEzVZk`) was **removed 2026-06-18**; it no longer
  exists in DSS or code.

---

## 8. Semantic models

- **Revenue** (`Drive_Revenues_Semantic_Model`, `AHUh9hb`): 3 entities
  (`revenue_record`, `customer_account`, `commercial_offer`) all mapping to ONE
  physical table (never JOIN), a `Total Revenue (EUR)` metric, named filters,
  golden queries, a glossary, and the SQL instructions (Phase=ACTUALS default;
  offer priority `Product > Solution > SolutionLine > sirano_product`;
  never-default-sirano + transparency; GROUP BY diamond_id, display Account_name +
  carrier_code). **Repointed to the clone dataset** (`datasetRef
  OWISMIND_PRD_V1_2.DRIVE_Revenues`, physical table
  `"OWISMIND_PRD_V1_2_drive_revenues"`) and the **`Solution` offer column re-added
  on 2026-07-08** (script `add_solution_and_repoint_prod_clone.py`), VALIDATED in
  DSS. Grounding preference order: 1.Product 2.Solution 3.SolutionLine
  4.sirano_product.
- **Tickets** (`TroubleTickets_Semantic_Model`, `dM4jA4G`): default metric
  `COUNT(DISTINCT id)` (historical-snapshot duplicates), `Duration_ticket_total` in
  minutes (AVG, never SUM). Repoint script `repoint_tickets_prod_clone.py` is READY
  and simulated 4/4, **not yet launched** on the clone.

Readable snapshot: [`semantic-models/MODEL.md`](semantic-models/MODEL.md). The
scripts (build / update / dump / drop / migrate / remap / repoint) are documented in
[`semantic-models/README.md`](semantic-models/README.md).

---

## 9. Git model

**One branch per version, named after the DSS prod project.** A version's branch is
the source of truth for that version of the whole system (plugin + agents + flow +
semantic models). The old two-project "develop in DEV, promote to a PROD twin"
workflow no longer exists: prod is the clone of DEV, and versions advance by
branch.

- `OWIsMind_PRD_V1_2` = the **current prod branch** (this project). Source of truth.
- `OWIsMind_PRD_V1_3-dev` = the **next dev branch** (user-feedback hub, WIP). New
  domains and changes are developed here, validated in the DSS clone, then promoted
  by **dropping the `-dev` suffix**: the validated dev branch becomes the new prod
  branch and the next version starts.
- `main` is **deprecated**.

Plugin packaging follows the same versioning: `plugin.json` version drives the zip
name (`Plugin/ready-for-dataiku/owismind-v1_2-upload.zip`, dots -> underscores,
major_minor only). The coexisting DEV plugin (`owismind_dev`, via
`tools/build_dev_plugin.py`, zip `owismind-v<VER>-dev-upload.zip`) is kept for
side-by-side testing.

---

## 10. Guardrails and limits

- **SQL safety**: read-only transaction (`SET LOCAL transaction_read_only`) +
  `statement_timeout 30s`; the direct engine guards LLM SQL (single SELECT, one
  whitelisted table, no DML/DDL, forced LIMIT, EXPLAIN dry-run, system tables
  rejected); `attribute_lookup` searches with one bounded `ILIKE`, streams rows,
  loads nothing into RAM. See `docs/security.md` and the skill's safety reference.
- **Honesty (rule P3)**: every shown figure comes from a SQL result; 0 rows ->
  honest message + the scenarios/period actually available (from the profile); an
  unresolved term -> clarification, never a guess. **No hardcoded business values**
  in agent logic - everything comes from the profile / index / overrides / catalog.
- **Two SQL engines**: `semantic_tool` (default, the semantic model writes + runs
  the SQL) and `direct` (deterministic templates + guarded LLM, executed
  read-only). The semantic -> direct fallback is automatic and technical only; a
  legitimately empty result is NOT a fallback.
- **v1 limits**: no cross-dataset JOIN in one query (the 360 goes through the
  orchestrator, one agent per dataset).

---

## 11. Cross-references

- **Skill** `agentique-python-dataiku` - how to design/build/audit DSS agents
  (LangGraph, LLM Mesh, Code Agents, tools, safety). Read it before any agent change.
- **Memory** (repo root, source of truth): `memory/PROJECT_STATE.md` (canonical
  ids, validated matrix), `memory/LESSONS.md` (L0xx, what really works),
  `memory/CONTEXT.md` (current focus).
- **Reference guides**: `docs/cadrage/GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`
  (LLM Mesh + streaming + gotchas), `docs/cadrage/code_samples_dataiku.md`
  (validated notebook snippets).
- **Tests**: `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests` (profiler +
  dataset-expert + langgraph + attribute_lookup). DSS-free.
