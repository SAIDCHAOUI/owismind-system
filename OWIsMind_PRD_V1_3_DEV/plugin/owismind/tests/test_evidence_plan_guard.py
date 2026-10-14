# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_evidence_plan_guard.py
"""evidence.plan_guard: the authoritative re-run check on PostgreSQL's own plan.

The token gate can read SQL differently from PostgreSQL (parenthesized joins,
attribute-notation calls); the plan cannot. These tests feed representative
EXPLAIN (FORMAT JSON, VERBOSE) shapes and lock the fail-closed rules.
"""
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.evidence.plan_guard import (  # noqa: E402
    called_names,
    decode_plan,
    plan_violations,
    strict_relation_matcher,
)
from owismind.evidence.sql_parse import SAFE_FUNCTIONS  # noqa: E402

CANDIDATES = [{"name": "DRIVE_Revenues", "schema": "public", "table": "P_drive_revenues"},
              {"name": "Tickets", "schema": None, "table": "P_tickets"}]
REL = strict_relation_matcher(CANDIDATES)


def FN(name):
    return name in SAFE_FUNCTIONS


def scan(rel, schema="public", **extra):
    node = {"Node Type": "Seq Scan", "Relation Name": rel, "Schema": schema, "Alias": "r"}
    node.update(extra)
    return node


class PlanGuardTests(unittest.TestCase):
    def test_typical_aggregate_plan_passes(self):
        plan = {
            "Node Type": "Limit",
            "Output": ["owi_result.\"Solution\"", "owi_result.rev"],
            "Plans": [{
                "Node Type": "Sort",
                "Sort Key": ["(sum(r.\"Revenues\")) DESC"],
                "Plans": [{
                    "Node Type": "HashAggregate",
                    "Group Key": ["r.\"Solution\""],
                    "Output": [
                        "r.\"Solution\"",
                        "round((sum(CASE WHEN (r.\"Phase\" = 'ACTUALS'::text) THEN r.\"Revenues\" ELSE '0'::double precision END))::numeric, 2)",
                        "EXTRACT(year FROM r.\"Snapshot_date\")",
                        "rank() OVER (?)",
                    ],
                    "Plans": [scan("P_drive_revenues",
                                   Filter="(r.\"Year\" = ANY ('{2025,2026}'::bigint[]))")],
                }],
            }],
        }
        self.assertEqual(plan_violations(plan, REL, FN), [])

    def test_relation_outside_project_is_refused_at_any_depth(self):
        # e.g. FROM (secret CROSS JOIN t): the token gate misses 'secret', the plan does not.
        plan = {"Node Type": "Nested Loop", "Plans": [
            scan("P_drive_revenues"), {"Node Type": "Materialize", "Plans": [scan("secret")]},
        ]}
        self.assertEqual(plan_violations(plan, REL, FN), ["relation:public.secret"])

    def test_relation_match_is_exact(self):
        self.assertTrue(REL("public", "P_drive_revenues"))
        self.assertTrue(REL("public", "P_tickets"))  # unknown dataset schema = public
        self.assertFalse(REL("public", "p_drive_revenues"))  # other relation (case)
        self.assertFalse(REL("other", "P_drive_revenues"))  # same name, other schema

    def test_attribute_notation_call_is_caught_in_output(self):
        plan = scan("P_drive_revenues", Output=["my_udf(r.*)"])
        self.assertEqual(plan_violations(plan, REL, FN), ["function:my_udf"])

    def test_qualified_calls(self):
        ok = scan("P_drive_revenues", Output=["pg_catalog.lower(r.x)"])
        self.assertEqual(plan_violations(ok, REL, FN), [])
        bad = scan("P_drive_revenues", Output=["public.lower(r.x)"])
        self.assertEqual(plan_violations(bad, REL, FN), ["function:public.lower"])
        bad = scan("P_drive_revenues", Output=["pg_catalog.pg_read_file('x'::text)"])
        self.assertEqual(plan_violations(bad, REL, FN), ["function:pg_catalog.pg_read_file"])

    def test_function_scans_are_refused(self):
        plan = {"Node Type": "Function Scan", "Function Name": "generate_series"}
        self.assertEqual(plan_violations(plan, REL, FN), ["node:Function Scan"])

    def test_literals_never_count_as_calls(self):
        self.assertEqual(called_names("(r.x = 'evil(1)'::text)"), [])
        self.assertEqual(called_names('"substring"(r.x, 1, 3)'), ["substring"])

    def test_unreadable_plan_fails_closed(self):
        self.assertEqual(plan_violations(None, REL, FN), ["no_plan"])

    def test_decode_plan_shapes(self):
        doc = [{"Plan": {"Node Type": "Result"}}]
        self.assertEqual(decode_plan(json.dumps(doc)), {"Node Type": "Result"})
        self.assertEqual(decode_plan(doc), {"Node Type": "Result"})
        self.assertIsNone(decode_plan("not json"))
        self.assertIsNone(decode_plan(None))


if __name__ == "__main__":
    unittest.main()
