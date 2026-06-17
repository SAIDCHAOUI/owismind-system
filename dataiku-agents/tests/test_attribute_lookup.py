"""DSS-free unit tests for the attribute_lookup Custom Python agent tool
(``dataiku-agents/tools/attribute_lookup_tool.py``).

``dataiku`` and ``dataiku.llm.agent_tools`` are stubbed BEFORE the tool file is
loaded via importlib. Pure helpers (norm, search needle, attribute mapping, SQL
builder, value summary, alias suggestions) are tested directly. The full
``invoke`` flow is tested with a tool subclass whose DSS-touching methods are
replaced by fixtures - so whole-dataset search, value shaping and the alias
fallback are covered without an instance. Real SQL execution must be validated on
the DSS instance.

Run from the repo root:
    python3 -m unittest discover -s dataiku-agents/tests -v
"""

import importlib.util
import os
import sys
import types
import unittest


def _install_stubs():
    if "dataiku" not in sys.modules:
        dataiku_mod = types.ModuleType("dataiku")
        dataiku_mod.api_client = lambda: None
        dataiku_mod.Dataset = lambda *a, **k: None
        dataiku_mod.SQLExecutor2 = lambda *a, **k: None
        sys.modules["dataiku"] = dataiku_mod
    else:
        dataiku_mod = sys.modules["dataiku"]

    if "dataiku.llm" not in sys.modules:
        llm_pkg = types.ModuleType("dataiku.llm")
        sys.modules["dataiku.llm"] = llm_pkg
        dataiku_mod.llm = llm_pkg
    else:
        llm_pkg = sys.modules["dataiku.llm"]

    if "dataiku.llm.agent_tools" not in sys.modules:
        agent_tools = types.ModuleType("dataiku.llm.agent_tools")

        class BaseAgentTool(object):
            pass

        agent_tools.BaseAgentTool = BaseAgentTool
        llm_pkg.agent_tools = agent_tools
        sys.modules["dataiku.llm.agent_tools"] = agent_tools


_install_stubs()

_TOOL_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "tools", "attribute_lookup_tool.py"))
_SPEC = importlib.util.spec_from_file_location("attribute_lookup_under_test",
                                               _TOOL_PATH)
al = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(al)


# --------------------------------------------------------------------------- #
# Fixtures + a DSS-free tool subclass
# --------------------------------------------------------------------------- #
ALL_COLS = ["diamond_id", "Account_name", "carrier_code", "account_manager",
            "sales_zone", "amount_eur"]
TEXT_COLS = ["diamond_id", "Account_name", "carrier_code", "account_manager",
             "sales_zone"]   # amount_eur is numeric -> not searched


def _cat_row(col, val, **kw):
    return {"search_domain": kw.get("search_domain", "alias"),
            "source_column": kw.get("source_column", col),
            "target_column": col, "target_value": val,
            "display_value": kw.get("display_value", val),
            "normalized_value": kw.get("normalized_value", al.norm(val)),
            "frequency": kw.get("frequency", 100),
            "is_alias": kw.get("is_alias", 1)}


class FakeTool(al.MyAgentTool):
    """fact_rows = rows the whole-dataset search 'matches'; alias_rows = catalog
    rows the fallback 'reads'. no_catalog makes the catalog read raise."""

    def __init__(self, fact_rows=None, alias_rows=None, all_columns=None,
                 text_columns=None, no_catalog=False):
        super(FakeTool, self).__init__()
        self._fact_rows = fact_rows if fact_rows is not None else []
        self._alias_rows = alias_rows or []
        self._all = all_columns if all_columns is not None else list(ALL_COLS)
        self._text = text_columns if text_columns is not None else list(TEXT_COLS)
        self._no_catalog = no_catalog
        self.sql_log = []

    def _get_table(self, dataset_name):
        return '"public"."%s"' % dataset_name

    def _live_columns_typed(self, dataset_name):
        return [(c, "string" if c in self._text else "double") for c in self._all]

    def _run_sql(self, dataset_name, sql, max_rows=al.SEARCH_SAMPLE_ROWS):
        self.sql_log.append((dataset_name, sql))
        if dataset_name == al.FACT_DATASET:
            return list(self._all), list(self._fact_rows)
        if self._no_catalog:
            raise RuntimeError("no catalog dataset")
        cols = ["search_domain", "source_column", "target_column", "target_value",
                "display_value", "normalized_value", "frequency", "is_alias"]
        return cols, list(self._alias_rows)


