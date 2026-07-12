"""DSS-free tests for the two non-blocking helpers added to the factory:

- ``DomainSpec.preflight`` : advisory WARNING strings, never raises.
- ``FactoryContext.runbook_markdown`` : an ordered human runbook.

No dataiku import: the factory package imports cleanly under plain CPython.
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MIRROR = os.path.dirname(_HERE)
_LIB = os.path.join(_MIRROR, "project-library", "python")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from owismind_factory.fctx import FactoryContext  # noqa: E402
from owismind_factory.spec import DomainSpec, MAX_DATASET_NAME  # noqa: E402


def _clean_spec():
    """A spec that should raise NO preflight warning."""
    return DomainSpec(
        domain="satisfaction",
        base_dataset="CX_Surveys",
        label_fr="Expert satisfaction",
        label_en="Satisfaction expert",
        planner_description="Owns every satisfaction figure: NPS, CSAT trends, "
                            "verbatim counts, and survey breakdowns by segment.",
        lookup_search_columns=["Account_name", "segment"],
    )


class TestPreflightClean(unittest.TestCase):
    def test_clean_spec_has_no_warning(self):
        self.assertEqual(_clean_spec().preflight(), [])

    def test_preflight_never_raises_and_returns_list(self):
        # Even with no arguments and a minimal spec, it must return a list.
        spec = DomainSpec(domain="x_ray", base_dataset="Xr", label_fr="a", label_en="b")
        result = spec.preflight()
        self.assertIsInstance(result, list)


class TestPreflightCollisions(unittest.TestCase):
    def test_capability_key_collision(self):
        spec = _clean_spec()
        warnings = spec.preflight(existing_capability_keys=["satisfaction_expert"])
        self.assertTrue(any("capability_key" in w for w in warnings))

    def test_domain_collision(self):
        spec = _clean_spec()
        warnings = spec.preflight(existing_domains=["satisfaction"])
        self.assertTrue(any("domain" in w and "already exists" in w for w in warnings))

    def test_no_collision_when_keys_absent(self):
        spec = _clean_spec()
        warnings = spec.preflight(existing_capability_keys=["revenue_expert"],
                                  existing_domains=["revenue", "tickets"])
        self.assertEqual(warnings, [])


class TestPreflightLookup(unittest.TestCase):
    def test_empty_lookup_columns_warns(self):
        spec = DomainSpec(
            domain="satisfaction", base_dataset="CX_Surveys",
            label_fr="Expert satisfaction", label_en="Satisfaction expert",
            planner_description="A rich wizard routing description of satisfaction.",
            lookup_search_columns=[],
        )
        warnings = spec.preflight()
        self.assertTrue(any("lookup_search_columns is empty" in w for w in warnings))

    def test_populated_lookup_columns_no_warning(self):
        warnings = _clean_spec().preflight()
        self.assertFalse(any("lookup_search_columns" in w for w in warnings))


class TestPreflightHeadroom(unittest.TestCase):
    def test_dataset_name_close_to_cap_warns_and_cites_name(self):
        # value_catalog suffix is the longest (+14); a 26-char base lands the
        # catalog name exactly at the cap (headroom 0) and the index name at 2.
        base = "A" * (MAX_DATASET_NAME - len("_value_catalog"))
        spec = DomainSpec(
            domain="satisfaction", base_dataset=base,
            label_fr="Expert satisfaction", label_en="Satisfaction expert",
            planner_description="A rich wizard routing description of satisfaction.",
            lookup_search_columns=["c"],
        )
        warnings = spec.preflight()
        headroom_warnings = [w for w in warnings if "from the %d cap" % MAX_DATASET_NAME in w]
        self.assertTrue(headroom_warnings)
        self.assertTrue(any(spec.value_catalog_dataset in w for w in headroom_warnings))

    def test_short_name_has_headroom(self):
        warnings = _clean_spec().preflight()
        self.assertFalse(any("cap" in w for w in warnings))


class TestPreflightLabelsAndPlanner(unittest.TestCase):
    def test_identical_labels_warn(self):
        spec = DomainSpec(
            domain="satisfaction", base_dataset="CX_Surveys",
            label_fr="Satisfaction expert", label_en="Satisfaction expert",
            planner_description="A rich wizard routing description of satisfaction.",
            lookup_search_columns=["c"],
        )
        warnings = spec.preflight()
        self.assertTrue(any("label_fr and label_en are identical" in w for w in warnings))

    def test_generic_planner_description_detected(self):
        # No planner_description supplied: the spec derives the generic fallback.
        spec = DomainSpec(
            domain="satisfaction", base_dataset="CX_Surveys",
            label_fr="Expert satisfaction", label_en="Satisfaction expert",
            lookup_search_columns=["c"],
        )
        warnings = spec.preflight()
        self.assertTrue(any("planner_description is the generic" in w for w in warnings))

    def test_rich_planner_description_not_flagged(self):
        warnings = _clean_spec().preflight()
        self.assertFalse(any("planner_description" in w for w in warnings))


class TestRunbookMarkdown(unittest.TestCase):
    def _ctx_with_actions(self):
        ctx = FactoryContext(project=object(), dry_run=True)
        ctx.done("source_dataset", "imported CX_Surveys")
        ctx.manual("repoint_model", "open the semantic model and repoint it")
        ctx.manual("smoke_test", "ask a real question end to end")
        return ctx

    def test_runbook_lists_manual_steps_in_order(self):
        book = self._ctx_with_actions().runbook_markdown()
        self.assertIn("# Run book", book)
        pos_repoint = book.find("repoint_model")
        pos_smoke = book.find("smoke_test")
        self.assertNotEqual(pos_repoint, -1)
        self.assertNotEqual(pos_smoke, -1)
        self.assertLess(pos_repoint, pos_smoke)
        # Ordered, unchecked checkboxes for each manual step.
        self.assertIn("1. [ ] `repoint_model`", book)
        self.assertIn("2. [ ] `smoke_test`", book)

    def test_runbook_summary_counts(self):
        book = self._ctx_with_actions().runbook_markdown()
        self.assertIn("Summary:", book)
        self.assertIn("1 DONE", book)
        self.assertIn("2 MANUAL", book)

    def test_runbook_warns_on_failed_and_blocked(self):
        ctx = FactoryContext(project=object(), dry_run=False, abort_on_failure=False)
        ctx.fail("build", "recipe raised ValueError")
        ctx.block("smoke_test", "skipped: build failed")
        ctx.manual("fix_it", "inspect the recipe logs")
        book = ctx.runbook_markdown()
        self.assertIn("## WARNING: unresolved before you start", book)
        self.assertIn("FAILED", book)
        self.assertIn("BLOCKED", book)
        self.assertIn("recipe raised ValueError", book)

    def test_runbook_no_manual_steps(self):
        ctx = FactoryContext(project=object(), dry_run=True)
        ctx.done("only_step", "all automated")
        book = ctx.runbook_markdown()
        self.assertIn("[x] none", book)
        self.assertNotIn("## WARNING", book)

    def test_runbook_has_no_em_or_en_dash(self):
        book = self._ctx_with_actions().runbook_markdown()
        self.assertNotIn("\u2014", book)
        self.assertNotIn("\u2013", book)

    def test_report_markdown_untouched(self):
        # runbook is additive: the record-style report still works as before.
        ctx = self._ctx_with_actions()
        report = ctx.report_markdown()
        self.assertIn("# Factory report", report)
        self.assertIn("Manual steps remaining", report)


if __name__ == "__main__":
    unittest.main()
