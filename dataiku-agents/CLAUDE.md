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
a **revenue sub-agent** that is an expert of one dataset (`DRIVE_Revenues`), the
**Flow recipes** that fabricate the sub-agent's knowledge, and the **semantic
model** that writes the SQL. You edit HERE, then paste back into the DSS Code
Agents (env 3.11); DSS direct edits are overwritten on the next paste.

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
  Custom Python tool              agent:bHrWLyOL                                   │
  one ILIKE over DRIVE_Revenues   UNDERSTAND -> RESOLVE -> QUERY -> RENDER         │
  text columns; Value_Catalog       1. UNDERSTAND : 1 LLM (strict JSON), prompt    │
  alias fallback; read-only            generated from the profile                 │
                                    2. RESOLVE   : ground user terms by INLINE     │
                                       read-only SQL on value_index (exact->fuzzy) │
                                    3. QUERY     : hand a grounded question to      │
                                       revenue_semantic_query -> it writes+runs SQL │
                                       (technical failure -> own direct-SQL fallback)│
                                    4. RENDER    : table + figures by code, "[Scope]"│
                                       line; about_data answered from profile (0 SQL)│
                                          │                                          │
                                          ▼                                          │
                                  revenue_semantic_query (Semantic Model Query, v4oqA6R)
                                          ▼                                          │
                                  Drive_Revenues_Semantic_Model -> PostgreSQL (read-only)
```

Everything the user sees as a figure is SQL-grounded: the orchestrator cannot
invent a number because it owns none. Work shows live on the timeline; executed
SQL surfaces in the Evidence panel (every SQL emits a `semantic-model-query` span).

## Live inventory (what exists in DSS, what it does, who uses it)

### Code Agents (env 3.11)

| Code Agent | File | Id | Role |
|---|---|---|---|
| OWIsMind_orchestrator | `agents/OWIsMind_orchestrator.py` | (orchestrator) | Chat, reason, route, fast-lookup, render, write the analysis. |
| SalesDrive_revenue_expert | `agents/SalesDrive_revenue_expert.py` | `agent:bHrWLyOL` | Expert of `DRIVE_Revenues`. All revenue figures, every Phase. |

### DSS agent tools (3 objects)

| Tool | Type | Id | Called by | Status |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | the **sub-agent** (QUERY) | **LIVE - the SQL engine** |
| `attribute_lookup` | Custom Python (`tools/attribute_lookup_tool.py`) | resolved by name | the **orchestrator** (built-in) | tool object **created in DSS**; the built-in wiring goes live after the next **orchestrator re-paste** |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | nobody | **TO DELETE (superseded)** |

So among the 3 tool objects: 2 live (`revenue_semantic_query`,
`attribute_lookup`) + 1 dead pending delete (`resolve_filter_value`).

`dataset_lookup` (managed, `9FEzVZk`) was **REMOVED 2026-06-18** (no longer in DSS
or code). The names `resolve_filter_value` / `dataset_sql_query` survive only as
frozen **timeline event labels** in the sub-agent (`KNOWN_TOOL_NAMES`), not as
tool calls.

`revenue_semantic_query` live config (DSS, source of truth): project
`OWISMIND_DEV`, model `Drive_Revenues_Semantic_Model` (version Active = v1), LLM
`vertex_ai/claude-sonnet-4-6`, embedding `vertex_ai/text-embedding-005`, **Agent
mode OFF (linear SQL pipeline)**, access datasets as the calling user. Its DSS
"Description for LLM" is STALE (references the deleted resolver) and must be
updated (corrected text in [`tools/README.md`](tools/README.md)).

### Datasets (Flow, design time -> read at runtime)

| Dataset | Built by | Read at runtime by | Role |
|---|---|---|---|
| `DRIVE_Revenues` | source (175,780 rows, 20 cols) | semantic model (SQL); `attribute_lookup` (fact search) | the revenue base |
| `DRIVE_Revenues_profile` | `recipes/profile_dataset_recipe.py` | the **sub-agent** (UNDERSTAND, about_data) | the business brain (`{key, payload}`, contract v1) |
| `DRIVE_Revenues_value_index` | `recipes/build_value_index_recipe.py` | the **sub-agent** (RESOLVE, inline SQL) | exact-value grounding; MUST be on the SQL connection |
| `DRIVE_Revenues_Value_Catalog` | `recipes/build_value_catalog_recipe.py` | `attribute_lookup` (alias fallback) | rich alias / suggestions catalog |

### Semantic model

`Drive_Revenues_Semantic_Model` (v1, Active): 3 entities (`revenue_record`,
`customer_account`, `commercial_offer`) all mapping to ONE physical table
(`DRIVE_Revenues`, never JOIN), a `Total Revenue (EUR)` metric, named filters,
9 golden queries, a glossary, and the SQL-generation instructions (Phase=ACTUALS
default; offer **resolution priority** = most granular first, Product then
Solution then SolutionLine then sirano_product, i.e. the reverse of the breadth
order SolutionLine to Product, with never-default-sirano + transparency; GROUP BY
diamond_id displaying Account_name + carrier_code). Readable snapshot: [`tools/semantic_model/MODEL.md`](tools/semantic_model/MODEL.md).
It was built as the aligned rebuild of the old model `2O2KcHw` (kept as rollback).

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
| `agents/` | The two Code Agents (LangGraph) + [`agents/README.md`](agents/README.md). |
| `recipes/` | The three Flow recipes (profile, value index, value catalog) + [`recipes/README.md`](recipes/README.md). |
| `tools/` | Doc of the DSS agent tools + the `attribute_lookup` Custom Python code + [`tools/README.md`](tools/README.md). |
| `tools/semantic_model/` | Build/update/dump scripts + [`MODEL.md`](tools/semantic_model/MODEL.md) (the live model, readable) + [`README.md`](tools/semantic_model/README.md). |
| `tests/` | DSS-free unit tests: `python3 -m unittest discover -s dataiku-agents/tests`. |

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

## Deploy reminder

After any change: re-paste the Code Agent(s) that changed (env 3.11), verify the
CONFIG ids (`GEMINI_*_ID`, `SEMANTIC_TOOL_ID=v4oqA6R`, `agent_id=agent:bHrWLyOL`,
optionally `LOOKUP_TOOL_ID`). Recipe changes deploy in the Flow (refresh scenario).
Agent-only changes need no zip upload; a `python-lib` backend change does (upload
zip + restart backend).

**Pending DSS steps for the current state (2026-06-18):** (1) update the
`revenue_semantic_query` "Description for LLM" (drop the `resolve_filter_value`
precondition); (2) re-paste the ORCHESTRATOR so the `attribute_lookup` built-in is
live (optionally set `LOOKUP_TOOL_ID`); (3) delete the
`Drive_Revenues_resolve_filter_value` tool object.
