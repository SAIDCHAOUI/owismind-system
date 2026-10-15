"""DSS-free tests of the sub-agent review (owismind_factory.review + the guided
review run): live model -> config, diff, selection, sample masking, prompt,
and the run machine with every DSS access patched."""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MIRROR = os.path.dirname(_HERE)
_LIB = os.path.join(_MIRROR, "project-library", "python")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from owismind_factory import guided, hub, removal, review, semantic_builder, wizard  # noqa: E402

RAW = {
    "privateEditorData": {"owismindFactory": {"domain": "deals"}},
    "entities": [{
        "name": "deal_record", "description": "One row per deal and month.",
        "attributes": [
            {"column": "Stage", "description": "Stage.", "indexDistinctValues": True},
            {"column": "Amount", "description": "Amount.", "indexDistinctValues": False},
        ],
        "metrics": [{"name": "Total", "description": "Sum.", "pseudoSQLExpression": "SUM(Amount)"}],
        "filters": [{"name": "Open", "description": "Open deals.", "pseudoSQLExpression": "Stage <> 'Won'"}],
        "primaryKey": {"attributes": []},
    }],
    "glossaryTerms": [{"term": "Customer", "synonyms": ["client"]}],
    "sqlGenerationConfig": {"instructions": "Never JOIN."},
    "goldenQueries": [{"name": "t", "question": "Top deals", "generatedSql": "SELECT 1"}],
}


def _proposal(base):
    import copy
    p = copy.deepcopy(base)
    p["attributes"][0]["description"] = "Sales stage. Closed means Won."
    p["attributes"][1]["resolvable"] = True
    p["metrics"].append({"name": "Deals", "pseudo_sql": "COUNT(DISTINCT id)"})
    p["filters"] = []
    p["glossary"][0]["synonyms"] = ["client", "account"]
    p["instructions"] = "Never JOIN. Count each deal once."
    p["planner_description"] = "Deals expert."
    p["golden_queries"].append({"question": "Deals won in 2025", "sql": "SELECT 2"})
    return p


