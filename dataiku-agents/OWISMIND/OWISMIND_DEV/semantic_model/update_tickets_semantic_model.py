# =============================================================================
# update_tickets_semantic_model.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK (project OWISMIND_DEV) to make the TICKETS
# semantic model a true expert of the TroubleTickets_year dataset. It refreshes,
# IN PLACE on the model's active version:
#   - the SQL-generation INSTRUCTIONS (the brain - the single most important
#     field: what the data is and how to query it correctly),
#   - the GOLDEN QUERIES (few-shot examples that teach the hard rules),
#   - the ENTITY description and every ATTRIBUTE (column) description,
#   - the METRICS (ticket count as COUNT(DISTINCT id), resolution time, ...).
# It does NOT create a model and it does NOT change which attributes are indexed,
# so NO re-indexing is needed (the distinct-values index is untouched).
#
# Recommended flow (see README.md, "Add a tickets model"):
#   1. In DSS, create a semantic model on the TroubleTickets_year dataset (the UI
#      auto-discovers entities/attributes from the schema, with valid shapes).
#      Name it "TroubleTickets_Semantic_Model".
#   2. Run THIS script (set NEW_MODEL_ID) to inject the tickets brain below.
#   3. Create a Semantic Model Query tool bound to that model (Agent mode OFF,
#      Sonnet, access datasets as the calling user); put its id in the tickets
#      Code Agent (SEMANTIC_TOOL_ID) and in registry.json.
#   4. Index distinct values once from the model UI (done at creation; re-index
#      only if you later add named filters / change which attributes are indexed).
#
# Documented API only (no class created directly):
#   project.get_semantic_model(id) -> get_active_version_id() -> get_version()
#   -> get_settings() -> get_raw() / save()
# =============================================================================

import dataiku

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
NEW_MODEL_ID = "dM4jA4G"                        # <-- REQUIRED: id of YOUR tickets model
TICKETS_DATASET = "TroubleTickets_year"   # used to resolve the physical table
# Physical table literal used inside the golden-query SQL. Leave empty to derive
# it from the dataset at runtime (recommended - avoids guessing the resolved name).
PHYSICAL_TABLE = ""


