"""Stream one agent run (LLM Mesh) and normalise its chunks for the frontend.

The DSS Agents API streams a heterogeneous sequence of chunks via
``c = project.get_llm(agent_id).new_completion(); for each turn:
c.with_message(content, role); c.execute_streamed()`` (multi-turn replay):
agent lifecycle events (eventKind: AGENT_TURN_START, AGENT_BLOCK_START,
AGENT_TOOL_START, …), answer text deltas, and a final footer carrying the run
trace (usage metadata + the SQL the agent's tools generated).

``run_agent_streamed`` consumes that raw stream and YIELDS normalised, JSON-safe
event dicts (one ``type`` per dict): ``agent_event`` / ``answer_delta`` /
``generated_sql`` / ``usage_summary`` feed the live timeline, plus a final
``trace`` event carrying the RAW footer trace for PERSISTENCE only. The eventKind
timeline is ephemeral (shown during the call, never stored); the raw end-of-stream
trace is what gets stored (mirroring the production Dash app). The worker captures
the ``trace`` event and stores it, but never adds it to the live, polled timeline.

Instance safety - this performs exactly ONE agent run for one validated message:
no loop, no retry. The agent's own tools may run governed SQL, but that is the
product's purpose and is controlled by DSS, not by this WebApp. The agent_id is
resolved server-side from the whitelist before this is ever called; nothing here
accepts a raw id from the frontend.
"""

import logging
import time

import dataiku

from owismind.evidence import capture

logger = logging.getLogger(__name__)

# The footer chunk type may also be recognised by class when available (optional
# import: older/newer SDKs differ, and a notebook-validated guard tolerates both).
try:
    from dataikuapi.dss.llm import DSSLLMStreamedCompletionFooter
except Exception:  # SDK shape differs / symbol absent - fall back to type sniffing
    DSSLLMStreamedCompletionFooter = None

# Chunk ``type`` values that carry an answer text delta (vs an agent lifecycle event).
_TEXT_CHUNK_TYPES = ("content", "text")

# The tool whose output holds a generated SQL query (semantic-model based agents).
_SQL_TOOL_NAME = "semantic-model-query"

# Defensive recursion bound for walking the footer trace. The trace is produced by
# DSS LLM Mesh (trusted), not the frontend, and a malformed walk is already caught
# by the worker's try/except - but a depth guard turns a pathologically deep trace
# into a graceful "no extraction" instead of a RecursionError. Real traces nest a
# handful of levels; 200 is far above any legitimate shape.
_MAX_TRACE_DEPTH = 200

# Orchestrator event whose eventData may relay the sub-agents' generated SQL list
# mid-stream (orchestrator v2.2). Emitting those items AT THAT MOMENT (instead of
# post-loop) means a run the user stops afterwards still persists its SQL (ORCH-08).
_AGENT_DONE_KIND = "AGENT_DONE"

# Orchestrator event asking the UI to render the latest data result as an artifact
# (chart / table). Its eventData carries {kind, title, chart} - NOT covered by the
# timeline whitelist, so it is surfaced as a dedicated normalized ``artifact`` event.
_ARTIFACT_KIND = "ARTIFACT"
_ARTIFACT_CHART_TYPES = ("line", "bar", "pie")

# Live "what I'm doing now" narration: surfaced as a dedicated normalized event,
# shown in the flow but NEVER persisted as the answer (transient progress).
_NARRATION_KIND = "NARRATION"
_NARRATION_MAX_CHARS = 280

# eventData keys relayed verbatim onto the live ``agent_event`` (trust-layer context
# for the timeline). This is a strict WHITELIST pass-through - never the whole dict:
# orchestrator payloads also carry agentId / message / instruction / steps /
# generatedSql, none of which may ever reach the polled timeline.
_EVENT_PASSTHROUGH_KEYS = ("label", "stepIndex", "stepCount", "agentKey", "status")
# Bound on each relayed string value (numbers pass as-is; other types are dropped).
_EVENT_VALUE_MAX_CHARS = 300


