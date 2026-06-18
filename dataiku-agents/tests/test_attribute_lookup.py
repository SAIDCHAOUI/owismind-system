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
        # The catalog dataset feeds the alias fallback; ANY other dataset name is
        # treated as a fact table (so multi-table routing can be exercised).
        if dataset_name == al.CATALOG_DATASET:
            if self._no_catalog:
                raise RuntimeError("no catalog dataset")
            cols = ["search_domain", "source_column", "target_column", "target_value",
                    "display_value", "normalized_value", "frequency", "is_alias"]
            return cols, list(self._alias_rows)
        return list(self._all), list(self._fact_rows)


def invoke(tool, entity, attributes=None, dataset=None, catalog=None):
    payload = {"entity": entity}
    if attributes is not None:
        payload["attributes"] = attributes
    if dataset is not None:
        payload["dataset"] = dataset
    if catalog is not None:
        payload["catalog"] = catalog
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

    def test_search_value_symmetric_fold_keeps_out_of_map(self):
        # In-map accents fold; OUT-of-map glyphs are KEPT - exactly like the
        # column-side translate(), so needle and column never de-sync (the
        # old NFKD needle dropped them, breaking the match).
        self.assertEqual(al.search_value("Telenør"), "telenør")   # o-slash kept
        # Folding the needle with the SAME map as unaccent_lower_sql means an
        # out-of-map char that survives on the needle also survives in SQL.
        self.assertEqual("Telenør".lower().translate(al._NEEDLE_TRANSLATION),
                         al.search_value("Telenør"))

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
    def test_single_ilike_over_concat_of_text_columns(self):
        sql = al.build_search_sql('"public"."F"',
                                  ["account_manager", "Account_name"], "blanchard")
        self.assertIn("'%blanchard%'", sql)
        self.assertIn('"account_manager"', sql)
        self.assertIn('"Account_name"', sql)
        self.assertIn("concat_ws(' ', ", sql)        # one concatenation...
        self.assertEqual(sql.count("ILIKE"), 1)       # ...so ONE ILIKE, not one per column
        self.assertNotIn(" OR ", sql)                 # readable, no 18-way OR
        self.assertIn("LIMIT %d" % al.SEARCH_SAMPLE_ROWS, sql)

    def test_accent_insensitive_needle(self):
        sql = al.build_search_sql('"public"."F"', ["Account_name"], "Télécom")
        self.assertIn("'%telecom%'", sql)

    def test_column_side_accent_folded(self):
        # The COLUMN side must be accent-folded, or a stored accented value
        # ('Societe Generale' with accents) is invisible to a folded needle.
        sql = al.build_search_sql('"public"."F"', ["Account_name"], "telecom")
        self.assertIn("translate(lower(", sql)

    def test_accent_map_equal_length(self):
        # translate() maps char-for-char; unequal lengths silently drop chars.
        self.assertEqual(len(al._ACCENTS_FROM), len(al._ACCENTS_TO))

    def test_accent_fold_sql_shape(self):
        expr = al.accent_fold_sql('"col"')
        self.assertIn('"col"', expr)
        self.assertTrue(expr.startswith("translate(lower(CAST("))

    def test_needle_escaped(self):
        sql = al.build_search_sql('"public"."F"', ["c"], "a%b")
        self.assertIn("'%a\\%b%' ESCAPE", sql)


