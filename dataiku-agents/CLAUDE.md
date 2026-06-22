# CLAUDE.md - dataiku-agents/

> Orientation for any Claude session touching the agent system, written to be
> self-sufficient: read this and you understand how the OWIsMind agents work
> without anyone pasting code. Full architecture: [`README.md`](README.md).
> Engineering reference for building agents safely: the skill
> `agentique-python-dataiku`. Project memory (source of truth, PRIMES over the
> cadrage guides): `memory/PROJECT_STATE.md` + `memory/LESSONS.md`.

## What this is

OWIsMind is the internal data assistant of Orange Wholesale International, running
as agents inside Dataiku DSS and used through a Vue web app. This folder is the
**source of truth** for those agents: an **orchestrator** that chats and routes,
a **revenue sub-agent** expert of `DRIVE_Revenues`, a second **tickets sub-agent**
(being built), the **Flow recipes** that fabricate the sub-agents' knowledge, and
the **semantic models** that write the SQL. You edit HERE, then paste back into the
DSS Code Agents (env 3.11); DSS direct edits are overwritten on the next paste.

## Two DSS projects, one design - develop in DEV, promote to PROD

The agents live in **two Dataiku projects** with the **same design** but
**different object ids**. The code is split accordingly under
[`OWISMIND/`](OWISMIND/README.md), one complete ready-to-paste copy per project,
every deployable file **prefixed with the project key**:

```
OWISMIND/
  README.md                 <- the DEV->PROD workflow + the full id map (read this)
  OWISMIND_DEV/             develop + validate HERE first  (revenue + tickets)
    OWISMIND_DEV_OWIsMind_orchestrator.py / _SalesDrive_revenue_expert.py /
    _CSSO_Trouble_Tickets_Expert.py / _attribute_lookup_tool.py
    registry.json  recipes/  semantic_model/
  OWISMIND_PROD_V1/         promote here once DEV is good  (revenue only, no tickets yet)
    OWISMIND_PROD_V1_OWIsMind_orchestrator.py / _SalesDrive_revenue_expert.py /
    _attribute_lookup_tool.py
    registry.json  recipes/  semantic_model/
  migrate_semantic_model_to_project.py  remap_semantic_model.py   (cross-project utils)
```

**Workflow:** make every change in `OWISMIND_DEV`, paste into the DEV DSS objects,
validate; then port the same change into the matching `OWISMIND_PROD_V1_*` file
(PROD ids already baked in) and paste into PROD. Never edit PROD untested. The
tickets agent is the live example: finished in DEV, intentionally **absent from
PROD** until validated. The **per-project id map** is in
[`OWISMIND/README.md`](OWISMIND/README.md) and each `registry.json`.

## The mechanism, end to end (one chat turn)

```
Vue web app
   │  user message + a logical agent key (never a raw agent id)
   ▼
python-lib Flask backend  (repo root, not this folder)
   │  resolves the key against a server-side whitelist -> the orchestrator Code Agent
   │  invokes it over LLM Mesh, streams timeline events back (polling-via-thread)
   ▼
OWIsMind_orchestrator  (LangGraph Code Agent, "sub-agents as tools")
   │  ONE model drives the whole turn (picked by the user's mode: eco/medium/high).
   │  It REASONS, then on the SAME turn either:
   │    - calls attribute_lookup (built-in)  for a fast value read, OR
   │    - calls ask_revenue_expert           to delegate a computed figure, OR
   │    - renders the last result (show_chart / show_table / show_kpi), then writes the analysis.
   │  Honesty firewall: it holds NO business data, never invents or denies a figure;
   │  it may only admit "no AGENT for this domain", never "the data is missing".
   ├──────────────────────────────┬──────────────────────────────────────────────┐
   ▼ (fast read)                   ▼ (computed figure, slow)                       │
attribute_lookup                SalesDrive_revenue_expert  (LangGraph Code Agent)  │
  Custom Python tool              UNDERSTAND -> RESOLVE -> QUERY -> RENDER          │
  one ILIKE over DRIVE_Revenues     1. UNDERSTAND : 1 LLM (strict JSON), prompt     │
  text columns; Value_Catalog          generated from the profile                  │
  alias fallback; read-only         2. RESOLVE   : ground user terms by INLINE      │
                                       read-only SQL on value_index (exact->fuzzy)  │
                                    3. QUERY     : hand a grounded question to       │
                                       revenue_semantic_query -> it writes+runs SQL │
                                       (technical failure -> own direct-SQL fallback)│
                                    4. RENDER    : table + figures by code, "[Scope]"│
                                       line; about_data answered from profile (0 SQL)│
                                          │                                          │
                                          ▼                                          │
                                  revenue_semantic_query (Semantic Model Query tool) │
                                          ▼                                          │
                                  Drive_Revenues semantic model -> PostgreSQL (read-only)
```