# ----------------------------------------------------------------------------
# SQL-GENERATION INSTRUCTIONS (the brain) - tickets specific, NOT revenue.
# This is the single most important field. It encodes, for the SQL writer itself,
# what the data is and how to query it: one table, no scenario, the duplicate-row
# trap (count DISTINCT ids, read the latest snapshot), the LD as the dominant
# lookup key, exact values instead of ILIKE, customer identity, date choice, and
# the transparency / honesty rules.
# ----------------------------------------------------------------------------
TICKETS_INSTRUCTIONS = """\
## Physical model - ONE table, NEVER join

The trouble_ticket entity maps to a SINGLE physical table (the incident-tickets
base). Select every needed column directly from it. NEVER emit a JOIN, and in
particular NEVER self-join the table - there is nothing to join.

## What this data is - incident / trouble tickets

One row is a SNAPSHOT of one incident ticket. There is NO scenario column (no
actual/budget/forecast): every row is a real ticket. The data covers the current
year and the three preceding years and is refreshed on the 1st of every month.
Never state a row count or invent a total volume.

## CRITICAL - duplicate rows: count DISTINCT ids, read the LATEST snapshot

The table keeps HISTORICAL SNAPSHOTS of each ticket: the SAME "id" appears on
SEVERAL rows because every update adds a NEW row and the old rows are kept (often
only "lastUpdate" changes, sometimes also "CurrentStatus", "Latest_Closed_Date",
"Duration_ticket_total" or "CurrentStatus_Reason"). You MUST always apply two
rules:

1. VOLUME = COUNT(DISTINCT "id"). NEVER COUNT(*): it over-counts updated tickets.
   "How many tickets", "number of incidents", and every ranking / breakdown by
   volume use COUNT(DISTINCT "id").

2. CURRENT STATE of a ticket (its status, closing date, duration, reason, and any
   "what is the status / is it closed" question) must come from its LATEST
   snapshot only = the row with the greatest "lastUpdate" for that "id".
   Deduplicate first, then aggregate:

       WITH latest AS (
         SELECT DISTINCT ON ("id") *
         FROM <the table>
         ORDER BY "id", "lastUpdate" DESC NULLS LAST
       )
       SELECT ... FROM latest ...

   COUNT(*) over the deduplicated "latest" set equals COUNT(DISTINCT "id"). Apply
   this dedup for status breakdowns, open/closed splits, duration aggregates and
   single-ticket / single-LD lookups.

"creationDate" is constant across a ticket's snapshots, so a pure "created in year
Y" count needs only COUNT(DISTINCT "id") WHERE EXTRACT(YEAR FROM "creationDate") =
Y - no dedup CTE required.

## The LD ("Service_id_1") - the dominant lookup key (VERY IMPORTANT)

"Service_id_1" is the primary product identifier, universally called the LD. It is
the field ticketing revolves around and the most frequently queried one. Map "LD"
followed by a code (e.g. "LD016835") to "Service_id_1". Frequent shapes:
- "status of LD016835" / "is LD016835 closed?": filter "Service_id_1" = 'LD016835',
  take the LATEST snapshot, and return the ticket "id", "Account_name",
  "CurrentStatus", "creationDate", "Latest_Closed_Date" and "Product" (lead with
  these). If the LD carries several tickets, return the latest snapshot of EACH,
  most recent first.
- "who is the account of LD016835": filter "Service_id_1" = 'LD016835', return
  "Account_name" (+ ticket "id"), latest snapshot.
- "the LDs of <customer>": resolve the customer (see identity below), then
  SELECT DISTINCT "Service_id_1" (with "Product"), excluding empty LDs.
When the question is about an LD, always LEAD the output with the LD.

## Exact values, NEVER ILIKE on names / LDs / products / accounts (CRITICAL)

Entity values reach you already grounded to the EXACT catalog spelling by a
grounding helper (see HELPER FINDINGS) - resolving real values is the whole point
of this stack. Filter on those exact values with "=" (or IN for several), e.g.
"Account_name" = 'ALGERIE TELECOM SPA', "Service_id_1" = 'LD016835'. Do NOT write
ILIKE '%...%' on an account name, LD, product or any named entity: it is imprecise
and silently matches the wrong rows. Only fall back to a pattern when NO exact
value is available and you truly must approximate - and then say so and state the
exact pattern you used.

## Customer / account identity - GROUP BY Customer_id, DISPLAY Account_name

"Customer_id" is the stable, precise customer key; "Account_name" is the human
label and its spelling can vary for the same customer. When grouping or ranking by
customer:
-> GROUP BY "Customer_id" ONLY (never by "Account_name", which would split one
   customer into several rows).
-> For DISPLAY, return MAX("Account_name") AS "Account_name"; LEAD with
   Account_name and keep "Customer_id" as the LAST, de-emphasized column.
When the user names a customer, prefer the exact resolved value and aggregate on
"Customer_id". "CustomerRepresentative_Name" is the CUSTOMER's representative (an
employee of the customer), not an OWI agent - group by it only when the user
explicitly asks about representatives.

## What to put forward in the output

Lead with the business-meaningful fields: the ticket "id", "Account_name", the
relevant dates ("creationDate", "Latest_Closed_Date"), the LD ("Service_id_1") and
"Product". Keep "Customer_id" present but as the LAST, de-emphasized column (a
technical key). Always return a clean tabular result with explicit column aliases.

## Dates - pick the one the question implies

- "creationDate": when the ticket was opened. DEFAULT time axis for "tickets in
  2025", trends over time, "created this year".
- "Latest_Closed_Date": when the ticket was closed; use it for closed-ticket
  timing and resolution-over-time questions.
- "detectionDate": when the incident was detected - only when the user explicitly
  asks about detection.
- "lastUpdate": last modification; it is used to pick the latest snapshot. Query
  by it only when the user explicitly asks about the last update.
For a year window, filter EXTRACT(YEAR FROM "creationDate") = <year> (or the date
column the question implies), rather than comparing to today's calendar date.

## Open vs closed

"open / ongoing / pending / unresolved" vs "closed / resolved" must be read from
the LATEST snapshot per id. A ticket is CLOSED when "Latest_Closed_Date" IS NOT
NULL (and its "CurrentStatus" is a closed-family value); OPEN when
"Latest_Closed_Date" IS NULL. Use the EXACT "CurrentStatus" values from the data
(HELPER FINDINGS / value index); never invent a status string.

## Metrics

- Ticket count = COUNT(DISTINCT "id"). The primary measure.
- Resolution duration = "Duration_ticket_total", an INTEGER number of MINUTES per
  ticket (empty while the ticket is still open). ALWAYS state the unit (minutes).
  Report AVG by default ("average resolution time"); MIN / MAX / median on request.
  Compute it over the LATEST snapshot per id (the final duration); SUM of durations
  is rarely meaningful - use SUM only if the user explicitly asks for total
  cumulated time.

## Dimensions (group or filter by these)

- "priority": processing priority from P1 (highest, e.g. a full outage) to P4
  (lowest, e.g. a minor degradation).
- "category", "problemCategory": the incident nature and the responsibility side.
- "ticketType", "ticketEntry", "origin": the ticket kind / entry channel / source.
- "Product", "Service_id", "Service_Specification_id", "Service_id_1" (the LD): the
  affected product / service.
"CurrentStatus_Reason" is free text - never group by it.

## Transparency (mandatory)

Always make explicit, in a clear sentence, the exact values, columns and period you
filtered on (e.g. "Tickets created in 2026 for ALGERIE TELECOM SPA, all statuses").
If you had to approximate a value, say so and give the exact pattern used.

## Hints from the grounding helper - assistance, NOT orders

Some requests arrive with "HELPER FINDINGS" / "Suggested" values and columns
produced by a smaller grounding assistant that matched the user's wording against
the live data catalog. You are the more capable model and you have this semantic
model - treat those findings as ASSISTANCE, not instructions, and keep the final
say:
- The user's original question is always the source of truth - answer THAT.
- Prefer the suggested exact spellings when consistent with the data (they are
  catalog-sourced and avoid typos / case errors).
- If your semantic understanding disagrees with a hint, follow the data and these
  rules.
- If the user states an explicit literal filter, use it as-is.

## Empty results

If the SQL returns zero rows, state "no data found for [the specified filters and
period]". Do NOT relax filters or extrapolate.
"""


