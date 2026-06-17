# Plugin/owismind/tests/test_evidence_sql_parse.py
"""evidence.sql_parse: pure tokenizer / parse_select / validate_fragment (no dataiku).

parse_select is BEST-EFFORT (user decision): JOINs, GROUP BY, sub-queries, CTEs
and set operations all parse - only non-analysable text (not SQL, comments,
multiple statements) degrades. These tests lock that contract, including the
demo query (self-join + aggregation) that used to degrade as 'join_unsupported'.
"""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.sql_parse import (  # noqa: E402
    parse_select,
    predicates_for_table,
    tokenize,
    validate_fragment,
)


class TokenizeTests(unittest.TestCase):
    def test_basic_tokens_with_offsets(self):
        toks, err = tokenize("SELECT a FROM t WHERE x = 'v''al'")
        self.assertIsNone(err)
        kinds = [t.kind for t in toks]
        self.assertEqual(kinds, ["word", "word", "word", "word", "word", "word", "op", "string"])
        self.assertEqual(toks[-1].text, "'v''al'")

    def test_comments_rejected(self):
        self.assertEqual(tokenize("SELECT 1 -- x")[1], "comment_unsupported")
        self.assertEqual(tokenize("SELECT 1 /* x */")[1], "comment_unsupported")

    def test_unknown_chars_rejected(self):
        self.assertEqual(tokenize("SELECT $$x$$")[1], "tokenize_failed")
        self.assertEqual(tokenize("WHERE a = b\\n")[1], "tokenize_failed")

    def test_unterminated_string_rejected(self):
        self.assertEqual(tokenize("WHERE x = 'oops")[1], "tokenize_failed")

    def test_casts_and_arithmetic_tokenize(self):
        # ':' '+' '-' '/' '%' are tokens, so a cast only degrades ITS conjunct (-> advanced),
        # never the whole statement.
        toks, err = tokenize("d >= '2025-01-01'::date + 1")
        self.assertIsNone(err)


class ValidateFragmentTests(unittest.TestCase):
    def test_accepts_plain_conditions(self):
        self.assertTrue(validate_fragment("(a = 1 OR b = 2)"))
        self.assertTrue(validate_fragment("date_trunc('month', d) = '2025-01-01'"))

    def test_rejects_dangerous_content(self):
        for frag in (
            "a = 1; DROP TABLE x",          # multi-statement
            "a IN (SELECT x FROM t)",        # subquery
            "a = 1 UNION ALL b",             # set op
            "pg_sleep(10) IS NULL",          # pg_* functions (DoS vector)
            "a = 1 -- c",                    # comment
            "a = (1",                        # unbalanced parens
        ):
            self.assertFalse(validate_fragment(frag), frag)

    def test_word_boundary_compounds_pass(self):
        # Banned words match on whole tokens: 'do_thing' is ONE word, not 'do'.
        self.assertTrue(validate_fragment("do_thing(a)"))

    def test_quoted_identifiers_checked_like_words(self):
        # PostgreSQL accepts a QUOTED identifier as a function name, so the
        # banned-word / pg_ gate must apply to qident tokens too.
        self.assertFalse(validate_fragment('"pg_sleep"(10) IS NULL'))
        self.assertFalse(validate_fragment('"do"(1) = 1'))
        # A legitimate quoted column still passes.
        self.assertTrue(validate_fragment('"Solution Name" = \'OBS\''))

    def test_banned_words_masked_inside_strings(self):
        # 'select' INSIDE a string literal is data, not a keyword.
        self.assertTrue(validate_fragment("status = 'selected'"))
        self.assertTrue(validate_fragment("note = 'please do it'"))

    def test_bounds(self):
        self.assertFalse(validate_fragment(""))
        self.assertFalse(validate_fragment(None))
        self.assertFalse(validate_fragment("a = 1" + " AND b = 2" * 500))  # > 2000 chars