Everything the user sees as a figure is SQL-grounded: the orchestrator cannot
invent a number because it owns none. Work shows live on the timeline; executed
SQL surfaces in the Evidence panel (every SQL emits a `semantic-model-query` span).

## Live inventory (per project - full id map in OWISMIND/README.md)

### Code Agents (env 3.11)

| Code Agent | File (per project) | DEV id | PROD id |
|---|---|---|---|
| OWIsMind_orchestrator | `OWISMIND_<PROJ>_OWIsMind_orchestrator.py` | `038G7mlF` | `Xrv7GvfG` |
| SalesDrive_revenue_expert | `OWISMIND_<PROJ>_SalesDrive_revenue_expert.py` | `bHrWLyOL` | `uO5hEzAs` |
| CSSO_Trouble_Tickets_Expert | `OWISMIND_DEV_CSSO_Trouble_Tickets_Expert.py` | `NcE9LD2i` (being built) | not in PROD yet |

### DSS agent tools

| Tool | Type | DEV id | PROD id | Called by |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | `sgk5pfln` | the **revenue sub-agent** (QUERY) |
| `tickets_semantic_query` | Semantic Model Query | `nEirlso` | not in PROD yet | the **tickets sub-agent** (QUERY) |
| `attribute_lookup` | Custom Python (`OWISMIND_<PROJ>_attribute_lookup_tool.py`) | `UUoynaL` | `szOZCoU` | the **orchestrator** (built-in, both domains) |

`Drive_Revenues_resolve_filter_value` (old Custom Python, called by nobody) is
**TO DELETE** in both projects (superseded by `attribute_lookup`). `dataset_lookup`
(managed, `9FEzVZk`) was already removed. The names `resolve_filter_value` /
`dataset_sql_query` survive only as frozen **timeline event labels** in the
sub-agent (`KNOWN_TOOL_NAMES`), not as tool calls.

Each `revenue_semantic_query` runs **Agent mode OFF (linear SQL pipeline)**, LLM
`vertex_ai/claude-sonnet-4-6`, embedding `vertex_ai/text-embedding-005`, access
datasets as the calling user. Its DSS "Description for LLM" must drop the stale
`resolve_filter_value` precondition (corrected text in the semantic_model README).

### Datasets (Flow, design time -> read at runtime; same names in both projects)

| Dataset | Built by (per-project `recipes/`) | Read at runtime by | Role |
|---|---|---|---|
| `DRIVE_Revenues` | source (175,780 rows, 19 cols) | semantic model (SQL); `attribute_lookup` | the revenue base |
| `DRIVE_Revenues_profile` | `profile_dataset_recipe.py` | revenue sub-agent (UNDERSTAND, about_data) | business brain (`{key, payload}` v1) |
| `DRIVE_Revenues_value_index` | `build_value_index_recipe.py` | revenue sub-agent (RESOLVE, inline SQL) | exact-value grounding; MUST be on the SQL connection |
| `DRIVE_Revenues_Value_Catalog` | `build_value_catalog_recipe.py` | `attribute_lookup` (alias fallback) | rich alias / suggestions catalog |
| `TroubleTickets_year` (+ `_profile`, `_value_index`, `_value_catalogue`) | the same three recipes (generic path) | tickets sub-agent / `attribute_lookup` | the incident-tickets base (DEV only, being built) |

### Semantic models

- **revenue**: 3 entities (`revenue_record`, `customer_account`, `commercial_offer`)
  all mapping to ONE physical table (`DRIVE_Revenues`, never JOIN), a
  `Total Revenue (EUR)` metric, named filters, golden queries, a glossary, and the
  SQL instructions (Phase=ACTUALS default; offer priority Product > SolutionLine >
  sirano_product, the `Solution` level was removed; never-default-sirano +
  transparency; GROUP BY diamond_id, display Account_name + carrier_code). DEV =
  `Drive_Revenues_Semantic_Model` (`AHUh9hb`); PROD = `Drive_Revenues_Model`
  (`a7K9jYk`). Readable snapshot: each project's
  `semantic_model/MODEL.md`.
- **tickets** (DEV only, being built): `TroubleTickets_Semantic_Model` (`dM4jA4G`).

### Modes (model per turn)

`eco` (default) = `vertex_ai/gemini-3.1-flash-lite`; `medium` =
`vertex_ai/gemini-3.5-flash`; `high` = `vertex_ai/claude-sonnet-4-6` (all with the
connection prefix `openai:LLM-7064-revforecast:`). One model drives the whole
turn (no escalation); the mode is propagated to the sub-agent; the semantic tool
stays on Sonnet in every mode.

## Folder map

