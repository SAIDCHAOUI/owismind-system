Now I have everything I need. Let me compose the answer.

---

## DATA & SEMANTIC LAYER - grounding stack and new-domain playbook

---

### 1. The revenue grounding stack (concrete names)

Four artifacts feed the live system, all produced at **design time** by Flow recipes from the single source `DRIVE_Revenues` (~175,780 rows, 20 columns):

**Source dataset: `DRIVE_Revenues`**
Denormalized, grain ~(Phase, Product, Account, month). Key columns: `Phase` (scenario: `ACTUALS`/`BUDGET`/`FORECAST`/`Q3F`/`HLF`), offer hierarchy (`SolutionLine > Solution > Product > sirano_product`), `diamond_id` + `Account_name` + `carrier_code`, `amount_eur` (the only measure), `year_month`, e-mail attributes (`account_manager`, `area_manager`, `sales_director`).

**`DRIVE_Revenues_profile`** (built by `profile_dataset_recipe.py`)
Schema: `{key, payload(JSON)}`. One `__dataset__` row (table-level: metrics, scenario column, time column, grain description) + one row per column (role, synonyms, enum values, display-pair rules, stats). Two passes: (A) deterministic stats, no LLM; (B) LLM enrichment via `ENRICH_LLM_ID` (currently `vertex_ai/claude-opus-4-7`) - sends only aggregated metadata, never raw rows. Human-editable overrides dataset (`DRIVE_Revenues_profile_overrides`, `{key, field, value}`) applied LAST and always win. The sub-agent reads this to generate the UNDERSTAND prompt at runtime (0 SQL for meta-questions).

**`DRIVE_Revenues_value_index`** (~3,600 rows, built by `build_value_index_recipe.py`)
Schema: `{column_name, value, value_norm, occurrences}`. Every distinct value of every groundable text column, with FROZEN normalization (`norm_value`: NFKD, ascii, lowercase, whitespace-collapsed). **Must live on the SQL connection `SQL_owi`** - the sub-agent queries it with inline `ILIKE` at runtime (in `_resolve_terms()`) to ground typed user terms into exact cell values. This is the primary grounding path, not the catalog.

**`DRIVE_Revenues_Value_Catalog`** (~4,900 rows, built by `build_value_catalog_recipe.py`)
12 columns: `search_domain, source_column, target_column, target_value, matched_value, display_value, normalized_value, frequency, canonical_account_name, canonical_carrier_code, parent_group, is_alias`. A richer alias layer: account short-names, offer values, and **hand-crafted business-concept aliases** in code (`BUSINESS_ALIASES` dict in the recipe: "indirect" -> `distribution_type`, "gcp" -> `sales_entity`, "roaming hub" -> `Product`). Read at runtime only by the `attribute_lookup` tool (orchestrator built-in) as its fallback when the fast `value_index` search finds no match. Not read by the sub-agent directly.

**Semantic model: `Drive_Revenues_Semantic_Model`** (tool id `v4oqA6R`, active version `v1`)
Three logical entities (`revenue_record`, `customer_account`, `commercial_offer`) all mapping to ONE physical table - never a JOIN. Owns: the SQL-generation instructions (~11 rule blocks), named filters (10 pre-built `WHERE` snippets), 9 golden queries (each question -> SQL pair), a ~50-term glossary with synonyms, and the embedding config (`vertex_ai/text-embedding-005`). Running **Agent mode OFF** (linear SQL pipeline). **The semantic model writes and runs the SQL** - the sub-agent never writes the final SQL in normal operation (`SQL_ENGINE="semantic_tool"`); it only hands a maximally grounded natural-language question to the tool via `project.get_agent_tool("v4oqA6R").run({"question": "..."})`. Direct-SQL templates in `SalesDrive_revenue_expert.py` (`build_sql()`) are the technical fallback only (`FALLBACK_TO_DIRECT=True`). The SQL LLM is always `vertex_ai/claude-sonnet-4-6` regardless of the user's mode.

**Call path summary:** user question -> orchestrator (`OWIsMind_orchestrator.py`, `ask_revenue_expert` tool) -> sub-agent UNDERSTAND (LLM, strict JSON, profile-generated prompt) -> RESOLVE (`_resolve_terms()`, inline SQL on `value_index`) -> COMPOSE (`build_semantic_question()`, grounded NL question with exact values + scenario + period) -> QUERY (semantic model tool `v4oqA6R`, writes+runs SQL via Sonnet) -> RENDER (`shape_result()`, `format_number()`, code-generated table, `[Scope]` line, `verify_headline()`).

---

### 2. Artifacts required for a new-domain agent

