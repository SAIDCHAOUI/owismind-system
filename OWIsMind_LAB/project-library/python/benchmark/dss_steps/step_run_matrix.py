"""Scenario step 2: run the benchmark matrix -> benchmark_runs_raw.

Copy-pasteable body for a Python step of the ``Run_Benchmark`` scenario in the
DSS project ``OWIsMind_LAB``. ALL the run parameters come from ONE project
variable named ``benchmark`` (see benchmark/run_params.py for the full schema):
which agents, which modes, which input / output datasets, language, concurrency,
question filter. Nothing is hardcoded here. The step loads the active golden
questions, calls the agent once per (question x agent x mode) capturing the
COMPLETE answer (text + SQL + result rows + artifacts) plus latency / tokens /
cost, and writes one row per call to the configured raw dataset.

Per-agent modes: an agent with ``"modes": true`` is tested across the requested
modes (mode token appended); an agent without it gets ONE plain call (mode
"default"). See run_params.py.

Input dataset : benchmark.golden_dataset  (default golden_questions_v1_prepared)
Output dataset: benchmark.raw_dataset      (default benchmark_runs_raw)

Instance safety: a small golden set, low bounded concurrency, a hard per-call
timeout; agent calls are read-only (SELECT through the semantic model). No
unbounded loops, no aggressive retries.
"""

import json
import uuid
from datetime import datetime

import dataiku
import pandas as pd

from benchmark import config, schemas, run_params
from benchmark import agent_runner
from benchmark import registry
from benchmark.dss_steps.history_io import write_history_dataset, read_history_rows

# Light columns the run resolver needs from the raw history (done detection + attempt numbering).
# Projected at the source so the heavy answer / SQL / artifact JSON is never loaded just to count.
_RESOLVER_COLUMNS = ("benchmark_id", "question_id", "agent_key", "mode", "attempt_no",
                     "run_id", "run_timestamp")


