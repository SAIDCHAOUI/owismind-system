"""Two-stage scoring of one captured run: objective anchor + structured LLM judge.

Per design spec section 6. For each ``benchmark_runs_raw`` row:

  1. Objective anchor (PURE, no LLM): when the golden row carries an
     ``expected_value``, normalize it and the COMPLETE agent answer
     (``full_answer`` + the flattened SQL result cells) according to
     ``expected_value_type`` and decide ``hit`` / ``miss``. ``n/a`` when there is
     no expected value. This is the deterministic ground truth: it covers the case
     where the answer lives inside a result table, which the old text-only capture
     could not score.
  2. Structured LLM judge (DSS-touching): a strong, constant model (Sonnet, id in
     config) reads the question + reference answer + expected value + the full
     answer and returns a structured verdict (1..5 score, correct/incorrect,
     justification, missing facts, hallucination flag). Native Mesh completion with
     ``with_json_output`` for reliable structure; the judge's OWN token usage / cost
     is captured separately.
  3. Correctness rule (PURE, deterministic): combine the two stages into a final
     ``correct`` / ``needs_review`` decision.

PURE except ``run_llm_judge`` (it lazily imports dataiku and calls Mesh). The
objective anchor, the normalizers, the prompt builder, the output schema and the
correctness rule are all stdlib-only so the NO INSTALL test environment loads this
module and exercises them without DSS.
"""

import re
import unicodedata

from benchmark import config
from benchmark.agent_capture import flatten_result_cells

# Tolerance default re-exported so callers can pass it explicitly or rely on it.
NUMERIC_TOLERANCE = config.NUMERIC_TOLERANCE

# Objective-anchor outcomes.
HIT = "hit"
MISS = "miss"
NA = "n/a"


def _is_nan(value):
    """True for a float NaN (how pandas renders an empty cell). Stdlib only."""
    return isinstance(value, float) and value != value


def _blank_value(value):
    """True when a cell is absent: None, a float NaN, or a blank string."""
    if value is None or _is_nan(value):
        return True
    return isinstance(value, str) and not value.strip()

# Currency / grouping symbols stripped before numeric parsing. Both the comma and
# the dot can be a decimal separator OR a thousands separator depending on locale,
# so they are handled by ``normalize_number`` rather than blindly stripped here.
_CURRENCY_CHARS = "$€£¥₽₩₤"  # $ EUR GBP JPY RUB KRW lira

# A run of digits with optional dot / comma group separators and an optional
# decimal tail. Used to harvest number-looking substrings from a free-text answer.
_NUMBER_RE = re.compile(r"[-+]?\d[\d.,\xa0\u202f]*\d|\d")

# Common date formats accepted by the date anchor (parsed without dateutil).
_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%m/%d/%Y",
    "%d-%m-%Y",
    "%Y/%m/%d",
    "%d.%m.%Y",
    "%Y%m%d",
    "%d %b %Y",
    "%d %B %Y",
    "%b %d, %Y",
    "%B %d, %Y",
)


