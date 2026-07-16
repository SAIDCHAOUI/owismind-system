# CLAUDE.md - OWIsMind_PRD_V1_2/

> Orientation for any Claude session touching the agent system, written to be
> self-sufficient: read this and you understand how the OWIsMind agents work
> without anyone pasting code. Full architecture + the repo <-> DSS map:
> [`README.md`](README.md). Engineering reference for building agents safely: the
> skill `agentique-python-dataiku`. Project memory (source of truth, PRIMES over the
> cadrage guides): `memory/PROJECT_STATE.md` + `memory/LESSONS.md`.

## What this is

OWIsMind is the internal data assistant of Orange Wholesale International, running
as agents inside Dataiku DSS and used through a Vue web app. This folder is the
**repo mirror and source of truth** for the DSS **production** project
`OWIsMind_PRD_V1_2` (project key `OWISMIND_PRD_V1_2`): an **orchestrator** that
chats and routes, a **revenue sub-agent** expert of `DRIVE_Revenues`, a **tickets
sub-agent** expert of `TroubleTickets_year`, the **Flow recipes** that fabricate the
sub-agents' knowledge, and the **semantic models** that write the SQL. You edit
HERE, then paste back into the DSS objects (env 3.11 for Code Agents); DSS direct
edits are overwritten on the next paste.

**This project is a clone of the DEV project `OWISMIND_DEV`.** It was created by
**duplicating** DEV, so every DSS object id is the **DEV id, preserved**.
Production launched 2026-07, demoed and in active use. There is no separate "PROD
twin with different ids" anymore; prod IS the clone. Versions advance by git branch
(see below), not by hand-porting between two DSS projects.

## The mechanism, end to end (one chat turn)

```
Vue web app
   │  user message + a logical agent key (never a raw agent id)
   ▼
python-lib Flask backend  (Plugin/owismind/python-lib/, not this folder)
   │  resolves the key against a server-side whitelist -> the orchestrator Code Agent
   │  invokes it over LLM Mesh, streams timeline events back (polling-via-thread)
   ▼
OWIsMind_orchestrator  (LangGraph Code Agent, "sub-agents as tools")
   │  ONE model drives the whole turn (picked by the user's mode: smart/pro/claude).
   │  It REASONS, then on the SAME turn either:
   │    - calls attribute_lookup (built-in)   for a fast value read, OR
   │    - calls ask_revenue_expert / ask_tickets_expert  to delegate a computed figure, OR
   │    - renders the last result (show_chart / show_table / show_kpi), then writes the analysis.
   │  Honesty firewall: it holds NO business data, never invents or denies a figure;
   │  it may only admit "no AGENT for this domain", never "the data is missing".
   ├──────────────────────────────┬──────────────────────────────────────────────┐
   ▼ (fast read)                   ▼ (computed figure, slow)                       │
attribute_lookup                revenue / tickets sub-agent  (LangGraph Code Agents)│
  Custom Python tool              UNDERSTAND -> RESOLVE -> QUERY -> RENDER          │
  one ILIKE over the base           1. UNDERSTAND : 1 LLM (strict JSON), prompt     │
  text columns; Value_Catalog          generated from the profile                  │
  alias fallback; read-only         2. RESOLVE   : ground user terms by INLINE      │
                                       read-only SQL on value_index (exact->fuzzy)  │
                                    3. QUERY     : hand a grounded question to the   │
                                       semantic-query tool -> it writes+runs SQL    │
                                       (technical failure -> own direct-SQL fallback)│
                                    4. RENDER    : table + figures by code, "[Scope]"│
                                       line; about_data answered from profile (0 SQL)│
                                          │                                          │
                                          ▼                                          │
                                  revenue_semantic_query / tickets_semantic_query    │
                                          ▼                                          │
                                  the domain semantic model -> PostgreSQL (read-only)
```

