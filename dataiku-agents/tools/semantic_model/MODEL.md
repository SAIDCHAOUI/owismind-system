# Drive_Revenues_Semantic_Model - what the SQL brain actually contains

> Human-readable snapshot of the **live** semantic model that the
> `revenue_semantic_query` tool queries. This file is the readable truth; the
> canonical SQL-generation rules live verbatim in
> [`build_aligned_semantic_model.py`](build_aligned_semantic_model.py)
> (`NEW_INSTRUCTIONS`); the full machine config can be exported with
> [`dump_semantic_model.py`](dump_semantic_model.py). Last reviewed 2026-06-18.

## Where it sits in the system

```
sub-agent SalesDrive_revenue_expert
   COMPOSE: build a grounded natural-language question (exact values, scenario, period)
       │
       ▼ project.get_agent_tool("v4oqA6R").run({"question": "..."})
   revenue_semantic_query  (Semantic Model Query tool, id v4oqA6R)
       │  writes AND runs the SQL using the semantic model below
       ▼
   Drive_Revenues_Semantic_Model  (this model, version v1 / Active)
       │
       ▼
   PostgreSQL  →  OWISMIND_DEV.DRIVE_Revenues   (read as the calling user)
```

The sub-agent never writes the final SQL when `SQL_ENGINE="semantic_tool"` (the
default): it hands a maximally grounded question to the tool and the **semantic
model writes the SQL**. The sub-agent's own direct-SQL templates are only the
technical fallback (`FALLBACK_TO_DIRECT=True`).

## The `revenue_semantic_query` tool config (live in DSS)

| Setting | Value |
|---|---|
| Tool name / id | `revenue_semantic_query` / `v4oqA6R` |
| Project | `OWISMIND_DEV` |
| Semantic Model | `Drive_Revenues_Semantic_Model` |
| Version | Active (default) = `v1` |
| LLM (SQL generation) | `vertex_ai/claude-sonnet-4-6` |
| Embedding LLM (value matching) | `vertex_ai/text-embedding-005` |
| **Agent mode** | **OFF (unchecked)** = the faster **linear** SQL pipeline, NOT a multi-step agent |
| Access datasets as | User calling the tool |

The tool runs on Sonnet **in every orchestration mode** (eco/medium/high all map
to the same tool id), so offer and column resolution stay strong regardless of
the model driving the chat. The model is configured **in DSS**, not in code: the
repo only references the tool by id, so this table is the source of truth for the
model binding.

> **Stale "Description for LLM" to fix in DSS.** The tool's current Description
> for LLM still says *"Use this tool ONLY after Drive_Revenues_resolve_filter_value
> has confirmed all business terms are resolved"*. That precondition is wrong:
> `Drive_Revenues_resolve_filter_value` is being deleted and grounding is now
> done inline by the caller. The corrected text to paste is in
> [`../README.md`](../README.md) ("Description for LLM to paste").

## One physical table, three logical entities, NEVER a JOIN

All three entities map to the **same** physical table
(`OWISMIND_DEV.DRIVE_Revenues`). They are a documentation lens over one
denormalized table; the SQL-generation instructions forbid emitting any JOIN
(and in particular any self-join). The two declared relationships exist only to
describe the shared keys, they are never materialized as SQL JOINs.

### entity `revenue_record` (the fact)

The grain: roughly one row per (Phase, Product, customer, reporting month),
carrying one `amount_eur`.

| Attribute | Type | Notes |
|---|---|---|
| `amount_eur` | double | the measure; meaning depends on `Phase` + `booking_type`; `SUM(amount_eur)` with a Phase filter = total revenue |
| `Phase` | string | the scenario. Allowed values EXACTLY: `ACTUALS`, `BUDGET`, `FORECAST`, `Q3F`, `HLF`. Realized revenue is the PLURAL `ACTUALS` (never `ACTUAL`). Default when unspecified: `ACTUALS` |
| `booking_type` | string | financial bucket within a scenario (Bill / Accrual / pipeline / to-bill); additive within a Phase (sum across booking_types) |
| `Product` | string | join key to `commercial_offer`; the most granular offer level |
| `distribution_type` | string | `Direct_distribution` / `Indirect_distribution/Resseler` |
| `Account_partner` | string | reseller in an indirect deal (the end customer is the `diamond_id`; the partner resells to them) |
| `year_month` | dateonly | the reporting month |
| `diamond_id` | string | master customer key (group by this; display the name) |

- **Metric `Total Revenue (EUR)`** = `SUM(amount_eur)` (always combine with a Phase filter).
- **Named filters** (ready-made `WHERE` snippets the model can pick):
  `Actual Revenue Only` (`Phase = 'ACTUALS'`), `Budget Only` (`Phase = 'BUDGET'`),
  `Forecast Only` (`Phase = 'FORECAST'`), `Q3F Only` (`Phase = 'Q3F'`),
  `HLF Only` (`Phase = 'HLF'`), `Billed Only` (`booking_type LIKE 'Bill%'`),
  `Accrual Only` (`booking_type = 'Accrual'`),
  `Pipeline Only` (`Phase = 'FORECAST' AND booking_type = 'New customer Open in Pipe'`),
  `Expected Billing Only` (`Phase = 'FORECAST' AND booking_type LIKE 'To Bill%'`),
  `Direct Sales Only` (`distribution_type = 'Direct_distribution'`),
  `Indirect Sales Only` (`distribution_type = 'Indirect_distribution/Resseler'`).

