# Plugin/owismind/tests/test_ancestor_chain.py
"""build_ancestor_chain_query: user-scoped, depth+LIMIT bounded recursive walk up parents."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.storage.sql_builders import build_ancestor_chain_query  # noqa: E402

class AncestorChainQueryTests(unittest.TestCase):
    def _q(self, depth=200, cap=13):
        return build_ancestor_chain_query(
            table_ref='public."T"', columns="user_text, assistant_text, generated_sql, created_at, exchange_id",
            user_value_sql="'u'", start_exchange_sql="'ex'", max_depth=depth, cap=cap,
        )
    def test_recursive_and_user_scoped_both_members(self):
        q = self._q()
        self.assertIn("RECURSIVE", q)
        self.assertEqual(q.count("user_id = 'u'"), 2)  # anchor + recursive member
        self.assertIn("exchange_id = 'ex'", q)         # anchor starts at the parent
        self.assertIn("t.exchange_id = chain.parent_exchange_id", q)  # walk up
    def test_depth_and_limit_bounded(self):
        q = self._q(depth=200, cap=13)
        self.assertIn("chain._depth < 200", q)
        self.assertIn("LIMIT 13", q)
    def test_newest_first(self):
        self.assertIn("ORDER BY created_at DESC", self._q())
    def test_ints_coerced(self):
        q = self._q(depth="200", cap="13")
        self.assertIn("chain._depth < 200", q); self.assertIn("LIMIT 13", q)

if __name__ == "__main__":
    unittest.main()
