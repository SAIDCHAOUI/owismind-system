# =============================================================================
# Drive_Revenues_Semantic_Model.py - THE single maintenance file for the REVENUE
# semantic model (one Python file per semantic model, user decision 2026-07-20).
# -----------------------------------------------------------------------------
# Run in a DSS notebook of the project that OWNS the model (the current clone).
# Pick ONE action in CONFIG below; every write action previews first (DRY_RUN).
#
#   ACTION = "dump"     READ-ONLY: export the LIVE model config to
#                       Drive_Revenues_Semantic_Model.v1.json, then commit that
#                       file to the repo (byte-faithful snapshot of the SQL brain).
#   ACTION = "update"   Push the canonical brain below IN PLACE on the active
#                       version: SQL-generation INSTRUCTIONS + GOLDEN QUERIES.
#                       No re-indexing needed (neither touches the value index).
#   ACTION = "repoint"  After a project clone: remap dataset refs + physical
#                       tables from SOURCE_PROJECT_KEY to THIS project's key,
#                       then re-index distinct values. The factory notebook
#                       02_align_clone.py does this for ALL models at once;
#                       this action is the per-model equivalent.
#
# This file replaces the old scripts/ folder (build_aligned / update_aligned /
# dump / repoint / add_solution / drop_column / migrate / remap) - git history
# keeps them. The canonical text below is the deterministic composition of the
# last update_aligned iteration with the add_solution hierarchy restore
# (Product > Solution > SolutionLine > sirano_product), VALIDATED in DSS on
# 2026-07-08.
#
# Documented API only: project.get_semantic_model(id) -> get_active_version_id()
# -> get_version() -> get_settings() -> get_raw()/save();
# get_version(id).start_update_distinct_values() for the repoint re-index.
# =============================================================================

import json

import dataiku

# CONFIG ----------------------------------------------------------------------
ACTION = "dump"                     # "dump" | "update" | "repoint"
DRY_RUN = True                      # update/repoint: True = preview only
MODEL_ID = ""                       # "" -> resolve by MODEL_NAME (clone-safe:
                                    # ids are usually preserved, names always)
MODEL_NAME = "Drive_Revenues_Semantic_Model"
REVENUE_DATASET = "DRIVE_Revenues"  # resolves the physical table for golden SQL
SNAPSHOT_PATH = "Drive_Revenues_Semantic_Model.v1.json"
# repoint only: the project key the cloned refs still (wrongly) point at.
SOURCE_PROJECT_KEY = "OWISMIND_PRD_V1_2"
REBUILD_DISTINCT_VALUES = True      # repoint only: re-index on the new table


# ------------------------------------------------------------------------------
# CANONICAL SQL-GENERATION INSTRUCTIONS (the brain). Pushed by ACTION="update".
# ------------------------------------------------------------------------------
INSTRUCTIONS = """\
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

These qualifiers select a booking_type WITHIN a scenario. "billed" / "accrual" do not name a
scenario by themselves: combine them with the scenario rule above (default Phase = 'ACTUALS'
unless the user names another scenario). "pipeline" and "to bill" already carry their
scenario (Phase = 'FORECAST').

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
sirano_product. Example: "IP" is a SolutionLine -> filter on SolutionLine. "IPL" and
"Roaming Sponsor" are Products -> filter on Product.

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

## Exact values, NEVER ILIKE on names / offers / codes (CRITICAL)

Entity values reach you already grounded to the EXACT catalog spelling by a grounding helper
(see HELPER FINDINGS) - resolving real values is the whole point of this stack (three datasets
plus a lookup tool exist precisely so you never have to guess a spelling). Filter on those
exact values with "=" (or IN for several), e.g. "Account_name" = 'HALYS', "Product" =
'IP Transit', "diamond_id" = '5373'. Do NOT write ILIKE '%...%' on an account name, product,
offer or any named entity: it is imprecise and silently matches the wrong rows (a typed partial
name must become the FULL exact catalog value via "=", never an ILIKE pattern on a fragment).
Prefer the stable id for aggregation: GROUP BY "diamond_id" and display MAX("Account_name").
Only fall back to a pattern when NO exact value is available and you truly must approximate -
and then say so and state the exact pattern you used. NEVER fabricate a name: if you were
given no grounded value for a named entity (no HELPER FINDING for it), do NOT invent or
complete one from your own knowledge - filter only on what is grounded, or return no data and
name the entity you could not resolve. A guessed name that returns zero rows is the worst
outcome.

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
- Comparing ACTUALS with BUDGET, FORECAST, Q3F or HLF on a YTD basis needs PERIOD ALIGNMENT:
  those phases carry rows for the FULL year up front, while ACTUALS stop at the latest
  reported month. Restrict EVERY compared phase to the months where ACTUALS exist in that
  year (year_month <= the MAX ACTUALS year_month of the year), so both sides cover the same
  window, and state the month window you used. A full-year BUDGET total against a
  partial-year ACTUALS total is NOT a YTD comparison.
"""


