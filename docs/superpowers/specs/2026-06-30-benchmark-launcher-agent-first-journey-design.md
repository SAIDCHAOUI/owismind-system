# Benchmark Launcher: agent-first guided journey (auto-membership, append mode)

Status: FROZEN design (session 2026-06-30, follow-on). This redesigns the LAB benchmark
**Launcher** webapp into an agent-first guided journey and, as a consequence, simplifies the
benchmark data model.

It SUPERSEDES, for the launcher + the membership model, parts of
`2026-06-29-benchmark-v2-append-mode-design.md`:
- the curated `questions` membership map on a benchmark is REMOVED (membership becomes auto-derived
  from a new golden agent tag);
- the launcher's flat Benchmarks tab and the Configuration tab are removed.
The append-mode identity, the per-run/attempt accumulation, the judge/scoring/capture engine, and the
reference `expected_sql` / `expected_tool` columns are kept unchanged except where stated.

This spec is the launcher journey plus the shared lib + data-model changes it requires. The Results
webapp and the plugin consultation tab are touched only where consistency demands it (section 11).

## 1. Locked decisions (settled with the user, do not re-litigate)

1. **Agent tag on the golden**: each golden question carries ONE agent tag (a new `agent_key` column).
   "All questions for agent X" = active golden rows whose `agent_key` == X.
2. **Agent discovery**: the agent catalog is populated by discovering the real agents from the DSS
   projects (best-effort Dataiku API call), cached in the `benchmark` variable; the user selects an
   agent and its label + `agent_id` + `project_key` are captured. Manual entry is the fallback.
3. **Auto-membership**: a benchmark stores NO question list. Its question set is computed LIVE = active
   golden rows whose `agent_key` == the benchmark's agent. A newly tagged question is therefore pending
   in EVERY benchmark of that agent until tested. No manual add/remove of questions to a benchmark.
4. **Per-benchmark config = modes only**. Everything else (golden dataset name, judge LLM id, the 4
   result dataset names, concurrency, run language) is GLOBAL and editable in a Settings surface.
5. **Hard delete**: deleting a benchmark removes it from the registry (the `benchmark` variable) behind
   a named confirmation. Past scored rows stay in the dataset (harmless, stamped with the dead
   benchmark id).
6. **Navigation = master-detail** with a persistent agents rail (not a linear wizard).
7. **Gated creation**: when an agent has 0 active tagged questions, `New benchmark` is locked and the
   only lit action is `Tag questions`. A benchmark can only be born already populated and runnable.

## 2. The path in one paragraph

Land on the list of real agents (discovered from DSS, ids auto-filled). Click one. See its benchmarks,
or "no benchmark yet" with a Create button (locked if no question is tagged yet). Create one with just
a name + the modes; the instant it exists it has pulled in every active golden question tagged to that
agent, so `Run pending` is armed, never grayed. Run it, watch progress, get a score; tested questions
are marked done (derived from the scored dataset). Tag new golden questions to the agent later and they
appear as pending in every one of that agent's benchmarks until one tests them; re-runs show evolution.
Hard-delete a benchmark behind a confirm. Change the golden dataset name and other globals in a gear
Settings. A quiet footer always states where the data lives.

## 3. The data model

### 3a. Golden questions: add `agent_key`
Add ONE nullable column to `GOLDEN_COLUMNS`: `agent_key` (the LOGICAL agent key the question tests,
e.g. `orchestrator`, `revenue_expert`). Nullable so legacy rows validate; a row with a blank
`agent_key` is "untagged" (belongs to no benchmark). NOT a hard-required field in `validate_golden_row`,
but the launcher's "Add a question" form requires it (a question is never born untagged via the UI).

`agent_key` is the LOGICAL key, never the human label and never the raw `agent_id`. This is rename-proof
(renaming the agent in DSS does not orphan tags) and deployment-flexible (the same tagged questions can
feed a DEV and a PROD benchmark of the same logical agent). The concrete `agent_id` + `project_key` live
on the catalog/benchmark binding, not on the question.

### 3b. Agent catalog (the `agents` block in the `benchmark` variable)
Each catalog entry = `{agent_key, agent_label, project_key, agent_id, modes}` (the existing shape).
`agent_key` is the stable logical key; `agent_id` + `project_key` are the concrete binding used to call
the agent via Mesh; `modes` (bool) = mode-aware or not.

Discovery (best-effort) enumerates agents across the accessible DSS projects and proposes candidates
`{project_key, agent_id, agent_label}`. When the user connects a candidate, the catalog stores it with a
logical `agent_key` prefilled from a slug of the label (editable once at connect time). The catalog is
CACHED in the variable; it is refreshed only on the explicit `Refresh` action, never on every page load
(instance safety). Manual add writes the same shape directly.