def invoke(tool, entity, attributes=None):
    payload = {"entity": entity}
    if attributes is not None:
        payload["attributes"] = attributes
    return tool.invoke({"input": payload}, trace=None)["output"]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
class TestNorm(unittest.TestCase):
    def test_norm_strips_accents_punctuation(self):
        self.assertEqual(al.norm("Algérie Télécom"), "algerie telecom")
        self.assertEqual(al.norm("AT&T, Inc."), "at t inc")

    def test_search_value_strips_accents_keeps_shape(self):
        self.assertEqual(al.search_value("Téléçom"), "telecom")
        self.assertEqual(al.search_value("Blanchard"), "blanchard")

    def test_none_empty(self):
        self.assertEqual(al.norm(None), "")
        self.assertEqual(al.search_value(None), "")


class TestAttributeMatching(unittest.TestCase):
    def test_spelling_casing_underscores_all_resolve(self):
        for raw in ("account manager", "Account_Manager", "ACCOUNT MANAGER",
                    "accountmanager"):
            self.assertEqual(al.match_attribute_column(raw, ALL_COLS),
                             "account_manager")

    def test_unknown_returns_none(self):
        self.assertIsNone(al.match_attribute_column("revenue forecast", ALL_COLS))

    def test_map_attributes_dedup_unknown(self):
        resolved, unknown = al.map_attributes(
            ["account manager", "Account_Manager", "wat", "sales zone"], ALL_COLS)
        self.assertEqual(resolved, ["account_manager", "sales_zone"])
        self.assertEqual(unknown, ["wat"])


class TestQuoting(unittest.TestCase):
    def test_quote_literal_escapes(self):
        self.assertEqual(al.quote_literal("O'Hara"), "'O''Hara'")

    def test_quote_ident_escapes(self):
        self.assertEqual(al.quote_ident('we"ird'), '"we""ird"')

    def test_like_escape(self):
        self.assertEqual(al.like_escape("a%b_c\\d"), "a\\%b\\_c\\\\d")


class TestSearchSql(unittest.TestCase):
    def test_or_ilike_over_text_columns(self):
        sql = al.build_search_sql('"public"."F"',
                                  ["account_manager", "Account_name"], "blanchard")
        self.assertIn('"account_manager" ILIKE \'%blanchard%\'', sql)
        self.assertIn('"Account_name" ILIKE \'%blanchard%\'', sql)
        self.assertIn(" OR ", sql)
        self.assertIn("LIMIT %d" % al.SEARCH_SAMPLE_ROWS, sql)

    def test_accent_insensitive_needle(self):
        sql = al.build_search_sql('"public"."F"', ["Account_name"], "Télécom")
        self.assertIn("'%telecom%'", sql)

    def test_needle_escaped(self):
        sql = al.build_search_sql('"public"."F"', ["c"], "a%b")
        self.assertIn("'%a\\%b%' ESCAPE", sql)


class TestSummarize(unittest.TestCase):
    def test_single_value_scalar(self):
        rows = [{"account_manager": "Jane"}, {"account_manager": "Jane"}]
        self.assertEqual(al.summarize_values(["account_manager"], rows),
                         {"account_manager": "Jane"})

    def test_multiple_values_list(self):
        rows = [{"sales_zone": "Africa"}, {"sales_zone": "Europe"}]
        self.assertEqual(al.summarize_values(["sales_zone"], rows),
                         {"sales_zone": ["Africa", "Europe"]})

    def test_cap_and_truncation_marker(self):
        rows = [{"a": str(i)} for i in range(al.DISTINCT_PER_COLUMN + 5)]
        out = al.summarize_values(["a"], rows)
        self.assertEqual(len(out["a"]), al.DISTINCT_PER_COLUMN + 1)
        self.assertEqual(out["a"][-1], "...")

    def test_nulls_skipped(self):
        rows = [{"a": None, "b": ""}, {"a": "x", "b": ""}]
        self.assertEqual(al.summarize_values(["a", "b"], rows), {"a": "x"})

    def test_keep_restricts(self):
        rows = [{"a": "1", "b": "2"}]
        self.assertEqual(al.summarize_values(["a", "b"], rows, keep=["a"]),
                         {"a": "1"})