class ParseStructureTests(unittest.TestCase):
    def test_simple_select_no_where(self):
        p = parse_select('SELECT * FROM "public"."ANALYTICS_revenue"')
        self.assertTrue(p["ok"])
        self.assertEqual(p["schema"], "public")
        self.assertEqual(p["table"], "ANALYTICS_revenue")
        self.assertEqual(p["tables"], [{"schema": "public", "table": "ANALYTICS_revenue"}])
        self.assertEqual(p["predicates"], [])
        self.assertIsNone(p["advanced"])

    def test_unquoted_and_aliased_table(self):
        p = parse_select("SELECT a FROM revenue r WHERE r.x = 1")
        self.assertTrue(p["ok"])
        self.assertIsNone(p["schema"])
        self.assertEqual(p["table"], "revenue")
        self.assertEqual(p["predicates"][0]["binding"], "revenue")

    def test_trailing_semicolon_tolerated(self):
        self.assertTrue(parse_select("SELECT a FROM t;")["ok"])

    def test_rejections(self):
        # Only non-analysable text degrades now (best-effort contract).
        cases = {
            "SELECT a FROM t; DROP TABLE t": "multi_statement",
            "UPDATE t SET a = 1": "not_select",
            "SELECT a FROM t WHERE (a = 1": "unbalanced_parens",
            "": "invalid_sql",
        }
        for sql, reason in cases.items():
            p = parse_select(sql)
            self.assertFalse(p["ok"], sql)
            self.assertEqual(p["reason"], reason, sql)

    def test_sql_too_long(self):
        self.assertEqual(parse_select("SELECT a FROM t WHERE " + "x" * 20001)["reason"], "sql_too_long")

    def test_select_without_from_parses_with_no_tables(self):
        p = parse_select("SELECT 1")
        self.assertTrue(p["ok"])
        self.assertEqual(p["tables"], [])
        self.assertIsNone(p["table"])

    def test_group_order_limit_ignored(self):
        p = parse_select("SELECT s, SUM(r) FROM t GROUP BY s ORDER BY 2 DESC LIMIT 10")
        self.assertTrue(p["ok"])  # aggregates/clauses are ignored: Evidence shows the SCOPE
        self.assertEqual(p["table"], "t")