# ------------------------------------------------------------------------------
# CANONICAL GOLDEN QUERIES. __TABLE__ is replaced at runtime by this project's
# own resolved physical table, so the same file works in every clone unedited.
# ------------------------------------------------------------------------------
GOLDEN_QUERIES = [
    {
        "name": "Revenue by Customer (Year)",
        "question": "Revenue of diamond_id 5373 in 2025",
        "generatedSql": "SELECT SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"diamond_id\" = '5373'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025;"
    },
    {
        "name": "Revenue with a named customer (Year)",
        "question": "How much revenue did we make with HALYS last year (2025)?",
        "generatedSql": "SELECT MAX(r.\"Account_name\") AS \"Account_name\",\n       MAX(r.\"carrier_code\")  AS \"carrier_code\",\n       SUM(r.\"amount_eur\")    AS total_revenue,\n       r.\"diamond_id\"\nFROM __TABLE__ r\nWHERE r.\"Account_name\" = 'HALYS'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025\nGROUP BY r.\"diamond_id\";"
    },
    {
        "name": "Top Customers by Revenue (Product, Year)",
        "question": "Top 20 customers for IP Transit in 2025",
        "generatedSql": "SELECT MAX(r.\"Account_name\") AS \"Account_name\",\n       MAX(r.\"carrier_code\")  AS \"carrier_code\",\n       SUM(r.\"amount_eur\")    AS total_revenue,\n       r.\"diamond_id\"\nFROM __TABLE__ r\nWHERE r.\"Product\" = 'IP Transit'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025\nGROUP BY r.\"diamond_id\"\nORDER BY total_revenue DESC\nLIMIT 20;"
    },
    {
        "name": "Offer term ambiguous across levels - prefer Product",
        "question": "How much revenue on IP Transit in 2026? (IP Transit is both a Product and a Solution; prefer the Product level)",
        "generatedSql": "SELECT SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"Product\" = 'IP Transit'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2026;"
    },
    {
        "name": "Billed revenue (booking_type within the default scenario)",
        "question": "Billed revenue in 2025",
        "generatedSql": "SELECT SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"Phase\" = 'ACTUALS'\n  AND r.\"booking_type\" LIKE 'Bill%'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025;"
    },
    {
        "name": "Budget vs Actuals Comparison (Monthly, Product)",
        "question": "Compare budget vs actuals 2026 for Roaming Sponsor by month",
        "generatedSql": "SELECT r.\"year_month\",\n       r.\"Phase\",\n       SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"Product\" = 'Roaming Sponsor'\n  AND r.\"Phase\" IN ('BUDGET', 'ACTUALS')\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2026\nGROUP BY r.\"year_month\", r.\"Phase\"\nORDER BY r.\"year_month\", r.\"Phase\";"
    },
    {
        "name": "Revenue Actuals YTD (SolutionLine)",
        "question": "Revenue actuals YTD 2026 for the Roaming solution line",
        "generatedSql": "SELECT SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"Phase\" = 'ACTUALS'\n  AND r.\"SolutionLine\" = 'ROAMING'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2026;"
    },
    {
        "name": "Indirect Customers by Product (Year)",
        "question": "Indirect customers on EVPL in 2025",
        "generatedSql": "SELECT MAX(r.\"Account_name\") AS \"Account_name\",\n       MAX(r.\"carrier_code\")  AS \"carrier_code\",\n       SUM(r.\"amount_eur\")    AS total_revenue,\n       r.\"diamond_id\"\nFROM __TABLE__ r\nWHERE r.\"Product\" = 'EVPL'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND r.\"distribution_type\" = 'Indirect_distribution/Resseler'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025\nGROUP BY r.\"diamond_id\"\nORDER BY total_revenue DESC;"
    },
    {
        "name": "Total revenue from indirect customers (Year)",
        "question": "How much revenue did we generate with all indirect customers last year (2025)?",
        "generatedSql": "SELECT SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"distribution_type\" = 'Indirect_distribution/Resseler'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025;"
    },
    {
        "name": "Revenue by partner / reseller (indirect, Year)",
        "question": "Revenue per partner (reseller) for indirect sales in 2025",
        "generatedSql": "SELECT r.\"Account_partner\",\n       SUM(r.\"amount_eur\") AS total_revenue\nFROM __TABLE__ r\nWHERE r.\"distribution_type\" = 'Indirect_distribution/Resseler'\n  AND r.\"Phase\" = 'ACTUALS'\n  AND EXTRACT(YEAR FROM r.\"year_month\") = 2025\nGROUP BY r.\"Account_partner\"\nORDER BY total_revenue DESC;"
    }
]


