"""doctor: the prompt-improvement engine, pure logic separated from IO.

The doctor reads recent agent interactions from the LLM interaction logging
dataset (turned on by ``Notebooks/05_enable_interaction_logging.py``), asks an
LLM to diagnose behavior problems against the CURRENT system prompt, and returns
a structured PROPOSAL: a diagnosis, the issues with their evidence, a complete
REVISED system prompt, a change summary, risks and regression questions.

It NEVER edits an agent. The notebook that drives it (``06_prompt_doctor.py``)
only prints the proposal and saves it to the hub for a human to review.

Design rules (same as the rest of ``owismind_factory``):
- stdlib only at import time (``json``); ``dataiku`` is imported lazily inside
  :func:`collect_interactions` so the pure helpers are testable without DSS.
- :func:`build_doctor_prompt`, the schema and :func:`format_proposal_markdown`
  are PURE, so the whole shape is covered by unit tests.
- everything defensive: :func:`collect_interactions` returns ``[]`` on any error,
  :func:`run_doctor` returns ``{"error": ...}`` rather than raising.
"""

import json

# Cap on how much of a single logged field we keep / send to the model.
MAX_FIELD_CHARS = 2000

# The structured output the doctor must return. Forced with ``with_json_output``
# when the connection supports it; parsed defensively otherwise.
DOCTOR_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "evidence": {"type": "string"},
                    "severity": {"type": "string"},
                },
                "required": ["title", "evidence", "severity"],
            },
        },
        "revised_prompt": {"type": "string"},
        "change_summary": {"type": "array", "items": {"type": "string"}},
        "risks": {"type": "array", "items": {"type": "string"}},
        "test_questions": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["diagnosis", "issues", "revised_prompt",
                 "change_summary", "risks", "test_questions"],
}


# --------------------------------------------------------------------------- collect

def classify_columns(names):
    """Map logging-dataset column names to interaction roles by name heuristics.

    The logging dataset schema is not documented and varies by build, so we guess
    which column holds the user input, the agent answer, the tool calls and the
    timestamp. Returns a ``{role: column_name}`` dict for the roles it could
    identify (first matching column wins per role). Pure.
    """
    roles = {}
    for name in names:
        low = (name or "").lower()
        if "input" in low or "query" in low or "prompt" in low or "question" in low:
            roles.setdefault("input", name)
        if "output" in low or "answer" in low or "response" in low \
                or "completion" in low or "reply" in low:
            roles.setdefault("answer", name)
        if "tool" in low:
            roles.setdefault("tools", name)
        if (low in ("ts", "date", "time", "datetime") or low.endswith("_ts")
                or "timestamp" in low or "date" in low or "time" in low
                or "created" in low):
            roles.setdefault("ts", name)
    return roles


def _cap(value, limit=MAX_FIELD_CHARS):
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    return text if len(text) <= limit else (text[:limit] + "...(truncated)")


def collect_interactions(project, dataset_name, limit=30):
    """Read up to ``limit`` recent interactions from the logging dataset.

    ``project`` is accepted for signature symmetry with the rest of the factory
    (the dataset is read through ``dataiku.Dataset`` in the current project).
    Each returned item is ``{"raw": {col: capped_value}, <role>: capped_value...}``
    where roles come from :func:`classify_columns`. Every field is capped to
    ``MAX_FIELD_CHARS`` and iteration stops at ``limit`` so a huge dataset is
    never fully read. Returns ``[]`` on ANY failure - it must not crash a
    notebook. Read-only.
    """
    try:
        import dataiku
        ds = dataiku.Dataset(dataset_name)
    except Exception:
        return []
    try:
        try:
            schema = ds.read_schema()
            names = [c.get("name") for c in schema if isinstance(c, dict)]
        except Exception:
            names = []
        roles = classify_columns(names)
        # Storage order is not guaranteed to be chronological: read a bounded
        # window (never the whole dataset), then keep the LATEST ``limit`` rows
        # by the detected timestamp column so "recent" means recent.
        ts_col = roles.get("ts")
        window = limit * 10 if ts_col else limit
        rows = []
        for row in ds.iter_rows():
            if len(rows) >= window:
                break
            rows.append({k: _cap(v) for k, v in dict(row).items()})
        if ts_col:
            rows.sort(key=lambda r: r.get(ts_col) or "", reverse=True)
        out = []
        for raw in rows[:limit]:
            item = {"raw": raw}
            for role, col in roles.items():
                if col in raw:
                    item[role] = raw[col]
            out.append(item)
        return out
    except Exception:
        return []