class ParseWhereTests(unittest.TestCase):
    def _preds(self, sql):
        p = parse_select(sql)
        self.assertTrue(p["ok"], p)
        return p

    def test_full_simple_where(self):
        p = self._preds(
            "SELECT * FROM rev WHERE solution IN ('OBS', 'OCD') "
            "AND period >= '2025-01' AND customer = 'Algérie Télécom'"
        )
        self.assertIsNone(p["advanced"])
        self.assertEqual(len(p["predicates"]), 3)
        p0, p1, p2 = p["predicates"]
        self.assertEqual((p0["column"], p0["op"], p0["values"]), ("solution", "IN", ["OBS", "OCD"]))
        self.assertTrue(p0["editable"])
        self.assertEqual((p1["column"], p1["op"], p1["values"]), ("period", ">=", ["2025-01"]))
        self.assertFalse(p1["editable"])
        # Value with a space survives intact (the maquette regex broke on this).
        self.assertEqual(p2["values"], ["Algérie Télécom"])
        self.assertEqual([x["id"] for x in p["predicates"]], [0, 1, 2])  # conjunct index

    def test_operator_coverage(self):
        p = self._preds(
            "SELECT * FROM t WHERE a != 5 AND b <> 'x' AND c BETWEEN 1 AND 10 "
            "AND d LIKE 'ab%' AND e IS NULL AND f IS NOT NULL AND g NOT IN (1, 2)"
        )
        ops = [x["op"] for x in p["predicates"]]
        self.assertEqual(ops, ["!=", "!=", "BETWEEN", "LIKE", "IS NULL", "IS NOT NULL", "NOT IN"])
        self.assertEqual(p["predicates"][2]["values"], [1, 10])
        self.assertTrue(all(not x["editable"] for x in p["predicates"]))

    def test_literal_types(self):
        p = self._preds("SELECT * FROM t WHERE n = 3 AND f = 1.5 AND b = TRUE AND s = 'it''s'")
        vals = [x["values"][0] for x in p["predicates"]]
        self.assertEqual(vals, [3, 1.5, True, "it's"])

    def test_top_level_or_becomes_one_advanced_fragment(self):
        p = self._preds("SELECT * FROM t WHERE a = 1 OR b = 2")
        self.assertEqual(p["predicates"], [])
        self.assertEqual(p["advanced"], "a = 1 OR b = 2")

    def test_mixed_simple_and_advanced(self):
        p = self._preds("SELECT * FROM t WHERE a = 1 AND (b = 2 OR c = 3) AND date_trunc('m', d) = '2025-01-01'")
        self.assertEqual(len(p["predicates"]), 1)
        self.assertEqual(p["predicates"][0]["column"], "a")
        self.assertEqual(p["advanced"], "(b = 2 OR c = 3) AND date_trunc('m', d) = '2025-01-01'")

    def test_between_and_not_split(self):
        p = self._preds("SELECT * FROM t WHERE c BETWEEN 1 AND 10 AND a = 2")
        self.assertEqual(len(p["predicates"]), 2)

    def test_qualified_and_quoted_columns(self):
        p = self._preds('SELECT * FROM rev r WHERE r."Solution Name" = \'OBS\'')
        self.assertEqual(p["predicates"][0]["column"], "Solution Name")

    def test_parenthesized_simple_predicate(self):
        p = self._preds("SELECT * FROM t WHERE (a = 1) AND b = 2")
        self.assertEqual(len(p["predicates"]), 2)

    def test_cast_degrades_only_its_conjunct(self):
        p = self._preds("SELECT * FROM t WHERE d >= '2025-01-01'::date AND a = 1")
        self.assertEqual(len(p["predicates"]), 1)
        self.assertEqual(p["advanced"], "d >= '2025-01-01'::date")

    def test_alias_qualifier_stripped_from_fragment(self):
        # The rebuilt query targets the bare table - a kept fragment must not
        # reference the agent's FROM alias.
        p = self._preds('SELECT * FROM t r WHERE r."amount" + r.fee > 100 AND r.phase = \'X\'')
        self.assertEqual(p["advanced"], '"amount" + fee > 100')
        self.assertEqual(p["predicates"][0]["column"], "phase")

    def test_deeply_nested_parens_still_simple(self):
        # _strip_parens removes ALL wrapping pairs in one pass.
        p = self._preds("SELECT * FROM t WHERE ((((a = 1))))")
        self.assertEqual(len(p["predicates"]), 1)
        self.assertEqual((p["predicates"][0]["column"], p["predicates"][0]["op"],
                          p["predicates"][0]["values"]), ("a", "=", [1]))
        self.assertIsNone(p["advanced"])

    def test_wrapped_and_group_is_one_advanced_conjunct(self):
        # Locked pre-refactor behavior: the AND sits at depth 1, so the WHERE is
        # ONE conjunct; stripping its outer pair leaves '(a = 1) AND b = 2' which
        # is not a simple predicate -> the ORIGINAL slice becomes the fragment.
        p = self._preds("SELECT * FROM t WHERE ((a = 1) AND b = 2)")
        self.assertEqual(p["predicates"], [])
        self.assertEqual(p["advanced"], "((a = 1) AND b = 2)")