# ------------------------------------------------------------------------------
# HELPERS (shared by all actions)
# ------------------------------------------------------------------------------
def resolve_model(project):
    """The model for MODEL_ID, else the one named MODEL_NAME. Raises if neither."""
    if MODEL_ID:
        return project.get_semantic_model(MODEL_ID)
    for h in project.list_semantic_models():
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        mid = h.get("id") if isinstance(h, dict) else getattr(h, "id", None)
        if name == MODEL_NAME and mid:
            return project.get_semantic_model(mid)
    raise RuntimeError(
        "Model not found: set MODEL_ID or check MODEL_NAME=%r" % MODEL_NAME)


def active_version_settings(model):
    """(version_id, settings) of the model's active version."""
    version_id = model.get_active_version_id()
    assert version_id, "The semantic model has no active version."
    return version_id, model.get_version(version_id).get_settings()


def resolve_physical_table(dataset_name):
    """The quoted physical table behind the dataset (no name guessing)."""
    info = dataiku.Dataset(dataset_name).get_location_info().get("info", {})
    t = info.get("quotedResolvedTableName")
    if t:
        return t
    schema, table = info.get("schema"), info.get("table")
    if table:
        return ('"%s"."%s"' % (schema, table)) if schema else ('"%s"' % table)
    raise RuntimeError("Cannot resolve the physical table for %r" % dataset_name)


def remap_strings(value, replacements):
    """Recursively rewrite every string through the replacement map. Pure."""
    if isinstance(value, dict):
        return {k: remap_strings(v, replacements) for k, v in value.items()}
    if isinstance(value, list):
        return [remap_strings(v, replacements) for v in value]
    if isinstance(value, str):
        for old, new in replacements.items():
            value = value.replace(old, new)
        return value
    return value


def strings_mentioning(config, needle):
    """Every string in the config that mentions the needle (for previews)."""
    hits = []

    def walk(v):
        if isinstance(v, dict):
            for c in v.values():
                walk(c)
        elif isinstance(v, list):
            for c in v:
                walk(c)
        elif isinstance(v, str) and needle in v:
            hits.append(v[:160])

    walk(config)
    return hits


