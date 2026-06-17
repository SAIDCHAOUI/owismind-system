# Plugin/owismind/tests/test_evidence_query_builders.py
"""evidence.query_builders: pure SQL text builders - owner-scoped, bounded."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.query_builders import (  # noqa: E402
    build_distinct_query,
    build_exchange_sql_query,
    build_rows_query,
    render_predicate,
)

# Stub quoters: assertions stay readable without dataiku.
def qi(name):
    return '"' + name + '"'
def qv(value):
    return "V(" + repr(value) + ")"


class ExchangeQueryTests(unittest.TestCase):
    def test_owner_scoped_and_bounded(self):
        q = build_exchange_sql_query('public."CHAT"', "'u'", "'ex'")
        self.assertIn("WHERE exchange_id = 'ex' AND user_id = 'u'", q)
        self.assertIn("LIMIT 1", q)
        self.assertIn("generated_sql", q)


class RowsQueryTests(unittest.TestCase):
    def test_bounded_page_with_conditions(self):
        q = build_rows_query(
            table_ref='public."REV"', column_idents=['"a"', '"b"'],
            conditions=['"a" = V(1)', "(x OR y)"],
            order_ident='"a"', order_dir="desc", limit=51, offset=100,
        )
        self.assertIn('SELECT "a", "b"', q)
        # Each condition is defensively parenthesized: a top-level OR inside one
        # fragment can never broaden the AND-conjunction's scope.
        self.assertIn('WHERE ("a" = V(1)) AND ((x OR y))', q)
        self.assertIn('ORDER BY "a" DESC', q)
        self.assertIn("LIMIT 51 OFFSET 100", q)

    def test_no_conditions_no_where(self):
        q = build_rows_query('t', ['"a"'], [], '"a"', "asc", 51, 0)
        self.assertNotIn("WHERE", q)
        self.assertIn('ORDER BY "a" ASC', q)

    def test_direction_is_normalized(self):
        q = build_rows_query('t', ['"a"'], [], '"a"', "junk; DROP", 51, 0)
        self.assertIn("ASC", q)
        self.assertNotIn("DROP", q)


class DistinctQueryTests(unittest.TestCase):
    def test_bounded_distinct(self):
        q = build_distinct_query('public."REV"', '"sol"', 100)
        # DISTINCT + LIMIT run in a subquery; only the bounded result is sorted.
        self.assertIn('SELECT value FROM (', q)
        self.assertIn('SELECT DISTINCT "sol" AS value', q)
        self.assertIn('WHERE "sol" IS NOT NULL', q)
        self.assertIn("LIMIT 100", q)
        self.assertIn("ORDER BY value", q)

    def test_conditions_scope_the_picker(self):
        # The agent's locked predicates scope the picker to its evidence.
        q = build_distinct_query('public."REV"', '"sol"', 100, conditions=['"a" = V(1)'])
        self.assertIn('WHERE "sol" IS NOT NULL AND ("a" = V(1))', q)


class RenderPredicateTests(unittest.TestCase):
    def _r(self, pred):
        return render_predicate(pred, qi, qv)

    def test_all_ops(self):
        self.assertEqual(self._r({"column": "a", "op": "=", "values": [1]}), '"a" = V(1)')
        self.assertEqual(self._r({"column": "a", "op": "!=", "values": ["x"]}), '"a" != V(\'x\')')
        self.assertEqual(self._r({"column": "a", "op": "<", "values": [1]}), '"a" < V(1)')
        self.assertEqual(self._r({"column": "a", "op": "<=", "values": [1]}), '"a" <= V(1)')
        self.assertEqual(self._r({"column": "a", "op": ">", "values": [1]}), '"a" > V(1)')
        self.assertEqual(self._r({"column": "a", "op": ">=", "values": [1]}), '"a" >= V(1)')
        self.assertEqual(self._r({"column": "a", "op": "IN", "values": [1, 2]}), '"a" IN (V(1), V(2))')
        self.assertEqual(self._r({"column": "a", "op": "NOT IN", "values": [1]}), '"a" NOT IN (V(1))')
        self.assertEqual(self._r({"column": "a", "op": "BETWEEN", "values": [1, 9]}), '"a" BETWEEN V(1) AND V(9)')
        self.assertEqual(self._r({"column": "a", "op": "LIKE", "values": ["x%"]}), '"a" LIKE V(\'x%\')')
        self.assertEqual(self._r({"column": "a", "op": "ILIKE", "values": ["x%"]}), '"a" ILIKE V(\'x%\')')
        self.assertEqual(self._r({"column": "a", "op": "IS NULL", "values": []}), '"a" IS NULL')
        self.assertEqual(self._r({"column": "a", "op": "IS NOT NULL", "values": []}), '"a" IS NOT NULL')

    def test_unknown_op_raises(self):
        with self.assertRaises(ValueError):
            self._r({"column": "a", "op": "EXOTIC", "values": [1]})


if __name__ == "__main__":
    unittest.main()
