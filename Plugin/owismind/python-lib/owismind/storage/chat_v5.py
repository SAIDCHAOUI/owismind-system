"""Reads/writes for the versioned chat_v5 table (direct SQL, no DSS Flow).

Owns ``webapp_chat_v5`` = the chat exchanges (with per-message feedback columns) turned
into a conversation TREE: each exchange carries a ``parent_exchange_id`` linking it to
the exchange it branched from (NULL for a root / first turn). The agent context of an
exchange is its ANCESTOR CHAIN (recursive walk up the parents), so a branch never sees
the messages that came after its branch point — see ``history_messages_for_chain``.

Two-phase write per exchange: the user message is persisted first (with NULL
assistant reply and NULL generated_sql), then the assistant reply, any SQL the
agent generated AND the run's token/cost usage are filled in by a follow-up UPDATE
keyed on the Python-generated ``exchange_id``. User-supplied values are escaped via
``sql_value``; identifiers come from controlled constants via ``full_table``. Every
write COMMITs explicitly.

Over the abandoned _v4 (which added ``parent_exchange_id`` over _v3's per-message
feedback columns, over _v2's ``generated_sql``), _v5 adds the per-exchange USAGE columns
``input_tokens``/``output_tokens``/``total_tokens``/``estimated_cost`` — the run's footer
``usage_summary`` totals, written with the reply. They are the AUTHORITATIVE per-exchange
usage record (the users + monthly aggregates are reconstructible from them). Feedback is
filled out-of-band by ``save_feedback`` (owner-scoped). The persisted ``agent_key`` is the
OPAQUE logical key, never the raw agent_id — so a readback never leaks a real agent id
to the frontend.
"""

import json
import logging
from uuid import uuid4

from owismind.agents.context import exchanges_to_fetch, flatten_exchanges_to_messages
from owismind.evidence import capture  # pure module (no dataiku), no import cycle
from owismind.security.validation import (
    validate_conversations_limit,
    validate_history_limit,
)
from owismind.storage import pagination
from owismind.storage.migrations import CHAT_V5_LOGICAL
from owismind.storage.serialization import parse_json_list, rows_to_json_safe
from owismind.storage.sql_builders import (
    build_ancestor_chain_query,
    build_conversation_list_query,
    build_session_messages_query,
)
from owismind.storage.sql_config import (
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)


# Upper bound on the text PERSISTED into a SQL column. DSS LOGS every SQLExecutor2 query
# (full statement text), and SQLExecutor2 has no server-side bind (official Python API
# reference), so sql_value ALWAYS inlines the value into the logged INSERT/UPDATE
# statement. On this instance a scenario materialises those query logs into a dataset,
# where an over-long SQL cell trips the row-length limit (the observed warning). Chat
# messages are normally KB-sized (well under any limit) — the traces, which can be MBs,
# were the actual culprit and avoid the logged-SQL path entirely via the Dataset writer
# (see chat_traces). This cap bounds the worst case; lower it if your log-materialising
# dataset has a tight per-row limit. The live answer is NOT capped here (bounded
# separately by stream_manager.MAX_ANSWER_CHARS); only the STORED copy is trimmed.
MAX_PERSISTED_TEXT_CHARS = 262_144


def _bounded(text):
    """Trim text to MAX_PERSISTED_TEXT_CHARS, appending a marker when truncated."""
    if text is None:
        return text
    s = str(text)
    if len(s) <= MAX_PERSISTED_TEXT_CHARS:
        return s
    return s[:MAX_PERSISTED_TEXT_CHARS] + "\n…[truncated {} chars for storage]".format(
        len(s) - MAX_PERSISTED_TEXT_CHARS
    )


# Columns selected for a conversation readback, in a stable order (includes generated_sql,
# the per-message feedback columns, parent_exchange_id, and the per-exchange usage columns
# — which feed /conversation -> frontend coloring, conversation-tree reconstruction, and
# the per-message tokens/cost line on reload).
_COLUMNS = (
    "exchange_id, session_id, user_id, user_display_name, user_groups, "
    "user_text, assistant_text, generated_sql, agent_key, created_at, answered_at, "
    "feedback_rating, feedback_reasons, feedback_comment, parent_exchange_id, "
    "input_tokens, output_tokens, total_tokens, estimated_cost"
)


