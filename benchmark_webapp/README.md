# benchmark_webapp - the OWIsMind_LAB benchmark webapps (results + launcher)

Two Dataiku **Standard webapps** (HTML / CSS / JS + Python backend) in the `OWIsMind_LAB`
project, next to the benchmark Flow + the `benchmark` project library. They are the control +
restitution surfaces of the benchmark. No plugin, no Vite, no zip: edited in the DSS browser.

Design contract: `docs/superpowers/specs/2026-06-25-benchmark-integration-design.md` (see the
"REVISION 2026-06-26b" section: the surface is SPLIT into two webapps).

> **Deploiement pas a pas (le guide a suivre) : [`DEPLOY_GUIDE.md`](DEPLOY_GUIDE.md).** Il prend
> par la main pour tout mettre en place (le plugin de capture + les 2 webapps LAB + permissions +
> variable + tests), avec les explications. Ce README-ci reste la reference courte (mapping
> fichiers, permissions, caveats).

## Two webapps, on purpose

- **Results** (`results/`) - PUBLIC consultation, READ-ONLY. Plain-language, trust-building
  display of the latest (or any) run: a clear confidence verdict, accuracy, response time,
  cost, what to double-check, per-configuration and per-topic and per-question views. Built so a
  NON-technical person understands everything. Its backend has NO write route at all.
- **Launcher** (`launcher/`) - the internal config + launch + golden management tool. A REAL
  FORM (pick agents / modes / question filter / concurrency / language, no JSON editing), a
  Launch button, a **Questions** card to manage the golden set directly (create / edit /
  enable-disable / delete a question with its expected answer + anchor), and a panel to review
  user-suggested questions and promote them. Keep this webapp's URL to the people who run
  benchmarks; the public consults the Results app.

The golden-management routes (`api/golden`, `api/golden/save`, `api/golden/delete`) and the run
history both write the LAB's OWN managed Flow datasets via the Dataset API only - see SQL safety
below. Each run now APPENDS (keyed by `run_id`) instead of overwriting, so Results browses history;
an optional `benchmark.history_keep_runs` caps it.

Splitting into two webapps is how the launch surface stays out of consultation users' hands -
no in-app admin gating needed.

Both webapps are **bilingual: English default, French via a toggle** (persisted client-side).
Code + comments are English.

## SQL safety (READ + APPEND ONLY)

The LAB project's SQL connection can see EVERY table on it (including the OWIsMind webapp's
chat / suggestion tables). The benchmark webapps are strict (all dataiku/SQL I/O is in the
single module `benchmark_webapp/dss.py`):
- The ONLY raw SQL on the shared connection is `dss.read_pending_suggestions`: a bounded,
  READ-ONLY `SELECT` (read-only + statement_timeout pre-queries, explicit column list, a guarded
  physical table name, `status='pending'` literal, `LIMIT 500`).
- NO UPDATE / DELETE / DROP / TRUNCATE / INSERT / raw DML on the shared connection, anywhere.
- The only WRITES are rewrites of the LAB's own Flow datasets (the golden, via promotion AND the
  Questions card; the result datasets, via the run-history append; a promoted-ids log) through the
  dataiku Dataset API, never raw SQL. Every write path uses a RAISING existing-read (a transient
  read failure aborts rather than truncating) and the golden writes share one process lock.

## Repo layout (what goes where in DSS)

| Repo file | DSS destination |
| --- | --- |
| `benchmark_webapp/views.py` (+ `__init__.py`) | LAB **project library** `python/benchmark_webapp/` (PURE, unit-tested). |
| `benchmark_webapp/dss.py` | LAB **project library** `python/benchmark_webapp/` (the single dataiku/SQL I/O module). |
| `benchmark_webapp/results/{body.html,style.css,script.js}` | the RESULTS Standard webapp's HTML / CSS / JS panes |
| `benchmark_webapp/results/backend.py` | the RESULTS Standard webapp's Python backend pane |
| `benchmark_webapp/launcher/{body.html,style.css,script.js}` | the LAUNCHER Standard webapp's HTML / CSS / JS panes |
| `benchmark_webapp/launcher/backend.py` | the LAUNCHER Standard webapp's Python backend pane |
| `benchmark_webapp/*/preview.html` | DEV ONLY - offline visual QA (mock data). Do NOT paste into DSS. |

