---
name: guided-first-build-auto-review
description: Review of the guided assistant first_build MANUAL->AUTO change (scenario step_based + run_scenario_and_wait + heal migration)
metadata:
  type: project
---

Change (2026-07-22, uncommitted on OWIsMind_PRD_V1_3-dev): the factory refresh
scenario became `step_based` (one `build_flowitem` step per knowledge dataset,
raw_steps read-back), and the guided assistant stage `first_build` went from
MANUAL to AUTO (`flow_builder.run_scenario_and_wait`, bounded 1800s/10s poll).

**Verified SOUND, no defects found (692 tests pass).** Points that survived
refutation:
- heal_interrupted has a NEW WAITING branch (`status==WAITING and key in _RUNNERS
  and key not in _CHECKERS`) placed BEFORE the RUNNING branch. Only `first_build`
  can satisfy it (brain/template are R+C; other runners never reach WAITING), so
  it migrates ONLY the stale manual first_build; RUNNING self-heal preserved.
  Idempotent (after migration status=READY, second call no-ops).
- Wait loop is bounded: `waited += step`, `step=poll or 1`; TIMEOUT returns
  _OUT_FAILED (re-runnable). `poll_seconds=0` busy-loop is TESTS-ONLY (prod uses
  default 10). run.refresh() handles staleness; run finishing between checks OK.
- Slot/deadlock: guided job holds the single mutating slot for up to 30 min BY
  DESIGN; worker `finally` always releases; a >timeout job flips to "done" so
  `_guided_job_running()` is False afterwards while the DSS run keeps going, and
  the stage is FAILED (not RUNNING) so heal won't wrongly demote. Re-run
  re-attaches via `scenario.get_current_run()` (never double-fires).
- Frontend contract frozen: script.js renders on `status` (ready/failed->Lancer,
  waiting_user->C'est fait), NOT on `kind`; heal runs inside api_guided_current
  before returning so the front always gets the healed READY state.
- Outcomes: SUCCESS/WARNING=green then row-proof (absent/empty fail, None
  tolerated); ABORTED/None/NOT_FOUND/NOT_STARTED->failed with FR fix path.
- Journal caps fine (state saved once at job end; <60 entries/stage vs 150k soft
  cap in guided_store). Py3.9 OK (% formatting, import time), no banned dashes.

Minor non-blocking: `docs/CAPABILITY_MATRIX.md` L14 still says the scenario is
`create_scenario(..., "custom_python")` (probe matrix, now stale vs step_based);
not a correctness defect. Related: [[factory-existence-checks-split]].
