"""Pure helpers that assemble the multi-turn payload sent to a DSS agent.

No ``dataiku`` import — kept pure so it is unit-testable without a DSS runtime.
The official LLM Mesh pattern is to replay each prior turn via
``completion.with_message(content, role)`` (developer.dataiku.com), so we build an
ordered list of ``{"role", "content"}`` dicts: prior messages verbatim, then the
current user turn carrying a compact context block APPENDED AT THE END.

Why a SUFFIX (not a prefix): small models honor an instruction far better when it
sits in the highest-recency slot — the very end of the current message. Burying the
name/date/language directive at the start lets the model forget it. So the block —
user, date, web-app language, and the load-bearing rule "answer in the language of
THIS message" — is appended last (see ``build_user_suffix``).
"""
import math
import re

# strftime template for the per-turn date stamp (C locale -> English, unambiguous).
_DATE_FMT = "%A, %B %d, %Y at %H:%M"

# Human label of each supported language (for the END-placed context block).
_LANG_LABEL = {"fr": "French", "en": "English"}


# Model modes the front can request (Eco / Medium / High). Relayed to the agent
# as a compact control token APPENDED to the current turn (the orchestrator parses
# and strips it, so it never reaches the model as part of the question). Unknown /
# absent -> the orchestrator defaults to "medium".
MODEL_MODES = ("eco", "medium", "high")


# Lightweight, deterministic language guess of a RAW user message. Ported into the
# 3.9 backend (stdlib-only) so language is computed ONCE, on the clean message
# (before the English date stamp can contaminate the heuristic), and handed to the
# agent as an authoritative ⟦owi:lang=…⟧ token + an end-of-prompt imperative. Mirror
# of the agent's own _detect_lang; kept in sync (used only for the reply language).
_FR_ACCENT_RE = re.compile(r"[éèêàùçâîôœ]")
# Whole-word markers (matched on word boundaries, NOT as substrings) so e.g. the FR
# "revenu" never matches inside the EN "revenue", and "add" never matches "address".
_FR_WORDS = (
    "le", "la", "les", "des", "du", "une", "un", "quel", "quels", "quelle",
    "quelles", "combien", "revenu", "revenus", "évolution", "evolution",
    "client", "clients", "montre", "montrez", "donne", "donnez", "pour",
    "bonjour", "salut", "merci", "ajoute", "ajouter", "rajoute", "rajouter",
    "explique", "expliquer", "affiche", "afficher",
)
_EN_WORDS = (
    "the", "a", "an", "of", "what", "how", "show", "give", "revenue", "which",
    "trend", "compare", "hello", "please", "thanks", "add", "explain", "display",
)
_FR_RE = re.compile(r"\b(?:" + "|".join(_FR_WORDS) + r")\b")
_EN_RE = re.compile(r"\b(?:" + "|".join(_EN_WORDS) + r")\b")


def detect_prompt_language(message, default="fr"):
    """Best-effort language of a user message ("fr" / "en").

    Run on the RAW current message (no date prefix). Word-boundary matching avoids
    cross-language substring collisions (revenu/revenue, add/address). Falls back to
    ``default`` (the web-app language when known) for a neutral message like "42".
    """
    t = (message or "").lower()
    if not t.strip():
        return default if default in _LANG_LABEL else "fr"
    if _FR_ACCENT_RE.search(t):
        return "fr"
    fr = len(_FR_RE.findall(t))
    en = len(_EN_RE.findall(t))
    if en > fr:
        return "en"
    if fr > en:
        return "fr"
    return default if default in _LANG_LABEL else "fr"


def build_user_suffix(full_name, now_dt, webapp_lang=None, prompt_lang=None, mode=None):
    """Compact context block APPENDED to the END of the CURRENT user message.

    Placed in the highest-recency slot so even a small model honors it. Carries who
    is asking, the date, the web-app's configured language and — the load-bearing
    rule — the language of THIS message, which the agent must answer in (it always
    wins over earlier turns and over the web-app language). The control tokens
    ``⟦owi:mode=…⟧`` / ``⟦owi:lang=…⟧`` are machine-only: the agent parses then
    STRIPS them, so they never reach the model as visible text, while the
    human-readable language imperative stays as the final line of the turn.
    """
    name = full_name or "Unknown user"
    date = now_dt.strftime(_DATE_FMT)
    webapp_label = _LANG_LABEL.get(webapp_lang)
    prompt_label = _LANG_LABEL.get(prompt_lang)
    tokens = ""
    if mode in MODEL_MODES:
        tokens += "⟦owi:mode={0}⟧".format(mode)
    if prompt_lang in _LANG_LABEL:
        tokens += "⟦owi:lang={0}⟧".format(prompt_lang)
    head = "\n\n[Context — User: {name} · Today: {date}".format(name=name, date=date)
    if webapp_label:
        head += " · Web app language: {0}".format(webapp_label)
    head += "]"
    if tokens:
        head += " " + tokens          # inline so stripping leaves the bracket line clean
    parts = [head]
    if prompt_label:
        parts.append(
            "IMPORTANT — reply in {plabel}: the SAME language as my message above. "
            "The language of my current message ALWAYS takes priority over earlier "
            "turns and over the web-app language.".format(plabel=prompt_label))
    return "\n".join(parts)


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


