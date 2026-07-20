# ADR-0021 - Source Data aggregates always computed DB-side on the FULL filtered set

> Audience: Backend + frontend developer. Last updated: 2026-07-06. Summary: why every number the Source
> Data Explorer and Evidence show is a database aggregate over the entire filtered set, never a computation
> over the rows currently displayed in the browser.

## Status

Accepted. Delivered 2026-07-06 (Run 1), validated locally (three adversarial reviews soldered, real
Playwright QA); Source Data v3 validated in DSS by the user across Runs 2-4. Lessons L132, L133.

## Context

The Source Data Explorer lets a user filter and explore an agent's raw datasets, with a "Calculer" (KPI)
zone and totals / analysis surfaces; Evidence shows the exact scope the agent's answer used. A dataset view
loads only a page of rows (limit/offset). If a shown total or KPI were computed over the loaded page, it
would be WRONG (it would reflect the window, not the filtered data) and would silently mislead a user who
is trying to verify a figure. This is a correctness requirement, not a nicety.

## Decision

- **Product rule: every number shown = a DB aggregate over the FULL filtered set**, never over the
  displayed window. Two routes serve this: `POST /source/aggregate` (Source Data) and
  `POST /evidence/aggregate` (Evidence), sharing the core `evidence/aggregate_core.py`.
- **The aggregate spec is structured and safe**: functions are WHITELISTED (count, count_distinct, sum,
  avg, median, min, max), each gated against the column's type from the LIVE schema; a `LIMIT 50` on
  groups is mandatory; a separate totals query returns the denominator so percentages are EXACT. All the
  Evidence read-only guards are inherited (`transaction_read_only`, `statement_timeout`, throttle).
- **Evidence aggregates over exactly the agent's pre-filtered scope**: `kept_ids` + drill + filters +
  search, proven by QA on the payloads, so "Verify this figure" computes on the same rows the answer used.
- **The surface is lazy**: opening the Evidence panel triggers NO COUNT; the aggregate runs on the first
  display of the Source data tab (and catches up), so exploration does not fire unnecessary queries.

## Reasons

- Correctness and trust: a figure a user checks must be the real figure over the real filtered data;
  computing over a page would produce confidently-wrong numbers and destroy the verification promise.
- Instance safety: whitelisted functions + type gate + `LIMIT 50` + read-only + timeout + throttle keep a
  replayed aggregate bounded and non-injectable on a shared instance (the same posture as Evidence
  replay, ADR-0008 / gotcha E-1).
- Laziness avoids a burst of COUNTs on panel open; the cost is paid only when a number is actually shown.

## Consequences

Positive:

- Numbers are exact and verifiable against the agent's answer; the "Verify this figure" link lands on the
  same scope.
- The shared `aggregate_core.py` (backend) and `aggregateSurface.js` (front) factor the logic across the
  two hosts, so Source Data and Evidence cannot diverge.
- Bounded and safe by construction on the shared instance.

Negative or watch points:

- Every KPI/total is a round-trip to PostgreSQL; the laziness and the `LIMIT 50` keep this cheap, but it is
  not a client-side computation.
- The pickers' columns default to the base table after a multi-table switch (a pre-existing convention);
  a per-table meta refetch is deferred.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Compute totals / KPIs over the loaded page in the browser | Produces wrong numbers (window, not filtered set); breaks the verification promise. |
| A generic SQL/aggregate route the front parameterizes freely | Violates ADR-0003 (no generic SQL route); the front would choose functions/columns. The spec is structured and whitelisted server-side. |
| Eager COUNT on Evidence panel open | Fires queries the user may never look at; laziness defers the cost to first display. |

## See also

- [ADR-0008 - Evidence trust layer and artifacts](0008-evidence-trust-layer-et-artifacts.md) - the read-only replay guards this reuses.
- [ADR-0003 - Direct SQL, no Flow at runtime](0003-sql-direct-sans-flow.md) - why there is no generic SQL route.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - the capture and read-only path.
- [ADR index](README.md) - all architecture decisions.
