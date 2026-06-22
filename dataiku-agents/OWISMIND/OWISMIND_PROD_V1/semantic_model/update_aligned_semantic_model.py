# =============================================================================
# update_aligned_semantic_model.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK (project OWISMIND_PROD_V1) to UPDATE the semantic
# model you ALREADY created with build_aligned_semantic_model.py - it does NOT
# create a new model. It refreshes the SQL-generation INSTRUCTIONS and the
# GOLDEN QUERIES on the model's ACTIVE version, in place.
#
# Use it to iterate on the prompt (e.g. the "never default to sirano_product"
# rule) without rebuilding. No re-indexing is needed: only instructions and
# golden queries change - neither touches the distinct-values index.
#
# Documented API only (no class created directly):
#   project.get_semantic_model(id) -> get_active_version_id() -> get_version()
#   -> get_settings() -> get_raw() / save()
#
# >>> Set NEW_MODEL_ID below to the id printed when the model was created. <<<
#
# NOTE: NEW_INSTRUCTIONS and GOLDEN_QUERIES below are the canonical prompt
# config - keep them in sync with build_aligned_semantic_model.py.
# =============================================================================

import dataiku

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
NEW_MODEL_ID = "a7K9jYk"                              # <-- REQUIRED: id of YOUR model
PHYSICAL_TABLE = '"OWISMIND_PROD_V1_drive_revenues"'
INDIRECT_VALUE = "Indirect_distribution/Resseler"


