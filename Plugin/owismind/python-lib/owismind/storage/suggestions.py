"""User-suggested benchmark questions (the collaborative golden-set intake).

A signed-in user can propose a benchmark question with the answer they vouch for, either
from a chat answer (the message "..." menu) or from the standalone Benchmark page. Each
proposal is one owner-stamped row in ``webapp_golden_suggestions_v1``. The admin pole (the
OWIsMind_LAB benchmark webapp) later reads this table cross-project READ-ONLY and promotes
accepted rows into the golden dataset; this module only handles the WRITE (a deliberate user
action) and the owner-scoped "my suggestions" read.

Storage rules (backend non-negotiables, mirror storage/artifacts.py):
  - Direct SQL only, parametrized via ``sql_value`` / ``nullable_value`` (no f-strings around values).
  - ``COMMIT`` after the write; no Flow at runtime; no generic SQL route.
  - Owner-scoped on read (``user_id`` in the WHERE), like every chat reader.
  - Bounded: every user-supplied string is length-capped before it reaches SQL, and the
    write/read run under a ``statement_timeout`` (the read additionally READ-ONLY), so a single
    suggestion can never write an unbounded row nor a runaway read pin a worker thread.
"""

import logging
from uuid import uuid4

from owismind.storage.migrations import (
    GOLDEN_SUGGESTIONS_V1_LOGICAL,
    ensure_golden_suggestions_table,
)
from owismind.storage.serialization import rows_to_json_safe
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)

# Per-field bounds (instance safety): the stored row stays small and the INSERT statement
# text (which DSS logs in full) stays bounded. The agent answer + captured SQL come from the
# already-bounded exchange row; cap them again here as defense in depth.
MAX_QUESTION_CHARS = 8_000
MAX_REFERENCE_CHARS = 8_000
MAX_AGENT_ANSWER_CHARS = 100_000
MAX_MISSING_CHARS = 4_000
MAX_EXPECTED_VALUE_CHARS = 500
MAX_CATEGORY_CHARS = 120
MAX_SQL_JSON_CHARS = 200_000

# Defensive cap on how many of the caller's own suggestions one read returns.
DEFAULT_MY_LIMIT = 100
MAX_MY_LIMIT = 500

_SOURCES = ("chat", "manual")
_EXPECTED_VALUE_TYPES = ("numeric", "currency", "date", "string", "list")
_LANGUAGES = ("fr", "en")

# Instance-safety guards (mirror storage/artifacts.py). The read runs READ-ONLY with a
# statement_timeout; the write is bounded by the same timeout so a single-row INSERT can
# never hang a worker thread.
_READ_PRE_QUERIES = [
    "SET LOCAL statement_timeout TO '30000'",
    "SET LOCAL transaction_read_only TO on",
]
_WRITE_TIMEOUT_PRE_QUERY = "SET LOCAL statement_timeout TO '30000'"

# Columns returned by the owner-scoped "my suggestions" read (light: no agent_answer body /
# no SQL, which are kept only for the admin promotion path).
_MY_COLUMNS = (
    "suggestion_id, source, question, reference_answer, answer_is_correct, "
    "category, language, status, created_at"
)


def _cap(value, max_chars):
    """Trimmed, length-capped string for a nullable text column, or None when blank."""
    if value is None:
        return None
    s = str(value).strip()
    if not s:
        return None
    return s[:max_chars]


def _enum(value, allowed):
    """The value when it is in ``allowed`` (lower-cased), else None."""
    if not isinstance(value, str):
        return None
    v = value.strip().lower()
    return v if v in allowed else None


def _nullable_bool_literal(value):
    """SQL keyword for a nullable boolean: NULL / true / false (server-controlled)."""
    if value is None:
        return "NULL"
    return "true" if value else "false"