# --------------------------------------------------------------------------- prompt

def _render_interactions(interactions):
    if not interactions:
        return ("(no interactions were available - reason from the persona and the "
                "complaint alone, and say so in the diagnosis)")
    blocks = []
    for index, item in enumerate(interactions, 1):
        if not isinstance(item, dict):
            blocks.append("### Interaction %d\n%s" % (index, str(item)[:MAX_FIELD_CHARS]))
            continue
        lines = ["### Interaction %d" % index]
        if item.get("ts"):
            lines.append("- when: %s" % item["ts"])
        if item.get("input"):
            lines.append("- user: %s" % item["input"])
        if item.get("answer"):
            lines.append("- agent: %s" % item["answer"])
        if item.get("tools"):
            lines.append("- tools: %s" % item["tools"])
        if not any(item.get(role) for role in ("input", "answer", "tools", "ts")):
            # No role recognized: hand the raw row over so nothing is hidden.
            payload = item.get("raw") or item
            lines.append("- row: %s" % json.dumps(payload, ensure_ascii=False)[:MAX_FIELD_CHARS])
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def build_doctor_prompt(persona_text, interactions, complaint=None, extra_context=None):
    """The full analysis prompt (English). Pure.

    Instructs the model to diagnose behavior problems against the CURRENT system
    prompt, cite concrete interactions, then output a complete REVISED prompt, a
    change summary, risks and 5 regression questions - WITHOUT weakening the
    agent's frozen contracts.
    """
    parts = []
    parts.append(
        "You are a PROMPT DOCTOR. Your job is to improve the SYSTEM PROMPT of an "
        "OWIsMind data-assistant agent (running in Dataiku DSS) using evidence "
        "from its recent interactions. Be precise, conservative and honest.")
    parts.append("## Current system prompt (under review)\n\n"
                 + (persona_text or "(none provided)"))
    if complaint:
        parts.append("## Reported problem (human complaint)\n\n" + str(complaint))
    if extra_context:
        parts.append("## Extra context\n\n" + str(extra_context))
    parts.append("## Recent interactions (evidence)\n\n"
                 + _render_interactions(interactions))
    parts.append(
        "## What to produce\n\n"
        "1. DIAGNOSIS: the behavior problems you see, judged against the CURRENT "
        "system prompt above.\n"
        "2. ISSUES: a list, each with a short title, the CONCRETE interaction "
        "evidence it rests on, and a severity.\n"
        "3. REVISED_PROMPT: the COMPLETE revised system prompt (full text, ready "
        "to paste, not a diff), keeping the same overall structure and every "
        "behavioral contract. Write it in English with NO em dashes or en dashes "
        "(use '-', ':' or parentheses).\n"
        "4. CHANGE_SUMMARY: bullet points describing what you changed and why.\n"
        "5. RISKS: what could regress and what to watch.\n"
        "6. TEST_QUESTIONS: exactly 5 regression questions a reviewer can ask the "
        "agent to confirm the fix and catch regressions.\n\n"
        "HARD CONSTRAINT: do NOT weaken the FROZEN contracts of this agent - the "
        "event kinds, the honesty firewall (it must never invent or deny a "
        "business figure; it may only admit it has no agent for a domain), and the "
        "output contract. Only strengthen or clarify behavior; never remove a "
        "safety rule.")
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- run