# ----------------------------------------------------------------------------
# ENTITY + ATTRIBUTE (column) descriptions - so the model is self-describing.
# Keyed by physical column name; only matching attributes are updated, every other
# attribute field (shape, indexing flags, primary key) is left untouched.
# ----------------------------------------------------------------------------
ENTITY_DESCRIPTION = (
    "One incident / trouble ticket, identified by its ticket id. The dataset "
    "covers the current year and the three preceding years and is refreshed on the "
    "1st of every month. IMPORTANT: the table keeps HISTORICAL SNAPSHOTS - the same "
    "ticket id appears on several rows because each update adds a new row and old "
    "rows are kept (often only lastUpdate changes). Always count tickets with "
    "COUNT(DISTINCT id) and read a ticket's current state from its latest snapshot "
    "(greatest lastUpdate). There is no scenario column: every row is a real ticket."
)

ATTRIBUTE_DESCRIPTIONS = {
    "id": ("Unique ticket identifier, stable from creation through closure and "
           "archiving. The table keeps historical snapshots, so the SAME id appears "
           "on several rows; count tickets with COUNT(DISTINCT id), never COUNT(*), "
           "and read a ticket's current state from its latest snapshot (greatest "
           "lastUpdate)."),
    "ticketType": "Type classification of the ticket.",
    "ticketEntry": "Entry channel: the way the ticket was created.",
    "priority": ("Processing priority, from P1 (highest, fastest handling, e.g. a "
                 "full outage) to P4 (lowest, e.g. a minor degradation)."),
    "origin": ("Where the ticket comes from, i.e. who reported the incident (the "
               "customer, or detected internally by us, etc.)."),
    "category": ("Nature of the incident, i.e. its motive (service interrupted, "
                 "service degraded, etc.)."),
    "creationDate": ("Date the ticket was created (opened). DEFAULT time axis for "
                     "'tickets in <year>', trends and 'created this year'."),
    "detectionDate": ("Date the underlying incident or disturbance was detected. Use "
                      "it only when the user explicitly asks about detection."),
    "lastUpdate": ("Date of the last update to the ticket (a follow-up, a status "
                   "change, etc.). Used to pick the latest snapshot per ticket id; "
                   "query by it only when the user explicitly asks about the last "
                   "update."),
    "CurrentStatus": ("The ticket's current (last known) lifecycle state: in "
                      "progress, closed, etc. Read it from the latest snapshot per "
                      "id."),
    "CurrentStatus_Reason": ("Short free-text label explaining the status, usually "
                             "the reason recorded when the ticket is closed or "
                             "archived (sometimes updated while still open); empty "
                             "for ongoing or frozen tickets. Free text - do not group "
                             "by it."),
    "Latest_Closed_Date": ("Date the ticket was closed, if it has been closed. Use it "
                           "for closed-ticket timing and resolution-over-time "
                           "questions; a ticket is closed when it is not null."),
    "Duration_ticket_total": ("Total ticket duration IN MINUTES, between the opening "
                              "date and the closing date. Empty while the ticket is "
                              "still open. Report it from the latest snapshot per id "
                              "(AVG by default, in minutes); SUM of durations is "
                              "rarely meaningful."),
    "CustomerRepresentative_Name": ("Name of the customer's representative: an "
                                    "employee of the customer who opened the ticket or "
                                    "was designated to follow it. Not an OWI agent."),
    "Customer_id": ("Stable, precise unique identifier of the customer / account in "
                    "the ticketing database. GROUP BY this id when aggregating by "
                    "customer, but keep it de-emphasized in the output (a technical "
                    "key)."),
    "Account_name": ("Name of the customer account concerned by the incident / "
                     "ticket. The human label to DISPLAY; its spelling can vary, so "
                     "group on Customer_id and display MAX(Account_name)."),
    "Service_id": "Identifier of the product / service concerned by the incident.",
    "Service_Specification_id": ("Identifier of the product specification (the product "
                                 "type) concerned by the incident."),
    "Product": "Exact name of the product concerned by the incident.",
    "Service_id_1": ("Primary product identifier, commonly called the LD - the key "
                     "identifier of the affected product/line in ticketing. VERY "
                     "IMPORTANT and very frequently queried: users ask for the status "
                     "of an LD, whether an LD is closed, the account of an LD, or the "
                     "LDs of a customer. 'LD' followed by a code maps to this column."),
    "problemCategory": ("Responsibility for the problem: which side is responsible "
                        "(sometimes OWI, sometimes the customer, etc.)."),
}


