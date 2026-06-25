# Benchmark integration into the OWIsMind system - design (2026-06-25)

Status: design approved verbally (user delegated full autonomous implementation overnight).
Builds on the frozen benchmark contract `2026-06-24-agent-benchmark-evaluation-design.md`.

## 1. Goal

Turn the standalone benchmark (datasets + project library + scenario in `OWIsMind_LAB`)
into a first-class part of the OWIsMind SYSTEM, with two control poles:

1. A USER pole (everyone, not admins): from a chat answer or from a dedicated page,
   users suggest benchmark questions WITH the answer they know is correct, growing the
   golden set collaboratively over time.
2. An ADMIN pole (engineer): one place to configure, launch and read a benchmark, with
   zero hardcode (every parameter is a setting, never a code edit).

## 2. The decision that shapes everything: the two poles live in different places

- The webapp (Vue plugin) is deployed in `OWISMIND_DEV` / `OWISMIND_PROD_V1`. It is where
  the chat, the answer footer menu and the users are. The USER suggestion surface belongs
  HERE (it is product).
- The benchmark (datasets, library, scenario, `benchmark` project variable) lives in the
  separate `OWIsMind_LAB` project. The ADMIN control + restitution surface belongs THERE,
  as a STANDARD DSS webapp (HTML/CSS/JS + Python backend) inside `OWIsMind_LAB`: it reads
  the 5 result datasets directly (same project), reads/writes the `benchmark` variable, and
  launches the `Run_Benchmark` scenario. No Vite, no zip, no plugin build, no body.html
  rewire: it is edited in the DSS browser. This keeps the heavy plugin build chain out of
  the engineer tool, and keeps an internal eval tool out of the end-user app.

So: NOT a Dash app (it needs a code env; charter styling is imperfect), NOT a native DSS
dashboard (it cannot edit the `benchmark` variable, so it is restitution-only), NOT a new
webapp inside the plugin (it inherits the build heaviness + cross-project reads). A standard
DSS webapp in the LAB is the lightest, most controllable, dependency-free option.

The work splits into three independent lots:
- Lot 2 - user suggestion capture (Vue plugin). Built + packaged (DEV) + tested.
- Lot 1 - benchmark webapp (repo artifacts for a LAB standard webapp). Pure-logic tested.
- Lot 3 - promotion bridge (inside Lot 1): admin reviews user suggestions and promotes
  accepted ones into the golden dataset.

## 3. Lot 2 - user suggestion capture (Vue plugin)

### 3.1 Data model: `webapp_golden_suggestions_v1` (new owner-stamped table)

A brand new `_v1` table (no ALTER), created lazily on first write, mirroring
`webapp_artifacts_v1` (owner-stamped, parametrized, COMMIT, bounded). Columns:

```
suggestion_id        TEXT PRIMARY KEY,   -- uuid4 hex (server-generated)
user_id              TEXT,               -- the suggester (owner-scope key)
source               TEXT,               -- 'chat' | 'manual'
exchange_id          TEXT,               -- nullable: source chat exchange
session_id           TEXT,               -- nullable
agent_key            TEXT,               -- nullable: opaque logical key of the answering agent (chat)
question             TEXT,               -- the question (authoritative; from the exchange for chat)
agent_answer         TEXT,               -- nullable: the agent's answer (chat)
answer_is_correct    BOOLEAN,            -- nullable: user verdict (chat). NULL for manual
reference_answer     TEXT,               -- the correct/expected answer (user-supplied)
missing_explanation  TEXT,               -- nullable: what was wrong/missing (when verdict = No)
expected_value       TEXT,               -- nullable: crisp anchor fact (optional)
expected_value_type  TEXT,               -- nullable enum: numeric|currency|date|string|list
category             TEXT,               -- nullable: theme (revenus, tickets, ...)
language             TEXT,               -- 'fr' | 'en'
generated_sql_json   TEXT,               -- nullable: captured SQL of the chat answer (proof)
status               TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected (review state)
created_at           TIMESTAMP NOT NULL DEFAULT now(),
reviewed_by          TEXT,               -- nullable
reviewed_at          TIMESTAMP           -- nullable
```

Index `(user_id, created_at DESC)` for the "my suggestions" read, `(status, created_at DESC)`
for the admin / LAB cross-project read. The columns are a SUPERSET of the golden lean-9
schema, so an accepted row maps cleanly onto a golden row (question_id minted at promotion).

### 3.2 Storage module `storage/suggestions.py` (mirrors artifacts.py)

- `save_suggestion(user_id, fields)` - owner-stamped INSERT + COMMIT, bounded strings,
  best-effort? NO: a suggestion is a deliberate user action, so a failure returns a clean
  error (unlike best-effort artifacts). statement_timeout guard on the write.
- `list_my_suggestions(user_id, limit)` - owner-scoped read, read-only + timeout, bounded
  LIMIT, newest first.