def _extract_json_object(text):
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:
        return None


def _parse_completion(resp):
    """Parse a completion response into a dict: ``resp.json`` then ``resp.text``."""
    data = getattr(resp, "json", None)
    if isinstance(data, dict):
        return data
    text = getattr(resp, "text", None)
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        return _extract_json_object(text)


def run_doctor(project, llm_id, persona_text, interactions, complaint=None):
    """Call the LLM Mesh native completion API and return the parsed proposal.

    Returns the proposal dict, or ``{"error": ...}`` on any failure (missing
    llm id, LLM error, unparseable response). Bounded single completion.
    """
    if not llm_id:
        return {"error": "no llm_id provided (hub factory_settings['llm_sonnet'] is empty)"}
    prompt = build_doctor_prompt(persona_text, interactions, complaint=complaint)
    try:
        llm = project.get_llm(llm_id)
        completion = llm.new_completion()
        try:
            completion.with_json_output(schema=DOCTOR_OUTPUT_SCHEMA)
        except Exception:
            # Native JSON mode unavailable on this connection: fall back to a
            # defensive text parse below instead of failing.
            pass
        completion.with_message(prompt)
        resp = completion.execute()
    except Exception as exc:  # noqa: BLE001
        return {"error": "LLM call failed: %s" % exc}
    parsed = _parse_completion(resp)
    if not isinstance(parsed, dict):
        return {"error": "could not parse the doctor response as JSON"}
    return parsed


# --------------------------------------------------------------------------- render

def format_proposal_markdown(result, agent_label, include_evidence=False):
    """Render a proposal dict (or an ``{"error": ...}``) as readable markdown.

    ``include_evidence`` defaults to False because this markdown is PERSISTED
    to the project library (readable by every project reader) while the issue
    evidence is VERBATIM excerpts of real conversations (client names,
    amounts). Withheld by default; pass True only for ephemeral display
    (the notebook's own output), never for anything written to the hub.
    """
    header = "# Prompt doctor proposal - %s" % agent_label
    if not isinstance(result, dict):
        return "%s\n\n(no result)\n" % header
    if result.get("error"):
        return ("%s\n\n**The doctor could not produce a proposal.**\n\nError: %s\n"
                % (header, result.get("error")))

    lines = [header, ""]
    lines.append("## Diagnosis")
    lines.append(str(result.get("diagnosis") or "(none)"))
    lines.append("")

    lines.append("## Issues found")
    issues = result.get("issues") or []
    if issues:
        for issue in issues:
            if isinstance(issue, dict):
                evidence = issue.get("evidence") or ""
                if evidence and not include_evidence:
                    # Verbatim conversation excerpts must not land in the hub.
                    evidence = ("[evidence withheld: 1 interaction excerpt(s), "
                                "review them in the notebook output only]")
                lines.append("- **%s** (%s): %s" % (
                    issue.get("title") or "(untitled)",
                    issue.get("severity") or "?",
                    evidence))
            else:
                lines.append("- %s" % issue)
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("## Change summary")
    for change in (result.get("change_summary") or ["(none)"]):
        lines.append("- %s" % change)
    lines.append("")

    lines.append("## Risks")
    for risk in (result.get("risks") or ["(none)"]):
        lines.append("- %s" % risk)
    lines.append("")

    lines.append("## Regression test questions")
    for question in (result.get("test_questions") or ["(none)"]):
        lines.append("- %s" % question)
    lines.append("")

    lines.append("## Proposed REVISED system prompt")
    lines.append("")
    lines.append("```")
    lines.append(str(result.get("revised_prompt") or "(none)"))
    lines.append("```")
    lines.append("")
    lines.append("> Review this proposal, apply it to the hub prompt BY HAND, then "
                 "re-run the LAB benchmark before keeping it. The doctor never edits "
                 "an agent.")
    return "\n".join(lines)
