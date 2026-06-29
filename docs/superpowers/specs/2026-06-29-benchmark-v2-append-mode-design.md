# Benchmark v2: per-agent named benchmarks, append mode, reference SQL/tool

Status: FROZEN design (session 2026-06-29 Run 3). Supersedes the run-centric model of
`2026-06-24-agent-benchmark-evaluation-design.md` and `2026-06-25-benchmark-integration-design.md`
for the IDENTITY + APPEND parts; the capture / judge / scoring engine is reused unchanged except
where stated.

User decisions (AskUserQuestion, 2026-06-29):
- **Reference SQL/tool columns** = a soft SIGNAL to the LLM judge (stored, displayed next to the
  agent's ACTUAL generated SQL/tool, AND passed to the judge as a hint - never a hard scored metric).
- **Benchmark identity** = each agent has a "current" benchmark (auto-created on first launch, unique
  id + unique name). Relaunch runs ONLY the not-yet-done questions and ACCUMULATES into the SAME
  benchmark; the global score is over ALL questions ever added, using the LAST attempt per question.
  Buttons: "re-run entire benchmark" and "new benchmark" (a fresh, unlinked benchmark). Multiple
  benchmarks may coexist per agent.
  - Verbatim: benchmark 123 "said" on the orchestrator with 10 questions -> next day add 5 -> relaunch
    runs only the 5 -> results append into 123 "said" -> it is now a benchmark over 15 questions. Goal:
    grow a benchmark question-by-question up to a statistically meaningful size, not all at once.
- **A new question added to the golden** becomes pending in the CURRENT benchmark only.
- **Scope this session** = LAB webapps (launcher + results) AND the plugin consultation tab.

## 1. The model

A **benchmark** is a named, unique evaluation campaign pinned to ONE agent. It accumulates the
results of one or more **runs** (launches). Its question set grows over time.

- `benchmark_id`  : uuid hex, unique, stable.
- `benchmark_name`: human label, unique (enforced by the launcher).
- pinned agent    : `{agent_key, agent_label, project_key, agent_id, modes}` (copied at creation).
- modes           : the modes this benchmark runs (e.g. `["Smart","Pro","Claude"]`, or `["default"]`
  for a non-mode agent).
- membership      : the golden `question_id`s belonging to this benchmark + a per-question `include_next`
  ("redo at next launch") flag.

A **run** is one launch of a benchmark. It still has a `run_id` (uuid) + `run_timestamp`. Every result
row now also carries `benchmark_id`, `benchmark_name`, and `attempt_no` (1-based, per
`(benchmark_id, question_id, agent_key, mode)`).

### Where state lives (no new DSS datasets)

The registry + membership + the launch request live in the **`benchmark` project variable** (already
read by the steps and read/written by the launcher backend). This avoids creating any new managed
dataset (instance-light, fewer setup steps). The variable gains:

```jsonc
{
  // ... existing keys (golden_dataset, raw_dataset, ..., agents[], modes, judge_llm_id, suggestions) ...

  "agents": [ /* the CATALOG of agents you can benchmark (dropdown source when creating one) */ ],

  "benchmarks": {                                   // the registry (benchmark_id -> entity)
    "<benchmark_id>": {
      "name": "said",
      "agent_key": "orchestrator",
      "agent_label": "OWIsMind Orchestrator (DEV)",
      "project_key": "OWISMIND_DEV",
      "agent_id": "agent:038G7mlF",
      "modes": ["Smart","Pro","Claude"],
      "status": "active",                           // active | archived
      "created_at": "2026-06-29T...Z",
      "created_by": "user",
      "questions": {                                // membership + redo intent
        "<question_id>": { "added_at": "...", "include_next": false, "active": true }
      }
    }
  },

  "run_request": {                                  // written by the launcher right before firing
    "benchmark_id": "<benchmark_id>",
    "launch_mode": "append" | "full",               // append = pending + redo ; full = every member
    "requested_at": "..."
  }
}
```

Size: a few KB even at 100 questions x a handful of benchmarks - trivially fine for a project variable.
The launcher backend is a single Flask process; writes to the variable are serialized by the existing
`RUN_LOCK` / a new registry lock. The scenario reads `dataiku.get_custom_variables()` fresh per run.

Result tables stay the source of truth for results (raw/scored/summary/breakdown), now benchmark-stamped.

## 2. New columns

### Golden (`GOLDEN_COLUMNS`) - add two nullable reference columns
- `expected_sql`  (nullable text): a reference SQL that would answer the question. Soft signal only.
- `expected_tool` (nullable text): a reference tool key (e.g. `show_chart` / `show_table` / `none`).

Both optional, never required, editable in the launcher's Questions card, shown in the consultation
beside the agent's ACTUAL generated SQL / tool.

### Raw (`RAW_COLUMNS`) + Scored (`SCORED_COLUMNS`) - add the benchmark dimension + references
Add (in this order, appended to the existing RAW columns, before the scored-only block):
- `benchmark_id`, `benchmark_name`, `attempt_no`
- `expected_sql`, `expected_tool` (denormalized from the golden, carried for display + judge)
- `actual_tools` (derived from the captured artifacts: a comma list of artifact kinds, e.g. `chart,table`)

`SCORED_COLUMNS = RAW_COLUMNS + (existing judge/correct/human_* block)` - unchanged tail.

### Summary (`SUMMARY_COLUMNS`) -> benchmark-level (NOT per single run)
A summary row is now one per `(benchmark_id, agent_key, mode)`, computed over the LATEST attempt of each
question in the benchmark:
- `benchmark_id`, `benchmark_name`, `agent_key`, `agent_label`, `mode`
- `n_questions` (distinct questions with a latest attempt), `n_ok`, `n_error`, `error_rate`
- `accuracy`, `mean_score`, `score_dist_json`
- `latency_p50_s`, `latency_p95_s`, `latency_max_s`, `ttft_p50_s`
- `avg_cost_per_q`, `total_cost`, `avg_input_tokens`, `avg_output_tokens`
- `needs_review_count`, `judge_total_cost`
- `last_run_id`, `last_run_timestamp` (most recent contributing run), `n_runs` (contributing runs)

### Breakdown (`BREAKDOWN_COLUMNS`) -> benchmark-level
Add `benchmark_id`, `benchmark_name`; key becomes `(benchmark_id, agent_key, mode, dimension, bucket)`,
computed over latest attempts.

## 3. Launch resolution (the heart)

`benchmark/registry.py` (NEW, PURE, stdlib only) owns the model + resolution. Key functions:

- `parse_registry(cfg_obj)` -> normalized `{benchmark_id: entity}` (clamps, never raises).
- `parse_run_request(cfg_obj)` -> `{benchmark_id, launch_mode}` or `None`.
- `mint_benchmark_id()` is NOT here (no clock/uuid in pure code): the launcher/step mints it.
- `done_question_ids(scored_rows, benchmark_id, agent_key)` -> set of question_ids with >=1 attempt.
- `attempt_numbers(scored_rows, benchmark_id, agent_key)` -> `{(question_id, mode): max_attempt_no}`.
- `resolve_to_run(entity, scored_rows, golden_active_ids, launch_mode)` -> the ORDERED list of
  question_ids to run this launch:
  - membership = entity.questions where `active` and `question_id in golden_active_ids`.
  - `append`: `pending` (membership minus done) UNION `redo` (membership with `include_next`).
  - `full`  : all membership.
- `next_attempt_no(attempt_map, question_id, mode)` -> max+1 (default 1).
- registry CRUD (pure, return a new registry dict): `create_benchmark`, `add_questions`,
  `remove_question`, `set_include_next`, `reset_include_next_for`, `rename`, `archive`.

The DSS step stamps `benchmark_id` / `benchmark_name` / `attempt_no` on each raw row.

### Step 1 (run_matrix) - benchmark-aware
1. `cfg = run_params.resolve(vars)`; `req = cfg["run_request"]`. If no request -> raise a clear error
   ("no run_request: launch from the benchmark launcher").
2. `entity = cfg["benchmarks"][req.benchmark_id]` (raise if missing).
3. agent = the entity's pinned agent (single); modes = entity.modes.
4. Read golden (active+valid) -> `golden_active_ids` + the rows by id.
5. Read scored history (the configured scored dataset; schema-gated, [] when never built).
6. `to_run_ids = resolve_to_run(entity, scored, golden_active_ids, req.launch_mode)`. If empty ->
   raise ("nothing to run: every question already done; use full re-run or add questions").
7. Build the question rows for `to_run_ids`; run the matrix for the SINGLE agent x entity.modes.
8. For each completed raw row: stamp `benchmark_id`, `benchmark_name`, and
   `attempt_no = next_attempt_no(attempt_map, question_id, mode)`; also denormalize
   `expected_sql` / `expected_tool` and derive `actual_tools`.
9. Append to the raw dataset (history merge by run_id - unchanged).
10. After a successful run, reset `include_next=false` for the run questions in the registry and write
    the variable back (best-effort; the step may also leave this to the launcher post-run poll - see 6).

> Concurrency / agent project: unchanged (one project per run; the entity pins exactly one agent, so the
> multi-project guard is naturally satisfied).

### Step 2 (judge) - unchanged logic, carries the new columns
`_score_row` copies `RAW_COLUMNS` (so `benchmark_id`/`benchmark_name`/`attempt_no`/`expected_sql`/
`expected_tool`/`actual_tools` flow through automatically). Scope = latest `run_id` (unchanged) unless
`score_all_runs`. The judge prompt gains the soft reference signal (section 5).

### Step 3 (aggregate) - benchmark-level
1. Read scored (NaN-safe).
2. Determine the benchmark(s) to aggregate: by default the `benchmark_id` of the latest run (look up
   the latest run_id, read its benchmark_id); `aggregate_all_runs` -> every benchmark_id present.
3. For each benchmark_id: take its scored rows, reduce to the LATEST attempt per
   `(question_id, agent_key, mode)` (`scoring.latest_attempts`), then summarize/breakdown keyed by
   `(benchmark_id, agent_key, mode)`.
4. Append (history merge): summary/breakdown now merge by `benchmark_id` (one block of rows per
   benchmark replaces the prior block for that benchmark). Light tables, never capped.

## 4. Aggregation (`scoring.py`)
- NEW `latest_attempts(rows)` -> the subset keeping, for each `(benchmark_id, question_id, agent_key,
  mode)`, the row with the max `attempt_no` (tie-break: max `run_timestamp`, then `run_id`). Rows with no
  `benchmark_id` fall back to a single bucket so legacy/per-run data still reduces sanely.
- `summarize` / `breakdown` group key gains `benchmark_id` (carry `benchmark_name`, `last_run_id`,
  `last_run_timestamp`, `n_runs`). Accuracy uses `effective_correct` (unchanged).

## 5. Judge soft signal (`judge.py`)
- `build_judge_prompt(..., expected_sql=None, expected_tool=None)` appends, when present, a clearly
  labelled, NON-binding hint block:
  - `REFERENCE SQL (one SQL that could answer; the assistant may legitimately use a different, equally
    valid query - do NOT penalize a different but correct approach):`
  - `SUGGESTED TOOL (a tool that could illustrate the answer; not required):`
- `_JUDGE_SYSTEM` gains one sentence: these references are HINTS to help you judge correctness/coverage,
  never a requirement; judge MEANING and FACTS; a different SQL or tool that yields the right answer is
  fully correct.
- `run_llm_judge(..., expected_sql=None, expected_tool=None)` threads them through. `step_judge` passes
  `row.get("expected_sql")` / `row.get("expected_tool")`.

## 6. Webapp shared backend (`benchmark_webapp/`)
`views.py` (PURE) gains:
- `benchmarks_view(registry, scored_rows, golden_rows)` -> the launcher's benchmark list: per benchmark,
  `{benchmark_id, name, agent_label, n_questions, n_done, n_pending, n_redo, last_run_timestamp, n_runs,
  accuracy_pct (latest-attempt, from summary or recomputed)}`.
- `benchmark_questions_view(entity, golden_rows, scored_rows)` -> the membership table: per member
  question `{question_id, question, category, status: pending|done, include_next, attempts: [{attempt_no,
  run_timestamp, mode, verdict, score}], latest_verdict, evolution}` + the golden's `expected_sql`/
  `expected_tool`.
- `evolution_view(scored_rows, benchmark_id)` -> per `(question_id, mode)` the ordered attempts with
  verdict/score + the delta latest-vs-previous (the "evolution / regression" surface).
- registry mutation helpers reuse `benchmark/registry.py`; `validate_benchmark_name` (non-blank, unique
  vs existing names).
- `detail_view` / `golden_view` / `prepare_golden_save` gain `expected_sql`/`expected_tool`.
- `build_launch_request(benchmark_id, launch_mode)` -> the `run_request` block.

`dss.py` (DSS I/O) gains:
- read/write the `benchmarks` registry + `run_request` inside the `benchmark` variable (extends the
  existing read_raw_benchmark_var / write_benchmark_var; serialized by a `_REGISTRY_LOCK`).
- `create_benchmark` / `add_questions_to_benchmark` / `toggle_include_next` / `rename_benchmark` /
  `archive_benchmark` (variable read-modify-write under the lock; the launcher mints id/timestamps).
- launch: write `run_request` (benchmark_id + launch_mode) into the variable THEN fire the scenario
  (single-flight unchanged). After a successful run completes, reset `include_next` for the run set
  (done by the step in 3.10; the launcher also reconciles on its status poll, idempotent).
- golden CRUD: carry `expected_sql` / `expected_tool`.
- `read_summary` stays; the launcher/results read benchmark-level summary rows.

## 7. Launcher UI (`webapps/benchmark_launcher/`)
A new **Benchmarks** concept (tab) becomes the primary surface:
- Benchmark list (per agent): name, agent, #questions (done/pending/redo), last run, accuracy. Actions:
  open, **New benchmark** (name + pick agent from the catalog + seed questions = all active golden or a
  chosen subset).
- Open a benchmark -> the membership table: each question with a pending/done badge, latest verdict, an
  evolution sparkline/delta when >1 attempt, a **"redo at next run"** toggle (`include_next`), and the
  reference `expected_sql`/`expected_tool` (editable, writes the golden). Add questions from the golden
  pool. Three launch buttons: **Run pending** (append, default, disabled when nothing pending/redo),
  **Re-run entire benchmark** (full), **New benchmark**.
- Keep the existing Config / Golden (now with expected_sql/tool) / Suggestions / Review tabs.

## 8. Results UI (`webapps/benchmark_results/`)
- A **benchmark selector** (replaces / augments the run selector): pick a benchmark -> its benchmark-level
  KPIs (over latest attempts), per-config table, per-category breakdown, per-question detail.
- Per-question **evolution** (attempt history: verdict/score across attempts, latest counts).
- Show `expected_sql`/`expected_tool` vs the agent's actual generated SQL / tools in the detail.

## 9. Plugin consultation (`benchmark_view/` + Vue)
- `schemas.LIGHT_COLUMNS` + `schema_check`: add `benchmark_id`, `benchmark_name`, `attempt_no`,
  `expected_sql`, `expected_tool`, `actual_tools` as OPTIONAL (NOT in `REQUIRED_COLUMNS`, so an older
  table still validates). `lab_io.read_scored` reads the INTERSECTION of a desired column set and the
  table's actual columns (one cheap `table_columns` read) so a missing optional column never 500s the
  SELECT.
- `aggregate.py`: benchmark-aware. `results_view(scored, benchmark_id=None)` -> select a benchmark (a
  `benchmarks` selector list = distinct `(benchmark_id, name)` with last_run_timestamp), reduce to latest
  attempts, compute KPIs/configs/categories/detail + per-question `evolution` + expected/actual SQL/tool.
- routes `GET /benchmark/results` gains an optional `benchmark_id` param; response carries `benchmarks`
  (the selector) + the selected benchmark's view-model. Admin override unchanged (key still
  run_id/question_id/agent_key/mode -> targets a specific attempt).
- Vue: a benchmark selector + evolution column/expander + expected-vs-actual SQL/tool in the detail,
  styled per the Orange charter (square, flat, rare orange, no em dash).

## 10. Backward compatibility / migration
- Old rows (no `benchmark_id`) are tolerated everywhere (treated as a single legacy bucket; never crash).
- `write_with_schema` evolves the managed dataset schema on the next run; the history merge unions
  columns (old rows get None for the new columns). The user is re-running fresh, so legacy test rows can
  be ignored or cleared.
- The plugin's robust intersection read means an un-migrated table keeps working (no benchmark dimension,
  one implicit benchmark) until the LAB re-runs and materializes the new columns.

## 11. Non-negotiables (unchanged)
- SQL: parametrized, COMMIT after write, READ+APPEND only on the shared connection, no generic SQL route.
- Instance safety: bounded concurrency + per-call timeout (unchanged); the variable read-modify-write is
  small; the only added reads are bounded `information_schema` + the existing scored read.
- No em dash anywhere. Code/comments in English. Charter-compliant UI. DEV plugin packaging only.
- Pure modules never raise (degrade to empty view, not 500). New pure code is unit-tested.