Everything the user sees as a figure is SQL-grounded: the orchestrator cannot
invent a number because it owns none. Work shows live on the timeline; executed
SQL surfaces in the Evidence panel (every SQL emits a `semantic-model-query` span).

## Live inventory (ids preserved from DEV by the clone; full map in README.md)

### Code Agents (env 3.11)

| Code Agent | File | Id |
|---|---|---|
| OWIsMind_orchestrator | `genai/agents/OWIsMind_orchestrator.py` | `038G7mlF` (`agent:038G7mlF`) |
| SalesDrive_revenue_expert | `genai/agents/SalesDrive_revenue_expert.py` | `bHrWLyOL` (`agent:bHrWLyOL`) |
| CSSO_Trouble_Tickets_Expert | `genai/agents/CSSO_Trouble_Tickets_Expert.py` | `NcE9LD2i` (`agent:NcE9LD2i`) |

`SalesDrive_AI_Agent` (`rNTZ781a`) is a LEGACY early agent, still listed in DSS but
NOT in the runtime chain and NOT mirrored in this repo. Ignore it.

### DSS agent tools

| Tool | Type | Id | Called by |
|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query (Custom_agent_tool) | `v4oqA6R` | the **revenue sub-agent** (QUERY) |
| `tickets_semantic_query` | Semantic Model Query (Custom_agent_tool) | `nEirlso` | the **tickets sub-agent** (QUERY) |
| `attribute_lookup_tool` | Custom Python (`genai/agent-tools/attribute_lookup_tool.py`) | `UUoynaL` | the **orchestrator** (built-in, both domains) |

`Drive_Revenues_resolve_filter_value` (old Custom Python, `aNxeOc4`, called by
nobody) is **legacy, pending DSS deletion** (superseded by `attribute_lookup_tool`).
`dataset_lookup` (managed, `9FEzVZk`) was already removed. The names
`resolve_filter_value` / `dataset_sql_query` survive only as frozen **timeline event
labels** in the sub-agent (`KNOWN_TOOL_NAMES`), not as tool calls - do not conflate
them with the dead `Drive_Revenues_resolve_filter_value` tool.

Each Semantic Model Query tool runs **Agent mode OFF (linear SQL pipeline)**, LLM
`vertex_ai/claude-sonnet-4-6`, embedding `vertex_ai/text-embedding-005`, access
datasets as the calling user. The "Description for LLM" to paste is in
`genai/semantic-models/TOOL_DESCRIPTIONS.md`.

### Datasets (Flow, design time -> read at runtime)

| Dataset | Built by (per-zone recipe) | Read at runtime by | Role |
|---|---|---|---|
| `DRIVE_Revenues` | source (sync from `DRIVE.Revenues`, ~176 k rows, 20 cols) | semantic model (SQL); `attribute_lookup` | the revenue base |
| `DRIVE_Revenues_profile` | `compute_DRIVE_Revenues_profile` | revenue sub-agent (UNDERSTAND, about_data) | business brain (`{key, payload}` v1) |
| `DRIVE_Revenues_value_index` | `compute_DRIVE_Revenues_value_index` | revenue sub-agent (RESOLVE, inline SQL) | exact-value grounding; MUST be on the SQL connection |
| `DRIVE_Revenues_Value_Catalog` | `compute_DRIVE_Revenues_Value_Catalog` | `attribute_lookup` (alias fallback) | rich alias / suggestions catalog |
| `TroubleTickets_year` (+ `_profile`, `_value_index`, `_value_catalogue`) | the same three recipes in the `CSC_ticket_AI_Agent` zone | tickets sub-agent / `attribute_lookup` | the incident-tickets base |

The `Webapp Zone` also holds two runtime datasets written by the plugin backend
(not by these recipes): `OWISMIND_PRD_V1_2_beta_owismind_webapp_events_v1` (usage
analytics) and `beta-owismind_webapp_traces_v2` (agent traces).

### Semantic models