Planned domains in `BUSINESS_DOMAINS` (declared but unstaffed in `OWIsMind_orchestrator.py`): `tickets`, `satisfaction`, `opportunities`, `delivery`, `billing`. Here is the full artifact checklist per new domain:

**Recipe artifacts (design-time, Flow):**

| Artifact | Recipe | Cost trigger | Output size estimate |
|---|---|---|---|
| `<DS>_profile` | `profile_dataset_recipe.py` (paste + configure `ENRICH_LLM_ID`, optional overrides input) | ~1 LLM call (Opus or similar) over aggregated metadata, ~500-2000 tokens; amortized | ~(N_columns + 1) rows |
| `<DS>_value_index` | `build_value_index_recipe.py` (output **must** be on `SQL_owi` connection) | pure pandas scan; no LLM | up to `N_groundable_columns * MAX_VALUES_PER_COLUMN` (cap 20k/column) |
| `<DS>_Value_Catalog` | `build_value_catalog_recipe.py` (alias block `BUSINESS_ALIASES` needs domain-specific edits) | pure pandas; no LLM | comparable to value_index + alias rows |

**Semantic model (design-time, DSS UI or script):**
One new `<Domain>_Semantic_Model` per source dataset. Built interactively in DSS or via `build_aligned_semantic_model.py` (adapted). Requires: entity definitions, attribute mappings to the physical table, the metric(s), named filters, SQL-generation instructions, golden queries, and embedding indexing. The indexing step (embedding all entities) is the **only step that costs LLM tokens at build time** (embedding model, not generation model).

**Code Agent (DSS, env 3.11):**
One new `<Domain>_expert.py` Code Agent. The `SalesDrive_revenue_expert.py` is the template: UNDERSTAND -> RESOLVE -> QUERY -> RENDER pattern. UNDERSTAND prompt is generated from the profile, so the profile contract (`profile_dataset_recipe.py`) is reusable as-is. The sub-agent calls its domain's semantic model tool by id.

**DSS tool object:**
One Semantic Model Query tool object per domain (like `revenue_semantic_query` / `v4oqA6R`), pointing to the new model.

**Orchestrator registration** (one entry in `CAPABILITIES` dict, `OWIsMind_orchestrator.py`):
```python
"tickets_expert": {
    "kind": "agent",
    "agent_id": "agent:<id>",
    "domain": "tickets",
    "tool_name": "ask_tickets_expert",
    "lookup_dataset": "<DS>_value_index_source_table",
    "lookup_catalog": "<DS>_Value_Catalog",
    "enabled": True,
    ...
}
```
`BUSINESS_DOMAINS["tickets"]` is already declared - just flip `enabled`. The CAPABILITIES comment at line 234 explicitly says: "Adding a sub-agent (e.g. a tickets expert) is one more entry here."

**Automatable steps:** profile deterministic pass (A), value_index build, value_catalog build, UNDERSTAND-prompt generation, orchestrator registration, Code Agent scaffolding from template. All are pure code with no human in the loop.

**Steps requiring human curation:** the overrides dataset (scenario column, default scenario, metric currency, synonyms, display-pair rules), the `BUSINESS_ALIASES` block in the catalog recipe (domain-specific concept aliases are pure domain knowledge: for tickets this means things like "P1" -> `priority`, "open" -> `status`), the semantic model SQL-generation instructions (the rules text is what the Sonnet SQL-generator follows - revenue took 2 iterative sessions to tune the Phase/sirano/JOIN rules), and golden queries (each verified against real data).

---

### 3. How much human calibration is intrinsic vs mechanizable

**Intrinsic (cannot be automated):**
- **Scenario/phase semantics**: revenue has 5 phases that must never be summed cross-phase; a billing domain might have `status` or `invoice_type` with similar exclusion rules. The profiler's LLM pass guesses a `scenario_column` but cannot infer the business rule "never sum across scenarios".
- **Offer/product hierarchy resolution priority** (the `sirano_product` bug): the hierarchy order and the "never default to lowest level when budget rows lack it" rule are pure domain knowledge. For tickets, the equivalent would be priority / SLA tiers.
- **Business-concept aliases in the catalog**: "indirect", "gcp", "roaming hub" are OWI-specific jargon. Each domain will have its own vocabulary not discoverable from column values.
- **Golden queries**: must be written against real data and verified. Revenue took 9 (and the Phase `ACTUAL` -> `ACTUALS` fix alone prevented empty results for an entire scenario).
- **Override dataset**: the final say on synonyms, display-pair rules, metric format (e.g. `amount_eur` -> unit `EUR`).

