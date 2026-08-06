"""In-backend orchestrator engine ("native engine", chantier B 2026-08-06).

An alternative chat engine that runs the ORCHESTRATION LOOP inside the plugin
backend itself (LLM Mesh completion + tool calls, per the Dataiku developer
guide) instead of invoking the OWIsMind_orchestrator Code Agent. The existing
Code Agents (revenue / tickets specialists) remain the SUB-agents: each enabled
capability of the Config & Prompt Hub becomes one delegation tool, executed by
streaming the sub-agent through the proven ``streaming.run_agent_streamed``
machinery (so Evidence capture, SQL surfacing and the timeline behave exactly
as today). The presentation tools (show_chart / show_table / show_kpi) are
executed NATIVELY here: the backend validates the spec against the latest
captured result and emits the frozen ``artifact`` event itself.

Why in-backend: the engine has direct access to everything the backend already
knows (screen context blocks, captured results, run settings) with no Code
Agent re-paste cycle, while producing the EXACT same normalized event stream
(``agent_event`` / ``answer_delta`` / ``narration`` / ``generated_sql`` /
``artifact`` / ``usage_summary`` / ``trace``) - the worker, the persistence
layer and the frontend are untouched.

Selection is per whitelist entry: an admin sets ``profile.native_engine`` on an
enabled agent and the worker routes its runs here (dual-path: the flag off means
the exact legacy Code Agent path). The single source of truth for capabilities
stays the hub seed ``/python/owismind_hub/capabilities.json`` in the DSS project
library, read via the public API with a bounded TTL cache and an embedded
fallback (fail-safe: the engine never dies on a hub read problem).

Instance safety: at most ``MAX_LLM_TURNS`` model iterations and
``MAX_SUBAGENT_CALLS`` specialist rounds per run; every sub-call is bounded and
individually caught (one failing specialist degrades to an honest tool error,
never a dead run); no SQL is executed here (the specialists' governed tools own
that); the worker's cooperative stop keeps its per-mode wall-clock authority.
"""

import json
import logging
import re
import time

import dataiku

from owismind.agents import streaming

logger = logging.getLogger(__name__)

# --- LLM Mesh model ids (mirror of the Code Agent CONFIG - L172/L173: the
# mode -> model mapping is COPIED in every engine; change them in lockstep). ---
GEMINI_FLASH_LITE_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite"
GEMINI_FLASH_ID = "openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash"
SONNET_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-5"
DEFAULT_MODE = "smart"
LLM_BY_MODE = {
    "smart": GEMINI_FLASH_LITE_ID,
    "pro": GEMINI_FLASH_ID,
    "claude": SONNET_ID,
}

# --- Hub capabilities (single source of truth, read from the project library) --
HUB_CAPABILITIES_PATH = "/python/owismind_hub/capabilities.json"
_CAPS_CACHE_TTL_SECONDS = 300
_caps_cache = None  # (caps_dict, monotonic_ts)

# Minimal embedded fallback mirroring the two live specialists (ids preserved by
# the DEV -> prod clone). Used ONLY when the hub file cannot be read or parsed;
# the hub file remains authoritative whenever it is reachable.
EMBEDDED_CAPABILITIES = {
    "revenue_expert": {
        "kind": "agent",
        "agent_id": "agent:bHrWLyOL",
        "tool_name": "ask_revenue_expert",
        "planner_description": (
            "The OWI customer revenue expert (DRIVE_Revenues): totals, "
            "breakdowns, rankings, comparisons, trends, scenario figures."),
        "pass_context": True,
        "enabled": True,
    },
    "tickets_expert": {
        "kind": "agent",
        "agent_id": "agent:NcE9LD2i",
        "tool_name": "ask_tickets_expert",
        "planner_description": (
            "The OWI trouble-tickets expert (TroubleTickets_year): incident "
            "counts, durations, breakdowns and trends."),
        "pass_context": True,
        "enabled": True,
    },
}