def save_suggestion(
    user_id,
    source,
    question,
    reference_answer,
    *,
    exchange_id=None,
    session_id=None,
    agent_key=None,
    agent_answer=None,
    answer_is_correct=None,
    missing_explanation=None,
    expected_value=None,
    expected_value_type=None,
    category=None,
    language="fr",
    generated_sql_json=None,
):
    """Persist one user benchmark suggestion (owner-stamped) and return its id.

    Strings are trimmed + length-capped here (defense in depth); enums are validated;
    ``answer_is_correct`` is a nullable boolean. Raises on a storage error (a suggestion is a
    deliberate user action, so the route surfaces a clean error rather than swallowing it).
    """
    suggestion_id = uuid4().hex
    src = source if source in _SOURCES else "manual"
    lang = language if language in _LANGUAGES else "fr"
    sql_json = _cap(generated_sql_json, MAX_SQL_JSON_CHARS)

    ensure_golden_suggestions_table()
    table = full_table(GOLDEN_SUGGESTIONS_V1_LOGICAL)
    insert = """
    INSERT INTO {table}
      (suggestion_id, user_id, source, exchange_id, session_id, agent_key, question,
       agent_answer, answer_is_correct, reference_answer, missing_explanation,
       expected_value, expected_value_type, category, language, generated_sql_json,
       status, created_at)
    VALUES ({suggestion_id}, {user_id}, {source}, {exchange_id}, {session_id}, {agent_key},
       {question}, {agent_answer}, {answer_is_correct}, {reference_answer},
       {missing_explanation}, {expected_value}, {expected_value_type}, {category},
       {language}, {generated_sql_json}, 'pending', now())
    """.format(
        table=table,
        suggestion_id=sql_value(suggestion_id),
        user_id=sql_value(user_id),
        source=sql_value(src),
        exchange_id=nullable_value(exchange_id),
        session_id=nullable_value(session_id),
        agent_key=nullable_value(agent_key),
        question=nullable_value(_cap(question, MAX_QUESTION_CHARS)),
        agent_answer=nullable_value(_cap(agent_answer, MAX_AGENT_ANSWER_CHARS)),
        answer_is_correct=_nullable_bool_literal(answer_is_correct),
        reference_answer=nullable_value(_cap(reference_answer, MAX_REFERENCE_CHARS)),
        missing_explanation=nullable_value(_cap(missing_explanation, MAX_MISSING_CHARS)),
        expected_value=nullable_value(_cap(expected_value, MAX_EXPECTED_VALUE_CHARS)),
        expected_value_type=nullable_value(_enum(expected_value_type, _EXPECTED_VALUE_TYPES)),
        category=nullable_value(_cap(category, MAX_CATEGORY_CHARS)),
        language=sql_value(lang),
        generated_sql_json=nullable_value(sql_json),
    )
    logger.info(
        "save_suggestion - INSERT into %s suggestion_id=%s user_id=%s source=%s exchange_id=%s",
        table, suggestion_id, user_id, src, exchange_id,
    )
    # The full INSERT text is not logged: it inlines the question + reference bodies.
    new_executor().query_to_df(
        "SELECT 1 AS suggestion_saved",
        pre_queries=[_WRITE_TIMEOUT_PRE_QUERY, insert],
        post_queries=["COMMIT"],
    )
    logger.info("save_suggestion - COMMITTED suggestion_id=%s", suggestion_id)
    return suggestion_id


def list_my_suggestions(user_id, limit=DEFAULT_MY_LIMIT):
    """Return the caller's OWN suggestions (newest first), owner-scoped + bounded.

    Read-only + statement_timeout. Never raises: any problem degrades to an empty list.
    """
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = DEFAULT_MY_LIMIT
    n = max(1, min(n, MAX_MY_LIMIT))
    try:
        ensure_golden_suggestions_table()
        table = full_table(GOLDEN_SUGGESTIONS_V1_LOGICAL)
        sql = (
            "SELECT {cols} FROM {table} WHERE user_id = {user_id} "
            "ORDER BY created_at DESC LIMIT {limit}"
        ).format(cols=_MY_COLUMNS, table=table, user_id=sql_value(user_id), limit=int(n))
        df = new_executor().query_to_df(sql, pre_queries=_READ_PRE_QUERIES)
        return rows_to_json_safe(df)
    except Exception:
        logger.exception("list_my_suggestions - failed for user_id=%s", user_id)
        return []
