"""The benchmark registry + membership model and launch resolution (PURE, stdlib only).

A *benchmark* is a named, unique evaluation campaign pinned to ONE agent. It accumulates the results
of one or more runs; membership is AUTO-DERIVED from the golden question set (rows tagged to the
agent), so the registry itself only carries a small ``redo`` list (questions to re-run at the next
append launch). The registry + the per-question "redo at next run" intent live in the ``benchmark``
PROJECT VARIABLE (so there is no new managed dataset to create): this module parses / normalizes /
mutates that registry and resolves, for a launch, exactly which (question, mode) cells to run.

Design contract: docs/superpowers/specs/2026-06-29-benchmark-v2-append-mode-design.md.

Everything here is pure (no dataiku / pandas, no clock / uuid: the caller mints ids + timestamps) and
NEVER raises - a malformed entry is dropped, not fatal, so the steps keep working while the launcher
edits the registry. The DSS side (benchmark_webapp.dss) reads/writes the variable under a lock.
"""

import json
import re

# Launch modes. ``append`` runs the pending cells plus any flagged "redo at next run"; ``full``
# re-runs every (member question, mode) cell (to show evolution / regression across the benchmark).
LAUNCH_APPEND = "append"
LAUNCH_FULL = "full"
_LAUNCH_MODES = (LAUNCH_APPEND, LAUNCH_FULL)

_STATUS_ACTIVE = "active"
_STATUS_ARCHIVED = "archived"

# Fallback mode key used when the entity carries no modes (agent does not support mode tokens).
DEFAULT_MODE = "default"


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


def _clean(value):
    """Trimmed string, or '' for None / non-string-coercible."""
    if value is None:
        return ""
    try:
        return str(value).strip()
    except Exception:
        return ""


def _bool(value, default=False):
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        s = value.strip().lower()
        if s in ("true", "1", "yes", "y", "oui", "t"):
            return True
        if s in ("false", "0", "no", "n", "non", "f", ""):
            return False
    return default


def _int(value, default=0):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def slug_agent_key(label):
    """A stable logical agent key from a human label. Pure, never raises.

    Lowercase, keep [a-z0-9_], collapse other runs to a single '_', strip leading/trailing '_'.
    Falls back to 'agent' for an empty / symbol-only label.
    """
    s = _clean(label).lower()
    s = re.sub(r"[^a-z0-9]+", "_", s).strip("_")
    return s or "agent"


def names_for_agent(registry, agent_key):
    """Lower-cased benchmark names already used BY THIS AGENT (name uniqueness is per agent)."""
    akey = _clean(agent_key)
    return {_clean(e.get("name")).lower() for e in (registry or {}).values()
            if isinstance(e, dict) and _clean(e.get("agent_key")) == akey and _clean(e.get("name"))}


# --- parse / normalize the registry -----------------------------------------

def _normalize_modes(value):
    """A list of mode strings; falls back to [] (the caller decides a default)."""
    parsed = _coerce_obj(value)
    if isinstance(parsed, list):
        return [m for m in (_clean(x) for x in parsed) if m]
    return []


def _normalize_redo(value):
    """Normalize the redo set into an ordered, de-duped list of question_ids. Never raises."""
    parsed = _coerce_obj(value)
    out, seen = [], set()
    if isinstance(parsed, list):
        for qid in parsed:
            key = _clean(qid)
            if key and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def normalize_entity(raw):
    """Return a normalized benchmark entity, or None when it is unusable. Never raises.

    A usable entity needs a benchmark_id, a name, and a pinned agent (agent_key + project_key +
    agent_id). ``modes`` is a list (possibly empty: the caller / step falls back to DEFAULT_MODE).
    ``redo`` is an ordered, de-duped list of question_ids flagged for re-run at the next append.
    A legacy ``questions`` membership map is silently ignored (membership is now auto-derived from
    the golden dataset by agent_key tag).
    """
    if not isinstance(raw, dict):
        return None
    bid = _clean(raw.get("benchmark_id"))
    name = _clean(raw.get("name"))
    agent_key = _clean(raw.get("agent_key"))
    project_key = _clean(raw.get("project_key"))
    agent_id = _clean(raw.get("agent_id"))
    if not bid or not name or not agent_key or not project_key or not agent_id:
        return None
    status = _clean(raw.get("status")).lower()
    if status not in (_STATUS_ACTIVE, _STATUS_ARCHIVED):
        status = _STATUS_ACTIVE
    return {
        "benchmark_id": bid,
        "name": name,
        "agent_key": agent_key,
        "agent_label": _clean(raw.get("agent_label")) or agent_key,
        "project_key": project_key,
        "agent_id": agent_id,
        "modes": _normalize_modes(raw.get("modes")),
        "status": status,
        "created_at": _clean(raw.get("created_at")),
        "created_by": _clean(raw.get("created_by")),
        "redo": _normalize_redo(raw.get("redo")),
    }