### 3c. Benchmark entity (registry, in the `benchmark` variable, key `benchmarks`)
```jsonc
"<benchmark_id>": {
  "benchmark_id": "<uuid hex>",
  "name": "Q4 Baseline",                 // unique per agent (was: globally unique)
  "agent_key": "revenue_expert",         // logical key (matches golden.agent_key)
  "agent_label": "Revenue Expert",       // display snapshot
  "project_key": "OWISMIND_DEV",         // concrete binding snapshot (precision)
  "agent_id": "agent:bHrWLyOL",          // concrete binding snapshot (precision)
  "modes": ["Smart","Pro"],              // the ONLY per-benchmark config
  "status": "active",
  "created_at": "...Z",
  "created_by": "user",
  "redo": ["<question_id>", ...]          // small set flagged "redo at next run"; the ONLY per-question state stored
}
```
REMOVED vs the 2026-06-29 model: the `questions` membership map. ADDED: a small `redo` list. Nothing
about "tested" is stored here (section 3d).

Name uniqueness is now PER AGENT (two different agents may each have a "Baseline").

### 3d. Derived status (per question, per mode) - never stored
Status is computed, not persisted:
- members(benchmark) = active golden rows where `agent_key` == benchmark.agent_key.
- For a member question q and a mode m in benchmark.modes:
  - `tested(q, m)` = a scored row exists with this `benchmark_id` + `question_id == q` + `mode == m`.
  - `pending(q, m)` = not tested.
- A question's row shows one chip per benchmark mode (e.g. Smart: OK, Pro: pending), where a tested
  cell shows the latest attempt's effective verdict (OK / MISS).
- Benchmark ledger: `tested` = count of (q, m) cells tested; `pending` = count not tested; `redo` =
  count of member questions in the `redo` set. These are three SEPARATE counts.

This keeps the variable tiny and makes "marked done in the dataset AND the webapp" mean: the scored
dataset is the source of truth, the UI reflects it.

### 3e. Launch resolution (per mode; append vs full)
`registry.resolve_to_run(entity, golden_active_tagged_ids, scored_rows, launch_mode)` returns a per-mode
plan, e.g. `{ "Smart": [qid, ...], "Pro": [qid, ...] }` (or an equivalent list of `(qid, mode)` cells):
- members = active golden ids tagged to entity.agent_key.
- `full`  : every (member, mode in entity.modes).
- `append`: every (member, mode) cell that is NOT tested, UNION every (member, mode) where the member is
  in entity.redo. (Adding a new mode via Edit modes makes every member pending for that new mode, since
  none of its cells are tested yet.)
The runner already does an agent x mode matrix; step 1 runs exactly the resolved cells.

`runnable` cells = the per-mode cells the next `append` run will execute = all pending (q, m) cells PLUS,
for each member question in entity.redo, its (q, m) cells across entity.modes (a redo question is
otherwise tested, so its cells are not already counted in pending). This single number labels the primary
button so the button and its helper can never disagree (kills the old silent gray button). The ledger
shows `redo` as the count of member questions flagged (display), while the `Run pending (N)` button's N
counts the actual cells to run.

## 4. Information architecture

Primary surface = agent-first master/detail. A persistent **AGENTS rail** (left) + a **detail panel**
(right) that re-renders in place: agent -> benchmark -> questions/run. A breadcrumb at the top of the
detail panel gives every level a parent. A muted one-line **data-location footer** is always visible.

What replaces the 5 old tabs:
- Benchmarks (flat list) -> the AGENTS rail -> agent detail -> benchmark detail drill (no flat list).
- Configuration -> DELETED. Per-benchmark modes move inside the benchmark; all globals move to a gear
  **Settings**.
- Golden set -> kept as a header link AND reachable as `Tag questions to this agent` (pre-filtered) from
  the agent screen.
- Suggestions / Review -> kept as header links, unchanged (out of scope).

A self-erasing **Getting Started** strip appears under the title while first-run setup is incomplete (no
agent connected, or selected agent has 0 tagged questions, or 0 benchmarks, or 0 runs ever); it hides
permanently after the first successful run.

Footer copy (the standing answer to "where is it stored"):
`Benchmarks and redo flags live in the project variable "benchmark". Questions and results live in Flow
datasets (set their names in Settings).`

## 5. Screens (the agreed wireframes)

