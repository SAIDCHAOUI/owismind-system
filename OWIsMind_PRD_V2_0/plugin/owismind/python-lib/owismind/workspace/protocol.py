"""Workspace protocol v1: contract constants + strict normalization of one operation.

Single contract: ``plugin/owismind/contracts/workspace_protocol.v1.json`` (shared with
the frontend reducer). The constants below MIRROR that file; they are embedded on
purpose because the plugin zip ships ``python-lib`` but not ``contracts/``, so a
runtime read of the JSON would fail in DSS. Drift is impossible to miss: the parity
test (tests/test_workspace_protocol.py) loads the contract from disk and asserts
every enum, pattern and cap below is identical.

``normalize_op(event_data, default_ts)`` turns ONE raw orchestrator ``eventData``
into the normalized event ``{type: "workspace", v: 1, op, seq, ts, ...payload}`` or
``None``. ``studio.carry`` is backend-generated (Studio continuity): the agent stream
can never send it (``normalize_op`` rejects it); the worker builds it from a validated
base workspace and ``normalize_carry`` re-projects it for the reducer (it never
carries ``suggest.set``: the next steps belong to an answer, not to the board).
Fail-closed per operation: an invalid op is dropped (the caller logs it),
never raises, the run continues. Projection rules (identical for every op):
  - unknown keys are removed; strings are stripped then truncated to their cap;
  - enums (op, kind, status, chart type, tool, origin, size, role) come from a
    whitelist;
  - integers reject booleans; ids are slugs ``^[a-z0-9_-]{1,32}$``;
  - a required field that is missing or invalid rejects the whole op; an invalid
    OPTIONAL field is simply dropped.

Pure stdlib, Python 3.9 compatible, no dataiku import.
"""

import re

PROTOCOL_VERSION = 1
EVENT_TYPE = "workspace"

# --- Caps (mirror contract "caps") --------------------------------------------
MAX_PLAN_STEPS = 10
MAX_NOTES = 30
MAX_WIDGETS = 12
MAX_PROVENANCE = 24
MAX_WORKSPACE_EVENTS_PER_RUN = 80
MAX_WORKSPACE_JSON_CHARS = 200000
MISSION_CHARS = 240
STEP_LABEL_CHARS = 140
NOTE_TITLE_CHARS = 140
NOTE_TEXT_CHARS = 1200
WIDGET_TITLE_CHARS = 200
WIDGET_COMMENT_CHARS = 280
WIDGET_TEXT_CHARS = 4000
TASK_CHARS = 800
MAX_Y_SERIES = 8
# Studio continuity: at most this many base widget ids in studio.continue.remove.
MAX_CARRY_REMOVE = 12
# Next steps (suggest.set): at most this many items, each this long once stripped.
SUGGESTIONS_MAX_ITEMS = 3
SUGGESTION_MIN_CHARS = 8
SUGGESTION_MAX_CHARS = 120

CAPS = {
    "max_plan_steps": MAX_PLAN_STEPS,
    "max_notes": MAX_NOTES,
    "max_widgets": MAX_WIDGETS,
    "max_provenance": MAX_PROVENANCE,
    "max_workspace_events_per_run": MAX_WORKSPACE_EVENTS_PER_RUN,
    "max_workspace_json_chars": MAX_WORKSPACE_JSON_CHARS,
    "mission_chars": MISSION_CHARS,
    "step_label_chars": STEP_LABEL_CHARS,
    "note_title_chars": NOTE_TITLE_CHARS,
    "note_text_chars": NOTE_TEXT_CHARS,
    "widget_title_chars": WIDGET_TITLE_CHARS,
    "widget_comment_chars": WIDGET_COMMENT_CHARS,
    "widget_text_chars": WIDGET_TEXT_CHARS,
    "task_chars": TASK_CHARS,
    "max_y_series": MAX_Y_SERIES,
    "max_carry_remove": MAX_CARRY_REMOVE,
    "suggestions_max_items": SUGGESTIONS_MAX_ITEMS,
    "suggestion_min_chars": SUGGESTION_MIN_CHARS,
    "suggestion_max_chars": SUGGESTION_MAX_CHARS,
}

