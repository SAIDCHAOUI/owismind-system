---
name: owismind-frontend-review-patterns
description: How to verify scope claims and where OWIsMind frontend sessions tend to be genuinely solid (2026-07-08 Help & Support hub review)
metadata:
  type: project
---

Reviewed the `/support` Help & Support hub (HelpSupportView.vue, catalogFallback.js, backend.js
additions, router, AgentsView CTA) against a detailed 10-point contract on 2026-07-08. Result: all
10 requirements passed on inspection + `node --test` (10/10 tests, real assertions not stubs) +
a clean `vite build`. No frontend defects found. Notable things confirmed by tracing, not assumed:
- The `submitFeedback` (per-message thumbs) vs `submitGeneralFeedback` (new hub) naming split in
  `services/backend.js` was clean: old signature/call sites untouched, no stale call site expected
  the old name for the new feature.
- The catalog fallback rule (`ok:false` OR `ok:true` with an empty list -> MANUAL; only `null`/`undefined`
  response -> LOADING) was applied identically and independently for both the project picker and the
  dataset picker, including the manual-entry payload shape matching the live-catalog payload shape
  exactly (`{dataset, table, connection}`).
- i18n: only truly-new keys (`fb.cat.other`, `sup.*`, `ar.*`) were added to `extra.js`; keys that
  pre-existed in `messages.json` (from the deleted FeedbackView) were correctly left alone, and
  `test/i18nExtraParity.test.js` iterates all keys generically so it does exercise the new ones.

**Process note - scope-claim verification**: the task said "backend routes NOT yet built by other
workstreams," but `git status` on the working tree showed `python-lib/owismind/api/routes.py`,
`storage/feedback.py`, `storage/agent_requests.py`, `agents/user_catalog.py` etc. already present
and uncommitted alongside the frontend changes (all in the same dirty working tree, no separate
commits/branches to disambiguate). Always run `git status`/`git diff --stat` yourself rather than
trusting a task's framing of "not built yet" or "frontend only" - in this repo, parallel
workstreams routinely sit uncommitted together in one working tree, and only actual git state can
confirm isolation. This was reported as a scope-verification finding, not a frontend defect (the
routes.py content matched the exact contract the frontend called, so it read as a legitimate
concurrent backend workstream, not backend files accidentally touched by the frontend session).

**Calibration**: this repo's Claude-authored sessions (see [[repo-memory-layout]]) tend to produce
genuinely clean, well-tested frontend work with accurate self-documenting comments (e.g. the
comment in `catalogFallback.js` literally states the exact fallback rule, and it matched the code).
Do not assume the report exaggerates test coverage or skips edge cases - verify, but expect to
often confirm rather than refute.