def save_user_message(session_id, identity, user_text, agent_key, parent_exchange_id=None):
    """Persist the user side of an exchange and return its ``exchange_id``.

    Phase one of the two-phase write: assistant_text, generated_sql and answered_at
    are left NULL until the reply is saved; ``created_at`` is set by the DB default.
    The primary key is generated in Python, so no readback is needed.

    ``agent_key`` is the opaque logical key of the agent the user picked (never the
    raw agent_id). ``user_display_name`` is a per-message denormalised SNAPSHOT of
    the derived default at write time; it is intentionally NOT back-updated if the
    display name later changes. ``parent_exchange_id`` links this exchange to the one
    it branched from (NULL for a root / first turn) — the conversation-tree edge.
    """
    exchange_id = uuid4().hex
    groups = identity.get("groups") or []
    if not isinstance(groups, list):
        groups = [groups]
    groups_json = json.dumps(groups)
    # Bound the stored body so the INSERT statement text stays small (CRU log safety).
    user_text = _bounded(user_text)

    table = full_table(CHAT_V5_LOGICAL)
    #   columns:  ... agent_key, parent_exchange_id, answered_at
    #   values:   ... {agent_key}, {parent}, NULL
    insert_sql = """
    INSERT INTO {table}
      (exchange_id, session_id, user_id, user_display_name, user_groups,
       user_text, assistant_text, generated_sql, agent_key, parent_exchange_id, answered_at)
    VALUES ({exchange_id}, {session_id}, {user_id}, {display_name}, {groups},
       {user_text}, NULL, NULL, {agent_key}, {parent}, NULL)
    """.format(
        table=table,
        exchange_id=sql_value(exchange_id),
        session_id=sql_value(session_id),
        user_id=sql_value(identity.get("user_id")),
        display_name=nullable_value(identity.get("display_name")),
        groups=sql_value(groups_json),
        user_text=sql_value(user_text),
        agent_key=sql_value(agent_key),
        parent=nullable_value(parent_exchange_id),
    )
    logger.info(
        "save_user_message — INSERT into %s exchange_id=%s session_id=%s user_id=%s "
        "agent_key=%s groups=%s",
        table,
        exchange_id,
        session_id,
        identity.get("user_id"),
        agent_key,
        groups,
    )
    # The full INSERT text is intentionally NOT logged: it inlines the user message body.
    new_executor().query_to_df(
        "SELECT 1 AS user_saved",
        pre_queries=[insert_sql],
        post_queries=["COMMIT"],
    )
    logger.info("save_user_message — COMMITTED exchange_id=%s", exchange_id)
    return exchange_id


def _usage_literal(value, is_float=False):
    """Safe SQL numeric literal for a server-computed usage value, or ``NULL``.

    Usage values come from the LLM Mesh trace (never user input). They are strictly
    coerced — a missing/non-numeric/negative value becomes SQL ``NULL`` — and inlined
    as a bare numeric literal (floats with fixed decimals to avoid scientific notation),
    which sidesteps any ``Constant(float)`` escaping ambiguity for a fully-controlled,
    non-user value (mirrors the ``bool_literal`` precedent for server-side scalars).
    """
    if value is None:
        return "NULL"
    try:
        if is_float:
            f = float(value)
            return "{:.10f}".format(f) if f >= 0 else "NULL"
        n = int(value)
        return str(n) if n >= 0 else "NULL"
    except (TypeError, ValueError):
        return "NULL"