| Path | What |
|---|---|
| `README.md` | Master guide: architecture, Flow, models, deploy, extend, roadmap, contracts. |
| [`OWISMIND/README.md`](OWISMIND/README.md) | The DEV->PROD workflow + the full per-project id map. **Start here for deploy.** |
| `OWISMIND/OWISMIND_DEV/` , `OWISMIND/OWISMIND_PROD_V1/` | One complete, prefixed, ready-to-paste copy per project: the 3-or-4 deployable files + `registry.json` + `recipes/` + `semantic_model/`. |
| `OWISMIND/<PROJ>/registry.json` | Per-project DEV-OWNED manifest: ids, dataset names, model + tool binding, lookup config, guardrails. NOT imported at runtime. |
| `OWISMIND/<PROJ>/recipes/` | The three Flow recipes (profile, value index, value catalog). Dataset-agnostic, identical across projects. |
| `OWISMIND/<PROJ>/semantic_model/` | Build/update/dump/drop scripts (per-project ids) + `MODEL.md` (readable live model). |
| `OWISMIND/migrate_…` , `remap_…` | Cross-project promotion utilities (copy / repoint a semantic model DEV->PROD). |
| `DATASETS.md` | Canonical column inventory per dataset. |
| `PLAYBOOK_ADD_AGENT.md` | Ordered runbook to add a specialist (worked for tickets). |
| `tests/` | DSS-free unit tests, run against the **DEV** copies: `python3 -m unittest discover -s dataiku-agents/tests`. |

## Rules you must not break

1. **P3 - no hardcoded business values** in agent logic. Everything comes from
   the profile / value index / Value_Catalog / human overrides. Unknown cases ->
   constrained LLM understanding (candidate list) or an honest refusal, never a
   value patch.
2. **Frozen contracts** (event kinds, the `semantic-model-query` span shape,
   `AGENT_RESULT`, `sql_id`, registry `block_labels`/`tool_labels` <-> sub-agent
   `KNOWN_*`, the profile contract v1). The webapp / Evidence depend on them.
   Never rename, only add. An anti-drift test guards the registry <-> sub-agent.
3. **Two callers, two tools, never crossed**: the sub-agent calls only
   `revenue_semantic_query`; the orchestrator calls only `attribute_lookup`. The
   sub-agent is UNCHANGED by the lookup wiring (it is an orchestrator built-in).
4. **One enabled capability per business domain** (rollback = re-flip the flags).
5. **Standalone files**: agents import only stdlib + `dataiku` + `langgraph`
   (env 3.11); recipes may use pandas (design-time). No plugin import.
6. **LLM Mesh discipline** (see the skill): native completion API for reasoning +
   tool-calling; `with_json_output` is FORCED on the sub-agent's UNDERSTAND
   (deterministic extraction) and NEVER on the orchestrator (it disables
   reasoning in DSS 14).
7. **Dataiku safety**: read-only SQL, statement timeout, bounded parallelism,
   no raw-row data sent to the LLM. Conseil avant toute suppression de
   feature/dataset (lesson L087). Ask before anything risky for the instance.
8. **Code + comments in English**; no em dash (U+2014) or en dash (U+2013)
   anywhere (project rule #9).
9. **DEV before PROD**: never paste an untested change into a PROD object. Keep
   the DEV and PROD copies in sync only through the deliberate promotion step, and
   keep each `registry.json` matching its orchestrator's CAPABILITIES.

## Deploy reminder

A change is deployed by **pasting the matching `OWISMIND_<PROJ>_*` file** into its
DSS Code Agent / Custom Python tool (env 3.11 for Code Agents). The ids are already
baked into each file's CONFIG + deploy-target header; verify them against
[`OWISMIND/README.md`](OWISMIND/README.md) / the project `registry.json`. Recipe
changes deploy in the Flow (refresh scenario). Agent-only changes need no zip
upload; a `python-lib` backend change does (upload zip + restart backend).

**Promotion DEV -> PROD:** validate in DEV, then copy the change into the
`OWISMIND_PROD_V1_*` twin (PROD ids already set) and paste into PROD.

**Still pending in DSS:** (1) drop the stale `resolve_filter_value` precondition
from each `revenue_semantic_query` "Description for LLM"; (2) delete the dead
`Drive_Revenues_resolve_filter_value` tool object in both projects; (3) finish the
**tickets agent in DEV** (see [`PLAYBOOK_ADD_AGENT.md`](PLAYBOOK_ADD_AGENT.md):
profile + value_index + COUNT default metric, create `TroubleTickets_Semantic_Model`
and inject the brain, create the `tickets_semantic_query` tool, create the
`CSSO_Trouble_Tickets_Expert` Code Agent, re-paste the DEV orchestrator), then
promote tickets to PROD with PROD ids. Order matters: in DEV, fill the real tickets
`agent_id` (and create the Code Agent) BEFORE re-pasting the orchestrator, or set
`enabled:False` first (honest capability-gap via `BUSINESS_DOMAINS`).
