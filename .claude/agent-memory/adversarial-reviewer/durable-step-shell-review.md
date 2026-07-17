---
name: durable-step-shell-review
description: Recurring security-review points for the v1.3 Durable Step Shell (durable_runner, run_state, correlate guard, workflow token protocol)
metadata:
  type: project
---

Durable Step Shell (v1.3) adversarial-review gotchas, from the 2026-07-17 security audit.
UPDATE 2026-07-17 (run 3): the three findings below are now ALL FIXED and re-verified clean (see the
"Fix-verification pass" section at the end). Keep the descriptions as the map of where the guard's
weak spots historically were.

**Correlate SQL guard (`_corr_guard_model_sql`, OWIsMind_orchestrator.py).** It blanks single-quoted
string literals but NOT dollar-quotes/comments. Historic holes (all closed now): SQL comments
(`FROM/**/table`, PostgreSQL treats `/**/` as whitespace) -> now rejected outright (`/*`/`--`);
comma-join (`FROM d1, secret`, commit 79a94c5); no-whitespace quoted ident (`FROM"secret"`) needed
`\b\s*` not `\s+`; bare-relation `TABLE foo` needed the `table` keyword; query-executing/file funcs
(query_to_xml/dblink/pg_read_file...) needed `_CORR_FORBIDDEN_FUNC_RE`. NOTE `_CORR_SYSTEM_TABLE_RE`
`pg_[a-z_]+` also catches ALL `pg_*` funcs (pg_ls_waldir, pg_stat_file, ...) as a backstop. When
reviewing this guard: test `FROM/**/x`, `FROM"x"`, `TABLE x`, `UNION..TABLE x`, query_to_xml, dblink,
UNION/subquery to a non-alias, WITH cte, INTO, schema-qual `public.x`, dollar-quote. Verify empirically
by reusing the test's `_install_stubs`+`_load` harness (dataiku/langgraph stubs) and calling the guard
directly (I keep a probe pattern in scratchpad). Known ACCEPTED false-positive: a legit dataset column
named EXACTLY a banned keyword (`"table"`, `"into"`, `"with"`...) is rejected as forbidden_keyword;
fails CLOSED, correlate degrades, feature is flag-OFF, so it's an accepted trade-off, not a bug.

**Reservation reap TOCTOU (durable_runner.py).** `start_workflow` inserts a slot placeholder
`_WORKERS["resv-"+exchange_id] = {"thread": None, "reservation": True}` under the lock to close the
per-user/global cap TOCTOU. `_reap_dead_workers_locked` MUST skip `w.get("reservation")` (it reaps
falsy-thread entries) or a concurrent same-user start reaps the sibling's reservation and bypasses
`MAX_ACTIVE_WORKFLOWS_PER_USER=1`. FIXED: reaper now `if not w.get("reservation") and (no live thread)`.
The cap tests use LIVE-thread workers, so they miss this - check the reaper source directly.

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

**Fix-verification pass (2026-07-17 run 3), all CORRECT.** (1) `run_state.save_plan` now serializes the
WHOLE `{task,capability_keys,args,produces,checks,depends_on}` dict into `task_json` (was the bare task
string, so `_step_spec` rebuilt the wfstep token with no capabilities and every execute step failed);
empty payload still -> `_json_capped` None -> SQL NULL (no regression), value SQL-safe via toSQL/Constant,
bounded by MAX_TASK_JSON_CHARS. (2) orchestrator catalog read fixed to `column_name,column_type,
description,physical_table` with NO `item_level` filter - matches `owismind_factory.catalog.CATALOG_SCHEMA`
(the type col is `column_type`; there is no `item_level`/`data_type`, so the old query failed on every
read). The correlate test mock now ASSERTS column_type present + item_level/data_type absent (strengthened,
would catch a revert). (3) guard hardening verified by probe (25 cases, above). (4) `poll_durable` honors
`error=='not_found'` (done=True) - not an oracle because `read_events`->`load_run(user_id)` gives missing
and foreign runs the identical 404 shape; no CODE_* constant equals 'not_found' so a real run is never
misread. `start_workflow` swallows claim/spawn failures AFTER `create_run` (else the route's legacy
fallback double-runs the exchange); errors BEFORE create_run (BusyError/deadline/create fail w/ no
existing) still propagate. Recovery picks the orphan up: unclaimed run has status='queued' + lease NULL
(recoverable now), claimed-but-unspawned recovers when the 45s lease expires (find_recoverable_runs:
active AND lease NULL/expired). purge every 360 scans is bounded (terminal, finished>14d, LIMIT 1000,
off hot path). (5) `_coerce_flag`: falsy STRINGS ("false"/"0"/"no"/"off"/""/"none") -> False, real
bools/ints via bool() (1->True,0->False); the consumed profile is the VALIDATED one (save path
routes.py validate_agent_meta), so the route's extra bool() is a harmless no-op. Suites: backend 965 OK,
orchestrator/factory 619 OK (skip 2).

See also [[repo-review-pitfalls]] (read-only pre-queries, baseline) and [[security-invariants]].
