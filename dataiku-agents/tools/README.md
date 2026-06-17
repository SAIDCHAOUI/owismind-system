# tools/ - the DSS agent tools

> The revenue sub-agent (`agents/SalesDrive_revenue_expert.py`) reaches the data
> through DSS **agent tools**. This folder DOCUMENTS them (ids, types, I/O); the
> two managed tools are configured no-code in the DSS UI, so there is no `.py`
> here for them. The Custom Python tool's code lives in DSS (add it here if/when
> we vault it; see Roadmap).

| Tool name | Type | Id | Points at | Used by v3? |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | the aligned semantic model (over `DRIVE_Revenues`) | **yes - default SQL engine** |
| `dataset_lookup` | Dataset Lookup (managed) | `9FEzVZk` | `DRIVE_Revenues` | yes - the `lookup` intent |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | `DRIVE_Revenues_Value_Catalog` | **no - roadmap** |

The sub-agent calls a tool via `project.get_agent_tool(id).run(payload)`, with a
one-shot fallback that re-resolves the id by name against `list_agent_tools()`
(covers a recreated tool whose id changed).

---

## `revenue_semantic_query` (Semantic Model Query, `v4oqA6R`) - the SQL powerhouse

The default engine (`SQL_ENGINE = "semantic_tool"`). The sub-agent does
UNDERSTAND + RESOLVE + COMPOSE, then hands a **maximally grounded natural-language
question** to this tool, which **writes AND runs the SQL** against the semantic
model. Every upstream layer exists to feed it the best context: exact catalog
values grouped per column (`IN`), explicit scenario(s) and period(s), the axis
rule, a destination note.

- **Input**: one question string. The payload key is auto-detected at runtime
  (`SEMANTIC_QUESTION_KEY = "question"` is the first candidate).
- **Model**: the tool runs on its OWN DSS-configured strong model (Sonnet) in
  EVERY mode, so offer/column resolution stays strong regardless of the
  orchestration tier. `SEMANTIC_TOOL_ID_BY_MODE` can back a mode with a different
  semantic-model tool.
- **Output**: the executed SQL + result rows, captured from the tool's trace into
  the frozen `semantic-model-query` span `{sql, success, row_count, rows, columns}`.
- The aligned semantic model itself is scripted under
  [`semantic_model/`](semantic_model/README.md) (Phase=ACTUALS, offer
  hierarchy, "never default to sirano_product", transparency, golden queries).

On a TECHNICAL failure (not an empty result), the sub-agent falls back to its own
read-only direct-SQL engine (`FALLBACK_TO_DIRECT = True`).

---

## `dataset_lookup` (Dataset Lookup, `9FEzVZk`) - plain attribute reads

Used for the **`lookup`** intent: retrieve an attribute of a named entity without
SQL ("who is the account manager of X?", "the carrier code of Y?"). Reserve the
semantic tool for aggregations, rankings, comparisons; use this for plain field
reads.

- **Input**: `{"filter": <tree>}` where the tree uses `EQUALS / AND / OR`
  operators (built by `build_lookup_filter` from the resolved `{column, value}`
  clauses; an ambiguous offer term becomes an `OR` over its candidate columns).
- **Output**: up to ~10 rows (`DATASET_LOOKUP_MAX_ROWS`), parsed tolerantly by
  `extract_lookup_rows`.
- Disable the whole path with `DATASET_LOOKUP_ENABLED = False` (the `lookup`
  intent then degrades to the SQL / semantic path).

> **Roadmap**: this managed tool is the **planned replacement target**. It is
> less powerful than a Custom Python tool reading the rich `Value_Catalog`. See below.

---

## `Drive_Revenues_resolve_filter_value` (Custom Python) - roadmap, NOT wired in v3

A Custom Python tool that resolves a typed business term to an exact
`(target_column, target_value)` using `DRIVE_Revenues_Value_Catalog` (built by
[`../recipes/build_value_catalog_recipe.py`](../recipes/build_value_catalog_recipe.py)).
The catalog is richer than `value_index`: short account-name aliases, and
hand-crafted business concept aliases ("indirect" / "reseller", "gcp", "roaming
hub", ...).

**Status (2026-06-17, decided, deferred).** v3 grounds terms with INLINE SQL on
`value_index` and does NOT call this tool. The decision is to **replace the
managed Dataset Lookup with this Python resolver** (more powerful), in a dedicated
future session. When we do, vault the tool's code here as
`resolve_filter_value_tool.py` and rewire the sub-agent's `lookup` / grounding
path. Until then, this file is the contract reference, not a live dependency.

---

## Adding a tool (general)

1. Create the tool in DSS (managed type, or Custom Python with code vaulted here).
2. Add its id/name to the sub-agent CONFIG (mirror the `_get_tool` + run + result
   extraction pattern). Keep the timeline `toolNames` in sync with the
   orchestrator registry `tool_labels` (anti-drift test).
3. Prefer the right tool per job: Semantic Model Query for SQL (aggregations,
   maths), a lookup/resolver for plain value reads. See the skill
   `agentique-python-dataiku` (tool design + safety).
