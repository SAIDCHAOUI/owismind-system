# =============================================================================
# build_aligned_semantic_model.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK (project OWISMIND_DEV). It creates a brand-new
# semantic model aligned with the OWIsMind sub-agent, WITHOUT touching the
# existing one (id "2O2KcHw" / "Drive_Revenues_Model" stays 100% intact).
#
# Strictly follows the documented public API only:
#   - project.get_semantic_model(id)                  (read the source, READ-ONLY)
#   - project.create_semantic_model(name)             (new model)
#   - DSSSemanticModel.new_version / get_version / list_versions_ids /
#     set_active_version_id
#   - DSSSemanticModelVersionSettings.get_raw / save
#   - DSSSemanticModelVersion.start_update_distinct_values
# No class is ever instantiated directly (the doc forbids it); no undocumented
# endpoint is called; the old model is opened read-only and never saved.
#
# Strategy (safest possible): we read the LIVE active version of the old model
# as ground truth, deep-copy it, apply deterministic corrections on the copy,
# then push the corrected config into a NEW model. You can review every change
# in the printed diff before the model is activated/indexed (the last two steps
# are isolated so you stay in control).
#
# Docs:
#   https://developer.dataiku.com/latest/api-reference/python/semantic-models.html
#   https://developer.dataiku.com/latest/api-reference/python/projects.html
# =============================================================================

import copy
import json

import dataiku

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
OLD_SEMANTIC_MODEL_ID = "2O2KcHw"             # existing model - READ ONLY
NEW_SEMANTIC_MODEL_NAME = "Drive_Revenues_Model (aligned)"
NEW_VERSION_ID = "v1"                         # first version of the NEW model

# Physical table literal used inside golden-query SQL (matches the existing
# golden queries of the source model - PostgreSQL, case-sensitive identifiers).
PHYSICAL_TABLE = '"OWISMIND_DEV_drive_revenues"'

# Exact data literals (verified against the source model's manualValues / golden
# queries). Keep these in sync with the data - they are the only business values
# this script asserts, and they mirror what the dataset actually contains.
PHASE_ACTUALS = "ACTUALS"                     # realized revenue (NOT 'ACTUAL')
INDIRECT_VALUE = "Indirect_distribution/Resseler"


# ----------------------------------------------------------------------------
# NEW GLOBAL SQL-GENERATION INSTRUCTIONS
# This is the single most important field. It encodes, for the model itself
# (Playground / un-grounded terms), the same rules the sub-agent enforces at
# runtime: one physical table, ACTUALS default, commercial-hierarchy priority
# with transparency, customer display (name + carrier_code, diamond_id discreet),
# Parent_Group restraint, and the indirect/Account_partner semantics.
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
    SolutionLine  >  Solution  >  Product      (sirano_product is a secondary technical code).

When a user term (e.g. "IPL", "IP Transit", "Roaming Sponsor", "IP") could match a value in
several of these columns, resolve it to the MOST GRANULAR level that contains it, in this
STRICT order of preference:
    1. Product           (default - most users speak at the product level)
    2. Solution
    3. SolutionLine
    4. sirano_product    (last resort only)

So: filter on Product if the term is a Product value; else Solution; else SolutionLine; else
sirano_product. Example: "IP" is a SolutionLine → filter on SolutionLine. "IPL" and
"Roaming Sponsor" are Products → filter on Product.

sirano_product is a SECONDARY TECHNICAL CODE: NEVER default an offer term to it. Use
sirano_product ONLY if the user explicitly gives a sirano code. In particular, BUDGET rows
may not carry a sirano_product, so resolving an offer term to sirano_product can wrongly drop
the budget (returning budget = 0) - always prefer Product.

When a request flags a term as an "AMBIGUOUS OFFER TERM" (a value present in several offer
columns), YOU resolve it - pick the level from this hierarchy and the user's intent; do not
assume the helper's column.