The agreed wireframes and microcopy are the ones presented and approved in the brainstorm; they are the
reference for implementation:
- Screen 1: agent picker (rail) with discovery states (discovering / discovered / failed-with-known /
  manual add). Selecting a row auto-fills label + agent_id + project_key downstream.
- Screen 2: agent's benchmark list, including the empty states 2b (no benchmark, questions exist ->
  `Create the first benchmark`) and 2c (no benchmark AND 0 tagged -> Create locked, `Tag questions`
  lit). Header `New benchmark`, per-card `Open` / `Delete`, footer link `Tag questions`.
- Screen 3: create benchmark (agent locked + pre-filled, name unique-per-agent, modes only). Reassurance
  line shows the live pending count; if 0 tagged, Create is swapped for `Tag questions`.
- Screen 4: benchmark detail = LATEST SCORE + RUN LEDGER (`t tested . p pending . r redo`), the run
  buttons (`Run pending (N)` where N = runnable, `Re-run entire benchmark`), `Edit` (modes), `Delete`,
  and the questions table with one verdict chip per mode. States 4a (just created, armed), 4b (mixed),
  4c (all tested -> Re-run is the orange primary, no bare gray button), 4d (0 active tagged ->
  `Tag questions`), 4e (new-questions feedback banner), 4f (edit modes), 4g (delete confirm).
- Screen 5: run progress (`scored / total`, degrade to elapsed), single-flight lock messaging,
  run-complete (score + per-mode accuracy + `Open full results in Results webapp`), re-run-complete
  (evolution: improved / regressed / same, regressions pinned to top).
- Screen 6: golden agent-tagging (pre-filtered to the agent): a table with an `Agent tag` dropdown (fed
  by known agents) + Active toggle, plus full golden CRUD (question, reference answer, expected_value,
  and the v2 `expected_sql` / `expected_tool`). The tag dropdown + Active toggle are the only membership
  controls. `Add a question` requires the agent tag.
- Screen 7: Settings (gear): `Golden dataset name` (first, editable), `Judge LLM id`, `Concurrency`,
  `Run language`, the 4 result dataset names, and the where-data-lives note.

Charter: white/black/flat/square, a single orange #FF7900 used rarely (eyebrow, 52x4 title-bar, selected
rail edge, the one primary button per screen, the pending dot, the progress fill). Banned: gradients,
blur, glow/big shadows, emoji, color-mix, em dash and en dash (also in the FR strings). Bilingual EN
default + FR.

## 6. Backend routes (launcher `backend.py`)

New / changed (all wrapped by `_safe`, never a 500; all variable writes go through the registry lock):
- `GET  /api/agents` -> the cached catalog (+ a `discovered_at`); used to render the rail.
- `POST /api/agents/discover` -> best-effort DSS discovery, cache into the variable, return the catalog.
  Degrades to `{discovery: "unavailable"}` + the existing cached/known agents.
- `POST /api/agents/connect` -> add a discovered or manual agent to the catalog (`agent_key`, label,
  project_key, agent_id, modes). Variable RMW.
- `GET  /api/agent/benchmarks?agent_key=...` -> that agent's benchmarks (derived counts: questions,
  tested, pending, redo, last run, score) + tagged-question count.
- `POST /api/benchmark/create` -> `{name, agent_key, modes}` only (no question_ids; membership is
  derived). Pins the agent binding snapshot from the catalog. 400 if 0 active tagged questions (gated).
- `POST /api/benchmark/delete` -> hard delete from the registry (named confirm on the client). Variable
  RMW. (Replaces the dead `archive` route; archive is dropped.)
- `POST /api/benchmark/modes` -> set the benchmark's modes. Variable RMW.
- `POST /api/benchmark/redo` -> set/clear the redo flag for one member question. Variable RMW.
- `POST /api/benchmark/launch` -> write `run_request {benchmark_id, launch_mode}`, fire the single-flight
  scenario. Redo is cleared per (qid, mode) only AFTER its new scored row lands (section 10).
- `POST /api/run/reset` -> clear a stuck `run_request` when the scenario is verifiably not running
  (section 10). Variable RMW.
- `GET  /api/run/status` -> scenario status + live `scored / total` for the active run_id.
- `GET  /api/golden?agent_key=...` -> golden rows, optionally filtered to an agent / untagged / all.
- `POST /api/golden/save` / `POST /api/golden/delete` -> golden CRUD, now carrying `agent_key`,
  `expected_sql`, `expected_tool`. Save bootstraps the `agent_key` column if missing (section 8).
- `GET  /api/settings` / `POST /api/settings` -> the global settings (golden dataset name, judge LLM,
  concurrency, run language, 4 result dataset names). Save validates the golden dataset (section 8).