# ---------------------------------------------------------------------------
# Normalizers (PURE)
# ---------------------------------------------------------------------------
def normalize_text(s):
    """Lowercase, strip accents, collapse whitespace; '' for None / non-string.

    Used for the ``string`` and ``list`` anchors and for normalized containment.
    Never raises.
    """
    if s is None:
        return ""
    try:
        text = str(s)
    except Exception:
        return ""
    # Decompose accents then drop the combining marks (cafe == cafe with accent).
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    # Collapse every run of whitespace (incl. NBSP / thin space) to one space.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def normalize_number(s):
    """Parse a number out of a value, returning ``float`` or ``None``.

    Strips currency symbols, percent signs and grouping separators, then resolves
    the decimal separator heuristically:
      - if both '.' and ',' are present, the LAST one is the decimal separator
        (e.g. ``1.234.567,89`` -> 1234567.89 ; ``1,234,567.89`` -> 1234567.89);
      - if only ',' is present, it is treated as a thousands separator when it
        groups digits in threes (``1,234`` -> 1234) and as a decimal otherwise
        (``12,5`` -> 12.5);
      - if only '.' is present, the symmetric rule applies (``1.234`` thousands,
        ``12.5`` decimal). A trailing magnitude word / unit is ignored.
    Returns ``None`` when no number can be parsed. Never raises.
    """
    if s is None:
        return None
    if isinstance(s, bool):
        return None
    if isinstance(s, (int, float)):
        try:
            f = float(s)
        except (TypeError, ValueError, OverflowError):
            return None
        return f if f == f and f not in (float("inf"), float("-inf")) else None

    try:
        text = str(s)
    except Exception:
        return None

    # Drop currency symbols, percent, and whitespace-like grouping (NBSP, thin).
    for ch in _CURRENCY_CHARS:
        text = text.replace(ch, "")
    text = text.replace("%", "")
    text = text.replace(" ", "").replace(" ", "").replace(" ", "")
    text = text.strip()
    if not text:
        return None

    sign = ""
    if text[0] in "+-":
        sign, text = text[0], text[1:]

    has_dot = "." in text
    has_comma = "," in text

    if has_dot and has_comma:
        # The right-most separator is the decimal point.
        if text.rfind(".") > text.rfind(","):
            text = text.replace(",", "")
        else:
            text = text.replace(".", "").replace(",", ".")
    elif has_comma:
        text = _resolve_single_separator(text, ",")
    elif has_dot:
        text = _resolve_single_separator(text, ".")

    # Keep only a clean numeric core (drop any trailing unit letters).
    m = re.match(r"[0-9]*\.?[0-9]+", text)
    if not m:
        return None
    try:
        return float(sign + m.group(0))
    except (TypeError, ValueError):
        return None


def _resolve_single_separator(text, sep):
    """Decide whether a lone '.' or ',' is a thousands separator or a decimal."""
    parts = text.split(sep)
    # Two parts with a 3-digit tail and a non-empty head that is all digits =>
    # thousands grouping (1,234 / 1.234). Anything else => decimal point.
    if len(parts) == 2 and len(parts[1]) == 3 and parts[0].isdigit() and parts[0]:
        # Ambiguous: 1,234 could be 1.234 or 1234. We treat a single group of
        # exactly three trailing digits as thousands (the common case in figures).
        return parts[0] + parts[1]
    if len(parts) > 2:
        # Multiple separators of the same kind can only be grouping.
        return "".join(parts)
    # Single separator, non-3-digit tail => decimal.
    return parts[0] + "." + parts[1] if len(parts) == 2 else text


def _parse_date(s):
    """Return a ``date`` for a value in one of _DATE_FORMATS, else None."""
    if s is None:
        return None
    try:
        text = str(s).strip()
    except Exception:
        return None
    if not text:
        return None
    import datetime  # lazy: stdlib, but keep imports minimal at top level

    for fmt in _DATE_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


# ---------------------------------------------------------------------------
# Objective anchor (PURE)
# ---------------------------------------------------------------------------
def _numbers_in(text):
    """Yield every number-looking substring of ``text`` parsed to float."""
    out = []
    if not text:
        return out
    for m in _NUMBER_RE.finditer(text):
        value = normalize_number(m.group(0))
        if value is not None:
            out.append(value)
    return out


def _numeric_hit(expected, haystacks, tolerance):
    """True when ``expected`` appears (within tolerance) in any haystack string."""
    target = normalize_number(expected)
    if target is None:
        return False
    # Absolute fallback for exact-zero targets (relative tolerance is meaningless).
    abs_tol = abs(target) * tolerance if target != 0 else max(tolerance, 1e-9)
    for hay in haystacks:
        for candidate in _numbers_in(hay):
            if abs(candidate - target) <= abs_tol:
                return True
    return False


def _date_hit(expected, haystacks):
    """True when the expected date is parseable and present in any haystack."""
    target = _parse_date(expected)
    if target is None:
        return False
    for hay in haystacks:
        if hay is None:
            continue
        # Probe each whitespace-delimited token plus the raw string for a date.
        # Sentence punctuation (trailing '.', ',', ')', ...) is stripped off each
        # token so "closed on 2025-12-31." still parses the date.
        tokens = [str(hay)] + str(hay).replace(",", " ").split()
        for tok in tokens:
            d = _parse_date(tok.strip(".,;:!?()[]\"'"))
            if d is not None and d == target:
                return True
    return False


def _string_hit(expected, haystacks):
    """True when the normalized expected string is contained in a haystack."""
    needle = normalize_text(expected)
    if not needle:
        return False
    for hay in haystacks:
        if needle in normalize_text(hay):
            return True
    return False


