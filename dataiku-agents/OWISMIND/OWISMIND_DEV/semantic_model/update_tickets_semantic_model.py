# =============================================================================
# update_tickets_semantic_model.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK (project OWISMIND_DEV) to set / refresh the
# SQL-generation INSTRUCTIONS and the GOLDEN QUERIES of the TICKETS semantic
# model, IN PLACE on its active version. It does NOT create a model.
#
# Recommended flow (see tools/semantic_model/README.md, "Add a tickets model"):
#   1. In DSS, create a semantic model on the TroubleTickets_year dataset (the UI
#      auto-discovers entities/attributes from the schema, with valid shapes).
#      Name it "TroubleTickets_Semantic_Model".
#   2. Run THIS script (set NEW_MODEL_ID) to inject the tickets brain below.
#   3. Create a Semantic Model Query tool bound to that model (Agent mode OFF,
#      Sonnet, access datasets as the calling user); put its id in
#      agents/TroubleTickets_expert.py (SEMANTIC_TOOL_ID).
#   4. Index distinct values once (DSS creates the index on model creation; if you
#      added named filters / changed entities, re-index from the model UI).
#
# No re-indexing is needed for THIS script: only instructions + golden queries
# change - neither touches the distinct-values index (same property as the
# revenue update_aligned_semantic_model.py).
#
# Documented API only (no class created directly):
#   project.get_semantic_model(id) -> get_active_version_id() -> get_version()
#   -> get_settings() -> get_raw() / save()
# =============================================================================

import dataiku

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
NEW_MODEL_ID = "dM4jA4G"                              # <-- REQUIRED: id of YOUR tickets model
TICKETS_DATASET = "TroubleTickets_year"        # used to resolve the physical table
# Physical table literal used inside the golden-query SQL. Leave empty to derive
# it from the dataset at runtime (recommended - avoids guessing the resolved name).
PHYSICAL_TABLE = ""