# Field caps that live in the contract $defs (not in "caps").
STEP_UNIT_CHARS = 40
CHART_COLUMN_CHARS = 128
CHART_AXIS_LABEL_CHARS = 80
UNIT_CHARS = 16
KPI_LABEL_CHARS = 120
KPI_COLUMN_CHARS = 128
AGENT_KEY_CHARS = 64

# --- Enums (mirror contract "enums") ------------------------------------------
OPS = ("plan.set", "plan.step", "note.add", "widget.add", "prov.set", "studio.continue",
       "widget.remove", "studio.carry", "suggest.set")
PLAN_ORIGINS = ("model", "auto")
STEP_STATUSES = ("todo", "running", "done", "error")
NOTE_KINDS = ("plan", "find", "check", "note", "done")
WIDGET_KINDS = ("chart", "table", "kpi", "text")
DATA_WIDGET_KINDS = ("chart", "table", "kpi")
CHART_TYPES = ("bar", "line", "pie", "donut")
CHART_STYLES = ("grouped", "stacked", "horizontal", "area", "smooth", "stepped", "donut")
BINDINGS = ("explicit", "orphan")
RUN_STATUSES = ("running", "done", "stopped", "error")
TOOLS = ("semantic-model-query", "attribute_lookup", "correlate")
# Layout hints. ``size`` is a width hint for the visuals that may need it (a long
# time series, a wide table); ``role`` places a text widget: "section" (default)
# sits on the board, "scope" is the analysis scope shown in the Studio header.
WIDGET_SIZES = ("normal", "wide")
SIZED_WIDGET_KINDS = ("chart", "table")
TEXT_ROLES = ("section", "scope")

ENUMS = {
    "ops": OPS,
    "plan_origins": PLAN_ORIGINS,
    "step_statuses": STEP_STATUSES,
    "note_kinds": NOTE_KINDS,
    "widget_kinds": WIDGET_KINDS,
    "chart_types": CHART_TYPES,
    "chart_styles": CHART_STYLES,
    "bindings": BINDINGS,
    "run_statuses": RUN_STATUSES,
    "tools": TOOLS,
    "widget_sizes": WIDGET_SIZES,
    "text_roles": TEXT_ROLES,
}

# --- Patterns (mirror contract "patterns") ------------------------------------
SQL_ID_PATTERN = r"^s[0-9]+(q|lk|qc)[0-9]+$"
SLUG_PATTERN = r"^[a-z0-9_-]{1,32}$"
EXCHANGE_ID_PATTERN = r"^[A-Za-z0-9_-]{1,128}$"
PATTERNS = {"sql_id": SQL_ID_PATTERN, "slug": SLUG_PATTERN,
            "exchange_id": EXCHANGE_ID_PATTERN}

# fullmatch (not match): "$" would otherwise accept a trailing newline.
_SQL_ID_RE = re.compile(SQL_ID_PATTERN[1:-1])
_SLUG_RE = re.compile(SLUG_PATTERN[1:-1])
_EXCHANGE_ID_RE = re.compile(EXCHANGE_ID_PATTERN[1:-1])
# A sql_id is at most a few characters; bound before running the regex.
_MAX_SQL_ID_CHARS = 32


# --- Field projectors (pure, never raise) -------------------------------------
def is_int(value, minimum=0):
    """True for a real int (bool excluded) >= ``minimum``."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum


def text(value, cap):
    """A stripped string truncated to ``cap``, or None when absent/blank/not a str."""
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:cap]


def slug(value):
    """The value when it is a valid slug id, else None."""
    if isinstance(value, str) and _SLUG_RE.fullmatch(value):
        return value
    return None


def exchange_id(value):
    """The value when it is a valid exchange id (``^[A-Za-z0-9_-]{1,128}$``), else None."""
    if isinstance(value, str) and _EXCHANGE_ID_RE.fullmatch(value):
        return value
    return None


def sql_id(value):
    """The value when it is a valid captured-SQL id (``s{step}q{n}``), else None."""
    if isinstance(value, str) and len(value) <= _MAX_SQL_ID_CHARS and _SQL_ID_RE.fullmatch(value):
        return value
    return None


def ts_value(value):
    """A finite, non-negative number (bool excluded), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")) or value < 0:
        return None
    return value