TRANSPARENCY (mandatory): when the value you picked ALSO exists at another level (e.g.
"IP Transit" is both a Product AND a Solution), filter on the most granular level (Product)
AND say so explicitly, e.g.: "Revenue for the IP Transit product was X. Note: IP Transit
also exists as a Solution - tell me if you meant the Solution level." Never silently choose a
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
# CORRECTED + ENRICHED GOLDEN QUERIES
# Each teaches one rule. Customer rankings lead with Account_name + carrier_code
# and keep diamond_id last; the table is queried WITHOUT any join.
# ----------------------------------------------------------------------------
def _gq(name, question, sql):
    return {"name": name, "question": question, "generatedSql": sql}


GOLDEN_QUERIES = [
    # 1. Single customer total by explicit diamond_id (kept from source).
    _gq("Revenue by Customer (Year)",
        "Revenue of diamond_id 5373 in 2025",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."diamond_id" = \'5373\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025;' % {"t": PHYSICAL_TABLE}),

    # 2. Customer lookup BY NAME - display name + carrier_code, group by id.
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

    # 3. Top customers - NO self-join, name + carrier_code first, diamond_id last.
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

    # 4. Term that is BOTH a Product and a Solution -> prefer Product.
    _gq("Offer term ambiguous across levels - prefer Product",
        "How much revenue on IP Transit in 2026? (IP Transit is both a Product and a Solution; prefer the Product level)",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."Product" = \'IP Transit\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2026;' % {"t": PHYSICAL_TABLE}),

    # 5. Budget vs Actuals monthly (kept from source).
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

    # 6. YTD at SolutionLine level - no hardcoded "today", all of the year.
    _gq("Revenue Actuals YTD (SolutionLine)",
        "Revenue actuals YTD 2026 for the Roaming solution line",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."Phase" = \'ACTUALS\'\n'
        '  AND r."SolutionLine" = \'ROAMING\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2026;' % {"t": PHYSICAL_TABLE}),

    # 7. Indirect customers for a product - name + carrier first, diamond_id last.
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

    # 8. Total revenue from ALL indirect customers.
    _gq("Total revenue from indirect customers (Year)",
        "How much revenue did we generate with all indirect customers last year (2025)?",
        'SELECT SUM(r."amount_eur") AS total_revenue\n'
        'FROM %(t)s r\n'
        'WHERE r."distribution_type" = \'%(ind)s\'\n'
        '  AND r."Phase" = \'ACTUALS\'\n'
        '  AND EXTRACT(YEAR FROM r."year_month") = 2025;'
        % {"t": PHYSICAL_TABLE, "ind": INDIRECT_VALUE}),

    # 9. Revenue per RESELLER/partner (indirect) - uses Account_partner.
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
# DETERMINISTIC CORRECTIONS on a deep copy of the source raw settings.
# Helpers locate elements by NAME (robust to ordering / key presence).
# ----------------------------------------------------------------------------
def _find(items, key, value):
    for it in items or []:
        if it.get(key) == value:
            return it
    return None


def _entity(raw, name):
    return _find(raw.get("entities"), "name", name)


def _attr(entity, name):
    return _find((entity or {}).get("attributes"), "name", name)


def _filter(entity, name):
    return _find((entity or {}).get("filters"), "name", name)


def apply_corrections(raw):
    """Mutate `raw` in place. Returns a list of human-readable change notes."""
    changes = []

    # --- 1. Phase = 'ACTUAL' -> 'ACTUALS' everywhere (silent zero-rows bug) ---
    rr = _entity(raw, "revenue_record")
    if rr:
        before = rr.get("description", "")
        rr["description"] = before.replace("'ACTUAL'", "'%s'" % PHASE_ACTUALS)
        if rr["description"] != before:
            changes.append("revenue_record.description: 'ACTUAL' -> 'ACTUALS'")

        phase_attr = _attr(rr, "Phase")
        if phase_attr:
            b = phase_attr.get("description", "")
            phase_attr["description"] = b.replace("'ACTUAL'", "'%s'" % PHASE_ACTUALS)
            if phase_attr["description"] != b:
                changes.append("attribute Phase.description: 'ACTUAL' -> 'ACTUALS'")

        actual_filter = _filter(rr, "Actual Revenue Only")
        if actual_filter:
            b_sql = actual_filter.get("pseudoSQLExpression", "")
            actual_filter["pseudoSQLExpression"] = b_sql.replace(
                "'ACTUAL'", "'%s'" % PHASE_ACTUALS)
            b_desc = actual_filter.get("description", "")
            actual_filter["description"] = b_desc.replace(
                "'ACTUAL'", "'%s'" % PHASE_ACTUALS)
            changes.append("filter 'Actual Revenue Only': Phase = 'ACTUAL' -> 'ACTUALS' "
                           "(was matching ZERO rows)")

        # --- 5. Parent_Group restraint (lives on customer_account, see below) ---

    # --- 2. commercial_offer description: full hierarchy + transparency ------
    co = _entity(raw, "commercial_offer")
    if co:
        co["description"] = (
            "Commercial offer hierarchy, broadest to most granular: "
            "SolutionLine > Solution > Product (sirano_product is a secondary technical "
            "code). When a user term (e.g. 'IPL', 'IP Transit', 'Roaming Sponsor', 'IP') "
            "could match several levels, resolve it to the MOST GRANULAR level that contains "
            "it, in strict order: Product first, then Solution, then SolutionLine, then "
            "sirano_product. When the value also exists at another level (e.g. 'IP Transit' "
            "is both a Product and a Solution), filter the most granular level (Product) and "
            "say so explicitly so the user can ask for the other level.")
        changes.append("commercial_offer.description: hierarchy priority + sirano_product "
                       "fallback + transparency rule")

    # --- 3 + 5. customer_account: Account_partner example + Parent_Group rule --
    ca = _entity(raw, "customer_account")
    if ca:
        pg = _attr(ca, "Parent_Group")
        if pg:
            pg["description"] = (
                "Group-level parent entity linked to the account. Do NOT group, aggregate or "
                "split by Parent_Group unless the user explicitly asks for the parent / "
                "corporate group level; the default customer granularity is the individual "
                "account (diamond_id). When used, state it explicitly.")
            changes.append("attribute Parent_Group.description: 'do not use unless asked'")

    # Account_partner lives on the revenue_record entity in the source model.
    if rr:
        ap = _attr(rr, "Account_partner")
        if ap:
            ap["description"] = (
                "Reseller / distributor in an INDIRECT deal (distribution_type = "
                "'%s'). The customer (diamond_id / Account_name) is the END customer; "
                "Account_partner is the intermediary who resells to them. Example: we sell to "
                "Airbus, who resells to Maroc Telecom -> end customer = Maroc Telecom, "
                "Account_partner = Airbus. Populated only for indirect sales." % INDIRECT_VALUE)
            changes.append("attribute Account_partner.description: explicit indirect / "
                           "Airbus->Maroc Telecom example")

    # --- 4. Glossary fixes ---------------------------------------------------
    terms = raw.get("glossaryTerms") or []
    # 4a. remove the bogus diamond_id term (it actually describes original_dataset).
    bogus = [t for t in terms
             if t.get("term") == "diamond_id"
             and "lineage" in (t.get("description") or "").lower()]
    if bogus:
        for t in bogus:
            terms.remove(t)
        changes.append("glossary: removed bogus 'diamond_id' term (described "
                       "original_dataset / lineage - collided with the real Diamond ID)")
    # 4b. drop the wrong 'roaming hub' synonym from Roaming Sponsor (different product).
    rs = _find(terms, "term", "Roaming Sponsor")
    if rs and rs.get("synonyms"):
        kept = [s for s in rs["synonyms"] if s.strip().lower() != "roaming hub"]
        if len(kept) != len(rs["synonyms"]):
            rs["synonyms"] = kept
            changes.append("glossary: removed 'roaming hub' synonym from 'Roaming Sponsor' "
                           "(Roaming Hub is a Solution, a different offer)")
    raw["glossaryTerms"] = terms

    # --- 6. Golden queries: replace with the corrected + enriched set --------
    raw["goldenQueries"] = [dict(g) for g in GOLDEN_QUERIES]
    changes.append("goldenQueries: rebuilt (%d) - no self-join, name+carrier_code display, "
                   "diamond_id last, Product-priority + indirect/partner examples"
                   % len(GOLDEN_QUERIES))

    # --- 7. Global SQL-generation instructions (the heart) -------------------
    sgc = raw.get("sqlGenerationConfig")
    if not isinstance(sgc, dict):
        sgc = {}
        raw["sqlGenerationConfig"] = sgc
    sgc["instructions"] = NEW_INSTRUCTIONS
    changes.append("sqlGenerationConfig.instructions: full rewrite (one-table no-join, "
                   "ACTUALS default, hierarchy priority + transparency, customer display, "
                   "Parent_Group restraint, indirect/Account_partner, YTD)")

    return changes


# ----------------------------------------------------------------------------
# STEP 1 - read the source model (READ ONLY) and build the corrected config
# ----------------------------------------------------------------------------
client = dataiku.api_client()
try:
    project = client.get_default_project()
except Exception:
    project = client.get_project("OWISMIND_DEV")

old_sm = project.get_semantic_model(OLD_SEMANTIC_MODEL_ID)
old_active_id = old_sm.get_active_version_id()
old_settings = old_sm.get_version(old_active_id).get_settings()
source_raw = copy.deepcopy(old_settings.get_raw())   # never written back
print("Source model %s, active version %s - %d entities, %d golden queries, %d glossary terms"
      % (OLD_SEMANTIC_MODEL_ID, old_active_id,
         len(source_raw.get("entities") or []),
         len(source_raw.get("goldenQueries") or []),
         len(source_raw.get("glossaryTerms") or [])))

corrected = copy.deepcopy(source_raw)
change_notes = apply_corrections(corrected)
print("\n=== Corrections applied to the copy (old model untouched) ===")
for i, c in enumerate(change_notes, 1):
    print("  %2d. %s" % (i, c))

print("\n=== New global instructions preview (first 600 chars) ===")
print(corrected["sqlGenerationConfig"]["instructions"][:600], "...")


# ----------------------------------------------------------------------------
# STEP 2 - create the NEW model and push the corrected config into version v1
# (Run this only after reviewing the diff above.)
# ----------------------------------------------------------------------------
new_sm = project.create_semantic_model(NEW_SEMANTIC_MODEL_NAME)
print("\nCreated new semantic model id =", new_sm.id, "name =", NEW_SEMANTIC_MODEL_NAME)

# A fresh model may or may not auto-create a version - handle both, documented.
existing_versions = new_sm.list_versions_ids()
if existing_versions:
    version_id = existing_versions[0]
    settings = new_sm.get_version(version_id).get_settings()
else:
    version_id = NEW_VERSION_ID
    settings = new_sm.new_version(version_id)      # blank settings template

new_raw = settings.get_raw()
# Inject the corrected content keys; keep the new version's own 'id'.
for key in ("entities", "relationships", "goldenQueries", "glossaryTerms",
            "glossaryBindings", "indexingSettings", "sqlGenerationConfig",
            "privateEditorData"):
    if key in corrected:
        new_raw[key] = copy.deepcopy(corrected[key])
new_raw["description"] = ("Aligned with the OWIsMind sub-agent: one-table no-join, "
                          "ACTUALS default, Product>Solution>SolutionLine>sirano_product "
                          "priority + transparency, Account_name+carrier_code display "
                          "(diamond_id discreet), Parent_Group restraint, "
                          "indirect/Account_partner semantics.")
settings.save()
new_sm.set_active_version_id(version_id)
print("Saved + activated version %s of new model %s" % (version_id, new_sm.id))
print(">>> WRITE DOWN THE NEW MODEL ID:", new_sm.id)


# ----------------------------------------------------------------------------
# STEP 3 - index the distinct values of the new model (needed for the model's
# own value resolution). One bounded scan over the source table; safe on
# PostgreSQL. Run as a separate, deliberate step.
# ----------------------------------------------------------------------------
future = new_sm.get_version(version_id).start_update_distinct_values()
result = future.wait_for_result()
print("Indexing finished:", result)

print("\nDONE. Next: test in the new model's Playground, then point the Semantic Model Query "
      "tool (currently '%s' on the OLD model) to model id %s."
      % ("v4oqA6R", new_sm.id))
