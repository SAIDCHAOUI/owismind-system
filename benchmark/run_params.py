"""Single source of run configuration for the benchmark steps (PURE resolver).

Everything a human ever tunes lives in ONE place: a PROJECT variable named
``benchmark`` (a JSON object) under OWIsMind_LAB -> project menu -> Variables
(scenarios have no Variables tab in some DSS versions; project variables always
work and are read here via dataiku.get_custom_variables()). The three scenario
steps call ``resolve(get_custom_variables())`` and read the normalized config from
here. Nothing is hardcoded in the steps (not even the dataset names), so the day to
day workflow is: edit the golden dataset, edit the ``benchmark`` variable, run.
Never the code.

The ``benchmark`` object (every key optional except ``agents`` for the run step):

    {
      "golden_dataset":    "golden_questions_v1_prepared",  // input questions
      "raw_dataset":       "benchmark_runs_raw",            // step 2 output
      "scored_dataset":    "benchmark_runs_scored",         // step 3 output
      "summary_dataset":   "benchmark_summary",             // step 4 output
      "breakdown_dataset": "benchmark_breakdown",           // step 4 output

      "agents": [                                           // who to benchmark
        {"agent_key": "orchestrator",
         "agent_label": "OWIsMind Orchestrator (DEV)",
         "project_key": "OWISMIND_DEV",
         "agent_id": "agent:038G7mlF",
         "modes": true}        // true: test across modes ; false/absent: ONE plain call
      ],

      "modes":        ["Smart", "Pro", "Claude"], // modes tried on mode-aware agents
      "language":     "fr",
      "concurrency":  3,                          // bounded thread pool (clamped 1..8)
      "question_filter": {},                      // {"categories":[...],"question_ids":[...],"languages":[...]}
      "judge_llm_id": null,                       // null -> config.JUDGE_LLM_ID
      "score_all_runs":     false,                // step 3: re-judge every run_id
      "aggregate_all_runs": false                 // step 4: aggregate every run_id
    }

Per-agent ``modes`` flag (the key precision): an agent that supports the
Smart/Pro/Claude modes (the orchestrator) is tested once per requested mode, with
the mode control token appended. An agent that does NOT support them (a plain
visual agent) is called ONCE with the bare question (no token) and uses its default
mode: that single call is enough, exactly as asked. Default when absent: false
(opt in), mirroring the webapp's ``profile.modes`` convention.

Stdlib only, no dataiku / pandas. ``resolve`` is pure and deterministic; it never
raises (a malformed agent entry is skipped, not fatal), so the judge / aggregate
steps keep working even if the agents list is being edited. The run step checks for
at least one valid agent itself.

Design contract: docs/superpowers/specs/2026-06-24-agent-benchmark-evaluation-design.md
"""

import json

from benchmark import config

# Default value for every tunable key. Dataset defaults match what the setup guide
# tells the user to create in OWIsMind_LAB.
DEFAULTS = {
    "golden_dataset": "golden_questions_v1_prepared",
    "raw_dataset": "benchmark_runs_raw",
    "scored_dataset": "benchmark_runs_scored",
    "summary_dataset": "benchmark_summary",
    "breakdown_dataset": "benchmark_breakdown",
    "modes": list(config.MODES),
    "language": "fr",
    "concurrency": config.DEFAULT_CONCURRENCY,
    "per_call_timeout_s": config.PER_CALL_TIMEOUT_S,
    "question_filter": {},
    "judge_llm_id": config.JUDGE_LLM_ID,
    "score_all_runs": False,
    "aggregate_all_runs": False,
    # Optional: where the LAB benchmark webapp reads the webapp's user-suggested questions
    # (cross-project, read-only) and where it records promoted ids. Empty -> the suggestions
    # tab is simply "not configured". Additive; nothing else changes when absent.
    "suggestions": {},
}

_CONCURRENCY_MIN = 1
_CONCURRENCY_MAX = 8


def resolve(variables):
    """Resolve the ``benchmark`` project variable into a normalized config dict.

    ``variables`` is the merged custom-variables dict (``dataiku.get_custom_variables()``).
    Returns a dict carrying every key of ``DEFAULTS`` plus ``agents`` (a list of
    normalized agent descriptors). Pure, never raises.
    """
    raw = _coerce_obj(variables.get("benchmark") if isinstance(variables, dict) else None)
    raw = raw if isinstance(raw, dict) else {}

    cfg = dict(DEFAULTS)
    cfg["golden_dataset"] = _str_or(raw.get("golden_dataset"), DEFAULTS["golden_dataset"])
    cfg["raw_dataset"] = _str_or(raw.get("raw_dataset"), DEFAULTS["raw_dataset"])
    cfg["scored_dataset"] = _str_or(raw.get("scored_dataset"), DEFAULTS["scored_dataset"])
    cfg["summary_dataset"] = _str_or(raw.get("summary_dataset"), DEFAULTS["summary_dataset"])
    cfg["breakdown_dataset"] = _str_or(
        raw.get("breakdown_dataset"), DEFAULTS["breakdown_dataset"])

    cfg["modes"] = _resolve_modes(raw.get("modes"))
    cfg["language"] = _resolve_language(raw.get("language"))
    cfg["concurrency"] = _resolve_concurrency(raw.get("concurrency"))
    cfg["per_call_timeout_s"] = _resolve_timeout(raw.get("per_call_timeout_s"))
    cfg["question_filter"] = _resolve_filter(raw.get("question_filter"))
    cfg["judge_llm_id"] = _str_or(raw.get("judge_llm_id"), DEFAULTS["judge_llm_id"])
    cfg["score_all_runs"] = _coerce_bool(raw.get("score_all_runs"))
    cfg["aggregate_all_runs"] = _coerce_bool(raw.get("aggregate_all_runs"))
    cfg["suggestions"] = _resolve_suggestions(raw.get("suggestions"))
    cfg["agents"] = _resolve_agents(raw.get("agents"))
    return cfg


