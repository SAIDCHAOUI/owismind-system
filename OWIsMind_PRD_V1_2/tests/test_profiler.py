"""DSS-free unit tests for the two Flow recipes (profiler + value index).

Same harness as orchestrator/salesdrive tests: ``dataiku`` is stubbed in
``sys.modules`` BEFORE the recipe files are loaded via importlib. Only PURE
functions are tested; pandas-dependent paths are skipped when pandas is not
installed locally (they run in DSS where pandas is guaranteed).

Run from the repo root:
    python3 -m unittest discover -s dataiku-agents/tests -v
"""

import importlib.util
import json
import os
import sys
import types
import unittest


def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
    dataiku_mod.Dataset = lambda *a, **k: None
    dataiku_mod.SQLExecutor2 = lambda *a, **k: None

    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        pass

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg

    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)


_install_dataiku_stub()

_HERE = os.path.dirname(__file__)


def _load(name, rel_path):
    path = os.path.abspath(os.path.join(_HERE, "..", rel_path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


prof = _load("profiler_under_test",
             "OWISMIND/OWISMIND_DEV/recipes/profile_dataset_recipe.py")
vidx = _load("value_index_under_test",
             "OWISMIND/OWISMIND_DEV/recipes/build_value_index_recipe.py")

try:
    import pandas  # noqa: F401
    HAS_PANDAS = True
except Exception:
    HAS_PANDAS = False


# ==========================================================================
# norm_value (FROZEN contract shared by both recipes + the agent)
# ==========================================================================
class TestNormValue(unittest.TestCase):

    def test_accents_case_whitespace(self):
        self.assertEqual(prof.norm_value("  Algérie   Télécom "), "algerie telecom")
        self.assertEqual(vidx.norm_value("  Algérie   Télécom "), "algerie telecom")

    def test_identical_between_recipes(self):
        for raw in ("IPL +", "Côte d'Ivoire", "1&1 Mobilfunk GmbH", "  x\ty "):
            self.assertEqual(prof.norm_value(raw), vidx.norm_value(raw))


# ==========================================================================
# detect_time_format
# ==========================================================================
class TestDetectTimeFormat(unittest.TestCase):

    def test_dss_date_type_wins(self):
        self.assertEqual(prof.detect_time_format("date", []), "date")
        self.assertEqual(prof.detect_time_format("datetime", ["whatever"]), "date")

    def test_yyyy_mm_dd_strings(self):
        self.assertEqual(prof.detect_time_format(
            "string", ["2026-01-01", "2025-12-31"]), "yyyy_mm_dd_str")

    def test_yyyy_mm_strings(self):
        self.assertEqual(prof.detect_time_format(
            "string", ["2026-01", "2025-12"]), "yyyy_mm_str")

    def test_yyyymm_ints(self):
        self.assertEqual(prof.detect_time_format(
            "bigint", [202601, 202512]), "yyyymm_int")

    def test_year_ints(self):
        self.assertEqual(prof.detect_time_format("int", [2024, 2025, 2026]),
                         "year_int")

    def test_garbage_is_none(self):
        self.assertIsNone(prof.detect_time_format("string", ["hello", "world"]))
        self.assertIsNone(prof.detect_time_format("bigint", [42, 999999]))
        self.assertIsNone(prof.detect_time_format("string", []))

    def test_mixed_samples_rejected(self):
        self.assertIsNone(prof.detect_time_format(
            "string", ["2026-01-01", "not a date"]))


# ==========================================================================
# validate_enrichment
# ==========================================================================
class TestValidateEnrichment(unittest.TestCase):

    COLS = ["Phase", "amount_eur", "customer_id", "customer_name"]

    def test_non_dict_is_empty(self):
        out = prof.validate_enrichment("nope", self.COLS)
        self.assertEqual(out, {"dataset": {}, "columns": {}})

    def test_metric_unknown_column_rejected(self):
        out = prof.validate_enrichment({"dataset": {"metrics": [
            {"name": "x", "agg": "SUM", "column": "GHOST"}]}}, self.COLS)
        self.assertNotIn("metrics", out["dataset"])

    def test_metric_validation_and_unit(self):
        out = prof.validate_enrichment({"dataset": {
            "metrics": [{"name": "Revenue Total!", "agg": "sum",
                         "column": "amount_eur", "format": "amount",
                         "unit": "EUR", "label_fr": "Revenu"}],
            "default_metric": "revenue_total_"}}, self.COLS)
        m = out["dataset"]["metrics"][0]
        self.assertEqual(m["agg"], "SUM")
        self.assertEqual(m["column"], "amount_eur")
        self.assertEqual(m["format"], "amount")
        self.assertEqual(m["unit"], "EUR")
        self.assertEqual(m["name"], "revenue_total_")
        self.assertEqual(out["dataset"]["default_metric"], "revenue_total_")

    def test_default_metric_falls_back_to_first(self):
        out = prof.validate_enrichment({"dataset": {
            "metrics": [{"name": "rev", "agg": "SUM", "column": "amount_eur"}],
            "default_metric": "ghost"}}, self.COLS)
        self.assertEqual(out["dataset"]["default_metric"], "rev")

    def test_count_metric_needs_no_column(self):
        out = prof.validate_enrichment({"dataset": {"metrics": [
            {"name": "lines", "agg": "COUNT", "column": None,
             "format": "count"}]}}, self.COLS)
        self.assertEqual(out["dataset"]["metrics"][0]["column"], None)

    def test_scenario_and_time_columns_must_exist(self):
        out = prof.validate_enrichment({"dataset": {
            "scenario": {"column": "GHOST"}, "time": {"column": "GHOST"}}},
            self.COLS)
        self.assertNotIn("scenario", out["dataset"])
        self.assertNotIn("time", out["dataset"])
        out = prof.validate_enrichment({"dataset": {
            "scenario": {"column": "Phase", "default_values": ["ACTUALS"]}}},
            self.COLS)
        self.assertEqual(out["dataset"]["scenario"]["column"], "Phase")

    def test_column_role_and_display_pair(self):
        out = prof.validate_enrichment({"columns": {
            "customer_id": {"role": "identifier",
                            "display_column": "customer_name",
                            "synonyms": ["client", "Client", "customer"]},
            "GHOST": {"role": "dimension"},
            "Phase": {"role": "not_a_role", "description_en": "The phase."},
        }}, self.COLS)
        self.assertNotIn("GHOST", out["columns"])
        self.assertEqual(out["columns"]["customer_id"]["display_column"],
                         "customer_name")
        # case-insensitive synonym dedupe
        self.assertEqual(out["columns"]["customer_id"]["synonyms"],
                         ["client", "customer"])
        # bad role dropped, description kept
        self.assertNotIn("role", out["columns"]["Phase"])
        self.assertEqual(out["columns"]["Phase"]["description_en"], "The phase.")


# ==========================================================================
# overrides
# ==========================================================================
class TestOverrides(unittest.TestCase):

    def test_parse_override_value(self):
        self.assertEqual(prof.parse_override_value('["a", "b"]'), ["a", "b"])
        self.assertEqual(prof.parse_override_value("plain text"), "plain text")
        self.assertEqual(prof.parse_override_value('{"x": 1}'), {"x": 1})
        self.assertIsNone(prof.parse_override_value("   "))
        self.assertIsNone(prof.parse_override_value(None))

    def test_apply_overrides(self):
        ds = {"description_fr": "llm text", "notes": []}
        cols = {"Phase": {"description_fr": "llm", "llm_generated": True}}
        rows = [
            {"key": "__dataset__", "field": "description_fr", "value": "humain"},
            {"key": "Phase", "field": "synonyms", "value": '["phase", "scénario"]'},
            {"key": "GHOST", "field": "role", "value": "dimension"},
            {"key": "", "field": "x", "value": "y"},
        ]
        n = prof.apply_overrides(ds, cols, rows)
        self.assertEqual(n, 2)
        self.assertEqual(ds["description_fr"], "humain")
        self.assertEqual(cols["Phase"]["synonyms"], ["phase", "scénario"])
        self.assertTrue(cols["Phase"]["human_override"])


# ==========================================================================
# default_role / should_index_column
# ==========================================================================
class TestRolesAndIndexSelection(unittest.TestCase):

    def test_default_role(self):
        self.assertEqual(prof.default_role("string", 5, 1000, 10, "yyyymm_int", "ym"), "time")
        self.assertEqual(prof.default_role("double", 999, 1000, 0, None, "amount"), "measure")
        self.assertEqual(prof.default_role("string", 500, 1000, 200, None, "comment"), "free_text")
        self.assertEqual(prof.default_role("string", 990, 1000, 12, None, "ref"), "identifier")
        self.assertEqual(prof.default_role("string", 12, 1000, 12, None, "diamond_id"), "identifier")
        self.assertEqual(prof.default_role("string", 30, 1000, 15, None, "zone"), "dimension")

    def test_should_index_column(self):
        f = vidx.should_index_column
        self.assertTrue(f("zone", "string", 30, 170000, 12))
        self.assertFalse(f("amount", "double", 30, 170000, 12))
        self.assertFalse(f("created", "date", 30, 170000, 12))
        self.assertFalse(f("comment", "string", 5000, 170000, 200))
        self.assertFalse(f("huge", "string", 50001, 170000, 12))
        # quasi-unique short codes stay indexable, long ids do not
        # (the per-column value cap applies first: > MAX_VALUES_PER_COLUMN
        # distincts are never indexed regardless of shape)
        self.assertTrue(f("code", "string", 9800, 10000, 8))
        self.assertFalse(f("uuid", "string", 9800, 10000, 36))
        self.assertFalse(f("code", "string", 169000, 170000, 8))

    def test_include_exclude_overrides(self):
        old_inc, old_exc = vidx.INCLUDE_COLUMNS, vidx.EXCLUDE_COLUMNS
        try:
            vidx.INCLUDE_COLUMNS = ["amount"]
            vidx.EXCLUDE_COLUMNS = ["zone"]
            self.assertTrue(vidx.should_index_column("amount", "double", 30, 1000, 5))
            self.assertFalse(vidx.should_index_column("zone", "string", 30, 1000, 5))
        finally:
            vidx.INCLUDE_COLUMNS, vidx.EXCLUDE_COLUMNS = old_inc, old_exc


# ==========================================================================
# safe_json_parse + enrichment input
# ==========================================================================
class TestEnrichmentPlumbing(unittest.TestCase):

    def test_safe_json_parse_fenced(self):
        self.assertEqual(prof.safe_json_parse('```json\n{"a": 1}\n```'), {"a": 1})
        self.assertEqual(prof.safe_json_parse('bla {"a": 1} bla'), {"a": 1})
        self.assertIsNone(prof.safe_json_parse("not json"))
        self.assertIsNone(prof.safe_json_parse(""))

    def test_build_enrichment_input_contains_enums_and_stats(self):
        ds = {"row_count": 170000,
              "time": {"column": "ym", "format": "yyyymm_int",
                       "min": 202401, "max": 202606}}
        cols = {
            "Phase": {"dss_type": "string", "distinct_count": 3, "null_pct": 0.0,
                      "is_enum": True, "values": [{"v": "ACTUALS", "n": 100}],
                      "samples": [], "stats": {}},
            "amount": {"dss_type": "double", "distinct_count": 9999,
                       "null_pct": 1.5, "is_enum": False, "values": [],
                       "samples": ["12.5"], "stats": {"min": 0, "max": 10}},
        }
        text = prof.build_enrichment_input("DEMO", ds, cols)
        self.assertIn("ACTUALS(100)", text)
        self.assertIn("ROW COUNT: 170000", text)
        self.assertIn("yyyymm_int", text)
        self.assertIn('"max": 10', text)


# ==========================================================================
# pandas-dependent paths (run in DSS / any env with pandas)
# ==========================================================================
@unittest.skipUnless(HAS_PANDAS, "pandas not installed locally - covered in DSS")
class TestPandasPaths(unittest.TestCase):

    def test_profile_dataframe_enum_and_time(self):
        import pandas as pd
        df = pd.DataFrame({
            "Phase": ["ACTUALS"] * 6 + ["BUDGET"] * 4,
            "year_month": ["2026-01-01"] * 5 + ["2026-02-01"] * 5,
            "amount_eur": [10.0, 20.0, 30.0, 40.0, 50.0] * 2,
            "customer": ["A", "B", "C", "D", "E", "F", "G", "H", "I", "J"],
        })
        schema = [{"name": c, "type": t} for c, t in
                  (("Phase", "string"), ("year_month", "string"),
                   ("amount_eur", "double"), ("customer", "string"))]
        ds, cols = prof.profile_dataframe(df, schema)
        self.assertEqual(ds["row_count"], 10)
        self.assertTrue(cols["Phase"]["is_enum"])
        self.assertEqual(cols["Phase"]["values"][0]["v"], "ACTUALS")
        self.assertEqual(ds["time"]["column"], "year_month")
        self.assertEqual(ds["time"]["format"], "yyyy_mm_dd_str")
        self.assertEqual(cols["amount_eur"]["role"], "measure")
        json.dumps(ds)   # must be JSON-serializable
        for c in cols.values():
            c.pop("_time_format", None)
            json.dumps(c)

    def test_build_index_rows(self):
        import pandas as pd
        df = pd.DataFrame({
            "customer": ["Algérie Télécom", "HALYS", "HALYS", None],
            "amount": [1.0, 2.0, 3.0, 4.0],
        })
        rows = vidx.build_index_rows(df, {"customer": "string",
                                          "amount": "double"})
        by_val = {r["value"]: r for r in rows}
        self.assertIn("HALYS", by_val)
        self.assertEqual(by_val["HALYS"]["occurrences"], 2)
        self.assertEqual(by_val["Algérie Télécom"]["value_norm"],
                         "algerie telecom")
        self.assertTrue(all(r["column_name"] == "customer" for r in rows))


# ==========================================================================
# indexed-flag parity: the profiler MUST mark the same columns the value index
# grounds, or UNDERSTAND advertises the wrong groundable columns and named
# entities never resolve (the "fabricated account name" failure).
# ==========================================================================
class TestIndexParity(unittest.TestCase):

    CASES = [
        ("string", 3000, 84000, 15),    # account-name-like -> indexed
        ("string", 5, 84000, 4),        # enum -> indexed
        ("string", 60000, 84000, 8),    # LD-like high cardinality -> skipped
        ("string", 84000, 84000, 40),   # quasi-unique long id -> skipped
        ("string", 1000, 84000, 200),   # free text -> skipped
        ("bigint", 5000, 84000, 6),     # numeric -> skipped
        ("date", 1000, 84000, 10),      # date -> skipped
        ("string", 0, 84000, 0),        # empty -> skipped
    ]

    def test_profiler_matches_value_index_rule(self):
        for dss_type, distinct, rows, avg_len in self.CASES:
            a = prof.should_index_value_column(dss_type, distinct, rows, avg_len)
            b = vidx.should_index_column("x", dss_type, distinct, rows, avg_len)
            self.assertEqual(a, b, "%s distinct=%s avg=%s" % (dss_type, distinct, avg_len))


# ==========================================================================
# time-axis election: a creation/opened column must beat a close/update one,
# so a bare "this year" window defaults to creationDate (not Latest_Closed_Date,
# which silently drops every open ticket).
# ==========================================================================
class TestTimeNameRank(unittest.TestCase):

    def test_creation_beats_closed_and_update(self):
        self.assertLess(prof.time_name_rank("creationDate"),
                        prof.time_name_rank("Latest_Closed_Date"))
        self.assertLess(prof.time_name_rank("creationDate"),
                        prof.time_name_rank("lastUpdate"))
        self.assertLess(prof.time_name_rank("creationDate"),
                        prof.time_name_rank("detectionDate"))

    def test_creation_wins_among_ticket_dates(self):
        # Same priority/format -> the sort key (priority, name_rank, name) must
        # elect creationDate over the alphabetically-first Latest_Closed_Date.
        cands = [(0, prof.time_name_rank(n), n, "date") for n in
                 ("Latest_Closed_Date", "creationDate", "detectionDate", "lastUpdate")]
        cands.sort()
        self.assertEqual(cands[0][2], "creationDate")


if __name__ == "__main__":
    unittest.main()