# ----------------------------------------------------------------------------
# METRICS - ticket count is COUNT(DISTINCT id) (dedup of historical snapshots).
# pseudoSQLExpression uses plain identifiers, matching the DSS metric editor.
# ----------------------------------------------------------------------------
METRICS = [
    {"name": "Ticket count",
     "description": "Number of distinct tickets (COUNT DISTINCT id, dedup of historical snapshots).",
     "pseudoSQLExpression": "COUNT(DISTINCT id)"},
    {"name": "Average resolution time (minutes)",
     "description": "Average ticket resolution time in minutes, over the latest snapshot per ticket.",
     "pseudoSQLExpression": "AVG(Duration_ticket_total)"},
    {"name": "Max resolution time (minutes)",
     "description": "Longest ticket resolution time in minutes.",
     "pseudoSQLExpression": "MAX(Duration_ticket_total)"},
    {"name": "Distinct customers with tickets",
     "description": "Number of distinct customers that raised at least one ticket.",
     "pseudoSQLExpression": "COUNT(DISTINCT Customer_id)"},
    {"name": "Distinct LDs with tickets",
     "description": "Number of distinct LDs (Service_id_1) with at least one ticket.",
     "pseudoSQLExpression": "COUNT(DISTINCT Service_id_1)"},
]


# ----------------------------------------------------------------------------
# GOLDEN QUERIES (tickets) - each teaches one rule: COUNT(DISTINCT id) for volume,
# the DISTINCT ON latest-snapshot dedup for current state, LD lookups, exact-value
# equality (never ILIKE), GROUP BY Customer_id with MAX(Account_name) display.
# The example literals (years, an LD, an account name) are illustrative few-shots.
# ----------------------------------------------------------------------------
def _gq(name, question, sql):
    return {"name": name, "question": question, "generatedSql": sql}