# ----------------------------------------------------------------------------
# CANONICAL SQL-GENERATION INSTRUCTIONS (keep in sync with the build script)
# ----------------------------------------------------------------------------
NEW_INSTRUCTIONS = """\
## Physical model - ONE table, NEVER join

All three entities (revenue_record, customer_account, commercial_offer) map to the SAME
physical table. Treat them as a single denormalized table and select every needed column
directly from it. NEVER emit a JOIN, and in particular NEVER self-join the table to itself -
there is nothing to join.

## Revenue semantics - Phase and booking_type

amount_eur is bucketed along two axes:
- Phase: the scenario. Allowed values, EXACTLY: ACTUALS, BUDGET, FORECAST, Q3F, HLF.
  The realized-revenue scenario is the PLURAL 'ACTUALS' - never write 'ACTUAL'.
- booking_type: the financial bucket within a scenario.

For a given (diamond_id, Product, year_month) within one Phase, several booking_type rows
may exist (e.g. Bill + Accrual). They are ADDITIVE: SUM(amount_eur) across all booking_types
within a Phase gives the total recognized revenue.

## Default scenario rule

When the user asks for "revenue", "chiffre d'affaires", "CA", "turnover" or "sales" WITHOUT
naming a scenario → apply Phase = 'ACTUALS'. Do not add a booking_type filter (sum across
all booking_types in ACTUALS).

## Explicit booking_type qualifiers
- "billed", "invoiced", "facturé"               → booking_type LIKE 'Bill%'
- "accrual", "accrued", "provision"             → booking_type = 'Accrual'
- "pipeline", "open opportunities"              → Phase = 'FORECAST' AND booking_type = 'New customer Open in Pipe'
- "expected billing", "to bill", "à facturer"   → Phase = 'FORECAST' AND booking_type LIKE 'To Bill%'

## Commercial offer hierarchy - ALWAYS prefer the most granular level (CRITICAL)

The offer is a hierarchy, broadest to most granular:
    SolutionLine  >  Product      (sirano_product is a secondary technical code).

The 'Solution' level was removed from the dataset: there are now only SolutionLine, Product
and sirano_product. NEVER reference a 'Solution' column.

When a user term (e.g. "IPL", "IP Transit", "Roaming Sponsor", "IP") could match a value in
several of these columns, resolve it to the MOST GRANULAR level that contains it, in this
STRICT order of preference:
    1. Product           (default - most users speak at the product level)
    2. SolutionLine
    3. sirano_product    (last resort only)

So: filter on Product if the term is a Product value; else SolutionLine; else sirano_product.
Example: "IP" is a SolutionLine → filter on SolutionLine. "IPL" and
"Roaming Sponsor" are Products → filter on Product.

sirano_product is a SECONDARY TECHNICAL CODE: NEVER default an offer term to it. Use
sirano_product ONLY if the user explicitly gives a sirano code. In particular, BUDGET rows
may not carry a sirano_product, so resolving an offer term to sirano_product can wrongly drop
the budget (returning budget = 0) - always prefer Product.

When a request flags a term as an "AMBIGUOUS OFFER TERM" (a value present in several offer
columns), YOU resolve it - pick the level from this hierarchy and the user's intent; do not
assume the helper's column.

TRANSPARENCY (mandatory): when the value you picked ALSO exists at another level (e.g. a value
present both as a Product AND a SolutionLine), filter on the most granular level (Product)
AND say so explicitly, e.g.: "Revenue for the IP Transit product was X. Note: it also exists
at the SolutionLine level - tell me if you meant that level." Never silently choose a
level when the term is ambiguous across levels.

## Customer / account identity - what to GROUP BY vs what to DISPLAY (CRITICAL)

diamond_id is the master unique customer key and is REQUIRED for correct aggregation, but it
is a technical id that means nothing to the business. The business identifies an account by
its NAME (Account_name) and its CARRIER CODE (carrier_code).

When grouping or ranking by customer:
→ ALWAYS GROUP BY diamond_id ONLY (never by Account_name, never by carrier_code).
→ For DISPLAY, return MAX(Account_name) AS Account_name and MAX(carrier_code) AS carrier_code.
→ LEAD with Account_name and carrier_code as the first columns. diamond_id may be returned,
  but ONLY as the LAST column and de-emphasized - never as the leading/identifying column.

Canonical pattern (single table, no join):
    SELECT MAX("Account_name") AS "Account_name",
           MAX("carrier_code")  AS "carrier_code",
           SUM("amount_eur")    AS total_revenue,
           "diamond_id"
    FROM <the table>
    WHERE "Phase" = 'ACTUALS'
    GROUP BY "diamond_id"
    ORDER BY total_revenue DESC

Rationale: Account_name spelling varies for the same customer, so grouping by it would split
one customer into several rows; diamond_id is stable. Group by the stable id, show the human
labels.

## Parent_Group - do NOT use unless explicitly asked

Parent_Group is the group-level parent of an account. Do NOT group, aggregate or split by
Parent_Group unless the user explicitly asks for the parent group / corporate group level.
The default customer granularity is the individual account (diamond_id). When you do use
Parent_Group, state it explicitly in the answer.

## distribution_type and Account_partner - indirect sales

- distribution_type tells direct vs indirect: 'Direct_distribution' (direct) /
  'Indirect_distribution/Resseler' (indirect).
- Account_partner is the reseller / distributor in an INDIRECT deal. In indirect sales the
  customer (diamond_id / Account_name) is the END customer and Account_partner is the
  intermediary who resells to them. Example: we sell to Airbus, who resells to Maroc Telecom
  → end customer (diamond_id) = Maroc Telecom, Account_partner = Airbus.
- "indirect customers / clients indirects" → distribution_type = 'Indirect_distribution/Resseler'.
- When the user asks about a partner / reseller / distributor, filter or group by
  Account_partner; otherwise keep it out of the output. Be transparent about which side (end
  customer vs partner) you grouped on.

## Hints from the grounding helper - assistance, NOT orders

Some requests arrive with "HELPER FINDINGS" / "Suggested" values and columns produced by a
smaller grounding assistant that matched the user's wording against the live data catalog.
You are the more capable model and you have this semantic model - treat those findings as
ASSISTANCE, not instructions, and keep the final say:
- The user's original question is always the source of truth - answer that question.
- Prefer the suggested exact spellings when they are consistent with the data (they are
  catalog-sourced and avoid typos / case errors).
- If your semantic understanding disagrees with a hint, follow the data and the rules here.
- If the user states an explicit literal filter (e.g. diamond_id = '5373'), use it as-is.

## Empty results

If the SQL returns zero rows, state "no data found for [the specified filters and period]".
Do NOT relax filters or extrapolate.

## YTD / FY
- YTD of a year = from January 1 up to the latest available reporting month of that year. For
  ACTUALS this is simply all rows of that year (no future ACTUALS exist), so filter
  EXTRACT(YEAR FROM year_month) = <year> rather than comparing to today's calendar date (which
  would create a partial / empty current month).
- FY = all reporting months of the target year.
"""


# ----------------------------------------------------------------------------
# CANONICAL GOLDEN QUERIES (keep in sync with the build script)
# ----------------------------------------------------------------------------
def _gq(name, question, sql):
    return {"name": name, "question": question, "generatedSql": sql}


