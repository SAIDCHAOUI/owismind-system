"""Scenario step 2: run the benchmark matrix -> benchmark_runs_raw.

Copy-pasteable body for a Python step of the ``Run_Benchmark`` scenario in the
DSS project ``OWIsMind_LAB``. Reads the run parameters from scenario variables,
loads the active golden questions, calls the agent once per
(question x agent x mode) capturing the COMPLETE answer (text + SQL + result
rows + artifacts) plus latency / tokens / cost, and writes one row per call to
``benchmark_runs_raw``.

Scenario variables read (all optional except ``bench_agents``):
  - ``bench_agents``        : JSON string, list of agents to benchmark, each
                              {"agent_key", "agent_label", "project_key", "agent_id"}.
                              Example:
                              [{"agent_key":"orchestrator","agent_label":"Orchestrator",
                                "project_key":"OWISMIND_DEV","agent_id":"agent:038G7mlF"}]
  - ``bench_modes``         : JSON list or comma string of modes (subset of
                              eco/medium/high). Default: all three.
  - ``bench_language``      : "fr" or "en". Default "fr".
  - ``bench_concurrency``   : int, bounded thread pool size. Default config.DEFAULT_CONCURRENCY.
  - ``bench_question_filter``: JSON object, optional filter applied on top of
                              active=True. Recognised keys:
                                {"categories": [...], "difficulties": [...],
                                 "answer_types": [...], "question_ids": [...],
                                 "languages": [...]}
                              A question is kept when, for each provided key, its
                              value is in the listed set (AND across keys, OR within).

Input dataset : golden_questions
Output dataset: benchmark_runs_raw  (overwritten with this run's rows; rows are
                tagged by run_id, so historical runs live in prior dataset
                versions / can be unioned downstream by run_id)

Instance safety: the run is a small golden set with a low bounded concurrency and
a hard per-call timeout; agent calls are read-only (SELECT through the semantic
model). No unbounded loops, no aggressive retries.
"""

import json
import uuid
from datetime import datetime

import dataiku
import pandas as pd

from benchmark import config, schemas
from benchmark import agent_runner


# Logical dataset names (managed datasets in OWIsMind_LAB).
GOLDEN_DATASET = "golden_questions"
RAW_DATASET = "benchmark_runs_raw"


# ---------------------------------------------------------------------------
# Scenario variable parsing (defensive: variables arrive as strings)
# ---------------------------------------------------------------------------
def _get_variables():
    """Return the merged scenario / project custom variables dict (never raises)."""
    try:
        return dataiku.get_custom_variables() or {}
    except Exception:
        return {}


def _parse_json_var(variables, name, default):
    """Read a variable that should hold a JSON value; fall back to ``default``."""
    raw = variables.get(name)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return default
    if not isinstance(raw, str):
        return raw
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return default


def _parse_modes(variables):
    """Resolve the modes subset (JSON list, comma string, or default = all)."""
    value = _parse_json_var(variables, "bench_modes", None)
    if value is None:
        raw = variables.get("bench_modes")
        if isinstance(raw, str) and raw.strip():
            value = [m.strip() for m in raw.split(",") if m.strip()]
        else:
            value = list(config.MODES)
    if isinstance(value, str):
        value = [value]
    # Keep only known modes, preserve the canonical eco/medium/high order.
    requested = set(value)
    modes = [m for m in config.MODES if m in requested]
    return modes or list(config.MODES)


def _parse_agents(variables):
    """Resolve and validate the agents list. Raises a clear error when absent."""
    agents = _parse_json_var(variables, "bench_agents", None)
    if not isinstance(agents, list) or not agents:
        raise ValueError(
            "scenario variable 'bench_agents' is required: a JSON list of "
            '{"agent_key","agent_label","project_key","agent_id"} objects'
        )
    clean = []
    required = ("agent_key", "project_key", "agent_id")
    for entry in agents:
        if not isinstance(entry, dict):
            raise ValueError("each bench_agents entry must be an object")
        for field in required:
            if not entry.get(field):
                raise ValueError(
                    "bench_agents entry missing '{0}': {1!r}".format(field, entry)
                )
        clean.append({
            "agent_key": str(entry["agent_key"]),
            "agent_label": str(entry.get("agent_label") or entry["agent_key"]),
            "project_key": str(entry["project_key"]),
            "agent_id": str(entry["agent_id"]),
        })
    return clean


