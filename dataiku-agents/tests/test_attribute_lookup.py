"""DSS-free unit tests for the attribute_lookup Custom Python agent tool
(``dataiku-agents/tools/attribute_lookup_tool.py``).

``dataiku`` and ``dataiku.llm.agent_tools`` are stubbed BEFORE the tool file is
loaded via importlib. Pure helpers (norm, attribute mapping, SQL builders, entity
picking) are tested directly. The full ``invoke`` flow is tested with a tool
subclass whose ``_run_sql`` / ``_live_columns`` / ``_get_table`` are replaced by
fixtures - so resolution, attribute reading and output shaping are covered
without an instance. Real SQL execution must be validated on the DSS instance.

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
FACT_COLUMNS = ["diamond_id", "Account_name", "carrier_code", "Parent_Group",
                "account_manager", "sales_zone"]


def _cat_row(col, val, **kw):
    row = {"search_domain": kw.get("search_domain", "account"),
           "source_column": kw.get("source_column", col),
           "target_column": col, "target_value": val,
           "display_value": kw.get("display_value", val),
           "normalized_value": kw.get("normalized_value", al.norm(val)),
           "frequency": kw.get("frequency", 100),
           "is_alias": kw.get("is_alias", 0)}
    return row


class FakeTool(al.MyAgentTool):
    """Replaces the three DSS-touching methods with in-memory fixtures.

    exact_rows / fuzzy_rows : catalog rows the resolver 'reads'.
    fact_rows               : list-of-dict the attribute SELECT 'returns'.
    """

    def __init__(self, exact_rows=None, fuzzy_rows=None, fact_rows=None,
                 live_columns=None):
        super(FakeTool, self).__init__()
        self._exact_rows = exact_rows or []
        self._fuzzy_rows = fuzzy_rows or []
        self._fact_rows = fact_rows if fact_rows is not None else []
        self._live = live_columns if live_columns is not None else list(FACT_COLUMNS)
        self.sql_log = []

    def _get_table(self, dataset_name):
        return '"public"."%s"' % dataset_name

    def _live_columns(self, dataset_name):
        return list(self._live)

    def _run_sql(self, dataset_name, sql, max_rows=al.MAX_RESULT_ROWS):
        self.sql_log.append((dataset_name, sql))
        if dataset_name == al.CATALOG_DATASET:
            rows = self._fuzzy_rows if "LIKE" in sql else self._exact_rows
            cols = (["search_domain", "source_column", "target_column",
                     "target_value", "display_value", "normalized_value",
                     "frequency", "is_alias"] if rows else [])
            return cols, list(rows)
        # fact table read
        cols = list(self._fact_rows[0].keys()) if self._fact_rows else []
        return cols, list(self._fact_rows)


def invoke(tool, entity, attributes):
    return tool.invoke({"input": {"entity": entity, "attributes": attributes}},
                       trace=None)["output"]


# --------------------------------------------------------------------------- #
# Pure helpers
# --------------------------------------------------------------------------- #
class TestNorm(unittest.TestCase):
    def test_accent_and_punctuation_stripped(self):
        self.assertEqual(al.norm("Algérie Télécom"), "algerie telecom")
        self.assertEqual(al.norm("AT&T, Inc."), "at t inc")
        self.assertEqual(al.norm("  Multiple   spaces "), "multiple spaces")

    def test_none_and_empty(self):
        self.assertEqual(al.norm(None), "")
        self.assertEqual(al.norm("   "), "")


class TestAttributeMatching(unittest.TestCase):
    def test_spelling_casing_underscores_all_resolve(self):
        for raw in ("account manager", "Account_Manager", "ACCOUNT MANAGER",
                    "accountmanager"):
            self.assertEqual(al.match_attribute_column(raw, FACT_COLUMNS),
                             "account_manager")

    def test_unknown_returns_none(self):
        self.assertIsNone(al.match_attribute_column("revenue", FACT_COLUMNS))
        self.assertIsNone(al.match_attribute_column("", FACT_COLUMNS))

    def test_map_attributes_dedup_and_unknown(self):
        resolved, unknown = al.map_attributes(
            ["account manager", "Account_Manager", "wat", "sales zone"],
            FACT_COLUMNS)
        self.assertEqual(resolved, ["account_manager", "sales_zone"])
        self.assertEqual(unknown, ["wat"])

    def test_map_attributes_cap(self):
        resolved, _ = al.map_attributes(["account manager"] * 20, FACT_COLUMNS)
        self.assertEqual(resolved, ["account_manager"])


class TestQuoting(unittest.TestCase):
    def test_quote_literal_escapes(self):
        self.assertEqual(al.quote_literal("O'Hara"), "'O''Hara'")

    def test_quote_ident_escapes(self):
        self.assertEqual(al.quote_ident('we"ird'), '"we""ird"')

    def test_like_escape(self):
        self.assertEqual(al.like_escape("a%b_c\\d"), "a\\%b\\_c\\\\d")


class TestSqlBuilders(unittest.TestCase):
    def test_resolve_exact_sql(self):
        sql = al.build_resolve_sql('"public"."CAT"', "algerie telecom", fuzzy=False)
        self.assertIn("normalized_value = 'algerie telecom'", sql)
        self.assertIn("search_domain IN ('account', 'account_group', 'alias')", sql)
        self.assertNotIn("LIKE", sql)

    def test_resolve_fuzzy_sql_escapes_like(self):
        sql = al.build_resolve_sql('"public"."CAT"', "a%b", fuzzy=True)
        self.assertIn("LIKE '%a\\%b%' ESCAPE", sql)

    def test_attribute_sql_quotes_idents_and_value(self):
        sql = al.build_attribute_sql('"public"."F"', "diamond_id", "AT'1",
                                     ["account_manager", "sales_zone"])
        self.assertIn('SELECT DISTINCT "account_manager", "sales_zone"', sql)
        self.assertIn('WHERE "diamond_id" = \'AT\'\'1\'', sql)
        self.assertIn("LIMIT %d" % al.MAX_RESULT_ROWS, sql)


class TestEntityPicking(unittest.TestCase):
    def test_single_target_resolves(self):
        rows = [_cat_row("diamond_id", "AT001"),
                _cat_row("Account_name", "Algerie Telecom",
                         display_value="Algerie Telecom")]
        # Same entity, different columns but distinct targets -> priority decides.
        status, row = al.pick_exact_entity(rows)
        self.assertEqual(status, "resolved")
        self.assertEqual(row["target_column"], "diamond_id")

    def test_collapses_identical_target(self):
        rows = [_cat_row("diamond_id", "AT001", frequency=5),
                _cat_row("diamond_id", "AT001", frequency=900)]
        status, row = al.pick_exact_entity(rows)
        self.assertEqual(status, "resolved")
        self.assertEqual(row["target_value"], "AT001")

    def test_ambiguous_same_priority_distinct_entities(self):
        rows = [_cat_row("diamond_id", "AT001", display_value="Telecom A"),
                _cat_row("diamond_id", "ZZ999", display_value="Telecom Z")]
        status, cands = al.pick_exact_entity(rows)
        self.assertEqual(status, "ambiguous")
        self.assertEqual(len(cands), 2)

    def test_empty(self):
        self.assertEqual(al.pick_exact_entity([]), ("none", None))

    def test_fuzzy_accepts_clear_winner(self):
        rows = [_cat_row("diamond_id", "AT001",
                         normalized_value="algerie telecom")]
        status, row = al.pick_fuzzy_entity("algerie telecomm", rows)
        self.assertEqual(status, "resolved")
        self.assertEqual(row["target_value"], "AT001")

    def test_fuzzy_rejects_below_floor(self):
        rows = [_cat_row("diamond_id", "X", normalized_value="completely other")]
        status, _ = al.pick_fuzzy_entity("algerie telecom", rows)
        self.assertEqual(status, "none")

    def test_fuzzy_rejects_tie(self):
        rows = [_cat_row("diamond_id", "A", normalized_value="orange mali"),
                _cat_row("diamond_id", "B", normalized_value="orange malo")]
        # 'orange mal' is equidistant from both -> ambiguous -> rejected
        status, _ = al.pick_fuzzy_entity("orange mal", rows)
        self.assertEqual(status, "none")


# --------------------------------------------------------------------------- #
# Full invoke flow
# --------------------------------------------------------------------------- #
class TestInvoke(unittest.TestCase):
    def test_happy_path_account_manager(self):
        tool = FakeTool(
            exact_rows=[_cat_row("diamond_id", "AT001",
                                 display_value="Algerie Telecom SA",
                                 normalized_value="algerie telecom")],
            fact_rows=[{"account_manager": "Jane Doe"}])
        out = invoke(tool, "Algérie Télécom", ["account manager"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["entity"]["value"], "AT001")
        self.assertEqual(out["entity"]["display"], "Algerie Telecom SA")
        self.assertEqual(out["attributes_resolved"], ["account_manager"])
        self.assertEqual(out["rows"], [["Jane Doe"]])
        self.assertIn('"account_manager"', out["sql"])
        self.assertIn("'AT001'", out["sql"])

    def test_spelling_of_attribute_does_not_break(self):
        tool = FakeTool(
            exact_rows=[_cat_row("diamond_id", "AT001",
                                 normalized_value="algerie telecom")],
            fact_rows=[{"account_manager": "Jane Doe"}])
        out = invoke(tool, "Algerie Telecom", ["Account_Manager"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["attributes_resolved"], ["account_manager"])

    def test_entity_not_found_falls_to_fuzzy_then_gives_up(self):
        tool = FakeTool(exact_rows=[], fuzzy_rows=[])
        out = invoke(tool, "Nonexistent Co", ["account manager"])
        self.assertEqual(out["status"], "entity_not_found")
        # two catalog reads were attempted (exact then fuzzy)
        cat_reads = [s for (d, s) in tool.sql_log if d == al.CATALOG_DATASET]
        self.assertEqual(len(cat_reads), 2)

    def test_fuzzy_resolution(self):
        tool = FakeTool(
            exact_rows=[],
            fuzzy_rows=[_cat_row("diamond_id", "AT001",
                                 normalized_value="algerie telecom")],
            fact_rows=[{"account_manager": "Jane Doe"}])
        out = invoke(tool, "algerie telcom", ["account manager"])
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["entity"]["value"], "AT001")

    def test_ambiguous_entity_asks(self):
        tool = FakeTool(exact_rows=[
            _cat_row("diamond_id", "AT001", display_value="Telecom A"),
            _cat_row("diamond_id", "ZZ999", display_value="Telecom Z")])
        out = invoke(tool, "Telecom", ["account manager"])
        self.assertEqual(out["status"], "entity_ambiguous")
        self.assertEqual(len(out["candidates"]), 2)

    def test_attribute_unknown(self):
        tool = FakeTool(exact_rows=[_cat_row("diamond_id", "AT001")])
        out = invoke(tool, "Algerie Telecom", ["gross margin"])
        self.assertEqual(out["status"], "attribute_unknown")
        self.assertIn("gross margin", out["attributes_unknown"])

    def test_bad_input(self):
        tool = FakeTool()
        self.assertEqual(invoke(tool, "", ["account manager"])["status"],
                         "bad_input")
        self.assertEqual(invoke(tool, "X", [])["status"], "bad_input")

    def test_resolved_column_absent_from_fact_schema(self):
        # Catalog points at a column the live fact no longer has.
        tool = FakeTool(
            exact_rows=[_cat_row("legacy_id", "AT001",
                                 normalized_value="algerie telecom")],
            live_columns=["diamond_id", "account_manager"])
        out = invoke(tool, "Algerie Telecom", ["account manager"])
        self.assertEqual(out["status"], "entity_not_found")

    def test_no_value(self):
        tool = FakeTool(
            exact_rows=[_cat_row("diamond_id", "AT001",
                                 normalized_value="algerie telecom")],
            fact_rows=[])
        out = invoke(tool, "Algerie Telecom", ["account manager"])
        self.assertEqual(out["status"], "no_value")

    def test_output_has_sources(self):
        tool = FakeTool(
            exact_rows=[_cat_row("diamond_id", "AT001",
                                 normalized_value="algerie telecom")],
            fact_rows=[{"account_manager": "Jane Doe"}])
        full = tool.invoke({"input": {"entity": "Algerie Telecom",
                                      "attributes": ["account manager"]}},
                           trace=None)
        self.assertEqual(full["sources"][0]["id"], al.FACT_DATASET)


if __name__ == "__main__":
    unittest.main()