def _whitelisted_event_fields(event_data):
    """Copy ONLY the whitelisted eventData keys, bounded, for the live agent_event.

    Strings are capped to ``_EVENT_VALUE_MAX_CHARS``; real numbers (bool excluded -
    bool is an int subclass but is not a number for this contract) pass as-is; any
    other type is silently dropped. Missing keys are simply absent (additive event).
    """
    fields = {}
    if not isinstance(event_data, dict):
        return fields
    for key in _EVENT_PASSTHROUGH_KEYS:
        value = event_data.get(key)
        if isinstance(value, str):
            fields[key] = value[:_EVENT_VALUE_MAX_CHARS]
        elif isinstance(value, bool):
            continue
        elif isinstance(value, (int, float)):
            fields[key] = value
    return fields


def _tag(item, snake_key, camel_key):
    """Read an optional correlation tag accepting snake_case OR camelCase spelling."""
    value = item.get(snake_key)
    return value if value is not None else item.get(camel_key)


def _normalized_sql_event(item, sql_index):
    """Build ONE normalized ``generated_sql`` event from a raw item (trace or relay).

    The mandatory keys keep their historical shape (type/sqlIndex/success/rowCount/
    sql); the optional trust-layer keys (sqlId/stepIndex/agentKey/result) are added
    ONLY when present on the item, so pre-trust-layer flows emit byte-identical
    events. Correlation tags are accepted in snake_case or camelCase: the
    orchestrator v2.2 tags in snake_case (sql_id/step_index/agent_key) and
    untagged trace-walker items carry no correlation keys at all - both
    spellings stay accepted for forward compatibility (ORCHV22-01).
    """
    event = {
        "type": "generated_sql",
        "sqlIndex": sql_index,
        "success": item.get("success"),
        "rowCount": _tag(item, "row_count", "rowCount"),
        "sql": item.get("sql"),
    }
    sql_id = _tag(item, "sql_id", "sqlId")
    if sql_id is not None:
        event["sqlId"] = sql_id
    step_index = _tag(item, "step_index", "stepIndex")
    if step_index is not None:
        event["stepIndex"] = step_index
    agent_key = _tag(item, "agent_key", "agentKey")
    if agent_key is not None:
        event["agentKey"] = agent_key
    source_url = _tag(item, "source_url", "sourceUrl")
    if source_url:
        event["sourceUrl"] = source_url
    result = item.get("result")
    if isinstance(result, dict):
        event["result"] = result
    return event


def _normalized_artifact_event(event_data):
    """Build ONE normalized ``artifact`` event from an ARTIFACT eventData, or None.

    Strict shape: kind in {chart, table, kpi}, bounded title; a chart carries a
    {type, x, y[]} block, a KPI a {value[,delta,delta_pct]} block. The DATA is
    NOT here - the frontend reuses the captured generated_sql result via
    /evidence/meta; only the SPEC travels. Pure, never raises."""
    if not isinstance(event_data, dict):
        return None
    kind = event_data.get("kind")
    if kind not in ("chart", "table", "kpi"):
        return None
    out = {"type": "artifact", "kind": kind,
           "title": str(event_data.get("title") or "")[:200]}
    if kind == "chart":
        chart = event_data.get("chart")
        if not isinstance(chart, dict):
            return None
        ctype = chart.get("type")
        x = chart.get("x")
        y = chart.get("y")
        if ctype not in _ARTIFACT_CHART_TYPES or not isinstance(x, str):
            return None
        if isinstance(y, str):
            y = [y]
        if not isinstance(y, list):
            return None
        y = [str(c)[:128] for c in y if isinstance(c, str) and c][:8]
        if not y:
            return None
        chart_out = {"type": ctype, "x": x[:128], "y": y}
        style = chart.get("style")
        if isinstance(style, str) and style.strip():
            chart_out["style"] = style.strip()[:24]
        out["chart"] = chart_out
    elif kind == "kpi":
        kpi = event_data.get("kpi")
        if not isinstance(kpi, dict) or not isinstance(kpi.get("value"), str):
            return None
        kpi_out = {"label": str(kpi.get("label") or "")[:120],
                   "value": kpi["value"][:128]}
        for key in ("delta", "delta_pct"):
            v = kpi.get(key)
            if isinstance(v, str) and v:
                kpi_out[key] = v[:128]
        out["chart"] = None
        out["kpi"] = kpi_out
    else:
        out["chart"] = None
    return out


