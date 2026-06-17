# dataiku-agents - the OWIsMind agent system

> **What this folder is.** The complete, self-contained source of the OWIsMind
> agentic system that runs inside Dataiku DSS: an **orchestrator** + a **revenue
> sub-agent**, the **Flow recipes** that build the sub-agent's knowledge, and the
> **semantic model** scripts. This folder is the **source of truth**: every change
> is made HERE, then pasted back into the DSS Code Agents (never the other way
> around). Treat it like a small repo.
>
> **Before changing an agent, read the skill** `agentique-python-dataiku`
> (`.claude/skills/agentique-python-dataiku/SKILL.md`): it is the engineering
> reference for LangChain / LangGraph / Dataiku DSS (abstraction choice, Code
> Agents + LLM Mesh, tool design, structured output, tracing, safety, the
> Python 3.9 vs 3.11 dual path). It exists so we build agents that are safe and
> respect Dataiku best practices.

---

## 0. Read order for a new Claude session

1. `CLAUDE.md` (this folder) - orientation, frozen contracts, the rules you must not break.
2. This `README.md` - the full architecture, the Flow, deploy, extend, roadmap.
3. The skill `agentique-python-dataiku` - how to build/audit DSS agents safely.
4. `memory/PROJECT_STATE.md` + `memory/LESSONS.md` (repo root) - canonical ids and what really works (these PRIME over the cadrage guides).
5. Sub-folder READMEs for detail: [`agents/`](agents/README.md), [`recipes/`](recipes/README.md), [`tools/`](tools/README.md), [`semantic_model/`](semantic_model/README.md).

To navigate the code ("where is X handled?"), query the knowledge graph first
(`graphify query "..."`), not a full re-read.

---

## 1. The system in one picture

```
DESIGN TIME (Flow - built once, refreshed by a scenario)
  DRIVE_Revenues ──► [recipe profile_dataset]     ──► DRIVE_Revenues_profile        (the "business brain": metrics, scenarios, axes, synonyms)
                 ──► [recipe build_value_index]    ──► DRIVE_Revenues_value_index    (the exact-value index used for grounding)   << USED BY v3
                 ──► [recipe build_value_catalog]  ──► DRIVE_Revenues_Value_Catalog  (rich alias/variant catalog)                 << ROADMAP only, not wired in v3
  (+ optional editable dataset DRIVE_Revenues_profile_overrides: human corrections to the profile)

RUNTIME (one chat turn)
  WebApp ──► OWIsMind_orchestrator  (Code Agent, LangGraph, env 3.11)
                │  agentic loop: REASON -> call tool(s) -> REASON -> ... -> write the answer
                │  tools: ask_revenue_expert | show_chart | show_table | show_kpi | current_date
                ▼
            SalesDrive_revenue_expert  (Code Agent, LangGraph StateGraph, env 3.11)   agent:bHrWLyOL
                │  1. UNDERSTAND   1 LLM (strict JSON), prompt GENERATED from the profile
                │  2. RESOLVE      ground user terms by INLINE SQL on DRIVE_Revenues_value_index (exact -> fuzzy) + ambiguity policy
                │  3. QUERY        SQL_ENGINE="semantic_tool": hand a maximally grounded question to the Semantic Model Query tool
                │                  (it writes + runs the SQL); technical failure -> FALLBACK to own read-only SQL templates
                │                  ("lookup" intent: a plain attribute read via the Dataset Lookup tool)
                │  4. RENDER       table + figures formatted BY CODE; numbers verified; "about_data" answered from the profile (0 SQL)
                ▼
            DSS tools:  revenue_semantic_query (Semantic Model Query, id v4oqA6R)   << the SQL powerhouse
                        dataset_lookup        (Dataset Lookup, id 9FEzVZk)          << plain attribute reads (to be replaced, see Roadmap)
                ▼
            Semantic Model (SQL) ──► PostgreSQL (read-only transaction)
```

The orchestrator never holds business data: every figure comes from a sub-agent
(SQL-grounded), so it structurally cannot invent a number. The sub-agent shows
its reasoning live on the webapp timeline and surfaces the executed SQL in the
Evidence panel.

---

## 2. The two agents (detail: [`agents/README.md`](agents/README.md))

| Agent | File | DSS Code Agent | Role |
|---|---|---|---|
| Orchestrator | `agents/OWIsMind_orchestrator.py` | **OWIsMind_orchestrator** (env 3.11) | Chats, reasons, routes to specialist sub-agent(s), renders chart/table/KPI, writes the analysis. Honesty firewall: never denies that data exists, never invents a figure. Bounded parallel fan-out. |
| Revenue sub-agent | `agents/SalesDrive_revenue_expert.py` | **SalesDrive_revenue_expert** (`agent:bHrWLyOL`, env 3.11) | Expert of `DRIVE_Revenues`. UNDERSTAND -> RESOLVE -> QUERY -> RENDER. Owns ALL revenue figures across every Phase (ACTUALS / BUDGET / FORECAST / Q3F / HLF). |

