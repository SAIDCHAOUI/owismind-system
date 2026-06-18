# dataiku-agents - the OWIsMind agent system

> **What this folder is.** The complete, self-contained source of the OWIsMind
> agentic system that runs inside Dataiku DSS: an **orchestrator** + a **revenue
> sub-agent**, the **Flow recipes** that build the sub-agent's knowledge, and the
> **semantic model** that writes the SQL. This folder is the **source of truth**:
> every change is made HERE, then pasted back into the DSS Code Agents (never the
> other way around). Treat it like a small repo.
>
> **Before changing an agent, read the skill** `agentique-python-dataiku`
> (`.claude/skills/agentique-python-dataiku/SKILL.md`): the engineering reference
> for LangChain / LangGraph / Dataiku DSS (abstraction choice, Code Agents + LLM
> Mesh, tool design, structured output, tracing, safety, the Python 3.9 vs 3.11
> dual path).

---

## 0. Read order for a new Claude session

1. [`CLAUDE.md`](CLAUDE.md) (this folder) - orientation, the live inventory, frozen contracts, the rules you must not break.
2. This `README.md` - the full architecture, the Flow, deploy, extend, roadmap.
3. The skill `agentique-python-dataiku` - how to build/audit DSS agents safely.
4. `memory/PROJECT_STATE.md` + `memory/LESSONS.md` (repo root) - canonical ids and what really works (these PRIME over the cadrage guides).
5. Sub-folder READMEs for detail: [`agents/`](agents/README.md), [`recipes/`](recipes/README.md), [`tools/`](tools/README.md), [`tools/semantic_model/`](tools/semantic_model/MODEL.md).

To navigate the code ("where is X handled?"), query the knowledge graph first
(`graphify query "..."`), not a full re-read.

---

## 1. The system in one picture