def save_assistant_message(exchange_id, assistant_text, generated_sql=None, usage=None):
    """Fill in the assistant reply (+ any generated SQL + token/cost usage) for an exchange.

    Phase two: UPDATE assistant_text, generated_sql and the per-exchange usage columns,
    then stamp answered_at via SQL now(), matching on the exchange_id produced by
    ``save_user_message``.

    ``generated_sql`` is a Python list of ``{sql, success, row_count}`` items, plus
    the optional trust-layer keys ``sql_id``/``step_index``/``agent_key``/``result``
    (or None/empty when the run produced no SQL). The list is bounded by
    ``capture.cap_sql_list`` BEFORE serialization (mirror caps on each captured
    ``result``, item-count cap, global serialized budget) — closing the previously
    unbounded sql_json hole. The bounded list is JSON-encoded and stored as text; an
    empty list stores SQL NULL via ``nullable_value`` so "no SQL" reads back cleanly.
    ``_bounded()`` must NEVER touch this JSON: its text marker would corrupt decoding
    (cap_sql_list trims structurally instead).

    ``usage`` is the run's footer ``usage_summary`` totals
    (``promptTokens``/``completionTokens``/``totalTokens``/``estimatedCost``) or None
    (e.g. an early-stopped run with no footer). Each value is coerced to a safe numeric
    literal — written into the same atomic UPDATE as the reply so the per-exchange usage
    record (the source of truth for the aggregates) lands together with the answer.
    """
    capped_sql = capture.cap_sql_list(generated_sql) if generated_sql else None
    sql_json = json.dumps(capped_sql) if capped_sql else None
    # Bound the stored reply so the UPDATE statement text stays small (CRU log safety).
    assistant_text = _bounded(assistant_text)

    usage = usage or {}
    in_sql = _usage_literal(usage.get("promptTokens"))
    out_sql = _usage_literal(usage.get("completionTokens"))
    total_sql = _usage_literal(usage.get("totalTokens"))
    cost_sql = _usage_literal(usage.get("estimatedCost"), is_float=True)

    table = full_table(CHAT_V5_LOGICAL)
    update_sql = """
    UPDATE {table}
    SET assistant_text = {assistant_text},
        generated_sql  = {generated_sql},
        input_tokens   = {in_t},
        output_tokens  = {out_t},
        total_tokens   = {total_t},
        estimated_cost = {cost},
        answered_at    = now()
    WHERE exchange_id = {exchange_id}
    """.format(
        table=table,
        assistant_text=sql_value(assistant_text),
        generated_sql=nullable_value(sql_json),
        in_t=in_sql,
        out_t=out_sql,
        total_t=total_sql,
        cost=cost_sql,
        exchange_id=sql_value(exchange_id),
    )
    logger.info(
        "save_assistant_message — UPDATE %s exchange_id=%s reply_len=%d sql=%s "
        "in=%s out=%s cost=%s",
        table,
        exchange_id,
        len(assistant_text or ""),
        bool(generated_sql),
        in_sql,
        out_sql,
        cost_sql,
    )
    # The full UPDATE text is intentionally NOT logged: it inlines the assistant reply.
    new_executor().query_to_df(
        "SELECT 1 AS assistant_saved",
        pre_queries=[update_sql],
        post_queries=["COMMIT"],
    )
    logger.info("save_assistant_message — COMMITTED exchange_id=%s", exchange_id)


def save_feedback(user_id, exchange_id, rating, reasons, comment):
    """Persist per-message feedback ON the user's own exchange row (owner-scoped).

    rating ∈ {0, 1, None(clear)}. reasons -> JSON list. comment bounded. The WHERE
    is scoped by BOTH exchange_id and user_id, so a user can only rate their own
    messages. No-op (0 rows) if the exchange is not theirs.
    """
    table = full_table(CHAT_V5_LOGICAL)
    reasons_json = json.dumps(reasons) if reasons else None
    bounded_comment = _bounded(comment) if comment else None
    # Stamp feedback_at only when a rating is set; clearing (rating None) blanks it too.
    # This is a fixed SQL literal (now()/NULL), never user input — safe to inline.
    feedback_at_sql = "now()" if rating is not None else "NULL"
    sql = """
        UPDATE {table}
        SET feedback_rating = {rating},
            feedback_reasons = {reasons},
            feedback_comment = {comment},
            feedback_at = {feedback_at}
        WHERE exchange_id = {exchange} AND user_id = {user}
    """.format(
        table=table,
        rating=nullable_value(rating),
        reasons=nullable_value(reasons_json),
        comment=nullable_value(bounded_comment),
        feedback_at=feedback_at_sql,
        exchange=sql_value(exchange_id),
        user=sql_value(user_id),
    )
    logger.info(
        "save_feedback — UPDATE %s exchange_id=%s user_id=%s rating=%s reasons=%d comment_len=%d",
        table,
        exchange_id,
        user_id,
        rating,
        len(reasons or []),
        len(bounded_comment or ""),
    )
    new_executor().query_to_df(
        "SELECT 1 AS feedback_saved", pre_queries=[sql], post_queries=["COMMIT"]
    )
    logger.info("save_feedback — COMMITTED exchange_id=%s user_id=%s", exchange_id, user_id)


# Hard ceiling on the recursive ancestor walk (anti-cycle / instance safety). Far above
# any legitimate conversation depth; combined with the LIMIT it bounds the CTE cost.
MAX_CHAIN_DEPTH = 200


