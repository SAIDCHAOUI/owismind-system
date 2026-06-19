# ADR-0014 - Monthly rolling budget and per-user quota overrides

> Audience: Developer, administrator. Last updated: 2026-06-19. Summary: why OWIsMind enforces
> a rolling 50 USD/month credit per user via a two-layer resolution (global config in
> `webapp_settings_v1` + per-user overrides in the new `webapp_user_quota_v1` table), with
> server-side enforcement at `/chat/start` that returns HTTP 402 and fails open on storage
> errors.

## Status

Accepted. Coded in `storage/budget.py`, `security/validation.py` (budget validators),
`api/routes.py` (`/usage`, `/admin/budget`, `/admin/budget/users`), and `storage/migrations.py`
(`webapp_user_quota_v1` DDL). The monthly reset is self-managed by the calendar bucket in
`webapp_usage_monthly_v1` (no cron job). Not yet validated in DSS (backend restart required
after python-lib upload).

## Context and problem

OWIsMind calls LLM Mesh agents whose cost is metered per token by Dataiku. The `estimatedCost`
field on each `usage_summary` event already flows through the chat stream and is accumulated per
exchange in `webapp_chat_v5`. Two unsolved problems remained:

1. **No spending ceiling.** A single user could exhaust an organization's LLM Mesh quota
   (unlimited chat sessions, each potentially calling Sonnet in high mode).

2. **No per-user visibility.** Users had no way to see what they had spent or what their
   remaining credit was.

The desired behavior: each user gets a rolling monthly credit of 50 USD. The credit resets on
the 1st of each month without any scheduled job. Admins can raise or lower the global default
and override individual users permanently or temporarily. The enforcement must be server-side
and must not break the chat if the budget read itself fails.

## Decision

### 1. Two-layer limit resolution

Every user's effective monthly limit is resolved from two sources, in order of priority:

1. A **per-user override** stored in `webapp_user_quota_v1` (one row per user that received a
   custom limit). An override can be permanent (`expires_at IS NULL`) or temporary
   (`expires_at > now()`). Once the timestamp lapses the row is still there but ignored: the
   active test is `expires_at > now()` run in the SQL join.

2. The **global config** stored in `webapp_settings_v1` under the key `"monthly_budget"` (a
   JSON dict). The global config carries the default limit, an enforcement on/off switch, and an
   optional time-boxed global boost (a `temp_limit_usd` + `temp_expires_at` pair).

Resolution order (implemented in `_resolve_limit`, called per-user in `budget.py`):

```
active per-user override  >  active global temp boost  >  global default
```

The per-user active test runs in the database (SQL `LEFT JOIN ... AND now() < expires_at`); the
global temp boost active test runs in Python (comparing `datetime.now()` against the stored ISO
timestamp). Both clocks are "now" on their own side, and a sub-second skew is irrelevant at
month/day budget granularity.

The function `_resolve_limit` returns the resolved `limit_usd`, the `limit_source` string
(`"user_permanent"`, `"user_temp"`, `"global_temp"`, or `"default"`), and `limit_expires_at`
(None or an ISO string). These three fields are surfaced to the frontend so the profile Budget
card is fully transparent about WHY the cap is what it is.

### 2. The calendar-bucket table (no reset job)

The month's spend is accumulated in `webapp_usage_monthly_v1`:

```
PRIMARY KEY (user_id, period_start)
```

`period_start` is the first day of the calendar month (server clock), written by the UPSERT
via `date_trunc('month', now())::date`. A new month is simply a new row: there is no reset job,
no scheduled task, and no risk of a "missing reset" bug. The current month's bucket is the row
whose `period_start` equals today's truncated month. Future months have no row yet; absent rows
are treated as zero spend.

### 3. New table `webapp_user_quota_v1` (no ALTER)

The per-user override is NOT stored in `webapp_users_v1` (which already exists). A new
`_v1` table is created lazily on first write:

```sql
CREATE TABLE IF NOT EXISTS {full_table} (
    user_id     TEXT             PRIMARY KEY,
    limit_usd   DOUBLE PRECISION NOT NULL,
    expires_at  TIMESTAMP,
    note        TEXT,
    updated_at  TIMESTAMP        NOT NULL DEFAULT now(),
    updated_by  TEXT
)
```

The `webapp_users_v1` and `webapp_usage_monthly_v1` tables are untouched. The `_v1` suffix
follows the no-ALTER rule (ADR-0003): a new data shape gets a new table, not an `ALTER` of
an existing one.

### 4. Enforcement gate at `/chat/start`

Before any write (user-message persist or agent run), `/chat/start` calls `budget.has_budget`:

```python
within_budget, budget_status = budget.has_budget(identity["user_id"])
```

`has_budget` returns `(ok, status)` where `ok` is `False` only when enforcement is on AND
`spent_usd >= limit_usd`. When `ok` is False, `/chat/start` returns:

```
HTTP 402 Payment Required
{"status": "error", "error": "monthly_quota_exceeded", "budget": <status>}
```

The `budget` payload in the 402 carries the full resolved status (spent, limit, remaining,
source, reset date) so the frontend can render the exact "budget exhausted" banner without a
second API call.

**Fail-open contract.** If `has_budget` raises a storage error, `/chat/start` logs the
exception and sets `within_budget = True`, allowing the run through. The spend is still
recorded by the agent run, so the next request will be gated correctly once the read recovers.
The rationale: delivering an answer is more important than a perfectly-timed block when the
budget system itself is temporarily degraded.

### 5. In-process config cache

