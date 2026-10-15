# Webapp_Zone - runtime datasets written by the plugin

> A Flow zone of the production project **OWISMIND_PRD_V1_2** that holds the two
> datasets the OWIsMind plugin webapp writes **at runtime**. Unlike the
> `SalesDrive_Revenue_Expert` and `CSC_ticket_AI_Agent` zones, **no recipe builds
> these**: they are written directly by the Flask backend in direct SQL and appear
> in the Flow only for visibility / lineage.

## The two datasets

| Dataset (DSS name) | Family | Written by | Content |
|---|---|---|---|
| `OWISMIND_PRD_V1_2_beta_owismind_webapp_events_v1` | `webapp_events_v1` | Flask backend (`POST /track` -> direct SQL) | usage-analytics events emitted by the Vue webapp (page views, mode switches, interactions) |
| `beta-owismind_webapp_traces_v2` | `webapp_traces_v2` | Flask backend (direct SQL) | agent traces (conversation / run / event records of each chat turn) |

## How they are populated

- The backend talks to PostgreSQL through **direct SQL** (`SQLExecutor2`), with a
  `PROJECT_KEY` table prefix, parameterized statements, and a `COMMIT` after each
  write. There is **no Flow recipe** and **no build**: the rows appear as the
  webapp is used.
- Both datasets live on the SQL connection (same PostgreSQL as the agent data).
  They are surfaced in this Flow zone so the tables are discoverable next to the
  agents that produce the traffic, not because the Flow computes them.
- Treat them as **append-only runtime logs**. Do not wire a recipe onto them and
  do not rebuild them from the Flow: rebuilding would drop live analytics/traces.

The write path (schema, table names, the `/track` route) is owned by the plugin
backend (`python-lib/owismind/`, repo root), not by this agent mirror.