def build_golden_queries(table):
    t = {"t": table}
    return [
        _gq("Tickets created in a year (DISTINCT id)",
            "How many tickets were created in 2025?",
            'SELECT COUNT(DISTINCT "id") AS ticket_count\n'
            'FROM %(t)s\n'
            'WHERE EXTRACT(YEAR FROM "creationDate") = 2025;' % t),

        _gq("Ticket count by priority (DISTINCT id)",
            "How many tickets per priority?",
            'SELECT "priority", COUNT(DISTINCT "id") AS ticket_count\n'
            'FROM %(t)s\n'
            'GROUP BY "priority"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Status of an LD (latest snapshot)",
            "What is the status of LD016835?",
            'SELECT DISTINCT ON ("id")\n'
            '       "id", "Account_name", "CurrentStatus", "priority",\n'
            '       "creationDate", "Latest_Closed_Date", "Product", "Service_id_1"\n'
            'FROM %(t)s\n'
            'WHERE "Service_id_1" = \'LD016835\'\n'
            'ORDER BY "id", "lastUpdate" DESC NULLS LAST;' % t),

        _gq("LDs of a customer (exact name, DISTINCT)",
            "What are the LDs of ALGERIE TELECOM SPA?",
            'SELECT DISTINCT "Service_id_1", "Product"\n'
            'FROM %(t)s\n'
            'WHERE "Account_name" = \'ALGERIE TELECOM SPA\'\n'
            '  AND "Service_id_1" IS NOT NULL\n'
            'ORDER BY "Service_id_1";' % t),

        _gq("Tickets for a named customer (exact value, not ILIKE)",
            "How many tickets did ALGERIE TELECOM SPA open in 2026?",
            'SELECT MAX("Account_name")  AS "Account_name",\n'
            '       COUNT(DISTINCT "id") AS ticket_count,\n'
            '       "Customer_id"\n'
            'FROM %(t)s\n'
            'WHERE "Account_name" = \'ALGERIE TELECOM SPA\'\n'
            '  AND EXTRACT(YEAR FROM "creationDate") = 2026\n'
            'GROUP BY "Customer_id";' % t),

        _gq("Top customers by ticket volume (Year)",
            "Top 20 customers by number of tickets in 2025",
            'SELECT MAX("Account_name")  AS "Account_name",\n'
            '       COUNT(DISTINCT "id") AS ticket_count,\n'
            '       "Customer_id"\n'
            'FROM %(t)s\n'
            'WHERE EXTRACT(YEAR FROM "creationDate") = 2025\n'
            'GROUP BY "Customer_id"\n'
            'ORDER BY ticket_count DESC\n'
            'LIMIT 20;' % t),

        _gq("Ticket count by current status (latest snapshot)",
            "How many tickets in each status?",
            'WITH latest AS (\n'
            '  SELECT DISTINCT ON ("id") *\n'
            '  FROM %(t)s\n'
            '  ORDER BY "id", "lastUpdate" DESC NULLS LAST\n'
            ')\n'
            'SELECT "CurrentStatus", COUNT(*) AS ticket_count\n'
            'FROM latest\n'
            'GROUP BY "CurrentStatus"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Open tickets count (latest snapshot)",
            "How many tickets are still open?",
            'WITH latest AS (\n'
            '  SELECT DISTINCT ON ("id") *\n'
            '  FROM %(t)s\n'
            '  ORDER BY "id", "lastUpdate" DESC NULLS LAST\n'
            ')\n'
            'SELECT COUNT(*) AS open_tickets\n'
            'FROM latest\n'
            'WHERE "Latest_Closed_Date" IS NULL;' % t),

        _gq("Average resolution time by category (minutes, latest snapshot)",
            "Average resolution time by category, in minutes",
            'WITH latest AS (\n'
            '  SELECT DISTINCT ON ("id") *\n'
            '  FROM %(t)s\n'
            '  ORDER BY "id", "lastUpdate" DESC NULLS LAST\n'
            ')\n'
            'SELECT "category",\n'
            '       AVG("Duration_ticket_total") AS avg_duration_minutes,\n'
            '       COUNT(*)                      AS ticket_count\n'
            'FROM latest\n'
            'WHERE "Duration_ticket_total" IS NOT NULL\n'
            'GROUP BY "category"\n'
            'ORDER BY avg_duration_minutes DESC;' % t),

        _gq("Monthly ticket trend (Year, DISTINCT id)",
            "Monthly number of tickets created in 2025",
            'SELECT date_trunc(\'month\', "creationDate") AS month,\n'
            '       COUNT(DISTINCT "id") AS ticket_count\n'
            'FROM %(t)s\n'
            'WHERE EXTRACT(YEAR FROM "creationDate") = 2025\n'
            'GROUP BY date_trunc(\'month\', "creationDate")\n'
            'ORDER BY month;' % t),
    ]