- **revenue** (`Drive_Revenues_Semantic_Model`, `AHUh9hb`): 3 entities
  (`revenue_record`, `customer_account`, `commercial_offer`) all mapping to ONE
  physical table (`DRIVE_Revenues`, never JOIN), a `Total Revenue (EUR)` metric,
  named filters, golden queries, a glossary, and the SQL instructions (Phase=ACTUALS
  default; offer priority `Product > Solution > SolutionLine > sirano_product`;
  never-default-sirano + transparency; GROUP BY diamond_id, display Account_name +
  carrier_code). **Repointed to the clone dataset** (`datasetRef
  OWISMIND_PRD_V1_2.DRIVE_Revenues`, table `"OWISMIND_PRD_V1_2_drive_revenues"`) and
  the **`Solution` offer column re-added 2026-07-08**, VALIDATED in DSS. Readable
  snapshot: `genai/semantic-models/MODEL.md`.
- **tickets** (`TroubleTickets_Semantic_Model`, `dM4jA4G`): default metric
  `COUNT(DISTINCT id)`, `Duration_ticket_total` in minutes (AVG). Repoint script
  `genai/semantic-models/scripts/repoint_tickets_prod_clone.py` READY, simulated 4/4, not
  yet launched on the clone.

### Modes (model per turn)

`smart` (default) = `vertex_ai/gemini-3.1-flash-lite`; `pro` =
`vertex_ai/gemini-3.5-flash`; `claude` = `vertex_ai/claude-sonnet-4-6` (all with the
connection prefix `openai:LLM-7064-revforecast:`). One model drives the whole
turn (no escalation); the mode is propagated to the sub-agent; each semantic tool
stays on Sonnet in every mode (`v4oqA6R` revenue, `nEirlso` tickets).

## Folder map

| Path | What |
|---|---|
| `README.md` | Master guide: the repo <-> DSS map, architecture, Flow, models, tools, git model, contracts. |
| `genai/agents/` | The three Code Agent files (orchestrator + revenue + tickets sub-agents). Paste each into its DSS Code Agent (env 3.11). Ids baked into each CONFIG. |
| `genai/agent-tools/attribute_lookup_tool.py` | The `attribute_lookup` Custom Python tool (`UUoynaL`). |
| `flow/` | The Flow recipes per zone (`SalesDrive_Revenue_Expert/`, `CSC_ticket_AI_Agent/`, `Webapp_Zone/`) + `README.md` + `DATASETS.md`. Dataset IO comes from the DSS Flow wiring, not code constants. |
| `genai/semantic-models/` | Per-model `.v1.json` snapshots + `scripts/` (build / update / dump / drop / migrate / remap / repoint) + `MODEL.md` (readable live model) + `TOOL_DESCRIPTIONS.md`. |
| `registry.json` | The single manifest: ids, file paths, dataset names, model + tool binding, lookup config, guardrails. NOT imported at runtime. |
| `docs/PLAYBOOK_ADD_AGENT.md` | Ordered runbook to add a specialist (worked for tickets). Mostly automated by the v1.3 **agent factory**: `docs/AGENT_FACTORY.md` (deploy: `docs/DEPLOY_V1_3_DEV.md`). |
| `project-library/python/owismind_factory/` | The v1.3 agent factory engine package (pasted into the DSS project library). |
| `project-library/owismind_hub/` | Repo seeds of the Config & Prompt Hub (`/owismind_hub/` at the DSS library root): capabilities registry, orchestrator persona, factory settings; agents load them at start with embedded fallback. `regenerate_seeds.py` (repo-only) keeps them equivalent to the orchestrator defaults. |
| `notebooks/` | Factory runner notebooks 00-06 (probe, push hub, align clone, create domain, wizard, logging, doctor). |
| `webapps/agent-factory-console/` | The factory console (Standard webapp, optional; everything is also doable via notebooks). |
| `docs/` | Sub-project docs: `DEPLOY_V1_3_DEV.md` (deployment guide), `AGENT_FACTORY.md` (factory architecture), `CAPABILITY_MATRIX.md` (probe report), `PLAYBOOK_ADD_AGENT.md` (manual playbook). |
| `tests/` | DSS-free unit tests: `python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests`. |

