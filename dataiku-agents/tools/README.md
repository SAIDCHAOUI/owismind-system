# tools/ - the DSS agent tools

> The OWIsMind agents reach the data through DSS **agent tools**. This folder
> DOCUMENTS them (ids, types, I/O); managed tools are configured no-code in the
> DSS UI; Custom Python tools are vaulted here as `.py`.

## Tool objects in DSS (3: 2 live + 1 to delete)

| Tool name | Type | Id | Reads | Called by | Status |
|---|---|---|---|---|---|
| `revenue_semantic_query` | Semantic Model Query | `v4oqA6R` | `Drive_Revenues_Semantic_Model` over `DRIVE_Revenues` | the **sub-agent** (QUERY) | **ACTIVE - the SQL engine** |
| `attribute_lookup` | Custom Python ([`attribute_lookup_tool.py`](attribute_lookup_tool.py)) | (instance, resolved by name) | `DRIVE_Revenues` (+ `DRIVE_Revenues_Value_Catalog` fallback) | the **orchestrator** (built-in) | tool object **created in DSS**; built-in wiring goes live after the **orchestrator re-paste** |
| `Drive_Revenues_resolve_filter_value` | Custom Python | (instance) | `DRIVE_Revenues_Value_Catalog` | nobody | **TO DELETE (superseded by `attribute_lookup`)** |

`dataset_lookup` (managed Dataset Lookup, `9FEzVZk`) was **removed 2026-06-18**;
it no longer exists in DSS or in the code. Mental model of live tools =
`{revenue_semantic_query, attribute_lookup}` (+ `resolve_filter_value` being
deleted).

> Two completely different consumers, two completely different ids:
> the **sub-agent** calls `revenue_semantic_query` (`get_agent_tool("v4oqA6R")`);
> the **orchestrator** calls `attribute_lookup` (`get_agent_tool` by name). They
> never call each other's tool.

A tool is invoked via `project.get_agent_tool(id).run(payload)`, with a one-shot
fallback that re-resolves the id by name against `list_agent_tools()` (covers a
recreated tool whose id changed).

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
- **Live config (DSS, source of truth)**: Project `OWISMIND_DEV`, Semantic Model
  `Drive_Revenues_Semantic_Model` (version Active = `v1`), LLM
  `vertex_ai/claude-sonnet-4-6`, embedding `vertex_ai/text-embedding-005`,
  **Agent mode OFF** (the faster linear SQL pipeline, NOT a multi-step agent),
  access datasets as the calling user. It runs on Sonnet in EVERY orchestration
  mode (`SEMANTIC_TOOL_ID_BY_MODE` maps eco/medium/high to the same id), so
  offer/column resolution stays strong regardless of the chat tier.
- **Output**: the executed SQL + result rows, captured from the tool's trace into
  the frozen `semantic-model-query` span `{sql, success, row_count, rows, columns}`.
- The aligned semantic model itself is documented under
  [`semantic_model/`](semantic_model/MODEL.md) (Phase=ACTUALS, offer hierarchy,
  never default to sirano_product, transparency, golden queries).

On a TECHNICAL failure (not an empty result), the sub-agent falls back to its own
read-only direct-SQL engine (`FALLBACK_TO_DIRECT = True`).

### Description for LLM to paste (replaces the stale one in DSS)

The tool's current DSS "Description for LLM" still says *"Use this tool ONLY
after Drive_Revenues_resolve_filter_value has confirmed all business terms are
resolved"*. That precondition is wrong (`resolve_filter_value` is being deleted;
grounding is now inline in the caller). Paste this instead:

```
Generate and execute SQL over DRIVE_Revenues to answer revenue questions
(actuals/budget/forecast, by customer, offer, period, or partner) via the
Drive_Revenues_Semantic_Model semantic model.

INPUT: a natural-language question that already embeds the EXACT filter values,
e.g. "filter on diamond_id = '5373' AND Product = 'IP Transit'". The caller has
already grounded every business term against the live data, so the spellings are
exact: trust them and the user question.

DEFAULT BEHAVIOR (encoded in the semantic model):
- One physical table, NEVER JOIN.
- Phase = 'ACTUALS' when no scenario is named; sum all booking_types within a Phase.
- Offer terms resolve to the most granular level (Product > Solution >
  SolutionLine), NEVER default to sirano_product; disclose when a term spans levels.
- GROUP BY diamond_id and display MAX(Account_name) + MAX(carrier_code), diamond_id last.

OUTPUT: aggregated revenue data (totals, breakdowns, time series, rankings) with
display labels.
```

---

## `attribute_lookup` (Custom Python, [`attribute_lookup_tool.py`](attribute_lookup_tool.py)) - fast value resolver