The global budget config (`webapp_settings_v1`, key `"monthly_budget"`) is read on EVERY
`/chat/start` call. To avoid two DB round-trips on the hot path (one for the budget gate, one
for the config it depends on), `budget.py` caches the config in-process with a 30-second TTL
(`_config_cache`). `set_budget_config` busts the cache immediately so an admin sees their
change reflected on the next request in the same process. The cache is lock-free on purpose:
a redundant read or a few-second-stale limit is harmless, and the TTL is short enough to bound
staleness when the backend runs multiple workers.

### 6. Admin endpoints

Two admin-only endpoints manage the budget (both gated by `_admin_guard()`):

- `GET /admin/budget` - returns the global config plus every registered user's current-month
  spend and resolved effective limit (bounded to `MAX_OVERVIEW_USERS = 1000`).
- `POST /admin/budget` - persists `{limit_usd, enabled}` and handles the temp boost
  independently: `clear_temp: true` removes it, `{temp_limit_usd, temp_days}` arms a new one,
  omitting both PRESERVES any active boost (so a default-limit edit never silently clears a
  running boost).
- `POST /admin/budget/users` - UPSERT or DELETE a per-user override:
  `{user_ids: [...], limit_usd, expires_days, note}` or `{user_ids: [...], clear: true}`.

All amount and duration fields pass through `validate_budget_amount` and `validate_expires_days`
in `security/validation.py` before reaching any SQL. Amounts are inlined as server-computed
numeric literals (`"{:.6f}".format(float(limit_usd))`); user ids are escaped via `sql_value`.

### 7. User-facing `/usage` endpoint

`GET /usage` (authenticated, owner-scoped, rate-limited by `evidence_throttle.usage_can_accept`)
returns the caller's current-month status: spend, tokens (input/output/total), request count,
effective limit and its source/expiry, remaining, enforcement flag, reset date, and lifetime
counters. This powers the profile Budget card and the chat budget banner.

## Rationale

- **Calendar bucket, no reset job.** Each month is a natural PK row; forgetting to run a reset
  job cannot block a new month. The approach is O(1) on the per-user read path.
- **Fail-open on storage error.** Budget enforcement is a best-effort safety net, not a
  hard-gate. A temporary DB blip must not make the chat inaccessible; the spend is still
  recorded and the next request is correctly gated.
- **Two-layer resolution in one SQL query.** The status query (`build_user_usage_status_query`)
  joins the monthly bucket, the quota override, and the users table in one read. The Python layer
  then calls `_resolve_limit` (pure, unit-testable) with the row values and the cached config.
- **No ALTER on existing tables.** A new `_v1` table holds only the exceptions (per-user
  overrides); the global limit lives in the existing `webapp_settings_v1` JSON. Zero schema
  migration risk.
- **In-process cache for the hot path.** Removes one DB round-trip per `/chat/start` without
  meaningfully delaying an admin change (30-second TTL, busted on write).

## Consequences

Positive:

- Rolling monthly reset requires no scheduled job: new month = new bucket row.
- Fail-open on storage error: chat availability is prioritized over perfect enforcement timing.
- Transparent to the user: the Budget card shows not only the spend and limit but also the
  source of the limit (why it is $X and not the default $50).
- Admin override is flexible: permanent or temporary, for one user or many at once.
- All amounts go through typed validators: NaN, Infinity, negatives and non-numbers are rejected
  at the gate (`validate_budget_amount`).

Negative or watch points:

- **Not yet validated in DSS.** After upload the backend must be restarted (python-lib changed).
  The `webapp_user_quota_v1` table is created lazily on first write (no migration required, but
  the table does not exist until a budget-admin action triggers the first write).
- The 30-second config cache means that an admin change takes up to 30 seconds to propagate to
  OTHER processes (if the backend runs in multi-process mode). In single-process mode the bust
  is immediate.
- The fail-open contract means a user whose budget is exhausted during a DB outage will still
  get their answer. The spend is recorded on recovery, so the next request is correctly gated.
  This is the intended trade-off, not a bug.
- If `webapp_usage_monthly_v1` has no row for a user (brand-new user, new month), the effective
  spend is 0.0. The user's first-of-month call is always allowed, even at 23:59 on the last day
  of the previous month when no bucket row yet exists for the new month - correct behavior.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| A cron-based monthly reset | Fragile (missed jobs, time zone issues); the calendar bucket makes it unnecessary. |
| Hard-block on any storage error | Makes the chat inaccessible during DB blips; fail-open is the correct posture for a metering gate. |
| Per-user override in `webapp_users_v1` via ALTER | Violates the no-ALTER rule; the existing users table must not grow for a new feature. |
| Store the limit as a column in the users table | Would require ALTER + migration; the override is an exception (most users use the global default) - a sparse table is cleaner. |
| Client-side enforcement | Trivially bypassed; enforcement must be server-side, before the agent run starts. |
| Reset on the DB side (a scheduled SQL job) | Not supported in DSS WebApp runtime without a dedicated Flow recipe; the calendar bucket approach is simpler and safer. |

## See also

- [ADR-0003 - Direct SQL without Flow](0003-sql-direct-sans-flow.md) - the no-ALTER, `_vN`,
  parameterized-SQL and safety posture that frames the schema choices here.
- [Backend - security and validation](../04-backend/06-security-and-validation.md) - the
  `validate_budget_amount`, `validate_expires_days` and `validate_user_id_list` helpers.
- [Backend - storage and data model](../04-backend/04-storage-and-data-model.md) - the table
  list where `webapp_user_quota_v1` and `webapp_usage_monthly_v1` are documented.
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - the
  `/chat/start` request path where the budget gate sits.
- [ADR index](README.md) - all architecture decisions.
- [Documentation portal](../README.md) - back to the general table of contents.