# --- Loop bounds (instance safety + readable runs) ----------------------------
MAX_LLM_TURNS = 8
MAX_SUBAGENT_CALLS = 4
MAX_ARTIFACTS = 6
SUBAGENT_TASK_MAX_CHARS = 4000
MAX_TOOL_OUTPUT_CHARS = 6000
ANSWER_DELTA_CHUNK_CHARS = 400

# Machine control tokens the backend appends for token-aware agents; the native
# engine consumes mode/lang directly, then STRIPS every token before any LLM call
# (mirror of the Code Agent's _CTRL_TOKEN_RE discipline).
_LANG_TOKEN_RE = re.compile(r"⟦owi:lang=([a-z]+)⟧")
_CTRL_TOKEN_RE = re.compile(r"⟦owi:[a-z_]+=[^⟧]*⟧")

CHART_TYPES = ("line", "bar", "pie")

# Compact native persona: the same non-negotiable contracts as the Code Agent
# (honesty firewall + output contract), self-contained so the engine never
# depends on the hub prompt files to behave safely.
PERSONA = (
    "You are OWIsMind, the internal data assistant of Orange Wholesale "
    "International, running inside the OWIsMind web app.\n"
    "\n"
    "# HONESTY FIREWALL (non-negotiable)\n"
    "You hold NO business data yourself. Every figure you give MUST come from a "
    "specialist tool result in THIS conversation. Never invent, extrapolate or "
    "deny a figure: if no specialist covers a domain, say you have no AGENT for "
    "it (never 'the data does not exist'). Quote figures verbatim with their "
    "scope (scenario, period, currency).\n"
    "\n"
    "# HOW TO WORK\n"
    "- Delegate any data question to the matching specialist tool with ONE "
    "self-contained task (name the exact entity, scenario/phase and period; the "
    "specialist does not see the conversation).\n"
    "- The [ON SCREEN NOW] block describes what the user currently sees in the "
    "app (their filters, computed figures, charts). When the user says 'this' "
    "or asks about the view, they mean THAT. Its DB-computed figures are "
    "grounded: you may quote them verbatim.\n"
    "- Data belongs in the Evidence side panel, never in your text: render "
    "multi-value results with show_chart / show_table / show_kpi (a markdown "
    "table in your answer is forbidden), then COMMENT: trend, key figures, the "
    "so-what. Format every figure in your text with thousands separators.\n"
    "- For every chart give a clear title, x_label, y_label, the unit and a "
    "one-sentence description.\n"
    "- Answer in the user's language (the final context line of the turn is "
    "authoritative).\n"
)


# =============================================================================
# Capabilities (hub read + cache + fallback)
# =============================================================================
def _read_hub_capabilities(project):
    """Read and parse the hub capabilities seed from the project library.

    Returns the parsed dict or raises (caller guards). Uses the public library
    API only; the file is the SAME seed the Code Agents load at startup.
    """
    library = project.get_library()
    handle = library.get_file(HUB_CAPABILITIES_PATH)
    raw = handle.read()
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("capabilities seed is not an object")
    return value


def _valid_capability(entry):
    """Minimal structural gate on one hub entry (never trust a partial edit)."""
    return (
        isinstance(entry, dict)
        and isinstance(entry.get("agent_id"), str)
        and entry["agent_id"].startswith("agent:")
        and isinstance(entry.get("tool_name"), str)
        and bool(entry.get("tool_name"))
        and isinstance(entry.get("planner_description"), str)
    )