## Rules you must not break

1. **P3 - no hardcoded business values** in agent logic. Everything comes from
   the profile / value index / Value_Catalog / human overrides. Unknown cases ->
   constrained LLM understanding (candidate list) or an honest refusal, never a
   value patch.
2. **Frozen contracts** (event kinds, the `semantic-model-query` span shape,
   `AGENT_RESULT`, `sql_id`, registry `block_labels`/`tool_labels` <-> sub-agent
   `KNOWN_*`, the profile contract v1). The webapp / Evidence depend on them.
   Never rename, only add. An anti-drift test guards the registry <-> sub-agent.
3. **Two callers, two tools, never crossed**: a sub-agent calls only its
   `*_semantic_query` tool; the orchestrator calls only `attribute_lookup`. The
   sub-agents are UNCHANGED by the lookup wiring (it is an orchestrator built-in).
4. **One enabled capability per business domain** (rollback = re-flip the flags).
5. **Standalone files**: agents import only stdlib + `dataiku` + `langgraph`
   (env 3.11); recipes may use pandas (design-time). No plugin import.
6. **LLM Mesh discipline** (see the skill): native completion API for reasoning +
   tool-calling; `with_json_output` is FORCED on the sub-agent's UNDERSTAND
   (deterministic extraction) and NEVER on the orchestrator (it disables
   reasoning in DSS 14).
7. **Dataiku safety**: read-only SQL, statement timeout, bounded parallelism,
   no raw-row data sent to the LLM. Ask before any deletion of a feature/dataset
   (lesson L087) or anything risky for the instance.
8. **Code + comments in English**; no em dash (U+2014) or en dash (U+2013)
   anywhere (project rule #9).
9. **Changes land through the next `-dev` branch, then promote by version.**
   Develop and validate a change on the current dev branch (`OWIsMind_PRD_V1_3-dev`),
   validate it in the DSS clone, then promote by **dropping the `-dev` suffix** so
   the validated dev branch becomes the new prod branch. Never paste an untested
   change into the live prod objects. Keep `registry.json` matching the
   orchestrator's CAPABILITIES.

## Deploy reminder

A change is deployed by **pasting the matching file** into its DSS Code Agent /
Custom Python tool (env 3.11 for Code Agents). The ids are baked into each file's
CONFIG; verify them against `README.md` / `registry.json`. Recipe changes deploy in
the Flow (refresh scenario). Agent-only changes need no zip upload; a `python-lib`
backend change does (upload the versioned zip + restart the backend).

**Version flow (git model).** The prod project IS the clone of DEV: there is no
hand-port between two DSS projects. New domains and changes are built on the next
`-dev` branch (`OWIsMind_PRD_V1_3-dev`), validated in the DSS clone, then promoted
to prod by dropping the `-dev` suffix (the dev branch becomes the new prod branch).
`main` is deprecated. See `README.md`, section "Regle de version git".

**Still pending in DSS:** (1) drop the stale `resolve_filter_value` precondition
from each `revenue_semantic_query` "Description for LLM" (corrected text in
`genai/semantic-models/TOOL_DESCRIPTIONS.md`); (2) delete the dead
`Drive_Revenues_resolve_filter_value` tool object (`aNxeOc4`); (3) finish the
**tickets** curation - launch `genai/semantic-models/scripts/repoint_tickets_prod_clone.py`
on the clone (repoints `TroubleTickets_Semantic_Model` `dM4jA4G` to the clone
dataset; simulated 4/4), apply the profile overrides (COUNT_DISTINCT id,
time=creationDate, Customer_id display Account_name, LD synonyms), re-dump the
`.v1.json`, then smoke-test tickets end-to-end (see `docs/PLAYBOOK_ADD_AGENT.md`).
