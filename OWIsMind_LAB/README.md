# OWIsMind_LAB (the benchmark project)

**This whole folder mirrors ONE separate Dataiku project: `OWIsMind_LAB`.**

It is NOT the plugin. The plugin (the Vue webapp + Flask backend the users actually chat with)
lives in `Plugin/owismind/` and runs in the projects `OWISMIND_DEV` / `OWISMIND_PROD_V1`. The
Code Agents live in `dataiku-agents/OWISMIND/{OWISMIND_DEV, OWISMIND_PROD_V1}/`. `OWIsMind_LAB`
is a **third, dedicated project** whose only job is to **benchmark / evaluate the agents** of the
plugin projects (accuracy, latency, cost, per agent AND per mode) and to collect + promote the
golden questions users suggest from the chat.

The repo layout below is a 1:1 mirror of how the project is organized inside Dataiku, so what you
see in VS Code maps directly onto what you see in DSS.

```
OWIsMind_LAB/                              = the DSS project "OWIsMind_LAB"
  README.md                               <- you are here (the map)
  local-variables.example.json            = the project Local variable `benchmark` (the WHOLE config)

  project-library/python/                 = DSS  > Code (</>) > Libraries > python/
    benchmark/                            imported as `from benchmark import ...`  (the run engine)
      agent_capture.py                    rebuild the agent's FULL answer (text+SQL+rows) from the footer
      agent_runner.py                     the agent x mode matrix (bounded concurrency, latency/tokens/cost)
      judge.py  scoring.py                deterministic objective anchor + structured LLM judge + scoring
      config.py  run_params.py            modes (Smart/Pro/Claude), judge id + the single config resolver
      history.py  schemas.py              run-history append + the lean-9 golden schema
      dss_steps/                          the bodies pasted into the scenario steps (see scenario below)
        step_run_matrix.py  step_judge.py  step_aggregate.py  history_io.py
      tests/                              pure unit tests (no DSS)
      SETUP_GUIDE.md  README.md  GOLDEN_IMPORT_PROMPT.md

    benchmark_webapp/                     imported as `from benchmark_webapp import ...` (the 2 webapps' shared backend)
      views.py                            PURE restitution + validation + promotion mapping (unit-tested)
      dss.py                              the SINGLE dataiku/SQL I/O chokepoint (READ + APPEND only)
      tests/
      DEPLOY_GUIDE.md  README.md

  webapps/                                = DSS  > Code (</>) > Webapps  (two STANDARD webapps)
    benchmark_launcher/                   = webapp "benchmark_launcher" : config + launch + golden CRUD + suggestions review
      body.html  style.css  script.js  backend.py   (preview.html = local QA only, never pasted into DSS)
    benchmark_results/                    = webapp "Benchmark_results" : PUBLIC, read-only, plain-language results
      body.html  style.css  script.js  backend.py   (preview.html = local QA only)
```

## Repo file  ->  DSS object

| In this repo | Is, inside the `OWIsMind_LAB` DSS project |
|---|---|
| `project-library/python/benchmark/` | Libraries > `python/benchmark/` (imported `from benchmark import ...`) |
| `project-library/python/benchmark_webapp/` (`views.py`, `dss.py`, `__init__.py`) | Libraries > `python/benchmark_webapp/` |
| `project-library/python/benchmark/dss_steps/step_run_matrix.py` | Scenario `Run_Benchmark`, step 1 "Run matrix" (Custom Python) |
| `project-library/python/benchmark/dss_steps/step_judge.py` | Scenario `Run_Benchmark`, step 2 "Judge" |
| `project-library/python/benchmark/dss_steps/step_aggregate.py` | Scenario `Run_Benchmark`, step 3 "Aggregate" |
| `webapps/benchmark_launcher/{body.html,style.css,script.js,backend.py}` | Webapp "benchmark_launcher" (Standard) |
| `webapps/benchmark_results/{body.html,style.css,script.js,backend.py}` | Webapp "Benchmark_results" (Standard) |
| `local-variables.example.json` | Project menu > Variables > Local variables (the `benchmark` object) |