class TestReviewPure(unittest.TestCase):
    def setUp(self):
        self.base = review.config_from_model_raw(RAW)

    def test_config_from_model(self):
        self.assertEqual([a["column"] for a in self.base["attributes"]], ["Stage", "Amount"])
        self.assertTrue(self.base["attributes"][0]["resolvable"])
        self.assertEqual(self.base["metrics"][0]["pseudo_sql"], "SUM(Amount)")
        self.assertEqual(self.base["golden_queries"][0]["sql"], "SELECT 1")
        self.assertTrue(review.is_factory_model(RAW))
        self.assertFalse(review.is_factory_model({"entities": []}))

    def test_diff_lists_every_change(self):
        changes = review.diff_configs(self.base, _proposal(self.base), "Old routing.",
                                      {"column:Stage": "Closed now means won."})
        ids = {c["id"]: c for c in changes}
        self.assertEqual(ids["column:Stage"]["action"], "changed")
        self.assertEqual(ids["column:Stage"]["why"], "Closed now means won.")
        self.assertIn("search:Amount", ids)
        self.assertEqual(ids["metric:Deals"]["action"], "added")
        self.assertEqual(ids["filter:Open"]["action"], "removed")
        self.assertEqual(ids["term:Customer"]["action"], "changed")
        self.assertIn("rules", ids)
        self.assertIn("routing", ids)
        self.assertEqual(ids["example:Deals won in 2025"]["action"], "added")
        self.assertNotIn("SELECT", ids["example:Deals won in 2025"]["after"])

    def test_no_change_no_card(self):
        self.assertEqual(review.diff_configs(self.base, dict(self.base), ""), [])

    def test_unknown_column_is_ignored(self):
        p = dict(self.base)
        p["attributes"] = self.base["attributes"] + [{"column": "Invented", "description": "x"}]
        self.assertEqual(review.diff_configs(self.base, p, ""), [])

    def test_apply_only_kept(self):
        p = _proposal(self.base)
        changes = review.diff_configs(self.base, p, "Old routing.")
        final, routing, reindex = review.apply_selection(
            self.base, p, changes, ["column:Stage", "metric:Deals", "filter:Open"])
        self.assertEqual(final["attributes"][0]["description"], "Sales stage. Closed means Won.")
        self.assertFalse(final["attributes"][1]["resolvable"])
        self.assertEqual([m["name"] for m in final["metrics"]], ["Total", "Deals"])
        self.assertEqual(final["filters"], [])
        self.assertEqual(final["instructions"], "Never JOIN.")
        self.assertIsNone(routing)
        self.assertFalse(reindex)
        # the base is never mutated
        self.assertEqual(self.base["attributes"][0]["description"], "Stage.")

    def test_apply_routing_and_reindex(self):
        p = _proposal(self.base)
        changes = review.diff_configs(self.base, p, "Old routing.")
        final, routing, reindex = review.apply_selection(self.base, p, changes,
                                                         ["routing", "search:Amount", "rules"])
        self.assertEqual(routing, "Deals expert.")
        self.assertTrue(reindex)
        self.assertTrue(final["attributes"][1]["resolvable"])
        self.assertEqual(final["instructions"], "Never JOIN. Count each deal once.")

    def test_sample_masking_and_bounds(self):
        cols = ["Account_name", "contact_email", "Phone", "Amount"]
        rows = [["Acme", "a@b.c", "0600", "x" * 200] for _ in range(100)]
        text = review.format_sample_rows(cols, rows)
        lines = text.splitlines()
        self.assertEqual(len(lines), review.SAMPLE_ROWS)
        self.assertNotIn("a@b.c", text)
        self.assertNotIn("0600", text)
        self.assertIn("Acme", text)
        self.assertNotIn("x" * 100, text)

    def test_prompt(self):
        prompt = review.build_review_prompt(
            self.base, "DIGEST", "SAMPLES", {"Stage": "Owner text"},
            {"wrong": "WRONG_TEXT", "know": "KNOW_TEXT"}, "deals",
            answers={"q1": "A1"}, routing="ROUTING_TEXT")
        for needle in ("WRONG_TEXT", "KNOW_TEXT", "Owner text", "SAMPLES", "DIGEST",
                       "ROUTING_TEXT", "A1", "__TABLE__"):
            self.assertIn(needle, prompt)
        self.assertNotIn(chr(0x2014), prompt)
        self.assertNotIn(chr(0x2013), prompt)

    def test_digest_keeps_every_column(self):
        profile = {"col%d" % i: {"description": "y" * 3000} for i in range(120)}
        digest = wizard.build_profile_digest(profile, "DS")
        self.assertNotIn("[digest truncated]", digest)
        for i in range(120):
            self.assertIn("COLUMN col%d:" % i, digest)


class _Store(object):
    def save(self, run):
        pass