- No admin read/review here: the admin pole is the LAB webapp (Lot 1/3), which reads this
  table cross-project read-only. Keeps a single admin surface.

### 3.3 Server-side chat reader `chat_v5.read_exchange(user_id, exchange_id)`

For a from-chat suggestion the backend reconstructs the AUTHORITATIVE question + agent
answer + agent_key + generated_sql from the persisted exchange (owner-scoped), instead of
trusting client-sent text. Returns the `_COLUMNS`-shaped row (one exchange) or None.

### 3.4 Validation `security/validation.py`

- `validate_suggestion_manual(payload)` -> dict (question, reference_answer required;
  expected_value/type/category/language optional + bounded; enums checked).
- `validate_suggestion_from_chat(payload)` -> (exchange_id, answer_is_correct,
  reference_answer, missing_explanation, category). reference_answer required only when
  answer_is_correct is False (a "Yes" suggestion stores the agent answer as the reference).

### 3.5 Routes (`api/routes.py`)

All authenticated; WRITE routes blocked while impersonating (read-only), mirroring feedback.
- `POST /benchmark/suggest` - manual new Q/A (source 'manual').
- `POST /benchmark/suggest-from-chat` - keyed by exchange_id; backend reads the exchange
  owner-scoped, stores question + agent_answer + agent_key + sql + the user verdict.
- `GET  /benchmark/suggestions` - the caller's own suggestions (owner-scoped) + status.

### 3.6 Frontend

- `components/chat/MessageAgent.vue`: add one `moreItems` entry
  `{ key:'benchmark', label:t('msg.suggest_benchmark'), icon:'bookOpen' }` and a
  `key==='benchmark'` branch in `onMoreSelect` that opens a new modal.
- `components/chat/BenchmarkSuggestModal.vue` (new, modeled on FeedbackModal): shows the
  question + agent answer (read-only, from client memory), a Yes/No dial "Is the agent
  answer correct?", and when No a reference-answer textarea + a "what is missing" textarea
  + optional category. Submits via the service keyed by exchange_id.
- `views/BenchmarkSuggestView.vue` (new, ALL users, route `/benchmark`, no admin guard):
  a PageShell page = a form to propose a brand-new Q/A from scratch + a list of the user's
  own suggestions with their status. Reuses the charter.
- `router/index.js`: add `/benchmark` (no `requiresAdmin`).
- `components/shell/Sidebar.vue`: add a primary nav RouterLink to `/benchmark` (all users).
- `services/backend.js`: `suggestBenchmarkManual`, `suggestBenchmarkFromChat`, `fetchMySuggestions`.
- `i18n/extra.js`: `msg.suggest_benchmark` + a `bench.*` block (fr + en).

## 4. Lot 1 - benchmark webapp (standard DSS webapp in OWIsMind_LAB)

