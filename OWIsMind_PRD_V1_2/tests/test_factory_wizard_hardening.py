"""Wizard hardening tests (2026-07-12 night review wave 2).

Covers two reviewed improvements:

1. build_draft_prompt now bakes in the TRAP SHAPES learned from the live domains
   (COUNT DISTINCT, minutes / AVG, explicit time dimension, display column for
   opaque ids, one-physical-table) and requires clarifying_questions plus
   profile_overrides, WITHOUT hardcoding any live business value.
2. validate_golden_queries: a pure offline gate that rejects non read-only SQL,
   multi-statement chaining and invented column names, and the pipeline wiring
   that strips flagged golden queries before apply_config.

DSS-free: everything runs on fakes.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import pipeline, wizard  # noqa: E402
from owismind_factory.fctx import FactoryContext, MANUAL  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def make_spec(**overrides):
    kwargs = dict(domain="satisfaction", base_dataset="CX_Surveys",
                  label_fr="Satisfaction", label_en="Satisfaction")
    kwargs.update(overrides)
    return DomainSpec(**kwargs)


def statuses(ctx):
    return {a["step"]: a["status"] for a in ctx.actions}


class TestPromptHardening(unittest.TestCase):
    def test_prompt_requires_clarifying_questions_and_overrides(self):
        prompt = wizard.build_draft_prompt("DIGEST", "CX_Surveys", "satisfaction")
        self.assertIn("clarifying_questions", prompt)
        self.assertIn("profile_overrides", prompt)
        self.assertIn("display_column", prompt)

    def test_prompt_mentions_trap_shapes(self):
        prompt = wizard.build_draft_prompt("DIGEST", "CX_Surveys", "satisfaction")
        self.assertIn("TRAP SHAPES", prompt)
        self.assertIn("COUNT(DISTINCT", prompt)
        self.assertIn("AVG", prompt)
        self.assertIn("time dimension", prompt)
        self.assertIn("JOIN", prompt)

    def test_prompt_labels_traps_as_shapes_not_values(self):
        # The traps must be described as shapes to check, not copied live values.
        prompt = wizard.build_draft_prompt("DIGEST", "CX_Surveys", "satisfaction")
        self.assertIn("never values to copy", prompt)
        # No live-domain business value leaks into the generic prompt.
        self.assertNotIn("creationDate", prompt)
        self.assertNotIn("Account_name", prompt)

    def test_prompt_has_no_dashes(self):
        prompt = wizard.build_draft_prompt("DIGEST", "CX_Surveys", "satisfaction")
        self.assertNotIn(chr(0x2014), prompt)  # em dash
        self.assertNotIn(chr(0x2013), prompt)  # en dash


class TestValidateGoldenQueries(unittest.TestCase):
    KNOWN = ["Account_name", "amount", "Phase", "Customer_id"]

    def test_happy_path_all_ok(self):
        config = {"golden_queries": [
            {"question": "top accounts by revenue",
             "sql": "SELECT Account_name, SUM(amount) AS total FROM __TABLE__ "
                    "WHERE Phase = 'ACTUALS' GROUP BY Account_name"},
            {"question": "distinct customers",
             "sql": "SELECT COUNT(DISTINCT Customer_id) FROM __TABLE__"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertEqual(out["problems"], [])
        self.assertEqual(len(out["ok"]), 2)

    def test_table_placeholder_and_alias_accepted(self):
        config = {"golden_queries": [
            {"question": "aliased", "sql": "SELECT t.amount FROM __TABLE__ t"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertEqual(out["problems"], [])

    def test_invented_column_flagged(self):
        config = {"golden_queries": [
            {"question": "bad", "sql": "SELECT made_up_col FROM __TABLE__"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertEqual(len(out["problems"]), 1)
        joined = " ".join(out["problems"][0]["issues"])
        self.assertIn("made_up_col", joined)

    def test_write_statement_rejected(self):
        for sql in ("DELETE FROM __TABLE__",
                    "UPDATE __TABLE__ SET amount = 0",
                    "INSERT INTO __TABLE__ VALUES (1)",
                    "DROP TABLE __TABLE__",
                    "TRUNCATE __TABLE__"):
            config = {"golden_queries": [{"question": "q", "sql": sql}]}
            out = wizard.validate_golden_queries(config, self.KNOWN)
            self.assertEqual(len(out["problems"]), 1, sql)

    def test_multi_statement_rejected(self):
        config = {"golden_queries": [
            {"question": "q", "sql": "SELECT amount FROM __TABLE__; DROP TABLE x"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        issues = " ".join(out["problems"][0]["issues"])
        self.assertIn("multiple statements", issues)

    def test_literal_value_does_not_trip_forbidden_keyword(self):
        # 'DELETE' inside a string literal must NOT be read as a DELETE statement.
        config = {"golden_queries": [
            {"question": "status filter",
             "sql": "SELECT Account_name FROM __TABLE__ WHERE Phase = 'DELETE ME'"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertEqual(out["problems"], [])

    def test_empty_question_flagged(self):
        config = {"golden_queries": [
            {"question": "", "sql": "SELECT amount FROM __TABLE__"},
        ]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertIn("empty question", out["problems"][0]["issues"])

    def test_query_without_sql_is_ok(self):
        config = {"golden_queries": [{"question": "todo, no sql yet"}]}
        out = wizard.validate_golden_queries(config, self.KNOWN)
        self.assertEqual(out["problems"], [])
        self.assertEqual(len(out["ok"]), 1)

    def test_no_known_columns_skips_column_check(self):
        # Read-only is still enforced, but invented columns are not flagged.
        config = {"golden_queries": [
            {"question": "q", "sql": "SELECT whatever FROM __TABLE__"},
        ]}
        out = wizard.validate_golden_queries(config, [])
        self.assertEqual(out["problems"], [])


class _StripProject(object):
    """Minimal project: get_physical_table degrades to None, no listing needed."""
    project_key = "FAKE"

    def get_dataset(self, name):
        raise RuntimeError("no dataset in this fake")


class TestPipelineStripping(unittest.TestCase):
    def _settings(self):
        return {"sql_connection": "SQL_owi", "code_env_311": "",
                "template_zone_recipes": {}}

    def _wizard_config(self):
        return {
            "entity_description": "surveys",
            "attributes": [{"column": "Account_name"}, {"column": "amount"},
                           {"column": "Phase"}],
            "golden_queries": [
                {"question": "good",
                 "sql": "SELECT Account_name, SUM(amount) FROM __TABLE__ "
                        "WHERE Phase = 'ACTUALS' GROUP BY Account_name"},
                {"question": "invented", "sql": "SELECT made_up_col FROM __TABLE__"},
                {"question": "write", "sql": "DELETE FROM __TABLE__"},
            ],
        }

    def test_problem_queries_stripped_and_reported(self):
        captured = {}
        original = pipeline.wizard.substitute_golden_tables

        def recorder(config, physical):
            captured["config"] = config
            return [], []

        pipeline.wizard.substitute_golden_tables = recorder
        try:
            ctx = FactoryContext(project=_StripProject(), dry_run=False)
            pipeline.create_domain(ctx, make_spec(),
                                   wizard_config=self._wizard_config(),
                                   settings=self._settings(),
                                   steps=["semantic_config"])
        finally:
            pipeline.wizard.substitute_golden_tables = original

        # Only the valid query reaches substitution / apply_config.
        passed = captured["config"]["golden_queries"]
        self.assertEqual([g["question"] for g in passed], ["good"])

        # One manual action lists both stripped queries and their issues.
        st = statuses(ctx)
        self.assertEqual(st.get("semantic_config_validation"), MANUAL)
        detail = next(a["detail"] for a in ctx.actions
                      if a["step"] == "semantic_config_validation")
        self.assertIn("made_up_col", detail)
        self.assertIn("DELETE", detail)

    def test_no_attributes_still_runs_read_only_check(self):
        # Without attribute columns only the COLUMN check degrades (manual note);
        # the read-only check ALWAYS runs, so a destructive query is stripped even
        # with an empty schema, and a clean SELECT passes through.
        config = {"entity_description": "d", "attributes": [], "golden_queries": [
            {"question": "q", "sql": "SELECT whatever FROM __TABLE__"},
            {"question": "evil", "sql": "DELETE FROM __TABLE__"}]}
        ctx = FactoryContext(project=_StripProject(), dry_run=False)
        pipeline.create_domain(ctx, make_spec(), wizard_config=config,
                               settings=self._settings(), steps=["semantic_config"])
        st = statuses(ctx)
        detail_cols = next(a["detail"] for a in ctx.actions
                           if a["step"] == "semantic_config_validation_columns")
        self.assertIn("COLUMN check skipped", detail_cols)
        self.assertEqual(st.get("semantic_config_validation"), MANUAL)
        detail_strip = next(a["detail"] for a in ctx.actions
                            if a["step"] == "semantic_config_validation")
        self.assertIn("DELETE", detail_strip)

    def test_dry_run_still_validates_without_touching_dss(self):
        ctx = FactoryContext(project=_StripProject(), dry_run=True)
        pipeline.create_domain(ctx, make_spec(),
                               wizard_config=self._wizard_config(),
                               settings=self._settings(), steps=["semantic_config"])
        # Validation runs (planning only) and records the strip note; nothing ran.
        self.assertFalse(ctx.has_failures())
        self.assertEqual(statuses(ctx).get("semantic_config_validation"), MANUAL)


if __name__ == "__main__":
    unittest.main()
