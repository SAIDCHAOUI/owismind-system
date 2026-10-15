"""Pure workspace reducer (Python 3.9): normalized events -> reduced workspace state.

SAME semantics as the frontend reducer (``frontend/src/composables/workspaceModel.js``);
both are pinned by the shared fixtures ``contracts/fixtures/*.json``. The rules:

  - every event is re-normalized first (``protocol.normalize_op``, idempotent), so a
    direct caller can never bypass the caps;
  - ``seq`` gives a total order: an event whose ``seq`` is not strictly greater than
    ``last_seq`` is a replay and is ignored entirely; an accepted event advances
    ``last_seq`` even when its op turns out to be a semantic no-op;
  - ``plan.set``: the first one creates the plan (``version`` 1), any later one
    REPLACES it completely (``version`` + 1); notes and widgets keep their step_id.
    Steps start ``todo``; a step with a ``total`` starts with ``done: 0``;
  - ``plan.step``: ignored without a plan. ``add_step`` appends a new step (unknown
    id, plan under MAX_PLAN_STEPS) BEFORE ``status`` / ``done`` are applied to the
    step ``step_id`` (so one op can add and start a step); unknown step_id = no-op;
  - ``note.add`` / ``widget.add``: appended in arrival order, first id wins
    (a duplicate id is ignored), capped at MAX_NOTES / MAX_WIDGETS. A data widget
    gets ``binding: "explicit"``; a text widget has no binding. ``ts`` is copied;
  - ``prov.set``: keyed by ``sql_id``; a known key is overwritten in place (last
    wins, position kept), a new key is added while under MAX_PROVENANCE;
  - ``summary`` is derived after every event: ``widget_ids_by_step`` (widget ids
    per step_id, in widget order) and ``sql_ids`` (unique, in this order:
    provenance keys, then widget sql_ids, then note sql_ids).

``finalize`` (backend only, at the end of a run) stamps the run status + exchange id
and marks each data widget ``orphan`` when its sql_id matches no captured SQL of the
run. ``sanitize`` re-projects a stored document at read time (defense in depth).
All functions are pure and never mutate their input.
"""

import copy

from owismind.workspace import protocol as p


def empty_state():
    """A fresh reduced state for a run that has not emitted anything yet."""
    return {
        "v": p.PROTOCOL_VERSION,
        "status": "running",
        "last_seq": 0,
        "plan": None,
        "notes": [],
        "widgets": [],
        "provenance": {},
        "summary": {"widget_ids_by_step": {}, "sql_ids": []},
    }


def is_empty(state):
    """True when the state carries no plan, note, widget nor provenance."""
    if not isinstance(state, dict):
        return True
    return not (state.get("plan") or state.get("notes") or state.get("widgets")
                or state.get("provenance"))


def _summary(state):
    """Derived index: widget ids per step + every referenced sql_id (ordered)."""
    by_step = {}
    for widget in state["widgets"]:
        step_id = widget.get("step_id")
        if step_id:
            by_step.setdefault(step_id, []).append(widget["id"])
    sql_ids, seen = [], set()

    def _add(value):
        if value and value not in seen:
            seen.add(value)
            sql_ids.append(value)

    for key in state["provenance"]:
        _add(key)
    for widget in state["widgets"]:
        _add(widget.get("sql_id"))
    for note in state["notes"]:
        _add(note.get("sql_id"))
    return {"widget_ids_by_step": by_step, "sql_ids": sql_ids}


def _new_step(step):
    """A plan step as stored: status todo, done 0 when a total is declared."""
    out = {"id": step["id"], "label": step["label"], "status": "todo"}
    if "total" in step:
        out["total"] = step["total"]
        out["done"] = 0
    if "unit" in step:
        out["unit"] = step["unit"]
    return out