**Mechanizable after the first domain:**
- Profile pass A (stats, cardinality, enum detection): fully automatic.
- Profile pass B (LLM descriptions, role guessing, synonym suggestions): automatic; human reviews output and corrects via overrides.
- Value index build: fully automatic (pure pandas scan, no LLM).
- Value catalog account/offer rows: automatic; `BUSINESS_ALIASES` block is the manual part.
- Code Agent UNDERSTAND -> RESOLVE -> QUERY -> RENDER scaffold: template copy-paste with profile-name and tool-id substitution.
- Orchestrator entry: one dict block, no logic change.

The revenue agent required ~4-5 iterative sessions to tune the semantic model and sub-agent. A second domain with a simpler schema (e.g. tickets: fewer scenarios, no deep hierarchy) should converge in 2-3 sessions, assuming the source dataset is clean and the golden queries can be validated quickly.

---

### 4. Datasets implied for other domains

From `memory/PROJECT_STATE.md` line 352 and the functional spec:

- **Tickets** (`0ter` backlog): explicitly planned ("2 recettes + 1 Code Agent + 1 entrée registre"). No dataset name confirmed in memory. Likely a `TICKETS_Incidents` or similar dataset on `SQL_owi`. Expected columns: ticket_id, status, priority, SLA, account, product, open_date, close_date, resolution_time.
- **Opportunities**: CRM-style, likely `Account_name` + `diamond_id` overlap with revenue (join key at query time, but the ONE-TABLE rule means the semantic model for opportunities would point to a separate opportunities table - never JOIN with revenues).
- **CX / Satisfaction**: NPS, CSAT, or survey data. Likely time-series with account keys.
- **Delivery**: deployment timelines, project status.
- **Billing** (listed separately from revenue): possibly invoice-level detail at higher row count than DRIVE_Revenues.

**The one-table / no-JOIN constraint is absolute** (semantic model instruction #1, also enforced in `guard_custom_sql()` in the sub-agent). A cross-domain "360 analysis" (mentioned in the spec as a future feature: "une question peut mobiliser plusieurs agents") must be handled at the **orchestrator level** via parallel `ask_<domain>` tool calls, with the orchestrator synthesizing the results in its analysis text. It cannot be done with a single SQL JOIN.

---

### 5. Instance-safety profile of building these artifacts

**Profile recipe (`profile_dataset_recipe.py`):**
- Loads the **entire dataset into pandas** in DSS memory via `get_dataframe()` (capped at `MAX_ROWS_IN_MEMORY = 2_000_000`). For `DRIVE_Revenues` at 175k rows this is fine. A larger domain dataset (e.g. a full billing history at millions of rows) would hit the 2M cap (truncated with a warning) or exhaust DSS worker memory on large pandas loads.
- One LLM call (Opus) over aggregated metadata only: negligible instance load, ~1-5s, runs once and is amortized.
- **Flag**: on a large dataset (>500k rows, wide schema), the pandas `get_dataframe()` is the DSS memory risk. Set `MAX_ROWS_IN_MEMORY` conservatively or sample before profiling.

**Value-index recipe (`build_value_index_recipe.py`):**
- Scans all groundable text columns for distinct values. For `DRIVE_Revenues` it produces ~3,600 rows. A wide tickets dataset with many categorical columns (status, priority, product, zone, agent, queue...) could produce more rows but well within bounds (`MAX_VALUES_PER_COLUMN = 20000` per column enforced).
- No LLM. The main risk is the same pandas `get_dataframe()` load.
- **Flag**: output **must** be created on the `SQL_owi` PostgreSQL connection (not a filesystem dataset) - the sub-agent queries it at runtime with inline SQL. Wrong connection type = silent failure at query time.

**Value-catalog recipe (`build_value_catalog_recipe.py`):**
- Also pandas-based. Slightly heavier (computes cross-product of account names vs aliases). No LLM.

**Semantic model indexing:**
- Embedding indexing runs inside DSS when you create/update the model. For a model with many entities and a large glossary it can take a few minutes. It does NOT scan source data rows; it embeds the entity definitions and attribute descriptions only.
- **No instance risk** at chat runtime: the semantic model tool runs in a DSS background context, and its `statement_timeout 30s` + `transaction_read_only` guards are set by the sub-agent before delegating.

**Bottom line for ops:** run the three recipes as scheduled scenarios (weekly or after source refresh), never during peak usage (they do full table scans). The semantic model indexing is a one-time or rare operation. Chat-runtime load is minimal: value-index queries are `ILIKE` on a ~few-thousand-row table; the semantic model tool runs one SELECT on the source. No Flow is triggered at runtime.