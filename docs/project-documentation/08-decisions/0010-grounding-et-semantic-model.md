# ADR-0010 - Grounding via value_index, the Semantic Model owns the SQL

> Audience: agent engineer. Last updated: 2026-06-18. Summary: why the revenue sub-agent does NOT
> generate the analytical SQL itself (it delegates to the Semantic Model Query tool, on a Sonnet
> model) and why the grounding of user terms is done with inline read-only SQL on the `value_index`,
> rather than through a DSS tool.

- **Status**: ACCEPTED and validated in DSS (user: "it works really well"). The direct SQL engine is
  kept as a technical fallback.
- **Related decisions**: [ADR-0006](0006-appels-natifs-llm-mesh.md) (native LLM Mesh calls),
  [ADR-0007](0007-json-output-force-sur-understand.md) (`with_json_output` on UNDERSTAND),
  [ADR-0011](0011-sous-agent-assistif.md) (the sub-agent assists, it does not dictate),
  [ADR-0003](0003-sql-direct-sans-flow.md) (direct SQL, instance safety).

This ADR covers two coupled choices that form the core of the revenue sub-agent's data engine
(`SalesDrive_revenue_expert.py`, `agent:bHrWLyOL`): (1) WHO writes the analytical SQL, and (2) HOW
the terms from the user's natural language are grounded to exact cell values before they are passed
to the model.

## Context and problem

The sub-agent must be the expert of a dataset (`DRIVE_Revenues` today, tickets tomorrow) and produce
the right answer to a business question in natural language. Two sub-problems:

1. **Generate the right analytical SQL** (aggregations, scenario comparisons, shares of total, trends)
   reliably. An initial design (early v3) gave 100% of the SQL to our code: templates covering 9
   intents plus a guarded LLM path for the long tail. But the user A/B in DSS showed that the Semantic
   Model (the `v4oqA6R` tool, in Agent mode, on a Sonnet model with the semantic layer) "answers and
   understands much better" than our templates.

2. **Resolve user terms to exact values**. A salesperson types "EVPL", "Roaming Hub", or a misspelled
   customer name. Before querying the model, we must retrieve the exact cell value (the right case, the
   right accents, the right column) without hard-coding any column name or any business value (P3 rule).
   And all of this must be safe for a shared Dataiku instance (read-only, bounded, no overload).

## Decision

### 1. The Semantic Model Query tool owns the SQL; our layers feed it

The default engine is `SQL_ENGINE = "semantic_tool"` (`SalesDrive_revenue_expert.py`). The sub-agent
runs UNDERSTAND (intent and term extraction), RESOLVE (grounding, see below), COMPOSE (building a
maximally grounded question), then **delegates the generation AND execution of the SQL to the DSS tool
`revenue_semantic_query`** (id `SEMANTIC_TOOL_ID = "v4oqA6R"`), called natively via Mesh through
`get_agent_tool(tool_id).run({input_key: semantic_question})`. The Semantic Model owns the SQL; every
upstream layer exists to pass it the best possible context.

COMPOSE is carried by `build_semantic_question(u, profile, filters)`, a pure and deterministic
function. It assembles a question whose STRUCTURE is constant:

- the **user question first**, declared as the source of truth ("USER QUESTION (this is the
  source of truth - answer THIS)");
- an **expected shape** derived from the intent ("EXPECTED SHAPE (guidance, use your judgment)") that
  remains a suggestion, not an order;
- the **values grounded by the resolver**, grouped by column (`col = 'x'` or `col IN (...)`) and
  presented as "HELPER FINDINGS ... HINTS to ASSIST you, NOT orders";
- the **scenario** (the `Phase` column, by default `ACTUALS`) and the **period** made explicit;
- a destination note (`SEMANTIC_DESTINATION_NOTE`).

The model always keeps the final word: this is the invariant of [ADR-0011](0011-sous-agent-assistif.md)
(the sub-agent assists, it does not dictate). For an ambiguous offer term (present in multiple columns),
`build_semantic_question` pins no column: it emits an `AMBIGUOUS OFFER TERM` block and lets the model
decide using its offer-hierarchy rules (`Product > Solution > SolutionLine > sirano_product`, never
`sirano_product` by default). These rules live in the Semantic Model's instructions, not in the code.