```
DESIGN TIME (Flow - built once, refreshed by a scenario)
  DRIVE_Revenues ──► [recipe profile_dataset]     ──► DRIVE_Revenues_profile        the "business brain": metrics, scenarios, axes, synonyms   << sub-agent reads
                 ──► [recipe build_value_index]    ──► DRIVE_Revenues_value_index    the exact-value index used for grounding                   << sub-agent reads (SQL)
                 ──► [recipe build_value_catalog]  ──► DRIVE_Revenues_Value_Catalog  rich alias / variant catalog                               << attribute_lookup fallback reads
  (+ optional editable dataset DRIVE_Revenues_profile_overrides: human corrections to the profile)

RUNTIME (one chat turn)
  Vue web app ──► python-lib Flask backend ──► (agent whitelist resolves the id) ──► OWIsMind_orchestrator  (Code Agent, LangGraph, env 3.11)
                                                                                        │  agentic loop: REASON -> call tool(s) -> REASON -> ... -> write the answer
                                                                                        │  tools: ask_revenue_expert | attribute_lookup | show_chart | show_table | show_kpi | current_date
                                                                  ┌─────────────────────┴─────────────────────┐
                                            (fast value read)     ▼                                            ▼  (computed figures)
                                       attribute_lookup  (Custom Python tool)                     SalesDrive_revenue_expert  (Code Agent, LangGraph, env 3.11)  agent:bHrWLyOL
                                            │  one ILIKE over DRIVE_Revenues text columns             │  1. UNDERSTAND   1 LLM (strict JSON), prompt GENERATED from the profile
                                            │  + Value_Catalog alias fallback                         │  2. RESOLVE      ground terms by INLINE SQL on value_index (exact -> fuzzy) + ambiguity policy
                                            ▼                                                         │  3. QUERY        hand a grounded question to revenue_semantic_query (it writes + runs the SQL);
                                       PostgreSQL (read-only)                                         │                  technical failure -> FALLBACK to own read-only SQL templates
                                                                                                      │  4. RENDER       table + figures formatted BY CODE; "[Scope]" line; about_data answered from profile (0 SQL)
                                                                                                      ▼
                                                                              revenue_semantic_query (Semantic Model Query, id v4oqA6R)
                                                                                                      ▼
                                                                              Drive_Revenues_Semantic_Model (SQL) ──► PostgreSQL (read-only)
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

## 2. The two agents (detail: [`agents/README.md`](agents/README.md))

| Agent | File | DSS Code Agent | Role |
|---|---|---|---|
| Orchestrator | `agents/OWIsMind_orchestrator.py` | **OWIsMind_orchestrator** (env 3.11) | Chats, reasons, routes to specialist sub-agent(s), runs the `attribute_lookup` built-in for fast reads, renders chart/table/KPI, writes the analysis. Honesty firewall: never denies that data exists, never invents a figure. Bounded parallel fan-out (`MAX_PARALLEL_AGENTS = 3`). |
| Revenue sub-agent | `agents/SalesDrive_revenue_expert.py` | **SalesDrive_revenue_expert** (`agent:bHrWLyOL`, env 3.11) | Expert of `DRIVE_Revenues`. UNDERSTAND -> RESOLVE -> QUERY -> RENDER. Owns ALL revenue figures across every Phase (ACTUALS / BUDGET / FORECAST / Q3F / HLF). |

Both are **standalone files** (stdlib + `dataiku` + `langgraph` only, no plugin
import) pasted into a DSS Code Agent on the **Python 3.11 code env** (LangGraph
needs >= 3.10). LLM calls use the **native LLM Mesh** completion API so the
model's reasoning and tool-calling are honored (see the skill for why we never
force `with_json_output` on the orchestrator, and why we DO force it on the
sub-agent's UNDERSTAND).

---

## 3. The design-time Flow (detail: [`recipes/README.md`](recipes/README.md))

Four datasets, three recipes. All four are read by the runtime, each by a
different consumer.

| Dataset | Built by | Shape | Read at runtime by | Role |
|---|---|---|---|---|
| `DRIVE_Revenues` | source (Flow input) | 175,780 rows, 20 cols | semantic model (SQL); `attribute_lookup` (fact search) | The revenue base: Phase, offer hierarchy, account, amount_eur, year_month, ... |
| `DRIVE_Revenues_profile` | `recipes/profile_dataset_recipe.py` | `{key, payload}` (JSON, contract v1) | the **sub-agent** (UNDERSTAND + about_data) | The business brain: metrics, scenario column, time column, axes, synonyms, display pairs. Human-reviewable via an editable overrides dataset. |
| `DRIVE_Revenues_value_index` | `recipes/build_value_index_recipe.py` | `{column_name, value, value_norm, occurrences}` (approx. 3.6 k rows) | the **sub-agent** (RESOLVE, inline SQL) | Every distinct groundable value + normalized form. **Must live on the source SQL connection** (`SQL_owi`). |
| `DRIVE_Revenues_Value_Catalog` | `recipes/build_value_catalog_recipe.py` | 12 cols, approx. 4.9 k rows | `attribute_lookup` (alias fallback) | Rich alias/variant catalog (business concepts, short account names). Queried for "suggestions" when the fast search finds no exact match. |

The profile recipe sends the LLM **aggregated metadata only** (schema, stats,
low-cardinality enum values, a few samples), never raw rows.

**`DRIVE_Revenues` columns (20)**: `Phase`, `booking_type`, `SolutionLine`,
`Solution`, `Product`, `Account_name`, `Account_partner`, `distribution_type`,
`Parent_Group`, `carrier_code`, `year_month` (date), `amount_eur` (decimal),
`sales_entity`, `sales_zone`, `account_manager` (email), `area_manager` (email),
`sales_director` (email), `diamond_id`, `sirano_product`, `original_dataset`.

---

## 4. The DSS tools (detail: [`tools/README.md`](tools/README.md))

Three tool objects live in DSS, with two distinct callers.

| Tool (instance) | Type | Id | Called by | Status |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | the **sub-agent** (QUERY) | **yes - the SQL engine** |
| `attribute_lookup` | Custom Python (`tools/attribute_lookup_tool.py`) | (instance, resolved by name) | the **orchestrator** (built-in) | **created in DSS, wired as an orchestrator built-in** |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | nobody | **to be DELETED (superseded by `attribute_lookup`)** |

- `revenue_semantic_query` runs on its **OWN DSS-configured strong model**
  (`vertex_ai/claude-sonnet-4-6`) in **linear pipeline mode (Agent mode OFF)**, so
  offer/column resolution stays strong in every orchestration tier. It writes AND
  runs the SQL against `Drive_Revenues_Semantic_Model`. Live config and the
  corrected "Description for LLM" to paste are in [`tools/README.md`](tools/README.md).
- `attribute_lookup` is an **orchestrator built-in** (appended in
  `build_tool_specs`, dispatched inline in `node_tools`), so it touches NO frozen
  `KNOWN_*` contract and the sub-agent is UNCHANGED. The model passes a logical
  DOMAIN, the orchestrator resolves it to a whitelisted dataset via the registry.
- `dataset_lookup` (managed, `9FEzVZk`) was **removed 2026-06-18**; it no longer
  exists in DSS or code.

Grounding inside the sub-agent is **not** a tool: it runs inline read-only SQL on
`DRIVE_Revenues_value_index`. The timeline labels `resolve_filter_value` /
`dataset_sql_query` are frozen EVENT names (not tool calls).

---

## 5. Which model where (modes)

Model-agnostic by design: one model drives the whole turn, picked by the user's
mode. No mid-turn escalation. The same mode is propagated to the sub-agent.

| Mode | Model id (LLM Mesh) | Notes |
|---|---|---|
| `eco` (default) | `...vertex_ai/gemini-3.1-flash-lite` | Cheap, fast, good. Live narration OFF (the deterministic ticker covers the wait). |
| `medium` | `...vertex_ai/gemini-3.5-flash` | Stronger; narrates alongside tool calls. |
| `high` | `...vertex_ai/claude-sonnet-4-6` | Orchestrator AND sub-agent. Max quality. |

All ids carry the connection prefix `openai:LLM-7064-revforecast:`. Configure them
in `LOOP_LLM_BY_MODE` (orchestrator) and `LLM_BY_MODE` (sub-agent) - they must
match an id exposed by the LLM Mesh connection; **verify `GEMINI_FLASH_LITE_ID`
and `GEMINI_FLASH_ID` before deploy** (a wrong eco id breaks the default mode).

The **Semantic Model Query tool** keeps writing the SQL on Sonnet in EVERY mode
(`SEMANTIC_TOOL_ID_BY_MODE` maps all three to `v4oqA6R`), so offer/column
resolution stays strong regardless of the orchestration tier.

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
  one row per column (see `recipes/profile_dataset_recipe.py` docstring).
- **Result caps** mirrored across files: 50 rows x 50 cols x 256 chars/cell x 64k JSON.
- **One enabled capability per business domain** (a second revenue agent must
  flip the first to `enabled=False`).

---

## 7. Deploy / update procedure

Repo is the source of truth; DSS direct edits are overwritten on the next paste.

1. Edit the file(s) here, run the tests (`python3 -m unittest discover -s dataiku-agents/tests`).
2. **Re-paste the Code Agent(s) that changed** on the **Python 3.11** code env:
   `agents/OWIsMind_orchestrator.py` into **OWIsMind_orchestrator**,
   `agents/SalesDrive_revenue_expert.py` into **SalesDrive_revenue_expert**. When
   a fix lives on both sides (a frozen contract), re-paste both.
3. Check the CONFIG ids match the instance: `GEMINI_FLASH_LITE_ID` /
   `GEMINI_FLASH_ID` / `SONNET_ID`, `SEMANTIC_TOOL_ID` (`v4oqA6R`),
   `agent_id` (`agent:bHrWLyOL`), and optionally `LOOKUP_TOOL_ID` (else name fallback).
4. Optional: set `source_url` on the `revenue_expert` capability (orchestrator
   registry) to the Dataiku `DRIVE_Revenues` dataset URL - Evidence then turns the
   data source into a clickable link. It is empty today (link inactive).
5. If the **plugin backend** (`python-lib`) changed too, rebuild + upload the zip
   and **restart the webapp backend**. (Agent-only changes need NO zip upload.)

The Flow recipes are deployed as Python recipes in the DSS Flow (see
`recipes/README.md`); a refresh scenario keeps the profile + index + catalog
fresh, no re-paste needed.

### Pending DSS steps for the current state (2026-06-18)

- Update the `revenue_semantic_query` tool's **"Description for LLM"** (drop the
  stale `resolve_filter_value` precondition; the corrected text is in
  [`tools/README.md`](tools/README.md)).
- **Re-paste the ORCHESTRATOR** so the `attribute_lookup` built-in wiring is live;
  optionally set `LOOKUP_TOOL_ID`.
- **Delete** the `Drive_Revenues_resolve_filter_value` tool object (no longer used).

---

## 8. Add a new dataset / domain (e.g. tickets, CSAT)

1. Flow: wire the **same recipes** on the new dataset -> `X_profile` + `X_value_index`
   (+ `X_Value_Catalog` if you want the alias fallback).
2. Human-review the profile via an editable overrides dataset.
3. Duplicate the Dataset Expert Code Agent, change the two dataset names in its CONFIG.
4. Orchestrator: add **one** entry to `CAPABILITIES` (copy `revenue_expert`,
   adapt `agent_id` / labels / `domain` / `lookup_dataset` / `lookup_catalog`).
   The domains `tickets`, `satisfaction`, etc. already exist in `BUSINESS_DOMAINS`,
   so the honest capability-gap message closes itself, and the new dataset becomes
   searchable by `attribute_lookup` automatically (it declared `lookup_dataset`).
5. With two staffed domains, "360" questions fan out in parallel and the
   orchestrator's synthesis cites each source.

---

## 9. Roadmap (decided, deferred)

- **Set `LOOKUP_TOOL_ID`** to the real `attribute_lookup` id (small polish; the
  name fallback works meanwhile).
- **Fill `source_url`** on the revenue capability to enable the clickable Evidence
  data-source link.
- **Version the semantic model JSON**: run `tools/semantic_model/dump_semantic_model.py`
  to commit `Drive_Revenues_Semantic_Model.v1.json`, and keep aligning the model
  config via `update_aligned_semantic_model.py` (Phase=ACTUALS, offer hierarchy,
  transparency, golden queries).
- **Tickets agent**: 2 recipes + 1 Code Agent + 1 registry entry unlocks the
  parallel 360.

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
- **Tests**: `python3 -m unittest discover -s dataiku-agents/tests` (profiler +
  dataset-expert + langgraph + attribute_lookup). DSS-free.