Both are **standalone files** (stdlib + `dataiku` + `langgraph` only, no plugin
import) pasted into a DSS Code Agent on the **Python 3.11 code env** (LangGraph
needs >= 3.10). LLM calls use the **native LLM Mesh** completion API so the
model's reasoning and tool-calling are honored (see the skill for why we never
force `with_json_output` on the orchestrator, and why we DO force it on the
sub-agent's UNDERSTAND).

---

## 3. The design-time Flow (detail: [`recipes/README.md`](recipes/README.md))

Four datasets, three recipes. The sub-agent reads three of them at runtime; the
fourth (`Value_Catalog`) is built for the roadmap and is not wired into v3 yet.

| Dataset | Built by | Shape | Used by v3? | Role |
|---|---|---|---|---|
| `DRIVE_Revenues` | source (Flow input) | ~175 k rows, 20 cols | yes (queried by the semantic model) | The revenue base: Phase, Solution hierarchy, Account, amount_eur, year_month, ... |
| `DRIVE_Revenues_profile` | `recipes/profile_dataset_recipe.py` | `{key, payload}` (JSON) | yes (UNDERSTAND + about_data) | The business brain: metrics, scenario column, time column, axes, synonyms, display pairs. Human-reviewable via an editable overrides dataset. |
| `DRIVE_Revenues_value_index` | `recipes/build_value_index_recipe.py` | `{column_name, value, value_norm, occurrences}` ~3.6 k rows | **yes (RESOLVE grounds here)** | Every distinct groundable value + normalized form. **Must live on the source SQL connection** (the agent queries it in SQL at runtime). |
| `DRIVE_Revenues_Value_Catalog` | `recipes/build_value_catalog_recipe.py` | 12 cols, ~4.9 k rows | **no (roadmap)** | Rich alias/variant catalog (business concepts, short account names). Read by the Custom Python resolver tool, see Roadmap. |

The profile recipe sends the LLM **aggregated metadata only** (schema, stats,
low-cardinality enum values, a few samples), never raw rows.

---

## 4. The sub-agent's tools (detail: [`tools/README.md`](tools/README.md))

The sub-agent calls **two** DSS tools at runtime; the third tool exists in the
instance but is not wired into v3.

| Tool (instance) | Type | Id | Role | Used by v3? |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | Writes AND runs the SQL from a grounded natural-language question. The SQL powerhouse. Runs on its own DSS-configured strong model (Sonnet) in every mode. | **yes (default engine)** |
| `dataset_lookup` | Dataset Lookup (managed) | `9FEzVZk` | Plain attribute read for the `lookup` intent ("who is the account manager of X?"). EQUALS / AND / OR, ~10 rows. | yes (lookup intent) |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | Resolves a typed term to an exact (column, value) using the rich `Value_Catalog`. | **no (roadmap)** |

Grounding in v3 is **not** a tool: the sub-agent runs inline read-only SQL on
`DRIVE_Revenues_value_index` (the `resolve_filter_value` / `dataset_sql_query`
names you see are timeline event labels, not tool calls).

---

## 5. Which model where (modes)

Model-agnostic by design: one model drives the whole turn, picked by the user's
mode. No mid-turn escalation. The same mode is propagated to the sub-agent.

| Mode | Model (LLM Mesh) | Notes |
|---|---|---|
| `eco` (default) | Gemini 3.1 Flash-Lite (`...vertex_ai/gemini-3.1-flash-lite`) | Cheap, fast, good. Live narration OFF (the deterministic ticker covers the wait). |
| `medium` | Gemini 3.5 Flash | Stronger; narrates alongside tool calls. |
| `high` | Claude Sonnet 4.6 | Orchestrator AND sub-agent AND the semantic model. Max quality. |

The **Semantic Model Query tool** writes the SQL on its OWN DSS-configured model
(Sonnet) in every mode, so offer/column resolution stays strong regardless of
the orchestration tier. Configure model ids in `LOOP_LLM_BY_MODE` (orchestrator)
and `LLM_BY_MODE` (sub-agent) - they must match an id exposed by the LLM Mesh
connection.

---

## 6. Frozen contracts (the webapp / Evidence depend on these - never rename, only add)

