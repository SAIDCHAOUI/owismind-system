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
from benchmark.dss_steps.history_io import write_history_dataset


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


# The only keys question_filter recognizes; anything else is a typo that would silently
# widen the run to the WHOLE golden set (one real agent call per question x agent x mode).
_KNOWN_FILTER_KEYS = ("categories", "languages", "question_ids")


def _warn_unknown_filter_keys(question_filter):
    """Log any unrecognized question_filter key so a typo (e.g. 'category' / 'ids') is visible
    in the step log instead of silently running the full matrix. Never raises."""
    if not isinstance(question_filter, dict):
        return
    unknown = [k for k in question_filter if k not in _KNOWN_FILTER_KEYS]
    if unknown:
        print("benchmark: ignoring unknown question_filter key(s) {0} "
              "(known: {1}) - the filter on those keys is NOT applied".format(
                  sorted(unknown), list(_KNOWN_FILTER_KEYS)))


def _matches_filter(row, question_filter):
    """True when a golden row passes the optional question filter (AND across keys)."""
    if not isinstance(question_filter, dict) or not question_filter:
        return True
    checks = (
        ("categories", "category"),
        ("languages", "language"),
        ("question_ids", "question_id"),
    )
    for filter_key, column in checks:
        allowed = question_filter.get(filter_key)
        if allowed:
            allowed_set = {str(v) for v in allowed}
            if str(row.get(column)) not in allowed_set:
                return False
    return True


def run():
    """Execute the benchmark matrix and write the configured raw dataset."""
    cfg = run_params.resolve(_get_variables())

    agents = cfg["agents"]
    if not agents:
        raise ValueError(
            "no valid agent in the 'benchmark' project variable: set "
            "benchmark.agents = a list of {agent_key, project_key, agent_id, modes}"
        )

    # Stamp the run identity here (allowed in a step; not in the agent loop).
    run_id = uuid.uuid4().hex
    run_timestamp = datetime.now().isoformat()

    _warn_unknown_filter_keys(cfg["question_filter"])
    golden = [
        row for row in _load_golden_rows(cfg["golden_dataset"])
        if _matches_filter(row, cfg["question_filter"])
    ]
    if not golden:
        raise ValueError(
            "no active golden question matched the filter in '{0}'; nothing to run"
            .format(cfg["golden_dataset"])
        )

    # The runner resolves every agent's LLM through ONE project handle
    # (project.get_llm(agent_id)); it does not re-open a project per agent. All
    # agents in one run must share the same project_key; when they differ we surface
    # a clear error so the run is split per project rather than failing opaquely.
    project_keys = {a["project_key"] for a in agents}
    if len(project_keys) > 1:
        raise ValueError(
            "all benchmark.agents must share one project_key per run (got {0}); "
            "run them in separate benchmark runs".format(sorted(project_keys))
        )
    project = dataiku.api_client().get_project(agents[0]["project_key"])

    run_config = {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "project": project,           # DSS handle the runner uses to reach the agents
        "agents": agents,
        "modes": cfg["modes"],
        "language": cfg["language"],
        "concurrency": cfg["concurrency"],
        "per_call_timeout_s": cfg["per_call_timeout_s"],
        "questions": golden,
    }

    # Incremental capture: the runner calls write_row(raw) per finished call so a
    # crash mid-run keeps the completed work (each row already carries run_id /
    # run_timestamp / config_json, stamped by the runner). For this small golden
    # set we buffer in memory and write once at the end; for a larger set, swap
    # this buffer for a streaming writer (dataset.get_writer()) keyed on run_id to
    # checkpoint each row as it lands.
    collected = []

    def write_row(raw):
        collected.append(raw)

    agent_runner.run_matrix(run_config, write_row)

    # Build the raw frame with the canonical RAW_COLUMNS schema. Missing keys
    # default to None so partial rows (errors / timeouts) still conform.
    if collected:
        frame = pd.DataFrame(
            [{col: row.get(col) for col in schemas.RAW_COLUMNS} for row in collected],
            columns=list(schemas.RAW_COLUMNS),
        )
    else:
        frame = pd.DataFrame(columns=list(schemas.RAW_COLUMNS))
    # APPEND this run to the raw history (every row carries the fresh run_id), instead of
    # overwriting, so past runs are preserved and the Results app can compare them.
    write_history_dataset(cfg["raw_dataset"], frame, cfg.get("history_keep_runs"))


run()