# ------------------------------------------------------------------------------
# ACTIONS
# ------------------------------------------------------------------------------
def act_dump(project, model):
    """READ-ONLY export of the active version raw config to SNAPSHOT_PATH."""
    version_id, settings = active_version_settings(model)
    raw = settings.get_raw()
    with open(SNAPSHOT_PATH, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2, sort_keys=False)
    print("Wrote %s (version %s)." % (SNAPSHOT_PATH, version_id))
    print("Copy the file content into the repo at "
          "GenAI/semantic-models/Drive_Revenues_Semantic_Model/ and commit.")


def act_update(project, model):
    """Push INSTRUCTIONS + GOLDEN_QUERIES in place on the active version."""
    version_id, settings = active_version_settings(model)
    raw = settings.get_raw()
    table = resolve_physical_table(REVENUE_DATASET)
    golden = [dict(g, generatedSql=g["generatedSql"].replace("__TABLE__", table))
              for g in GOLDEN_QUERIES]
    old_instr = (raw.get("sqlGenerationConfig") or {}).get("instructions") or ""
    old_gq = raw.get("goldenQueries") or []
    print("Model %s | active version %s | table %s" % (model.id, version_id, table))
    print("  instructions : %d -> %d chars" % (len(old_instr), len(INSTRUCTIONS)))
    print("  goldenQueries: %d -> %d" % (len(old_gq), len(golden)))
    if DRY_RUN:
        print("DRY_RUN=True -> nothing saved. Review the counts, then set "
              "DRY_RUN=False and re-run.")
        return
    raw.setdefault("sqlGenerationConfig", {})["instructions"] = INSTRUCTIONS
    raw["goldenQueries"] = golden
    settings.save()
    print("Saved. No re-indexing needed (only instructions + golden queries "
          "changed). Re-test in the Playground, then in the webapp.")


def act_repoint(project, model):
    """Remap SOURCE_PROJECT_KEY refs to this project's key, in place."""
    target_key = project.project_key
    assert target_key != SOURCE_PROJECT_KEY, (
        "Target key == source key (%s): run this notebook in the CLONE project, "
        "not in the source project." % target_key)
    replacements = {
        SOURCE_PROJECT_KEY + ".": target_key + ".",   # entity datasetRef
        SOURCE_PROJECT_KEY + "_": target_key + "_",   # physical tables in SQL
    }
    version_id, settings = active_version_settings(model)
    raw = settings.get_raw()
    before = strings_mentioning(raw, SOURCE_PROJECT_KEY)
    fixed = remap_strings(raw, replacements)
    after = strings_mentioning(fixed, SOURCE_PROJECT_KEY)
    print("Model %s | active version %s" % (model.id, version_id))
    print("Remap: %s.* -> %s.*  and  %s_* -> %s_*"
          % (SOURCE_PROJECT_KEY, target_key, SOURCE_PROJECT_KEY, target_key))
    print("Refs to %s before / after: %d / %d %s"
          % (SOURCE_PROJECT_KEY, len(before), len(after),
             "(after should be 0)" if not after else "<-- CHECK"))
    for s in after[:20]:
        print("   !!", s)
    if DRY_RUN:
        print("DRY_RUN=True -> nothing saved. Review (AFTER = 0), then set "
              "DRY_RUN=False and re-run.")
        return
    raw.clear()
    raw.update(fixed)
    settings.save()
    print("Saved. Model repointed to the %s datasets/tables." % target_key)
    if REBUILD_DISTINCT_VALUES:
        print("Re-indexing distinct values on the new table...")
        print(model.get_version(version_id)
              .start_update_distinct_values().wait_for_result())


# ------------------------------------------------------------------------------
# DISPATCH
# ------------------------------------------------------------------------------
_project = dataiku.api_client().get_default_project()
_model = resolve_model(_project)
_actions = {"dump": act_dump, "update": act_update, "repoint": act_repoint}
assert ACTION in _actions, "ACTION must be one of %s" % sorted(_actions)
print("Project:", _project.project_key, "| ACTION:", ACTION)
_actions[ACTION](_project, _model)