Repo source = new `benchmark_webapp/` package (the same "repo is the source of truth,
recolled into DSS" model as `benchmark/`). Pasted into a STANDARD webapp's four panes
(HTML / CSS / JS / Python backend). Reuses the `benchmark` project library (`run_params`,
`schemas`, `scoring`, `config`).

### 4.1 Pure view module `benchmark_webapp/views.py` (stdlib only, tested)

- `summary_view(summary_rows, run_id=None)` - shape into KPI tiles + an agent x mode table
  (accuracy %, latency p50/p95, cost/q, error rate, needs-review), filtered to one run.
- `breakdown_view(breakdown_rows, run_id)` - accuracy per category per agent x mode.
- `detail_view(scored_rows, run_id, only_needs_review=False, limit=...)` - the per-question
  table rows (question, verdict, score, objective_match, correct, needs_review, latency,
  cost), the heavy `full_answer`/`generated_sql_json` trimmed.
- `runs_view(rows)` - distinct (run_id, run_timestamp) for the run selector, newest first.
- `validate_config(raw)` - validate an edited `benchmark` variable before write (reuses
  run_params.resolve semantics + explicit error messages for the UI).
- formatting helpers (pct, money, seconds) returning strings.

### 4.2 Backend `benchmark_webapp/backend.py` (DSS standard webapp body, uses `app`)

JSON endpoints (read-only unless noted), bounded + safe:
- `GET  /api/config` - resolved `benchmark` variable + the raw editable JSON + the live
  golden categories/ids (for the filter pickers) + available runs.
- `POST /api/config` - validate + WRITE the `benchmark` project variable (admin/write
  identity required; guarded).
- `POST /api/run` - launch `Run_Benchmark` async (fire-and-forget); refuses if a run is
  already in progress (no double-launch).
- `GET  /api/run/status` - the last scenario run state (running / done / failed).
- `GET  /api/results/summary|breakdown|detail|runs` - read the result datasets (selected
  columns, bounded), shaped by `views.py`.
- `GET  /api/suggestions` - Lot 3: pending user suggestions (cross-project read-only).
- `POST /api/suggestions/promote` - Lot 3: append accepted suggestions to the golden
  dataset + record promoted ids LAB-side.

Instance safety: reads are `get_dataframe()` on the small summary/breakdown (+ column-
selected / limited scored); the scenario launch is async (never blocks the request); a
guard refuses launching when a run is active; cross-project reads are read-only.

### 4.3 Frontend `benchmark_webapp/{body.html, style.css, script.js}`

Two pages (tabs): "Resultats" (restitution) and "Lancer" (config + launch), plus a
"Suggestions" review tab (Lot 3). Charter Orange reapplied by hand (tokens copied into
style.css; square geometry, single rare orange, flat, 1px borders, heavy H1 + 52x4 title-
bar). Charts are hand-rolled inline SVG/CSS bars (no chart dependency). A run selector
fixes a `run_id`; accuracy is shown as a percentage; one fixed color per mode.

## 5. Lot 3 - promotion bridge (inside the LAB webapp)

The LAB webapp reads the plugin's `webapp_golden_suggestions_v1` table cross-project,
READ-ONLY, via the same `SQL_owi` connection (it is the same Postgres schema; the physical
table name is config, not hardcoded - see the `benchmark.suggestions` block below). It shows
the admin the pending suggestions; on "Promote" it appends the selected ones to
`golden_questions_v1_prepared` (mapping suggestion -> golden lean-9 row, minting a stable
`question_id`) and records the promoted suggestion ids in a small LAB dataset
`benchmark_suggestions_promoted` so they are never offered or re-promoted twice. The LAB
webapp does NOT write back to the plugin table (no cross-project write), which avoids
permission and ownership complications. The plugin "my suggestions" view therefore shows
"submitted / pending" in v1 (status sync back to the user is a future enhancement).

## 6. The `benchmark` project variable - new optional blocks (still zero hardcode)

Additive, all optional (defaults keep current behaviour):
```
"suggestions": {
  "connection": "SQL_owi",                 // same connection as the webapp storage
  "table": "OWISMIND_DEV_owismind_webapp_golden_suggestions_v1",  // exact physical table
  "promoted_dataset": "benchmark_suggestions_promoted"            // LAB-side promoted log
}
```
`run_params.resolve` gains a `_resolve_suggestions` that normalizes this block (empty when
absent -> the suggestions tab simply shows "not configured"). Nothing else changes.

## 7. Instance safety (rule #2)

- Plugin: the suggestion table is owner-stamped, parametrized, COMMIT, bounded strings,
  statement_timeout on writes, read-only + timeout on reads (the artifacts.py pattern).
- LAB webapp: result reads are bounded (column-selected / LIMIT on the heavy scored table);
  the scenario launch is async + single-flight (refuses a second concurrent launch); the
  cross-project suggestion read is read-only + bounded; config write needs write identity.
- No new Flow at runtime in the plugin; no generic SQL route; the front never picks a
  table/connection/query.

## 8. Verified vs not (honest)

- Lot 2: built + DEV-packaged + unit tests (backend pure + node frontend). NOT DSS-validated
  (needs the instance): upload DEV zip + restart backend + smoke the menu/page.
- Lot 1 + 3: repo artifacts + pure-logic unit tests + local visual QA on mock data. NOT
  DSS-validated (needs creating the standard webapp in the LAB + permissions + a real run).

## 9. Defaults chosen autonomously (flag for morning review)

- The user suggestion page is ALL-users (the brief said "grand public"). A "Yes" verdict
  stores the agent answer as the reference answer (a positive golden example).
- Promotion does NOT write status back to the plugin table (read-only cross-project); the
  user sees "submitted/pending" not "accepted/rejected" in v1.
- `expected_value`/`expected_value_type` are OPTIONAL on a suggestion (most user
  suggestions will be reference-answer only; the admin can add an anchor at promotion).
- The LAB webapp config write to the `benchmark` variable is gated on the executing
  identity having write on the LAB project; if not, the config tab is read-only (the user
  edits Local variables by hand, as today).

## 10. DSS runbook (after this session, since nothing here touches the instance)

Lot 2 (plugin): build + package DEV -> upload the DEV zip (Uploaded) + RESTART backend
(python-lib changed) -> the `/benchmark` page + the answer "..." menu appear. The table is
created lazily on first suggestion.

Lot 1 + 3 (LAB webapp): in `OWIsMind_LAB` -> Code -> Webapps -> New -> Standard webapp;
paste `body.html` / `style.css` / `script.js` / `backend.py` into the four panes; create the
`benchmark_suggestions_promoted` dataset; add the `benchmark.suggestions` block to the
`benchmark` variable with the exact physical suggestion-table name; grant the LAB execution
identity read on the `SQL_owi` connection (suggestions) and write on the LAB project (config
edit + scenario launch). Then: open the webapp, read the latest run, launch a run, promote
suggestions.