The fast path for plain reads ("is value X in the data, in which column, and what
are the related values?"). It runs a case/accent-insensitive search across every
TEXT column in ONE readable predicate (a single `ILIKE` over an accent-folded
`concat_ws` of the columns, not one OR per column), read-only,
`statement_timeout` 30s + `LIMIT 1000`, nothing loaded into RAM. Casing is handled
by `lower()` / `ILIKE` and accents (a `translate()` map) at QUERY time: the source
data is never altered and no database extension (no `unaccent`) is required. It
returns `found_in` (where the term is + its exact value), and, when `attributes`
are requested, the matched record's values for those columns. The result carries
`rows_capped` (the `LIMIT` fired -> sample) and `multi_column` (the term spans
several columns -> ambiguous). A short-needle guard (`MIN_NEEDLE_CHARS = 2`), a
bounded TTL cache (256 entries, 120s), and a conditional alias fallback (entity
searches only, reading `DRIVE_Revenues_Value_Catalog`) round it off. `status` is
`found` / `suggestions` / `not_found` (or `bad_input` / `attribute_unknown`); the
`not_found` message never asserts the data is absent.

- **Input** (the orchestrator builds this): `{entity, attributes?, dataset?,
  catalog?}`. The needle key is **`entity`** (not `term`). `dataset` / `catalog`
  are resolved server-side by the orchestrator (the model never names a table).
- **Searches**: only the TEXT/string columns of `DRIVE_Revenues`, i.e. the 18
  string columns (all 20 except `year_month` (date) and `amount_eur` (decimal),
  which are excluded from the `concat_ws`). The set is read live from the schema,
  no column name is hardcoded.
- **Config**: `FACT_DATASET = "DRIVE_Revenues"`,
  `CATALOG_DATASET = "DRIVE_Revenues_Value_Catalog"`, both overridable per call.

**Wiring: a BUILT-IN tool of the ORCHESTRATOR, NOT of the sub-agent.** It is
appended in `build_tool_specs` and dispatched inline in `node_tools` (like
`show_table` / `current_date`), so it touches NO frozen `KNOWN_*` contract and the
sub-agent is UNCHANGED. **Multi-table by design**: the model passes a logical
`domain`, NEVER a table; the orchestrator resolves it to a whitelisted dataset via
the registry (`lookup_domains()` reads each capability's `lookup_dataset` /
`lookup_catalog`), so a second agent is searchable just by declaring its dataset
(rule #3/#4: the table name never leaves the server). The orchestrator calls
`project.get_agent_tool(LOOKUP_TOOL_ID).run({entity, attributes, dataset, catalog})`
(name fallback when `LOOKUP_TOOL_ID` is empty), routes simple "who/what is the
&lt;attribute&gt; of &lt;named entity&gt;" questions to it FIRST (descriptor + a
HOW-TO-WORK rule), and emits the lookup SQL + result as a `semantic-model-query`
subspan (`sql_id` `s{step}lk{n}`) so Evidence keeps provenance. On
`not_found` / `suggestions` the planner asks the user or hands off to the
specialist; it never claims the data is missing (honesty firewall).

**Status: built + hardened + unit-tested + RUN-TEST validated in DSS (fast path +
specialist fall-through both confirmed). The Custom Python tool object EXISTS in
DSS.** Remaining DSS steps:
1. Finalize its DSS "Description for LLM" (the descriptor text is in
   `attribute_lookup_tool.py` `get_descriptor()`).
2. Re-paste the **ORCHESTRATOR** (env 3.11) so the built-in wiring is live.
3. Optional: set `LOOKUP_TOOL_ID` in the orchestrator to the tool's real id
   (until then the name fallback resolves `attribute_lookup`).

No sub-agent change.

---

## `Drive_Revenues_resolve_filter_value` (Custom Python) - TO DELETE

A Custom Python tool that resolved a typed business term to an exact
`(target_column, target_value)` using `DRIVE_Revenues_Value_Catalog`. It is
**called by nobody** (the sub-agent's only `get_agent_tool` targets
`revenue_semantic_query`; the orchestrator's targets `attribute_lookup`) and it
loads the catalog into pandas RAM, so it is being **deleted in DSS**. It is
superseded by `attribute_lookup` (which covers more columns, including attributes
the catalog never indexed, and matches in SQL not RAM). No `.py` for it is kept in
the repo.

> `resolve_filter_value` survives only as a **timeline event label** in the frozen
> `KNOWN_TOOL_NAMES` (the sub-agent emits `resolve_filter_value` /
> `dataset_sql_query` around its inline grounding / SQL execution for the webapp
> timeline). Those labels are NOT live tool calls and are unrelated to the deleted
> tool object. They are frozen (the webapp depends on them): never rename, only the
> doc clarifies them.

---

## The four datasets behind the tools

| Dataset | Role | Read by |
|---|---|---|
| `DRIVE_Revenues` | the revenue base (175,780 rows, 20 cols) | the semantic model (SQL), `attribute_lookup` (fact search) |
| `DRIVE_Revenues_profile` | the business brain (`{key, payload}`) | the **sub-agent** (UNDERSTAND, about_data) |
| `DRIVE_Revenues_value_index` | exact-value grounding index | the **sub-agent** (RESOLVE, inline SQL) |
| `DRIVE_Revenues_Value_Catalog` | rich alias/variant catalog | `attribute_lookup` (alias fallback only) |

`DRIVE_Revenues` columns (20): `Phase`, `booking_type`, `SolutionLine`,
`Solution`, `Product`, `Account_name`, `Account_partner`, `distribution_type`,
`Parent_Group`, `carrier_code`, `year_month` (date), `amount_eur` (decimal),
`sales_entity`, `sales_zone`, `account_manager` (email), `area_manager` (email),
`sales_director` (email), `diamond_id`, `sirano_product`, `original_dataset`.
See [`../recipes/README.md`](../recipes/README.md) for how the three derived
datasets are built.

---

## Adding a tool (general)

1. Create the tool in DSS (managed type, or Custom Python with code vaulted here).
2. For a sub-agent SQL tool: add its id/name to the sub-agent CONFIG (mirror the
   `_get_tool` + run + result extraction pattern). For an orchestrator fast lookup:
   declare a `lookup_dataset` on a capability (it becomes searchable automatically).
   Keep timeline labels in sync with the registry (anti-drift test).
3. Prefer the right tool per job: Semantic Model Query for SQL (aggregations,
   maths), `attribute_lookup` for plain value reads. See the skill
   `agentique-python-dataiku` (tool design + safety).