class TestFindMatches(unittest.TestCase):
    def test_reports_column_and_exact_value(self):
        rows = [{"account_manager": "jean.blanchard@x.com",
                 "Account_name": "ALGERIE TELECOM"}]
        out = al.find_matches(["account_manager", "Account_name"], rows, "blanchard")
        self.assertEqual(out, [{"column": "account_manager",
                                "values": ["jean.blanchard@x.com"]}])

    def test_accent_insensitive(self):
        rows = [{"Account_name": "ALGERIE TELECOM"}]
        out = al.find_matches(["Account_name"], rows, "Algérie Télécom")
        self.assertEqual(out[0]["column"], "Account_name")

    def test_distinct_values_across_rows(self):
        rows = [{"account_manager": "a.blanchard@x.com"},
                {"account_manager": "b.blanchard@x.com"}]
        out = al.find_matches(["account_manager"], rows, "blanchard")
        self.assertEqual(sorted(out[0]["values"]),
                         ["a.blanchard@x.com", "b.blanchard@x.com"])

    def test_no_hit_returns_empty(self):
        rows = [{"Account_name": "ORANGE"}]
        self.assertEqual(al.find_matches(["Account_name"], rows, "blanchard"), [])


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

    def test_found_in_reports_where_and_value(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard")
        self.assertEqual(out["status"], "found")
        self.assertEqual(out["found_in"],
                         [{"column": "account_manager",
                           "values": ["jean.blanchard@x.com"]}])
        self.assertNotIn("attributes", out)   # nothing extra unless asked

    def test_search_only_hits_text_columns(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        invoke(tool, "blanchard")
        fact_sql = [s for (d, s) in tool.sql_log if d == al.FACT_DATASET][0]
        self.assertIn('"account_manager"', fact_sql)
        self.assertIn("ILIKE", fact_sql)
        self.assertNotIn("amount_eur", fact_sql)   # numeric column not searched

    def test_requested_attributes_return_other_columns(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard", ["sales zone"])
        self.assertEqual(out["status"], "found")
        self.assertEqual(out["attributes"], {"sales_zone": "Africa"})
        self.assertEqual(out["found_in"][0]["column"], "account_manager")

    def test_attribute_spelling_does_not_break(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard", ["Sales_Zone"])
        self.assertIn("sales_zone", out["attributes"])

    def test_no_match_offers_alias_suggestions(self):
        tool = FakeTool(fact_rows=[], alias_rows=[
            _cat_row("distribution_type", "Indirect_distribution/Resseler",
                     display_value="Indirect distribution",
                     normalized_value="indirect")])
        out = invoke(tool, "indirect")
        self.assertEqual(out["status"], "suggestions")
        self.assertEqual(out["candidates"][0]["value"],
                         "Indirect_distribution/Resseler")

    def test_no_match_no_catalog_is_not_found(self):
        tool = FakeTool(fact_rows=[], no_catalog=True)
        out = invoke(tool, "zzz nothing")
        self.assertEqual(out["status"], "not_found")

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

    def test_found_carries_flags(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        out = invoke(tool, "blanchard")
        # 2 fixture rows < SEARCH_SAMPLE_ROWS, term only in account_manager.
        self.assertFalse(out["rows_capped"])
        self.assertFalse(out["multi_column"])

    def test_rows_capped_flag_when_limit_hit(self):
        many = [{"Account_name": "ALGERIE TELECOM %d" % i, "amount_eur": "1"}
                for i in range(al.SEARCH_SAMPLE_ROWS)]
        tool = FakeTool(fact_rows=many)
        out = invoke(tool, "telecom")
        self.assertTrue(out["rows_capped"])

    def test_multi_column_flag_when_term_in_two_columns(self):
        rows = [{"Account_name": "BLANCHARD GROUP",
                 "account_manager": "p.blanchard@x.com", "amount_eur": "1"}]
        tool = FakeTool(fact_rows=rows)
        out = invoke(tool, "blanchard")
        self.assertTrue(out["multi_column"])
        self.assertEqual(len(out["found_in"]), 2)

    def test_alias_fallback_skipped_when_attributes_requested(self):
        # An attribute read that misses wants a clean not_found, NOT alias guesses
        # (and must not pay the extra catalog round-trips).
        tool = FakeTool(fact_rows=[], alias_rows=[
            _cat_row("distribution_type", "Indirect_distribution/Resseler",
                     display_value="Indirect distribution",
                     normalized_value="indirect")])
        out = invoke(tool, "indirect", ["sales zone"])
        self.assertEqual(out["status"], "not_found")
        self.assertFalse(any(d == al.CATALOG_DATASET for (d, _) in tool.sql_log))

    def test_short_needle_skips_broad_scan(self):
        tool = FakeTool(fact_rows=self.BLANCHARD, no_catalog=True)
        out = invoke(tool, "a")     # 1-char needle
        self.assertEqual(out["status"], "not_found")
        self.assertFalse(any(d == al.FACT_DATASET for (d, _) in tool.sql_log))

    def test_cache_avoids_second_sql(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        invoke(tool, "blanchard")
        n_after_first = len(tool.sql_log)
        out = invoke(tool, "Blanchard")   # same needle, different casing
        self.assertEqual(out["status"], "found")
        self.assertEqual(len(tool.sql_log), n_after_first)   # served from cache

    def test_softer_not_found_message_no_absolute_claim(self):
        tool = FakeTool(fact_rows=[], no_catalog=True)
        out = invoke(tool, "zzz nothing")
        self.assertEqual(out["status"], "not_found")
        self.assertNotIn("was not found in the data", out["message"])

    def test_rows_without_reconfirm_is_not_found_not_found_status(self):
        # SQL matched rows (FakeTool returns them verbatim) but the term does not
        # re-confirm in any value and no attribute was asked -> a 'found' with an
        # empty found_in would be a lie; it must degrade to not_found.
        tool = FakeTool(fact_rows=[{"Account_name": "ORANGE", "amount_eur": "1"}],
                        no_catalog=True)
        out = invoke(tool, "ghost")
        self.assertEqual(out["status"], "not_found")

    def test_attributes_only_answer_still_found(self):
        # found_in can be empty while a requested attribute resolved -> still a
        # valid 'found' (attributes-only), not a not_found.
        tool = FakeTool(fact_rows=[{"Account_name": "ORANGE", "sales_zone": "Europe",
                                    "amount_eur": "1"}])
        out = invoke(tool, "orange", ["sales zone"])
        self.assertEqual(out["status"], "found")
        self.assertEqual(out["attributes"], {"sales_zone": "Europe"})

    def test_routes_to_caller_supplied_dataset(self):
        # Multi-table: the orchestrator passes a whitelisted dataset; the tool
        # searches THAT table (not the hardcoded default) and sources it.
        tool = FakeTool(fact_rows=self.BLANCHARD)
        full = tool.invoke({"input": {"entity": "blanchard",
                                      "dataset": "TICKETS_FACT"}}, trace=None)
        out = full["output"]
        self.assertEqual(out["status"], "found")
        self.assertTrue(any(d == "TICKETS_FACT" for (d, _) in tool.sql_log))
        self.assertFalse(any(d == al.FACT_DATASET for (d, _) in tool.sql_log))
        self.assertEqual(full["sources"][0]["id"], "TICKETS_FACT")

    def test_default_dataset_when_not_supplied(self):
        tool = FakeTool(fact_rows=self.BLANCHARD)
        invoke(tool, "blanchard")
        self.assertTrue(any(d == al.FACT_DATASET for (d, _) in tool.sql_log))


if __name__ == "__main__":
    unittest.main()
