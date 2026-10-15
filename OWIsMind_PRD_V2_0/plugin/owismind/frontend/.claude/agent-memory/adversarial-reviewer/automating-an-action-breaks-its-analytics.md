---
name: automating-an-action-breaks-its-analytics
description: When a diff turns a user-triggered UI action into an automatic one, check its track() call - intent-named events in webapp_events_v1 silently change meaning
metadata:
  type: project
---

Whenever a diff makes a previously user-triggered action happen automatically, grep the code
path for `track(...)` before accepting it.

**Why:** this repo ships real usage analytics (`services/track.js` -> `POST /track` ->
`webapp_events_v1`), and the event names encode USER INTENT (`source_explorer_opened`,
`agent_changed`, `conversation_created`, `screen_context_dismissed`). Automating the action keeps
the event firing but changes what it measures, with no error and no test failure: the metric's
history breaks silently and nobody notices until someone reads the dashboard. Found on 2026-08-06
when the Source Data panel became auto-docked on the arrival screen: `source_explorer_opened`
went from "a user opened the explorer" to "an arrival screen was shown".

**How to apply:**
- The accepted fix shape here is an options flag on the store action, not a new call site:
  `openPanel(key, opts)` with `if (!(opts && opts.auto)) track(...)`, the automatic caller passing
  `{ auto: true }` and user callers passing nothing. Check that EVERY call site was audited
  (`grep -rn "openPanel(" src/`), not just the one the diff touched.
- Ask whether the team still needs a denominator. Skipping the event entirely leaves ZERO
  telemetry on how often the automatic surface is shown, so a dismissal/engagement rate becomes
  uncomputable; a distinct event name (`*_docked`) preserves both. Raise it, let the lead decide.
- `services/trackModel.js` holds the event-name -> category map: it is the authoritative list of
  which events exist, useful to spot the intent-named ones.

See also [[boot-race-exchanges-length]], [[owismind-frontend-review-patterns]].
