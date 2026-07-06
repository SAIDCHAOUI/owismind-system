# ADR-0017 - Usage analytics in a single SQL events table (not file-per-event)

> Audience: Backend + frontend developer. Last updated: 2026-07-06. Summary: why webapp usage tracking
> writes to ONE raw SQL table (`webapp_events_v1`) via a best-effort `POST /track`, instead of the
> one-file-per-event folder approach of the old Dash webapp.

## Status

Accepted (DSS). Decision made and validated by the user on 2026-07-02 ("it works great", "all good").
Lesson L125.

## Context

The team wanted GA4-like visibility into webapp usage (frequentation, feature adoption, user journeys),
distinct from the agentic run logs. The predecessor Dash webapp had written one file per event to a
managed folder / S3; that pattern is slow to aggregate, produces millions of tiny objects, and its
weakness was proven in practice. Tracking must also never slow or destabilize the request path on a shared
instance (rule #2), and must not leak PII.

## Decision

- **One raw SQL table, `webapp_events_v1`** (13 columns; `view_name` because `VIEW` is reserved in PG;
  index `(app_session_id, seq)` for journey reconstruction). A GROUP BY on `event_name` gives top features.
- **`storage/events.py` is the whitelist source of truth: 38 auto-descriptive events** (`question_sent`,
  `answer_received {duration_ms}`, `webapp_opened`, `page_viewed`, and the Evidence tabs as first-class
  events: `chart_viewed` / `table_viewed` / `kpi_viewed` / `source_data_viewed` / `evidence_proof_viewed`).
  `validate_events` is pure (batch cap 40, prop cap 2000c, dedup, py3.9-safe `client_ts`); `record_events`
  is ONE multi-row INSERT with `ON CONFLICT DO NOTHING`, best-effort.
- **`POST /track` never breaks the app**: it accepts a `sendBeacon` text/plain body (`get_json` force +
  silent), DROPS the write under impersonation, throttles (12 per 0.5 s), and NEVER returns 500.
- **Frontend**: pure `trackModel.js` (queue cap 200, drain 40, error limiter 10/session) + `track.js`
  (app_session_id, seq, flush every 5 s / 20 events, `sendBeacon` on pagehide, no-op under impersonation) +
  thin hooks (router `afterEach`, 7 stores, feedback, cell popover, window/Vue/network errors).
- **Privacy by construction**: searches log only `{len}`; error paths log the route WITHOUT the query
  string (the HIGH finding of the 12-Opus adversarial review, L125). Sessions = 30-min gap, no `session_end`.

## Reasons

- A single table aggregates with plain SQL (DAU, feature counts, funnels) and scales far better than
  millions of one-event files; the file-per-event weakness was already observed on the Dash app.
- Best-effort + throttle + never-500 keeps analytics strictly subordinate to the product: a tracking
  failure is invisible to the user and harmless to the instance.
- A server-side whitelist (38 events) prevents an open-ended event space and keeps the schema stable;
  parity is enforced by a script (38/38).

## Consequences

Positive:

- Adoption is queryable with SQL and crossable with `webapp_chat_v5.mode` (ADR-0016) for a per-mode
  adoption dashboard.
- Zero risk to the request path: impersonation drop, throttle, best-effort write, no 500.
- PII-safe: no raw search text, no query strings in error events.

Negative or watch points:

- The event taxonomy is a whitelist: a NEW event must be added on BOTH sides (server whitelist + client
  hook) and keep 38/38 parity; an unknown event is silently ignored.
- The adoption dashboard itself (a DSS dataset over the table + rollups) remains roadmap.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| One file per event in a managed folder / S3 (old Dash approach) | Millions of tiny objects, slow to aggregate; its weakness was proven in production. |
| Reuse the agentic run/event tables | Different purpose (product usage vs run tracing); mixing them muddies both schemas. |
| A third-party analytics SDK | External network calls from inside DSS, PII exposure, and it violates the NO INSTALL / instance-safety posture. |

## See also

- [ADR-0016 - Ephemeral response modes](0016-ephemeral-response-modes.md) - `chat_v5.mode`, crossed with events.
- [ADR-0003 - Direct SQL, no Flow at runtime](0003-sql-direct-sans-flow.md) - the SQL storage posture this table follows.
- [Storage and data model](../04-backend/04-storage-and-data-model.md) - `webapp_events_v1` schema.
- [ADR index](README.md) - all architecture decisions.
