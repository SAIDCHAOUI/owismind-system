"""Validation of incoming request payloads (pure - no DSS env required).

The frontend only ever sends logical data (session_id, message, an opaque
agent_key, a context-window size, an optional parent exchange id, feedback). It
never chooses a table, column, query, connection or raw agent id. Every helper
here validates shape and bounds before any value reaches SQL, and returns a stable
machine-readable ``code`` (never an internal detail) when the payload is invalid.
"""

import math
import re

from owismind.benchmark_view.agent_profile import validate_benchmark_block

# Defensive upper bound on message length (avoid pathological payloads).
MAX_MESSAGE_LENGTH = 8000

# Defensive upper bound on the frontend-supplied session id (a uuid is ~36 chars).
MAX_SESSION_ID_LENGTH = 128

# Defensive upper bound on the opaque agent logical key ("ag_" + 12 hex = 15 chars).
MAX_AGENT_KEY_LENGTH = 64


class ValidationError(ValueError):
    """Raised when the incoming payload is invalid. ``code`` is a stable, safe
    machine-readable error code returned to the frontend (no internal details)."""

    def __init__(self, code, message=None):
        self.code = code
        super().__init__(message or code)


def validate_message(payload):
    """Validate the payload and return the cleaned message string.

    Raises ``ValidationError`` (with a stable ``code``) on any problem.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload", "Request body must be a JSON object")

    message = payload.get("message")
    if not isinstance(message, str):
        raise ValidationError("missing_message", "Field 'message' (string) is required")

    if len(message) > MAX_MESSAGE_LENGTH:
        raise ValidationError(
            "message_too_long",
            "Field 'message' exceeds {} characters".format(MAX_MESSAGE_LENGTH),
        )

    cleaned = message.strip()
    if not cleaned:
        raise ValidationError("empty_message", "Field 'message' must not be empty")

    return cleaned


def validate_chat_request(payload):
    """Validate the common ``{session_id, message}`` core and return them.

    Shared base for ``validate_chat_start_request`` (which layers ``agent_key`` on
    top). Identity is resolved from the auth headers, never the body. Raises
    ``ValidationError`` (with a stable ``code``) on any problem.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload", "Request body must be a JSON object")

    session_id = payload.get("session_id")
    if not isinstance(session_id, str):
        raise ValidationError(
            "missing_session_id", "Field 'session_id' (string) is required"
        )
    session_id = session_id.strip()
    if not session_id:
        raise ValidationError("empty_session_id", "Field 'session_id' must not be empty")
    if len(session_id) > MAX_SESSION_ID_LENGTH:
        raise ValidationError(
            "session_id_too_long",
            "Field 'session_id' exceeds {} characters".format(MAX_SESSION_ID_LENGTH),
        )

    message = validate_message(payload)
    return session_id, message


def validate_chat_start_request(payload):
    """Validate a /chat/start payload and return ``(session_id, message, agent_key)``.

    Extends the /chat payload with ``agent_key``: the OPAQUE logical key of the
    agent the user picked. It is bounded in length here; whether it maps to a real,
    enabled agent is enforced separately server-side (settings.resolve_enabled_agent).
    Identity comes from the auth headers; the raw agent_id is never accepted here.
    Raises ``ValidationError`` (with a stable ``code``) on any problem.
    """
    session_id, message = validate_chat_request(payload)

    agent_key = payload.get("agent_key")
    if not isinstance(agent_key, str):
        raise ValidationError("missing_agent_key", "Field 'agent_key' (string) is required")
    agent_key = agent_key.strip()
    if not agent_key:
        raise ValidationError("empty_agent_key", "Field 'agent_key' must not be empty")
    if len(agent_key) > MAX_AGENT_KEY_LENGTH:
        raise ValidationError(
            "agent_key_too_long",
            "Field 'agent_key' exceeds {} characters".format(MAX_AGENT_KEY_LENGTH),
        )

    return session_id, message, agent_key


# --- Agent-context history window (number of MESSAGES, not conversations) -----
MIN_HISTORY_LIMIT = 10
MAX_HISTORY_LIMIT = 50
DEFAULT_HISTORY_LIMIT = 20


def validate_history_limit(value):
    """Clamp the client-supplied agent-context window to [10, 50]; default 20.

    Counts individual messages (user/assistant). Never raises - a bad value must
    not break a chat send; it just falls back to a safe default/bound.
    """
    if value is None:
        return DEFAULT_HISTORY_LIMIT
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_HISTORY_LIMIT
    if n < MIN_HISTORY_LIMIT:
        return MIN_HISTORY_LIMIT
    if n > MAX_HISTORY_LIMIT:
        return MAX_HISTORY_LIMIT
    return n


# --- Sidebar conversation-list page size -------------------------------------
MIN_CONV_PAGE = 1
MAX_CONV_PAGE = 60
DEFAULT_CONV_PAGE = 30


def validate_conversations_limit(value):
    """Clamp the sidebar page size to [1, 60]; default 30. Never raises."""
    if value is None:
        return DEFAULT_CONV_PAGE
    try:
        n = int(value)
    except (TypeError, ValueError):
        return DEFAULT_CONV_PAGE
    if n < MIN_CONV_PAGE:
        return MIN_CONV_PAGE
    if n > MAX_CONV_PAGE:
        return MAX_CONV_PAGE
    return n


# --- Per-message feedback ----------------------------------------------------
ALLOWED_FEEDBACK_REASONS = ("incorrect", "incomplete", "off_topic", "other")
MAX_FEEDBACK_REASONS = 8
MAX_FEEDBACK_COMMENT_CHARS = 2000