def get_capabilities(project):
    """The enabled hub capabilities ``{key: entry}`` (TTL cache + fallback).

    Best-effort by design: a hub read/parse failure logs once and serves the
    embedded fallback so the chat never dies on a library hiccup. Only entries
    passing the structural gate AND flagged ``enabled`` are returned.
    """
    global _caps_cache
    now = time.monotonic()
    if _caps_cache is not None and (now - _caps_cache[1]) < _CAPS_CACHE_TTL_SECONDS:
        raw = _caps_cache[0]
    else:
        try:
            raw = _read_hub_capabilities(project)
        except Exception:
            logger.exception("native engine - hub capabilities read failed; "
                             "serving embedded fallback")
            raw = EMBEDDED_CAPABILITIES
        _caps_cache = (raw, now)
    out = {}
    seen_tools = set()
    for key in sorted(raw):
        entry = raw[key]
        if not (_valid_capability(entry) and entry.get("enabled")):
            continue
        # Duplicate tool_name guard: two entries with the same tool would
        # silently shadow each other in the dispatch map - keep the first
        # (deterministic sorted order) and log the clash.
        if entry["tool_name"] in seen_tools:
            logger.warning("native engine - duplicate tool_name %r (entry %s "
                           "skipped)", entry["tool_name"], key)
            continue
        seen_tools.add(entry["tool_name"])
        out[key] = entry
    if not out:
        # An all-disabled or fully malformed registry still yields the embedded
        # specialists: an orchestrator with zero tools would be a dead chat.
        out = {k: v for k, v in EMBEDDED_CAPABILITIES.items() if v.get("enabled")}
    return out


def invalidate_capabilities_cache():
    """Test/maintenance hook: drop the TTL cache."""
    global _caps_cache
    _caps_cache = None


# =============================================================================
# Tool specs
# =============================================================================
def build_tool_specs(caps):
    """The Mesh tool list: one delegation tool per capability + the three
    presentation tools (same schemas as the Code Agent, ``title`` required on
    show_chart so charts never ship unlabeled)."""
    specs = []
    for key in sorted(caps):
        cap = caps[key]
        specs.append({
            "type": "function",
            "function": {
                "name": cap["tool_name"],
                # Bounded: an over-long hub description must not bloat the prompt.
                "description": cap["planner_description"][:600] + (
                    " The task must be SELF-CONTAINED: name the exact entity, "
                    "the scenario/phase and the exact period inside the task."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string",
                                 "description": "A complete, self-contained "
                                                "question for the specialist."},
                    },
                    "required": ["task"],
                },
            },
        })
    specs.append({
        "type": "function",
        "function": {
            "name": "show_chart",
            "description": (
                "Render the LATEST specialist result as an interactive chart in "
                "the Evidence side panel, then COMMENT on it (never reprint the "
                "rows). 'line' = evolution over time; 'bar' = compare across "
                "categories; 'pie' = share of a total. x and y MUST be EXACT "
                "column names of the latest result. `title` is REQUIRED; ALWAYS "
                "also give x_label, y_label, the unit and a one-sentence "
                "description."),
            "parameters": {
                "type": "object",
                "properties": {
                    "chart_type": {"type": "string", "enum": list(CHART_TYPES)},
                    "title": {"type": "string"},
                    "x": {"type": "string"},
                    "y": {"type": "array", "items": {"type": "string"}},
                    "style": {"type": "string"},
                    "x_label": {"type": "string"},
                    "y_label": {"type": "string"},
                    "unit": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["chart_type", "x", "y", "title"],
            },
        },
    })
    specs.append({
        "type": "function",
        "function": {
            "name": "show_table",
            "description": (
                "Render the LATEST specialist result as a full table in the "
                "Evidence side panel, then COMMENT on it. The ONLY allowed way "
                "to show a list/ranking."),
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": [],
            },
        },
    })
    specs.append({
        "type": "function",
        "function": {
            "name": "show_kpi",
            "description": (
                "Render ONE headline figure of the LATEST specialist result as "
                "a big KPI card ('value' = the EXACT column holding the figure; "
                "optional delta / delta_pct columns), then comment."),
            "parameters": {
                "type": "object",
                "properties": {
                    "label": {"type": "string"},
                    "value": {"type": "string"},
                    "delta": {"type": "string"},
                    "delta_pct": {"type": "string"},
                    "unit": {"type": "string"},
                },
                "required": ["value"],
            },
        },
    })
    return specs


# =============================================================================
# Small helpers
# =============================================================================
# Languages the engine recognizes (mirror of the backend's supported UI locales).
_KNOWN_LANGS = ("fr", "en")