# Screen-awareness caps (bounded so the block can never bloat the prompt).
MAX_SCREEN_ARTIFACTS = 4
MAX_SCREEN_COLS = 24
SCREEN_ANSWER_EXCERPT_CHARS = 300


def _artifact_phrase(a):
    """One short human phrase describing a rendered artifact spec, or '' if empty."""
    if not isinstance(a, dict):
        return ""
    kind = a.get("kind")
    title = (a.get("title") or "").strip()
    if kind == "chart":
        ch = a.get("chart") or {}
        desc = "a {0} chart".format(ch.get("type") or "")
        if title:
            desc += ' titled "{0}"'.format(title[:120])
        x, ys = ch.get("x"), (ch.get("y") or [])
        if x:
            desc += " (x={0}, y={1})".format(x, ",".join([str(y) for y in ys]))
        return desc
    if kind == "kpi":
        kpi = a.get("kpi") or {}
        return 'a KPI card "{0}" ({1})'.format(
            (kpi.get("label") or title or "")[:120], kpi.get("value") or "")
    if kind == "table":
        return 'a table' + (' titled "{0}"'.format(title[:120]) if title else "")
    return ""


def _screen_columns(artifacts):
    """Collect the data column names referenced by the rendered artifacts (chart
    x/y, kpi value/delta) — enough for the model to know what 'add X' can touch."""
    cols, seen = [], set()
    for a in artifacts or []:
        if not isinstance(a, dict):
            continue
        ch = a.get("chart") or {}
        kpi = a.get("kpi") or {}
        for c in ([ch.get("x")] + list(ch.get("y") or [])
                  + [kpi.get("value"), kpi.get("delta"), kpi.get("delta_pct")]):
            if c and c not in seen:
                seen.add(c)
                cols.append(str(c))
    return cols[:MAX_SCREEN_COLS]


def build_screen_state(artifacts, last_answer_excerpt=None, active_tab=None):
    """Compact, bounded description of what is CURRENTLY on the user's screen.

    The rendered artifacts (chart/table/KPI in the Evidence panel) + the data
    columns they expose + the gist of the previous answer. Appended to the current
    turn so the agent can answer "explain this chart" / "add the forecast to it"
    instead of replying off-topic. Returns "" when nothing is on screen. The block
    is framed as GROUNDED prior data so it never trips the honesty firewall (new
    figures still require a specialist call).
    """
    phrases = [p for p in (_artifact_phrase(a) for a in (artifacts or [])[:MAX_SCREEN_ARTIFACTS]) if p]
    cols = _screen_columns(artifacts)
    excerpt = (last_answer_excerpt or "").strip()
    if not phrases and not cols and not excerpt:
        return ""
    out = ["\n\n[ON SCREEN NOW — what the user can see in the app right now:"]
    if phrases:
        out.append(" Displayed in the Evidence panel: " + "; ".join(phrases) + ".")
    if active_tab in ("evidence", "chart", "table"):
        out.append(" The user is looking at the '{0}' tab.".format(active_tab))
    if cols:
        out.append(" Underlying data columns: " + ", ".join(cols) + ".")
    if excerpt:
        out.append(' Your previous reply began: "{0}".'.format(excerpt[:SCREEN_ANSWER_EXCERPT_CHARS]))
    out.append(" If the user says 'this', 'the chart', 'it', or asks to explain or "
               "change what's shown, they mean THIS. You may explain it directly; for "
               "any NEW figure, still call the specialist.]")
    return "".join(out)


def build_completion_messages(history_messages, current_message, user_suffix):
    """Ordered replay list: prior turns verbatim + current user turn.

    ``user_suffix`` is APPENDED to the current message (end-of-prompt context block
    from ``build_user_suffix``) so the name/date/language directive sits in the
    highest-recency slot. Empty suffix -> the bare message.
    """
    out = list(history_messages or [])
    out.append({"role": "user", "content": current_message + (user_suffix or "")})
    return out
