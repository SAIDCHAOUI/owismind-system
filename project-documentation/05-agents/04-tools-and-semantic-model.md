# Agent tools and Semantic Model

> Audience: agent engineer. Last updated: 2026-06-18. Summary: this document details the real DSS tools
> called at runtime by the revenue sub-agent (`revenue_semantic_query` `v4oqA6R`, plus the new
> `attribute_lookup` that is built but not yet wired) and the aligned Semantic Model that owns the
> analytical SQL.

The revenue expert sub-agent (`SalesDrive_revenue_expert`, `agent:bHrWLyOL`) does not compute revenue
figures itself in the nominal case. It prepares the context (UNDERSTAND, RESOLVE, COMPOSE) then delegates
both the WRITING AND the EXECUTION of the SQL to a DSS tool, `revenue_semantic_query`, which queries a
Semantic Model. This document explains that responsibility boundary: what the real tools are, how they are
resolved and called, and why the Semantic Model (and not the agent code) owns the SQL.

To situate these tools within the sub-agent's complete loop (UNDERSTAND -> RESOLVE -> QUERY -> RENDER),
see [The revenue expert sub-agent](03-revenue-expert-subagent.md). For inline grounding on the value index
(which is NOT a tool), see [Flow recipes and grounding](05-flow-recipes-and-grounding.md).

## Overview: three tool statuses

The `dataiku-agents/tools/` folder documents the system's DSS tools. Not all of them are active in v3. The
table below reflects the state read on 2026-06-18 (source: `dataiku-agents/tools/README.md`).

| Tool | DSS type | Id | Points to | v3 status |
|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | the aligned Semantic Model (over `DRIVE_Revenues`) | active (sub-agent), default SQL engine |
| `attribute_lookup` | Custom Python | (to create in DSS) | `DRIVE_Revenues` (+ catalog as fallback) | wired as an ORCHESTRATOR built-in (DSS deployment pending) |
| `dataset_lookup` | Dataset Lookup (managed) | `9FEzVZk` | `DRIVE_Revenues` | REMOVED on 2026-06-18 |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | `DRIVE_Revenues_Value_Catalog` | roadmap, not wired (superseded by `attribute_lookup`) |

A capital point to avoid confusion: `resolve_filter_value` and `dataset_sql_query` are timeline event
LABELS (`KNOWN_TOOL_NAMES` in the sub-agent), NOT tool calls. Likewise, term grounding on the value index
is inline SQL, not a tool. On the SUB-AGENT side, the only real DSS tool called at runtime in v3 is
`revenue_semantic_query`. On the ORCHESTRATOR side, a second real DSS tool now exists: `attribute_lookup`,
wired as a built-in pending deployment (see below).

> IN FLUX: the `dataiku-agents/` folder is being edited live by another engineer. The paths, ids and
> contracts below reflect the state read on 2026-06-18. The code takes precedence over this documentation
> in case of divergence.

## The runtime tool: `revenue_semantic_query` (`v4oqA6R`)

### Configuration and invariant

In `SalesDrive_revenue_expert.py`, the default SQL engine is selected by `SQL_ENGINE = "semantic_tool"`.
The associated CONFIG constants are: `SEMANTIC_TOOL_ID = "v4oqA6R"`,
`SEMANTIC_TOOL_NAME = "revenue_semantic_query"`, and `SEMANTIC_QUESTION_KEY = "question"` (the first
candidate for the input key, auto-detected at runtime).

The `SEMANTIC_TOOL_ID_BY_MODE` mapping associates the three modes with the SAME tool (`eco`, `medium`,
`high` all point to `v4oqA6R`). The tool's underlying LLM model (Sonnet 4.6) is configured in DSS, not from
the sub-agent code: whatever orchestration mode the user picks, SQL generation always goes through a strong
model with the semantic layer. This is an essential invariant: the quality of offer and column resolution
never degrades in `eco` mode.

### Tool resolution: `_get_tool`

The sub-agent resolves the tool via the `_get_tool(self, project, tool_id, tool_name)` method. It calls
`project.get_agent_tool(tool_id)`, with a one-shot fallback: on failure, it re-resolves the id by NAME by
walking `project.list_agent_tools()` looking for `tool_name`. This safety net covers the case of a tool
recreated in DSS whose id would have changed: as long as the `revenue_semantic_query` name stays stable,
the sub-agent recovers without a code edit.

### Input key detection: `pick_semantic_input_key`