Removed: the old `GET/POST /api/config` (Configuration tab) and the manual agents-catalog editor it fed
(replaced by discovery + connect + Settings). The legacy global `POST /api/run` is removed (launch is
per-benchmark). Suggestions / Review / override routes are unchanged.

## 7. Pure module changes (`benchmark/` lib, unit-tested, never raise)

- `registry.py`: drop the `questions` membership map and `add_questions` / `remove_question` /
  `_normalize_questions`. Keep `create_benchmark` (no question seed), `rename_benchmark`,
  `delete_benchmark` (new; remove from the dict), `set_redo` / `reset_redo` (the small redo set),
  `done_cells` / `pending_cells` (per (qid, mode), from scored), `resolve_to_run` (per-mode plan, append
  vs full, section 3e), `next_attempt_no`. Name uniqueness becomes per-agent
  (`validate_benchmark_name(name, taken_names_for_agent)`). Add an `agent_key`-slug helper.
- `schemas.py`: add `agent_key` to `GOLDEN_COLUMNS` (nullable, not in `_REQUIRED_GOLDEN`); carry it
  through `normalize_golden_row`. Add `agent_key` to `RAW_COLUMNS` (denormalized for display/breakdown)
  if useful; `SCORED_COLUMNS` inherits. A future `BREAKDOWN_DIMENSIONS` could add `agent_key` (optional).
- `run_params.py`: `golden_dataset`, `judge_llm_id`, the 4 result dataset names, `concurrency`,
  `language` stay global keys (now editable from Settings). The `question_filter` category filter is
  RETIRED for membership (superseded by the agent tag); keep reading it tolerantly for back-compat but
  the launcher no longer writes it. Add a normalized `agents` catalog read (already present).
- `views.py` (benchmark_webapp, pure): `agent_benchmarks_view` (per agent), `benchmark_detail_view`
  (derived per-mode status, ledger, runnable), `golden_tag_view` (filtered), `settings_view`,
  `build_launch_request`, `validate_benchmark_name` (per agent), `validate_settings`. Remove
  `build_config_object` / config_view membership pieces.

## 8. DSS I/O (`benchmark_webapp/dss.py`)

- Variable RMW under `_REGISTRY_LOCK` for every mutation (create, delete, modes, redo, connect agent,
  cache discovery, settings, run_request). The variable is one JSON blob; concurrent edits must
  read-modify-write under the lock (no lost updates), consistent with the existing code.
- Agent discovery: best-effort via the Dataiku API (verify the exact call on the instance, section 15);
  cache into `agents`; never call on every page load.
- Golden `agent_key` column bootstrap: when saving a tag and the golden dataset lacks the `agent_key`
  column, evolve the managed dataset schema (add the column) before the write, so a freshly recreated
  golden does not hard-stop. Golden writes stay via the Dataset API (no raw SQL), append/RMW only.
- Settings save: validate the golden dataset name not just for existence but for the REQUIRED schema
  (`question`, `reference_answer`, and tolerate-or-bootstrap `agent_key`). Inline error if invalid;
  never auto-create, never fail silently. Result dataset renames show a warning that prior rows live in
  the previously named datasets (the view re-points, it does not move data).
- Hard delete: pop the benchmark from the registry; scored rows are left in place.
- `run/reset`: only clears `run_request` when the scenario is verifiably idle (last run finished /
  errored), so it cannot abort a live run.

## 9. Robustness decisions from the adversarial review (folded in)

1. Tested state is DERIVED from scored, never written to the variable (section 3d, 8). The variable holds
   only {benchmarks, redo sets, run_request, settings, agents catalog}.
2. Status is per (question, mode); adding a mode makes members pending for that mode (3d, 3e).
3. The golden tag = logical `agent_key` (rename/deployment proof); the concrete `agent_id` + `project_key`
   are snapshotted on the benchmark and catalog (3a, 3b, 3c).
4. Stuck `run_request` has an escape hatch: `POST /api/run/reset` + a "A run looks stuck. Reset run
   state?" affordance shown only when the scenario is idle but `run_request` is set (section 10).
5. Settings validates the golden SCHEMA, not just existence; the `agent_key` column is bootstrapped (8).
6. `New benchmark` is gated to never produce an empty, non-runnable benchmark (decision 7).
7. Re-run shows a confirm panel with scope (questions x modes) + a rough cost note before launching,
   especially for Claude across a large set (the $50/user ethos).
8. Discovery is cached, not run on every load; rail pending dots are computed cheaply (from the light
   summary / on agent select), not by fanning out SQL per agent on load (instance safety).
