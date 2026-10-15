# V2.0 handoff (after phase 1, commit 7ab674e, 2026-10-15)

Branch `OWIsMind_PRD_V2_0` (no `-dev` suffix: explicit user decision). Spec: `docs/V2_ARCHITECTURE.md`.
Budget rule from the user: at most 2 Opus subagents + 1 Fable advisor; warn the user before 45% context.

## Phase 1 status (done, validated by the user on the harness)
- Backend 988 tests OK, agents 804 OK, frontend 473/473, vite build OK.
- Harness: `OWIsMind_PRD_V2_0/plugin/owismind/frontend/node_modules/.bin/vite --config OWIsMind_PRD_V2_0/dev-harness/vite.config.mjs` then http://127.0.0.1:5199.

## User feedback to apply first (phase 2 front)
1. The user did not see the right-hand side (data / results workspace) in the harness: check that the
   workspace panel actually shows when a question runs, and make it discoverable.
2. Like the mock (`docs/design-v2/Espace de travail v4.dc.html`, prop `showTeaser`, `.bcn` styles):
   at start, only a small clickable teaser zone to discover the data, never an imposed open panel.

## Phase 2 scope (see spec section E)
- WP-A: orchestrator tools write_plan / update_plan / write_note / publish_widget, plan-first policy,
  prov.set with result_id per sub-agent result, persona via hub, graph tests; backend relays capped
  rows per sql_id live on /chat/poll (keys `sqlId` + `result`, the frontend already consumes them).
- WP-B: teaser + panel discoverability, responsive, Data tab pre-filtered by sql_id, sidebar, analytics.
