# Test strategy

> Audience: Developer. Last updated: 2026-06-18. Summary: OWIsMind's three pure-logic test
> suites (backend, frontend, agents), how to run them WITHOUT INSTALL, what they
> cover, and where automatable verification stops outside a DSS instance.

OWIsMind is tested in three places, one per layer: the Flask backend (`python-lib/owismind/`), the
Vue frontend (`Plugin/owismind/frontend/`) and the LangGraph agents (`dataiku-agents/`). All three suites
share the same philosophy: they are **pure-logic**, run with the language's **native runner**
(stdlib `unittest`, `node --test`), **without a DSS environment** and **without any installation**. They
lock down the invariants that are testable outside an instance; they do not replace validation IN DSS.

> NO INSTALL principle (non-negotiable rule #1): the agent never installs a dependency. The commands
> below use only `python3` and `npm` (already present) with the built-in runners. None of them is
> an install command. If `node_modules/` is missing for the build, it is up to the user to install, not
> the agent. See [Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

## Overview of the three suites

| Suite | Location | Runner | Run from | Tests (verified 2026-06-18) |
|---|---|---|---|---|
| Backend | `Plugin/owismind/tests/` | `python3 -m unittest` | repository root | 385 `test_` functions (20 files) |
| Frontend | `Plugin/owismind/frontend/test/` | `node --test` | `Plugin/owismind/frontend/` | 116 `test(...)` (8 files) |
| Agents | `dataiku-agents/tests/` | `python3 -m unittest` | repository root | 262 `test_` functions (4 files) |

None of these three suites instantiates a real `dataiku` client, touches PostgreSQL, calls LLM
Mesh, or runs a real LangGraph graph. Everything that requires the instance is isolated behind pure
modules or neutralized by a stub (see the "What requires DSS" section).

## 1. Backend suite (Flask, Python 3.9)

```bash
python3 -m unittest discover -s Plugin/owismind/tests -v
```

The `Plugin/owismind/tests/` folder lives **outside `python-lib/`**, so it is **never packaged** in
the deliverable zip (packaging only stages the runtime; see
[Build, packaging and deployment](../06-operations/02-build-package-deploy.md)). Each test module
inserts `python-lib/` onto `sys.path` (`sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))`) so
that `owismind.*` imports resolve without installing the package.

### What is covered

The suite targets the safety and shape invariants that can be verified without a database or a DSS
runtime. The busiest modules are on the Evidence and capture side.

| Domain | File(s) | What is locked down |
|---|---|---|
| Payload validation | `test_validation.py`, `test_history_limit.py`, `test_conversations_limit.py`, `test_feedback_validation.py` | shape and bounds of `/chat/start`; `validate_history_limit` clamp [10, 50] default 20; `validate_optional_exchange_id`; `validate_conversations_limit` clamp [1, 60] default 30 (never raises); `validate_feedback` (rating in {0, 1, None}, boolean rating rejected) |
| Pure SQL builders | `test_session_queries.py`, `test_ancestor_chain.py` | `build_conversation_list_query`, `build_session_messages_query`, `build_ancestor_chain_query`: user-scoped queries (in BOTH members of the recursive CTE for the ancestor walk), keyset-paginated, depth-bounded and `LIMIT` |
| Pagination | `test_pagination.py` | opaque cursor round-trip; malformed input degrades to `None` |
| Agent context | `test_agent_context.py` | pure multi-turn assembly (user prefix, flattening of exchanges into messages, generated-SQL grounding, final completion list) |
| Identity | `test_identity_names.py` | `security.identity.derive_full_name` (`prenom.nom` -> `Prenom Nom`), with a minimal `dataiku` stub injected so the import succeeds |
| Evidence (parse/validation) | `test_evidence_sql_parse.py`, `test_evidence_query_builders.py`, `test_evidence_whitelist.py`, `test_evidence_validation.py`, `test_evidence_throttle.py` | tokenizer and `parse_select` + `validate_fragment` (banned words, `pg_*`, balanced parentheses, bounded length); owner-scoped lookups with a mandatory `ORDER BY`; `match_whitelist` (case-insensitive, unknown table/schema rejected); structured filter bounds, clamped page, degrading sort, zero SQL in an accepted payload; `take_token` (per-user token-bucket, deterministic on `now`) |
| Evidence (capture/proof) | `test_evidence_capture.py`, `test_evidence_service_proof.py`, `test_evidence_sql_explain.py` | capture of the exact `result`, PURE structured explanation (never-raises), deterministic verification levels |
| Artifacts and usage | `test_artifacts.py`, `test_chart_payload.py`, `test_usage_accounting.py` | validation of `show_chart`/`show_table`/`show_kpi` specs, building the Chart.js payload on the Python side, token and cost accounting |

The detailed module-by-module inventory lives in
[`Plugin/owismind/tests/README.md`](../../Plugin/owismind/tests/README.md) ("Covered now" section).

## 2. Frontend suite (Vue 3, Node)

```bash
npm --prefix Plugin/owismind/frontend test          # = node --test test/*.test.js
```

The `test` script of `frontend/package.json` is exactly `node --test test/*.test.js`: no Vitest,
no Jest, just Node's built-in runner. The tests live under `frontend/test/` (outside `src/`,
so never built or zipped). Design rule (gotcha F11): these units stay **without Vue or
dataiku** so they can run under the native runner, which forces pure logic to be extracted into testable
modules (reducers, selectors, clamps, parsing).

### What is covered

| File | What is locked down |
|---|---|
| `timeline.test.js` | the timeline's `applyEvent` reducer (the largest unit: 42 tests) |
| `evidenceModel.test.js` | the Evidence Studio model (chips, payload, `modified` state) |
| `evidenceProof.test.js` | the derivation of evidence / drill levels on the frontend |
| `conversationTree.test.js`, `conversationList.test.js` | the pure conversation tree and the side list |
| `sqlPretty.test.js` | Evidence's colored SQL formatting |
| `agentPick.test.js` | agent selection |
| `prefs.test.js` | preference clamps |

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

| File | What is locked down |
|---|---|
| `test_profiler.py` | design-time profiling (building the profile) |
| `test_dataset_expert.py` | the sub-agent's engine (UNDERSTAND/RESOLVE/QUERY/RENDER pipeline, SQL guard, normalization): the largest file |
| `test_langgraph_agents.py` | the registry and tool specs, the honesty sources block, the SQL/usage extraction from the trace, artifact validation, language detection, and the frozen cross-file events contract (anti-drift) |
| `test_attribute_lookup.py` | the `attribute_lookup` tool (case-/accent-insensitive lookup on text columns) |

### The anti-drift test (central invariant)

The most structuring test in this suite is the **anti-drift** one: it guarantees that the
orchestrator registry (`OWIsMind_orchestrator.CAPABILITIES`) and the sub-agent's frozen contracts stay
synchronized. Concretely, `test_langgraph_agents.py` asserts that the `block_labels` and `tool_labels`
declared for the `revenue_expert` capability match exactly the `KNOWN_BLOCK_IDS` and
`KNOWN_TOOL_NAMES` sets of the sub-agent, and that `CAPABILITIES["revenue_expert"]["agent_id"]` is indeed
`agent:bHrWLyOL`. If someone renames an event, adds a tool, or changes the sub-agent id without keeping
both files up to date, this test breaks. This is what makes it possible to **re-paste the two Code Agents
together with confidence**: orchestrator <-> sub-agent consistency is verified locally before deployment.

> IN FLUX: the `dataiku-agents/` layer is being edited live. `test_attribute_lookup.py` exists (46
> tests) and the `attribute_lookup` tool (`tools/attribute_lookup_tool.py`) is built and unit-tested,
> but it is **not yet wired** into the sub-agent. Its predecessor, the managed
> `dataset_lookup` tool (`9FEzVZk`) and the `lookup` intent, were REMOVED on 2026-06-18. The wiring of
> `attribute_lookup` remains to be done (creating the Custom Python tool in DSS + routing attribute
> reads from the sub-agent).

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
python3 -m unittest discover -s Plugin/owismind/tests -v

# Frontend (from Plugin/owismind/frontend/)
npm --prefix Plugin/owismind/frontend test

# Agents (from the repository root)
python3 -m unittest discover -s dataiku-agents/tests
```

> Note on stale reference docs: `docs/build-test-deploy.md` still cites "65 tests" backend and
> "27 tests" frontend. These are stale counts. The CODE is the source of truth: 385 backend, 116
> frontend, 262 agents (verified 2026-06-18). Do not copy a stale number.

## See also
- [Agent evaluation](02-agent-evaluation.md) - anti-drift test in detail, smoke tests, golden queries, what remains to validate in DSS.
- [Build, packaging and deployment](../06-operations/02-build-package-deploy.md) - NO INSTALL, compile-check, what-to-rebuild-when matrix, DSS deployment.
- [Backend - overview and structure](../04-backend/01-overview-and-structure.md) - the tested sub-packages (validation, storage, evidence, agents).
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - `stream_manager`, one of the modules to stub (TEST-01).
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - re-paste the 2 Code Agents env 3.11, verify the config ids.
- [Contributing - conventions and rules](../09-maintenance/01-contributing-and-conventions.md) - the NO INSTALL rule and the non-negotiable rules.
