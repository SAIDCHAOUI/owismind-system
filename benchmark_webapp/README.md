# benchmark_webapp - the OWIsMind_LAB benchmark control + restitution webapp

A Dataiku **Standard webapp** (HTML / CSS / JS + Python backend) that lives in the
`OWIsMind_LAB` project, next to the benchmark Flow + the `benchmark` project library. It is
the ADMIN pole of the benchmark: read the results, configure + launch a run, and promote the
user-suggested questions into the golden set. No plugin, no Vite, no zip: it is edited in the
DSS browser.

Design contract: `docs/superpowers/specs/2026-06-25-benchmark-integration-design.md`.

## What it does (3 tabs)

- **Resultats** : the latest (or any) run. Global accuracy %, question count, configurations
  tested, total cost, needs-review count; an agent x mode comparison (accuracy / latency
  p50-p95 / cost); accuracy per category; the per-question detail (with a "needs review only"
  filter). All read directly from `benchmark_summary` / `benchmark_breakdown` /
  `benchmark_runs_scored` (same project).
- **Lancer** : the resolved config + a JSON editor for the `benchmark` project variable
  (zero hardcode, validated before write), and a button that launches the `Run_Benchmark`
  scenario (async, single-flight) with a status poll.
- **Suggestions** : the pending user-suggested questions (read cross-project, read-only) and
  a "Promote" action that appends accepted ones to the golden dataset.

## Repo layout (what goes where in DSS)

| Repo file | DSS destination |
| --- | --- |
| `benchmark_webapp/views.py` (+ `__init__.py`) | LAB **project library** `python/benchmark_webapp/` (next to `benchmark/`). PURE, unit-tested. |
| `benchmark_webapp/backend.py` | the Standard webapp **Python backend** pane |
| `benchmark_webapp/body.html` | the Standard webapp **HTML** pane (body content) |
| `benchmark_webapp/style.css` | the Standard webapp **CSS** pane |
| `benchmark_webapp/script.js` | the Standard webapp **JS** pane |
| `benchmark_webapp/preview.html` | DEV ONLY - offline visual QA (mock data). Do NOT paste into DSS. |

The repo is the source of truth (same model as `benchmark/`). Re-collect the changed files
when they evolve.

## Setup (one time)

1. **Project library**: copy `benchmark_webapp/views.py` (+ `__init__.py`) into the LAB
   project library under `python/benchmark_webapp/` (it imports `benchmark.run_params`, which
   is already a LAB library). Run the benchmark tests locally first:
   `python3 -m unittest discover -s benchmark_webapp/tests`.
2. **Create the webapp**: `OWIsMind_LAB` -> Code -> Webapps -> New -> **Standard**. Paste
   `body.html` / `style.css` / `script.js` / `backend.py` into the four panes. Save, then open.
3. **Permissions** (the webapp runs as your identity): you need READ on the result datasets
   (automatic, same project), WRITE on the LAB project (to save the config + launch the
   scenario), and - only for the Suggestions tab - READ on the `SQL_owi` connection (the
   cross-project suggestion table lives on it). If you lack LAB write, the config editor save
   and the launch button fail gracefully (edit Local variables + Run the scenario by hand).

## Enabling the Suggestions tab (Lot 3)

The webapp reads the OWIsMind webapp's user-suggestion table cross-project (read-only) and
records what it promotes LAB-side, so a suggestion is never promoted twice.

1. In the OWIsMind webapp Admin -> **Storage**, copy the exact physical table name shown for
   `golden_suggestions` (e.g. `OWISMIND_DEV_owismind_webapp_golden_suggestions_v1`).
2. In `OWIsMind_LAB`, create an empty managed dataset `benchmark_suggestions_promoted` (it
   gets one column `suggestion_id` on first promotion - leave it schemaless / empty).
3. In `OWIsMind_LAB` -> Variables -> **Local variables**, add the `suggestions` block to the
   `benchmark` object:

```json
"benchmark": {
  "agents": [ ... ],
  "modes": ["Smart", "Pro", "Claude"],
  "suggestions": {
    "connection": "SQL_owi",
    "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
    "promoted_dataset": "benchmark_suggestions_promoted"
  }
}
```

When the block is absent, the Suggestions tab simply reports "not configured" (no error). The
`table` value is restricted to a plain identifier server-side before it is used in the read.

## Caveats (verify on instance)

- The exact dataikuapi scenario method (`run_scenario` vs `run`, `get_current_run` vs
  `get_last_runs`) varies by DSS version; the launch/status endpoints are defensive and
  degrade to "launch from the scenario UI" if the call is unsupported.
- Promotion appends to `golden_questions_v1_prepared` by re-writing it with the new rows
  (de-duped by `question_id`); for a large golden set, switch to an append writer.
- The webapp does NOT write back to the OWIsMind suggestion table (read-only cross-project),
  so a user's "my suggestions" status stays "pending" in v1 (status sync is a future step).