def parse_registry(raw):
    """Parse the ``benchmarks`` block into ``{benchmark_id: entity}``. Pure, never raises.

    ``raw`` is the value of the ``benchmarks`` key (a dict keyed by benchmark_id, or a JSON string of
    one). Malformed / unusable entries are dropped silently. The benchmark_id key is reconciled with
    the entity's own benchmark_id (the entity wins, since normalize_entity validates it).
    """
    parsed = _coerce_obj(raw)
    out = {}
    if isinstance(parsed, dict):
        for key, value in parsed.items():
            # Tolerate an entity that omits benchmark_id by back-filling it from the map key.
            if isinstance(value, dict) and not _clean(value.get("benchmark_id")):
                value = dict(value)
                value["benchmark_id"] = _clean(key)
            entity = normalize_entity(value)
            if entity:
                out[entity["benchmark_id"]] = entity
    elif isinstance(parsed, list):
        for value in parsed:
            entity = normalize_entity(value)
            if entity:
                out[entity["benchmark_id"]] = entity
    return out


def parse_run_request(raw):
    """Parse the ``run_request`` block. Returns ``{benchmark_id, launch_mode}`` or None. Never raises."""
    parsed = _coerce_obj(raw)
    if not isinstance(parsed, dict):
        return None
    bid = _clean(parsed.get("benchmark_id"))
    if not bid:
        return None
    mode = _clean(parsed.get("launch_mode")).lower()
    if mode not in _LAUNCH_MODES:
        mode = LAUNCH_APPEND
    return {"benchmark_id": bid, "launch_mode": mode}


# --- attempt tracking -------------------------------------------------------

def attempt_numbers(scored_rows, benchmark_id, agent_key=None):
    """Map ``(question_id, mode) -> max attempt_no`` seen in this benchmark. Pure, never raises."""
    bid = _clean(benchmark_id)
    akey = _clean(agent_key)
    out = {}
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if _clean(r.get("benchmark_id")) != bid:
            continue
        if akey and _clean(r.get("agent_key")) != akey:
            continue
        qid = _clean(r.get("question_id"))
        if not qid:
            continue
        mode = _clean(r.get("mode"))
        n = _int(r.get("attempt_no"), default=0)
        key = (qid, mode)
        if key not in out or n > out[key]:
            out[key] = n
    return out


def next_attempt_no(attempt_map, question_id, mode):
    """The next attempt number for a (question, mode): max seen + 1 (1 when none). Pure."""
    prior = (attempt_map or {}).get((_clean(question_id), _clean(mode)), 0)
    return _int(prior, default=0) + 1


def benchmark_id_of_run(scored_rows, run_id):
    """The benchmark_id stamped on the rows of a given run_id ('' when unknown). Pure, never raises."""
    rid = _clean(run_id)
    for r in (scored_rows or []):
        if isinstance(r, dict) and _clean(r.get("run_id")) == rid:
            bid = _clean(r.get("benchmark_id"))
            if bid:
                return bid
    return ""


# --- launch resolution ------------------------------------------------------

def done_cells(scored_rows, benchmark_id, agent_key=None):
    """Set of ``(question_id, mode)`` cells already scored in this benchmark. Pure, never raises.

    Per-mode: (Q1, Smart) done does NOT imply (Q1, Pro) done. Each cell is resolved independently.
    """
    bid = _clean(benchmark_id)
    akey = _clean(agent_key)
    out = set()
    for r in (scored_rows or []):
        if not isinstance(r, dict):
            continue
        if _clean(r.get("benchmark_id")) != bid:
            continue
        if akey and _clean(r.get("agent_key")) != akey:
            continue
        qid = _clean(r.get("question_id"))
        mode = _clean(r.get("mode"))
        if qid and mode:
            out.add((qid, mode))
    return out


def _entity_modes(entity):
    """The modes to run for this entity; falls back to [DEFAULT_MODE] when the list is empty."""
    modes = entity.get("modes") if isinstance(entity, dict) else None
    if isinstance(modes, list):
        cleaned = [_clean(m) for m in modes if _clean(m)]
        if cleaned:
            return cleaned
    return [DEFAULT_MODE]