def _resolve_suggestions(value):
    """Normalize the optional ``suggestions`` block (the LAB webapp's cross-project source).

    Keys (all optional strings): ``connection`` (the SQL connection holding the webapp's
    suggestion table, e.g. SQL_owi), ``table`` (the EXACT physical table name to read,
    e.g. OWISMIND_DEV_owismind_webapp_golden_suggestions_v1), ``promoted_dataset`` (a LAB
    dataset where promoted suggestion ids are recorded so they are never promoted twice).
    Returns ``{}`` when absent or malformed (the suggestions tab then reports not-configured).
    Never raises.
    """
    value = _coerce_obj(value)
    if not isinstance(value, dict):
        return {}
    out = {}
    for key in ("connection", "table", "promoted_dataset"):
        cleaned = _clean(value.get(key))
        if cleaned:
            out[key] = cleaned
    return out


def suggestions_config(cfg):
    """Return the resolved ``suggestions`` block of a config dict (``{}`` when absent)."""
    if isinstance(cfg, dict):
        sug = cfg.get("suggestions")
        if isinstance(sug, dict):
            return sug
    return {}


def _resolve_agents(value):
    """Normalize the agents list: keep well-formed entries, add the modes flag.

    Each kept entry is ``{agent_key, agent_label, project_key, agent_id, modes}``.
    A required field (agent_key / project_key / agent_id) being blank drops that
    entry silently (the run step raises a clear error when none survive). ``modes``
    is coerced to bool, default False. Never raises.
    """
    value = _coerce_obj(value)
    if not isinstance(value, list):
        return []
    agents = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        key = _clean(entry.get("agent_key"))
        project_key = _clean(entry.get("project_key"))
        agent_id = _clean(entry.get("agent_id"))
        if not key or not project_key or not agent_id:
            continue
        agents.append({
            "agent_key": key,
            "agent_label": _clean(entry.get("agent_label")) or key,
            "project_key": project_key,
            "agent_id": agent_id,
            "modes": _coerce_bool(entry.get("modes")),
        })
    return agents


def _resolve_modes(value):
    """Resolve the modes subset (list, JSON list, or comma string).

    Accepts the display names (Smart/Pro/Claude) or their lowercase tokens
    (smart/pro/claude), any case, and returns the canonical display names in
    Smart/Pro/Claude order. An empty or all-unknown selection falls back to every mode.
    """
    parsed = _coerce_obj(value)
    if isinstance(parsed, list):
        items = parsed
    elif isinstance(value, str) and value.strip():
        items = [m.strip() for m in value.split(",") if m.strip()]
    else:
        items = None
    if not items:
        return list(config.MODES)
    requested = set()
    for m in items:
        canon = config.normalize_mode(m)
        if canon:
            requested.add(canon)
    modes = [m for m in config.MODES if m in requested]
    return modes or list(config.MODES)


def _resolve_language(value):
    lang = _clean(value)
    return lang if lang in ("fr", "en") else DEFAULTS["language"]


def _resolve_concurrency(value):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULTS["concurrency"]
    return max(_CONCURRENCY_MIN, min(n, _CONCURRENCY_MAX))


def _resolve_timeout(value):
    try:
        t = float(value)
    except (TypeError, ValueError):
        return DEFAULTS["per_call_timeout_s"]
    return t if t > 0 else DEFAULTS["per_call_timeout_s"]


def _resolve_filter(value):
    value = _coerce_obj(value)
    return value if isinstance(value, dict) else {}


# --- scalar helpers ---------------------------------------------------------

def _coerce_obj(value):
    """Return a dict/list as-is, or parse a JSON string into one (None on failure)."""
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return None


def _coerce_bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "oui"):
            return True
        if s in ("false", "0", "no", "n", "non", ""):
            return False
    return default


def _clean(value):
    """Trimmed string, or '' for None / blank / non-string-coercible."""
    if value is None:
        return ""
    s = str(value).strip()
    return s


def _str_or(value, default):
    """Trimmed string when non-blank, else the default."""
    s = _clean(value)
    return s if s else default
