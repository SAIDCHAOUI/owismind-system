# ADR-0003 - Direct SQL, no Flow at runtime

> Audience: Developer. Last updated: 2026-06-18. Summary: why OWIsMind
> persists everything (conversations, usage, settings, artifacts) via direct SQL through `SQLExecutor2`
> (parameterized, explicit COMMIT, a fresh executor per call, read-only on reads), with
> versioned `_vN` tables and no generic SQL route, rather than through DSS Flow datasets/recipes
> at runtime.

## Status

Accepted and in production. Safety posture audited several times (adversarial greps came back empty).
This is a NON-NEGOTIABLE project rule (CLAUDE.md rule 3, Dataiku instance safety rule 2).

## Context and problem

OWIsMind is a Dataiku DSS plugin whose Flask backend must store, performantly and
SAFELY, the application state of a chat webapp: exchanges (one user turn plus response), the conversation
tree, settings (the agent whitelist), token/cost accounting, artifact specs. The
backend runs on a SHARED Dataiku instance. The user requirement is explicit: nothing
that could harm the instance, slow it down, or overload it (memory L015).

Two families of solution were available:

1. go through the DSS **Flow** (datasets and recipes) to read and write, like a classic
   analytical pipeline;
2. talk in **direct SQL** to a PostgreSQL database through the `SQLExecutor2` API, without touching
   the instance's dataset orchestration.

The Flow is heavy, slow, and its execution touches the scheduler and the orchestration of
the instance. For KB-sized transactional writes triggered on every chat request, this
model is unsuitable and risky. The runtime need is a bounded, predictable and auditable
transactional access, not a pipeline.

## Decision

At runtime, everything goes through **direct SQL via `SQLExecutor2`** (PostgreSQL, connection configured
by the admin, by default `SQL_owi`, schema `public`, project key resolved server-side, by default
`OWISMIND_DEV`), **with no Flow at all**. The only exception to "zero Flow at runtime" is the RAW
end-of-stream trace, written write-only to an admin-chosen dataset via the Dataset API
(see `storage/chat_traces.py`), precisely to keep that large JSON OUT of the text of the SQL
queries and out of the DSS logs.

The heart of the posture lives in `storage/sql_config.py`, the single module that centralizes the
configuration and the safety helpers. Every read/write to the database goes through it.

### The safety invariants (non-negotiable)

| Invariant | Mechanism in the code | Where |
|---|---|---|
| FRESH executor per call | `new_executor()` returns a brand-new `SQLExecutor2(connection=...)` every time (the executor carries transaction state, so it is never shared between Flask worker threads) | `sql_config.py` |
| Never an implicit connection | `new_executor()` RAISES if no connection is configured; we never open a connection the admin has not explicitly chosen | `sql_config.py` |
| PARAMETERIZED values | any user-supplied value goes through `sql_value(v)` = `toSQL(Constant(v), dialect=Dialects.POSTGRES)`; a nullable fragment through `nullable_value(v)`; a server-side boolean through `bool_literal(v)` | `sql_config.py` |
| Valid identifiers | table/column/schema names go through `pg_identifier(name)` (regex `_IDENTIFIER_RE`, double-quoting, rejected if > 63 bytes); never any user input here, never `sql_value` for an identifier | `sql_config.py` |
| Systematic `COMMIT` | every write puts its query or queries in `pre_queries=[...]` and ends with `post_queries=["COMMIT"]` | `chat_v5.py`, `usage.py`, `migrations.py`, `settings.py`, `artifacts.py`, `admin.py` |
| READ-ONLY reads (defense in depth) | transactions that REPLAY SQL (Evidence) or re-read artifacts set `SET LOCAL transaction_read_only TO on` + `SET LOCAL statement_timeout TO '30000'` | `evidence/service.py`, `storage/artifacts.py` |

The canonical write idiom combines the write and the re-read in ONE round-trip, relying
on PostgreSQL's read-your-own-writes before the COMMIT (memory L009):

```python
new_executor().query_to_df(
    "SELECT 1 AS user_saved",
    pre_queries=[insert_sql],
    post_queries=["COMMIT"],
)
```

The main query is an inert `SELECT 1`; the real work (INSERT/UPDATE/DDL) lives in
`pre_queries`, and the `COMMIT` closes the transaction in `post_queries`. See `save_user_message` and
`save_assistant_message` (`storage/chat_v5.py`) for the two-phase version (user message
first, then response plus generated SQL plus token/cost usage in a single atomic UPDATE).

### No destructive DDL

The runtime emits ONLY non-destructive operations: `CREATE TABLE IF NOT EXISTS`, `INSERT`,
`UPDATE ... WHERE key`, bounded `SELECT`. No `DROP`, `TRUNCATE`, `GRANT`, `REVOKE`, `VACUUM`.
On the DSS API side, the backend stays READ-only (never `set_*` / `save` / `set_variables`),
except for the write-only append to the traces dataset.

Two tracked, benign exceptions to be aware of:

- an additive `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` on `webapp_users_v1` (lifetime usage
  counters), deemed non-destructive and explicitly authorized by the user
  (`migrations.py`, `_ALTERS_BY_LOGICAL`, memory L049);
- an admin-scoped `DELETE` on `webapp_user_quota_v1` (`build_user_quota_clear`,
  `storage/sql_builders.py`) that returns a user to the global limit by deleting THEIR
  override row: this is a targeted, bounded administration action, not a runtime path
  triggerable by an end user.

### No generic SQL route

