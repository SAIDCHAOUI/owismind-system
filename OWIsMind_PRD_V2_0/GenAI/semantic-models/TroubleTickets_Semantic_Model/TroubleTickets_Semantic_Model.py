# =============================================================================
# TroubleTickets_Semantic_Model.py - THE single maintenance file for the TICKETS
# semantic model (one Python file per semantic model, user decision 2026-07-20).
# -----------------------------------------------------------------------------
# Run in a DSS notebook of the project that OWNS the model (the current clone).
# Pick ONE action in CONFIG below; every write action previews first (DRY_RUN).
#
#   ACTION = "dump"     READ-ONLY: export the LIVE model config to
#                       TroubleTickets_Semantic_Model.v1.json, then commit that
#                       file to the repo (byte-faithful snapshot of the SQL brain).
#   ACTION = "update"   Push the canonical brain below IN PLACE on the active
#                       version: SQL-generation INSTRUCTIONS + GOLDEN QUERIES +
#                       entity/attribute DESCRIPTIONS + METRICS. No re-indexing
#                       needed (none of these touch the distinct-values index).
#   ACTION = "repoint"  After a project clone: remap dataset refs + physical
#                       tables from SOURCE_PROJECT_KEY to THIS project's key,
#                       then re-index distinct values. The factory notebook
#                       02_align_clone.py does this for ALL models at once;
#                       this action is the per-model equivalent.
#
# This file replaces the old scripts/ folder (update_tickets_semantic_model.py +
# repoint_tickets_prod_clone.py + dump_semantic_model.py) - git history keeps
# them. The canonical brain below is update_tickets_semantic_model.py's content,
# carried over verbatim.
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
MODEL_NAME = "TroubleTickets_Semantic_Model"
TICKETS_DATASET = "TroubleTickets_year"  # resolves the physical table
# Physical table literal used inside the golden-query SQL. Leave empty to derive
# it from the dataset at runtime (recommended - avoids guessing the resolved name).
PHYSICAL_TABLE = ""
SNAPSHOT_PATH = "TroubleTickets_Semantic_Model.v1.json"
# repoint only: the project key the cloned refs still (wrongly) point at.
SOURCE_PROJECT_KEY = "OWISMIND_PRD_V1_2"
REBUILD_DISTINCT_VALUES = True      # repoint only: re-index on the new table