9. The "pending" overload is resolved: the ledger shows `tested . pending . redo` as three counts; the
   button reads `Run pending (N)` with N = pending + redo and a helper that spells the split.
10. Two language controls are disambiguated: header `EN | FR` = interface language; Settings
    `Run language` = the language the benchmark runs questions in.

## 10. Run lifecycle

Launch writes `run_request {benchmark_id, launch_mode}` then fires the single-flight scenario
(`Prevent concurrent executions` is the authoritative cross-process guard). The launcher polls
`run/status` (`scored / total` for the live run_id, degrade to elapsed). Leaving the page does not stop
the run; reopening re-detects the live run from `run_request`.

Redo clearing: a member's redo flag is cleared only AFTER all its (q, mode) cells for the run have landed
a new scored row (not at launch time), so a crashed scenario never loses the redo intent nor leaves a
question reading "tested" with a stale result. (Reconciled on the launcher's status poll, idempotent.)

Stuck-run reset: if `run_request` is set but the scenario is idle (finished/errored), the UI surfaces
`Reset run state` -> `POST /api/run/reset` clears `run_request`. Never clears a live run.

## 11. Ripple / consequent changes and out-of-scope

In scope (the launcher engine): `benchmark/registry.py`, `schemas.py`, `run_params.py`,
`benchmark_webapp/views.py` + `dss.py`, the launcher webapp (`script.js`, `style.css`, `body.html`),
and the 3 scenario steps where resolution feeds the run (step 1 consumes the per-mode plan; steps 2/3
already carry `RAW_COLUMNS`, so `agent_key` flows through).

Consequent (keep consistent):
- Results webapp: already benchmark-aware (selector + per-mode summary). It needs the golden `agent_key`
  only if it adds a per-agent filter; the per-mode status is already its grain. Minimal change.
- Plugin consultation tab (`benchmark_view/` + Vue): reads scored by intersection of columns, so it
  keeps working with the new optional `agent_key` (already tolerant). No required change this session; a
  per-agent selector is a future nicety.

Out of scope: Suggestions tab, Review/override tab (unchanged), the judge/scoring/capture engine, the
Results webapp visual redesign, the plugin consultation redesign.

## 12. Migration / clean slate

The user has wiped all datasets and benchmarks, so this starts clean:
- The recreated golden dataset gets the `agent_key` column (bootstrapped on first tag save, or added when
  the golden is rebuilt by the import flow).
- The `benchmark` variable starts `{ "benchmarks": {}, "run_request": null, "agents": [] }` plus the
  global settings.
- Legacy rows (no `agent_key`, old benchmark entities with a `questions` map) are tolerated: parsing
  ignores the obsolete `questions` map; an untagged golden row simply belongs to no benchmark.

## 13. Non-negotiables (unchanged)

SQL parametrized, COMMIT after write, READ + APPEND only on the shared connection, no generic SQL route.
Instance safety: bounded concurrency + per-call timeout; small variable RMW under the lock; the only
added reads are the bounded discovery (cached) + the existing scored read + a bounded `information_schema`
for schema validation. No em dash or en dash anywhere (EN and FR strings). Code/comments in English.
Charter-compliant UI. DEV plugin packaging only when the plugin is touched (it is not, this session).
Pure modules never raise (degrade to an empty view, not a 500); new pure code is unit-tested.

## 14. Testing

- Pure: `registry.resolve_to_run` per-mode (append skips tested cells, includes redo + new-mode cells;
  full = all cells), `done_cells` / `pending_cells`, `validate_benchmark_name` per agent, `delete`,
  `set_redo` / `reset_redo`, golden `agent_key` normalize, `validate_settings`, view-models.
- Webapp dss: variable RMW under lock, discovery cache + degrade, golden column bootstrap, settings
  schema validation, hard delete leaves scored rows, run/reset only when idle.
- Frontend (node:test where pure): rail/detail state machine, the single `runnable` counter driving the
  button + helper, gated create, ledger split, evolution rendering.
- Run command: `python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t
  OWIsMind_LAB/project-library/python`.

## 15. Open items / verify on the instance

- Agent discovery API: confirm the exact Dataiku call that lists agents (LLM Mesh `agent:` ids) per
  project on this instance; if unavailable, the manual-add fallback is the path (do not assert it works
  without proof; backend observed = Python 3.9.23).
- Scenario async launch method (`run_scenario` / `run`): confirm the async launch used by the existing
  launcher still applies.
- Golden schema evolution: confirm adding the `agent_key` column to the managed golden dataset via the
  Dataset API behaves as expected on the instance.
