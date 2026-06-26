"""Benchmark configuration: LLM ids, modes, caps, tolerances, message assembly.

No ``dataiku`` import at top level (kept pure so tests load it stdlib-only). The
mode / language control tokens are mirrored EXACTLY from the production code, not
guessed:
  - the literal: Plugin/owismind/python-lib/owismind/agents/context.py
    build_user_suffix -> ``"⟦owi:mode={0}⟧".format(mode)``
  - the parser:  dataiku-agents/OWISMIND/OWISMIND_DEV/agents/
    OWISMIND_DEV_OWIsMind_orchestrator.py line 137 ->
    ``_MODE_TOKEN_RE = re.compile(r"⟦owi:mode=([a-z]+)⟧")``
The brackets are U+27E6 (left white square bracket) and U+27E7 (right). The
orchestrator strips every ``⟦owi:...⟧`` token before the model sees it,
so appending the token forces the mode without leaking text into the question.
"""

# --- modes (Smart / Pro / Claude) -------------------------------------------
# Canonical mode names = the webapp's display names. The benchmark speaks
# Smart/Pro/Claude everywhere (config input, run rows, dashboard). The control
# token sent to the orchestrator uses the LOWERCASE form of the same names
# (smart/pro/claude), so build_mode_token just lower-cases at the wire boundary.
MODES = ("Smart", "Pro", "Claude")
DEFAULT_MODE = "Smart"

# friendly mode -> the lowercase internal token the orchestrator's parse_mode expects.
_MODE_TOKEN_KEY = {"Smart": "smart", "Pro": "pro", "Claude": "claude"}

# Accept the display name or the lowercase token in config input (case-insensitive),
# so both "Smart" and "smart" resolve.
MODE_ALIASES = {
    "smart": "Smart", "pro": "Pro", "claude": "Claude",
}

# Human-facing model name per mode (display only; verify on instance). Mirrors the
# orchestrator LOOP_LLM_BY_MODE tiers (Gemini Flash-Lite / Gemini Flash / Sonnet).
MODE_LABELS = {
    "Smart": "Gemini 3.1 Flash-Lite",
    "Pro": "Gemini 3.5 Flash",
    "Claude": "Claude Sonnet 4.6",
}


def normalize_mode(mode):
    """Map a config mode (display name or legacy key, any case) to the canonical
    display name (Smart / Pro / Claude), or None when unrecognized. Pure."""
    if mode is None:
        return None
    return MODE_ALIASES.get(str(mode).strip().lower())

# --- control-token brackets (U+27E6 / U+27E7), mirrored from production --------
# Kept as named constants so the exact code points are explicit and greppable.
_LB = "⟦"  # MATHEMATICAL LEFT WHITE SQUARE BRACKET
_RB = "⟧"  # MATHEMATICAL RIGHT WHITE SQUARE BRACKET

# --- LLM ids -----------------------------------------------------------------
# The judge runs on a strong, constant model: the Sonnet id the orchestrator uses
# as its "high" tier (SONNET_ID in OWISMIND_DEV_OWIsMind_orchestrator.py line 104).
# verify on instance
JUDGE_LLM_ID = "openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6"

# --- run knobs (instance safety: low bounded concurrency, hard timeout) ------
DEFAULT_CONCURRENCY = 3
PER_CALL_TIMEOUT_S = 120

# --- scoring ----------------------------------------------------------------
# Relative tolerance for the numeric / currency objective anchor (0.5%).
NUMERIC_TOLERANCE = 0.005

# Language names supported by the language token (parity with context.py).
_LANG_LABEL = {"fr": "French", "en": "English"}


def build_mode_token(mode):
    """Return the exact mode control token, or '' for an unknown / absent mode.

    Mirrors context.py build_user_suffix: ``⟦owi:mode=<key>⟧`` where ``key`` is the
    lowercase token (smart/pro/claude). A friendly mode (Smart/Pro/Claude) is
    lower-cased to its token; the lowercase token passed directly is tolerated.
    Anything else yields '' (the orchestrator then defaults to its own default).
    """
    key = _MODE_TOKEN_KEY.get(mode)
    if key is None and mode in _MODE_TOKEN_KEY.values():
        key = mode  # tolerate the lowercase token passed directly
    if key:
        return "{lb}owi:mode={key}{rb}".format(lb=_LB, key=key, rb=_RB)
    return ""


def build_lang_token(language):
    """Return the exact language control token, or '' when unknown / absent.

    Mirrors context.py: ``⟦owi:lang=<language>⟧`` (parsed by the
    orchestrator _LANG_TOKEN_RE and stripped before the model sees it).
    """
    if language in _LANG_LABEL:
        return "{lb}owi:lang={lang}{rb}".format(lb=_LB, lang=language, rb=_RB)
    return ""


def build_message(question, mode, language):
    """Assemble the message sent to the agent for a benchmark call.

    = the raw question + the machine-only control tokens appended at the END (mode
    first, then language), matching the recency-anchored placement of the webapp's
    build_user_suffix. The orchestrator parses and strips both tokens, so the model
    sees only the question. In this direct-Mesh path there is no profile.modes gate
    (that lives in the webapp /chat/start): the orchestrator honors the mode token
    unconditionally, which is exactly what we want to force a mode per run.

    Returns the message string. Pure, never raises.
    """
    base = (question or "").strip()
    tokens = build_mode_token(mode) + build_lang_token(language)
    if tokens:
        return base + " " + tokens
    return base


def build_plain_message(question):
    """Return the bare question, with NO control token at all.

    Used for an agent that does not support the Smart/Pro/Claude modes (a plain
    visual agent): a single simple call, the agent answers in its default mode.
    Pure, never raises.
    """
    return (question or "").strip()