The exact key the tool expects as input is not frozen in the code. It is auto-detected once per tool id:
`pick_semantic_input_key(descriptor)` reads the tool descriptor's `inputSchema` and picks the first
recognized key from a list of candidates (`question`, `query`, `user_question`, `input`, `text`), falling
back to `SEMANTIC_QUESTION_KEY`. The result is cached on `self._semantic_keys` keyed by tool id (a different
tool per mode could expose another key). The final call is simple: `tool.run({sem_key: semantic_question})`.

### What the sub-agent sends: COMPOSE (`build_semantic_question`)

The natural-language question sent to the tool is built 100% by deterministic code, in
`build_semantic_question(u, profile, filters)`. The LLM NEVER writes this question. It aggregates everything
the upstream layers (UNDERSTAND, RESOLVE) have gathered, in explicit sections:

- `USER QUESTION (this is the source of truth - answer THIS)`: the user question, which takes precedence
  over everything else.
- `EXPECTED SHAPE (guidance, use your judgment)`: a hint about the expected shape derived from the intent
  (total, breakdown, top_n...), phrased as a suggestion.
- `HELPER FINDINGS`: the safe values grounded by the grounding helper, grouped by column (`=` or `IN`),
  with the catalog's exact spellings. The text explicitly qualifies them as HINTS that HELP, not orders.
- `AMBIGUOUS OFFER TERM`: for an offer term present in several columns (values with `alt_columns` or
  deferred terms `offer_terms_for_model`), an instruction tells the model NOT to take a column pinned by
  the helper and to resolve it itself, with the rule `NEVER default to sirano_product`.
- `SCENARIO` and `PERIOD`: scenario(s) and period(s), as guidance.
- a destination note indicating that the produced SQL yields a result table displayed to the user AND
  re-read by another LLM, so it must return a clean tabular output with explicit aliases, never prose.

### What the sub-agent retrieves: EXTRACTION (`extract_semantic_payload`)

The tool runs in Agent mode: its return value is a multi-message transcript (reasoning, schema exploration,
probe queries, final answer). The extraction is therefore a DEFENSIVE walker,
`extract_semantic_payload(raw_output)`, which produces the following structured payload:

```
{"sqls": [str], "result": {...}|None, "answer": str|None, "row_count": int|None, "shape_keys": [str]}
```

Two rules handle the multi-message nature of the transcript:

- The ANSWER is selected by key priority (`_SEM_ANSWER_KEY_PRIORITY`: `answer`/`output_text` at rank 0,
  `completion` at rank 1, `text` at rank 2, `result` at rank 3); at equal priority, the LAST occurrence
  wins (the final message, never the preamble).
- The tabular RESULT and the `row_count` also keep the LAST occurrence (the probe-query results precede the
  final result). The accepted row keys are `rows`, `records`, `data`, `result_rows`, `values`
  (`_SEM_ROW_KEYS`).

When the actual output schema matches nothing known, the absence stays honest (`result: None`): the
extraction never invents data.

### Capture toward Evidence: one span per SQL, result on the last one

