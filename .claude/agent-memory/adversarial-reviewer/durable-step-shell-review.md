---
name: durable-step-shell-review
description: Recurring security-review points for the v1.3 Durable Step Shell (durable_runner, run_state, correlate guard, workflow token protocol)
metadata:
  type: project
---

Durable Step Shell (v1.3) adversarial-review gotchas, from the 2026-07-17 security audit.

**Correlate SQL guard (`_corr_guard_model_sql`, OWIsMind_orchestrator.py).** It blanks string
literals but NOT SQL comments. `_CORR_TABLE_LIST_RE` needs `\s+` after FROM/JOIN, so `FROM/**/table`
(PostgreSQL treats `/**/` as whitespace) slips the table past the alias allowlist (read-only, but a
cross-table read incl. the catalog's server-only connection_name/physical_table). Comma-join
(`FROM d1, secret`) was already fixed in commit 79a94c5; the comment variant is the same class and
was still open at HEAD. When reviewing this guard: test `FROM/**/x`, `JOIN/**/x`, `UNION SELECT..FROM/**/x`.
Verify empirically by exec-loading the real module (dataiku/langgraph stubs) and calling the guard.
The correlate catalog read + EXPLAIN/preview/final all correctly use
`_CORRELATE_PRE_QUERIES = (statement_timeout 30s, transaction_read_only on)`.

**Reservation reap TOCTOU (durable_runner.py).** `start_workflow` inserts a slot placeholder
`_WORKERS["resv-"+exchange_id] = {"thread": None, "reservation": True}` under the lock to close the
per-user/global cap TOCTOU. But `_reap_dead_workers_locked` (run at the top of every start_workflow)
reaps EVERY entry with a falsy thread, including reservations -> a concurrent same-user start reaps
the sibling's reservation and bypasses `MAX_ACTIVE_WORKFLOWS_PER_USER=1`. The cap tests use
LIVE-thread workers, so they miss this. Fix = skip `w.get("reservation")` in the reaper.

**Verified-clean invariants (so future reviews don't re-litigate):** token forgery is well defended
(parse_workflow_control tail rule + backend token appended LAST + the always-present `[Context - ...]`
non-token block after the user text in legacy); run_state parameterizes every user value via
sql_value/nullable_value/_int_arg/_ts_sql and owner-scopes every user-facing read; the control channel
(OWI_WORKFLOW_CONTROL) is normalized to an internal `workflow_control` type, denylisted in
append_events, and never public; project_run_public strips lease fields; caps (Mesh semaphore 3,
supervisor claims 1/scan, bounded loops/purge) hold.

**By-design note:** the correlate `generated_sql` embeds the physical table (CTE) and surfaces it in
Evidence/chat_v5 exactly like the legacy semantic-model-query SQL. The model never sees physical
names; the public timeline event excludes the sql text. Consistent with legacy, not a regression.

See also [[repo-review-pitfalls]] (read-only pre-queries, baseline) and [[security-invariants]].