def _list_hit(expected, haystacks):
    """True when EVERY expected list item is contained somewhere in the answer.

    The expected value is a delimited list (comma / semicolon / pipe / newline);
    each item must appear (normalized containment) in the concatenated haystacks.
    """
    items = [normalize_text(x) for x in re.split(r"[;,|\n]+", str(expected or ""))]
    items = [x for x in items if x]
    if not items:
        return False
    blob = " ".join(normalize_text(h) for h in haystacks)
    return all(item in blob for item in items)


def objective_anchor(expected_value, expected_value_type, full_answer, sql_items,
                     tolerance=NUMERIC_TOLERANCE):
    """Deterministic ground-truth check of the COMPLETE answer.

    Searches BOTH ``full_answer`` and every flattened SQL result cell (so a figure
    that only lives in a table still counts). Returns ``"hit"`` / ``"miss"`` /
    ``"n/a"`` (``"n/a"`` when no expected value is provided). Pure, never raises.

    Type handling (``expected_value_type``):
      - ``numeric`` / ``currency``: parse numbers on both sides, relative tolerance;
      - ``date``: parse a few common formats, exact date match;
      - ``string``: accent / case / whitespace insensitive containment;
      - ``list``: every expected item present (set-style match).
    An unknown type falls back to the ``string`` rule.
    """
    # Inputs may arrive from pandas as a float NaN (an all-empty column reads as
    # float64), so guard against non-strings, not just None / blank strings.
    if _blank_value(expected_value):
        return NA
    expected = expected_value if isinstance(expected_value, str) else str(expected_value)

    try:
        cells = flatten_result_cells(sql_items)
    except Exception:
        cells = []
    answer = "" if _blank_value(full_answer) else (
        full_answer if isinstance(full_answer, str) else str(full_answer))
    haystacks = [answer] + [c for c in cells if c]

    vtype = expected_value_type if (
        isinstance(expected_value_type, str) and expected_value_type.strip()) else "string"
    vtype = vtype.strip().lower()
    try:
        if vtype in ("numeric", "currency"):
            hit = _numeric_hit(expected, haystacks, tolerance)
        elif vtype == "date":
            hit = _date_hit(expected, haystacks)
        elif vtype == "list":
            hit = _list_hit(expected, haystacks)
        else:  # string + unknown
            hit = _string_hit(expected, haystacks)
    except Exception:
        return MISS
    return HIT if hit else MISS


# ---------------------------------------------------------------------------
# Structured LLM judge
# ---------------------------------------------------------------------------
# JSON schema handed to with_json_output. A plain JSON-schema dict (the shape the
# Mesh native completion API accepts, mirroring the sub-agent's UNDERSTAND schema).
JUDGE_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 1, "maximum": 5},
        "verdict": {"type": "string", "enum": ["correct", "incorrect"]},
        "justification": {"type": "string"},
        "missing_facts": {"type": "array", "items": {"type": "string"}},
        "hallucination": {"type": "boolean"},
    },
    "required": ["score", "verdict", "justification", "hallucination"],
}

# System prompt: a hardened rubric on the 1..5 scale (design section 6.2). The
# judge scores MEANING and FACTUAL accuracy, not wording, and is told the answer
# may carry its figures inside a serialized data table.
_JUDGE_SYSTEM = (
    "You are a strict, fair evaluator of an AI data-assistant's answer. You compare "
    "the assistant answer against a human-validated reference answer and decide how "
    "correct it is. Judge MEANING and FACTUAL accuracy, never wording, style, "
    "language or formatting: a correct figure phrased differently, in another "
    "language, or shown inside a data table is fully correct.\n\n"
    "The assistant answer you receive is the COMPLETE answer: the final text PLUS a "
    "readable serialization of the data tables it produced. A number that appears "
    "only in a table still counts as given.\n\n"
    "Score on this 1 to 5 scale:\n"
    "  5 = perfect: the key fact(s) of the reference are present and correct, no "
    "factual error, no fabricated figure.\n"
    "  4 = essentially correct: the core fact is right; only a minor, "
    "non-misleading omission or imprecision.\n"
    "  3 = partially correct: some of the answer is right but a material part is "
    "missing, wrong, or unsupported.\n"
    "  2 = mostly wrong: the answer misses or contradicts the main fact, with at "
    "most an incidental correct element.\n"
    "  1 = total contradiction: the answer is wrong, irrelevant, or fabricates "
    "figures not supported by the data.\n\n"
    "Set verdict to 'correct' only when the answer conveys the reference's key "
    "fact(s) without a material error (typically score 4 or 5). Set hallucination "
    "to true when the answer states a figure or fact that is NOT supported by the "
    "reference or by the shown data. List the reference facts the answer omits in "
    "missing_facts. Keep justification to one or two sentences. Output only the "
    "structured result."
)