- **Orchestrator event kinds**: `START, PLANNING, CALLING_AGENT, AGENT_DONE,
  RUNNING_TOOL, TOOL_DONE, ARTIFACT, WRITING_ANSWER, DONE, ERROR, SUB_AGENT_*`,
  plus transient `NARRATION`.
- **Sub-agent collaboration dialect**: `AGENT_BLOCK_START` blockIds
  (`resolve, run_sql, lookup, format_output, clarify_user, out_of_scope_msg,
  about_data`); `AGENT_TOOL_START` toolNames (`resolve_filter_value,
  dataset_sql_query, dataset_lookup`); one final `AGENT_RESULT`
  `{status, language, intent, resolvedFilters, sqlCount, rowCount, attempts}`
  (status: `ready | need_clarification | out_of_scope | no_data | error`).
- **SQL span** named `semantic-model-query` per executed SQL, outputs
  `{sql, success, row_count}` (+ `rows, columns` on the successful one). The
  orchestrator appends the sub-agent trace to its own so Evidence capture + usage
  work unchanged. Frozen `sql_id` format `s{step}q{n}`.
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
2. **Re-paste BOTH Code Agents** when either changes (the orchestrator resolves
   the sub-agent by id; some fixes live on both sides): paste
   `agents/OWIsMind_orchestrator.py` into **OWIsMind_orchestrator** and
   `agents/SalesDrive_revenue_expert.py` into **SalesDrive_revenue_expert**, on
   the **Python 3.11** code env.
3. Check the CONFIG ids match the instance: `GEMINI_FLASH_LITE_ID` /
   `GEMINI_FLASH_ID` / `SONNET_ID`, `SEMANTIC_TOOL_ID` (`v4oqA6R`),
   `DATASET_LOOKUP_TOOL_ID` (`9FEzVZk`), `agent_id` (`agent:bHrWLyOL`).
4. Optional: set `source_url` on the `revenue_expert` capability (orchestrator
   registry) to the Dataiku dataset URL - Evidence then turns the data source
   into a clickable link.
5. If the **plugin backend** (`python-lib`) changed too, rebuild + upload the zip
   and **restart the webapp backend**. (Agent-only changes need NO zip upload:
   the webapp resolves the orchestrator by id via the whitelist.)

The Flow recipes are deployed as Python recipes in the DSS Flow (see
`recipes/README.md`); a refresh scenario keeps the profile + index fresh, no
re-paste needed.

---

## 8. Add a new dataset / domain (e.g. tickets, CSAT)

1. Flow: wire the **same recipes** on the new dataset -> `X_profile` + `X_value_index`.
2. Human-review the profile via an editable overrides dataset.
3. Duplicate the Dataset Expert Code Agent, change the two dataset names in its CONFIG.
4. Orchestrator: add **one** entry to `CAPABILITIES` (copy `revenue_expert`,
   adapt `agent_id` / labels / `domain`). The domains `tickets`, `satisfaction`,
   etc. already exist in `BUSINESS_DOMAINS`, so the honest capability-gap message
   closes itself.
5. With two staffed domains, "360" questions fan out in parallel and the
   orchestrator's synthesis cites each source.

---

## 9. Roadmap (decided, deferred)

- **Replace the managed Dataset Lookup with the Custom Python resolver**
  (`Drive_Revenues_resolve_filter_value`, reading the rich `Value_Catalog`):
  it is more powerful than the managed Dataset Lookup and than the plain
  `value_index` (aliases like "indirect" / "voice", short account names,
  business concepts). Decided 2026-06-17; the code rewiring (sub-agent `lookup`
  path + grounding) is a **dedicated future session**. The catalog recipe and
  tool doc are already in the repo (`recipes/build_value_catalog_recipe.py`,
  `tools/README.md`) so the direction is ready.
- **Semantic model**: keep aligning its config via the `semantic_model/` scripts
  (Phase=ACTUALS, offer hierarchy, transparency, golden queries).
- **Tickets agent**: 2 recipes + 1 Code Agent + 1 registry entry unlocks the
  parallel 360.

---

## 10. Guardrails and limits

- **SQL safety**: read-only transaction (`SET LOCAL transaction_read_only`) +
  `statement_timeout 30s`; the direct engine guards LLM SQL (single SELECT, one
  whitelisted table, no DML/DDL, forced LIMIT, EXPLAIN dry-run, system tables
  rejected). See `docs/security.md` and the skill's safety reference.
- **Honesty (rule P3)**: every shown figure comes from a SQL result; 0 rows ->
  honest message + the scenarios/period actually available (from the profile);
  an unresolved term -> clarification, never a guess. **No hardcoded business
  values** in agent logic - everything comes from the profile / index / overrides.
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
  dataset-expert + langgraph). DSS-free.