# ----------------------------------------------------------------------------
# Resolve the physical table from the dataset (robust, no name guessing).
# ----------------------------------------------------------------------------
def resolve_physical_table(dataset_name, fallback):
    if fallback:
        return fallback
    try:
        info = dataiku.Dataset(dataset_name).get_location_info().get("info", {})
        t = info.get("quotedResolvedTableName")
        if t:
            return t
        schema, table = info.get("schema"), info.get("table")
        if table:
            return ('"%s"."%s"' % (schema, table)) if schema else ('"%s"' % table)
    except Exception:
        pass
    raise RuntimeError(
        "Cannot resolve the physical table for %r; set PHYSICAL_TABLE explicitly."
        % dataset_name)


def apply_descriptions_and_metrics(raw):
    """Set the entity description, the per-attribute descriptions and the metrics,
    in place, without touching attribute shapes / indexing / primary keys. Returns
    (entities_touched, attributes_touched)."""
    entities_touched, attributes_touched = 0, 0
    for entity in raw.get("entities") or []:
        if ENTITY_DESCRIPTION:
            entity["description"] = ENTITY_DESCRIPTION
            entities_touched += 1
        for attr in entity.get("attributes") or []:
            col = attr.get("column") or attr.get("name")
            if col in ATTRIBUTE_DESCRIPTIONS:
                attr["description"] = ATTRIBUTE_DESCRIPTIONS[col]
                attributes_touched += 1
        entity["metrics"] = [dict(m, created={}) for m in METRICS]
    return entities_touched, attributes_touched


# ----------------------------------------------------------------------------
# UPDATE IN PLACE - refresh instructions + golden queries + descriptions + metrics
# ----------------------------------------------------------------------------
assert NEW_MODEL_ID, "Set NEW_MODEL_ID to the id of your tickets semantic model."

client = dataiku.api_client()
try:
    project = client.get_default_project()
except Exception:
    project = client.get_project("OWISMIND_DEV")

physical_table = resolve_physical_table(TICKETS_DATASET, PHYSICAL_TABLE)
golden_queries = build_golden_queries(physical_table)
print("Using physical table:", physical_table)

sm = project.get_semantic_model(NEW_MODEL_ID)
version_id = sm.get_active_version_id()
settings = sm.get_version(version_id).get_settings()
raw = settings.get_raw()

old_instr = (raw.get("sqlGenerationConfig") or {}).get("instructions") or ""
old_gq = raw.get("goldenQueries") or []

raw.setdefault("sqlGenerationConfig", {})["instructions"] = TICKETS_INSTRUCTIONS
raw["goldenQueries"] = [dict(g) for g in golden_queries]
entities_touched, attributes_touched = apply_descriptions_and_metrics(raw)
settings.save()

print("Updated tickets model %s (active version %s) in place:" % (NEW_MODEL_ID, version_id))
print("  instructions : %d -> %d chars" % (len(old_instr), len(TICKETS_INSTRUCTIONS)))
print("  goldenQueries: %d -> %d" % (len(old_gq), len(golden_queries)))
print("  entities described: %d, attributes described: %d" % (entities_touched, attributes_touched))
print("No re-indexing needed (instructions, golden queries, descriptions and "
      "metrics do not touch the distinct-values index).")
print("Next: test in the Playground, then point the tickets Semantic Model Query "
      "tool at this model and set SEMANTIC_TOOL_ID in the tickets Code Agent.")
