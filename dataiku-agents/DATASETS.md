# DATASETS - the canonical column inventory

> One place that lists every dataset an OWIsMind agent touches, with columns,
> types, role, and which runtime consumer reads it. This replaces the column
> lists that used to be duplicated across the READMEs. The per-domain spec (ids,
> dataset names, semantic model + tool binding, lookup config, guardrails) lives
> in [`registry.json`](registry.json). Last reviewed 2026-06-19.

## How to read the role columns

- **role**: `measure` (numeric, aggregated), `dimension` (group / filter),
  `time` (date axis), `identifier` (key / id), `free_text` (prose, not grouped).
- **value_index**: `yes` = indexed by `build_value_index_recipe` so the sub-agent
  can ground a typed term to its exact value + column (categorical text columns
  only; numerics / dates / quasi-unique ids / long prose are skipped).
- **lookup search**: `yes` = in the `attribute_lookup` search allowlist for this
  domain (named-entity / id text columns the user looks up directly). Any column
  is still **returnable** as a lookup attribute regardless of this flag.

The four design-time datasets per domain (built by the Flow recipes): `<base>`
(source), `<base>_profile` (the business brain, `{key,payload}`),
`<base>_value_index` (`{column_name,value,value_norm,occurrences}`, MUST be on the
`SQL_owi` connection), and the optional `<base>_Value_Catalog` (alias fallback).

---

## DRIVE_Revenues  (revenue_expert)  -  175,780 rows, 20 cols, connection SQL_owi

Base table of the revenue domain. Read by the semantic model (SQL) and by
`attribute_lookup`. The business meaning lives in `DRIVE_Revenues_profile` and the
semantic model `Drive_Revenues_Semantic_Model`.

| Column | DSS type | role | value_index | lookup search | Notes |
|---|---|---|---|---|---|
| `Phase` | string | dimension | yes | no | scenario: ACTUALS / BUDGET / FORECAST / Q3F / HLF (default ACTUALS) |
| `booking_type` | string | dimension | yes | no | financial bucket within a Phase (additive) |
| `SolutionLine` | string | dimension | yes | no | offer hierarchy (broadest) |
| `Solution` | string | dimension | yes | no | offer hierarchy |
| `Product` | string | dimension | yes | no | offer hierarchy (most granular business level) |
| `Account_name` | string | dimension | yes | no | customer display name (group by diamond_id, display this) |
| `Account_partner` | string | dimension | yes | no | reseller in an indirect deal |
| `distribution_type` | string | dimension | yes | no | Direct_distribution / Indirect_distribution/Resseler |
| `Parent_Group` | string | dimension | yes | no | corporate parent (use only when asked) |
| `carrier_code` | string | dimension | yes | no | account carrier code (display) |
| `year_month` | date | time | no | no | reporting month (the time axis) |
| `amount_eur` | decimal | measure | no | no | the revenue measure; SUM with a Phase filter |
| `sales_entity` | string | dimension | yes | no | GCS external / GCP internal |
| `sales_zone` | string | dimension | yes | no | sales zone |
| `account_manager` | string (email) | dimension | yes | no | owner email |
| `area_manager` | string (email) | dimension | yes | no | owner email |
| `sales_director` | string (email) | dimension | yes | no | owner email |
| `diamond_id` | string | identifier | yes | no | master customer key (GROUP BY this) |
| `sirano_product` | string | dimension | yes | no | secondary technical code (never default an offer term to it) |
| `original_dataset` | string | free_text | no | no | lineage |

> Revenue keeps the FULL lookup search (no allowlist) - validated in DSS. The
> lookup is wired by the orchestrator registry, not a column flag.

---

## TroubleTickets_year  (tickets_expert)  -  83,738 rows, 21 cols, connection SQL_owi

Base table of the incident-tickets domain. One row = one incident / trouble
ticket. **No scenario column** (every row is a real ticket). Primary measure =
ticket COUNT; resolution time = `Duration_ticket_total`. `Account_name` and
`Customer_id` are the natural bridge to `DRIVE_Revenues` for a future 360.

| Column | DSS type | role | value_index | lookup search | Notes |
|---|---|---|---|---|---|
| `id` | string | identifier | no | yes | ticket id (exact-id lookup; quasi-unique, not value-indexed) |
| `ticketType` | string | dimension | yes | no | kind of ticket (enum) |
| `ticketEntry` | string | dimension / free_text | maybe | no | entry; if prose, auto-skipped by the index; kept out of lookup search |
| `priority` | string | dimension | yes | no | severity (enum) |
| `origin` | string | dimension | yes | no | channel / source (enum) |
| `category` | string | dimension | yes | no | problem classification (enum) |
| `creationDate` | datetime (tz) | time | no | no | ticket opened - DEFAULT time axis |
| `detectionDate` | datetime (tz) | time | no | no | incident detected |
| `lastUpdate` | datetime (tz) | time | no | no | last modification |
| `CurrentStatus` | string | dimension | yes | no | lifecycle state (open vs closed family); use EXACT indexed values |
| `CurrentStatus_Reason` | natural language | free_text | no | no | prose; never grouped, never searched |
| `Latest_Closed_Date` | datetime (tz) | time | no | no | when closed (closed-ticket timing) |
| `Duration_ticket_total` | integer | measure | no | no | resolution duration (AVG by default; CONFIRM the unit) |
| `CustomerRepresentative_Name` | string | dimension | yes | yes | OWI representative for the account |
| `Customer_id` | integer | identifier | no | no | stable customer key (GROUP BY this; numeric so not searched) |
| `Account_name` | string | dimension | yes | yes | customer display name (display; group by Customer_id) |
| `Service_id` | string | identifier | yes | yes | affected service id |
| `Service_Specification_id` | string | identifier | yes | yes | service specification id |
| `Product` | string | dimension | yes | yes | affected product |
| `Service_id_1` | string | identifier | yes | yes | secondary service id |
| `problemCategory` | string | dimension | yes | no | problem category (enum) |

> Lookup search allowlist (`registry.json` -> tickets_expert.lookup.search_columns):
> `Account_name, CustomerRepresentative_Name, Service_id, Service_Specification_id,
> Service_id_1, Product, id`. Long free-text columns (`ticketEntry`,
> `CurrentStatus_Reason`) are deliberately excluded so a short needle does not
> match noisily. Enums (`priority`, `CurrentStatus`, `category`, ...) are resolved
> by the specialist via the value index, not the fast lookup - but remain
> returnable as lookup attributes.

### Human curation items (the irreducible part - confirm against the real data)

- **`Duration_ticket_total` unit**: seconds / minutes / hours? Set it in the
  semantic-model instructions and the profile metric label.
- **`CurrentStatus` exact values**: the open vs closed states (from the value
  index after the recipe runs). Pin them in the semantic-model instructions.
- **Default metric**: COUNT of tickets (not SUM of duration). Enforce via the
  `TroubleTickets_year_profile_overrides` dataset (see `recipes/README.md`):
  `__dataset__ / default_metric = ticket_count`, plus `ticket_count` (COUNT) and
  `avg_duration` (AVG of Duration_ticket_total, format `number`) in `metrics`.