The extraction of the tool's answer (Agent mode, which returns a multi-message transcript: reasoning,
schema exploration, probe queries, final answer) is hardened by `extract_semantic_payload`: the answer
is selected by KEY PRIORITY (`answer`/`output_text` beat a generic `text`) and, at equal priority, the
LAST occurrence wins (the final answer, never the reasoning preamble); the tabular row set also keeps
the last occurrence (the probe-query results precede the final result).

### 2. Grounding is inline read-only SQL on the value_index, NOT a tool

Grounding (the anchoring of terms) is **NOT a DSS tool call**. It is inline SQL via
`dataiku.SQLExecutor2`, executed by the method `_resolve_terms(profile, base_terms, trace)` on the
dataset `VALUE_INDEX_DATASET = "DRIVE_Revenues_value_index"`. The value_index is a dataset
`{column_name, value, value_norm, occurrences}` built design-time by a Flow recipe
(`recipes/build_value_index_recipe.py`, schema FROZEN v1), with a `norm_value` normalization SHARED
(frozen) between the profiler, the recipe, and the agent's resolver.

Resolution is a three-stage cascade, from the most precise to the most tolerant:

| Stage | Mechanics | Guardrail |
|---|---|---|
| Exact | A single `WHERE value_norm IN (...)` query on the normalized form of all terms | read-only, bounded `LIMIT` (`max(200, 20 * n)`) |
| Fuzzy (substring) | For unresolved terms: `WHERE value_norm LIKE %term% ESCAPE '\' ORDER BY occurrences DESC LIMIT 40` | sequential (no SQL parallelism: `SQLExecutor2` not guaranteed thread-safe, marginal gain) |
| Last chance | A slice `ORDER BY occurrences DESC LIMIT 5000` (`LAST_CHANCE_SCAN_LIMIT`), fetched AT MOST ONCE per request and reused, then `difflib` matching | `FUZZY_MIN_RATIO = 0.62` minimum |

Every query goes through `_run_sql`, which opens a fresh `SQLExecutor2` and applies
`SQL_PRE_QUERIES = ["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]`.
The matching happens IN the database (SQL), never in RAM over the full dataset.

Each resolution returns a resolver contract status: `resolved` (a single column, a single value),
`ambiguous` (multiple candidate columns or values), or `unresolved` (no candidate above the threshold).
A term present in multiple columns is never pinned: it is deferred to the model.

### 3. The direct SQL engine remains a technical fallback

`FALLBACK_TO_DIRECT = True`. If the semantic tool fails **technically** (exception on the call), the
sub-agent switches to `engine = "direct"`: `build_sql(u, profile, filters, table)` (deterministic
per-intent templates) then, for the long tail or the `custom` intent, a guarded LLM path
(`SQLGEN_PROMPT`, filter values injected verbatim, read-only). A legitimate EMPTY result is not a
failure: it remains an honest `no_data`, not a fallback. The fallback covers only the technical failure
of the tool.

## Rationale

- **The model resolves better than our templates in practice.** The production SOTA (semantic layer plus
  templates, dbt or Snowflake Cortex style) measures accuracy clearly higher than free LLM-generated SQL
  (on the order of 98-100% against 84-90%). In practice on this instance, the Semantic Model (Sonnet plus
  semantic layer) beat our templates in the user A/B. So we leave the SQL to it and invest the coding
  effort in the CONTEXT we give it.

- **Tool versus inline is NOT a SQL-load debate.** A tool that queries would run exactly the same SQL.
  The real lever is WHERE the matching happens: in the DATABASE (bounded SQL, read-only) rather than in
  RAM. Inline grounding is fast, bounded, read-only, and hard-codes no column name (P3-safe).

- **Deterministic Evidence capture.** Managed tools are called via `get_agent_tool(id).run()` and the
  SQL plus rows are read from the tool's RETURN value, not guessed from the trace. On the multi-SQL side,
  the result is attached to the LAST SQL span (`semantic-model-query`), since Evidence and the chart take
  the last successful item with a result.

## Consequences

### Positives
- Data engine validated in DSS and robust to the reality of the Agent-mode transcript (extraction by
  key priority, last-wins).
- Safe, bounded grounding with no hard-coded business value; the `FUZZY_MIN_RATIO` threshold and the
  caps absorb typos without ever inventing a column.