def validate_feedback(payload):
    """Validate a per-message feedback payload.

    Returns ``(exchange_id, rating, reasons, comment)``:
      - ``exchange_id``: required non-empty str (<= MAX_SESSION_ID_LENGTH).
      - ``rating``: 0 (down), 1 (up) or None (clear). Anything else -> ValidationError.
      - ``reasons``: list filtered to the allowed set (unknown dropped), capped.
      - ``comment``: str, length-bounded.
    Raises ValidationError only on structurally invalid input.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = payload.get("exchange_id")
    if not exchange_id or not isinstance(exchange_id, str) or len(exchange_id) > MAX_SESSION_ID_LENGTH:
        raise ValidationError("invalid_exchange_id")
    rating = payload.get("rating")
    # Reject bool explicitly (True/False are int subclasses); only 0, 1 or None allowed.
    if isinstance(rating, bool) or rating not in (0, 1, None):
        raise ValidationError("invalid_rating")
    raw_reasons = payload.get("reasons") or []
    if not isinstance(raw_reasons, list):
        raw_reasons = []
    reasons = [r for r in raw_reasons if r in ALLOWED_FEEDBACK_REASONS][:MAX_FEEDBACK_REASONS]
    comment = payload.get("comment") or ""
    if not isinstance(comment, str):
        comment = ""
    comment = comment[:MAX_FEEDBACK_COMMENT_CHARS]
    return exchange_id, rating, reasons, comment


def validate_optional_exchange_id(value):
    """A client-supplied parent_exchange_id: a non-empty str <= MAX_SESSION_ID_LENGTH, else None.

    Never raises - a malformed value degrades to None (= start a new branch at the root).
    Server still scopes every read/write by user_id, so a forged id can only ever match
    the caller's own rows.
    """
    if not value or not isinstance(value, str) or len(value) > MAX_SESSION_ID_LENGTH:
        return None
    return value


# --- Benchmark suggestions (the collaborative golden-set intake) ---------------
# A signed-in user proposes a benchmark question + the answer they vouch for, either from a
# chat answer (keyed by exchange_id) or as a brand-new manual Q/A. The frontend only sends
# logical display text (question, reference, an optional crisp value + its type, a category):
# never a table/query/connection/raw agent id. Bounds keep a single suggestion small.
MAX_SUGGEST_TEXT_CHARS = 8_000        # question / reference answer
MAX_SUGGEST_MISSING_CHARS = 4_000     # "what was wrong/missing" explanation
MAX_SUGGEST_EXPECTED_CHARS = 500      # the crisp anchor fact
MAX_SUGGEST_CATEGORY_CHARS = 120
SUGGEST_EXPECTED_VALUE_TYPES = ("numeric", "currency", "date", "string", "list")
SUGGEST_LANGUAGES = ("fr", "en")


def _required_suggest_text(payload, key, max_chars, code):
    """A required, non-empty, length-bounded display string. Raises ``code`` otherwise."""
    value = payload.get(key)
    if not isinstance(value, str):
        raise ValidationError(code)
    value = value.strip()
    if not value or len(value) > max_chars:
        raise ValidationError(code)
    return value


def _optional_suggest_text(payload, key, max_chars):
    """An optional display string -> trimmed + capped, or None when blank/absent. Never raises."""
    value = payload.get(key)
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    return value[:max_chars]


def _suggest_language(value):
    """A suggestion language: 'fr'/'en' (default 'fr'). Never raises."""
    if isinstance(value, str) and value.strip().lower() in SUGGEST_LANGUAGES:
        return value.strip().lower()
    return "fr"


def _suggest_expected(payload):
    """Validate the optional ``(expected_value, expected_value_type)`` pair.

    When a crisp value is given its type is REQUIRED and must be a known enum (the objective
    anchor needs the type to normalize - mirrors the golden schema rule). Returns
    ``(expected_value, expected_value_type)``, both None when absent.
    """
    expected_value = _optional_suggest_text(payload, "expected_value", MAX_SUGGEST_EXPECTED_CHARS)
    raw_type = payload.get("expected_value_type")
    expected_type = None
    if isinstance(raw_type, str) and raw_type.strip():
        expected_type = raw_type.strip().lower()
        if expected_type not in SUGGEST_EXPECTED_VALUE_TYPES:
            raise ValidationError("invalid_expected_type")
    if expected_value is not None and expected_type is None:
        raise ValidationError("missing_expected_type")
    return expected_value, expected_type


def validate_suggestion_manual(payload):
    """Validate a standalone (manual) benchmark suggestion. Returns a normalized dict.

    Required: ``question`` + ``reference_answer``. Optional: ``expected_value`` (+ its type),
    ``category``, ``language`` (default 'fr'). Raises ``ValidationError`` (stable code) on a
    structurally invalid payload.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    question = _required_suggest_text(payload, "question", MAX_SUGGEST_TEXT_CHARS, "invalid_question")
    reference = _required_suggest_text(
        payload, "reference_answer", MAX_SUGGEST_TEXT_CHARS, "invalid_reference"
    )
    expected_value, expected_type = _suggest_expected(payload)
    return {
        "question": question,
        "reference_answer": reference,
        "expected_value": expected_value,
        "expected_value_type": expected_type,
        "category": _optional_suggest_text(payload, "category", MAX_SUGGEST_CATEGORY_CHARS),
        "language": _suggest_language(payload.get("language")),
    }