def build_judge_prompt(question, reference_answer, expected_value, full_answer):
    """Assemble the user message for the judge (the four inputs, clearly labelled).

    The reference answer and the expected exact value are the ground truth; the
    full answer is the complete agent output (text + serialized tables). Pure,
    never raises.
    """
    expected = "" if expected_value is None else str(expected_value)
    parts = [
        "QUESTION:",
        str(question or "").strip(),
        "",
        "REFERENCE ANSWER (human-validated, ground truth):",
        str(reference_answer or "").strip(),
    ]
    if expected.strip():
        parts += ["", "EXPECTED EXACT VALUE:", expected.strip()]
    parts += [
        "",
        "ASSISTANT ANSWER (complete: final text + serialized data tables):",
        str(full_answer or "").strip(),
        "",
        "Evaluate the assistant answer against the reference. Return the structured "
        "result.",
    ]
    return "\n".join(parts)


def _judge_usage_from_resp(resp):
    """Pull the judge's own token usage / cost off the Mesh response (best-effort)."""
    usage = {
        "promptTokens": 0,
        "completionTokens": 0,
        "totalTokens": 0,
        "estimatedCost": 0.0,
    }
    u = getattr(resp, "total_usage", None)
    if not isinstance(u, dict):
        return usage
    try:
        usage["promptTokens"] = int(u.get("promptTokens") or 0)
        usage["completionTokens"] = int(u.get("completionTokens") or 0)
        usage["totalTokens"] = int(u.get("totalTokens") or 0)
        usage["estimatedCost"] = float(u.get("estimatedCost") or 0.0)
    except (TypeError, ValueError):
        pass
    return usage


def _coerce_judge_payload(parsed):
    """Coerce a parsed judge dict onto the public result shape with safe defaults."""
    score = parsed.get("score")
    try:
        score = int(score)
    except (TypeError, ValueError):
        score = None
    if score is not None:
        score = max(1, min(5, score))

    verdict = parsed.get("verdict")
    if verdict not in ("correct", "incorrect"):
        verdict = None

    missing = parsed.get("missing_facts")
    if not isinstance(missing, list):
        missing = []
    missing = [str(x) for x in missing][:50]

    return {
        "score": score,
        "verdict": verdict,
        "justification": str(parsed.get("justification") or "")[:4000],
        "missing_facts": missing,
        "hallucination": bool(parsed.get("hallucination")),
        "usage": {
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "estimatedCost": 0.0,
        },
        "error": None,
    }


def _safe_failure(message):
    """The safe result returned when the judge call cannot produce a verdict."""
    return {
        "score": None,
        "verdict": None,
        "justification": "",
        "missing_facts": [],
        "hallucination": False,
        "usage": {
            "promptTokens": 0,
            "completionTokens": 0,
            "totalTokens": 0,
            "estimatedCost": 0.0,
        },
        "error": str(message)[:500],
    }