# ------------------------------------------------------------------------------
# SQL-GENERATION INSTRUCTIONS (the brain) - tickets specific, NOT revenue.
# This is the single most important field. It encodes, for the SQL writer itself,
# what the data is and how to query it: one table, no scenario, the duplicate-row
# trap (count DISTINCT ids, read the latest snapshot), the LD as the dominant
# lookup key, exact values instead of ILIKE, customer identity, date choice, and
# the transparency / honesty rules. Pushed by ACTION="update".
# ------------------------------------------------------------------------------
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
   volume use COUNT(DISTINCT "id"). Write COUNT(DISTINCT "id") DIRECTLY on the
   table; do NOT build a latest-snapshot CTE just to count (the dedup CTE in rule 2
   is ONLY for reading a ticket's current state, not for counting).

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
followed by a code (e.g. "LD000123") to "Service_id_1". Frequent shapes:
- "status of LD000123" / "is LD000123 closed?": filter "Service_id_1" = 'LD000123',
  take the LATEST snapshot, and return the ticket "id", "Account_name",
  "CurrentStatus", "creationDate", "Latest_Closed_Date" and "Product" (lead with
  these). If the LD carries several tickets, return the latest snapshot of EACH,
  most recent first.
- "who is the account of LD000123": filter "Service_id_1" = 'LD000123', return
  "Account_name" (+ ticket "id"), latest snapshot.
- "the LDs of <customer>": resolve the customer (see identity below), then
  SELECT DISTINCT "Service_id_1" (with "Product"), excluding empty LDs.
When the question is about an LD, always LEAD the output with the LD.

## Exact values, NEVER ILIKE on names / LDs / products / accounts (CRITICAL)

Entity values reach you already grounded to the EXACT catalog spelling by a
grounding helper (see HELPER FINDINGS) - resolving real values is the whole point
of this stack. Filter on those exact values with "=" (or IN for several), e.g.
"Account_name" = '<exact account from the catalog>', "Service_id_1" = '<exact LD
code>'. Do NOT write
ILIKE '%...%' on an account name, LD, product or any named entity: it is imprecise
and silently matches the wrong rows. Only fall back to a pattern when NO exact
value is available and you truly must approximate - and then say so and state the
exact pattern you used.

NEVER FABRICATE A NAME. If you were given NO grounded value for a named entity (no
HELPER FINDING for it), do NOT invent or complete a name from your own knowledge
(do not expand a partial customer or product name into a fuller, made-up one).
Filter only on values you actually have; if the entity cannot be resolved, return no
data and NAME the entity you could not resolve, so the user can give the exact value.
A guessed name that returns zero rows is the worst outcome - refuse to guess.

## Related / group accounts - disclose, never merge

There is NO customer-group hierarchy in this data: a corporate group's separate
entities (for example a fixed-line arm and a mobile arm) are DISTINCT accounts with
different "Account_name" and "Customer_id" values. When the user names a customer,
state the EXACT account you matched. If several accounts plausibly match the wording
(e.g. several entities of the same group), report the one you used AND list the
other close matches so the user can pick - never silently merge group entities into
one figure.

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

## Dates - DEFAULT to creationDate (CRITICAL)

The DEFAULT time axis is "creationDate". ANY question with a time window but NO
explicit lifecycle verb - "tickets this year", "tickets cette annee", "tickets en
2025", "combien de tickets ... cette annee", "tickets de janvier", a trend, "X
tickets created / crees / ouverts" - filters on "creationDate". Do NOT use
"Latest_Closed_Date" for these: it silently drops every still-open ticket
(open tickets have a NULL closing date), which is exactly how a real count returns
zero.
- "creationDate": when the ticket was opened. The default for volumes, trends and
  any unqualified year window.
- "Latest_Closed_Date": when the ticket was closed. Use it ONLY when the question
  is explicitly about CLOSING / RESOLUTION ("tickets closed in 2025", "resolved
  last month", closure timing).
- "detectionDate": only when the user explicitly asks about detection.
- "lastUpdate": only when the user explicitly asks about the last update (it also
  picks the latest snapshot, rule 2 above).
For a year window, filter EXTRACT(YEAR FROM "creationDate") = <year> (or the date
column the question explicitly implies), rather than comparing to today's date.

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
filtered on (e.g. "Tickets created in <year> for <exact account>, all statuses").
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


# ------------------------------------------------------------------------------
# ENTITY + ATTRIBUTE (column) descriptions - so the model is self-describing.
# Keyed by physical column name; only matching attributes are updated, every other
# attribute field (shape, indexing flags, primary key) is left untouched.
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# METRICS - ticket count is COUNT(DISTINCT id) (dedup of historical snapshots).
# pseudoSQLExpression uses plain identifiers, matching the DSS metric editor.
# ------------------------------------------------------------------------------
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


# ------------------------------------------------------------------------------
# GOLDEN QUERIES (tickets) - each teaches one rule: COUNT(DISTINCT id) for volume,
# the DISTINCT ON latest-snapshot dedup for current state, LD lookups, exact-value
# equality (never ILIKE), GROUP BY Customer_id with MAX(Account_name) display.
# The example literals (years, an LD, an account name) are illustrative few-shots.
# ------------------------------------------------------------------------------
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

        _gq("Tickets for a customer this year (bare year -> creationDate, FR/EN)",
            "How many tickets this year for a given customer? / combien de tickets cette annee pour un client ?",
            'SELECT MAX("Account_name")  AS "Account_name",\n'
            '       COUNT(DISTINCT "id") AS ticket_count,\n'
            '       "Customer_id"\n'
            'FROM %(t)s\n'
            'WHERE "Account_name" = \'EXAMPLE CUSTOMER\'\n'
            '  AND EXTRACT(YEAR FROM "creationDate") = EXTRACT(YEAR FROM CURRENT_DATE)\n'
            'GROUP BY "Customer_id";' % t),

        _gq("Ticket count by priority (DISTINCT id)",
            "How many tickets per priority?",
            'SELECT "priority", COUNT(DISTINCT "id") AS ticket_count\n'
            'FROM %(t)s\n'
            'GROUP BY "priority"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Status of an LD (latest snapshot)",
            "What is the status of a given LD?",
            'SELECT DISTINCT ON ("id")\n'
            '       "id", "Account_name", "CurrentStatus", "priority",\n'
            '       "creationDate", "Latest_Closed_Date", "Product", "Service_id_1"\n'
            'FROM %(t)s\n'
            'WHERE "Service_id_1" = \'LD000123\'\n'
            'ORDER BY "id", "lastUpdate" DESC NULLS LAST;' % t),

        _gq("LDs of a customer (exact name, DISTINCT)",
            "What are the LDs of a given customer?",
            'SELECT DISTINCT "Service_id_1", "Product"\n'
            'FROM %(t)s\n'
            'WHERE "Account_name" = \'EXAMPLE CUSTOMER\'\n'
            '  AND "Service_id_1" IS NOT NULL\n'
            'ORDER BY "Service_id_1";' % t),

        _gq("Tickets for a named customer (exact value, not ILIKE)",
            "How many tickets did a given customer open in a given year?",
            'SELECT MAX("Account_name")  AS "Account_name",\n'
            '       COUNT(DISTINCT "id") AS ticket_count,\n'
            '       "Customer_id"\n'
            'FROM %(t)s\n'
            'WHERE "Account_name" = \'EXAMPLE CUSTOMER\'\n'
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


def resolve_physical_table(dataset_name, fallback):
    """The quoted physical table behind the dataset (no name guessing)."""
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
          "GenAI/semantic-models/TroubleTickets_Semantic_Model/ and commit.")


def act_update(project, model):
    """Push instructions + golden queries + descriptions + metrics in place."""
    version_id, settings = active_version_settings(model)
    raw = settings.get_raw()
    table = resolve_physical_table(TICKETS_DATASET, PHYSICAL_TABLE)
    golden = build_golden_queries(table)
    old_instr = (raw.get("sqlGenerationConfig") or {}).get("instructions") or ""
    old_gq = raw.get("goldenQueries") or []
    print("Model %s | active version %s | table %s" % (model.id, version_id, table))
    print("  instructions : %d -> %d chars" % (len(old_instr), len(TICKETS_INSTRUCTIONS)))
    print("  goldenQueries: %d -> %d" % (len(old_gq), len(golden)))
    if DRY_RUN:
        print("DRY_RUN=True -> nothing saved. Review the counts, then set "
              "DRY_RUN=False and re-run.")
        return
    raw.setdefault("sqlGenerationConfig", {})["instructions"] = TICKETS_INSTRUCTIONS
    raw["goldenQueries"] = [dict(g) for g in golden]
    entities_touched, attributes_touched = apply_descriptions_and_metrics(raw)
    settings.save()
    print("Saved. Entities described: %d, attributes described: %d."
          % (entities_touched, attributes_touched))
    print("No re-indexing needed (instructions, golden queries, descriptions and "
          "metrics do not touch the distinct-values index). Test in the "
          "Playground, then in the webapp.")


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
