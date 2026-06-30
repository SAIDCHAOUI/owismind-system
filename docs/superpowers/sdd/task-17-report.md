# Task 17 - Dispatch 2: Benchmark Detail Screen (Screen 4)

**Date:** 2026-06-30
**Status:** COMPLETE - all 4 gates passed, Playwright-verified

## What was implemented

Screen 4 = Benchmark Detail view, entered from [data-bm-open] on the Agent Detail screen.
Navigation: level==="benchmark" in the route state.

### New state slot

`S.benchDetailState` with fields: `loaded, loadError, detail, editModes, editModesValue, deleteConfirm, running, runMsg`

### New DICT keys (9)

`bd4.col.q / .cat / .redo`, `bd4.editModes / .editSave / .modesOk / .modesError`, `bd4.runDone / .runError`

### New MOCK shape for bench_detail

- `agent` is now an object `{agent_key, agent_label, project_key, agent_id}`
- `questions[].cells = [{mode, status, verdict}]`
- `questions[].redo` (bool flag, replaces old `include_next`)
- `ledger = {tested, pending, redo}` + `runnable` (integer)
- `mockSyncBench(bid)` rewritten to compute all counts from cells+redo

### New MOCK handlers

- `benchmark/modes` - updates modes, adds pending cells for new modes, drops removed modes
- `benchmark/redo` - flips `q.redo`, calls `mockSyncBench`
- `benchmark/launch` - sets `run_id`, marks running; `run/status` completes after 2 ticks

### Dead code removed

`benchModalHtml()`, `configPanelHtml()`, `asideHtml()` bodies removed from script.js.
All `wireStatic()` wiring for `bnClose / bnCancel / bnCreate / bnSeedAll / bnSeedEmpty` removed.
`setStatus(S.bench.running ? ...)` call removed from `render()`.

### `navigateTo()` extended

Handles level==="benchmark": resets `S.benchDetailState`, calls `loadBenchmarkDetail4(bid)`.

### 3-part breadcrumb

When level==="benchmark": Agents (clickable, goes home) / AgentLabel (clickable, goes agent) / BenchmarkName (plain text).

### `renderDetailContent()` routing

Dispatches to `renderBenchmarkDetail()` for level==="benchmark".

### New functions (11)

| Function | Role |
|---|---|
| `loadBenchmarkDetail4(bid)` | fetch + stale guard + render |
| `renderBenchmarkDetail()` | build HTML + wire |
| `buildBenchmarkDetailHtml()` | full HTML: meta, ledger, run status, actions, modes form, delete confirm, questions table |
| `wireBenchmarkDetail()` | all event wiring |
| `bench4RecomputeLedger(det)` | client-side recompute for optimistic updates |
| `bench4Launch(launchMode)` | POST benchmark/launch + toast + poll |
| `bench4PollErrors` + `bench4Poll()` | 2500ms cadence, stale guard, auto-stop |
| `bench4EndRun(msg)` | clear running, set runMsg, re-render |
| `bench4Redo(questionId, value)` | optimistic flip + revert on POST failure |
| `bench4Delete()` | POST delete + toast + navigate to agent + reload |

### CSS: new `.bd4-*` classes

`.bd4`, `.bd4-loading`, `.bd4-meta`, `.bd4-ledger`, `.bd4-run-status` (+3 modifiers),
`.bd4-actions`, `.bd4-sec-actions`, `.bd4-run-hint`, `.bd4-edit-modes`, `.bd4-edit-actions`,
`.confirm-row / .confirm-msg / .confirm-btns`, `.bd4-table-wrap / .bd4-table`,
column-width helpers, chip classes (`--ok / --miss / --pending`), dark overrides.

## Gates

| Gate | Command | Result |
|---|---|---|
| 1 - Syntax | `node --check script.js` | PASS (no output) |
| 2 - Tests | `node --test test/journey.test.js` | PASS (5/5) |
| 3 - Dash scan | Python byte count | PASS (0 em/en dash) |
| 4 - Playwright | Preview QA | PASS (0 JS errors) |

## Playwright interactions verified

- Screen 4 renders from [data-bm-open] click (3-part breadcrumb, meta, ledger, table)
- Run button label/count from `Journey.runnableLabel()` - showed "Run pending (4)"
- Redo toggle (a_revenue001): ledger instantly updated 0 done/2 pending/2 redo, button changed to "Run pending (6)"
- Edit modes form: opens with current modes pre-selected (Smart=on, Pro=off, Claude=on)
- Delete confirm (4g): inline named confirm, NOT `window.confirm`; delete navigates to agent + toast "Benchmark deleted."
- Run launch: toast "Benchmark launched.", polling completes, status "Run complete." with --ok class
- FR toggle: "Modifier les modes" / "Supprimer" / "A refaire" / "Categorie" all correct
- 0 JS console errors throughout (only expected favicon 404)