class BestEffortShapesTests(unittest.TestCase):
    """JOINs / sub-queries / CTEs / set ops parse and expose mappable filters."""

    DEMO_SQL = (
        'SELECT r."diamond_id",\n'
        '       MAX(c."Account_name") AS Account_name,\n'
        '       SUM(r."amount_eur") AS total_revenue\n'
        'FROM "OWISMIND_DEV_drive_revenues" r\n'
        'JOIN "OWISMIND_DEV_drive_revenues" c ON r."diamond_id" = c."diamond_id"\n'
        "WHERE r.\"Product\" = 'Roaming Sponsor'\n"
        "  AND r.\"Phase\" = 'ACTUALS'\n"
        'GROUP BY r."diamond_id"\n'
        "ORDER BY total_revenue DESC\n"
        "LIMIT 10;"
    )

    def test_demo_self_join_yields_both_where_chips(self):
        p = parse_select(self.DEMO_SQL)
        self.assertTrue(p["ok"], p)
        self.assertEqual(p["tables"], [{"schema": None, "table": "OWISMIND_DEV_drive_revenues"}])
        kept = predicates_for_table(p["predicates"], "OWISMIND_DEV_drive_revenues")
        self.assertEqual(
            [(x["column"], x["op"], x["values"]) for x in kept],
            [("Product", "=", ["Roaming Sponsor"]), ("Phase", "=", ["ACTUALS"])],
        )
        self.assertTrue(all(x["editable"] for x in kept))
        self.assertIsNone(p["advanced"])  # join plumbing never becomes a fragment

    def test_join_of_two_tables_lists_both_and_binds_predicates(self):
        p = parse_select(
            "SELECT * FROM rev r JOIN customers c ON r.id = c.id "
            "WHERE r.phase = 'ACTUALS' AND c.country = 'FR' AND product = 'X'"
        )
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["rev", "customers"])
        kept_rev = predicates_for_table(p["predicates"], "rev")
        # r.phase binds to rev; c.country binds to customers (dropped);
        # the unqualified product is kept best-effort (live schema decides).
        self.assertEqual([x["column"] for x in kept_rev], ["phase", "product"])
        kept_cust = predicates_for_table(p["predicates"], "customers")
        self.assertEqual([x["column"] for x in kept_cust], ["country", "product"])

    def test_comma_join_collects_both_tables(self):
        p = parse_select("SELECT * FROM t1 a, t2 b WHERE a.x = 1 AND b.y = 2")
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["t1", "t2"])
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "t1")], ["x"])

    def test_left_join_words_are_not_aliases(self):
        p = parse_select("SELECT * FROM t1 LEFT OUTER JOIN t2 ON t1.id = t2.id WHERE t1.a = 1")
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["t1", "t2"])

    def test_in_subquery_conjunct_dropped_other_chips_kept(self):
        p = parse_select(
            "SELECT * FROM rev WHERE phase = 'ACTUALS' AND id IN (SELECT id FROM other WHERE z = 1)"
        )
        self.assertTrue(p["ok"])
        kept = predicates_for_table(p["predicates"], "rev")
        self.assertEqual([x["column"] for x in kept], ["phase"])
        # Multi-scope statement -> no advanced fragment (it could not re-execute).
        self.assertIsNone(p["advanced"])
        # The sub-query's own predicate binds to ITS table only.
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "other")], ["z"])

    def test_derived_table_keeps_inner_filters(self):
        p = parse_select(
            "SELECT * FROM (SELECT * FROM rev WHERE phase = 'ACTUALS') s LIMIT 10"
        )
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["rev"])
        kept = predicates_for_table(p["predicates"], "rev")
        self.assertEqual([(x["column"], x["values"]) for x in kept], [("phase", ["ACTUALS"])])

    def test_cte_keeps_inner_filters(self):
        p = parse_select(
            "WITH base AS (SELECT * FROM rev WHERE product = 'Roaming Sponsor') "
            "SELECT diamond_id, SUM(amount) FROM base GROUP BY diamond_id"
        )
        self.assertTrue(p["ok"])
        # Outer-scope tables rank first (the outer FROM should win the dataset
        # match); 'base' is a CTE name and will match no dataset, so the service
        # falls through to 'rev'.
        self.assertEqual([t["table"] for t in p["tables"]], ["base", "rev"])
        kept = predicates_for_table(p["predicates"], "rev")
        self.assertEqual([x["column"] for x in kept], ["product"])

    def test_set_op_analyses_first_arm(self):
        p = parse_select("SELECT a FROM t1 WHERE x = 1 UNION SELECT b FROM t2")
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["t1"])
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "t1")], ["x"])

    def test_extract_from_is_not_a_table(self):
        p = parse_select("SELECT EXTRACT(MONTH FROM created_at) FROM rev WHERE a = 1")
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["rev"])

    def test_unknown_qualifier_never_matches(self):
        p = parse_select("SELECT * FROM rev r WHERE z.col = 1 AND r.a = 2")
        kept = predicates_for_table(p["predicates"], "rev")
        self.assertEqual([x["column"] for x in kept], ["a"])

    def test_deeply_nested_subqueries_never_raise(self):
        # ~1100 nesting levels fit in MAX_SQL_CHARS but would blow the stack
        # without MAX_SCOPE_DEPTH - the cap keeps the "never raises" contract.
        sql = "SELECT * FROM " + "(SELECT * FROM " * 1100 + "t" + ")" * 1100
        p = parse_select(sql)
        self.assertTrue(p["ok"])  # deeper groups are opaque, not an error

    def test_schema_qualified_fragment_strips_whole_chain(self):
        # public.t.col must lose the WHOLE "public.t." qualifier (a dangling
        # "public." would parse as a correlation name and fail at execution).
        p = parse_select(
            "SELECT * FROM public.t WHERE public.t.col LIKE 'x%' OR public.t.other = 1"
        )
        self.assertTrue(p["ok"])
        self.assertEqual(p["advanced"], "col LIKE 'x%' OR other = 1")

    def test_is_distinct_from_is_not_a_table_site(self):
        p = parse_select(
            "SELECT * FROM orders WHERE status IS DISTINCT FROM closed_status AND region = 'EU'"
        )
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["orders"])
        kept = predicates_for_table(p["predicates"], "orders")
        self.assertEqual([x["column"] for x in kept], ["region"])
        # Single-table statement: the operator conjunct survives as the fragment.
        self.assertEqual(p["advanced"], "status IS DISTINCT FROM closed_status")
        self.assertTrue(validate_fragment(p["advanced"]))

    def test_nested_set_op_analyses_first_arm_only(self):
        p = parse_select(
            "SELECT * FROM rev WHERE id IN "
            "(SELECT id FROM a WHERE x = 1 UNION SELECT id FROM b WHERE y = 2)"
        )
        self.assertTrue(p["ok"])
        self.assertEqual([t["table"] for t in p["tables"]], ["rev", "a"])
        # arm-2's filter is never misattributed to arm-1's table.
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "a")], ["x"])
        self.assertEqual(predicates_for_table(p["predicates"], "b"), [])

    def test_comma_join_after_derived_table(self):
        p = parse_select(
            "SELECT * FROM (SELECT * FROM rev WHERE p = 1) s, orders WHERE orders.region = 'EU'"
        )
        self.assertTrue(p["ok"])
        self.assertEqual(sorted(t["table"] for t in p["tables"]), ["orders", "rev"])
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "orders")],
                         ["region"])
        self.assertEqual([x["column"] for x in predicates_for_table(p["predicates"], "rev")],
                         ["p"])

    def test_only_and_lateral_are_not_table_names(self):
        p = parse_select("SELECT * FROM ONLY rev WHERE a = 1")
        self.assertEqual([t["table"] for t in p["tables"]], ["rev"])
        p = parse_select(
            "SELECT * FROM rev JOIN LATERAL (SELECT 1 AS one) l ON TRUE WHERE a = 1"
        )
        self.assertEqual([t["table"] for t in p["tables"]], ["rev"])

    def test_predicate_ids_stay_deterministic_across_scopes(self):
        sql = (
            "SELECT * FROM rev WHERE a = 1 AND id IN (SELECT id FROM other WHERE z = 9) AND b = 2"
        )
        p1, p2 = parse_select(sql), parse_select(sql)
        self.assertEqual(
            [(x["id"], x["column"]) for x in p1["predicates"]],
            [(x["id"], x["column"]) for x in p2["predicates"]],
        )
        ids = [x["id"] for x in p1["predicates"]]
        self.assertEqual(len(ids), len(set(ids)))  # unique across scopes


if __name__ == "__main__":
    unittest.main()
