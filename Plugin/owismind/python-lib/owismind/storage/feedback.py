"""General user feedback (Help & Support hub, "Feedback general" tab).

A signed-in user can submit a free-form feedback item (bug report, wrong answer,
feature request, UX remark, ...) from the Support hub. Each submission is one
owner-stamped row in ``webapp_feedback_v1``. Admin response is v1 read-only: an
admin answers by editing the table directly in DSS (no in-app reply route yet,
see the v1.3 design spec) - this module only handles the WRITE (a deliberate user
action) and the owner-scoped "my feedback" read.

Storage rules (backend non-negotiables, mirror storage/suggestions.py):
  - Direct SQL only, parametrized via ``sql_value`` / ``nullable_value`` (no f-strings around values).
  - ``COMMIT`` after the write; no Flow at runtime; no generic SQL route.
  - Owner-scoped on read (``user_id`` in the WHERE), like every chat reader.
  - Bounded: every user-supplied string is length-capped before it reaches SQL, and the
    write/read run under a ``statement_timeout`` (the read additionally READ-ONLY), so a single
    feedback item can never write an unbounded row nor a runaway read pin a worker thread.
"""

import logging
from uuid import uuid4

from owismind.storage.migrations import (
    FEEDBACK_V1_LOGICAL,
    ensure_feedback_table,
)
from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    readonly_pre_queries,
    sql_value,
)

logger = logging.getLogger(__name__)

# Per-field bounds (instance safety): the stored row stays small and the INSERT statement
# text (which DSS logs in full) stays bounded.
MAX_MESSAGE_CHARS = 8_000
MAX_CATEGORY_CHARS = 40
MAX_LINKED_SESSION_ID_CHARS = 200

# Defensive cap on how many of the caller's own feedback items one read returns.
DEFAULT_MY_LIMIT = 100
MAX_MY_LIMIT = 500

# Closed set of feedback categories shown in the UI select. An unknown/missing value
# degrades to "other" rather than being rejected (defense in depth: validation.py is
# the primary gate, this is a second, storage-side backstop).
_CATEGORIES = ("bug", "wrong", "feature", "ux", "perf", "data", "routing", "other")

# Instance-safety guards (mirror storage/suggestions.py). The read runs READ-ONLY with a
# statement_timeout; the write is bounded by the same timeout so a single-row INSERT can
# never hang a worker thread.
_READ_PRE_QUERIES = readonly_pre_queries()
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"

# Columns returned by the owner-scoped "my feedback" read.
_MY_COLUMNS = (
    "feedback_id, category, message, status, admin_response, responded_at, created_at"
)


def _cap(value, max_chars):
    """Trimmed, length-capped string for a nullable text column, or None when blank."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_chars]


def _category(value):
    """The category when it is in the closed set (lower-cased), else 'other'."""
    if not isinstance(value, str):
        return "other"
    v = value.strip().lower()
    return v if v in _CATEGORIES else "other"


def save_feedback(user_id, category, message, *, linked_session_id=None):
    """Persist one user feedback item (owner-stamped) and return its id.

    ``category`` is validated against a closed set (falls back to "other"); strings
    are trimmed + length-capped here (defense in depth, primary validation is
    security/validation.py upstream). ``status`` is always 'open' at write. Raises on
    a storage error (a feedback submission is a deliberate user action, so the route
    surfaces a clean error rather than swallowing it).
    """
    feedback_id = uuid4().hex
    cat = _category(category)

    ensure_feedback_table()
    table = full_table(FEEDBACK_V1_LOGICAL)
    insert = """
    INSERT INTO {table}
      (feedback_id, user_id, category, message, linked_session_id, status, created_at)
    VALUES ({feedback_id}, {user_id}, {category}, {message}, {linked_session_id},
      'open', now())
    """.format(
        table=table,
        feedback_id=sql_value(feedback_id),
        user_id=sql_value(user_id),
        category=sql_value(cat),
        message=nullable_value(_cap(message, MAX_MESSAGE_CHARS)),
        linked_session_id=nullable_value(_cap(linked_session_id, MAX_LINKED_SESSION_ID_CHARS)),
    )
    logger.info(
        "save_feedback - INSERT into %s feedback_id=%s user_id=%s category=%s",
        table, feedback_id, user_id, cat,
    )
    # The full INSERT text is not logged: it inlines the feedback message body.
    new_executor().query_to_df(
        "SELECT 1 AS feedback_saved",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, insert],
        post_queries=["COMMIT"],
    )
    logger.info("save_feedback - COMMITTED feedback_id=%s", feedback_id)
    return feedback_id


def list_my_feedback(user_id, limit=DEFAULT_MY_LIMIT):
    """Return the caller's OWN feedback items (newest first), owner-scoped + bounded.

    Read-only + statement_timeout. Never raises: any problem degrades to an empty list.
    """
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_MY_LIMIT
    n = max(1, min(n, MAX_MY_LIMIT))
    try:
        ensure_feedback_table()
        table = full_table(FEEDBACK_V1_LOGICAL)
        sql = (
            "SELECT {cols} FROM {table} WHERE user_id = {user_id} "
            "ORDER BY created_at DESC LIMIT {limit}"
        ).format(cols=_MY_COLUMNS, table=table, user_id=sql_value(user_id), limit=int(n))
        df = new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES)
        return rows_to_json_safe(df)
    except Exception:
        logger.exception("list_my_feedback - failed for user_id=%s", user_id)
        return []