def resolve_mode(explicit_mode):
    """The run's response mode: the ROUTE-resolved value only, else the default.

    The engine deliberately never scans message text for a mode token: the
    worker always hands over the route-resolved mode, so any ``owi:mode`` token
    found in the text of a modes-OFF agent could only be user-forged (a free
    upgrade to the most expensive tier). Tokens are still stripped before every
    LLM call by ``strip_control_tokens``."""
    return explicit_mode if explicit_mode in LLM_BY_MODE else DEFAULT_MODE


def parse_lang(messages):
    """The authoritative reply language: the LAST valid ``owi:lang`` token
    ('fr' default). Last-token discipline (the backend appends its token at the
    END of the message, so a user-typed token earlier can never win); an unknown
    language string is ignored rather than trusted."""
    for m in reversed(messages or []):
        for token in reversed(_LANG_TOKEN_RE.findall(m.get("content") or "")):
            if token in _KNOWN_LANGS:
                return token
    return "fr"


def strip_control_tokens(text):
    """Remove every machine token so the model never sees one as prose."""
    return _CTRL_TOKEN_RE.sub("", text or "")


def _columns_of(result):
    """Lower-cased column names of a captured result block, or []."""
    if not isinstance(result, dict):
        return []
    return [str(c).strip().lower() for c in (result.get("columns") or [])]


def is_captured_result(result):
    """True when a generated_sql ``result`` is a real captured block.

    The PRODUCTION shape (evidence/capture.extract_result) is EXACTLY
    ``{columns, rows, truncated}`` - list columns + list rows, NO 'captured'
    key (that flag only exists on the /evidence/meta response block). Mirror of
    the canonical ``evidence/service.has_captured_result`` predicate.
    """
    return (isinstance(result, dict)
            and isinstance(result.get("columns"), list)
            and isinstance(result.get("rows"), list))


def build_artifact_event(name, args, latest_result, latest_sql_id):
    """Validate one show_* call against the latest captured result and return
    (normalized_artifact_event_or_None, error_text_or_None).

    The event is produced through ``streaming._normalized_artifact_event`` so
    the FROZEN artifact shape has a single owner. A spec naming an unknown
    column is refused with an explicit error the model can correct."""
    args = args if isinstance(args, dict) else {}
    cols = _columns_of(latest_result)
    if not cols:
        return None, "No captured specialist result to render yet - call a specialist first."
    event_data = {"title": str(args.get("title") or "")[:200]}
    description = args.get("description")
    if isinstance(description, str) and description.strip():
        event_data["description"] = description.strip()
    if latest_sql_id:
        event_data["sql_id"] = str(latest_sql_id)
    if name == "show_chart":
        x = args.get("x")
        y = args.get("y")
        if isinstance(y, str):
            y = [y]
        y = [c for c in (y or []) if isinstance(c, str) and c]
        ctype = args.get("chart_type")
        if ctype not in CHART_TYPES or not isinstance(x, str) or not y:
            return None, "Invalid chart spec: chart_type must be line/bar/pie and x/y set."
        missing = [c for c in [x] + y if str(c).strip().lower() not in cols]
        if missing:
            return None, ("Unknown column(s) %s. The latest result columns are: %s."
                          % (missing, ", ".join(cols)))
        event_data["kind"] = "chart"
        event_data["chart"] = {"type": ctype, "x": x, "y": y}
        for key in ("style", "x_label", "y_label", "unit"):
            v = args.get(key)
            if isinstance(v, str) and v.strip():
                event_data["chart"][key] = v
    elif name == "show_kpi":
        value = args.get("value")
        if not isinstance(value, str) or not value:
            return None, "Invalid KPI spec: 'value' (exact column name) is required."
        if value.strip().lower() not in cols:
            return None, ("Unknown column '%s'. The latest result columns are: %s."
                          % (value, ", ".join(cols)))
        kpi = {"label": str(args.get("label") or "")[:120], "value": value}
        for key in ("delta", "delta_pct"):
            v = args.get(key)
            if isinstance(v, str) and v and v.strip().lower() in cols:
                kpi[key] = v
        unit = args.get("unit")
        if isinstance(unit, str) and unit.strip():
            kpi["unit"] = unit
        event_data["kind"] = "kpi"
        event_data["kpi"] = kpi
    else:  # show_table
        event_data["kind"] = "table"
    event = streaming._normalized_artifact_event(event_data)
    if event is None:
        return None, "Malformed presentation spec."
    return event, None