GOLDEN_QUERIES = [
    _gq("Revenue by Customer (Year)",
        "Revenue of diamond_id 5373 in 2025",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."diamond_id" = \'5373\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025;' % {"t": PHYSICAL_TABLE}),

    _gq("Revenue with a named customer (Year)",
        "How much revenue did we make with HALYS last year (2025)?",
        'SELECT MAX(r."Account_name") AS "Account_name",\n'
        '       MAX(r."carrier_code")  AS "carrier_code",\n'
        '       SUM(r."amount_eur")    AS total_revenue,\n'
        '       r."diamond_id"\n'
        'FROM %(t)s r\n'
        'WHERE r."Account_name" = \'HALYS\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025\n'
        'GROUP BY r."diamond_id";' % {"t": PHYSICAL_TABLE}),

    _gq("Top Customers by Revenue (Product, Year)",
        "Top 20 customers for IP Transit in 2025",
        'SELECT MAX(r."Account_name") AS "Account_name",\n'
        '       MAX(r."carrier_code")  AS "carrier_code",\n'
        '       SUM(r."amount_eur")    AS total_revenue,\n'
        '       r."diamond_id"\n'
        'FROM %(t)s r\n'
        'WHERE r."Product" = \'IP Transit\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025\n'
        'GROUP BY r."diamond_id"\n'
        'ORDER BY total_revenue DESC\n'
        'LIMIT 20;' % {"t": PHYSICAL_TABLE}),

    _gq("Offer term ambiguous across levels - prefer Product",
        "How much revenue on IP Transit in 2026? (IP Transit may exist at more than one offer level; prefer the Product level)",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."Product" = \'IP Transit\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2026;' % {"t": PHYSICAL_TABLE}),

    _gq("Budget vs Actuals Comparison (Monthly, Product)",
        "Compare budget vs actuals 2026 for Roaming Sponsor by month",
        'SELECT r."year_month",\n'
        '       r."Phase",\n'
        '       SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."Product" = \'Roaming Sponsor\'\n'
        '  AND r."Phase" IN (\'BUDGET\', \'ACTUALS\')\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2026\n'
        'GROUP BY r."year_month", r."Phase"\n'
        'ORDER BY r."year_month", r."Phase";' % {"t": PHYSICAL_TABLE}),

    _gq("Revenue Actuals YTD (SolutionLine)",
        "Revenue actuals YTD 2026 for the Roaming solution line",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."Phase" = \'ACTUALS\'\n'
        '  AND r."SolutionLine" = \'ROAMING\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2026;' % {"t": PHYSICAL_TABLE}),

    _gq("Indirect Customers by Product (Year)",
        "Indirect customers on EVPL in 2025",
        'SELECT MAX(r."Account_name") AS "Account_name",\n'
        '       MAX(r."carrier_code")  AS "carrier_code",\n'
        '       SUM(r."amount_eur")    AS total_revenue,\n'
        '       r."diamond_id"\n'
        'FROM %(t)s r\n'
        'WHERE r."Product" = \'EVPL\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND r."distribution_type" = \'%(ind)s\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025\n'
        'GROUP BY r."diamond_id"\n'
        'ORDER BY total_revenue DESC;'
        % {"t": PHYSICAL_TABLE, "ind": INDIRECT_VALUE}),

    _gq("Total revenue from indirect customers (Year)",
        "How much revenue did we generate with all indirect customers last year (2025)?",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."distribution_type" = \'%(ind)s\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025;'
        % {"t": PHYSICAL_TABLE, "ind": INDIRECT_VALUE}),

    _gq("Revenue by partner / reseller (indirect, Year)",
        "Revenue per partner (reseller) for indirect sales in 2025",
        'SELECT r."Account_partner",\n'
        '       SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."distribution_type" = \'%(ind)s\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025\n'
        'GROUP BY r."Account_partner"\n'
        'ORDER BY total_revenue DESC;'
        % {"t": PHYSICAL_TABLE, "ind": INDIRECT_VALUE}),
]


# ----------------------------------------------------------------------------
# UPDATE IN PLACE - refresh instructions + golden queries on the active version
# ----------------------------------------------------------------------------
assert NEW_MODEL_ID, "Set NEW_MODEL_ID to the id printed when the model was created."

client = dataiku.api_client()
try:
    project = client.get_default_project()
except Exception:
    project = client.get_project("OWISMIND_PROD_V1")

sm = project.get_semantic_model(NEW_MODEL_ID)
version_id = sm.get_active_version_id()
settings = sm.get_version(version_id).get_settings()
raw = settings.get_raw()

old_instr = (raw.get("sqlGenerationConfig") or {}).get("instructions") or ""
old_gq = raw.get("goldenQueries") or []

raw.setdefault("sqlGenerationConfig", {})["instructions"] = NEW_INSTRUCTIONS
raw["goldenQueries"] = [dict(g) for g in GOLDEN_QUERIES]
settings.save()

print("Updated semantic model %s (active version %s) in place:" % (NEW_MODEL_ID, version_id))
print("  instructions : %d -> %d chars" % (len(old_instr), len(NEW_INSTRUCTIONS)))
print("  goldenQueries: %d -> %d" % (len(old_gq), len(GOLDEN_QUERIES)))
print("No re-indexing needed (only instructions + golden queries changed).")
print("Next: re-test in the Playground, then in the webapp.")