The frontend NEVER chooses the table, the connection, or the query. There is no route such as
`/execute-sql` or `/run-query`. The endpoint inventory (`api/routes.py`) confirms it: these
are routes with a fixed business intent (`/chat/start`, `/conversation`, `/evidence/meta`,
etc.). The SQL is built entirely server-side, from controlled constants and parameterized
values. See [ADR-0004](0004-whitelist-agents-serveur.md) for the counterpart on the agents side (the
front sends only an opaque logical key, the backend resolves the `agent_id`).

## Rationale

- Bounded direct SQL is PREDICTABLE and AUDITABLE: we know exactly which query leaves, and
  the whole surface is greppable. The Flow, by contrast, is a wider box that touches
  the instance's orchestration.
- The fresh executor per call avoids sharing transactional state between worker threads (a
  `SQLExecutor2` carries a cursor and a transaction).
- Read-your-own-writes in one transaction removes a round-trip and guarantees the write
  is visible before the COMMIT, without a separate read.
- The read-only transactions on the paths that replay SQL (Evidence) turn any
  future regression into a LOUD failure rather than a silent write: every query there is
  already a bare `SELECT`, the read-only being defense in depth (comment in
  `evidence/service.py`). See [04-backend - security and validation](../04-backend/06-security-and-validation.md).

## Consequences

Positive:

- no generic SQL route exposed, hence no query-forging surface on the front side;
- safety re-confirmed by adversarial audits (`DROP`/`TRUNCATE`/`set_*`/`save` greps came back empty,
  memory L015/L026); a 6-lens Evidence audit confirmed 0 injection / 0 IDOR / 0 XSS,
  the residual findings all being of the instance-safety/perf kind (memory L036);
- the systematic caps (rows, columns, JSON size, CTE depth, global budget)
  bound the worst case. Example: `MAX_PERSISTED_TEXT_CHARS = 262144` bounds the persisted text
  (the INSERT/UPDATE body is inlined in the SQL logged by DSS); the capture caps live
  on the Evidence side.

Negative:

- a strict naming convention is MANDATORY (see [ADR-0004](0004-whitelist-agents-serveur.md)
  for the agents key, and the section below for `_vN` versioning);
- no `ALTER` at runtime, so any schema change = a NEW `_vN` table (see
  below), which makes old conversations invisible at the switchover (assumed, L049);
- `SQLExecutor2` has no server-side bind (official Python API): `sql_value` always INLINES
  the value into the query text, which DSS logs. Hence the persisted-text cap and
  the routing of large payloads (traces) off the SQL path.

## Versioned `_vN` tables, never an ALTER

A direct corollary of the "no destructive DDL" decision. Any change to the row format
creates a NEW `_vN` table (via `CREATE TABLE IF NOT EXISTS`), never an in-place `ALTER` of
the existing one. The old table stays inert (never dropped by the backend): its conversations
simply stop surfacing.

The physical naming is centralized in `sql_config.py`:
`physical_table(logical) = f"{PROJECT_KEY}_{namespace}_{logical}"` with
`namespace = "owismind"` (or `"{prefix}-owismind"` if a valid admin prefix is configured), and
`full_table()` quotes `public."..."`. Example:
`webapp_chat_v5` becomes `public."OWISMIND_DEV_owismind_webapp_chat_v5"`.

The `chat` lineage illustrates the rule: `webapp_chat_v2` (added `generated_sql`) ->
`webapp_chat_v3` (feedback columns) -> `webapp_chat_v4` (`parent_exchange_id`) ->
`webapp_chat_v5` (usage columns `input_tokens`/`output_tokens`/`total_tokens`/`estimated_cost`).
Companion tables: `webapp_settings_v1`, `webapp_users_v1`, `webapp_usage_monthly_v1`,
`webapp_artifacts_v1`, `webapp_user_quota_v1`. Creation is idempotent and concurrency-safe:
`migrations._ensure_table` runs the DDL at most once per process (guarded by
`_ensured_tables` + a lock), with its secondary indexes (`CREATE INDEX IF NOT EXISTS`, additive,
non-ALTER) in the same transaction.

The full detail of the data model and the conversation tree
(`parent_exchange_id`) is in [04-backend - storage and data model](../04-backend/04-storage-and-data-model.md),
the canonical home of the SQL schema; we do not redraw it here.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Flow datasets / recipes at runtime | Heavy, slow, touches the shared instance's orchestration; unsuitable for KB-sized transactional writes per request. |
| ORM (SQLAlchemy or other) | Overkill and an increased dependency surface (and NO INSTALL) for an access already entirely controlled by homemade helpers. |
| `ALTER TABLE` to evolve the schema | Deemed destructive/risky on a shared instance; replaced by `_vN` versioning. The only tracked exception: an additive `ADD COLUMN IF NOT EXISTS` on `users` (L049). |
| Generic SQL route (`/execute-sql`) | Forbidden: it would open a forging surface where the front would choose table/connection/query (CLAUDE.md rule 3). |

## See also
- [04-backend - storage and data model](../04-backend/04-storage-and-data-model.md) - the full SQL schema, the `_vN` tables and the conversation tree (canonical home of the data model).
- [04-backend - security and validation](../04-backend/06-security-and-validation.md) - payload validation, SQL safety, read-only guards in detail.
- [02-architecture - security model](../02-architecture/04-security-model.md) - the general framework of trust boundaries (run-as-user, owner-scoping, whitelist).
- [ADR-0004 - Server-side agent whitelist](0004-whitelist-agents-serveur.md) - the agents counterpart: an opaque logical key, the `agent_id` never leaves the server.
- [ADR-0008 - Evidence trust layer and artifacts](0008-evidence-trust-layer-et-artifacts.md) - the read-only replay of the agent's SELECT, deterministic and bounded.
- [Decisions index (ADR)](README.md) - back to the index.
