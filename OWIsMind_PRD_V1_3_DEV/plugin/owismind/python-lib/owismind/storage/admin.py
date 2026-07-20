"""Users/admin registry for the OWIsMind WebApp (direct SQL, no DSS Flow).

Every caller is recorded once (so admins can later promote them by their exact
user_id). The first ever user is bootstrapped as the admin. Admin checks gate the
/admin/* routes server-side. All values are escaped via ``sql_value``; identifiers
come from controlled constants via ``full_table``. Writes COMMIT explicitly.
"""

import json
import logging

from owismind.storage.migrations import USERS_V1_LOGICAL, ensure_users_table
from owismind.storage.serialization import parse_json_list, rows_to_json_safe
from owismind.storage.sql_config import (
    bool_literal,
    full_table,
    new_executor,
    nullable_value,
    sql_value,
)

logger = logging.getLogger(__name__)

_LIST_COLUMNS = "user_id, display_name, user_groups, is_admin, first_seen, last_seen"

# Bound the users listing so an admin request can never pull an unbounded result.
MAX_USERS_LISTED = 1000

# Transaction-scoped advisory-lock key that serialises the first-admin election across
# concurrent connections. Without it, two genuinely-concurrent first users could each
# evaluate "no admin exists yet" before either commits (PostgreSQL READ COMMITTED) and
# both become admin. record_user is infrequent (≈ once per session on POST /me) and its
# transaction is tiny, so serialising on this lock is negligible. The constant is
# app-specific ("OWIM") to avoid colliding with other advisory-lock users on the DB.
_BOOTSTRAP_LOCK_KEY = 0x4F57494D  # 1330926157


def record_user(identity):
    """Upsert the caller into the registry; bootstrap the first ever user as admin.

    Idempotent and cheap (one round-trip): an UPSERT refreshes groups/last_seen,
    then a guarded UPDATE grants admin only if no admin exists yet.

    display_name handling: the value passed in is a DEFAULT derived from the login
    (see identity.derive_display_name). On conflict we COALESCE - keep the stored
    name if there is one, otherwise fill it with the derived default. This backfills
    rows left NULL by the old (broken) code path. It is also forward-looking: if a
    "set my display name" feature is added later (none exists yet), the COALESCE
    keeps that stored custom name instead of resetting it on the user's next visit.
    """
    ensure_users_table()
    table = full_table(USERS_V1_LOGICAL)
    user_id = identity.get("user_id")
    groups_json = json.dumps(identity.get("groups") or [])

    # Alias the target row as ``u`` so ON CONFLICT can read the existing value.
    upsert_sql = """
    INSERT INTO {table} AS u (user_id, display_name, user_groups, last_seen)
    VALUES ({uid}, {disp}, {grp}, now())
    ON CONFLICT (user_id) DO UPDATE
       SET display_name = COALESCE(u.display_name, EXCLUDED.display_name),
           user_groups  = EXCLUDED.user_groups,
           last_seen    = now()
    """.format(
        table=table,
        uid=sql_value(user_id),
        disp=nullable_value(identity.get("display_name")),
        grp=sql_value(groups_json),
    )
    # Serialise the election across connections (released at COMMIT) so the NOT EXISTS
    # check below is race-free: a second concurrent first user waits, then sees the
    # first's committed admin row and does not also get elected.
    lock_sql = "SELECT pg_advisory_xact_lock({})".format(int(_BOOTSTRAP_LOCK_KEY))
    # Promote to admin only when there is currently no admin at all (first user).
    bootstrap_sql = """
    UPDATE {table} SET is_admin = true
    WHERE user_id = {uid}
      AND NOT EXISTS (SELECT 1 FROM {table} WHERE is_admin = true)
    """.format(table=table, uid=sql_value(user_id))

    new_executor().query_to_df(
        "SELECT 1 AS user_recorded",
        pre_queries=[lock_sql, upsert_sql, bootstrap_sql],
        post_queries=["COMMIT"],
    )


def is_admin(user_id):
    """True if the user is flagged admin in the registry."""
    ensure_users_table()
    table = full_table(USERS_V1_LOGICAL)
    sql = "SELECT is_admin FROM {table} WHERE user_id = {uid}".format(
        table=table, uid=sql_value(user_id)
    )
    rows = rows_to_json_safe(new_executor().query_to_df(sql))
    return bool(rows and rows[0].get("is_admin"))


def count_admins():
    """Number of admins (used to prevent removing the last one)."""
    ensure_users_table()
    table = full_table(USERS_V1_LOGICAL)
    sql = "SELECT COUNT(*) AS n FROM {table} WHERE is_admin = true".format(table=table)
    rows = rows_to_json_safe(new_executor().query_to_df(sql))
    return int(rows[0]["n"]) if rows else 0


def list_users():
    """All registered users (oldest first), groups decoded, is_admin as a bool."""
    ensure_users_table()
    table = full_table(USERS_V1_LOGICAL)
    sql = """
    SELECT {columns}
    FROM {table}
    ORDER BY first_seen, user_id
    LIMIT {limit}
    """.format(columns=_LIST_COLUMNS, table=table, limit=int(MAX_USERS_LISTED))
    rows = rows_to_json_safe(new_executor().query_to_df(sql))
    for row in rows:
        row["user_groups"] = parse_json_list(row.get("user_groups"))
        row["is_admin"] = bool(row.get("is_admin"))
    return rows


def set_admin(user_id, value):
    """Set or clear the admin flag for a user (DML UPDATE, COMMITted)."""
    ensure_users_table()
    table = full_table(USERS_V1_LOGICAL)
    sql = "UPDATE {table} SET is_admin = {val} WHERE user_id = {uid}".format(
        table=table, val=bool_literal(value), uid=sql_value(user_id)
    )
    new_executor().query_to_df(
        "SELECT 1 AS admin_updated",
        pre_queries=[sql],
        post_queries=["COMMIT"],
    )
    logger.info("set_admin - user_id=%s is_admin=%s", user_id, bool(value))