def plan_step(raw):
    """One plan step ``{id, label[, total, unit]}`` or None (id + label required)."""
    if not isinstance(raw, dict):
        return None
    step_id = slug(raw.get("id"))
    label = text(raw.get("label"), STEP_LABEL_CHARS)
    if step_id is None or label is None:
        return None
    out = {"id": step_id, "label": label}
    if is_int(raw.get("total"), 1):
        out["total"] = raw["total"]
    unit = text(raw.get("unit"), STEP_UNIT_CHARS)
    if unit is not None:
        out["unit"] = unit
    return out


def chart_spec(raw):
    """A chart spec ``{type, x, y[][, style, x_label, y_label, unit]}`` or None."""
    if not isinstance(raw, dict):
        return None
    ctype = raw.get("type")
    x = text(raw.get("x"), CHART_COLUMN_CHARS)
    y = raw.get("y")
    if isinstance(y, str):
        y = [y]
    if ctype not in CHART_TYPES or x is None or not isinstance(y, list):
        return None
    series = []
    for col in y:
        col = text(col, CHART_COLUMN_CHARS)
        if col is not None:
            series.append(col)
        if len(series) >= MAX_Y_SERIES:
            break
    if not series:
        return None
    out = {"type": ctype, "x": x, "y": series}
    if raw.get("style") in CHART_STYLES:
        out["style"] = raw["style"]
    for key, cap in (("x_label", CHART_AXIS_LABEL_CHARS), ("y_label", CHART_AXIS_LABEL_CHARS),
                     ("unit", UNIT_CHARS)):
        value = text(raw.get(key), cap)
        if value is not None:
            out[key] = value
    return out


def kpi_spec(raw):
    """A KPI spec ``{label, value[, delta, delta_pct, unit]}`` or None."""
    if not isinstance(raw, dict):
        return None
    label = text(raw.get("label"), KPI_LABEL_CHARS)
    value = text(raw.get("value"), KPI_COLUMN_CHARS)
    if label is None or value is None:
        return None
    out = {"label": label, "value": value}
    for key in ("delta", "delta_pct"):
        col = text(raw.get(key), KPI_COLUMN_CHARS)
        if col is not None:
            out[key] = col
    unit = text(raw.get("unit"), UNIT_CHARS)
    if unit is not None:
        out["unit"] = unit
    return out


# --- Payload projectors, one per op (also reused by reducer.sanitize) ---------
def plan_set_payload(raw):
    """``{mission, origin, steps[]}``: 1..MAX_PLAN_STEPS valid steps, unique ids."""
    mission = text(raw.get("mission"), MISSION_CHARS)
    origin = raw.get("origin")
    steps_raw = raw.get("steps")
    if mission is None or origin not in PLAN_ORIGINS or not isinstance(steps_raw, list):
        return None
    steps, seen = [], set()
    for item in steps_raw:
        step = plan_step(item)
        if step is None or step["id"] in seen:
            continue
        seen.add(step["id"])
        steps.append(step)
        if len(steps) >= MAX_PLAN_STEPS:
            break
    if not steps:
        return None
    return {"mission": mission, "origin": origin, "steps": steps}


def plan_step_payload(raw):
    """``{step_id[, status, done, add_step]}``; rejected when it changes nothing."""
    step_id = slug(raw.get("step_id"))
    if step_id is None:
        return None
    out = {"step_id": step_id}
    if raw.get("status") in STEP_STATUSES:
        out["status"] = raw["status"]
    if is_int(raw.get("done"), 0):
        out["done"] = raw["done"]
    add_step = plan_step(raw.get("add_step"))
    if add_step is not None:
        out["add_step"] = add_step
    if len(out) == 1:
        return None
    return out


def note_payload(raw):
    """``{id, kind, title[, text, step_id, sql_id]}``."""
    note_id = slug(raw.get("id"))
    kind = raw.get("kind")
    title = text(raw.get("title"), NOTE_TITLE_CHARS)
    if note_id is None or kind not in NOTE_KINDS or title is None:
        return None
    out = {"id": note_id, "kind": kind, "title": title}
    body = text(raw.get("text"), NOTE_TEXT_CHARS)
    if body is not None:
        out["text"] = body
    if slug(raw.get("step_id")) is not None:
        out["step_id"] = raw["step_id"]
    if sql_id(raw.get("sql_id")) is not None:
        out["sql_id"] = raw["sql_id"]
    return out