Managed datasets the scenario reads/writes (created during setup, NOT in the repo):
`golden_questions_v1_prepared` (input) -> `benchmark_runs_raw` -> `benchmark_runs_scored` ->
`benchmark_summary` + `benchmark_breakdown`, plus `benchmark_suggestions_promoted` (promotion log).

## v2: named per-agent benchmarks + append mode (2026-06-30)

Spec: `docs/superpowers/specs/2026-06-29-benchmark-v2-append-mode-design.md`.

The benchmark is no longer "set all the questions, run them all, every launch re-runs everything". Now:

- A **benchmark** is a NAMED, unique campaign pinned to ONE agent (unique `benchmark_id` + name). Runs
  ACCUMULATE into the same benchmark (**append mode**): a launch runs only the not-yet-done questions;
  the global score is over ALL questions ever added, using the LATEST attempt of each. You grow a
  benchmark question by question up to a statistically meaningful size. Buttons: **Run pending**
  (append), **Re-run entire benchmark** (full = new attempt for every question -> evolution), and
  **New benchmark** (a fresh, unlinked campaign). A "redo at next run" flag re-includes a done question.
- **No new dataset**: the registry (benchmarks) + per-benchmark question membership + the redo flags
  live in the `benchmark` project variable (`benchmarks` map + `run_request`); the launcher writes them.
- Result tables gained `benchmark_id`, `benchmark_name`, `attempt_no`; the golden + raw/scored gained
  `expected_sql` + `expected_tool` (a soft signal to the judge + training data) and scored gained
  `actual_tools`. `benchmark_summary` / `benchmark_breakdown` are now **benchmark-level** (one block per
  benchmark, over the latest attempt of each question), keyed by `benchmark_id` (not `run_id`).
- The Results app + the plugin consultation select BY BENCHMARK (not by run) and show per-question
  EVOLUTION (attempt history + improved/regressed delta) and expected-vs-actual SQL/tool.

What to do in DSS to deploy v2: re-collect the `benchmark` library (NEW `registry.py`; changed
`schemas.py` / `run_params.py` / `scoring.py` / `judge.py` / `agent_runner.py` / the 3 `dss_steps/*`),
re-collect `benchmark_webapp` (`views.py` + `dss.py`), re-paste the launcher panes (new "Benchmarks"
tab) and the results panes (benchmark selector). In the `benchmark` variable add `"benchmarks": {}` +
`"run_request": null` (both empty; see `local-variables.example.json`). A fresh **run** materializes
the new columns on the result datasets (managed datasets auto-evolve their schema on write); legacy
pre-v2 rows are tolerated everywhere. The plugin consultation reads the new columns when the table has
them and degrades gracefully on an un-migrated table (it reads the intersection of the live columns).

## How it connects to the rest of the repo

- The run engine calls the **orchestrator agent cross-project** (in `OWISMIND_DEV` / `OWISMIND_PROD_V1`)
  via LLM Mesh; the agent id + project are config, in the `benchmark` variable (`agents[]`).
- The Launcher's "Suggestions" tab **reads cross-project, read-only** the plugin's user-suggestion
  table (`webapp_golden_suggestions_v1`, in the plugin project) over the shared SQL connection. The
  exact physical table name to read goes in the `benchmark.suggestions.table` config (copy it from the
  plugin's Administration > Storage > `golden_suggestions` row).

## Deploy / setup

The repo is the source of truth: edit here, then re-collect into DSS. Two guides, in order:

1. **`project-library/python/benchmark/SETUP_GUIDE.md`** - stand up the run engine (library, scenario,
   datasets, the `benchmark` variable, a first run + dashboard).
2. **`project-library/python/benchmark_webapp/DEPLOY_GUIDE.md`** - the full end-to-end deploy in 3 parts
   (the agents, the plugin's capture feature, and these two LAB webapps).

## Tests (pure, no DSS, no install)

One command from the repo root runs both packages' unit tests with the library root on the path:

```bash
python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python
```