def _is_footer_chunk(chunk, data):
    """True when a streamed chunk is the final run footer (carries the trace).

    Recognised either by its ``type == "footer"`` payload or, when the SDK exposes
    the class, by isinstance - matching the notebook-validated detection.
    """
    if isinstance(data, dict) and data.get("type") == "footer":
        return True
    if DSSLLMStreamedCompletionFooter is not None:
        return isinstance(chunk, DSSLLMStreamedCompletionFooter)
    return False


def _find_usage_metadata(obj, _depth=0):
    """Collect every ``usageMetadata`` dict nested anywhere inside the trace."""
    found = []
    if _depth > _MAX_TRACE_DEPTH:
        return found
    if isinstance(obj, dict):
        if isinstance(obj.get("usageMetadata"), dict):
            found.append(obj["usageMetadata"])
        for value in obj.values():
            found.extend(_find_usage_metadata(value, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            found.extend(_find_usage_metadata(item, _depth + 1))
    return found


def _sum_usage_metadata(usages):
    """Sum a list of usageMetadata dicts into one totals dict (tokens + cost)."""
    total = {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "estimatedCost": 0.0,
    }
    for usage in usages:
        total["promptTokens"] += usage.get("promptTokens", 0) or 0
        total["completionTokens"] += usage.get("completionTokens", 0) or 0
        total["totalTokens"] += usage.get("totalTokens", 0) or 0
        total["estimatedCost"] += usage.get("estimatedCost", 0.0) or 0.0
    return total


def _find_generated_sql(obj, _depth=0):
    """Extract ``{success, row_count, sql[, result]}`` per SQL-tool output in the trace.

    Walks the (possibly deeply nested) trace looking for the semantic-model query
    tool's outputs, where the generated SQL is exposed for transparency. ``result``
    (the exact rows the tool returned, capped) is OPTIONAL: the rows key is not
    confirmed on this instance, so ``capture.extract_result`` is best-effort and the
    key is simply absent when nothing recognisable is found (honest no-capture).
    """
    sql_queries = []
    if _depth > _MAX_TRACE_DEPTH:
        return sql_queries
    if isinstance(obj, dict):
        outputs = obj.get("outputs", {}) or {}
        if obj.get("name") == _SQL_TOOL_NAME and isinstance(outputs, dict):
            sql = outputs.get("sql")
            if sql:
                entry = {
                    "success": outputs.get("success"),
                    "row_count": outputs.get("row_count"),
                    "sql": sql,
                }
                result = capture.extract_result(outputs)
                if result is not None:
                    entry["result"] = result
                sql_queries.append(entry)
        for value in obj.values():
            sql_queries.extend(_find_generated_sql(value, _depth + 1))
    elif isinstance(obj, list):
        for item in obj:
            sql_queries.extend(_find_generated_sql(item, _depth + 1))
    return sql_queries


def _find_relayed_sql_from_events(events):
    """Fallback SQL extraction for the Code Agent dispatcher.

    When a dispatcher relays a sub-agent, the generated SQL may travel inside a
    SUB_AGENT_FOOTER event's ``eventData.generatedSql`` rather than the top-level
    trace. ``events`` is the list of raw eventData dicts seen during the run.
    """
    sql_queries = []
    for event_data in events:
        generated = (event_data or {}).get("generatedSql", [])
        if isinstance(generated, list):
            sql_queries.extend(generated)
    return sql_queries


def run_agent_streamed(project_key, agent_id, messages):
    """Run one agent completion and yield normalised event dicts (a generator).

    ``messages`` is an ordered list of ``{role, content}`` dicts assembled by the
    caller: prior session turns replayed verbatim, then the current user turn (which
    already carries the name/date prefix). The official LLM Mesh multi-turn pattern
    is to replay each turn via ``completion.with_message(content, role)``.

    Yields, in stream order:
      - ``{type:"agent_event", eventKind, blockId, nextBlockId, toolName, elapsedSeconds}``
        - plus the WHITELISTED eventData pass-through keys (label / stepIndex /
        stepCount / agentKey / status) when present, bounded; never the whole dict
      - ``{type:"answer_delta", text}``
      - ``{type:"generated_sql", sqlIndex, success, rowCount, sql[, sqlId, stepIndex,
        agentKey, result]}`` - emitted MID-STREAM when an AGENT_DONE event relays its
        ``eventData.generatedSql`` (orchestrator v2.2), so a user-stopped run still
        persists its SQL
    then, once the footer arrives:
      - the remaining ``generated_sql`` events from the footer trace (the PRIMARY
        source), MERGED by sql text with the mid-stream emissions: an already-yielded
        sql is never re-emitted as a new item - when the trace brings success /
        row_count (or a captured result) the relay lacked, ONE enrichment event is
        re-yielded with the SAME ``sqlIndex`` (the consumer updates its stored item
        in place and keeps the live timeline untouched)
      - ``{type:"usage_summary", promptTokens, completionTokens, totalTokens, estimatedCost}``
      - ``{type:"trace", trace}`` - the RAW footer trace, emitted for storage only

    The caller accumulates answer deltas + generated SQL for persistence, stores the
    raw ``trace`` (without surfacing it on the live timeline), and translates the rest
    into transport frames. ``project_key``/``agent_id`` come from the whitelist.
    """
    logger.info(
        "run_agent_streamed - project_key=%s agent_id=%s turns=%d",
        project_key,
        agent_id,
        len(messages or []),
    )

    project = dataiku.api_client().get_project(project_key)
    completion = project.get_llm(agent_id).new_completion()
    # Multi-turn: replay each prior turn with its role, then the current user turn.
    # Official LLM Mesh pattern (developer.dataiku.com): with_message(content, role).
    for m in messages:
        completion.with_message(m["content"], m["role"])

    t0 = time.perf_counter()
    footer_data = None
    # Raw eventData seen during the run - only kept for the relayed-SQL fallback.
    seen_event_data = []
    # sql text -> the normalized generated_sql event already yielded for it (dedup +
    # post-loop merge with the footer-trace extraction). sql_index keeps numbering
    # monotonic across the mid-stream and post-loop emissions.
    emitted_by_sql = {}
    sql_index = 0

    for chunk in completion.execute_streamed():
        data = getattr(chunk, "data", {}) or {}
        elapsed = round(time.perf_counter() - t0, 2)

        if _is_footer_chunk(chunk, data):
            footer_data = data
            continue

        chunk_type = data.get("type")

        if chunk_type == "event":
            event_data = data.get("eventData", {}) or {}
            seen_event_data.append(event_data)
            # NARRATION: a short live "what I'm doing now" message. Surfaced as its
            # own normalized event so the front renders it as a flowing message -
            # NOT as a timeline step and NEVER accumulated into the stored answer
            # (it is transient; the worker only appends it to the live timeline).
            if data.get("eventKind") == _NARRATION_KIND:
                text = event_data.get("text")
                if isinstance(text, str) and text.strip():
                    yield {"type": "narration", "text": text[:_NARRATION_MAX_CHARS]}
                continue
            agent_event = {
                "type": "agent_event",
                "eventKind": data.get("eventKind"),
                "blockId": event_data.get("blockId"),
                "nextBlockId": event_data.get("nextBlockId"),
                # The tool name lives under one of several keys across event shapes.
                "toolName": (
                    event_data.get("toolName")
                    or event_data.get("name")
                    or event_data.get("tool")
                ),
                "elapsedSeconds": elapsed,
            }
            # Trust-layer context for the timeline: WHITELISTED keys only, bounded.
            agent_event.update(_whitelisted_event_fields(event_data))
            yield agent_event
            # AGENT_DONE may relay the sub-agent's generated SQL (orchestrator v2.2):
            # yield the normalized events NOW so a run the user stops afterwards
            # still persists its SQL. Deduped by sql text across AGENT_DONE events;
            # the footer trace stays the primary/authoritative source post-loop.
            if data.get("eventKind") == _AGENT_DONE_KIND:
                relayed = event_data.get("generatedSql")
                if isinstance(relayed, list):
                    for item in relayed:
                        if not isinstance(item, dict):
                            continue
                        sql = item.get("sql")
                        if not sql or sql in emitted_by_sql:
                            continue
                        sql_index += 1
                        sql_event = _normalized_sql_event(item, sql_index)
                        emitted_by_sql[sql] = sql_event
                        yield sql_event
            # ARTIFACT: surface the chart/table spec on its own normalized event so
            # the worker can persist it (the timeline already showed the label).
            elif data.get("eventKind") == _ARTIFACT_KIND:
                artifact_event = _normalized_artifact_event(event_data)
                if artifact_event is not None:
                    yield artifact_event
        elif chunk_type in _TEXT_CHUNK_TYPES:
            text = data.get("text", "") or ""
            if text:
                yield {"type": "answer_delta", "text": text}
        else:
            # Unknown chunk shape: surface it as a labelled event for visibility,
            # but never break the stream on it.
            logger.debug("run_agent_streamed - unknown chunk type: %r", chunk_type)
            yield {
                "type": "agent_event",
                "eventKind": "UNKNOWN_CHUNK_TYPE:{}".format(chunk_type),
                "blockId": None,
                "nextBlockId": None,
                "toolName": None,
                "elapsedSeconds": elapsed,
            }

    # --- Footer: extract generated SQL + usage totals, and surface the raw trace --
    trace = footer_data.get("trace") if isinstance(footer_data, dict) else None

    sql_queries = _find_generated_sql(trace) if trace else []
    if not sql_queries:
        # Dispatcher case: SQL relayed inside sub-agent footer events.
        sql_queries = _find_relayed_sql_from_events(seen_event_data)
    # MERGE strictly against the mid-stream AGENT_DONE emissions (the only
    # entries in emitted_by_sql), consumed ONE-SHOT via pop(): two DISTINCT
    # trace spans with the same sql text (a transient failure then an identical
    # retry) must each emit their own event exactly as the DSS-validated
    # pre-trust-layer flow did - only a relay duplicate is merged (CHAT-REG-01).
    for item in sql_queries:
        if not isinstance(item, dict):
            continue
        sql = item.get("sql")
        prior = emitted_by_sql.pop(sql, None) if sql else None
        if prior is None:
            sql_index += 1
            yield _normalized_sql_event(item, sql_index)
            continue
        # Already yielded mid-stream by AGENT_DONE: never re-emit as a new item.
        # When the trace brings authority the relay lacked (success / row_count,
        # or a captured result), re-yield ONE enrichment event with the SAME
        # sqlIndex - the consumer fills the missing fields of its stored item in
        # place and never duplicates the live timeline entry.
        updates = {}
        if prior.get("success") is None and item.get("success") is not None:
            updates["success"] = item.get("success")
        trace_row_count = _tag(item, "row_count", "rowCount")
        if prior.get("rowCount") is None and trace_row_count is not None:
            updates["rowCount"] = trace_row_count
        if "result" not in prior and isinstance(item.get("result"), dict):
            updates["result"] = item["result"]
        if updates:
            merged = dict(prior)
            merged.update(updates)
            yield merged

    usages = _find_usage_metadata(trace) if trace else []
    totals = _sum_usage_metadata(usages)
    logger.info(
        "run_agent_streamed - done agent_id=%s sql_count=%d totalTokens=%s cost=%s",
        agent_id,
        sql_index,
        totals.get("totalTokens"),
        totals.get("estimatedCost"),
    )
    yield {"type": "usage_summary", **totals}

    # Surface the RAW footer trace for PERSISTENCE only. It is deliberately the last
    # event and is NOT part of the live timeline: the worker captures it for storage
    # and never adds it to the polled events (it can be large, and the front shows
    # only the ephemeral eventKind steps live). Emitted only when a trace exists.
    if trace:
        yield {"type": "trace", "trace": trace}