For each SQL returned by the tool, the sub-agent emits a frozen `semantic-model-query` span carrying
`{sql, success, row_count}`. When the tool has generated several queries (for example a query then a
repaired variant), the tabular result (`rows`, `columns`) is attached to the LAST span (`i == last_i`),
because the webapp and Evidence take the last successful SQL to render the chart. Attaching the result
elsewhere would leave the active item without data and the chart could not render. This span contract is
the hinge between the sub-agent and Evidence; it is detailed on the backend side in
[Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

### The technical fallback: direct SQL engine

The flag `FALLBACK_TO_DIRECT = True` allows a fallback to a read-only direct SQL engine built BY the
sub-agent itself, but ONLY on a TECHNICAL failure of the tool (an exception), never on an empty result (an
empty result is a valid answer). This direct engine composes per-intent SQL templates or, for the
`custom` long tail, a guarded LLM with an EXPLAIN dry-run and repairs. It is described together with the
sub-agent pipeline in [The revenue expert sub-agent](03-revenue-expert-subagent.md). For this document, the
key point is: under nominal operation, the SQL belongs to the Semantic Model, not to the agent code.

## The new `attribute_lookup` tool: wired as an orchestrator built-in

> IN FLUX: the architecture of `attribute_lookup` evolved on 2026-06-18 while this documentation was being
> written. The tool (`tools/attribute_lookup_tool.py`) is BUILT and unit-tested
> (`tests/test_attribute_lookup.py`, validated by RUN TEST), and it is now WIRED as a built-in tool of the
> ORCHESTRATOR (not the sub-agent), pending DSS deployment. Its DSS id (`LOOKUP_TOOL_ID`) still has to be
> created/filled. Its predecessor, the managed `dataset_lookup` tool (`9FEzVZk`) and the entire `lookup`
> intent, were REMOVED from the sub-agent on 2026-06-18.

### What it does and what it is for

`attribute_lookup` is a self-contained Custom Python agent tool (`from dataiku.llm.agent_tools import
BaseAgentTool`, class `MyAgentTool`). It is the FAST path for simple reads on a named object, without a
Semantic Model, without a dataframe in RAM. It behaves like Dataiku's "Whole data" search box: a filter
insensitive to both case AND accents on EVERY text column of the dataset, which returns the values of the
other columns (or only the requested column). Examples it resolves in under a second: "who is the account
manager of X?", "carrier code or sales zone of X?".

Its CONFIG: `FACT_DATASET = "DRIVE_Revenues"` and `CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"`
(optional alias fallback). No business column name is hard-coded: it is reusable on another dataset by
changing `FACT_DATASET`.

### The three-step flow

1. SEARCH (`build_search_sql`): `SELECT * FROM <fact> WHERE (col1 ILIKE %term% OR col2 ILIKE %term% ...)
   LIMIT <sample>` over each text column. The term and the column are both folded to lowercase and
   accent-stripped (the key is `unaccent_lower_sql`, which uses `translate()` WITHOUT the `unaccent`
   extension, in line with the NO INSTALL rule). The query is bounded by `SEARCH_SAMPLE_ROWS` (1000).
2. SUMMARIZE: `find_matches` returns `found_in`, that is, where the term appears and with which exact
   values; `summarize_values` returns the distinct values of the requested columns (parameter `keep`).
3. FALLBACK: if nothing matches AND no specific column was requested, `_alias_fallback` proposes catalog
   aliases (short names, business concepts), never auto-chosen. An absent or unreadable catalog yields no
   suggestion, never an error.

### Output statuses and guardrails

The tool returns one status among `found`, `suggestions`, `not_found`, `bad_input`, `attribute_unknown`.
Its descriptor (`get_descriptor`) is explicit about the limitations: "Do NOT use it for sums, totals,
rankings or comparisons - use the semantic model query tool for those", and indicates that a `suggestions`
or `not_found` status must lead to asking the user, never to guessing or to asserting that the data does
not exist.

On the safety side: read-only execution (same `SQL_PRE_QUERIES` as the sub-agent: `statement_timeout` 30 s
+ `transaction_read_only`), bounded by LIMIT, only real column names discovered from the live schema reach
the SQL (`_live_columns_typed`, `match_attribute_column`), nothing loaded into RAM. A bounded, TTL'd
in-process cache absorbs repeated lookups (distinct values only). `MAX_ATTRIBUTES = 12` limits abuse.

### How it is wired: an orchestrator built-in

The architecture choice (decision of 2026-06-18) is to plug `attribute_lookup` into the ORCHESTRATOR, NOT
into the sub-agent. It is a built-in tool on the same footing as `show_table` or `current_date`: it is
added to the tool specs by `build_tool_specs` and dispatched inline in the orchestrator graph's
`node_tools` node. The benefit: it touches NO frozen `KNOWN_*` contract and the sub-agent stays UNCHANGED.

On the orchestrator side, the CONFIG is `LOOKUP_TOOL_ID = ""` (to fill in after creating the Custom Python
tool in DSS, e.g. `"ab12CdEf"`) and `LOOKUP_TOOL_NAME = "attribute_lookup"`. The `_run_lookup` method
resolves the tool via the same `_get_tool` (id then fallback by name), calls it with
`tool.run({"entity": term, "attributes": attrs})`, and NEVER raises: a failure degrades into a hint
inviting the question to be passed to the sub-agent (`ask_revenue_expert`), so the turn always completes.
The output is also transformed into an Evidence item (`_lookup_evidence_item`), with a source link
inherited from the `revenue_expert` capability (`LOOKUP_SOURCE_CAP`), bounded to `LOOKUP_RESULT_MAX_ROWS`
(25) rows.

The orchestrator prompt invites calling `attribute_lookup` FIRST for questions of the type "who is the
account manager of X", "does X exist / what is its exact spelling", in order to short-circuit the slow
semantic path when a simple read is enough. For sums, totals, rankings or comparisons, the orchestrator
routes to the revenue expert sub-agent.

> DEPLOYMENT: create the Custom Python tool in DSS, fill `LOOKUP_TOOL_ID` on the orchestrator side
> (optional thanks to the by-name fallback that resolves `attribute_lookup`), then RE-PASTE THE ORCHESTRATOR
> only (env 3.11). No sub-agent change. See [Deploying and editing the agents](07-deploying-and-editing-agents.md).

### Why `dataset_lookup` was removed

The managed `dataset_lookup` tool (`9FEzVZk`) served the old `lookup` intent (simple attribute reads). It
was removed because it could not find values in columns that the value catalog did not index (for example
`account_manager`), because handling the empty result added complexity, and because it duplicated work.
All the `lookup` intent code on the sub-agent side (`build_lookup_filter`, `extract_lookup_rows`,
`lookup_note`, `_lookup_rows`, and the profile helpers `match_attribute`/`attribute_columns`/`live_columns`)
was removed. Its replacement is `attribute_lookup`.

> ROADMAP: `Drive_Revenues_resolve_filter_value` (Custom Python, over `DRIVE_Revenues_Value_Catalog`) and
> the `DRIVE_Revenues_Value_Catalog` itself remain roadmap, NOT wired in v3. The decision (made and
> deferred) is to replace the managed Dataset Lookup with a richer Python resolver in a dedicated session.
> `attribute_lookup` supersedes that resolver for now.

## The aligned Semantic Model: the Semantic Model owns the SQL

### The principle

The `revenue_semantic_query` tool points to a Semantic Model that OWNS the analytical SQL. This is the
central architecture decision (see [ADR-0010](../08-decisions/0010-grounding-et-semantic-model.md)): the
model runs on Sonnet 4.6 WITH the semantic layer, so it understands the dataset far better than the
sub-agent's small UNDERSTAND model. The sub-agent ASSISTS, it does not DICTATE: it sends the user question
(truth) plus HINTS, and the model keeps the last word. This philosophy explains why, for an ambiguous offer
term, the sub-agent pins NO column and lets the model decide.

The regression that motivated this principle is instructive: the sub-agent's `column_priority`, falling
back on `-distinct_count`, pinned `sirano_product = 'EVPL'`; yet the BUDGET rows carry no `sirano_product`,
so the budget came out at 0. The offer hierarchy now lives in the model's instructions, never hard-coded in
the agent code.

### The aligned content (the business core)

The model's `sqlGenerationConfig.instructions` field (`NEW_INSTRUCTIONS` in the scripts) encodes the rules
the model applies. The main ones:

- one physical table, NEVER a JOIN: the three entities (`revenue_record`, `customer_account`,
  `commercial_offer`) map the SAME denormalized table.
- default scenario `'ACTUALS'` (plural, never `'ACTUAL'`). Allowed `Phase` values: ACTUALS, BUDGET,
  FORECAST, Q3F, HLF. `amount_eur` is additive by `booking_type`.
- offer hierarchy, most granular first: Product, Solution, SolutionLine; `sirano_product` is a secondary
  technical code, NEVER the default. Transparency required when a value exists at several levels.
- customer identity: GROUP BY `diamond_id` alone (stable), display headed by `MAX(Account_name)` +
  `MAX(carrier_code)`, `diamond_id` last and de-emphasized.
- `Parent_Group`: not used unless explicitly requested.
- indirect sales: `distribution_type` / `Account_partner` (the reseller Airbus sells to Maroc Telecom, so
  the end customer = Maroc Telecom, partner = Airbus). `INDIRECT_VALUE = "Indirect_distribution/Resseler"`.
- YTD for ACTUALS: filter `EXTRACT(YEAR FROM year_month) = <year>` rather than comparing to "today" (which
  would create a partial or empty month).

These rules come with `GOLDEN_QUERIES`: nine golden queries, each teaching a rule (no self-join, name +
carrier_code, diamond_id last, Product priority, named customer, indirect, by partner).

The detail of the source data model (`DRIVE_Revenues`) and the building of the artifacts (profile, value
index, value catalog) are covered in [Flow recipes and grounding](05-flow-recipes-and-grounding.md).

### Two scripts: build (create + index) vs update (in place)

The model is scripted under `dataiku-agents/tools/semantic_model/`. The two scripts run in a Dataiku
notebook (project `OWISMIND_DEV`) and use ONLY the public semantic models API (no class instantiated
directly).

| | `build_aligned_semantic_model.py` | `update_aligned_semantic_model.py` |
|---|---|---|
| Role | one-time CREATE of the new model | in-place MODIFY of an existing model |
| Reads the old model `2O2KcHw` | yes, READ-ONLY (`get_raw()` on a deep copy, never a `save()`) | no |
| Creates a new model | yes (`create_semantic_model`) + version v1 | no |
| Indexes distinct values | yes (`start_update_distinct_values`) | no (the index is not touched) |
| Modified fields | everything: instructions, golden queries, corrections | `sqlGenerationConfig.instructions` + `goldenQueries` on the active version |
| Required parameter | no id as input (creates an id, to note) | `NEW_MODEL_ID` (the id printed at creation) |

The build script reads the old model (`OLD_SEMANTIC_MODEL_ID = "2O2KcHw"`) READ-ONLY to start from the
exact current config, applies deterministic corrections (`apply_corrections`), creates a NEW model plus a
version v1, then indexes distinct values against the physical table `PHYSICAL_TABLE =
'"OWISMIND_DEV_drive_revenues"'`. The old model `2O2KcHw` remains intact as a rollback and must NEVER be
deleted.

`apply_corrections` locates elements by NAME (robust to ordering) and corrects in particular: Phase
`'ACTUAL'` -> `'ACTUALS'` everywhere (including the "Actual Revenue Only" filter that matched ZERO rows),
the description of `commercial_offer` (hierarchy + transparency), the `Parent_Group` restriction, the
indirect example of `Account_partner`, the removal of the bogus glossary term `diamond_id` and of the
"roaming hub" synonym of Roaming Sponsor, and the complete replacement of the golden queries.

Once the model is created, each prompt or golden-query iteration goes through
`update_aligned_semantic_model.py`, which modifies in place WITHOUT re-indexing (neither the instructions
nor the golden queries touch the distinct-values index). The `NEW_INSTRUCTIONS` and `GOLDEN_QUERIES` blocks
are kept byte-identical across both files; the instruction is to edit them in the `update_…` script going
forward.

### Repointing the tool to the new model

After creation, the tool is repointed by editing the settings of `v4oqA6R` to select the NEW model. No
sub-agent code edit is needed if you reuse the same tool (alternative: create a new tool and update
`SEMANTIC_TOOL_ID`, but editing the existing tool is simpler).

> IN FLUX: the README and the Semantic Model build script still reference a file
> `dataset_expert_langgraph.py` and a Code Agent `agent:AKQaQ0Am` as the target to re-paste. These are
> EARLIER names: the current file in the repository is `SalesDrive_revenue_expert.py` (`agent:bHrWLyOL`).
> The `dataiku-agents/` documentation is being aligned here; follow the current name.

## Summary of invariants for the agent engineer

- On the sub-agent side, a single real runtime tool in v3: `revenue_semantic_query` (`v4oqA6R`). The inline
  grounding and the `resolve_filter_value` / `dataset_sql_query` labels are NOT tools.
- The tool writes AND executes the SQL; the agent code ONLY composes a grounded question and extracts the
  answer. The direct SQL engine is a fallback on a technical failure only.
- In all modes, the tool runs on Sonnet: the quality of SQL generation does not depend on the user mode.
- The Semantic Model owns the business rules (offer hierarchy, ACTUALS by default, never `sirano_product`
  by default, customer identity). They are edited via the scripts, never hard-coded in the agent.
- `attribute_lookup` is wired as an ORCHESTRATOR built-in (not the sub-agent), pending DSS deployment:
  create the Custom Python tool, fill `LOOKUP_TOOL_ID`, re-paste the orchestrator. The sub-agent no longer
  has a `lookup` path (intent removed on 2026-06-18).

## See also
- [The revenue expert sub-agent](03-revenue-expert-subagent.md) - the UNDERSTAND/RESOLVE/QUERY/RENDER pipeline that calls these tools.
- [Flow recipes and building the expertise](05-flow-recipes-and-grounding.md) - profile, value index, value catalog and the inline grounding (not a tool).
- [Models, prompts and LLM Mesh](06-models-prompts-and-llm-mesh.md) - per-mode models, native calls, with_json_output.
- [Agent system - overview](01-agent-system-overview.md) - orchestrator + sub-agent, frozen contracts.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - how the `semantic-model-query` span becomes Evidence.
- [ADR-0010 - Grounding and Semantic Model](../08-decisions/0010-grounding-et-semantic-model.md) - the decision: the Semantic Model owns the SQL (hybrid engine).
- [Deploying and editing the agents](07-deploying-and-editing-agents.md) - re-paste the Code Agents, verify the tool and model ids.
