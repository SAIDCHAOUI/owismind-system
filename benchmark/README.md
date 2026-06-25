# benchmark/

Agent benchmark and evaluation for OWIsMind. Measures quality (accuracy via a
deterministic objective anchor plus a structured LLM judge), latency, cost and
tokens for each agent on each response mode (eco / medium / high = Smart / Pro /
Claude), with a per-question detail table anyone can read.

This repo package is the single source of truth. It is recolled into the DSS
project `OWIsMind_LAB` as a project library; the scenario steps in `dss_steps/`
are thin entrypoints that read managed datasets, drive the pure logic here, and
write the result datasets (no Flow at runtime, native managed datasets so the DSS
dashboard sits directly on them).

## Module map

| module | role | imports |
|---|---|---|
| `agent_capture.py` | footer trace -> complete answer (text + SQL + result rows + artifacts); `assemble_full_answer` is the single string the judge sees | pure (stdlib) |
| `schemas.py` | canonical column lists + enums + golden-row validate/normalize | pure |
| `config.py` | judge LLM id, modes, caps, tolerance, exact mode/lang control tokens, `build_message` / `build_plain_message` | pure (no dataiku at top) |
| `run_params.py` | the single run config, resolved from the one `benchmark` project variable (datasets, agents + per-agent modes flag, modes, language, concurrency, ...) | pure |
| `agent_runner.py` | run one agent x mode (mode-aware: token for mode agents, plain call for others), capture, latency / ttft / errors, bounded concurrency (`run_matrix`) | dataiku lazy inside functions |
| `judge.py` | objective anchor + structured LLM judge + correctness rule | dataiku lazy inside functions |
| `scoring.py` | aggregation maths: `summarize` (KPI per run x agent x mode) + `breakdown` (per dimension bucket) | pure |
| `dss_steps/step_run_matrix.py` | scenario step 2 -> `benchmark_runs_raw` | dataiku / pandas at top (DSS-only) |
| `dss_steps/step_judge.py` | scenario step 3 -> `benchmark_runs_scored` | dataiku / pandas at top (DSS-only) |
| `dss_steps/step_aggregate.py` | scenario step 4 -> `benchmark_summary` + `benchmark_breakdown` | dataiku / pandas at top (DSS-only) |

## Tests

```
python3 -m unittest discover -s benchmark/tests
```

Pure-logic only, no DSS calls. The fixtures lock capture parity with the webapp.

## Rules (non negotiable)

- NO INSTALL: never run pip / npm / brew installs. The test environment has the
  Python stdlib only (no pandas, no dataiku, no langchain).
- No top-level pandas / dataiku in the pure modules (`agent_capture`, `schemas`,
  `config`, `run_params`, `judge`, `scoring`, and the runner's pure helpers): import them
  lazily inside functions so the modules load stdlib-only for the tests. Only the
  `dss_steps/` entrypoints import dataiku / pandas at top level, and the tests
  never import those.
- Code and comments in English. No em dash or en dash anywhere.

## Pointers

- Runbook (DSS setup: datasets, scenario, variables, recolling the library):
  `benchmark/SETUP_GUIDE.md`.
- Design contract: `docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md`.