def run_llm_judge(project, question, reference_answer, expected_value, full_answer,
                  llm_id=config.JUDGE_LLM_ID):
    """Call the LLM judge over Mesh and return its structured verdict (DSS-touching).

    Uses the native Mesh completion API: ``project.get_llm(llm_id).new_completion()``
    with ``with_json_output(JUDGE_OUTPUT_SCHEMA)`` for reliable structure, the
    hardened rubric as the system message, and the four labelled inputs as the user
    message. Parses the JSON and also captures the judge's OWN token usage / cost
    (``total_usage``) under the ``usage`` key.

    Never raises: any failure (Mesh error, JSON-mode unavailable, unparseable
    output) returns a safe dict with ``verdict=None`` and a populated ``error``
    field, so a flaky judge call degrades one row instead of aborting the run.

    Lazy ``import json`` only; ``dataiku`` is never imported here because the
    ``project`` handle is passed in by the DSS step (which owns the dataiku import).
    """
    import json

    try:
        llm = project.get_llm(llm_id)
    except Exception as e:
        return _safe_failure("get_llm failed: {0}".format(e))

    system_prompt = _JUDGE_SYSTEM
    user_msg = build_judge_prompt(question, reference_answer, expected_value,
                                  full_answer)

    # Attempt native JSON mode first; fall back to a prompt-only parse if the model
    # or connection rejects with_json_output (mirrors the sub-agent's UNDERSTAND).
    last_error = None
    for use_json_mode in (True, False):
        try:
            completion = llm.new_completion()
            if use_json_mode:
                try:
                    completion.with_json_output(schema=JUDGE_OUTPUT_SCHEMA)
                except Exception as e:
                    last_error = "json_mode_unavailable: {0}".format(e)
            completion.with_message(system_prompt, role="system")
            completion.with_message(user_msg, role="user")
            resp = completion.execute()
        except Exception as e:
            last_error = "execute failed: {0}".format(e)
            continue

        usage = _judge_usage_from_resp(resp)
        raw = getattr(resp, "text", None)
        parsed = _parse_judge_json(raw, json)
        if parsed is None:
            last_error = "unparseable judge output"
            continue
        result = _coerce_judge_payload(parsed)
        result["usage"] = usage
        if result["verdict"] is None and result["score"] is None:
            # Parsed JSON but with neither a verdict nor a score: not usable.
            last_error = "judge output missing score and verdict"
            continue
        return result

    return _safe_failure(last_error or "judge call failed")


def _parse_judge_json(raw, json_mod):
    """Parse the judge response text into a dict, tolerating fenced / wrapped JSON."""
    if raw is None:
        return None
    if isinstance(raw, dict):
        return raw
    try:
        text = str(raw).strip()
    except Exception:
        return None
    if not text:
        return None
    # Direct parse first.
    try:
        obj = json_mod.loads(text)
        return obj if isinstance(obj, dict) else None
    except Exception:
        pass
    # Strip a ```json ... ``` fence if present.
    fenced = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        obj = json_mod.loads(fenced)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    # Last resort: the first balanced { ... } block.
    m = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if m:
        try:
            obj = json_mod.loads(m.group(0))
            return obj if isinstance(obj, dict) else None
        except Exception:
            return None
    return None


# ---------------------------------------------------------------------------
# Final correctness rule (PURE, deterministic - design section 6.3)
# ---------------------------------------------------------------------------
def final_correctness(objective_match, judge):
    """Combine the objective anchor and the judge verdict into the final decision.

    Rules (design section 6.3):
      - WITH an anchor (objective_match in {hit, miss}): the anchor is ground truth,
        so ``correct = (objective_match == "hit")``; the judge only adds nuance.
      - WITHOUT an anchor (n/a / missing): ``correct = (verdict == "correct" and
        score >= 4)``.
      - ``needs_review`` is True when the anchor and the judge DISAGREE (anchor hit
        but judge says incorrect, or anchor miss but judge says correct), or when
        the agent errored (passed in as objective_match=='error' or judge carrying
        an error). These rows are the most instructive and should be re-read first.

    Returns ``{"correct": bool, "needs_review": bool}``. Pure, never raises.
    """
    judge = judge or {}
    verdict = judge.get("verdict")
    score = judge.get("score")
    judge_error = bool(judge.get("error"))

    anchor = (objective_match or "").strip().lower() if isinstance(
        objective_match, str) else NA

    # An explicit agent error always flags review and is never correct.
    if anchor == "error":
        return {"correct": False, "needs_review": True}

    if anchor in (HIT, MISS):
        correct = (anchor == HIT)
        # Disagreement between the deterministic anchor and the LLM judge.
        disagree = (
            (anchor == HIT and verdict == "incorrect")
            or (anchor == MISS and verdict == "correct")
        )
        needs_review = disagree or judge_error
        return {"correct": correct, "needs_review": needs_review}

    # No anchor: lean on the judge. A missing / failed judge cannot confirm. A verdict that
    # carries NO usable score (the prompt-only judge fallback does not enforce the schema's
    # required score) is ambiguous - flag it for a human rather than silently scoring it wrong.
    has_score = isinstance(score, int)
    correct = (verdict == "correct" and has_score and score >= 4)
    needs_review = judge_error or verdict is None or not has_score
    return {"correct": correct, "needs_review": needs_review}
