"""The benchmark registry + membership model and launch resolution (PURE, stdlib only).

A *benchmark* is a named, unique evaluation campaign pinned to ONE agent. It accumulates the results
of one or more runs and its question set grows over time (append mode). The registry + per-benchmark
question membership + the per-question "redo at next run" intent live in the ``benchmark`` PROJECT
VARIABLE (so there is no new managed dataset to create): this module parses / normalizes / mutates
that registry and resolves, for a launch, exactly which questions to run and at which attempt number.

Design contract: docs/superpowers/specs/2026-06-29-benchmark-v2-append-mode-design.md.

Everything here is pure (no dataiku / pandas, no clock / uuid: the caller mints ids + timestamps) and
NEVER raises - a malformed entry is dropped, not fatal, so the steps keep working while the launcher
edits the registry. The DSS side (benchmark_webapp.dss) reads/writes the variable under a lock.
"""

import json

# Launch modes. ``append`` runs the pending questions plus any flagged "redo at next run"; ``full``
# re-runs every member question (to show evolution / regression across the whole benchmark).
LAUNCH_APPEND = "append"
LAUNCH_FULL = "full"
_LAUNCH_MODES = (LAUNCH_APPEND, LAUNCH_FULL)

_STATUS_ACTIVE = "active"
_STATUS_ARCHIVED = "archived"


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


# --- parse / normalize the registry -----------------------------------------

def _normalize_modes(value):
    """A list of mode strings; falls back to [] (the caller decides a default)."""
    parsed = _coerce_obj(value)
    if isinstance(parsed, list):
        return [m for m in (_clean(x) for x in parsed) if m]
    return []


def _normalize_questions(value):
    """Normalize the membership map: ``{question_id: {added_at, include_next, active}}``."""
    parsed = _coerce_obj(value)
    out = {}
    if not isinstance(parsed, dict):
        return out
    for qid, meta in parsed.items():
        key = _clean(qid)
        if not key:
            continue
        meta = meta if isinstance(meta, dict) else {}
        out[key] = {
            "added_at": _clean(meta.get("added_at")),
            "include_next": _bool(meta.get("include_next"), default=False),
            "active": _bool(meta.get("active"), default=True),
        }
    return out


def normalize_entity(raw):
    """Return a normalized benchmark entity, or None when it is unusable. Never raises.

    A usable entity needs a benchmark_id, a name, and a pinned agent (agent_key + project_key +
    agent_id). ``modes`` is a list (possibly empty: the caller / step falls back to a default).
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
        "questions": _normalize_questions(raw.get("questions")),
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


# --- launch resolution ------------------------------------------------------

def _member_order(entity):
    """Member question_ids in a deterministic order (by added_at, then question_id)."""
    questions = entity.get("questions") if isinstance(entity, dict) else None
    questions = questions if isinstance(questions, dict) else {}
    items = [(qid, meta) for qid, meta in questions.items()
             if isinstance(meta, dict) and meta.get("active", True)]
    items.sort(key=lambda it: (_clean(it[1].get("added_at")), it[0]))
    return [qid for qid, _ in items]


def done_question_ids(scored_rows, benchmark_id, agent_key=None):
    """Set of question_ids with at least one scored attempt in this benchmark. Pure, never raises.

    A question is "done" at the QUESTION level (any mode counts), matching the launch semantics: a
    launch runs a question across all the benchmark's modes together.
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
        if qid:
            out.add(qid)
    return out


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


def resolve_to_run(entity, scored_rows, golden_active_ids, launch_mode=LAUNCH_APPEND):
    """The ORDERED list of question_ids to run for one launch of ``entity``. Pure, never raises.

    - members = the entity's active membership that is ALSO an active golden question.
    - ``full``  : every member (re-run the whole benchmark -> evolution / regression).
    - ``append``: members not yet done, plus members flagged ``include_next`` (the "redo" intent).
    The ``golden_active_ids`` gate drops a member whose golden row was deactivated / deleted.
    """
    if not isinstance(entity, dict):
        return []
    active_golden = set(_clean(x) for x in (golden_active_ids or []))
    members = [qid for qid in _member_order(entity) if qid in active_golden]
    mode = _clean(launch_mode).lower()
    if mode == LAUNCH_FULL:
        return members
    done = done_question_ids(scored_rows, entity.get("benchmark_id"), entity.get("agent_key"))
    questions = entity.get("questions") or {}
    out = []
    for qid in members:
        meta = questions.get(qid) if isinstance(questions.get(qid), dict) else {}
        if qid not in done or _bool(meta.get("include_next"), default=False):
            out.append(qid)
    return out


