# flow/ - the design-time Flow (two agent zones)

> The Python recipes that turn each source dataset into the knowledge artifacts the
> sub-agents consume. They run **design-time** in the DSS Flow (pandas allowed),
> never at chat runtime. A refresh scenario keeps the outputs fresh; the agents
> always read live, so no re-paste is needed when a recipe re-runs.

This mirror holds the recipe code of the two data-preparation Flow zones of the
production project **OWISMIND_PRD_V1_2**. Column inventories:
[`DATASETS.md`](DATASETS.md). The runtime datasets written by the webapp (not built
by any recipe) are documented in [`Webapp_Zone/README.md`](Webapp_Zone/README.md).

## The two zones (exact DSS names)

### `SalesDrive_Revenue_Expert`  (revenue sub-agent)

```
DRIVE.Revenues ──sync──► DRIVE_Revenues ──► compute_DRIVE_Revenues_profile        ──► DRIVE_Revenues_profile         (business brain)
                                        ──► compute_DRIVE_Revenues_value_index    ──► DRIVE_Revenues_value_index     (exact-value grounding, SQL_owi)
                                        ──► compute_DRIVE_Revenues_Value_Catalog   ──► DRIVE_Revenues_Value_Catalog   (rich alias catalog)
```

### `CSC_ticket_AI_Agent`  (tickets sub-agent)

```
IC_DATA.TroubleTickets_year ──sync──► TroubleTickets_year ──► compute_TroubleTickets_year_profile          ──► TroubleTickets_year_profile
                                                           ──► compute_TroubleTickets_year_value_index      ──► TroubleTickets_year_value_index      (SQL_owi)
                                                           ──► compute_TroubleTickets_year_value_catalogue   ──► TroubleTickets_year_value_catalogue
```

Who reads what: `*_profile` + `*_value_index` are read by the domain **sub-agent**
(`SalesDrive_revenue_expert` / `CSSO_Trouble_Tickets_Expert`); the `*_Value_Catalog`
/ `*_value_catalogue` is read by the **`attribute_lookup`** tool (an orchestrator
built-in, [`../genai/agent-tools/`](../genai/agent-tools/README.md)) as its alias / suggestions fallback.
Each source base (`DRIVE_Revenues`, `TroubleTickets_year`) is also read directly by
its semantic model (SQL) and by `attribute_lookup` (fact search).

## Six DSS recipes, three template codes

There are **three generic recipe codes**, each pasted **verbatim twice** (once per
zone), giving the six files here:

| Template code | Revenue zone file | Tickets zone file |
|---|---|---|
| profile | `SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_profile.py` | `CSC_ticket_AI_Agent/compute_TroubleTickets_year_profile.py` |
| value index | `SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_value_index.py` | `CSC_ticket_AI_Agent/compute_TroubleTickets_year_value_index.py` |
| value catalog | `SalesDrive_Revenue_Expert/compute_DRIVE_Revenues_Value_Catalog.py` | `CSC_ticket_AI_Agent/compute_TroubleTickets_year_value_catalogue.py` |

The two copies of each template are **byte-identical**: the recipes are
**dataset-agnostic** and auto-detect INPUT/OUTPUT from the DSS Flow wiring
(`dataiku.recipe.get_inputs_as_datasets()` / `get_outputs_as_datasets()`), never
from code constants. The literal dataset names inside the code (which are
revenue-named, e.g. `DRIVE_Revenues`) are only **fallback constants for a
standalone run outside a recipe**; in DSS the Flow wiring always wins, so the
same revenue-named code drives the tickets zone unchanged and the constants are
harmless. Do not "fix" them per zone: the files must stay identical to what is
pasted in DSS.

## Rules that matter when you (re)wire a recipe

- **`*_value_index` outputs MUST live on the SQL connection `SQL_owi`.** The
  sub-agent queries the value index **in SQL at runtime** to ground typed terms to
  exact cell values, so the output has to be a SQL dataset on `SQL_owi` (the same
  connection as the source), not a filesystem dataset.