def widget_payload(raw):
    """``{id, kind, title[, comment, step_id, sql_id, size, role, chart|kpi|text]}``.

    A data widget (chart / table / kpi) REQUIRES a valid ``sql_id`` (never a
    fallback to "the latest result"); a chart requires a valid chart spec, a KPI a
    valid kpi spec, a text widget a non-empty ``text``. ``binding`` is never taken
    from the input: the reducer and the persistence step own it. Layout hints:
    ``size`` is kept on a chart / table only, ``role`` on a text widget only; an
    invalid or misplaced hint is dropped and the widget stays valid. ``origin`` (a
    carried widget's owning exchange) is NEVER taken from here: only the backend
    carry sets it.
    """
    widget_id = slug(raw.get("id"))
    kind = raw.get("kind")
    title = text(raw.get("title"), WIDGET_TITLE_CHARS)
    if widget_id is None or kind not in WIDGET_KINDS or title is None:
        return None
    out = {"id": widget_id, "kind": kind, "title": title}
    comment = text(raw.get("comment"), WIDGET_COMMENT_CHARS)
    if comment is not None:
        out["comment"] = comment
    if slug(raw.get("step_id")) is not None:
        out["step_id"] = raw["step_id"]
    bound = sql_id(raw.get("sql_id"))
    if kind in DATA_WIDGET_KINDS:
        if bound is None:
            return None
        out["sql_id"] = bound
    elif bound is not None:
        out["sql_id"] = bound
    if kind in SIZED_WIDGET_KINDS and raw.get("size") in WIDGET_SIZES:
        out["size"] = raw["size"]
    if kind == "text" and raw.get("role") in TEXT_ROLES:
        out["role"] = raw["role"]
    if kind == "chart":
        chart = chart_spec(raw.get("chart"))
        if chart is None:
            return None
        out["chart"] = chart
    elif kind == "kpi":
        kpi = kpi_spec(raw.get("kpi"))
        if kpi is None:
            return None
        out["kpi"] = kpi
    elif kind == "text":
        body = text(raw.get("text"), WIDGET_TEXT_CHARS)
        if body is None:
            return None
        out["text"] = body
    return out


def widget_add_payload(raw):
    """``widget_payload`` + the optional op attribute ``replaces`` (a widget id)."""
    out = widget_payload(raw)
    if out is None:
        return None
    replaces = slug(raw.get("replaces"))
    if replaces is not None and replaces != out["id"]:
        out["replaces"] = replaces
    return out


def id_list(value, cap):
    """Unique valid slugs of a list, in order, at most ``cap`` (invalid ones dropped)."""
    out = []
    for item in value if isinstance(value, list) else []:
        sid = slug(item)
        if sid is not None and sid not in out:
            out.append(sid)
        if len(out) >= cap:
            break
    return out


def studio_continue_payload(raw):
    """``{[remove]}``: the base widget ids NOT carried (unknown ids are ignored later)."""
    remove = id_list(raw.get("remove"), MAX_CARRY_REMOVE)
    return {"remove": remove} if remove else {}


def widget_remove_payload(raw):
    """``{id}`` of the widget to drop from the board."""
    widget_id = slug(raw.get("id"))
    return {"id": widget_id} if widget_id is not None else None


def carried_widget(raw):
    """One carried widget: the widget projection (no step_id: the base plan is not
    carried) + ``binding`` for a data widget + a REQUIRED valid ``origin``."""
    if not isinstance(raw, dict):
        return None
    origin = exchange_id(raw.get("origin"))
    widget = widget_payload(raw)
    if widget is None or origin is None:
        return None
    widget.pop("step_id", None)
    if widget["kind"] in DATA_WIDGET_KINDS:
        binding = raw.get("binding")
        widget["binding"] = binding if binding in BINDINGS else "explicit"
    widget["origin"] = origin
    return widget


def studio_carry_payload(raw):
    """``{base_exchange_id, widgets[]}``: unique ids, at most MAX_WIDGETS."""
    base = exchange_id(raw.get("base_exchange_id"))
    widgets_raw = raw.get("widgets")
    if base is None or not isinstance(widgets_raw, list):
        return None
    widgets, seen = [], set()
    for item in widgets_raw:
        widget = carried_widget(item)
        if widget is None or widget["id"] in seen:
            continue
        seen.add(widget["id"])
        widgets.append(widget)
        if len(widgets) >= MAX_WIDGETS:
            break
    return {"base_exchange_id": base, "widgets": widgets}


