# CLAUDE.md - dataiku-agents/

> Orientation for any Claude session touching the agent system. Full guide:
> [`README.md`](README.md). Engineering reference for building agents safely:
> the skill `agentique-python-dataiku`. Project memory (source of truth):
> `memory/PROJECT_STATE.md` + `memory/LESSONS.md` (these PRIME over the cadrage guides).

## What this is

The OWIsMind agentic system: an **orchestrator** (`agents/OWIsMind_orchestrator.py`)
that routes to a **revenue sub-agent** (`agents/SalesDrive_revenue_expert.py`,
`agent:bHrWLyOL`), which is an expert of `DRIVE_Revenues`. The sub-agent's
expertise is fabricated in the **Flow** (recipes -> a profile + a value index),
human-reviewable, consumed at runtime. The **Semantic Model Query tool** owns the
SQL; every layer (understand, ground, disambiguate) exists to feed it the best
context. A read-only direct-SQL engine is the technical fallback.

> **Repo = source of truth.** Change code HERE, then re-paste into the DSS Code
> Agents (env 3.11). DSS direct edits are overwritten on the next paste.

## Read this before assuming the architecture (avoid the v2/v3 trap)

The CURRENT (v3) sub-agent:
- **Grounds terms with INLINE read-only SQL on `DRIVE_Revenues_value_index`** (method `_resolve_terms`). Grounding is NOT a tool.
- Calls **two** DSS tools: `revenue_semantic_query` (`v4oqA6R`, the SQL engine) and `dataset_lookup` (`9FEzVZk`, plain attribute reads for the `lookup` intent).
- Does **NOT** use `DRIVE_Revenues_Value_Catalog` nor the Custom Python tool `Drive_Revenues_resolve_filter_value`. Those are the v2 / roadmap path (richer grounding), kept in the repo but not wired in. The timeline labels `resolve_filter_value` / `dataset_sql_query` are event names, not tool calls.

Replacing Dataset Lookup with the Python resolver (Value_Catalog) is decided but
**deferred to a dedicated session** (see README "Roadmap"). Do not document or wire
it as current.

## Folder map

| Path | What |
|---|---|
| `README.md` | Master guide: architecture, Flow, models, deploy, extend, roadmap, contracts. |
| `agents/` | The two Code Agents (LangGraph) + [`agents/README.md`](agents/README.md). |
| `recipes/` | The three Flow recipes (profile, value index, value catalog) + [`recipes/README.md`](recipes/README.md). |
| `tools/` | Doc of the DSS agent tools + [`tools/README.md`](tools/README.md). |
| `tools/semantic_model/` | Scripts to build/update the aligned Semantic Model that the `revenue_semantic_query` tool queries + [`tools/semantic_model/README.md`](tools/semantic_model/README.md). |
| `tests/` | DSS-free unit tests: `python3 -m unittest discover -s dataiku-agents/tests`. |

## Rules you must not break

1. **P3 - no hardcoded business values** in agent logic. Everything comes from
   the profile / value index / human overrides. Unknown cases -> constrained LLM
   understanding (candidate list) or an honest refusal, never a value patch.
2. **Frozen contracts** (event kinds, the `semantic-model-query` span shape,
   `AGENT_RESULT`, `sql_id`, registry `block_labels`/`tool_labels` <-> sub-agent
   `KNOWN_*`, the profile contract v1). The webapp / Evidence depend on them.
   Never rename, only add. An anti-drift test guards the registry <-> sub-agent.
3. **One enabled capability per business domain** (rollback = re-flip the flags).
4. **Standalone files**: agents import only stdlib + `dataiku` + `langgraph`
   (env 3.11); recipes may use pandas (design-time). No plugin import.
5. **LLM Mesh discipline** (see the skill): native completion API for reasoning +
   tool-calling; `with_json_output` is FORCED on the sub-agent's UNDERSTAND
   (deterministic extraction) and NEVER on the orchestrator (it disables
   reasoning in DSS 14).
6. **Dataiku safety**: read-only SQL, statement timeout, bounded parallelism,
   no raw-row data sent to the LLM. Ask before anything risky for the instance.
7. **Code + comments in English**; no em dash `-` (U+2014) or en dash (U+2013)
   anywhere (project rule #9).

## Deploy reminder

After any change: re-paste BOTH Code Agents (env 3.11), verify the CONFIG ids
(`GEMINI_*_ID`, `SEMANTIC_TOOL_ID=v4oqA6R`, `DATASET_LOOKUP_TOOL_ID=9FEzVZk`,
`agent_id=agent:bHrWLyOL`). Recipe changes deploy in the Flow (refresh scenario).
Agent-only changes need no zip upload; a `python-lib` backend change does
(upload zip + restart backend).