def _extract_usage(obj):
    """Best-effort ``usage_summary``-shaped totals from a raw response payload.

    Each destination reads the FIRST spelling present (camelCase then
    snake_case) - never both, so a payload carrying the two graphies is not
    double-counted."""
    totals = {"promptTokens": 0, "completionTokens": 0, "totalTokens": 0,
              "estimatedCost": 0.0}
    found = False
    if isinstance(obj, dict):
        usage = obj.get("usage") or obj.get("usageMetadata")
        if isinstance(usage, dict):
            for dst, sources in (("promptTokens", ("promptTokens", "prompt_tokens")),
                                 ("completionTokens", ("completionTokens", "completion_tokens")),
                                 ("totalTokens", ("totalTokens", "total_tokens")),
                                 ("estimatedCost", ("estimatedCost",))):
                for src in sources:
                    value = usage.get(src)
                    if isinstance(value, (int, float)) and not isinstance(value, bool):
                        totals[dst] += value
                        found = True
                        break
    return totals if found else None


def _accumulate_usage(total, extra):
    for key in ("promptTokens", "completionTokens", "totalTokens"):
        total[key] += int(extra.get(key) or 0)
    total["estimatedCost"] += float(extra.get("estimatedCost") or 0.0)


# =============================================================================
# The engine
# =============================================================================
def run_native_streamed(project_key, agent_id, messages, mode=None):
    """Run one native-orchestrated turn; yield the normalized event stream.

    Same generator contract as ``streaming.run_agent_streamed`` (the worker is
    engine-agnostic). ``agent_id`` is the whitelist-resolved entry id - kept for
    logging/trace parity; the sub-agents actually invoked come from the hub
    capabilities. ``mode`` is the route-resolved response mode (never raw
    frontend input).
    """
    t0 = time.perf_counter()
    mode = resolve_mode(mode)
    lang = parse_lang(messages)
    llm_id = LLM_BY_MODE.get(mode, LLM_BY_MODE[DEFAULT_MODE])
    logger.info("native engine - start project_key=%s mode=%s llm=%s turns=%d",
                project_key, mode, llm_id, len(messages or []))

    project = dataiku.api_client().get_project(project_key)
    caps = get_capabilities(project)
    tool_by_name = {cap["tool_name"]: (key, cap) for key, cap in caps.items()}
    specs = build_tool_specs(caps)

    completion = project.get_llm(llm_id).new_completion()
    completion.settings["tools"] = specs
    completion.with_message(PERSONA, role="system")
    for m in messages or []:
        completion.with_message(strip_control_tokens(m.get("content")).rstrip(),
                                m.get("role") or "user")

    yield {"type": "agent_event", "eventKind": "AGENT_TURN_START",
           "blockId": None, "nextBlockId": None, "toolName": None,
           "elapsedSeconds": 0.0}

    usage_totals = {"promptTokens": 0, "completionTokens": 0,
                    "totalTokens": 0, "estimatedCost": 0.0}
    trace_steps = []
    sub_traces = []
    subagent_calls = 0
    artifact_count = 0
    global_sql_index = 0
    latest_result = None
    latest_sql_id = None
    final_text = ""

    # The user's RAW current message (control tokens + appended backend blocks
    # stripped), handed to pass_context sub-agents for disambiguation - the same
    # both-sides contract as the legacy orchestrator context.
    raw_user_message = ""
    for m in reversed(messages or []):
        if (m.get("role") or "") == "user":
            raw_user_message = strip_control_tokens(m.get("content") or "")
            for marker in ("\n\n[ON SCREEN NOW", "\n\n[PRIOR DATA", "\n\n[Context"):
                idx = raw_user_message.find(marker)
                if idx != -1:
                    raw_user_message = raw_user_message[:idx]
            raw_user_message = raw_user_message.strip()[:500]
            break

    for turn in range(MAX_LLM_TURNS):
        # Last allowed iteration: withdraw the tools so the model MUST conclude
        # in text (a run that never converges would otherwise die tool-calling).
        if turn == MAX_LLM_TURNS - 1:
            completion.settings.pop("tools", None)
        response = completion.execute()
        if not getattr(response, "success", True):
            raise RuntimeError("native engine - LLM call failed (mode=%s)" % mode)
        loop_usage = _extract_usage(getattr(response, "raw", None))
        if loop_usage:
            _accumulate_usage(usage_totals, loop_usage)
        tool_calls = list(getattr(response, "tool_calls", None) or [])

        if not tool_calls:
            final_text = (getattr(response, "text", None) or "").strip()
            break

        completion.with_tool_calls(tool_calls, role="assistant")
        for call in tool_calls:
            fn = (call.get("function") or {}) if isinstance(call, dict) else {}
            name = fn.get("name") or ""
            call_id = call.get("id") if isinstance(call, dict) else None
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except (TypeError, ValueError):
                args = {}
            if not isinstance(args, dict):
                args = {}
            elapsed = round(time.perf_counter() - t0, 2)

            if name in tool_by_name:
                cap_key, cap = tool_by_name[name]
                if subagent_calls >= MAX_SUBAGENT_CALLS:
                    output = ("Specialist call budget reached for this turn - "
                              "answer with what you already have.")
                else:
                    subagent_calls += 1
                    yield {"type": "agent_event", "eventKind": "AGENT_TOOL_START",
                           "blockId": None, "nextBlockId": None, "toolName": name,
                           "elapsedSeconds": elapsed, "agentKey": cap_key}
                    output, sub_summary = None, {"tool": name, "agentKey": cap_key}
                    task = str(args.get("task") or "")[:SUBAGENT_TASK_MAX_CHARS]
                    sub_messages = []
                    if cap.get("pass_context"):
                        context_lines = (
                            "MODE: %s\n"
                            "USER LANGUAGE: %s - write any message addressed "
                            "to the user (clarification, no-data, "
                            "out-of-scope) in THIS language.\n" % (mode, lang))
                        if raw_user_message:
                            context_lines += (
                                "USER'S RAW CURRENT MESSAGE (disambiguation "
                                "only - the task below is authoritative): "
                                "%s\n" % raw_user_message)
                        sub_messages.append({"role": "system",
                                             "content": context_lines})
                    sub_messages.append({"role": "user", "content": task})
                    answer_parts = []
                    sub_sql_map = {}  # sub-run sqlIndex -> global sqlIndex
                    # Captured result of THIS sub-run only (never a stale one
                    # from an earlier specialist - the tool note must describe
                    # what THIS call brought back, or nothing).
                    call_captured = None
                    sub_t0 = time.perf_counter()
                    try:
                        for event in streaming.run_agent_streamed(
                                project_key, cap["agent_id"], sub_messages):
                            etype = event.get("type")
                            if etype == "answer_delta":
                                answer_parts.append(event.get("text") or "")
                            elif etype == "generated_sql":
                                # Renumber into the ENGINE-global monotonic index
                                # space; an enrichment re-emission (same sub-run
                                # index) keeps its assigned global index so the
                                # worker's in-place update contract holds.
                                out_event = dict(event)
                                orig = event.get("sqlIndex")
                                if orig in sub_sql_map:
                                    out_event["sqlIndex"] = sub_sql_map[orig]
                                else:
                                    global_sql_index += 1
                                    sub_sql_map[orig] = global_sql_index
                                    out_event["sqlIndex"] = global_sql_index
                                out_event.setdefault("agentKey", cap_key)
                                # PRODUCTION captured shape = {columns, rows,
                                # truncated} (no 'captured' key - that flag only
                                # exists on the /evidence/meta response block).
                                result = out_event.get("result")
                                if is_captured_result(result):
                                    latest_result = result
                                    latest_sql_id = out_event.get("sqlId")
                                    call_captured = result
                                yield out_event
                            elif etype == "usage_summary":
                                _accumulate_usage(usage_totals, event)
                            elif etype == "trace":
                                sub_traces.append({"agentKey": cap_key,
                                                   "trace": event.get("trace")})
                            elif etype == "agent_event":
                                # Relay the specialist's lifecycle steps under
                                # the SUB_AGENT_ prefix (the frontend humanizes
                                # it), tagged with the capability key.
                                fwd = dict(event)
                                fwd["eventKind"] = "SUB_AGENT_" + str(
                                    event.get("eventKind") or "")
                                fwd.setdefault("agentKey", cap_key)
                                yield fwd
                            elif etype == "narration":
                                yield event
                            # workflow_control / unknown types never leave a sub-run.
                    except Exception:
                        logger.exception("native engine - specialist %s failed", name)
                        output = ("The specialist failed on a technical error. "
                                  "Tell the user honestly; do not invent figures.")
                    if output is None:
                        answer = "".join(answer_parts).strip()
                        output = answer[:MAX_TOOL_OUTPUT_CHARS] if answer else (
                            "The specialist returned no text.")
                        # Note what THIS call captured (never a stale result
                        # from an earlier specialist).
                        if call_captured is not None:
                            cols = ", ".join(
                                str(c) for c in (call_captured.get("columns") or []))
                            output += ("\n\n[Result captured: columns %s, %d rows - "
                                       "you can now call show_chart / show_table / "
                                       "show_kpi on it.]"
                                       % (cols, len(call_captured.get("rows") or [])))
                    sub_summary["elapsed_s"] = round(time.perf_counter() - sub_t0, 2)
                    sub_summary["sql_count"] = len(sub_sql_map)
                    trace_steps.append(sub_summary)
                    yield {"type": "agent_event", "eventKind": "AGENT_TOOL_END",
                           "blockId": None, "nextBlockId": None, "toolName": name,
                           "elapsedSeconds": round(time.perf_counter() - t0, 2),
                           "agentKey": cap_key}
            elif name in ("show_chart", "show_table", "show_kpi"):
                if artifact_count >= MAX_ARTIFACTS:
                    output = "Artifact budget reached for this turn."
                else:
                    event, error = build_artifact_event(
                        name, args, latest_result, latest_sql_id)
                    if event is not None:
                        artifact_count += 1
                        trace_steps.append({"tool": name,
                                            "kind": event.get("kind")})
                        yield {"type": "agent_event", "eventKind": "AGENT_TOOL_START",
                               "blockId": None, "nextBlockId": None,
                               "toolName": name, "elapsedSeconds": elapsed}
                        yield event
                        output = ("Rendered in the Evidence panel. Now write "
                                  "your analysis (never reprint the rows).")
                    else:
                        output = error
            else:
                output = "Unknown tool '%s'." % name

            completion.with_tool_output(
                str(output)[:MAX_TOOL_OUTPUT_CHARS],
                tool_call_id=call_id)
    else:
        # MAX_LLM_TURNS exhausted without a final text (the no-tools last
        # iteration normally prevents this; kept as an honest guard).
        final_text = ""

    if not final_text:
        # Honest fallback in the two supported UI languages (parse_lang only
        # ever returns a member of _KNOWN_LANGS).
        final_text = ("Je n'ai pas pu conclure ce tour proprement. "
                      "Reformulez ou réessayez : rien n'a été inventé."
                      if lang == "fr" else
                      "I could not conclude this turn cleanly. Please rephrase "
                      "or retry; nothing was invented.")

    for i in range(0, len(final_text), ANSWER_DELTA_CHUNK_CHARS):
        yield {"type": "answer_delta",
               "text": final_text[i:i + ANSWER_DELTA_CHUNK_CHARS]}

    yield {"type": "agent_event", "eventKind": "AGENT_DONE", "blockId": None,
           "nextBlockId": None, "toolName": None,
           "elapsedSeconds": round(time.perf_counter() - t0, 2)}
    yield {"type": "usage_summary", **usage_totals}
    yield {"type": "trace", "trace": {
        "engine": "native",
        "mode": mode,
        "llm_id": llm_id,
        "entry_agent_id": agent_id,
        "steps": trace_steps,
        "subagent_traces": sub_traces,
        "duration_s": round(time.perf_counter() - t0, 2),
    }}