def _parse_concurrency(variables):
    """Resolve the bounded concurrency (instance safety: clamped to [1, 8])."""
    raw = variables.get("bench_concurrency")
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = config.DEFAULT_CONCURRENCY
    return max(1, min(value, 8))


# ---------------------------------------------------------------------------
# Golden question loading + filtering
# ---------------------------------------------------------------------------
def _load_golden_rows():
    """Read golden_questions, normalize, keep active rows. Returns list[dict]."""
    df = dataiku.Dataset(GOLDEN_DATASET).get_dataframe()
    # NaN -> None so the pure normalizer / validator see real blanks.
    df = df.where(pd.notnull(df), None)
    rows = []
    for record in df.to_dict(orient="records"):
        norm = schemas.normalize_golden_row(record)
        if norm.get("active"):
            rows.append(norm)
    return rows


def _matches_filter(row, question_filter):
    """True when a golden row passes the optional question filter (AND across keys)."""
    if not isinstance(question_filter, dict) or not question_filter:
        return True
    checks = (
        ("categories", "category"),
        ("difficulties", "difficulty"),
        ("answer_types", "answer_type"),
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


# ---------------------------------------------------------------------------
# Step body
# ---------------------------------------------------------------------------
def run():
    """Execute the benchmark matrix and write benchmark_runs_raw."""
    variables = _get_variables()

    agents = _parse_agents(variables)
    modes = _parse_modes(variables)
    language = variables.get("bench_language") or "fr"
    if language not in schemas.LANGUAGES:
        language = "fr"
    concurrency = _parse_concurrency(variables)
    question_filter = _parse_json_var(variables, "bench_question_filter", {}) or {}

    # Stamp the run identity here (allowed in a step; not in the agent loop).
    run_id = uuid.uuid4().hex
    run_timestamp = datetime.now().isoformat()

    golden = [
        row for row in _load_golden_rows()
        if _matches_filter(row, question_filter)
    ]
    if not golden:
        raise ValueError(
            "no active golden questions matched the filter; nothing to run"
        )

    # The runner resolves every agent's LLM through ONE project handle
    # (project.get_llm(agent_id)); it does not re-open a project per agent. We
    # resolve that handle from the agents' project_key. All agents in one run are
    # expected to share the same project_key (the default target is a single
    # orchestrator); when they differ we use the first and surface a clear error so
    # the run is split per project rather than failing opaquely on a wrong handle.
    project_keys = {a["project_key"] for a in agents}
    if len(project_keys) > 1:
        raise ValueError(
            "all bench_agents must share one project_key per run (got {0}); "
            "run them in separate benchmark runs".format(sorted(project_keys))
        )
    agent_project_key = agents[0]["project_key"]
    project = dataiku.api_client().get_project(agent_project_key)

    run_config = {
        "run_id": run_id,
        "run_timestamp": run_timestamp,
        "project": project,           # DSS handle the runner uses to reach the agents
        "agents": agents,
        "modes": modes,
        "language": language,
        "question_filter": question_filter,
        "concurrency": concurrency,
        "per_call_timeout_s": config.PER_CALL_TIMEOUT_S,
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

    # Write benchmark_runs_raw with the canonical RAW_COLUMNS schema. Missing keys
    # default to None so partial rows (errors / timeouts) still conform.
    out = dataiku.Dataset(RAW_DATASET)
    if collected:
        frame = pd.DataFrame(
            [{col: row.get(col) for col in schemas.RAW_COLUMNS} for row in collected],
            columns=list(schemas.RAW_COLUMNS),
        )
    else:
        frame = pd.DataFrame(columns=list(schemas.RAW_COLUMNS))
    out.write_with_schema(frame)


run()