def benchmark_id_of_run(scored_rows, run_id):
    """The benchmark_id stamped on the rows of a given run_id ('' when unknown). Pure, never raises."""
    rid = _clean(run_id)
    for r in (scored_rows or []):
        if isinstance(r, dict) and _clean(r.get("run_id")) == rid:
            bid = _clean(r.get("benchmark_id"))
            if bid:
                return bid
    return ""


# --- registry mutation (pure: returns a NEW registry dict) ------------------

def _copy_registry(registry):
    out = {}
    for bid, entity in (registry or {}).items():
        if isinstance(entity, dict):
            clone = dict(entity)
            clone["questions"] = {q: dict(m) for q, m in (entity.get("questions") or {}).items()
                                  if isinstance(m, dict)}
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


def create_benchmark(registry, benchmark_id, name, agent, modes, created_at,
                     created_by="", question_ids=None):
    """Return a new registry with a fresh benchmark added. Pure, never raises.

    ``agent`` is ``{agent_key, agent_label, project_key, agent_id}``. ``question_ids`` seeds the
    membership (all pending, include_next=False). The caller mints ``benchmark_id`` + ``created_at``
    and has validated the name uniqueness (validate_benchmark_name).
    """
    out = _copy_registry(registry)
    bid = _clean(benchmark_id)
    agent = agent if isinstance(agent, dict) else {}
    questions = {}
    for qid in (question_ids or []):
        key = _clean(qid)
        if key:
            questions[key] = {"added_at": _clean(created_at), "include_next": False, "active": True}
    entity = normalize_entity({
        "benchmark_id": bid,
        "name": _clean(name),
        "agent_key": _clean(agent.get("agent_key")),
        "agent_label": _clean(agent.get("agent_label")),
        "project_key": _clean(agent.get("project_key")),
        "agent_id": _clean(agent.get("agent_id")),
        "modes": modes if isinstance(modes, list) else [],
        "status": _STATUS_ACTIVE,
        "created_at": _clean(created_at),
        "created_by": _clean(created_by),
        "questions": questions,
    })
    if entity:
        out[entity["benchmark_id"]] = entity
    return out


def add_questions(registry, benchmark_id, question_ids, added_at):
    """Add member questions to a benchmark (pending, include_next=False). Idempotent. Pure."""
    out = _copy_registry(registry)
    bid = _clean(benchmark_id)
    entity = out.get(bid)
    if not isinstance(entity, dict):
        return out
    questions = entity.setdefault("questions", {})
    for qid in (question_ids or []):
        key = _clean(qid)
        if not key:
            continue
        if key in questions:
            # Re-adding an existing member re-activates it but keeps its run/redo state.
            questions[key]["active"] = True
        else:
            questions[key] = {"added_at": _clean(added_at), "include_next": False, "active": True}
    return out


def remove_question(registry, benchmark_id, question_id):
    """Remove a member question from a benchmark (drops the membership row). Pure, never raises.

    Past results for that question stay in the scored table; only the membership is removed, so the
    question no longer runs nor counts toward the benchmark's pending/score going forward.
    """
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        entity.get("questions", {}).pop(_clean(question_id), None)
    return out


def set_include_next(registry, benchmark_id, question_id, value):
    """Set the "redo at next run" flag on one member question. Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        meta = entity.get("questions", {}).get(_clean(question_id))
        if isinstance(meta, dict):
            meta["include_next"] = bool(value)
    return out


def reset_include_next_for(registry, benchmark_id, question_ids):
    """Clear the redo flag for the given member questions (after they ran). Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        questions = entity.get("questions", {})
        for qid in (question_ids or []):
            meta = questions.get(_clean(qid))
            if isinstance(meta, dict):
                meta["include_next"] = False
    return out


def rename_benchmark(registry, benchmark_id, name):
    """Rename a benchmark (caller validates uniqueness). Pure, never raises."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict) and _clean(name):
        entity["name"] = _clean(name)
    return out


def archive_benchmark(registry, benchmark_id):
    """Mark a benchmark archived (kept for consultation, hidden from the active list). Pure."""
    out = _copy_registry(registry)
    entity = out.get(_clean(benchmark_id))
    if isinstance(entity, dict):
        entity["status"] = _STATUS_ARCHIVED
    return out


def serialize_registry(registry):
    """Return the registry as a plain JSON-friendly dict for writing back to the variable."""
    return _copy_registry(registry)