def validate_suggestion_from_chat(payload):
    """Validate a from-chat benchmark suggestion. Returns a normalized dict.

    Required: ``exchange_id`` + ``answer_is_correct`` (a strict bool). When the agent answer
    is judged INCORRECT, ``reference_answer`` is required (the correct answer the user
    vouches for); when judged correct, the agent answer itself is stored as the reference
    server-side, so no reference text is required from the user. Optional:
    ``missing_explanation``, ``category``. The question / agent answer / agent_key / SQL are
    NOT taken from the client - they are reconstructed from the persisted exchange server-side.
    Raises ``ValidationError`` (stable code) on a structurally invalid payload.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = validate_required_exchange_id(payload.get("exchange_id"))
    answer_is_correct = payload.get("answer_is_correct")
    if not isinstance(answer_is_correct, bool):
        raise ValidationError("invalid_verdict")
    # A "No" verdict must carry the correct answer; a "Yes" verdict needs none (the agent
    # answer becomes the reference downstream), but an optional note is still accepted.
    if not answer_is_correct:
        reference = _required_suggest_text(
            payload, "reference_answer", MAX_SUGGEST_TEXT_CHARS, "missing_reference"
        )
    else:
        reference = _optional_suggest_text(payload, "reference_answer", MAX_SUGGEST_TEXT_CHARS)
    return {
        "exchange_id": exchange_id,
        "answer_is_correct": answer_is_correct,
        "reference_answer": reference,
        "missing_explanation": _optional_suggest_text(
            payload, "missing_explanation", MAX_SUGGEST_MISSING_CHARS
        ),
        "category": _optional_suggest_text(payload, "category", MAX_SUGGEST_CATEGORY_CHARS),
    }


# --- Evidence Studio -----------------------------------------------------------
# The frontend NEVER sends SQL to /evidence/*: only an exchange_id, structured
# {column, op, values} filters (the editable chips), kept locked-chip ids, a
# bounded page and an optional sort. Column EXISTENCE is checked by the service
# against the live dataset schema; here we validate shape and bounds only.
MAX_EVIDENCE_FILTERS = 20
MAX_EVIDENCE_IN_VALUES = 50
MAX_EVIDENCE_VALUE_CHARS = 500
# Row-window pagination (shared by /evidence/rows and /source/rows). The client asks
# for an explicit limit + offset instead of a page index: a first load of up to
# MAX_ROWS_LIMIT rows, then small follow-up windows. OFFSET pagination makes the
# server re-sort and skip `offset` rows, so a deep offset is an O(offset) cost on the
# dataset's connection; capping the offset bounds that worst case. Both values are
# CLAMPED (never raise): a missing / malformed value degrades to the default, an
# out-of-range one to the nearest bound (same philosophy as the old page clamp). The
# browsable window is bounded by MAX_ROWS_OFFSET + MAX_ROWS_LIMIT (600 rows) before
# the user must filter.
MAX_ROWS_LIMIT = 100
MAX_ROWS_OFFSET = 500
DEFAULT_ROWS_LIMIT = 50
# The free-text search cap. Shared: /source/rows AND /evidence/rows both take a `q`.
MAX_SOURCE_QUERY_CHARS = 200
MAX_EVIDENCE_KEPT_IDS = 100
MAX_EVIDENCE_COLUMN_CHARS = 128
# Optional source-table selector (multi-table SQL): the client may ask Evidence
# to re-query a SPECIFIC matched source table instead of the first one. Only a
# bounded identifier string travels; the service re-validates it against the SQL's
# own set of matched tables, so this is a request, never an authority.
MAX_EVIDENCE_TABLE_CHARS = 256
# Client-filter op whitelist. /evidence/rows stays equality + IN only (the editable
# chips are always a single value or an IN list). The /source/* routes additionally
# accept BETWEEN so a date-range chip (a low/high pair) can filter the raw dataset;
# render_predicate already supports BETWEEN, and _source_conditions renders it as-is.
EVIDENCE_FILTER_OPS = ("=", "IN")
SOURCE_FILTER_OPS = ("=", "IN", "BETWEEN")
# Drill-down labels (one per drillable group key): the server re-derives the
# drillable column set from the STORED SQL, so only shape/bounds are checked
# here. Mirrored by evidence.service.MAX_DRILL_CONDITIONS (defense in depth).
MAX_EVIDENCE_DRILL = 8


def validate_required_exchange_id(value):
    """A mandatory exchange id: non-empty bounded string - raises otherwise."""
    if not value or not isinstance(value, str) or len(value) > MAX_SESSION_ID_LENGTH:
        raise ValidationError("invalid_exchange_id")
    return value


def validate_evidence_column(value):
    """A column NAME (shape only - existence is checked against the live schema)."""
    if not value or not isinstance(value, str) or len(value) > MAX_EVIDENCE_COLUMN_CHARS:
        raise ValidationError("invalid_filter_column")
    return value


def _validate_evidence_value(v):
    # bool FIRST (it is an int subclass) - allowed here: boolean dataset columns
    # are legitimate filter values, unlike the feedback rating trap.
    if isinstance(v, bool):
        return v
    if isinstance(v, float) and not math.isfinite(v):
        # NaN/Infinity parse as JSON literals but render as unquoted SQL tokens
        # downstream - reject at the gate with a stable code instead.
        raise ValidationError("invalid_filter_value")
    if isinstance(v, (int, float)):
        # JSON ints have arbitrary precision in Python: a 100k-digit literal
        # would otherwise inline into the executed (and DSS-logged) statement.
        # The str-length cap mirrors the string bound (SQL-INST-02).
        if len(str(v)) > MAX_EVIDENCE_VALUE_CHARS:
            raise ValidationError("filter_value_too_long")
        return v
    if isinstance(v, str):
        if len(v) > MAX_EVIDENCE_VALUE_CHARS:
            raise ValidationError("filter_value_too_long")
        return v
    raise ValidationError("invalid_filter_value")


def _parse_evidence_filters(raw_filters, allowed_ops=EVIDENCE_FILTER_OPS):
    """Shape + bounds a list of ``{column, op, values}`` chips into normalized dicts.

    Shared by /evidence/rows and /source/rows: same caps and stable codes. ``allowed_ops``
    is the op whitelist the ``op`` is checked against: /evidence/rows uses the default
    ``EVIDENCE_FILTER_OPS`` (equality + IN only), while the /source/* routes pass
    ``SOURCE_FILTER_OPS`` to also accept a BETWEEN date-range chip. Arity by op: ``=``
    requires exactly 1 value, ``BETWEEN`` exactly 2 (the range low/high), ``IN`` 1..cap;
    an out-of-arity op raises 'invalid_filter_values'. Column EXISTENCE is checked against
    the live schema downstream; here only shape/bounds.
    """
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_EVIDENCE_FILTERS:
        raise ValidationError("invalid_filters")
    filters = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ValidationError("invalid_filters")
        column = validate_evidence_column(item.get("column"))
        op = item.get("op")
        if op not in allowed_ops:
            raise ValidationError("invalid_filter_op")
        values = item.get("values")
        if not isinstance(values, list) or not values or len(values) > MAX_EVIDENCE_IN_VALUES:
            raise ValidationError("invalid_filter_values")
        if op == "=" and len(values) != 1:
            raise ValidationError("invalid_filter_values")
        if op == "BETWEEN" and len(values) != 2:
            raise ValidationError("invalid_filter_values")
        filters.append({"column": column, "op": op,
                        "values": [_validate_evidence_value(v) for v in values]})
    return filters


def _parse_rows_limit(value):
    """Clamp a client row-window limit to ``[1, MAX_ROWS_LIMIT]``. Never raises.

    A missing / malformed value (including a bool - an int subclass that must not
    read as 0/1) degrades to ``DEFAULT_ROWS_LIMIT``; a valid number is clamped into
    the ``[1, MAX_ROWS_LIMIT]`` band. Mirrors the old page-clamp philosophy: a bad
    limit never fails the request, it just shrinks to a safe window.
    """
    if isinstance(value, bool):
        return DEFAULT_ROWS_LIMIT
    try:
        limit = int(value)
    except (TypeError, ValueError, OverflowError):
        return DEFAULT_ROWS_LIMIT
    return max(1, min(MAX_ROWS_LIMIT, limit))


def _parse_rows_offset(value):
    """Clamp a client row-window offset to ``[0, MAX_ROWS_OFFSET]``. Never raises.

    A missing / malformed value (including a bool) degrades to 0; a valid number is
    clamped into ``[0, MAX_ROWS_OFFSET]`` so a deep OFFSET can never make the dataset
    connection skip an unbounded number of rows.
    """
    if isinstance(value, bool):
        return 0
    try:
        offset = int(value)
    except (TypeError, ValueError, OverflowError):
        return 0
    return max(0, min(MAX_ROWS_OFFSET, offset))


def _parse_evidence_sort(raw_sort):
    """An optional ``{column, dir}`` sort, or None. Malformed input degrades to None.

    The column EXISTENCE is validated against the live schema by the service (which
    errors there); here only shape/bounds are checked, direction is normalized.
    """
    if isinstance(raw_sort, dict):
        column = raw_sort.get("column")
        if column and isinstance(column, str) and len(column) <= MAX_EVIDENCE_COLUMN_CHARS:
            direction = "desc" if str(raw_sort.get("dir") or "").lower() == "desc" else "asc"
            return {"column": column, "dir": direction}
    return None


def _clean_source_query(value):
    """The free-text search string: non-str -> "", control chars -> space, then
    whitespace-collapsed, stripped and length-capped.

    Shared by /source/rows and /evidence/rows (both take a ``q``). Whitespace is
    collapsed (not just trimmed) so the LIKE needle lines up with the server's
    single-space ``concat_ws`` join; the search-condition builder still treats a
    folded needle shorter than 2 chars as no search (returns None). Never raises.
    """
    if not isinstance(value, str):
        return ""
    spaced = "".join(ch if ch.isprintable() else " " for ch in value)
    return " ".join(spaced.split())[:MAX_SOURCE_QUERY_CHARS]


def _parse_evidence_kept_ids(raw_kept):
    """The locked-chip ids to keep: a bounded list of non-negative ints (bool refused).

    Shared by /evidence/rows and /evidence/aggregate. ``None`` / falsy -> ``[]``; a
    non-list, an over-cap list, or any non-int / negative / bool element raises
    'invalid_kept_ids'.
    """
    raw_kept = raw_kept or []
    if not isinstance(raw_kept, list) or len(raw_kept) > MAX_EVIDENCE_KEPT_IDS:
        raise ValidationError("invalid_kept_ids")
    kept_ids = []
    for v in raw_kept:
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValidationError("invalid_kept_ids")
        kept_ids.append(v)
    return kept_ids


def _parse_evidence_drill(raw_drill):
    """Optional drill-down labels: <= MAX_EVIDENCE_DRILL ``{column, value}`` entries.

    Shared by /evidence/rows and /evidence/aggregate. ``None`` / falsy -> ``[]``. Unlike
    sort, a malformed drill RAISES: a drill silently dropped would return the UNdrilled
    (wider) scope while the UI believes it shows one group - a scope-honesty violation,
    not a cosmetic degradation. Values reuse the filter-value gates (str <= cap, finite
    numbers, bool) with None additionally allowed (IS NULL drill). One stable code for the
    whole block ('invalid_drill'); the drillable column SET is re-derived server-side from
    the stored SQL, so only shape/bounds are checked here.
    """
    drill = []
    raw_drill = raw_drill or []
    if not isinstance(raw_drill, list) or len(raw_drill) > MAX_EVIDENCE_DRILL:
        raise ValidationError("invalid_drill")
    for item in raw_drill:
        if not isinstance(item, dict):
            raise ValidationError("invalid_drill")
        try:
            column = validate_evidence_column(item.get("column"))
            value = item.get("value")
            if value is not None:
                value = _validate_evidence_value(value)
        except ValidationError:
            # One stable code for the whole drill block (the helpers' own codes
            # describe filter problems; here the failing unit is the drill).
            raise ValidationError("invalid_drill")
        drill.append({"column": column, "value": value})
    return drill


def _parse_evidence_table(raw_table):
    """Optional source-table selector (multi-table SQL): a bounded identifier or None.

    Shared by /evidence/rows and /evidence/aggregate. A malformed value degrades to None
    (default = first matched table); the service matches a given name against the SQL's
    own set (the client never picks an arbitrary table), so only shape/bounds here.
    """
    if (isinstance(raw_table, str) and raw_table
            and len(raw_table) <= MAX_EVIDENCE_TABLE_CHARS):
        return raw_table
    return None


def _parse_optional_exclude_id(value):
    """The server id of the chip being edited, or None. Never raises.

    On /evidence/distinct the chip currently being edited must not scope its own picker,
    so the client sends its predicate id here. A missing / malformed / negative value
    (or a bool - the int-subclass trap) degrades to None (the picker is then simply
    scoped by every locked predicate). Mirrors the old GET query-param parse verbatim.
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        n = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return n if n >= 0 else None


def validate_evidence_rows_request(payload):
    """Validate a /evidence/rows payload.

    Returns ``(exchange_id, filters, kept_ids, include_advanced, limit, offset,
    sort, drill, table, q)``. Raises ValidationError (stable code) on structurally
    invalid input; ``limit`` and ``offset`` are CLAMPED (never raise), mirroring the
    old page helper. ``filters`` accept ``SOURCE_FILTER_OPS`` (equality + IN + a BETWEEN
    date-range chip): the evidence table now takes the same date-range chip the Source
    Data explorer does. ``drill`` is the optional drill-down label list (<= 8 entries of
    ``{column, value}``; value may be None - it renders an IS NULL test); the
    drillable column SET is re-derived server-side from the stored SQL, so only
    shape and bounds are validated here (single stable code: 'invalid_drill').
    ``table`` is the OPTIONAL source-table selector (multi-table SQL): a bounded
    identifier string or None; the service matches it against the SQL's own set
    of matched tables (the client never picks an arbitrary table). ``q`` is the
    OPTIONAL free-text search term (cleaned like /source/rows, effective only when
    its folded form is >= 2 chars), matched server-side over every live column.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = validate_required_exchange_id(payload.get("exchange_id"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    kept_ids = _parse_evidence_kept_ids(payload.get("kept_ids"))
    include_advanced = bool(payload.get("include_advanced"))
    # Explicit row window (replaces the old page index). Both clamp, never raise.
    limit = _parse_rows_limit(payload.get("limit"))
    offset = _parse_rows_offset(payload.get("offset"))
    # Optional sort: malformed input degrades to None (the service still validates the
    # column against the live schema and errors there).
    sort = _parse_evidence_sort(payload.get("sort"))
    drill = _parse_evidence_drill(payload.get("drill"))
    table = _parse_evidence_table(payload.get("table"))
    # Optional free-text search over every live column (cleaned + capped, never raises;
    # the service treats a folded needle < 2 chars as no search).
    q = _clean_source_query(payload.get("q"))
    return (exchange_id, filters, kept_ids, include_advanced, limit, offset, sort,
            drill, table, q)


def validate_evidence_distinct_request(payload):
    """Validate an /evidence/distinct payload (POST). Returns
    ``(exchange_id, column, exclude_id, q, filters, kept_ids, include_advanced, drill,
    scope_q)``.

    The filter-chip picker is now CASCADING: it only offers values compatible with the
    OTHER currently-active chips (the trap the redesign removes - picking a value with
    zero rows under an active filter). The client therefore sends the same scope object
    /evidence/rows does, so the scope fields are validated by the EXACT same parsers
    (``_parse_evidence_filters`` with ``SOURCE_FILTER_OPS`` incl. a BETWEEN date-range
    chip, ``_parse_evidence_kept_ids``, ``_parse_evidence_drill``, ``include_advanced``
    coerced to a bool). ``column`` is the picked column (shape-only, existence checked
    against the live schema by the service). Two independent search terms travel: ``q``
    is the picker's own search on THAT column, ``scope_q`` the table-level search over
    ALL columns (both cleaned by ``_clean_source_query``, never raise). ``exclude_id`` is
    the server id of the chip being edited (its own predicate must not scope its own
    picker; a malformed value degrades to None). A request WITHOUT the new scope fields
    validates to empty scope and yields the same picker as before.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = validate_required_exchange_id(payload.get("exchange_id"))
    column = validate_evidence_column(payload.get("column"))
    exclude_id = _parse_optional_exclude_id(payload.get("exclude_id"))
    q = _clean_source_query(payload.get("q"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    kept_ids = _parse_evidence_kept_ids(payload.get("kept_ids"))
    include_advanced = bool(payload.get("include_advanced"))
    drill = _parse_evidence_drill(payload.get("drill"))
    scope_q = _clean_source_query(payload.get("scope_q"))
    return (exchange_id, column, exclude_id, q, filters, kept_ids, include_advanced,
            drill, scope_q)


# --- Source Data Explorer ------------------------------------------------------
# Users browse the RAW project datasets an agent is configured with (admin-authored),
# before/after prompting. The frontend never names a table/connection/query: it sends
# the opaque agent logical key + an integer source index (into the agent's validated
# sources block) + evidence-shaped {column, op, values} filters + a free-text q. The
# server resolves the index to a discovered dataset. Bounds mirror Evidence.
MAX_AGENT_SOURCES = 8
MAX_SOURCE_LABEL_CHARS = 60
MAX_SOURCE_DATASET_CHARS = 128
# MAX_SOURCE_QUERY_CHARS lives with the Evidence section now: the free-text `q` is
# shared by /source/rows and /evidence/rows.
# A DSS dataset NAME (never a query): letters, digits, underscore, dot, hyphen. The
# length is bounded by the pattern itself (mirrors MAX_SOURCE_DATASET_CHARS).
_SOURCE_DATASET_RE = re.compile(r"^[A-Za-z0-9_.\-]{1,128}$")


def _validate_source_agent(value):
    """The opaque agent logical key on a /source/* request.

    Same cleaning as the chat-start agent key (validate_chat_start_request): a
    non-empty, length-bounded string. Whether it maps to a real, enabled agent -
    and to a source - is enforced server-side. Raises ``invalid_agent`` otherwise.
    """
    if not isinstance(value, str):
        raise ValidationError("invalid_agent")
    value = value.strip()
    if not value or len(value) > MAX_AGENT_KEY_LENGTH:
        raise ValidationError("invalid_agent")
    return value


def _validate_source_id(value):
    """A source index into the agent's configured sources: int in [0, MAX_AGENT_SOURCES).

    Accepts a JSON int (rows body) or a numeric string (meta/distinct query param).
    bool is refused (int subclass trap). Raises ``invalid_source`` otherwise.
    """
    if isinstance(value, bool):
        raise ValidationError("invalid_source")
    try:
        source_id = int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValidationError("invalid_source")
    if source_id < 0 or source_id >= MAX_AGENT_SOURCES:
        raise ValidationError("invalid_source")
    return source_id


def validate_source_rows_request(payload):
    """Validate a /source/rows payload. Returns ``(agent_key, source_id, q, filters, limit, offset, sort)``.

    Mirrors ``validate_evidence_rows_request`` (same filter/limit/offset/sort helpers
    and bounds) but keyed by an agent + source index instead of an exchange id, and with
    a free-text ``q`` instead of locked chips / drill. Filters accept ``SOURCE_FILTER_OPS``
    (equality + IN + a BETWEEN date-range chip), unlike /evidence/rows. Raises
    ValidationError (stable code) on structurally invalid input; ``limit`` and ``offset``
    are CLAMPED (never raise).
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    agent_key = _validate_source_agent(payload.get("agent"))
    source_id = _validate_source_id(payload.get("source"))
    q = _clean_source_query(payload.get("q"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    limit = _parse_rows_limit(payload.get("limit"))
    offset = _parse_rows_offset(payload.get("offset"))
    sort = _parse_evidence_sort(payload.get("sort"))
    return agent_key, source_id, q, filters, limit, offset, sort


def validate_source_meta_params(agent, source):
    """The ``(agent, source)`` query params on /source/meta. Returns ``(agent_key, source_id)``."""
    return _validate_source_agent(agent), _validate_source_id(source)


def validate_source_distinct_request(payload):
    """Validate a /source/distinct payload (POST). Returns
    ``(agent_key, source_id, column, q, filters, scope_q)``.

    The filter-chip picker is now CASCADING: it only offers values compatible with the
    OTHER currently-active filters (so picking a value that has zero rows under an active
    filter is no longer possible). The client sends the same scope /source/rows does, so
    the agent / source / filters core is validated by the EXACT same helpers (same stable
    codes, ``SOURCE_FILTER_OPS`` including a BETWEEN date-range chip). Two independent
    search terms travel: ``q`` is the picker's own search on THAT column (cleaned + capped),
    ``scope_q`` the table-level free-text search over ALL columns (both never raise). A
    request WITHOUT filters/scope_q validates to empty scope and yields the same picker as
    before. Column existence is checked against the live schema by the service; here only
    shape/bounds.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    agent_key = _validate_source_agent(payload.get("agent"))
    source_id = _validate_source_id(payload.get("source"))
    column = validate_evidence_column(payload.get("column"))
    q = _clean_source_query(payload.get("q"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    scope_q = _clean_source_query(payload.get("scope_q"))
    return agent_key, source_id, column, q, filters, scope_q


# --- Source Data Explorer: safe aggregation -----------------------------------
# The explorer's table view is only a paginated WINDOW; business users also need EXACT
# totals computed by the DATABASE over the FULL filtered set. The frontend never sends
# SQL: it sends a STRUCTURED spec (an optional grouping + whitelisted measures) resolved
# server-side, over the SAME agent + source + {column, op, values} filters + free-text q
# as /source/rows. Only whitelisted aggregate functions and calendar buckets travel; the
# grouped result is always capped. Column EXISTENCE, the numeric-ness required by
# sum/avg, and the temporal-ness required by a bucket are enforced against the LIVE
# schema in the service - here only shape / whitelist / bounds are checked.
AGG_FUNCTIONS = ("count", "count_distinct", "sum", "avg", "median", "min", "max")
MAX_AGG_MEASURES = 8
MAX_AGG_GROUP_ROWS = 50
AGG_BUCKETS = ("month", "quarter", "year")


def _parse_aggregate_limit(value):
    """Clamp the group-rows cap to ``[1, MAX_AGG_GROUP_ROWS]``. Never raises.

    Missing / malformed (including a bool - an int subclass that must not read as 0/1)
    degrades to ``MAX_AGG_GROUP_ROWS``; a valid number is clamped into the band, so a
    grouped aggregation can never return an unbounded group list.
    """
    if isinstance(value, bool):
        return MAX_AGG_GROUP_ROWS
    try:
        limit = int(value)
    except (TypeError, ValueError, OverflowError):
        return MAX_AGG_GROUP_ROWS
    return max(1, min(MAX_AGG_GROUP_ROWS, limit))


def _parse_aggregate_measures(raw_measures):
    """Shape + whitelist a measures list into normalized ``{"fn", "column"}`` dicts.

    A list of 1..MAX_AGG_MEASURES items; each ``fn`` must be in ``AGG_FUNCTIONS``.
    ``count`` is COUNT(*) and takes NO column (a column present is a contract violation
    -> 'invalid_aggregate'); every other fn REQUIRES a column, shape-checked via
    ``validate_evidence_column`` (a missing / malformed column -> 'invalid_filter_column').
    The column EXISTENCE and its numeric-ness (for sum/avg/median) are checked against the
    live schema downstream. Any other structural problem raises 'invalid_aggregate'.
    """
    if (not isinstance(raw_measures, list) or not raw_measures
            or len(raw_measures) > MAX_AGG_MEASURES):
        raise ValidationError("invalid_aggregate")
    measures = []
    for item in raw_measures:
        if not isinstance(item, dict):
            raise ValidationError("invalid_aggregate")
        fn = item.get("fn")
        if fn not in AGG_FUNCTIONS:
            raise ValidationError("invalid_aggregate")
        raw_column = item.get("column")
        if fn == "count":
            if raw_column is not None:
                raise ValidationError("invalid_aggregate")
            column = None
        else:
            column = validate_evidence_column(raw_column)
        measures.append({"fn": fn, "column": column})
    return measures


def _parse_aggregate_group(raw_group):
    """An optional ``{"column", "bucket"}`` grouping, or None.

    ``None`` means an ungrouped aggregation (one totals row). A dict must carry a
    shape-valid ``column`` (``validate_evidence_column`` -> 'invalid_filter_column');
    ``bucket`` is None (group by the raw value) or one of ``AGG_BUCKETS`` (a calendar
    DATE_TRUNC, which additionally requires a temporal column - enforced against the live
    schema in the service). A present-but-non-dict group raises 'invalid_group'; an
    unknown bucket raises 'invalid_group_bucket'.
    """
    if raw_group is None:
        return None
    if not isinstance(raw_group, dict):
        raise ValidationError("invalid_group")
    column = validate_evidence_column(raw_group.get("column"))
    bucket = raw_group.get("bucket")
    if bucket is not None and bucket not in AGG_BUCKETS:
        raise ValidationError("invalid_group_bucket")
    return {"column": column, "bucket": bucket}


def validate_source_aggregate_request(payload):
    """Validate a /source/aggregate payload.

    Returns ``(agent_key, source_id, q, filters, group, measures, limit)``. Mirrors
    ``validate_source_rows_request`` for the agent / source / q / filters core (same
    helpers, same stable codes, same ``SOURCE_FILTER_OPS`` filter ops including a BETWEEN
    date-range chip) and adds a structured aggregation spec: an optional ``group``
    ({column, bucket}) and 1..MAX_AGG_MEASURES whitelisted ``measures`` ({fn, column}).
    Structural problems raise ValidationError with a stable code ('invalid_payload',
    'invalid_aggregate', 'invalid_group', 'invalid_group_bucket', or a reused filter code);
    ``limit`` is CLAMPED to ``[1, MAX_AGG_GROUP_ROWS]`` (never raises). Column existence and
    type gating (numeric for sum/avg/median, temporal for a bucket) are enforced against the
    LIVE schema by the service, not here.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    agent_key = _validate_source_agent(payload.get("agent"))
    source_id = _validate_source_id(payload.get("source"))
    q = _clean_source_query(payload.get("q"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    group = _parse_aggregate_group(payload.get("group"))
    measures = _parse_aggregate_measures(payload.get("measures"))
    limit = _parse_aggregate_limit(payload.get("limit"))
    return agent_key, source_id, q, filters, group, measures, limit


def validate_evidence_aggregate_request(payload):
    """Validate an /evidence/aggregate payload.

    Returns ``(exchange_id, filters, kept_ids, include_advanced, q, drill, table,
    group, measures, limit)``. The base fields are validated EXACTLY like
    ``validate_evidence_rows_request`` (same helpers, same stable codes) MINUS the row
    window (limit/offset/sort), PLUS a structured aggregation spec resolved by the SAME
    ``_parse_aggregate_*`` helpers /source/aggregate uses: an optional ``group``
    ({column, bucket}) and 1..MAX_AGG_MEASURES whitelisted ``measures`` ({fn, column}).
    ``filters`` accept ``SOURCE_FILTER_OPS`` (equality + IN + a BETWEEN date-range chip).
    Structural problems raise ValidationError with a stable code ('invalid_payload',
    'invalid_exchange_id', 'invalid_filter_op'/'invalid_filter_values'/'invalid_filter_value',
    'invalid_kept_ids', 'invalid_drill', 'invalid_aggregate', 'invalid_group',
    'invalid_group_bucket'); the aggregate ``limit`` (group cap) is CLAMPED to
    ``[1, MAX_AGG_GROUP_ROWS]`` (never raises). Column existence and type gating (numeric
    for sum/avg/median, temporal for a bucket) are enforced against the LIVE schema by the
    service, not here.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = validate_required_exchange_id(payload.get("exchange_id"))
    filters = _parse_evidence_filters(payload.get("filters") or [], allowed_ops=SOURCE_FILTER_OPS)
    kept_ids = _parse_evidence_kept_ids(payload.get("kept_ids"))
    include_advanced = bool(payload.get("include_advanced"))
    q = _clean_source_query(payload.get("q"))
    drill = _parse_evidence_drill(payload.get("drill"))
    table = _parse_evidence_table(payload.get("table"))
    group = _parse_aggregate_group(payload.get("group"))
    measures = _parse_aggregate_measures(payload.get("measures"))
    limit = _parse_aggregate_limit(payload.get("limit"))
    return (exchange_id, filters, kept_ids, include_advanced, q, drill, table,
            group, measures, limit)


# --- Monthly budget / quota (admin) -------------------------------------------
# The admin sets a global default monthly limit (US dollars) and may grant per-user
# overrides (permanent or temporary). Amounts are bounded to a sane range; durations
# to whole days; the user-id list is bounded so one admin call can never fan out
# unboundedly. None of these values ever reach SQL unescaped - the storage layer
# inlines amounts as server-computed numeric literals and escapes the user ids.
MAX_BUDGET_USD = 1_000_000.0
MAX_QUOTA_USERS = 1000
MIN_QUOTA_DAYS = 1
MAX_QUOTA_DAYS = 3650  # ~10 years - a "temporary" boost is never unbounded
MAX_QUOTA_NOTE_CHARS = 280


def validate_budget_amount(value):
    """A monetary limit in USD: a finite number in [0, MAX_BUDGET_USD]. Raises otherwise.

    0 is allowed (an explicit "no budget" / hard block); negatives, NaN/inf and
    non-numbers are rejected with a stable code. bool is refused (int subclass trap).
    """
    if isinstance(value, bool):
        raise ValidationError("invalid_amount")
    try:
        amount = float(value)
    except (TypeError, ValueError, OverflowError):
        # OverflowError: a bare huge JSON integer (e.g. 10**400) parses as an
        # arbitrary-precision Python int whose float() overflows - reject cleanly (400)
        # instead of letting it bubble up as an opaque 500.
        raise ValidationError("invalid_amount")
    if not math.isfinite(amount) or amount < 0 or amount > MAX_BUDGET_USD:
        raise ValidationError("invalid_amount")
    return amount


def validate_expires_days(value):
    """Optional temporary-boost duration in whole days, or None (= permanent).

    None / missing / 0 -> None (permanent). Otherwise an int in [1, MAX_QUOTA_DAYS];
    anything else raises a stable code. bool is refused (int subclass trap).
    """
    if value is None or value == 0 or value == "":
        return None
    if isinstance(value, bool):
        raise ValidationError("invalid_expires")
    try:
        days = int(value)
    except (TypeError, ValueError):
        raise ValidationError("invalid_expires")
    if days < MIN_QUOTA_DAYS or days > MAX_QUOTA_DAYS:
        raise ValidationError("invalid_expires")
    return days


def validate_user_id_list(value):
    """A non-empty, bounded list of distinct user ids (each a bounded non-empty str).

    Order-preserving de-dup; caps the count at MAX_QUOTA_USERS and each id at
    MAX_SESSION_ID_LENGTH. Raises a stable code on a structurally invalid list.
    """
    if not isinstance(value, list) or not value:
        raise ValidationError("invalid_user_ids")
    seen = set()
    out = []
    for item in value:
        if not isinstance(item, str):
            raise ValidationError("invalid_user_ids")
        uid = item.strip()
        if not uid or len(uid) > MAX_SESSION_ID_LENGTH:
            raise ValidationError("invalid_user_ids")
        if uid in seen:
            continue
        seen.add(uid)
        out.append(uid)
    if len(out) > MAX_QUOTA_USERS:
        raise ValidationError("too_many_users")
    return out


def validate_quota_note(value):
    """An optional admin memo on an override: a bounded string (empty when absent)."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_QUOTA_NOTE_CHARS]


# --- Agent profile metadata (admin-authored display copy) --------------------
# An admin describes each exposed agent (what it does, capabilities, exposed tools)
# so users see an honest, authored profile instead of hardcoded copy. This content
# is DISPLAY text only - never a query, table, connection or raw agent id - so it is
# sanitized/clamped rather than rejected (an over-long field must not fail the whole
# save). The icon name is whitelisted against the frontend icon registry (an unknown
# name renders nothing client-side anyway, but we keep it tidy server-side too).
MAX_AGENT_TAGLINE_CHARS = 120
MAX_AGENT_DESC_CHARS = 700
MAX_AGENT_CAP_ITEMS = 8
MAX_AGENT_CAP_CHARS = 120
MAX_AGENT_TOOL_ITEMS = 16
MAX_AGENT_TOOL_CHARS = 48

# Curated subset of the frontend icon registry an admin may assign to an agent.
ALLOWED_AGENT_ICONS = frozenset(
    {
        "robot", "sparkle", "sparkles", "trendUp", "alert", "thumbsUp", "layers",
        "chart", "database", "users", "route", "message", "wallet", "shield",
        "globe", "sliders", "bookOpen", "tool", "tag", "grid",
    }
)
DEFAULT_AGENT_ICON = "robot"
ALLOWED_AGENT_BADGES = frozenset({"", "default", "new", "beta"})


def _clean_str(value, max_chars):
    """A single bounded display line: whitespace/control runs collapse to one space,
    the result is stripped and length-capped.

    The cards render as flowing text, so EVERY non-printable character (line breaks,
    tabs, vertical tab, form feed, NEL, U+2028 / U+2029, C0 controls...) becomes a
    space rather than being deleted - that way adjacent words are never glued
    together. Accents and normal printable text (the euro sign included) are kept.
    """
    if not isinstance(value, str):
        return ""
    # Any non-printable char -> space, then collapse whitespace runs + strip.
    spaced = "".join(ch if ch.isprintable() else " " for ch in value)
    return " ".join(spaced.split())[:max_chars]


def _clean_str_list(value, max_items, max_chars):
    """A bounded list of bounded non-empty display lines (order-preserving)."""
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        line = _clean_str(item, max_chars)
        if line:
            out.append(line)
        if len(out) >= max_items:
            break
    return out


# --- Admin conversation review (view-as) -------------------------------------
# An admin consults ANOTHER user's stored conversations (read-only) for agent
# improvement. The target user id travels in the query/body of the admin-gated
# /admin/inspect/* routes; it is bounded here exactly like every other id (the
# storage reads are then scoped on this value, never the admin's own id).
MAX_TARGET_USER_ID_LENGTH = 256


def validate_target_user_id(value):
    """A non-empty, length-bounded target user id (the inspected user). Raises otherwise.

    Stripped; must be a non-empty str of at most ``MAX_TARGET_USER_ID_LENGTH``
    characters - any other shape raises ``ValidationError('invalid_target')``.
    """
    if not isinstance(value, str):
        raise ValidationError("invalid_target")
    value = value.strip()
    if not value or len(value) > MAX_TARGET_USER_ID_LENGTH:
        raise ValidationError("invalid_target")
    return value


# --- Help & Support hub: general feedback (feature A) -------------------------
# A signed-in user submits general UI/UX/product feedback with an optional category tag
# and an optional pointer to the conversation it is about. The frontend sends only
# logical display text (message, category) + an optional session id - never a table,
# query or admin field. The category ENUM itself is enforced at the storage layer
# (storage/feedback.py, closed list -> 'other' fallback); here only shape/bounds.
MAX_FEEDBACK_MESSAGE_CHARS = 8000
MAX_FEEDBACK_CATEGORY_CHARS = 40


def validate_feedback_submission(payload):
    """Validate a /feedback/submit payload. Returns a clean dict.

    Required: ``message`` (non-empty, bounded). Optional: ``category`` (a bounded
    display string - the closed enum + 'other' fallback is enforced at the storage
    layer, not here), ``linked_session_id`` (bounded like every other session id).
    Raises ``ValidationError`` (stable code) on a structurally invalid payload.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    message = payload.get("message")
    if not isinstance(message, str):
        raise ValidationError("missing_message")
    message = message.strip()
    if not message:
        raise ValidationError("empty_message")
    if len(message) > MAX_FEEDBACK_MESSAGE_CHARS:
        raise ValidationError("message_too_long")
    return {
        "message": message,
        "category": _optional_suggest_text(payload, "category", MAX_FEEDBACK_CATEGORY_CHARS),
        "linked_session_id": _optional_suggest_text(
            payload, "linked_session_id", MAX_SESSION_ID_LENGTH
        ),
    }


# --- Help & Support hub: agent-data request (feature B) ------------------------
# A signed-in user requests a new data agent scoped to some of THEIR OWN DSS project's
# SQL tables. The frontend sends a project (key + label, picked from the impersonated
# catalog OR typed manually when the catalog is unavailable), a bounded list of
# ``{dataset, table, connection}`` entries (the catalog picks) OR plain table-name
# strings (the manual fallback - normalized to the same shape here), plus free-text
# business case / use cases / importance. Never a raw SQL query, connection secret or
# admin field.
MAX_AGENT_REQUEST_DATASETS = 25
MAX_AGENT_REQUEST_FIELD_CHARS = 128
MAX_PROJECT_KEY_CHARS = 128
MAX_PROJECT_LABEL_CHARS = 200
MAX_BUSINESS_CASE_CHARS = 4000
MAX_USE_CASES_CHARS = 4000
MAX_IMPORTANCE_CHARS = 200


def _clean_dataset_entry(item):
    """Normalize one dataset pick into a bounded ``{dataset, table, connection}`` dict.

    Accepts either a catalog-shaped dict (``{dataset, table, connection}``, each an
    optional bounded string) or a plain string (the manual free-text fallback). ``dataset``
    is the DSS dataset/object name and is the entry's PRIMARY key at the storage layer
    (storage/agent_requests.py drops any entry lacking it, table/connection alone are not
    enough) - a plain string, or a dict missing ``dataset`` but carrying ``table``, is
    therefore normalized into the ``dataset`` field so a manual entry is never silently
    discarded downstream. Any other shape, or an entry with nothing usable, is dropped
    (returns None) rather than failing the whole list - a malformed entry must not block
    every other well-formed one.
    """
    if isinstance(item, str):
        name = item.strip()[:MAX_AGENT_REQUEST_FIELD_CHARS]
        if not name:
            return None
        return {"dataset": name, "table": None, "connection": None}
    if isinstance(item, dict):
        def _field(key):
            value = item.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()[:MAX_AGENT_REQUEST_FIELD_CHARS]
            return None

        dataset = _field("dataset")
        table = _field("table")
        connection = _field("connection")
        if not dataset:
            # No catalog dataset name known (manual entry with only a table typed in):
            # fall back to the table value so the entry still carries the primary key
            # the storage layer requires.
            dataset = table
        if not dataset:
            return None
        return {"dataset": dataset, "table": table, "connection": connection}
    return None


def _clean_datasets(raw):
    """A bounded list of normalized dataset picks (see ``_clean_dataset_entry``).

    Never raises: a non-list degrades to an empty list, malformed entries are simply
    dropped, and the result is capped at ``MAX_AGENT_REQUEST_DATASETS``.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        cleaned = _clean_dataset_entry(item)
        if cleaned:
            out.append(cleaned)
        if len(out) >= MAX_AGENT_REQUEST_DATASETS:
            break
    return out


def validate_agent_request(payload):
    """Validate an /agent-request/submit payload. Returns a clean dict.

    Required: ``business_case`` (non-empty, bounded). Optional: ``project_key`` /
    ``project_label`` (the chosen or manually-typed project), ``datasets`` (a bounded
    list, catalog picks or manual strings - normalized by ``_clean_datasets``),
    ``use_cases``, ``importance``. Raises ``ValidationError`` (stable code) on a
    structurally invalid payload.
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    business_case = payload.get("business_case")
    if not isinstance(business_case, str):
        raise ValidationError("missing_business_case")
    business_case = business_case.strip()
    if not business_case:
        raise ValidationError("empty_business_case")
    if len(business_case) > MAX_BUSINESS_CASE_CHARS:
        raise ValidationError("business_case_too_long")
    return {
        "business_case": business_case,
        "project_key": _optional_suggest_text(payload, "project_key", MAX_PROJECT_KEY_CHARS),
        "project_label": _optional_suggest_text(
            payload, "project_label", MAX_PROJECT_LABEL_CHARS
        ),
        "datasets": _clean_datasets(payload.get("datasets")),
        "use_cases": _optional_suggest_text(payload, "use_cases", MAX_USE_CASES_CHARS),
        "importance": _optional_suggest_text(payload, "importance", MAX_IMPORTANCE_CHARS),
    }


def validate_sources_block(raw):
    """Sanitize an admin-authored SOURCES list into bounded ``{dataset, label}`` entries.

    A source is a RAW project dataset (admin-selected by NAME) the agent is configured
    with, so users can explore it in the Source Data Explorer. Never raises: a malformed
    entry is dropped, not fatal (same contract as ``validate_agent_meta``). ``dataset``
    must be a DSS dataset name matching ``_SOURCE_DATASET_RE`` (never a query); ``label``
    is a bounded display line, falling back to the dataset name when blank. Entries are
    de-duplicated by dataset (case-insensitive, first wins) and capped at MAX_AGENT_SOURCES.
    The list ORDER is preserved: its index is the stable ``source`` id the client sends.
    """
    if not isinstance(raw, list):
        return []
    out = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        dataset = item.get("dataset")
        if not isinstance(dataset, str):
            continue
        dataset = dataset.strip()
        if not _SOURCE_DATASET_RE.match(dataset):
            continue
        low = dataset.lower()
        if low in seen:
            continue
        seen.add(low)
        out.append({
            "dataset": dataset,
            "label": _clean_str(item.get("label"), MAX_SOURCE_LABEL_CHARS) or dataset,
        })
        if len(out) >= MAX_AGENT_SOURCES:
            break
    return out


def validate_agent_meta(raw):
    """Sanitize an admin-authored agent profile into a bounded, safe display dict.

    Never raises: every field is clamped/dropped to its bound so an over-long or
    malformed field degrades gracefully instead of failing the whole whitelist save.
    Returns ``{tagline, description, capabilities, tools, icon, badge, modes}``; absent
    input yields the empty profile (all fields blank, default icon, modes off).
    """
    if not isinstance(raw, dict):
        raw = {}
    # Coerce to str BEFORE the membership test: an unhashable value (a JSON array ->
    # list, object -> dict) would otherwise raise TypeError on `x in frozenset(...)`,
    # which would break the "never raise / clamp, don't fail" contract this function
    # is relied upon for (it sits on the admin whitelist-save path).
    icon = raw.get("icon")
    if not isinstance(icon, str) or icon not in ALLOWED_AGENT_ICONS:
        icon = DEFAULT_AGENT_ICON
    badge = raw.get("badge")
    if not isinstance(badge, str) or badge not in ALLOWED_AGENT_BADGES:
        badge = ""
    # Whether this agent supports the chat "response modes" dial (Smart / Pro / Claude).
    # Only an agent whose backend actually understands the per-turn ⟦owi:mode=…⟧ control
    # token (the OWIsMind code orchestrator) should enable this. For any other agent
    # (e.g. a plain DSS visual agent) the dial is hidden and the token is never appended
    # server-side, so a meaningless control string never leaks into its prompt. Coerced
    # to a strict bool so a malformed value defaults to off (dial hidden).
    modes = bool(raw.get("modes"))
    # The benchmark block tells the plugin WHERE this agent's benchmark lives (a SQL table the admin
    # selected). Validated/bounded by benchmark_view.agent_profile (an invalid table is blanked, which
    # just disables consultation for that agent - never fails the whole profile save).
    benchmark = validate_benchmark_block(raw.get("benchmark"))
    return {
        "tagline": _clean_str(raw.get("tagline"), MAX_AGENT_TAGLINE_CHARS),
        "description": _clean_str(raw.get("description"), MAX_AGENT_DESC_CHARS),
        "capabilities": _clean_str_list(
            raw.get("capabilities"), MAX_AGENT_CAP_ITEMS, MAX_AGENT_CAP_CHARS
        ),
        "tools": _clean_str_list(
            raw.get("tools"), MAX_AGENT_TOOL_ITEMS, MAX_AGENT_TOOL_CHARS
        ),
        "icon": icon,
        "badge": badge,
        "modes": modes,
        "benchmark": benchmark,
        # The RAW project datasets this agent is configured with (Source Data Explorer).
        "sources": validate_sources_block(raw.get("sources")),
    }