def history_messages_for_chain(user_id, parent_exchange_id, max_messages):
    """Agent context = the ancestor chain of the new exchange (from its parent up to
    the root of THIS branch), newest-first then reversed to chronological, flattened
    to the last ``max_messages`` messages (+ SQL appended, L031). Excludes other
    branches and anything after the branch point. Empty when there is no parent.

    The walk is a recursive CTE that is user-scoped in BOTH members and bounded by
    depth AND a row LIMIT; ``parent_exchange_id`` (the chain start) and the user value
    are escaped via ``sql_value``. Never alters storage.
    """
    if not parent_exchange_id:
        return []
    limit = validate_history_limit(max_messages)
    n_exchanges = exchanges_to_fetch(limit)
    table = full_table(CHAT_V5_LOGICAL)
    sql = build_ancestor_chain_query(
        table_ref=table,
        columns="user_text, assistant_text, generated_sql, created_at, exchange_id",
        user_value_sql=sql_value(user_id),
        start_exchange_sql=sql_value(parent_exchange_id),
        max_depth=MAX_CHAIN_DEPTH,
        cap=n_exchanges,
    )
    df = new_executor().query_to_df(sql)
    rows = rows_to_json_safe(df)          # newest-first
    rows.reverse()                        # -> chronological (oldest-first)
    for r in rows:
        r["generated_sql"] = parse_json_list(r.get("generated_sql"))
    return flatten_exchanges_to_messages(rows, limit)


# Server-side truncation length for a conversation title (first user message).
CONV_TITLE_MAXLEN = 140


def list_conversations(user_id, cursor_token, limit):
    """One page of conversation summaries (names only) for ``user_id``.

    Returns ``{"conversations": [{session_id, title, last_at}], "next_cursor", "has_more"}``.
    Keyset pagination on (last_at, session_id); never returns message bodies.
    """
    page = validate_conversations_limit(limit)
    decoded = pagination.decode_cursor(cursor_token)
    cl = sql_value(decoded[0]) if decoded else None
    cs = sql_value(decoded[1]) if decoded else None
    table = full_table(CHAT_V5_LOGICAL)
    sql = build_conversation_list_query(
        table_ref=table, user_value_sql=sql_value(user_id),
        cursor_last_at_sql=cl, cursor_session_sql=cs,
        limit=page + 1,  # fetch one extra to compute has_more
        title_maxlen=CONV_TITLE_MAXLEN,
    )
    df = new_executor().query_to_df(sql)
    rows = rows_to_json_safe(df)
    has_more = len(rows) > page
    rows = rows[:page]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = pagination.encode_cursor(last["last_at"], last["session_id"])
    conversations = [
        {"session_id": r["session_id"], "title": r.get("title") or "", "last_at": r.get("last_at")}
        for r in rows
    ]
    return {"conversations": conversations, "next_cursor": next_cursor, "has_more": has_more}


# Absolute backstop on rows returned for one session (/conversation lazy load).
SESSION_MESSAGES_CAP = 500

# Keys of a generated_sql item exposed on the /conversation readback. The captured
# ``result`` rows are deliberately PROJECTED OUT so the thread payload stays light —
# only /evidence/meta returns the stored result (trust-layer contract §1).
_SQL_ITEM_PUBLIC_KEYS = ("sql", "success", "row_count", "sql_id", "step_index", "agent_key")


def _project_sql_items(items):
    """Project decoded generated_sql items onto their public keys (drops ``result``).

    Legacy ``{sql, success, row_count}`` items pass through unchanged; non-dict
    entries (corrupt cells) are kept as-is so a bad row never breaks a response.
    """
    projected = []
    for item in items:
        if isinstance(item, dict):
            projected.append({k: item[k] for k in _SQL_ITEM_PUBLIC_KEYS if k in item})
        else:
            projected.append(item)
    return projected


def messages_for_session(user_id, session_id, cap=SESSION_MESSAGES_CAP):
    """All exchanges of ONE session (chronological), user+session scoped, bounded.

    Returns JSON-safe rows in the stable ``_COLUMNS`` order (so the frontend reuses
    one ``rowsToMessages`` mapper): user_groups + generated_sql decoded to lists.
    The generated_sql items are projected onto their PUBLIC keys (no stored result).
    """
    table = full_table(CHAT_V5_LOGICAL)
    sql = build_session_messages_query(
        table_ref=table, columns=_COLUMNS,
        user_value_sql=sql_value(user_id), session_value_sql=sql_value(session_id), cap=cap,
    )
    df = new_executor().query_to_df(sql)
    rows = rows_to_json_safe(df)
    for r in rows:                       # decode JSON text columns to ready-to-use lists
        r["user_groups"] = parse_json_list(r.get("user_groups"))
        r["generated_sql"] = _project_sql_items(parse_json_list(r.get("generated_sql")))
        r["feedback_reasons"] = parse_json_list(r.get("feedback_reasons"))
    return rows