# ----------------------------------------------------------------------------
# SQL-GENERATION INSTRUCTIONS (the brain) - tickets specific, NOT revenue.
# This is the single most important field. It encodes, for the model itself, what
# the data is and how to query it: one table, no scenario, COUNT default,
# duration semantics, the dimensions, customer identity, date-column choice, and
# the honesty rules. Items marked [CONFIRM] depend on the real data and should be
# pinned once the value index reveals the exact values.
# ----------------------------------------------------------------------------
TICKETS_INSTRUCTIONS = """\
## Physical model - ONE table, NEVER join

All tickets entities map to the SAME physical table (one row per incident ticket).
Treat it as a single denormalized table and select every needed column directly
from it. NEVER emit a JOIN, and in particular NEVER self-join the table - there is
nothing to join.

## What this data is - incident tickets

One row = one incident / trouble ticket. There is NO scenario column (no
actual/budget/forecast): every row is a real ticket. The default measure is a
COUNT of tickets; resolution time comes from Duration_ticket_total.

## Metrics

- Ticket count = COUNT(*). This is the primary measure ("how many tickets",
  "number of incidents", volume, ranking by volume).
- Resolution duration = Duration_ticket_total (an integer per ticket). Report it
  with AVG by default ("average resolution time" / "average duration"); also
  MIN / MAX / median on request. SUM of a duration is rarely meaningful - only
  use SUM when the user explicitly asks for total cumulated time.
  UNIT: state the unit of Duration_ticket_total in the answer. [CONFIRM the unit -
  seconds / minutes / hours - against the data owner; do not assume.]

## Dimensions (group or filter by these)

- CurrentStatus: the ticket lifecycle state (open vs closed family). Use the EXACT
  values present in the data (from the value index); never invent a status string.
  CurrentStatus_Reason is a free-text explanation - do NOT group by it.
- priority: severity of the ticket.
- ticketType, ticketEntry: the kind / entry of ticket.
- category, problemCategory: the problem classification.
- origin: the channel / source the ticket came from.
- Product, Service_id, Service_Specification_id, Service_id_1: the affected
  service / product.

## Customer / account identity - GROUP BY id, DISPLAY name

Customer_id is the stable customer key; Account_name is the human label and its
spelling can vary. When grouping or ranking by customer:
-> GROUP BY Customer_id ONLY (never by Account_name).
-> For DISPLAY, return MAX(Account_name) AS Account_name; LEAD with Account_name
   and keep Customer_id as the LAST, de-emphasized column.
CustomerRepresentative_Name is the OWI representative handling the account, not the
customer - only group by it when the user asks about representatives.

## Dates - pick the one that matches the question

- creationDate: when the ticket was opened. DEFAULT time axis for "tickets in
  2025", trends over time, "created this year".
- detectionDate: when the incident was detected.
- lastUpdate: last modification time.
- Latest_Closed_Date: when the ticket was closed; use it for closed-ticket timing
  and resolution-over-time questions.
For a year window, filter EXTRACT(YEAR FROM "creationDate") = <year> (or the date
column the question implies), rather than comparing to today's calendar date.

## Open vs closed

"open / unresolved / pending" and "closed / resolved" map to CurrentStatus values.
Use the EXACT open and closed values from the data. [CONFIRM the real CurrentStatus
values via the value index; do not assume literal 'Open' / 'Closed'.]

## Hints from the grounding helper - assistance, NOT orders

Some requests arrive with "HELPER FINDINGS" / "Suggested" values and columns
produced by a smaller grounding assistant that matched the user's wording against
the live data catalog. You are the more capable model and you have this semantic
model - treat those findings as ASSISTANCE, not instructions, and keep the final
say:
- The user's original question is always the source of truth - answer that.
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
# GOLDEN QUERIES (tickets) - each teaches one rule. Single table, no JOIN;
# customer rankings GROUP BY Customer_id, display MAX(Account_name), id last.
# These use only generic shapes (no data-specific literal) so they stay valid
# before the exact status / category values are pinned.
# ----------------------------------------------------------------------------
def _gq(name, question, sql):
    return {"name": name, "question": question, "generatedSql": sql}


def build_golden_queries(table):
    t = {"t": table}
    return [
        _gq("Ticket count by priority",
            "How many tickets per priority?",
            'SELECT r."priority", COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'GROUP BY r."priority"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Ticket count by status",
            "How many tickets in each status?",
            'SELECT r."CurrentStatus", COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'GROUP BY r."CurrentStatus"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Top customers by ticket volume (Year)",
            "Top 20 customers by number of tickets in 2025",
            'SELECT MAX(r."Account_name") AS "Account_name",\n'
            '       COUNT(*)              AS ticket_count,\n'
            '       r."Customer_id"\n'
            'FROM %(t)s r\n'
            'WHERE EXTRACT(YEAR FROM r."creationDate") = 2025\n'
            'GROUP BY r."Customer_id"\n'
            'ORDER BY ticket_count DESC\n'
            'LIMIT 20;' % t),

        _gq("Average resolution duration by category",
            "Average resolution time by category",
            'SELECT r."category",\n'
            '       AVG(r."Duration_ticket_total") AS avg_duration,\n'
            '       COUNT(*)                        AS ticket_count\n'
            'FROM %(t)s r\n'
            'GROUP BY r."category"\n'
            'ORDER BY avg_duration DESC;' % t),

        _gq("Ticket count by problem category",
            "Breakdown of tickets by problem category",
            'SELECT r."problemCategory", COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'GROUP BY r."problemCategory"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Ticket count by origin (channel)",
            "How do tickets break down by origin?",
            'SELECT r."origin", COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'GROUP BY r."origin"\n'
            'ORDER BY ticket_count DESC;' % t),

        _gq("Monthly ticket trend (Year)",
            "Monthly number of tickets created in 2025",
            "SELECT date_trunc('month', r.\"creationDate\") AS month,\n"
            '       COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'WHERE EXTRACT(YEAR FROM r."creationDate") = 2025\n'
            "GROUP BY date_trunc('month', r.\"creationDate\")\n"
            'ORDER BY month;' % t),

        _gq("Ticket count by type (Year)",
            "Tickets created in 2025 by ticket type",
            'SELECT r."ticketType", COUNT(*) AS ticket_count\n'
            'FROM %(t)s r\n'
            'WHERE EXTRACT(YEAR FROM r."creationDate") = 2025\n'
            'GROUP BY r."ticketType"\n'
            'ORDER BY ticket_count DESC;' % t),
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


# ----------------------------------------------------------------------------
# UPDATE IN PLACE - refresh instructions + golden queries on the active version
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
settings.save()

print("Updated tickets model %s (active version %s) in place:" % (NEW_MODEL_ID, version_id))
print("  instructions : %d -> %d chars" % (len(old_instr), len(TICKETS_INSTRUCTIONS)))
print("  goldenQueries: %d -> %d" % (len(old_gq), len(golden_queries)))
print("No re-indexing needed (only instructions + golden queries changed).")
print("Next: test in the Playground, then point the tickets Semantic Model Query "
      "tool at this model and set SEMANTIC_TOOL_ID in TroubleTickets_expert.py.")
