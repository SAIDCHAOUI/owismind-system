# ADR-0018 - Benchmark in a separate DSS project (OWIsMind_LAB); the plugin only consults

> Audience: Backend developer, architect. Last updated: 2026-07-06. Summary: why the agent
> evaluation / benchmark system is its own DSS project (`OWIsMind_LAB`, mirrored under `OWIsMind_LAB/`)
> with its own webapps, and why the plugin embeds a CONSULTATION-only view rather than a launcher.

## Status

Accepted (DSS, phased). Engine and launcher live in the LAB; the plugin consultation page is validated
locally and deployed. Lessons L102 to L117.

## Context

Agents must be measured (accuracy, latency, cost) per agent AND per mode, against golden questions, with a
deterministic anchor plus an LLM judge and a human override. Running benchmarks calls the orchestrator
directly through LLM Mesh and can be heavy and long. Putting a launcher inside the end-user plugin would
mix a costly admin/eval workload into the product surface, risk an end user triggering a run, and couple
the plugin's release cycle to the evaluation tooling.

## Decision

- **The benchmark is a SEPARATE DSS project, `OWIsMind_LAB`**, mirrored in the repo under `OWIsMind_LAB/`:
  `project-library/python/{benchmark, benchmark_webapp}` (recolled as project-library packages), two
  Standard webapps (`benchmark_launcher` to configure/run/override, `benchmark_results` for public
  read-only consultation), a `benchmark` project variable as the single config, and a `Run_Benchmark`
  scenario (3 steps). It is NOT the plugin. Map: `OWIsMind_LAB/README.md`.
- **The scoring is deterministic-first**: an objective anchor (magnitude-aware) plus a structured LLM
  judge whose disagreement flags `needs_review`; a human override (`human_*` columns) always wins and
  survives re-runs.
- **The plugin only CONSULTS**: a pure `benchmark_view/` package plus read-only routes render the LAB
  results NATIVELY (no iframe), and users can capture a golden SUGGESTION from a chat answer (table
  `webapp_golden_suggestions_v1` + `/benchmark/*` routes). The plugin never launches a run.

## Reasons

- Isolation of a heavy admin workload from the product: a benchmark run cannot be triggered by an end
  user and cannot stall the plugin backend; instance-safety (rule #2) is preserved.
- Decoupled release cycles: the eval tooling evolves in the LAB without repackaging or restarting the
  plugin.
- Single source of config (the `benchmark` variable) avoids hardcoded agent/mode lists; the append-mode
  registry accumulates runs per agent so scores show evolution.
- Consultation-in-plugin keeps the results visible to the people who use the agents, without granting
  them the launch surface.

## Consequences

Positive:

- The plugin surface stays product-only; the costly path lives in a project the admins own.
- Golden questions can be sourced from real chat answers (suggestion flow) and promoted in the LAB.
- The plugin reads results by intersecting stored columns with the live schema, so it is resilient to LAB
  schema evolution.

Negative or watch points:

- Two deployment targets: a benchmark change may require recolling the LAB project-library AND the two
  webapps' panes, separately from the plugin zip.
- A managed-table name can exceed PG's 63-byte identifier limit once prefixed; the shortener
  (`sql_config._shorten_identifier`) is required and the exact physical name must be copied into the LAB
  variable (L110).
- Scheduled runs and a richer judge UI remain roadmap.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| A launcher inside the end-user plugin | Mixes a heavy admin workload into the product, risks an end user triggering a run, couples release cycles. |
| An iframe of the LAB results webapp inside the plugin | Loses the Orange charter, cross-origin friction; a native re-render is cleaner and on-brand. |
| Ad-hoc manual evaluation (no system) | Not reproducible, no per-mode/per-agent breakdown, no human-override audit trail. |

## See also

- [Agent evaluation](../07-testing/02-agent-evaluation.md) - the golden questions, judge and smoke tests.
- [ADR-0004 - Server-side agent whitelist](0004-whitelist-agents-serveur.md) - the same agents are consulted here by id.
- `OWIsMind_LAB/README.md` (external) - the repo<->DSS map for the LAB project and its two deploy guides.
- [ADR index](README.md) - all architecture decisions.