def resolve_to_run(entity, golden_agent_active_ids, prior_scored, launch_mode=LAUNCH_APPEND):
    """The per-mode launch plan ``{mode: [question_id]}`` for one benchmark launch. Pure, never raises.

    Args:
        entity: normalized benchmark entity (from the registry).
        golden_agent_active_ids: active golden question_ids tagged to the entity's agent_key (the
            gate: only these are eligible to run regardless of past attempts).
        prior_scored: already-scored rows for this benchmark (used to detect done cells in append).
        launch_mode: LAUNCH_APPEND or LAUNCH_FULL.

    Returns:
        A dict ``{mode: [question_id]}`` where each mode maps to its ordered list of question_ids.
        Empty modes list -> ``{DEFAULT_MODE: [...]}``.
        Returns ``{}`` for an unusable entity.

    Modes:
        full   : every golden_agent_active_id in every mode (re-run the whole benchmark).
        append : per (qid, mode) cell - include if NOT yet done, OR if qid is in entity.redo.
    """
    if not isinstance(entity, dict):
        return {}
    active_golden = [_clean(x) for x in (golden_agent_active_ids or []) if _clean(x)]
    modes = _entity_modes(entity)
    redo = set(entity.get("redo") or [])
    lmode = _clean(launch_mode).lower()

    if lmode == LAUNCH_FULL:
        return {mode: list(active_golden) for mode in modes}

    # append mode: per-(qid, mode) cell
    bid = _clean(entity.get("benchmark_id"))
    akey = _clean(entity.get("agent_key"))
    cells_done = done_cells(prior_scored, bid, akey)
    plan = {}
    for mode in modes:
        qids = [qid for qid in active_golden
                if (qid, mode) not in cells_done or qid in redo]
        plan[mode] = qids
    return plan


# --- registry mutation (pure: returns a NEW registry dict) ------------------

def _copy_registry(registry):
    out = {}
    for bid, entity in (registry or {}).items():
        if isinstance(entity, dict):
            clone = dict(entity)
            clone["redo"] = list(entity.get("redo") or [])
            clone.pop("questions", None)
            out[_clean(bid) or _clean(entity.get("benchmark_id"))] = clone
    return out


def existing_names(registry):
    """Lower-cased set of benchmark names already in the registry (for uniqueness checks)."""
    return {_clean(e.get("name")).lower() for e in (registry or {}).values()
            if isinstance(e, dict) and _clean(e.get("name"))}


def validate_benchmark_name(name, taken_names):
    """Validate a NEW benchmark name. Returns ``(ok, error_or_None)``. Pure, never raises.

    Non-blank, <= 80 chars, unique (case-insensitive) against ``taken_names``.
    """
    n = _clean(name)
    if not n:
        return False, "name is required"
    if len(n) > 80:
        return False, "name is too long (max 80 characters)"
    taken = {_clean(x).lower() for x in (taken_names or [])}
    if n.lower() in taken:
        return False, "a benchmark with this name already exists"
    return True, None


def create_benchmark(registry, benchmark_id, name, agent, modes, created_at, created_by=""):
    """Return a new registry with a fresh, EMPTY-redo benchmark added. Pure, never raises.

    Membership is auto-derived (active golden rows tagged to the agent), so nothing is seeded here.
    ``agent`` is ``{agent_key, agent_label, project_key, agent_id}``. The caller mints benchmark_id +
    created_at and has validated the name uniqueness (validate_benchmark_name with names_for_agent).
    """
    out = _copy_registry(registry)
    agent = agent if isinstance(agent, dict) else {}
    entity = normalize_entity({
        "benchmark_id": _clean(benchmark_id),
        "name": _clean(name),
        "agent_key": _clean(agent.get("agent_key")),
        "agent_label": _clean(agent.get("agent_label")),
        "project_key": _clean(agent.get("project_key")),
        "agent_id": _clean(agent.get("agent_id")),
        "modes": modes if isinstance(modes, list) else [],
        "status": _STATUS_ACTIVE,
        "created_at": _clean(created_at),
        "created_by": _clean(created_by),
        "redo": [],
    })
    if entity:
        out[entity["benchmark_id"]] = entity
    return out


def delete_benchmark(registry, benchmark_id):
    """Hard-remove a benchmark from the registry. Pure, never raises. Scored rows are untouched."""
    out = _copy_registry(registry)
    out.pop(_clean(benchmark_id), None)
    return out


def set_redo(registry, benchmark_id, question_id, value):
    """Set/clear the 'redo at next run' flag for one member question. Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        qid = _clean(question_id)
        redo = entity.setdefault("redo", [])
        if value and qid and qid not in redo:
            redo.append(qid)
        elif not value and qid in redo:
            redo.remove(qid)
    return out


def reset_redo_for(registry, benchmark_id, question_ids):
    """Clear the redo flag for the given questions (after they ran). Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        drop = {_clean(q) for q in (question_ids or [])}
        entity["redo"] = [q for q in (entity.get("redo") or []) if q not in drop]
    return out


def rename_benchmark(registry, benchmark_id, name):
    """Rename a benchmark (caller validates uniqueness). Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict) and _clean(name):
        entity["name"] = _clean(name)
    return out


def serialize_registry(registry):
    """Return the registry as a plain JSON-friendly dict for writing back to the variable."""
    return _copy_registry(registry)