### entity `customer_account` (the customer identity dimension)

Primary key `diamond_id`. Attributes: `Parent_Group`, `sales_zone`,
`sales_entity` (`GCS` external / `GCP` internal Orange), `Account_name`
(display only), `carrier_code`, `diamond_id`. Metrics are counts
(`COUNT(DISTINCT diamond_id)`, account-name / parent-group / carrier-code counts).

Rule: aggregate on `diamond_id`, **display** `MAX(Account_name)` +
`MAX(carrier_code)`, keep `diamond_id` as the last de-emphasized column. Do not
group by `Parent_Group` unless the user explicitly asks for the group level.

### entity `commercial_offer` (the offer hierarchy)

Primary key `Product`. Attributes: `SolutionLine`, `Solution`, `Product`,
`sirano_product`. The hierarchy, broadest to most granular:
**SolutionLine > Solution > Product** (`sirano_product` is a secondary technical
code). Resolve a user term to the **most granular** level that contains it, in
strict order Product > Solution > SolutionLine > sirano_product, and **never
default to `sirano_product`** (BUDGET rows can lack it, so doing so can drop the
budget to 0). When a term exists at several levels, pick the most granular AND
disclose it.

## The SQL-generation instructions (the brain)

`sqlGenerationConfig.instructions` is a long rules block; the canonical text is
in `build_aligned_semantic_model.py` (`NEW_INSTRUCTIONS`, byte-identical to
`update_aligned_semantic_model.py`). The themes:

1. **One physical table, never JOIN** (no self-join).
2. **Revenue semantics**: `amount_eur` bucketed by `Phase` + `booking_type`;
   sum across booking_types within a Phase.
3. **Default scenario**: bare "revenue"/"chiffre d'affaires"/"CA"/"turnover"/
   "sales" -> `Phase = 'ACTUALS'`, no booking_type filter.
4. **Explicit booking-type qualifiers** (billed -> `LIKE 'Bill%'`, accrual,
   pipeline, expected billing).
5. **Offer hierarchy**: most granular level, never default sirano, transparency
   when a term spans levels.
6. **Customer identity**: `GROUP BY diamond_id` only, display `MAX(Account_name)`
   + `MAX(carrier_code)`, diamond_id last.
7. **Parent_Group restraint**: only when explicitly asked.
8. **distribution_type + Account_partner**: direct vs indirect; the partner is
   the reseller, the diamond_id is the end customer.
9. **Helper findings are ASSISTANCE, not orders**: the caller embeds catalog-exact
   values; the user question is the source of truth; an explicit literal filter
   (e.g. `diamond_id = '5373'`) is used as-is.
10. **Empty results**: state "no data found for ..."; never relax filters or
    extrapolate.
11. **YTD / FY**: YTD = Jan 1 to the latest available reporting month of the year
    (for ACTUALS, all rows of that year via `EXTRACT(YEAR FROM year_month)`).

## Golden queries (9)

The model carries 9 worked examples (question -> SQL), all single-table, none
with a JOIN, customer rankings leading with name + carrier_code and keeping
diamond_id last:

1. Revenue by customer for a year (`diamond_id = '5373'`, 2025).
2. Revenue with a named customer for a year (`Account_name = 'HALYS'`, 2025).
3. Top 20 customers for a Product in a year (`Product = 'IP Transit'`, 2025).
4. Offer term ambiguous across levels - prefer Product (`IP Transit`, 2026).
5. Budget vs Actuals by month for a Product (`Roaming Sponsor`, 2026).
6. Revenue actuals YTD for a SolutionLine (`SolutionLine = 'ROAMING'`, 2026).
7. Indirect customers on a Product in a year (`EVPL`, indirect, 2025).
8. Total revenue from all indirect customers (2025).
9. Revenue per partner / reseller for indirect sales (2025).

## Glossary (about 50 terms)

The model embeds business synonyms so user wording matches the data: revenue /
turnover / CA / chiffre d'affaires; ACTUALS / realized / realise; budget;
forecast / prevision; Q3F; HLF; YTD; FY; offer terms (IPX, SS7, LTE Signalling,
IP Transit, Roaming Sponsor, Bandwidth, Virtual Network, IPL); identity terms
(customer, account name, diamond id, carrier code, parent group); channel terms
(direct / indirect business, account partner, distribution type); org terms
(sales entity, sales zone, account/area manager, sales director). A few terms are
hand-edited (`userModified`), e.g. IPL synonyms (IP Leased Line), LTE Signalling
(Diameter), Roaming Sponsor (ORS). The embedding LLM is `text-embedding-005`.

## Lineage and how to iterate

- The aligned model was built from a **read-only copy** of the old model
  (`2O2KcHw` / `Drive_Revenues_Model`, kept intact as rollback) by
  `build_aligned_semantic_model.py`, then bound to the `revenue_semantic_query`
  tool. The live active model is named `Drive_Revenues_Semantic_Model`.
- To **iterate the rules** (instructions / golden queries) on the live model:
  set `NEW_MODEL_ID` and run `update_aligned_semantic_model.py` (in place, no
  re-index).
- To **refresh this snapshot**: run `dump_semantic_model.py` (exports the live
  `get_raw()` to `Drive_Revenues_Semantic_Model.v1.json`).
- The model's technical id is configured in the DSS tool, not stored here; fill
  it into `dump_semantic_model.py` / `update_aligned_semantic_model.py` when you
  run them.