The repo is the source of truth (same model as `benchmark/`). Re-collect changed files when they
evolve. Run the pure tests first: `python3 -m unittest discover -s benchmark_webapp/tests`.

## Setup (one time)

1. **Project library**: copy `benchmark_webapp/views.py`, `benchmark_webapp/dss.py` (+
   `__init__.py`) into the LAB project library under `python/benchmark_webapp/` (they import
   `benchmark.run_params` / `benchmark.schemas` / `benchmark.config`, already LAB libraries).
2. **Create the two webapps**: `OWIsMind_LAB` -> Code -> Webapps -> New -> **Standard**, twice.
   For each, paste its `body.html` / `style.css` / `script.js` / `backend.py` into the four panes.
   Name them clearly (e.g. "Benchmark - Results" and "Benchmark - Launcher").
3. **Permissions** (the webapp runs as your identity): both need READ on the result datasets
   (automatic, same project). The LAUNCHER additionally needs WRITE on the LAB project (save the
   config + launch the scenario) and - for the Suggestions panel - READ on the `SQL_owi`
   connection. The RESULTS webapp needs only read.

## Enabling the suggestion review (in the Launcher)

The Launcher reads the OWIsMind webapp's user-suggestion table cross-project (read-only) and
records what it promotes LAB-side, so a suggestion is never promoted twice.

1. In the OWIsMind webapp Admin -> **Storage**, copy the exact physical table name shown for
   `golden_suggestions` (e.g. `OWISMIND_DEV_owismind_webapp_golden_suggestions_v1`).
2. In `OWIsMind_LAB`, create an empty managed dataset `benchmark_suggestions_promoted`.
3. In `OWIsMind_LAB` -> Variables -> **Local variables**, add the `suggestions` block to the
   `benchmark` object:

```json
"suggestions": {
  "connection": "SQL_owi",
  "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",
  "promoted_dataset": "benchmark_suggestions_promoted"
}
```

When the block is absent, the Launcher's Suggestions panel reports "not configured" (no error).

## Prerequisite (data safety): golden_dataset must be a STANDALONE managed dataset

Promotion appends user-suggested questions INTO `benchmark.golden_dataset` (a full read +
de-duped re-write via the Dataset API). **`golden_dataset` MUST be a standalone managed dataset
with NO upstream recipe.** If it were a recipe OUTPUT (e.g. a `prepare` recipe over a raw
source), a routine recipe rebuild would regenerate it from the source and silently ERASE every
promoted question. The benchmark must READ this same dataset, so point `benchmark.golden_dataset`
at the human-authored, standalone golden (not a recipe output). The promoted answers also survive
in the OWIsMind suggestion table (never written back), so a mistaken erase is recoverable by
clearing `benchmark_suggestions_promoted` and re-promoting, but treat the standalone constraint as
a hard prerequisite.

## Caveats (verify on instance)

- The exact dataikuapi scenario method (`run_scenario` vs `run`, `get_current_run` vs
  `get_last_runs`) varies by DSS version; the launch/status endpoints are defensive and degrade
  to "launch from the scenario UI" if unsupported. ALSO enable **"Prevent concurrent executions"**
  on the `Run_Benchmark` scenario (the authoritative cross-process single-flight; the launcher's
  in-process RUN_LOCK only guards one backend process).
- Promotion is serialized by an in-process lock and reads the existing golden with a RAISING read,
  so a transient read failure ABORTS (returns 500) rather than overwriting the golden. The
  "already promoted" signal is the golden's `question_id`s (source of truth), so the
  `benchmark_suggestions_promoted` dataset is only a best-effort audit log (never relied on for
  correctness, never truncated on a read failure). For a very large golden set, switch the rewrite
  to an append writer.
- The Launcher does NOT write back to the OWIsMind suggestion table (read-only cross-project),
  so a user's "my suggestions" status stays "pending" in v1.
- The public Results app reads the scored detail with column projection (the heavy answer / SQL /
  artifact blobs are never loaded), so consultation never materializes that data into RAM.
