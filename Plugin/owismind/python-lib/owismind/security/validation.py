"""Validation of incoming request payloads (pure - no DSS env required).

The frontend only ever sends logical data (session_id, message, an opaque
agent_key, a context-window size, an optional parent exchange id, feedback). It
never chooses a table, column, query, connection or raw agent id. Every helper
here validates shape and bounds before any value reaches SQL, and returns a stable
machine-readable ``code`` (never an internal detail) when the payload is invalid.
"""

import math

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


# --- Evidence Studio -----------------------------------------------------------
# The frontend NEVER sends SQL to /evidence/*: only an exchange_id, structured
# {column, op, values} filters (the editable chips), kept locked-chip ids, a
# bounded page and an optional sort. Column EXISTENCE is checked by the service
# against the live dataset schema; here we validate shape and bounds only.
MAX_EVIDENCE_FILTERS = 20
MAX_EVIDENCE_IN_VALUES = 50
MAX_EVIDENCE_VALUE_CHARS = 500
# Max browsable page index. OFFSET pagination makes the server re-sort and skip
# (page * PAGE_SIZE) rows, so a deep page is an O(offset) cost on the dataset's
# connection. 50 rows x 20 pages = 1000 rows browsable before the user must filter,
# which bounds the worst-case OFFSET sort 10x vs. the previous 200.
MAX_EVIDENCE_PAGE = 20
MAX_EVIDENCE_KEPT_IDS = 100
MAX_EVIDENCE_COLUMN_CHARS = 128
# Optional source-table selector (multi-table SQL): the client may ask Evidence
# to re-query a SPECIFIC matched source table instead of the first one. Only a
# bounded identifier string travels; the service re-validates it against the SQL's
# own set of matched tables, so this is a request, never an authority.
MAX_EVIDENCE_TABLE_CHARS = 256
EVIDENCE_FILTER_OPS = ("=", "IN")
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


def validate_evidence_rows_request(payload):
    """Validate a /evidence/rows payload.

    Returns ``(exchange_id, filters, kept_ids, include_advanced, page, sort,
    drill, table)``. Raises ValidationError (stable code) on structurally
    invalid input; the page is CLAMPED (never raises), mirroring the other limit
    helpers. ``drill`` is the optional drill-down label list (<= 8 entries of
    ``{column, value}``; value may be None - it renders an IS NULL test); the
    drillable column SET is re-derived server-side from the stored SQL, so only
    shape and bounds are validated here (single stable code: 'invalid_drill').
    ``table`` is the OPTIONAL source-table selector (multi-table SQL): a bounded
    identifier string or None; the service matches it against the SQL's own set
    of matched tables (the client never picks an arbitrary table).
    """
    if not isinstance(payload, dict):
        raise ValidationError("invalid_payload")
    exchange_id = validate_required_exchange_id(payload.get("exchange_id"))

    raw_filters = payload.get("filters") or []
    if not isinstance(raw_filters, list) or len(raw_filters) > MAX_EVIDENCE_FILTERS:
        raise ValidationError("invalid_filters")
    filters = []
    for item in raw_filters:
        if not isinstance(item, dict):
            raise ValidationError("invalid_filters")
        column = validate_evidence_column(item.get("column"))
        op = item.get("op")
        if op not in EVIDENCE_FILTER_OPS:
            raise ValidationError("invalid_filter_op")
        values = item.get("values")
        if not isinstance(values, list) or not values or len(values) > MAX_EVIDENCE_IN_VALUES:
            raise ValidationError("invalid_filter_values")
        if op == "=" and len(values) != 1:
            raise ValidationError("invalid_filter_values")
        filters.append({"column": column, "op": op,
                        "values": [_validate_evidence_value(v) for v in values]})

    raw_kept = payload.get("kept_ids") or []
    if not isinstance(raw_kept, list) or len(raw_kept) > MAX_EVIDENCE_KEPT_IDS:
        raise ValidationError("invalid_kept_ids")
    kept_ids = []
    for v in raw_kept:
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise ValidationError("invalid_kept_ids")
        kept_ids.append(v)

    include_advanced = bool(payload.get("include_advanced"))

    try:
        page = int(payload.get("page") or 0)
    except (TypeError, ValueError, OverflowError):
        page = 0
    page = max(0, min(MAX_EVIDENCE_PAGE, page))

    # Optional sort: malformed input degrades to None (the service still
    # validates the column against the live schema and errors there).
    sort = None
    raw_sort = payload.get("sort")
    if isinstance(raw_sort, dict):
        column = raw_sort.get("column")
        if column and isinstance(column, str) and len(column) <= MAX_EVIDENCE_COLUMN_CHARS:
            direction = "desc" if str(raw_sort.get("dir") or "").lower() == "desc" else "asc"
            sort = {"column": column, "dir": direction}

    # Optional drill-down labels. Unlike sort, a malformed drill RAISES: a drill
    # silently dropped would return the UNdrilled (wider) page while the UI
    # believes it is showing one group - a scope-honesty violation, not a
    # cosmetic degradation. Values reuse the filter-value gates (str <= 500,
    # finite numbers, bool) with None additionally allowed (IS NULL drill).
    drill = []
    raw_drill = payload.get("drill") or []
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

    # Optional source-table selector (multi-table SQL). A malformed value
    # degrades to None (default = first matched table); the service rejects an
    # unknown table against the SQL's matched set, so only shape/bounds here.
    table = None
    raw_table = payload.get("table")
    if (isinstance(raw_table, str) and raw_table
            and len(raw_table) <= MAX_EVIDENCE_TABLE_CHARS):
        table = raw_table

    return exchange_id, filters, kept_ids, include_advanced, page, sort, drill, table
