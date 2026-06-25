"""Thin DSS scenario-step entrypoints for the OWIsMind benchmark Flow.

Each module here is a copy-pasteable body for a Python step of the
``Run_Benchmark`` scenario in the DSS project ``OWIsMind_LAB``. Unlike the rest
of the package, these modules DO import ``dataiku`` / ``pandas`` at top level:
they only ever run inside a DSS scenario step (where both are on the path) and
are NEVER imported by the unit tests (which stay stdlib-only, NO INSTALL).

The heavy lifting lives in the pure package modules (agent_capture, agent_runner,
judge, scoring, schemas, config); these steps only read the input managed
datasets, drive the pure logic, and write the output managed datasets via the
canonical OWIsMind pattern (Dataset(name).get_dataframe / write_with_schema).

Step order (design spec section 8):
  1. step_run_matrix  -> benchmark_runs_raw
  2. step_judge       -> benchmark_runs_scored
  3. step_aggregate   -> benchmark_summary + benchmark_breakdown

Design contract: docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md
"""