- Clean separation of responsibilities: the code owns UNDERSTAND/RESOLVE/COMPOSE and instance safety,
  the model owns SQL generation and the business hierarchy.

### Negatives and points of attention
- **The Semantic Model engine remains opaque** (its internal prompts cannot be controlled by the code).
  Its anomalies are fixed in ITS config, not in the agent code: that is how `Phase='ACTUAL'` was
  corrected to `'ACTUALS'`. The alignment scripts live in `tools/semantic_model/`
  (`build_aligned_semantic_model.py`, `update_aligned_semantic_model.py`); the `v4oqA6R` tool must
  point to the aligned model.
- **The value_index can be STALE** after a dataset change (the agent does not "see" new columns until
  the recipe has re-run). Freshness depends on the design-time Flow.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| 100% free LLM-generated SQL | Clearly lower accuracy in SOTA (84-90%); not auditable. |
| 100% code-owned SQL (templates only) | Worse than the Semantic Model in practice (user A/B). Kept as a technical FALLBACK only. |
| Make grounding a DSS tool | No gain: the tool would run the same SQL. Inline keeps the matching in the database, bounded and read-only, with no extra tool surface. |
| Load the value_index in RAM and match on the Python side | Memory load and instance risk; database-side `IN`/`LIKE` matching is safer and bounded. |
| Instantiate the semantic model API by hand | Forbidden by the DSS documentation: go through `create_semantic_model` plus the versions workflow. |

## Points in flux

> IN FLUX: grounding layer in transition. The managed tool `dataset_lookup` (`9FEzVZk`) and the `lookup`
> intent of the sub-agent were FULLY REMOVED on 2026-06-18 (from the sub-agent and from the frozen
> `KNOWN_*` contract). Their replacement, `attribute_lookup` (`tools/attribute_lookup_tool.py`), is a
> standalone Custom Python tool for sub-second lookup of a named value in the dataset. At the time of
> writing, the orchestrator code (`OWIsMind_orchestrator.py`) wires it as a BUILT-IN tool of the
> orchestrator (constants `LOOKUP_TOOL_ID` empty to fill in DSS and `LOOKUP_TOOL_NAME = "attribute_lookup"`,
> inline dispatch in `node_tools`, like `show_table`), and NOT in the sub-agent: it touches no frozen
> contract and the sub-agent stays unchanged. Deployment requires creating the Custom Python tool in DSS
> and filling in `LOOKUP_TOOL_ID`. To be confirmed on the instance (50-user performance not measured).

> ROADMAP: `DRIVE_Revenues_Value_Catalog` (a richer value-catalog, recipe
> `recipes/build_value_catalog_recipe.py`) and the Python resolver `Drive_Revenues_resolve_filter_value`
> are NOT wired in v3. They are superseded by `attribute_lookup` for the direct-lookup need.

> IN FLUX: the model of the `revenue_semantic_query` tool is the same in all modes (`eco`/`medium`/
> `high`), via `SEMANTIC_TOOL_ID_BY_MODE`, which maps the three modes to the same `v4oqA6R`. The turn's
> mode drives the model of the agent's LOOP (see [ADR-0009](0009-modeles-par-mode.md)), not that of the
> semantic tool: the latter runs on Sonnet in all cases.

## See also
- [ADR-0011 - Assistive sub-agent](0011-sous-agent-assistif.md) - why the sub-agent does not pin a column for an ambiguous offer term.
- [ADR-0006 - Native LLM Mesh calls](0006-appels-natifs-llm-mesh.md) - how the semantic tool is called (`get_agent_tool(id).run()`).
- [ADR-0009 - Per-mode models](0009-modeles-par-mode.md) - the loop model versus the semantic tool model.
- [ADR-0003 - Direct SQL without Flow](0003-sql-direct-sans-flow.md) - the read-only/bounded safety posture shared by grounding.
- [Flow recipes and building the expertise](../05-agents/05-flow-recipes-and-grounding.md) - the home of the recipes diagram (profile, value index, value catalog) and the detail of inline grounding.
- [Agent tools and Semantic Model](../05-agents/04-tools-and-semantic-model.md) - the `revenue_semantic_query` tool, `attribute_lookup`, and the aligned model.
- [The revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md) - the full UNDERSTAND/RESOLVE/QUERY/RENDER pipeline.
- [ADR index](README.md) - the 12 architecture decisions.
