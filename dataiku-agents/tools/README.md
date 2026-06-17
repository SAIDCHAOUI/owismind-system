# tools/ - the DSS agent tools

> The revenue sub-agent (`agents/SalesDrive_revenue_expert.py`) reaches the data
> through DSS **agent tools**. This folder DOCUMENTS them (ids, types, I/O); managed
> tools are configured no-code in the DSS UI; Custom Python tools are vaulted here
> as `.py`.

| Tool name | Type | Id | Points at | Used by v3? |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | the aligned semantic model (over `DRIVE_Revenues`) | **yes - default SQL engine** |
| `attribute_lookup` | Custom Python (`attribute_lookup_tool.py`) | (to create) | `DRIVE_Revenues` (+ catalog fallback) | **built, not yet wired** |
| `dataset_lookup` | Dataset Lookup (managed) | `9FEzVZk` | `DRIVE_Revenues` | **REMOVED 2026-06-18** |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | `DRIVE_Revenues_Value_Catalog` | no - superseded by `attribute_lookup` |

The sub-agent calls a tool via `project.get_agent_tool(id).run(payload)`, with a
one-shot fallback that re-resolves the id by name against `list_agent_tools()`
(covers a recreated tool whose id changed).

## `attribute_lookup` (Custom Python, `attribute_lookup_tool.py`) - fast value resolver

Code vaulted here: [`attribute_lookup_tool.py`](attribute_lookup_tool.py). The
fast path for plain reads ("is value X in the data, in which column, and what are
the related values?"). It runs a case/accent-insensitive `ILIKE` search across
every TEXT column of the fact table (read-only, `statement_timeout` + `LIMIT`,
nothing loaded into RAM), returns `found_in` (where the term is + its exact
value), and - when `attributes` are requested - the matched rows' values for
those columns. No catalog is required; an optional catalog fallback offers
aliases when nothing matches. **Status: built + unit-tested
(`tests/test_attribute_lookup.py`), validated by RUN TEST, NOT yet wired into the
sub-agent** (replaces the removed `dataset_lookup`). To wire: create the Custom
Python tool in DSS, set its id in the sub-agent, route plain reads to it.

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

## `dataset_lookup` (Dataset Lookup, `9FEzVZk`) - REMOVED 2026-06-18

This managed tool used to serve the `lookup` intent (plain attribute reads). It
was **removed from the sub-agent**: it could not find values in columns the value
catalog did not index (e.g. `account_manager`), the empty-result handling added
complexity, and it duplicated work. All of its code (the `lookup` intent,
`build_lookup_filter`, `extract_lookup_rows`, `lookup_note`, `_lookup_rows`,
`Profile.match_attribute` / `attribute_columns` / `live_columns`) is gone. Its
replacement is **`attribute_lookup`** above. The managed tool object can be
deleted from DSS once `attribute_lookup` is wired in.

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
