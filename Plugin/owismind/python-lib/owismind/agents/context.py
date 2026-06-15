"""Pure helpers that assemble the multi-turn payload sent to a DSS agent.

No ``dataiku`` import — kept pure so it is unit-testable without a DSS runtime.
The official LLM Mesh pattern is to replay each prior turn via
``completion.with_message(content, role)`` (developer.dataiku.com), so we build an
ordered list of ``{"role", "content"}`` dicts: prior messages verbatim, then the
current user turn carrying a compact name/date prefix.
"""
import math

# strftime template for the per-turn date stamp (C locale -> English, unambiguous).
_DATE_FMT = "%A, %B %d, %Y at %H:%M"


# Model modes the front can request (Eco / Medium / High). Relayed to the agent
# as a compact control token APPENDED to the current turn (the orchestrator parses
# and strips it, so it never reaches the model as part of the question). Unknown /
# absent -> the orchestrator defaults to "medium".
MODEL_MODES = ("eco", "medium", "high")


def build_user_prefix(full_name, now_dt, mode=None):
    """Compact context prefix prepended to the CURRENT user message every turn.

    The agent is stateless between calls, so we re-state who is asking and the
    current date on each send (mirrors the validated Dash production pattern).
    A valid ``mode`` adds a ``⟦owi:mode=…⟧`` control token the orchestrator reads
    to pick its model policy (cheap by default; the strong model is the exception).
    """
    name = full_name or "Unknown user"
    prefix = "[User: {name} — Date: {date}] ".format(name=name, date=now_dt.strftime(_DATE_FMT))
    if mode in MODEL_MODES:
        prefix += "⟦owi:mode={0}⟧ ".format(mode)
    return prefix


# Upper bound on the generated-SQL block appended to a prior assistant turn (keeps
# the replayed context compact; the SQL is for grounding, not verbatim re-execution).
MAX_SQL_CONTEXT_CHARS = 4000


def _format_sql_context(generated_sql):
    """Render the stored generated_sql list into a bounded context block (or '').

    ``generated_sql`` is the decoded list of ``{sql, success, row_count}`` for a prior
    turn. Returns "" when there is nothing to add, so rows without SQL are unchanged.
    """
    if not generated_sql:
        return ""
    parts = []
    for item in generated_sql:
        sql = (item.get("sql") if isinstance(item, dict) else None) or ""
        sql = sql.strip()
        if sql:
            parts.append(sql)
    if not parts:
        return ""
    body = "\n".join(parts)[:MAX_SQL_CONTEXT_CHARS]
    return "\n\n[SQL généré pour cette réponse :\n{0}]".format(body)


def flatten_exchanges_to_messages(rows, max_messages):
    """Flatten chronological exchange rows into the last ``max_messages`` messages.

    ``rows`` are oldest->newest, each a dict with ``user_text``/``assistant_text``.
    One exchange yields up to two messages (user then assistant). Empty sides are
    skipped (e.g. a prior run that produced no answer). When an exchange carries a
    decoded ``generated_sql`` list, a bounded SQL block is appended to its assistant
    turn so the agent has the SQL it produced earlier as grounding context.
    """
    messages = []
    for row in rows:
        u = (row.get("user_text") or "").strip()
        a = (row.get("assistant_text") or "").strip()
        if u:
            messages.append({"role": "user", "content": u})
        if a:
            content = a + _format_sql_context(row.get("generated_sql"))
            messages.append({"role": "assistant", "content": content})
    n = max(0, int(max_messages))
    return messages[-n:] if n else []


def exchanges_to_fetch(max_messages):
    """How many EXCHANGES to read to cover ``max_messages`` messages (2 per exchange)."""
    return max(1, int(math.ceil(int(max_messages) / 2.0)))


def build_completion_messages(history_messages, current_message, user_prefix):
    """Ordered replay list: prior turns verbatim + current user turn (prefixed)."""
    out = list(history_messages or [])
    out.append({"role": "user", "content": (user_prefix or "") + current_message})
    return out
