# Test strategy

> Audience: Developer. Last updated: 2026-07-06. Summary: OWIsMind's four pure-logic test
> suites (backend, frontend, agents, benchmark LAB), how to run them WITHOUT INSTALL, what they
> cover, the deterministic no-change proofs used during refactors, and where automatable
> verification stops outside a DSS instance.

OWIsMind is tested in four places: the Flask backend (`python-lib/owismind/`), the Vue frontend
(`OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/`), the LangGraph agents (`dataiku-agents/`), and the benchmark project
`OWIsMind_LAB/` (a SEPARATE DSS project, mirrored in the repo). All four suites share the same
philosophy: they are **pure-logic**, run with the language's **native runner** (stdlib `unittest`,
`node --test`), **without a DSS environment** and **without any installation**. They lock down the
invariants that are testable outside an instance; they do not replace validation IN DSS.

> NO INSTALL principle (non-negotiable rule #1): the agent never installs a dependency. The commands
> below use only `python3` and `npm` (already present) with the built-in runners. None of them is
> an install command. If `node_modules/` is missing for the build, it is up to the user to install, not
> the agent. See [Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

## Overview of the three suites

| Suite | Location | Runner | Run from | Tests (verified 2026-07-06) |
|---|---|---|---|---|
| Backend | `OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/` | `python3 -m unittest` | repository root | 790 `test_` functions (35 files) |
| Frontend | `OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/` | `node --test` | repository root (via `npm --prefix`) | 352 `test(...)` (18 files) |
| Agents | `dataiku-agents/tests/` | `python3 -m unittest` | repository root | 316 `test_` functions (4 files, 2 skipped at runtime) |
| Benchmark (LAB) | `OWIsMind_LAB/project-library/python/` | `python3 -m unittest` | repository root (`-t` at the lib root) | 343 `test_` functions (12 files) |

None of these four suites instantiates a real `dataiku` client, touches PostgreSQL, calls LLM
Mesh, or runs a real LangGraph graph. Everything that requires the instance is isolated behind pure
modules or neutralized by a stub (see the "What requires DSS" section).

## 1. Backend suite (Flask, Python 3.9)

```bash
python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests -v
```

The `OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/` folder lives **outside `python-lib/`**, so it is **never packaged** in
the deliverable zip (packaging only stages the runtime; see
[Build, packaging and deployment](../06-operations/02-build-package-deploy.md)). Each test module
inserts `python-lib/` onto `sys.path` (`sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))`) so
that `owismind.*` imports resolve without installing the package.

### What is covered

The suite targets the safety and shape invariants that can be verified without a database or a DSS
runtime. The busiest modules are on the Evidence and capture side.

| Domain | File(s) | What is locked down |
|---|---|---|
| Payload validation | `test_validation.py`, `test_history_limit.py`, `test_conversations_limit.py`, `test_feedback_validation.py` | shape and bounds of `/chat/start`; `validate_history_limit` clamp [10, 50] default 20; `validate_optional_exchange_id`; `validate_conversations_limit` clamp [1, 60] default 30 (never raises); `validate_feedback` (rating in {0, 1, None}, boolean rating rejected); `validate_agent_meta` (admin-authored agent profile: strings stripped and clamped, lists deduped and capped at 8 items, icon against a whitelist, badge against an enum, control chars stripped, never raises) |
| Budget and quotas | `test_budget.py` | SQL query builders (`build_user_usage_status_query`, `build_admin_usage_overview_query`, `build_user_quota_upsert`, `build_user_quota_clear`): server-side month arithmetic, LEFT JOINs, upsert shape, int-coerced days; `_resolve_limit` priority (user override > active global temp boost > default, enforcement disabled = never blocked, exactly-at-limit blocks); `get_budget_config` in-process cache (second call = cache hit, invalidation forces re-read, returns independent copies); `set_budget_config` (arm/clear/preserve temp boost); `set_user_quotas` / `clear_user_quotas` (one committed transaction, statement_timeout pre-query); input validators `validate_budget_amount` and `validate_expires_days` (bool-trap, overflow, inf, negative, over-cap); `validate_user_id_list` (dedup, bounds) |
| Pure SQL builders | `test_session_queries.py`, `test_ancestor_chain.py` | `build_conversation_list_query`, `build_session_messages_query`, `build_ancestor_chain_query`: user-scoped queries (in BOTH members of the recursive CTE for the ancestor walk), keyset-paginated, depth-bounded and `LIMIT` |
| Pagination | `test_pagination.py` | opaque cursor round-trip; malformed input degrades to `None` |
| Agent context | `test_agent_context.py` | pure multi-turn assembly (user prefix, flattening of exchanges into messages, generated-SQL grounding, final completion list) |
| Identity | `test_identity_names.py` | `security.identity.derive_full_name` (`prenom.nom` -> `Prenom Nom`), with a minimal `dataiku` stub injected so the import succeeds |
| Evidence (parse/validation) | `test_evidence_sql_parse.py`, `test_evidence_query_builders.py`, `test_evidence_whitelist.py`, `test_evidence_validation.py`, `test_evidence_throttle.py` | tokenizer and `parse_select` + `validate_fragment` (banned words, `pg_*`, balanced parentheses, bounded length); owner-scoped lookups with a mandatory `ORDER BY`; `match_whitelist` (case-insensitive, unknown table/schema rejected); structured filter bounds, clamped page, degrading sort, zero SQL in an accepted payload; `take_token` (per-user token-bucket, deterministic on `now`) |
| Evidence (capture/proof) | `test_evidence_capture.py`, `test_evidence_service_proof.py`, `test_evidence_sql_explain.py` | capture of the exact `result`, PURE structured explanation (never-raises), deterministic verification levels |
| Artifacts and usage | `test_artifacts.py`, `test_chart_payload.py`, `test_usage_accounting.py` | validation of `show_chart`/`show_table`/`show_kpi` specs, building the Chart.js payload on the Python side, token and cost accounting |
| Source Data Explorer | `test_source_aggregate.py`, `test_source_search.py`, `test_source_validation.py`, `test_cascading_distinct.py`, `test_evidence_aggregate.py` | schema-gated aggregate spec (whitelisted fns count/count_distinct/sum/avg/median/min/max, mandatory `LIMIT 50` on groups, totals query for exact percentages), distinct cascade with `filters`/`scope_q`, accent-insensitive search, read-only + timeout inherited; the shared `evidence/aggregate_core.py` proves both `/source/aggregate` and `/evidence/aggregate` aggregate the full pre-filtered set (never the displayed window) |
| Analytics and events | `test_events.py` | the 38-event whitelist source of truth + `validate_events` (batch/prop caps, dedup, py3.9 client_ts), `record_events` (one multi-row INSERT ON CONFLICT DO NOTHING, best-effort), `/track` never-500, impersonation drop-before-write, query-string PII stripping (L125) |
| Screen context and modes | `test_screen_context_state.py`, `test_chat_screen_ctx.py`, `test_chat_mode.py` | `sanitize_source_state` never-raises, the `[ON SCREEN NOW]` block budget, the verbatim permission phrase always preserved, per-answer mode stamping (`resolve_effective_mode`) |
| Benchmark and suggestions | `test_benchmark_view.py`, `test_suggestion_validation.py`, `test_suggestions_storage.py` | reading LAB-produced results read-only, live-schema intersection on the single-row `LIMIT 1` attempt load, validation and owner-scoped storage of a golden suggestion captured from chat |
| Impersonation and identity | `test_impersonation.py`, `test_identity_names.py`, `test_sql_config.py` | admin-gated impersonation resolution (drop on write paths), `derive_full_name`, identifier shortening/quoting in `sql_config` |

The detailed module-by-module inventory lives in
[`OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/README.md`](../../OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/README.md) ("Covered now" section).

## 2. Frontend suite (Vue 3, Node)

```bash
npm --prefix OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend test          # = node --test test/*.test.js
```

The `test` script of `frontend/package.json` is exactly `node --test test/*.test.js`: no Vitest,
no Jest, just Node's built-in runner. The tests live under `frontend/test/` (outside `src/`,
so never built or zipped). Design rule (gotcha F11): these units stay **without Vue or
dataiku** so they can run under the native runner, which forces pure logic to be extracted into testable
modules (reducers, selectors, clamps, parsing).

### What is covered

| File | Tests | What is locked down |
|---|---|---|
| `timeline.test.js` | 46 | the timeline's `applyEvent` reducer (the frozen F8 contract) |
| `evidenceModel.test.js` | 38 | the Evidence Studio model (chips, payload, `modified` state) |
| `evidenceProof.test.js` | 28 | the derivation of evidence / drill levels on the frontend |
| `sourceModel.test.js` | 28 | the Source Data Explorer model (chips, filters, ISO date-range sniffing, bascule list/range) |
| `sourceAnalyze.test.js` | 41 | the Analyser buckets and chronological ranges |
| `aggregateSurface.test.js` | 16 | the shared aggregate factory (2 hosts: Source data and Evidence) |
| `sourceViewMemory.test.js` | 20 | per-`(agent, dataset)` view persistence (chips/q/sort/calc survive close/reopen) |
| `screenContextModel.test.js` | 36 | the screen-context-to-agent snapshot and the localizable detail (`ScreenContextDetail`) |
| `promptContextModel.test.js` | 16 | the consent banner state (sticky by scope signature, retirable chip) |
| `benchmarkResults.test.js` | 28 | the plugin benchmark consultation model (KPIs, per-question cards, lazy attempt detail) |
| `track.test.js` | 21 | the analytics queue model (`trackModel.js`): queue cap 200, drain 40, error limiter |
| `budgetModel.test.js` | 8 | budget/usage helpers: gauge math, severity levels, money/token/date formatting |
| `conversationTree.test.js`, `conversationList.test.js` | 5 + 3 | the pure conversation tree and the side list |
| `sqlPretty.test.js` | 7 | Evidence's colored SQL formatting |
| `i18nExtraParity.test.js` | 3 | fr/en key parity of the domain i18n (`extra.js`) |
| `agentPick.test.js` | 3 | agent selection |
| `prefs.test.js` | 5 | preference clamps |

## 3. Agents suite (LangGraph, Python 3.11 in DSS, but tested DSS-free)

```bash
python3 -m unittest discover -s dataiku-agents/tests
```

Although the Code Agents run in Python 3.11 in DSS (LangGraph/LangChain installed there, an env
distinct from the 3.9 backend), their test suite runs **without DSS and without langgraph**. The mechanism is
explicit: `test_langgraph_agents.py` **stubs `dataiku` AND `langgraph` BEFORE** the agent files are
loaded (via `importlib`), so that only the PURE logic is exercised. The graph itself
is NOT executed (it needs DSS).

### What is covered

| File | Tests | What is locked down |
|---|---|---|
| `test_profiler.py` | 28 | design-time profiling (building the profile) |
| `test_dataset_expert.py` | 115 | the sub-agent's engine (UNDERSTAND/RESOLVE/QUERY/RENDER pipeline, SQL guard, normalization): the largest file |
| `test_langgraph_agents.py` | 114 | the registry and tool specs, the honesty sources block, the SQL/usage extraction from the trace, artifact validation, language detection, the `attribute_lookup` wiring (built-in routing, evidence items, output shaping), `show_kpi` specs and the frozen cross-file events contract (anti-drift) |
| `test_attribute_lookup.py` | 59 | the `attribute_lookup` tool (case-/accent-insensitive lookup on text columns, `concat_ws` + single `ILIKE`, `translate`-based accent folding, `rows_capped` / `multi_column` flags, Value_Catalog alias fallback, `not_found` / `suggestions` shaping) |

### The anti-drift test (central invariant)

The most structuring test in this suite is the **anti-drift** one: it guarantees that the
orchestrator registry (`OWIsMind_orchestrator.CAPABILITIES`) and the sub-agent's frozen contracts stay
synchronized. Concretely, `test_langgraph_agents.py` asserts that the `block_labels` and `tool_labels`
declared for the `revenue_expert` capability match exactly the `KNOWN_BLOCK_IDS` and
`KNOWN_TOOL_NAMES` sets of the sub-agent, and that `CAPABILITIES["revenue_expert"]["agent_id"]` is indeed
`agent:bHrWLyOL`. If someone renames an event, adds a tool, or changes the sub-agent id without keeping
both files up to date, this test breaks. This is what makes it possible to **re-paste the two Code Agents
together with confidence**: orchestrator <-> sub-agent consistency is verified locally before deployment.

> Note on the DEV/PROD_V1 split: the suite loads the DEV agent files
> (`dataiku-agents/OWISMIND/OWISMIND_DEV/`), which carry the DEV ids (orchestrator `038G7mlF`,
> revenue expert `agent:bHrWLyOL`). The PROD_V1 deployables are not tested by a second suite; they are
> instead REGENERATED from DEV by `tools/promote_agents_to_prod.py`, which guarantees parity by
> construction (copy DEV, substitute the PROD ids, surgically drop the tickets block) and refuses to
> write on any unexpected diff. See [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

> IN FLUX: `attribute_lookup` (`tools/attribute_lookup_tool.py`) is built, unit-tested (48 tests),
> and **wired as a built-in of the orchestrator** (constants `LOOKUP_TOOL_NAME = "attribute_lookup"`,
> `LOOKUP_TOOL_ID`, inline dispatch in `node_tools`) - confirmed in `agents/OWIsMind_orchestrator.py`.
> The sub-agent is UNCHANGED by this wiring (rule P2: the lookup is an orchestrator built-in only).
> What remains to do IN DSS: create the Custom Python tool object pointing to `attribute_lookup_tool.py`,
> optionally set `LOOKUP_TOOL_ID` for a direct bind (defaults to name resolution), and re-paste the
> orchestrator. The predecessor `dataset_lookup` tool (`9FEzVZk`) and the `lookup` intent were REMOVED
> on 2026-06-18. The `Drive_Revenues_resolve_filter_value` tool object is pending deletion in DSS.

## 4. Benchmark suite (OWIsMind_LAB, separate DSS project)

```bash
python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python
```

The benchmark / agent-evaluation system lives in its OWN DSS project (`OWIsMind_LAB`), mirrored in the
repo under `OWIsMind_LAB/`; it is NOT part of the plugin. Its 343 tests split into two packages:
`benchmark/tests/` (the engine: capture of the agent's full answer, the objective-anchor + LLM-judge
scoring, the registry/append-mode, run params, history) and `benchmark_webapp/tests/` (the two admin
webapps' pure views and the golden CRUD). Like the other suites it is pure-logic: it stubs `dataiku`, never
calls LLM Mesh and never runs a real benchmark. The `-t` at the library root is required so the
`from benchmark ...` / `from benchmark_webapp ...` package imports resolve. Full map:
[`OWIsMind_LAB/README.md`](../../OWIsMind_LAB/README.md).

## Deterministic no-change proofs (refactor safety)

Beyond the unit suites, two byte/AST-level checks are used during clean-up refactors to PROVE that a
change is behavior-preserving, without needing a DSS run:

- **AST-strip-docstrings compare (Python).** When a refactor should only touch comments, docstrings or
  formatting, parse the before and after with `ast`, strip docstrings and re-`ast.dump` (or `ast.unparse`)
  both sides, and assert they are identical. This proves the executable AST is unchanged while the source
  text differs, and it is exactly how the `promote_agents_to_prod.py` regeneration is reviewed: the only
  admissible DEV<->PROD diff is deploy-target headers + id lines + the removed tickets block.
- **Byte-identical Vite bundle.** When a frontend refactor is supposed to leave the built app untouched
  (a pure rename, a dead-code removal), run the throwaway compile-check (below) before and after and
  compare the emitted bundle. An identical `index-<hash>.js` hash is the proof that the deployed asset is
  unchanged; a different hash means the change is NOT inert and must be re-validated in DSS. (Conversely,
  a stale `body.html` still pointing at an old hash is a known deploy trap, gotcha F10.)

These proofs replace, for inert changes, the DSS smoke test that would otherwise be the only way to gain
confidence. They do NOT replace DSS validation for changes that alter behavior.

## Runtime QA with Playwright (bundle-level, off-instance)

Some frontend behavior lives above the pure-logic layer (Evidence panel rendering, the Source Data
Explorer flows, the benchmark consultation page) and cannot be reached by `node --test`. For these, the
project runs a **real-browser QA harness**: a tiny static server maps the plugin's hashed asset prefix
(`/plugins/owismind/resource/owismind-app/`) onto the freshly built bundle, a `qa-stub.js` injects a stub
`getWebAppBackendUrl` and canned backend responses (conversation + meta + rows + aggregate + distinct),
and Playwright drives the actual flows in light and dark, at a couple of widths, with the console watched
for errors. This is how the Source Data waves, the artifact/Evidence tabs and the benchmark page were
verified against the ACTUAL bundle before upload (lessons L129, L132). Two rules learned the hard way:
QA the FRESHLY built bundle (a stale bundle silently passes an already-fixed bug, L132), and READ every
screenshot the harness takes (do not assume a green console means the layout is right, L130). This harness
is a per-change verification aid, not a committed suite, and still does not exercise real LLM Mesh or
PostgreSQL.

## Checking that a build compiles locally (throwaway compile-check)

To make sure a frontend change **compiles** without touching the deployed app, run a build to
a temporary directory that is deleted right away:

```bash
./node_modules/.bin/vite build --outDir /tmp/owi_buildcheck --emptyOutDir
rm -rf /tmp/owi_buildcheck
```

> Warning (gotcha F1): NEVER build into `resource/` outside the `/build-plugin` skill. The
> official `outDir` points there with `emptyOutDir: true`, so a "wild" build PURGES then OVERWRITES the
> deployed app. The compile-check must go through an `outDir` in `/tmp`. The official build (which
> also rewires `body.html`) goes through the `/build-plugin` skill; see
> [Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

## What requires DSS (not covered by the suites) and the TEST-01 recommendation

Some backend modules import `dataiku` or `pandas` at load time: they need the DSS Python
(or a stub) just to import, so they are not covered by the current suites. They are
nonetheless high-value invariants:

- `sql_config.pg_identifier`: rejection of an injected identifier, correct quoting.
- `storage.serialization.rows_to_json_safe`: NaN/NaT -> None, timestamps -> ISO.
- `settings.resolve_enabled_agent`: only an enabled `logical_key` resolves; a forged key -> `None`.
- `agents.stream_manager`: the run state machine (cursor advance, TTL eviction, concurrency
  cap, `can_accept` guard, cooperative stop via `_stop_reason`).
- `security.identity.derive_display_name`: login -> friendly default; TTL cache behavior.

> ROADMAP (TEST-01, recommended, NOT done): add DSS-free tests based on a `dataiku`/`pandas` stub
> for these already-hardened but uncovered invariants, then wire `python3 -m py_compile` (or
> `compileall`) on `python-lib/owismind/**` as a minimal verification. There is **NO CI**
> today. The targeted minimal pipeline would be: lint + `py_compile` on `python-lib/owismind/**` +
> backend `unittest` + `vite build` (compile-check).

Beyond the modules above, end-to-end behavior remains untestable outside an instance: real
LLM Mesh calls, PostgreSQL SQL execution, Evidence panel rendering, per-mode model behavior,
and the actual execution of the LangGraph graph. These aspects fall under validation IN DSS and the
agent smoke tests, described in [Agent evaluation](02-agent-evaluation.md).

## Recap of the three commands (no install)

```bash
# Backend (from the repository root)
python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests -v

# Frontend (from the repository root)
npm --prefix OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend test

# Agents (from the repository root)
python3 -m unittest discover -s dataiku-agents/tests

# Benchmark LAB (from the repository root)
python3 -m unittest discover -s OWIsMind_LAB/project-library/python -t OWIsMind_LAB/project-library/python
```

> Note on stale reference docs: older guides may cite obsolete test counts. The CODE is the source of
> truth: 790 backend (35 files), 352 frontend (18 files), 316 agents (4 files, 2 skipped), 343 benchmark
> LAB (12 files) - verified 2026-07-06. Do not copy a stale number.

## See also
- [Agent evaluation](02-agent-evaluation.md) - anti-drift test in detail, smoke tests, golden queries, what remains to validate in DSS.
- [Build, packaging and deployment](../06-operations/02-build-package-deploy.md) - NO INSTALL, compile-check, what-to-rebuild-when matrix, DSS deployment.
- [Backend - overview and structure](../04-backend/01-overview-and-structure.md) - the tested sub-packages (validation, storage, evidence, agents).
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - `stream_manager`, one of the modules to stub (TEST-01).
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - re-paste the 2 Code Agents env 3.11, verify the config ids.
- [Contributing - conventions and rules](../09-maintenance/01-contributing-and-conventions.md) - the NO INSTALL rule and the non-negotiable rules.