def suggestion_items(value):
    """The valid next-step texts of a list, in order, at most SUGGESTIONS_MAX_ITEMS.

    Each item must be a string whose stripped length (code points) is within
    [SUGGESTION_MIN_CHARS, SUGGESTION_MAX_CHARS]; an out-of-bounds item is DROPPED,
    never truncated (a cut request would not be sendable as is). Duplicates are
    removed case- and whitespace-insensitively (lowercased, whitespace runs
    collapsed); the first occurrence wins and is kept as stripped. Not a list -> [].
    """
    out, seen = [], set()
    for item in value if isinstance(value, list) else []:
        if not isinstance(item, str):
            continue
        item = item.strip()
        if not SUGGESTION_MIN_CHARS <= len(item) <= SUGGESTION_MAX_CHARS:
            continue
        key = " ".join(item.split()).lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
        if len(out) >= SUGGESTIONS_MAX_ITEMS:
            break
    return out


def suggest_set_payload(raw):
    """``{items[]}``: 1..SUGGESTIONS_MAX_ITEMS valid next steps, else None (op dropped)."""
    items = suggestion_items(raw.get("items"))
    return {"items": items} if items else None


def prov_payload(raw):
    """``{sql_id, agent_key, tool, success[, task, step_id, duration_ms, row_count]}``."""
    bound = sql_id(raw.get("sql_id"))
    agent_key = text(raw.get("agent_key"), AGENT_KEY_CHARS)
    tool = raw.get("tool")
    success = raw.get("success")
    if bound is None or agent_key is None or tool not in TOOLS or not isinstance(success, bool):
        return None
    out = {"sql_id": bound, "agent_key": agent_key, "tool": tool, "success": success}
    task = text(raw.get("task"), TASK_CHARS)
    if task is not None:
        out["task"] = task
    if slug(raw.get("step_id")) is not None:
        out["step_id"] = raw["step_id"]
    for key in ("duration_ms", "row_count"):
        if is_int(raw.get(key), 0):
            out[key] = raw[key]
    return out


_PAYLOAD_BY_OP = {
    "plan.set": plan_set_payload,
    "plan.step": plan_step_payload,
    "note.add": note_payload,
    "widget.add": widget_add_payload,
    "prov.set": prov_payload,
    "studio.continue": studio_continue_payload,
    "widget.remove": widget_remove_payload,
    "suggest.set": suggest_set_payload,
}


def _normalize(event_data, default_ts, payload_by_op):
    if not isinstance(event_data, dict):
        return None
    version = event_data.get("v")
    if not is_int(version, 0) or version != PROTOCOL_VERSION:
        return None
    op = event_data.get("op")
    if op not in payload_by_op:
        return None
    seq = event_data.get("seq")
    if not is_int(seq, 1):
        return None
    payload = payload_by_op[op](event_data)
    if payload is None:
        return None
    event = {"type": EVENT_TYPE, "v": PROTOCOL_VERSION, "op": op, "seq": seq}
    ts = ts_value(event_data.get("ts"))
    if ts is None:
        ts = ts_value(default_ts)
    if ts is not None:
        event["ts"] = ts
    event.update(payload)
    return event


def normalize_op(event_data, default_ts=None):
    """One raw WORKSPACE ``eventData`` -> the normalized frontend event, or None.

    Output: ``{"type": "workspace", "v": 1, "op", "seq", "ts", ...payload}``.
    ``ts`` (seconds since run start) is the orchestrator's when valid, else
    ``default_ts`` (the backend chronometer); omitted when neither is a valid
    number. Idempotent: normalizing an already-normalized event returns it unchanged.
    Pure, never raises.
    """
    try:
        return _normalize(event_data, default_ts, _PAYLOAD_BY_OP)
    except Exception:  # pragma: no cover - defensive: never break the stream
        return None


_CARRY_PAYLOAD = {"studio.carry": studio_carry_payload}


def normalize_carry(event_data, default_ts=None):
    """The backend-built ``studio.carry`` event re-projected (same envelope rules as
    ``normalize_op``), or None. Never fed by the agent stream. Pure, never raises."""
    try:
        return _normalize(event_data, default_ts, _CARRY_PAYLOAD)
    except Exception:  # pragma: no cover - defensive
        return None