- **The profile recipe takes an OPTIONAL 2nd input: a `*_profile_overrides`
  dataset** (`{key, field, value}`). When wired, overrides are applied LAST (humans
  always win) and survive re-runs: use it to pin the scenario default, metric
  currency/unit, display pairs, synonyms, the default metric (e.g. ticket COUNT).
  Without it the profile is fully auto-generated (deterministic stats + one LLM
  enrichment pass on aggregated metadata only, never raw rows; everything the LLM
  wrote is flagged `llm_generated: true`).
- **The reads are NA-safe**: they fall back to pandas inference when an integer
  column contains NULLs (e.g. a resolution duration empty for open tickets, which
  otherwise raises "Integer column has NA values").
- **`build_value_catalog` is dataset-adaptive**: the revenue-shaped dataset gets
  the rich curated catalog (account resolvers, offer/business resolvers, hand-crafted
  business-concept aliases); any other dataset (e.g. tickets) gets a generic
  per-value catalog (`search_domain` "value") that feeds the `attribute_lookup`
  "did you mean" fallback.

## The output datasets, per zone

| Output dataset | Built by | Read at runtime by | Role |
|---|---|---|---|
| `DRIVE_Revenues_profile` | `compute_DRIVE_Revenues_profile` | revenue sub-agent (UNDERSTAND, about_data) | business brain (`{key, payload}` contract v1) |
| `DRIVE_Revenues_value_index` | `compute_DRIVE_Revenues_value_index` | revenue sub-agent (RESOLVE, inline SQL) | exact-value grounding; on `SQL_owi` |
| `DRIVE_Revenues_Value_Catalog` | `compute_DRIVE_Revenues_Value_Catalog` | `attribute_lookup` (alias fallback) | rich alias / suggestions catalog |
| `TroubleTickets_year_profile` | `compute_TroubleTickets_year_profile` | tickets sub-agent | business brain (`{key, payload}` v1) |
| `TroubleTickets_year_value_index` | `compute_TroubleTickets_year_value_index` | tickets sub-agent (RESOLVE, inline SQL) | exact-value grounding; on `SQL_owi` |
| `TroubleTickets_year_value_catalogue` | `compute_TroubleTickets_year_value_catalogue` | `attribute_lookup` (generic fallback) | per-value catalog |

The `*_profile` payload is the **profile contract v1**: one `__dataset__` row
(table-level: metrics, scenario, time, grain, descriptions) + one row per column
(role, descriptions, synonyms, enum values, display pairs, stats). The
`*_value_index` shape is `{column_name, value, value_norm, occurrences}`: every
distinct value of every groundable text column + its FROZEN normalized form
(lowercase, accents stripped, whitespace collapsed - shared with the sub-agent's
`_norm`). The `*_Value_Catalog` shape is `{search_domain, source_column,
target_column, target_value, matched_value, display_value, normalized_value,
frequency, canonical_account_name, canonical_carrier_code, parent_group, is_alias}`.

## Re-paste a recipe into DSS

1. Flow: open the target zone, `+ Recipe -> Code -> Python` (or edit the existing
   recipe). Set the INPUT to the base dataset (+ the optional `*_profile_overrides`
   input for a profile recipe). Set the OUTPUT to the target dataset (the value
   index MUST be on the `SQL_owi` connection).
2. Paste the recipe code verbatim from the matching file here. Review the CONFIG
   block (`ENRICH_LLM_ID` for the profile, the column-selection thresholds for the
   value index). Do not per-zone-edit the fallback constants.
3. Run. Keep a **refresh scenario** (weekly, or after each source refresh) so the
   profile + index stay fresh.

To onboard a NEW domain you wire the same three recipes on the new base dataset
with no code edit. Worked example: [`../docs/PLAYBOOK_ADD_AGENT.md`](../docs/PLAYBOOK_ADD_AGENT.md).

## Tests

The profile and value-index templates have pure helpers unit-tested in
[`../tests/test_profiler.py`](../tests/test_profiler.py) (norm, time-format
detection, enrichment validation, column selection). Run:
`python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests`.