def _get_variables():
    """Return the merged scenario / project custom variables dict (never raises)."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def _load_golden_rows(golden_dataset):
    """Read the golden dataset, normalize, validate, keep active+valid rows. Returns list[dict].

    Invalid rows are SKIPPED with a step-log line (not run): a mis-authored row (e.g. an
    expected_value with no expected_value_type) would otherwise reach the objective anchor as a
    silent 'string' containment and corrupt the deterministic ground truth (a wrong answer could
    be scored 'hit'). The validator never raises, so this only filters - it cannot fail the run.
    """
    df = dataiku.Dataset(golden_dataset).get_dataframe()
    # NaN -> None so the pure normalizer / validator see real blanks. astype(object)
    # first: on a numeric column, where(..., None) would otherwise re-coerce None
    # back to NaN (pandas keeps the float dtype).
    df = df.astype(object).where(pd.notnull(df), None)
    rows = []
    skipped = 0
    for record in df.to_dict(orient="records"):
        norm = schemas.normalize_golden_row(record)
        if not norm.get("active"):
            continue
        ok, errors = schemas.validate_golden_row(norm)
        if not ok:
            skipped += 1
            print("benchmark: skipping invalid golden row {0}: {1}".format(
                norm.get("question_id"), "; ".join(errors)))
            continue
        rows.append(norm)
    if skipped:
        print("benchmark: skipped {0} invalid golden row(s)".format(skipped))
    return rows


def _benchmark_agent(entity):
    """Return ``(agent_descriptor, run_modes)`` for the runner from a registry entity.

    The descriptor carries the runner's per-agent ``modes`` BOOL (derived from the entity's mode
    LIST): a benchmark whose modes are exactly ["default"] (or empty) is a single plain call; any
    other mode list is mode-aware (one call per mode with the control token).
    """
    entity = entity if isinstance(entity, dict) else {}
    modes = [m for m in (entity.get("modes") or []) if m]
    supports = bool(modes) and modes != [agent_runner.DEFAULT_MODE_LABEL]
    agent = {
        "agent_key": entity.get("agent_key"),
        "agent_label": entity.get("agent_label") or entity.get("agent_key"),
        "project_key": entity.get("project_key"),
        "agent_id": entity.get("agent_id"),
        "modes": supports,
    }
    run_modes = modes if supports else [agent_runner.DEFAULT_MODE_LABEL]
    return agent, run_modes


def run():
    """Execute ONE benchmark launch (the run_request) and append to the raw dataset.

    v2: a launch targets ONE named benchmark (its pinned agent + modes). It runs only the questions
    resolved from the benchmark membership + the launch mode (append = pending + redo ; full = every
    member), stamping benchmark_id / benchmark_name / attempt_no on each row so runs ACCUMULATE into
    the same benchmark. The launcher writes ``run_request`` into the variable before firing this step.
    """
    cfg = run_params.resolve(_get_variables())

    req = cfg.get("run_request")
    if not req:
        raise ValueError(
            "no run_request in the 'benchmark' project variable: launch from the benchmark launcher "
            "(it writes run_request = {benchmark_id, launch_mode} before firing the run)."
        )
    benchmark_id = req["benchmark_id"]
    launch_mode = req["launch_mode"]
    entity = (cfg.get("benchmarks") or {}).get(benchmark_id)
    if not entity:
        raise ValueError(
            "run_request points at an unknown benchmark_id {0!r}; it is not in benchmark.benchmarks"
            .format(benchmark_id)
        )

    agent, run_modes = _benchmark_agent(entity)
    if not (agent["agent_key"] and agent["project_key"] and agent["agent_id"]):
        raise ValueError("benchmark {0!r} has an incomplete pinned agent".format(benchmark_id))

    # Stamp the run identity here (allowed in a step; not in the agent loop).
    run_id = uuid.uuid4().hex
    run_timestamp = datetime.now().isoformat()

    # Active + valid golden rows, indexed by id (the gate for membership + the question payloads).
    golden_rows = _load_golden_rows(cfg["golden_dataset"])
    golden_by_id = {r.get("question_id"): r for r in golden_rows if r.get("question_id")}
    golden_active_ids = set(golden_by_id.keys())

    # Prior attempts of THIS benchmark from the raw history (fail-open []): used to skip already-done
    # questions (append mode) and to compute the next attempt number per (question, mode).
    prior = read_history_rows(cfg["raw_dataset"], columns=_RESOLVER_COLUMNS)
    to_run_ids = registry.resolve_to_run(entity, prior, golden_active_ids, launch_mode)
    if not to_run_ids:
        raise ValueError(
            "nothing to run for benchmark {0!r} ({1}): every member question is already done. "
            "Use the full re-run, add questions, or flag some 'redo at next run'."
            .format(entity.get("name") or benchmark_id, launch_mode)
        )
    attempt_map = registry.attempt_numbers(prior, benchmark_id, agent["agent_key"])
    questions = [golden_by_id[qid] for qid in to_run_ids if qid in golden_by_id]

    project = dataiku.api_client().get_project(agent["project_key"])

    run_config = {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "project": project,           # DSS handle the runner uses to reach the agent
        "agents": [agent],            # a benchmark pins exactly ONE agent
        "modes": run_modes,
        "language": cfg["language"],
        "concurrency": cfg["concurrency"],
        "per_call_timeout_s": cfg["per_call_timeout_s"],
        "questions": questions,
    }

    bench_name = entity.get("name") or ""
    collected = []

    def write_row(raw):
        # Stamp the benchmark dimension + the per-(question, mode) attempt number on every row. The
        # runner already filled run_id / run_timestamp / config_json / the denormalized golden +
        # expected_sql / expected_tool / actual_tools.
        raw["benchmark_id"] = benchmark_id
        raw["benchmark_name"] = bench_name
        raw["attempt_no"] = registry.next_attempt_no(
            attempt_map, raw.get("question_id"), raw.get("mode"))
        collected.append(raw)

    print("benchmark: run {0} on benchmark {1!r} ({2}) - {3} question(s) x {4} mode(s)".format(
        run_id, bench_name, launch_mode, len(questions), len(run_modes)))
    agent_runner.run_matrix(run_config, write_row)

    # Build the raw frame with the canonical RAW_COLUMNS schema (missing keys -> None so error /
    # timeout rows still conform), then APPEND this run to the raw history (idempotent by run_id).
    if collected:
        frame = pd.DataFrame(
            [{col: row.get(col) for col in schemas.RAW_COLUMNS} for row in collected],
            columns=list(schemas.RAW_COLUMNS),
        )
    else:
        frame = pd.DataFrame(columns=list(schemas.RAW_COLUMNS))
    write_history_dataset(cfg["raw_dataset"], frame, cfg.get("history_keep_runs"))


run()
