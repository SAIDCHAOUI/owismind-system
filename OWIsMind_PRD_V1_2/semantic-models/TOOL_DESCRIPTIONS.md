# Semantic Model Query tools - "Description for LLM" (paste into DSS)

Each Semantic Model Query tool has a **Description for LLM** field (DSS: the tool
settings, "Additional setup"). It is appended to the auto-generated internal
description and passed to the model, so it reinforces, at the tool interface, the
same rules that live in the model's `sqlGenerationConfig.instructions`. Paste the
matching block verbatim. Keep it in sync with the model instructions
(`update_*_semantic_model.py`).

---

## tickets_semantic_query  (model TroubleTickets_Semantic_Model, DEV id nEirlso)

```
Queries the OWI incident-tickets data (TroubleTickets) and returns a result table that is
shown to the user and read by another model to write the answer. Return clean tabular output
with explicit column aliases, never prose.

ONE physical table, never join. There is no scenario column; every row is a real ticket.

DUPLICATE ROWS (critical): the table keeps historical snapshots, so the same ticket "id"
appears on several rows (an update adds a row, old rows are kept). VOLUME = COUNT(DISTINCT
"id"), never COUNT(*); write it directly, no CTE. A ticket's CURRENT STATE (status, closing
date, duration, reason) must come from its LATEST snapshot per id (greatest "lastUpdate"):
WITH latest AS (SELECT DISTINCT ON ("id") * FROM <table> ORDER BY "id","lastUpdate" DESC NULLS
LAST) SELECT ... FROM latest.

DATES: default to "creationDate" for any time window with no explicit lifecycle verb ("this
year", "cette annee", "en 2025", "created/crees/ouverts"). Use "Latest_Closed_Date" ONLY for
closing/resolution questions; "detectionDate"/"lastUpdate" only when explicitly asked. Filter
a year with EXTRACT(YEAR FROM "creationDate") = <year>.

EXACT VALUES, NEVER ILIKE: filter named entities (Account_name, Service_id_1, Product) on the
exact catalog value with "=" / IN, using the HELPER FINDINGS supplied with the question. Never
ILIKE '%...%' on a name, and NEVER fabricate or complete a name from general knowledge - if no
grounded value is given, return no data and name the entity you could not resolve.

LD = "Service_id_1" (the dominant lookup key; codes like LD000123). For an LD question lead the
output with the LD, ticket "id", "Account_name", "CurrentStatus" and the dates, taking the
latest snapshot.

IDENTITY: GROUP BY "Customer_id", DISPLAY MAX("Account_name"); lead with the ticket "id",
"Account_name", dates, the LD and "Product"; keep "Customer_id" as the last, de-emphasized
column. No customer-group hierarchy exists: report the exact account matched and list other
close matches rather than merging group entities.

DURATION = "Duration_ticket_total" in MINUTES (AVG by default, on the latest snapshot per id;
SUM is rarely meaningful). State the unit.

Empty result: say "no data found for [the filters and period]"; never relax filters or guess.
```

---

## revenue_semantic_query  (model Drive_Revenues_Semantic_Model, DEV id v4oqA6R)

Replaces the stale text that referenced the deleted `Drive_Revenues_resolve_filter_value`
precondition (grounding is now inline; that tool is being removed).

```
Queries the OWI customer-revenue data (DRIVE_Revenues) and returns a result table that is shown
to the user and read by another model to write the answer. Return clean tabular output with
explicit column aliases, never prose.

ONE physical table, never join. amount_eur is bucketed by Phase (the scenario: ACTUALS, BUDGET,
FORECAST, Q3F, HLF) and booking_type; default to Phase = 'ACTUALS' when no scenario is named.

EXACT VALUES, NEVER ILIKE: filter named entities (Account_name, Product, SolutionLine) on the
exact catalog value with "=" / IN, using the HELPER FINDINGS: a typed partial name must become
the FULL exact catalog value, never an ILIKE pattern on a fragment. Never fabricate a name; if
no grounded value is given, return no data and name the entity you could not resolve.

IDENTITY: GROUP BY "diamond_id", DISPLAY MAX("Account_name") + MAX("carrier_code"); keep
diamond_id last. OFFER hierarchy: prefer Product, then SolutionLine; never default to
sirano_product. Period: filter EXTRACT(YEAR FROM year_month) = <year>.

Empty result: say "no data found for [the filters and period]"; never relax filters or guess.
```