class TestAliasSuggestions(unittest.TestCase):
    def test_returns_alias_rows(self):
        rows = [_cat_row("distribution_type", "Indirect_distribution/Resseler",
                         display_value="Indirect distribution",
                         normalized_value="indirect")]
        sugg = al.alias_suggestions(rows, "indirect")
        self.assertEqual(len(sugg), 1)
        self.assertEqual(sugg[0]["target_value"], "Indirect_distribution/Resseler")

    def test_ignores_non_alias(self):
        rows = [_cat_row("diamond_id", "AT001", is_alias=0)]
        self.assertEqual(al.alias_suggestions(rows, "x"), [])

    def test_dedup_by_display(self):
        rows = [_cat_row("Product", "X", display_value="Roaming Hub",
                         normalized_value="roaming hub"),
                _cat_row("Product", "X", display_value="Roaming Hub",
                         normalized_value="open roaming hub")]
        self.assertEqual(len(al.alias_suggestions(rows, "roaming hub")), 1)


# --------------------------------------------------------------------------- #
# Full invoke flow
# --------------------------------------------------------------------------- #
class TestInvoke(unittest.TestCase):
    # The whole-dataset search 'matched' these rows (e.g. on account_manager).
    BLANCHARD = [
        {"diamond_id": "AT001", "Account_name": "ALGERIE TELECOM",
         "carrier_code": "DZ1", "account_manager": "jean.blanchard@x.com",
         "sales_zone": "Africa", "amount_eur": "100"},
        {"diamond_id": "MA009", "Account_name": "MAROC TELECOM",
         "carrier_code": "MA1", "account_manager": "jean.blanchard@x.com",
         "sales_zone": "Africa", "amount_eur": "250"},
    ]

    def test_search_returns_matching_values(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard")
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["attributes"]["account_manager"],
                         "jean.blanchard@x.com")          # constant -> scalar
        self.assertEqual(out["attributes"]["sales_zone"], "Africa")
        self.assertEqual(sorted(out["attributes"]["Account_name"]),
                         ["ALGERIE TELECOM", "MAROC TELECOM"])   # several -> list

    def test_search_only_hits_text_columns(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        invoke(tool, "blanchard")
        fact_sql = [s for (d, s) in tool.sql_log if d == al.FACT_DATASET][0]
        self.assertIn('"account_manager" ILIKE', fact_sql)
        self.assertNotIn("amount_eur", fact_sql)   # numeric column not searched

    def test_requested_attribute_restricts(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard", ["account manager"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["attributes"], {"account_manager": "jean.blanchard@x.com"})

    def test_attribute_spelling_does_not_break(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard", ["Account_Manager"])
        self.assertIn("account_manager", out["attributes"])

    def test_no_match_offers_alias_suggestions(self):
        tool = FakeTool(fact_rows=[], alias_rows=[
            _cat_row("distribution_type", "Indirect_distribution/Resseler",
                     display_value="Indirect distribution",
                     normalized_value="indirect")])
        out = invoke(tool, "indirect")
        self.assertEqual(out["status"], "entity_suggestions")
        self.assertEqual(out["candidates"][0]["value"],
                         "Indirect_distribution/Resseler")

    def test_no_match_no_catalog_is_not_found(self):
        tool = FakeTool(fact_rows=[], no_catalog=True)
        out = invoke(tool, "zzz nothing", )
        self.assertEqual(out["status"], "entity_not_found")

    def test_attribute_unknown_when_requested(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard", ["gross margin"])
        self.assertEqual(out["status"], "attribute_unknown")
        self.assertIn("gross margin", out["attributes_unknown"])

    def test_bad_input_when_term_missing(self):
        self.assertEqual(invoke(FakeTool(), "")["status"], "bad_input")

    def test_output_has_sources(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        full = tool.invoke({"input": {"entity": "blanchard"}}, trace=None)
        self.assertEqual(full["sources"][0]["id"], al.FACT_DATASET)


if __name__ == "__main__":
    unittest.main()
