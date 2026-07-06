# ADR-0016 - Ephemeral response modes (Smart by default, reset on send, mode stamped per answer)

> Audience: Frontend + backend developer. Last updated: 2026-07-06. Summary: why the Smart/Pro/Claude
> mode picker resets to Smart at every send instead of persisting, and why the effective mode is stamped
> server-side on each answer (`webapp_chat_v5.mode`).

## Status

Accepted (DSS). Decision made and validated by the user on 2026-07-02 ("great, it works very well").
Lesson L126.

## Context

Modes are named Smart / Pro / Claude in the UI (internal keys eco / medium / high), each mapping to a
different LLM (see ADR-0009). Claude is far more expensive and eats the 50 USD monthly quota (ADR-0014).
When the mode was PERSISTED in `localStorage`, a user who tried Claude once stayed on Claude silently for
every later question, burning the quota without noticing. There was also no record, after the fact, of
which mode had produced a given answer, so usage and cost could not be attributed per response.

## Decision

- **Smart is the permanent default.** Boot is unconditionally `smart`; the `localStorage` persistence of
  the mode was REMOVED (legacy key purged). `resetModelMode()` returns the picker to Smart.
- **Reset happens at the instant of send.** `chat.js` captures `rawMode` / `runMode` BEFORE the reset,
  stamps `newVersion({mode})`, then resets SYNCHRONOUSLY before the await, so the picker is already back
  to Smart while the run is in flight (edit and regenerate behave identically). Analytics
  (`question_sent` / `answer_received`) read the STAMP, never the reset store.
- **The effective mode is stamped server-side per answer.** A nullable `mode VARCHAR(16)` column was added
  to `webapp_chat_v5` via `ADD COLUMN IF NOT EXISTS` (no `_v6` bump; the idempotent-ALTER pattern, L126).
  `/chat/start` computes the effective mode with the pure helper `agents/context.resolve_effective_mode`
  and writes it in phase 1 (`'smart'|'pro'|'claude'`, NULL for an agent with no modes). `/conversation`
  exposes it NULL-safe and `MessageAgent` shows it in the token/cost line. Old NULL answers render exactly
  as before.

## Reasons

- Cost safety by construction: the expensive mode is opt-in per question, never sticky. The user chooses
  Claude only for the question that needs it.
- Attribution: stamping the mode on the row makes cost and adoption analyzable per answer and crossable
  with `webapp_events_v1` (ADR-0017) for the adoption dashboard.
- The idempotent `ADD COLUMN IF NOT EXISTS` avoids a `_vN` bump (which would have orphaned history) for a
  purely additive, nullable column - the second sanctioned use of that pattern (after users_v1).

## Consequences

Positive:

- No silent quota drain; Smart (recommended, green) is always the starting point.
- Per-answer mode is durable and visible, and feeds analytics without a new table.
- `timelineModel.js` only gained a `mode:null` field on the shape plus a pure `modeFromRow`; the reducer
  and `timelineSignature` are UNTOUCHED (verified by the 3-lens review, 0 confirmed findings).

Negative or watch points:

- A user who wants Pro/Claude for several questions in a row must re-select it each time; this is the
  intended friction, not a bug.
- `ADD COLUMN IF NOT EXISTS` is the ONLY sanctioned exception to the "no ALTER, new `_vN`" rule (B-1): it
  is additive and nullable. A type change or a non-null column still requires a new table.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Keep persisting the mode in `localStorage` | The exact cause of the silent quota drain; sticky Claude is a cost trap. |
| Bump to `webapp_chat_v6` for the new column | Would orphan all prior conversations for a purely additive nullable field; the idempotent ALTER is safe here. |
| Infer the mode after the fact from the model id | Fragile (ids move, ADR-0009) and impossible for answers already written; an explicit stamp is authoritative. |

## See also

- [ADR-0009 - Per-mode model and mode propagation](0009-modeles-par-mode.md) - what each mode maps to.
- [ADR-0014 - Monthly budget and per-user quotas](0014-monthly-budget-and-per-user-quotas.md) - the quota the modes spend against.
- [ADR-0017 - Usage analytics in a single SQL events table](0017-usage-analytics-events-table.md) - the mode stamp is crossed with events for adoption.
- [Storage and data model](../04-backend/04-storage-and-data-model.md) - `webapp_chat_v5` and the `_vN` naming rule.
- [ADR index](README.md) - all architecture decisions.