def _apply_plan_set(state, event):
    previous = state.get("plan")
    version = previous["version"] + 1 if isinstance(previous, dict) else 1
    state["plan"] = {
        "version": version,
        "origin": event["origin"],
        "mission": event["mission"],
        "steps": [_new_step(s) for s in event["steps"]],
    }


def _apply_plan_step(state, event):
    plan = state.get("plan")
    if not isinstance(plan, dict):
        return
    steps = plan["steps"]
    added = event.get("add_step")
    if added is not None and len(steps) < p.MAX_PLAN_STEPS \
            and all(s["id"] != added["id"] for s in steps):
        steps.append(_new_step(added))
    for step in steps:
        if step["id"] == event["step_id"]:
            if "status" in event:
                step["status"] = event["status"]
            if "done" in event:
                step["done"] = event["done"]
            break


def _entry(event, keys):
    """Copy the present ``keys`` of an event into a stored entry (+ its ts)."""
    out = {k: copy.deepcopy(event[k]) for k in keys if k in event}
    if "ts" in event:
        out["ts"] = event["ts"]
    return out


_NOTE_KEYS = ("id", "kind", "title", "text", "step_id", "sql_id")
_WIDGET_KEYS = ("id", "kind", "title", "comment", "step_id", "sql_id", "chart", "kpi", "text")
_PROV_KEYS = ("agent_key", "tool", "task", "step_id", "duration_ms", "row_count", "success")


def _apply_note(state, event):
    notes = state["notes"]
    if len(notes) >= p.MAX_NOTES or any(n["id"] == event["id"] for n in notes):
        return
    notes.append(_entry(event, _NOTE_KEYS))


def _apply_widget(state, event):
    widgets = state["widgets"]
    if len(widgets) >= p.MAX_WIDGETS or any(w["id"] == event["id"] for w in widgets):
        return
    widget = _entry(event, _WIDGET_KEYS)
    if widget["kind"] in p.DATA_WIDGET_KINDS:
        widget["binding"] = "explicit"
    widgets.append(widget)


def _apply_prov(state, event):
    provenance = state["provenance"]
    key = event["sql_id"]
    if key not in provenance and len(provenance) >= p.MAX_PROVENANCE:
        return
    entry = {k: event[k] for k in _PROV_KEYS if k in event}
    provenance[key] = entry


_HANDLERS = {
    "plan.set": _apply_plan_set,
    "plan.step": _apply_plan_step,
    "note.add": _apply_note,
    "widget.add": _apply_widget,
    "prov.set": _apply_prov,
}


def apply(state, event):
    """Return the NEW state after one event (the input state is never mutated).

    An invalid event (fails normalization) or a replayed ``seq`` returns the state
    unchanged (same content, new object)."""
    base = state if isinstance(state, dict) else empty_state()
    normalized = p.normalize_op(event)
    if normalized is None or normalized["seq"] <= base.get("last_seq", 0):
        return copy.deepcopy(base)
    new = copy.deepcopy(base)
    new["last_seq"] = normalized["seq"]
    _HANDLERS[normalized["op"]](new, normalized)
    new["summary"] = _summary(new)
    return new


def reduce_events(events, state=None):
    """Fold a list of events from ``state`` (default: an empty state)."""
    current = state if isinstance(state, dict) else empty_state()
    for event in events or []:
        current = apply(current, event)
    return current


def finalize(state, status, exchange_id=None, known_sql_ids=None):
    """The persisted form at the end of a run (pure).

    Stamps ``status`` (when a valid run status) and ``exchange_id``. With
    ``known_sql_ids`` (the sql_ids actually captured in the run), every data widget
    is re-bound: ``explicit`` when its sql_id was captured, ``orphan`` otherwise -
    an orphan widget renders an honest empty state, never another query's rows.
    """
    new = copy.deepcopy(state if isinstance(state, dict) else empty_state())
    if status in p.RUN_STATUSES:
        new["status"] = status
    if isinstance(exchange_id, str) and exchange_id:
        new["exchange_id"] = exchange_id
    if known_sql_ids is not None:
        known = set(known_sql_ids)
        for widget in new.get("widgets") or []:
            if widget.get("kind") in p.DATA_WIDGET_KINDS:
                widget["binding"] = "explicit" if widget.get("sql_id") in known else "orphan"
    return new