class TestReviewRun(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        self.caps = {"deals_expert": {"domain": "deals", "lookup_dataset": "Deals",
                                      "label_en": "Deals", "planner_description": "Old routing."}}
        self.calls = []
        self._orig = (hub.read_capabilities, hub.write_capabilities, hub.write_json,
                      removal.resolve_model, semantic_builder.read_model_raw,
                      semantic_builder.find_model_by_name, semantic_builder.apply_config,
                      semantic_builder.start_indexing, wizard.get_physical_table)
        hub.read_capabilities = lambda project: self.caps
        hub.write_capabilities = lambda project, caps, backup=True: self.saved.setdefault("caps", caps)
        hub.write_json = lambda project, path, obj: self.saved.setdefault(path, obj)
        removal.resolve_model = lambda project, spec, tool_id: ("M1", spec.semantic_model_name)
        semantic_builder.read_model_raw = lambda project, model_id, version_id=None: RAW

        self.model_id = "M1"
        semantic_builder.find_model_by_name = lambda project, name: type("M", (), {"id": self.model_id})()

        def fake_apply(ctx, model_id, config, created_this_run=False, version_id=None):
            self.calls.append(("apply", model_id, config, created_this_run))
            ctx.done("semantic_config", "ok")
            return model_id

        def fake_index(ctx, model_id, wait=True):
            self.calls.append(("index", model_id))
            ctx.done("semantic_index", "ok")
        semantic_builder.apply_config = fake_apply
        semantic_builder.start_indexing = fake_index
        wizard.get_physical_table = lambda project, name: '"P_deals"'

    def tearDown(self):
        (hub.read_capabilities, hub.write_capabilities, hub.write_json,
         removal.resolve_model, semantic_builder.read_model_raw,
         semantic_builder.find_model_by_name, semantic_builder.apply_config,
         semantic_builder.start_indexing, wizard.get_physical_table) = self._orig

    def test_full_review_run(self):
        run = guided.start_review_run(object(), "deals_expert", settings={})
        self.assertEqual(run["current_stage"], "review_feedback")
        self.assertTrue(guided.can_verify(run))
        info = run["state"]["review"]
        base = info["base"]
        guided.record_review_proposal(run, {"proposed": _proposal(base), "notes": {}},
                                      {"wrong": "w", "know": "k"}, {})
        self.assertTrue(info["changes"])
        self.assertEqual(sorted(info["keep"]), sorted(c["id"] for c in info["changes"]))
        info["keep"] = ["column:Stage", "routing", "bogus"]
        run = guided.verify_current_stage(object(), run, settings={})
        self.assertEqual(run["current_stage"], "review_apply")
        self.assertEqual(info["keep"], ["column:Stage", "routing"])
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["status"], guided.RUN_DONE)
        self.assertEqual(len(self.calls), 1)
        _kind, model_id, config, created = self.calls[0]
        self.assertEqual((model_id, created), ("M1", False))
        # ONLY the kept column is sent: nothing else of the live model is rewritten
        self.assertEqual(config, {"attributes": [{"column": "Stage",
                                                  "description": "Sales stage. Closed means Won."}]})
        self.assertEqual(self.saved["caps"]["deals_expert"]["planner_description"], "Deals expert.")
        self.assertEqual(info["applied"], {"count": 2, "routing": True, "reindexed": False})

    def _to_apply(self, keep):
        run = guided.start_review_run(object(), "deals_expert", settings={})
        guided.record_review_proposal(run, {"proposed": _proposal(run["state"]["review"]["base"])}, {}, {})
        run["state"]["review"]["keep"] = keep
        return guided.verify_current_stage(object(), run, settings={})

    def test_model_swapped_is_refused_before_any_write(self):
        run = self._to_apply(["column:Stage"])
        self.model_id = "OTHER"
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["state"]["stages"]["review_apply"]["status"], guided.STAGE_FAILED)
        self.assertEqual(self.calls, [])

    def test_bad_new_example_is_refused_before_any_write(self):
        run = self._to_apply(["example:Deals won in 2025"])
        run["state"]["review"]["proposal"]["golden_queries"][-1]["sql"] = "DELETE FROM __TABLE__"
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["state"]["stages"]["review_apply"]["status"], guided.STAGE_FAILED)
        self.assertEqual(self.calls, [])

    def test_example_kept_keeps_existing_ones_and_substitutes_table(self):
        run = self._to_apply(["example:Deals won in 2025", "search:Amount"])
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["status"], guided.RUN_DONE)
        config = self.calls[0][2]
        self.assertEqual([g["question"] for g in config["golden_queries"]], ["Top deals", "Deals won in 2025"])
        self.assertEqual(config["attributes"], [{"column": "Amount", "resolvable": True}])
        self.assertEqual(self.calls[1], ("index", "M1"))

    def test_dangerous_expression_is_refused_before_any_write(self):
        run = self._to_apply(["metric:Deals"])
        run["state"]["review"]["proposal"]["metrics"][-1]["pseudo_sql"] = "COUNT(*)); DROP TABLE x; --"
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["state"]["stages"]["review_apply"]["status"], guided.STAGE_FAILED)
        self.assertEqual(self.calls, [])

    def test_config_issues(self):
        self.assertEqual(review.config_issues({"metrics": [{"name": "a", "pseudo_sql": "SUM(x)"}]}), [])
        self.assertTrue(review.config_issues({"filters": [{"name": "f", "pseudo_sql": "1=1; DELETE"}]}))
        self.assertTrue(review.config_issues({"instructions": "x" * 30000}))
        # checked on the RAW text: a literal can never hide a separator or a keyword
        self.assertTrue(review.config_issues({"filters": [{"name": "f", "pseudo_sql": "Stage = 'x'; DROP TABLE t"}]}))
        self.assertTrue(review.config_issues({"filters": [{"name": "f", "pseudo_sql": "Stage = $$a$$"}]}))
        self.assertTrue(review.config_issues({"filters": [{"name": "f", "pseudo_sql": "Stage = E'\\x27'"}]}))
        self.assertEqual(review.config_issues({"filters": [{"name": "f", "pseudo_sql": "Stage = 'Won'"}]}), [])

    def test_alternate_sql_fields_never_reach_the_writer(self):
        run = self._to_apply(["example:Deals won in 2025", "metric:Deals"])
        proposal = run["state"]["review"]["proposal"]
        proposal["golden_queries"][-1]["generatedSql"] = "DELETE FROM __TABLE__"
        proposal["metrics"][-1]["pseudoSQLExpression"] = "1); DROP TABLE t; --"
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["status"], guided.RUN_DONE)
        config = self.calls[0][2]
        self.assertNotIn("DELETE", str(config))
        self.assertNotIn("DROP", str(config))
        self.assertNotIn("pseudoSQLExpression", str(config))

    def test_normalize_proposal(self):
        out = review.normalize_proposal({"golden_queries": [{"question": "q", "generatedSql": "x", "sql": "SELECT 1"}],
                                         "metrics": [{"name": "m", "pseudoSQLExpression": "x"}], "evil": 1})
        self.assertEqual(out, {"golden_queries": [{"question": "q", "sql": "SELECT 1"}],
                               "metrics": [{"name": "m"}]})

    def test_new_example_raw_check(self):
        run = self._to_apply(["example:Deals won in 2025"])
        run["state"]["review"]["proposal"]["golden_queries"][-1]["sql"] = "SELECT 'a'' ; drop' FROM __TABLE__"
        run = guided.run_current_stage(object(), run, settings={})
        self.assertEqual(run["state"]["stages"]["review_apply"]["status"], guided.STAGE_FAILED)
        self.assertEqual(self.calls, [])

    def test_personal_values_masked_in_any_column(self):
        text = review.format_sample_rows(["Comment"], [["call john at +33 6 12 34 56 78 or j.doe@corp.com"]])
        self.assertNotIn("j.doe@corp.com", text)
        self.assertNotIn("12 34 56", text)
        self.assertIn("call john", text)

    def test_oversized_routing_is_never_proposed(self):
        base = review.config_from_model_raw(RAW)
        p = dict(base, planner_description="x" * 2500)
        self.assertNotIn("routing", [c["id"] for c in review.diff_configs(base, p, "old")])

    def test_nothing_kept_does_not_advance(self):
        run = guided.start_review_run(object(), "deals_expert", settings={})
        guided.record_review_proposal(run, {"proposed": _proposal(run["state"]["review"]["base"])}, {}, {})
        run["state"]["review"]["keep"] = []
        run = guided.verify_current_stage(object(), run, settings={})
        self.assertEqual(run["current_stage"], "review_feedback")

    def test_hand_made_model_is_refused(self):
        semantic_builder.read_model_raw = lambda project, model_id, version_id=None: {"entities": []}
        with self.assertRaises(guided.ReviewUnsupported):
            guided.start_review_run(object(), "deals_expert", settings={})

    def test_unknown_capability(self):
        with self.assertRaises(ValueError):
            guided.start_review_run(object(), "nope", settings={})


if __name__ == "__main__":
    unittest.main()
