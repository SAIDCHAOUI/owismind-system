# Plugin/owismind/tests/test_session_queries.py
"""Pure SQL builders for per-session reads must stay user+session scoped & bounded."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.storage.sql_builders import (  # noqa: E402
    build_conversation_list_query, build_session_messages_query,
)


class ConversationListQueryTests(unittest.TestCase):
    def _q(self, cl=None, cs=None, n=30, tlen=140):
        return build_conversation_list_query(
            table_ref='public."T"', user_value_sql="'u'",
            cursor_last_at_sql=cl, cursor_session_sql=cs, limit=n, title_maxlen=tlen,
        )

    def test_user_scoped_and_grouped(self):
        q = self._q()
        self.assertIn("WHERE user_id = 'u'", q)
        self.assertIn("GROUP BY session_id", q)
        self.assertIn("MAX(created_at) AS last_at", q)

    def test_title_is_first_user_text_truncated(self):
        q = self._q(tlen=120)
        self.assertIn("ARRAY_AGG(user_text ORDER BY created_at ASC", q)
        self.assertIn("120", q)  # LEFT(..., 120)

    def test_title_is_cleaned_to_one_line_before_truncating(self):
        # Newlines/tabs/repeated spaces collapse to single spaces and the value is
        # trimmed BEFORE LEFT(...), so a multi-line prompt becomes a tidy label.
        q = self._q(tlen=56)
        self.assertIn("regexp_replace(", q)
        self.assertIn("'[[:space:]]+'", q)
        self.assertIn("BTRIM(", q)
        # Cleanup must wrap the first-message extraction, inside the LEFT truncation.
        self.assertIn("LEFT(BTRIM(regexp_replace((ARRAY_AGG(user_text", q)

    def test_no_cursor_no_keyset_clause(self):
        q = self._q()
        self.assertNotIn("last_at <", q)

    def test_with_cursor_adds_keyset(self):
        q = self._q(cl="'2026-06-09T10:00:00'", cs="'sid'")
        self.assertIn("last_at < '2026-06-09T10:00:00'", q)
        self.assertIn("session_id < 'sid'", q)

    def test_order_and_limit(self):
        q = self._q(n=31)
        self.assertIn("ORDER BY last_at DESC, session_id DESC", q)
        self.assertIn("LIMIT 31", q)

    def test_keyset_direction_matches_desc_order(self):
        q = self._q(cl="'2026-06-09T10:00:00'", cs="'sid'")
        # strictly-less keyset paired with DESC ordering (no skipped/dup rows)
        self.assertIn("last_at < '2026-06-09T10:00:00'", q)
        self.assertIn("session_id < 'sid'", q)
        self.assertIn("ORDER BY last_at DESC, session_id DESC", q)
        self.assertIn(" OR ", q)  # the (a<x) OR (a=x AND b<y) keyset shape


class SessionMessagesQueryTests(unittest.TestCase):
    def _q(self, cap=500):
        return build_session_messages_query(
            table_ref='public."T"', columns="exchange_id, user_text, assistant_text",
            user_value_sql="'u'", session_value_sql="'s'", cap=cap,
        )

    def test_user_and_session_scoped(self):
        q = self._q()
        self.assertIn("user_id = 'u'", q)
        self.assertIn("session_id = 's'", q)

    def test_chronological_and_bounded(self):
        q = self._q(500)
        self.assertIn("ORDER BY created_at ASC", q)
        self.assertIn("LIMIT 500", q)

if __name__ == "__main__":
    unittest.main()