_MAX_EXCHANGE_ID_CHARS = 128


def sanitize(doc):
    """Re-project a stored workspace document onto the strict reduced shape.

    Read-time defense in depth: every entry goes through the same projectors as the
    live events, caps are re-applied, ``summary`` is recomputed. Returns None for a
    document that is not a v1 workspace. Never raises.
    """
    try:
        if not isinstance(doc, dict) or doc.get("v") != p.PROTOCOL_VERSION \
                or isinstance(doc.get("v"), bool):
            return None
        state = empty_state()
        status = doc.get("status")
        state["status"] = status if status in p.RUN_STATUSES else "error"
        exchange_id = doc.get("exchange_id")
        if isinstance(exchange_id, str) and exchange_id:
            state["exchange_id"] = exchange_id[:_MAX_EXCHANGE_ID_CHARS]
        if p.is_int(doc.get("last_seq"), 0):
            state["last_seq"] = doc["last_seq"]

        plan = doc.get("plan")
        if isinstance(plan, dict) and plan.get("origin") in p.PLAN_ORIGINS:
            mission = p.text(plan.get("mission"), p.MISSION_CHARS)
            steps, seen = [], set()
            for raw in plan.get("steps") or []:
                step = p.plan_step(raw)
                if step is None or step["id"] in seen:
                    continue
                seen.add(step["id"])
                stored = _new_step(step)
                if raw.get("status") in p.STEP_STATUSES:
                    stored["status"] = raw["status"]
                if p.is_int(raw.get("done"), 0):
                    stored["done"] = raw["done"]
                steps.append(stored)
                if len(steps) >= p.MAX_PLAN_STEPS:
                    break
            if mission is not None and steps:
                version = plan.get("version")
                state["plan"] = {
                    "version": version if p.is_int(version, 1) else 1,
                    "origin": plan["origin"],
                    "mission": mission,
                    "steps": steps,
                }

        seen_notes = set()
        for raw in doc.get("notes") or []:
            if not isinstance(raw, dict):
                continue
            note = p.note_payload(raw)
            if note is None or note["id"] in seen_notes:
                continue
            seen_notes.add(note["id"])
            if p.ts_value(raw.get("ts")) is not None:
                note["ts"] = raw["ts"]
            state["notes"].append(note)
            if len(state["notes"]) >= p.MAX_NOTES:
                break

        seen_widgets = set()
        for raw in doc.get("widgets") or []:
            if not isinstance(raw, dict):
                continue
            widget = p.widget_payload(raw)
            if widget is None or widget["id"] in seen_widgets:
                continue
            seen_widgets.add(widget["id"])
            if widget["kind"] in p.DATA_WIDGET_KINDS:
                binding = raw.get("binding")
                widget["binding"] = binding if binding in p.BINDINGS else "explicit"
            if p.ts_value(raw.get("ts")) is not None:
                widget["ts"] = raw["ts"]
            state["widgets"].append(widget)
            if len(state["widgets"]) >= p.MAX_WIDGETS:
                break

        provenance = doc.get("provenance")
        if isinstance(provenance, dict):
            for key, raw in provenance.items():
                if not isinstance(raw, dict):
                    continue
                entry = p.prov_payload(dict(raw, sql_id=key))
                if entry is None:
                    continue
                entry.pop("sql_id", None)
                state["provenance"][key] = entry
                if len(state["provenance"]) >= p.MAX_PROVENANCE:
                    break

        state["summary"] = _summary(state)
        return state
    except Exception:  # pragma: no cover - defensive: a corrupt row reads as absent
        return None
