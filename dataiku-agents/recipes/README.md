# recipes/ - the design-time Flow

> Three Python recipes that turn `DRIVE_Revenues` into the knowledge artifacts the
> sub-agent consumes. They run **design-time** in the DSS Flow (pandas allowed),
> never at chat runtime. A refresh scenario keeps the outputs fresh; the agent
> always reads live, no re-paste needed when a recipe re-runs.

```
DRIVE_Revenues ──► [profile_dataset_recipe]    ──► DRIVE_Revenues_profile        (the business brain)        USED BY v3 (sub-agent)
               ──► [build_value_index_recipe]  ──► DRIVE_Revenues_value_index    (exact-value grounding)     USED BY v3 (sub-agent)
               ──► [build_value_catalog_recipe]──► DRIVE_Revenues_Value_Catalog  (rich alias catalog)        USED BY v3 (attribute_lookup fallback)
```

Who reads what: `profile` + `value_index` are read by the **sub-agent**
(`SalesDrive_revenue_expert`); `Value_Catalog` is read by the **`attribute_lookup`**
tool (an orchestrator built-in) as its alias / suggestions fallback. `DRIVE_Revenues`
itself is read by the semantic model (SQL) and by `attribute_lookup` (fact search).

---

## The four datasets

### `DRIVE_Revenues` (source, ~175 k rows, 19 columns)

The revenue base. Grain: roughly one row per (Phase, offer, account, month).

| Column | Type | Role |
|---|---|---|
| `Phase` | text | **scenario** column: ACTUALS / BUDGET / FORECAST / Q3F / HLF (never sum across) |
| `booking_type` | text | booking type |
| `SolutionLine`, `Product`, `sirano_product` | text | the **offer hierarchy** (most granular = Product, then SolutionLine; `sirano_product` is the lowest technical level, never the default; the `Solution` level was removed) |
| `Account_name` | text | customer name |
| `Account_partner` | text | indirect reseller / partner |
| `distribution_type` | text | Direct_distribution / Indirect_distribution/Resseler |
| `Parent_Group` | text | account parent group |
| `carrier_code` | text | carrier code |
| `diamond_id` | text | customer id (display pair: `Account_name`) |
| `year_month` | date | the **time** column |
| `amount_eur` | decimal | the **measure** (revenue, EUR) - the `metric_unit` derives the `EUR` currency from this column name |
| `sales_entity` | text | GCS (external) / GCP (internal Orange) |
| `sales_zone` | text | sales zone |
| `account_manager`, `area_manager`, `sales_director` | e-mail | attribute columns (typical `lookup` targets) |
| `original_dataset` | text | provenance |

### `DRIVE_Revenues_profile` (`{key, payload}`, built by `profile_dataset_recipe.py`)

The business brain. Profile **contract v1**: one `__dataset__` row (table-level:
metrics, scenario, time, grain, descriptions) + one row per column (role,
descriptions, synonyms, enum values, display pairs, stats). Two passes:
deterministic stats (zero LLM), then an LLM enrichment that sends **aggregated
metadata only** (schema, stats, low-cardinality enums, a few samples), never raw
rows. Everything the LLM wrote is flagged `llm_generated: true`.

**Human overrides (the step that makes quality).** Create an editable dataset
`DRIVE_Revenues_profile_overrides` with columns `{key, field, value}`, add it as
the recipe's 2nd input, re-run. Overrides are applied LAST (humans always win) and
survive re-runs. Set the scenario default (ACTUALS), metric currency, display
pairs, synonyms. Configure `ENRICH_LLM_ID` to the strongest available Mesh model
(it runs once per dataset; cost is amortized).

### `DRIVE_Revenues_value_index` (`{column_name, value, value_norm, occurrences}`, ~3.6 k rows)

Built by `build_value_index_recipe.py`. Every distinct value of every groundable
text column + its normalized form (lowercase, accents stripped, whitespace
collapsed - the FROZEN `norm_value`, shared with the sub-agent's `_norm`). The
sub-agent queries this **in SQL at runtime** to ground typed terms into exact cell
values, so **create the output ON THE SOURCE SQL CONNECTION** (`SQL_owi`).

### `DRIVE_Revenues_Value_Catalog` (12 columns, approx. 4.9 k rows) - USED BY v3 (alias fallback)

Built by `build_value_catalog_recipe.py`. A RICHER catalog than the value index:
account resolvers with short-name aliases, the offer/business resolvers, AND
hand-crafted **business concept aliases** maintained in code (e.g. "indirect" /
"reseller" -> `distribution_type`, "gcp" -> `sales_entity`, "roaming hub" ->
`Product`). Columns: `search_domain, source_column, target_column, target_value,
matched_value, display_value, normalized_value, frequency,
canonical_account_name, canonical_carrier_code, parent_group, is_alias`.

This catalog is read **at runtime** by the `attribute_lookup` tool
([`../tools/attribute_lookup_tool.py`](../tools/attribute_lookup_tool.py),
`CATALOG_DATASET`): when the fast search finds no exact match, the tool queries
the catalog (`search_domain` in account / account_group / alias) to return close
**suggestions** ("did you mean ..."). It is the tool's alias fallback, NOT the
primary grounding path (the primary path is inline SQL on `value_index`). The
old `Drive_Revenues_resolve_filter_value` tool that used to read this catalog is
being deleted; `attribute_lookup` superseded it.

---

## Reusable for any dataset (auto-IO + NA-safe)

All three recipes are **dataset-agnostic**: they auto-detect INPUT/OUTPUT from the
Flow wiring (`recipe.get_inputs_as_datasets()` / `get_outputs_as_datasets()`), so to
onboard a new domain (e.g. tickets) you wire them on the new base dataset with NO
code edit. The reads are **NA-safe** (they fall back to pandas inference when an
integer column contains NULLs, e.g. a resolution duration empty for open tickets,
which otherwise raises "Integer column has NA values"). `build_value_catalog_recipe`
is **dataset-adaptive**: the revenue-shaped dataset gets the rich curated catalog;
any other dataset gets a generic per-value catalog (search_domain "value") that
feeds the `attribute_lookup` "did you mean" fallback. Worked example + the column
inventory: [`../PLAYBOOK_ADD_AGENT.md`](../PLAYBOOK_ADD_AGENT.md) and
[`../DATASETS.md`](../DATASETS.md).

## Deploy a recipe

1. Flow: `+ Recipe -> Code -> Python`. Input the base dataset (+ optional overrides
   input for the profile). Output = the target dataset (the value index MUST be on
   the SQL connection).
2. Paste the recipe code; review the CONFIG block (`ENRICH_LLM_ID` for the profile,
   the column selection thresholds for the value index).
3. Run. Add a **refresh scenario** (weekly or after each source refresh) so the
   profile + index stay fresh.

## Tests

`profile_dataset_recipe.py` and `build_value_index_recipe.py` have pure helpers
unit-tested in `../tests/test_profiler.py` (norm, time-format detection,
enrichment validation, column selection). Run:
`python3 -m unittest discover -s dataiku-agents/tests`.
