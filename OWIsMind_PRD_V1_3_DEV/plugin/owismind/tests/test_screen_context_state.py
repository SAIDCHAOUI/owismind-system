# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_screen_context_state.py
"""SCREEN CONTEXT -> AGENT feature (backend half).

Three pure/near-pure surfaces:
  - ``context.sanitize_source_state`` : whitelist + bound the untrusted source_state
    (never raises, None when empty/incomplete);
  - ``context.build_screen_state``    : render the [ON SCREEN NOW] block, now with an
    optional SOURCE-DATA VIEW section (conditional lines, fn labels, budget ladder);
  - ``routes._sanitize_screen_context``: retro-compatible request gate (open-only,
    source_state-only, both, neither -> None).

``context`` is pure (no dataiku); ``routes`` needs the same dataiku + flask stubs the
existing route tests install (see test_impersonation.py).
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents import context  # noqa: E402


# --- dataiku + flask stubs so owismind.api.routes imports (route-gate tests) ----
def _ensure_dataiku_stub():
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
    if not hasattr(dk, "api_client"):
        dk.api_client = lambda: None
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = lambda constant, dialect=None: "'" + str(constant) + "'"
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


def _ensure_flask_stub():
    flask = sys.modules.get("flask")
    if flask is not None and hasattr(flask, "_OWI_STUB"):
        return
    flask = types.ModuleType("flask")
    flask._OWI_STUB = True

    class Blueprint(object):
        def __init__(self, name, import_name, url_prefix=None):
            self.name = name
            self.url_prefix = url_prefix

        def route(self, *_a, **_k):
            def _decorator(fn):
                return fn
            return _decorator

        def before_request(self, fn):
            return fn

        def after_request(self, fn):
            return fn

    flask.Blueprint = Blueprint
    flask.jsonify = lambda payload: payload
    flask.request = types.SimpleNamespace(headers={}, args={}, method="GET")
    flask.g = types.SimpleNamespace()
    sys.modules["flask"] = flask


_ensure_dataiku_stub()
_ensure_flask_stub()

from owismind.api import routes  # noqa: E402


def _valid_ss(**over):
    """A minimally-meaningful source_state (one filter), overridable."""
    base = {
        "surface": "explorer",
        "dataset": "DRIVE_Revenues",
        "filters": [{"column": "year", "op": "=", "values": ["2025"]}],
    }
    base.update(over)
    return base


# --- sanitize_source_state ----------------------------------------------------
class SanitizeSourceStateTests(unittest.TestCase):
    def test_none_on_non_dict_and_garbage(self):
        for bad in (None, 42, "x", [], object(), True):
            self.assertIsNone(context.sanitize_source_state(bad))

    def test_none_when_surface_missing_or_invalid(self):
        self.assertIsNone(context.sanitize_source_state(
            {"dataset": "D", "filters": [{"column": "c", "op": "=", "values": ["v"]}]}))
        self.assertIsNone(context.sanitize_source_state(
            {"surface": "nope", "dataset": "D",
             "filters": [{"column": "c", "op": "=", "values": ["v"]}]}))

    def test_none_when_dataset_missing(self):
        self.assertIsNone(context.sanitize_source_state(
            {"surface": "explorer",
             "filters": [{"column": "c", "op": "=", "values": ["v"]}]}))
        self.assertIsNone(context.sanitize_source_state(
            {"surface": "explorer", "dataset": "",
             "filters": [{"column": "c", "op": "=", "values": ["v"]}]}))

    def test_none_when_no_meaningful_field(self):
        # surface + dataset + row_count + agent only -> not a shaped view.
        self.assertIsNone(context.sanitize_source_state(
            {"surface": "evidence", "dataset": "D", "row_count": 10, "agent": "Rev"}))

    def test_unknown_keys_dropped(self):
        ss = context.sanitize_source_state(_valid_ss(evil="DROP TABLE", secret={"a": 1}))
        self.assertNotIn("evil", ss)
        self.assertNotIn("secret", ss)
        self.assertEqual(set(ss), {"surface", "dataset", "filters"})

    def test_surface_and_dataset_kept_bounded(self):
        ss = context.sanitize_source_state(_valid_ss(surface="evidence", dataset="D" * 200))
        self.assertEqual(ss["surface"], "evidence")
        self.assertEqual(len(ss["dataset"]), context.SS_DATASET_CHARS)

    def test_agent_optional_and_bounded(self):
        ss = context.sanitize_source_state(_valid_ss(agent="Revenue expert " + "x" * 200))
        self.assertEqual(len(ss["agent"]), context.SS_AGENT_CHARS)
        ss2 = context.sanitize_source_state(_valid_ss(agent=""))
        self.assertNotIn("agent", ss2)

    def test_row_count_bool_rejected(self):
        ss = context.sanitize_source_state(_valid_ss(row_count=True))
        self.assertNotIn("row_count", ss)
        ss2 = context.sanitize_source_state(_valid_ss(row_count=False))
        self.assertNotIn("row_count", ss2)

    def test_row_count_int_coerced_and_bounded(self):
        self.assertEqual(context.sanitize_source_state(_valid_ss(row_count=42))["row_count"], 42)
        # numeric-ish inputs coerce to int.
        self.assertEqual(context.sanitize_source_state(_valid_ss(row_count=5.9))["row_count"], 5)
        self.assertEqual(context.sanitize_source_state(_valid_ss(row_count="7"))["row_count"], 7)
        # negatives and non-numeric are dropped.
        self.assertNotIn("row_count", context.sanitize_source_state(_valid_ss(row_count=-3)))
        self.assertNotIn("row_count", context.sanitize_source_state(_valid_ss(row_count="abc")))
        # magnitude capped.
        big = context.sanitize_source_state(_valid_ss(row_count=10 ** 30))["row_count"]
        self.assertEqual(big, context.SS_ROW_COUNT_MAX)

    def test_q_optional_bounded(self):
        ss = context.sanitize_source_state(
            {"surface": "explorer", "dataset": "D", "q": "orange " + "z" * 200})
        self.assertEqual(len(ss["q"]), context.SS_Q_CHARS)
        # q ALONE (no filters) is still a meaningful shaped view.
        self.assertEqual(ss["surface"], "explorer")

    def test_filters_invalid_op_dropped_valid_kept(self):
        ss = context.sanitize_source_state(_valid_ss(filters=[
            {"column": "a", "op": "LIKE", "values": ["x"]},      # invalid op -> dropped
            {"column": "", "op": "=", "values": ["x"]},          # empty col -> dropped
            {"column": "b", "op": "IN", "values": []},           # no values -> dropped
            {"column": "c", "op": "=", "values": ["ok"]},        # kept
        ]))
        self.assertEqual(len(ss["filters"]), 1)
        self.assertEqual(ss["filters"][0]["column"], "c")

    def test_filters_values_capped_and_more_kept(self):
        ss = context.sanitize_source_state(_valid_ss(filters=[
            {"column": "c", "op": "IN", "values": [str(i) for i in range(20)], "more": 15},
        ]))
        f = ss["filters"][0]
        self.assertEqual(len(f["values"]), context.SS_VALUES)
        self.assertEqual(f["more"], 15)

    def test_filters_count_capped(self):
        many = [{"column": "c%d" % i, "op": "=", "values": ["v"]} for i in range(20)]
        ss = context.sanitize_source_state(_valid_ss(filters=many))
        self.assertEqual(len(ss["filters"]), context.SS_FILTERS)

    def test_bracket_glyphs_and_newlines_stripped(self):
        ss = context.sanitize_source_state(_valid_ss(
            dataset="D⟦x⟧",
            q="a\nb\tc\rd",
            filters=[{"column": "c⟦", "op": "=", "values": ["v⟧\nw"]}]))
        self.assertNotIn("⟦", ss["dataset"])
        self.assertNotIn("⟧", ss["dataset"])
        self.assertEqual(ss["q"], "a b c d")
        self.assertNotIn("⟦", ss["filters"][0]["column"])
        self.assertNotIn("⟧", ss["filters"][0]["values"][0])
        self.assertNotIn("\n", ss["filters"][0]["values"][0])

    def test_drill_kept_and_capped(self):
        drill = [{"column": "c%d" % i, "value": "v"} for i in range(10)]
        ss = context.sanitize_source_state({"surface": "evidence", "dataset": "D", "drill": drill})
        self.assertEqual(len(ss["drill"]), context.SS_DRILL)
        self.assertEqual(ss["drill"][0], {"column": "c0", "value": "v"})

    def test_calc_invalid_fn_dropped(self):
        ss = context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "calc": {"column": "amount", "measures": [
                {"fn": "sum", "value": "100"},
                {"fn": "variance", "value": "9"},   # not whitelisted -> dropped
                {"fn": "median", "value": "12"},
            ]}})
        fns = [m["fn"] for m in ss["calc"]["measures"]]
        self.assertEqual(fns, ["sum", "median"])
        self.assertEqual(ss["calc"]["column"], "amount")

    def test_calc_dropped_when_no_valid_measure(self):
        ss = context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "calc": {"column": "amount", "measures": [{"fn": "nope", "value": "1"}]}})
        self.assertIsNone(ss)  # calc gone -> no meaningful field

    def test_analyze_full_shape(self):
        ss = context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "analyze": {
                "group": "carrier", "bucket": "month", "fn": "sum",
                "measure_column": "amount",
                "rows": [{"key": "2025-01", "value": "10"}, {"key": "2025-02", "value": "20"}],
                "total": "30", "truncated": True}})
        a = ss["analyze"]
        self.assertEqual(a["group"], "carrier")
        self.assertEqual(a["bucket"], "month")
        self.assertEqual(a["fn"], "sum")
        self.assertEqual(len(a["rows"]), 2)
        self.assertEqual(a["total"], "30")
        self.assertTrue(a["truncated"])

    def test_analyze_invalid_bucket_and_fn(self):
        # invalid fn -> whole analyze dropped -> no meaningful field -> None
        self.assertIsNone(context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "analyze": {"group": "g", "fn": "max", "rows": [{"key": "k", "value": "1"}]}}))
        # invalid bucket -> coerced to None, block kept.
        ss = context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "analyze": {"group": "g", "fn": "count", "bucket": "week",
                        "rows": [{"key": "k", "value": "1"}]}})
        self.assertIsNone(ss["analyze"]["bucket"])
        self.assertIsNone(ss["analyze"]["measure_column"])

    def test_analyze_dropped_when_no_rows(self):
        self.assertIsNone(context.sanitize_source_state({
            "surface": "explorer", "dataset": "D",
            "analyze": {"group": "g", "fn": "count", "rows": []}}))

    def test_never_raises_on_garbage_nested_types(self):
        garbage = {
            "surface": "explorer", "dataset": "D",
            "filters": "not-a-list",
            "drill": 5,
            "calc": [],
            "analyze": 7,
            "q": {"weird": 1},
        }
        # q is a dict -> str() of it, still truthy -> meaningful; must not raise.
        out = context.sanitize_source_state(garbage)
        self.assertIsNotNone(out)
        self.assertIn("q", out)


# --- build_screen_state rendering ---------------------------------------------
class BuildScreenStateSourceTests(unittest.TestCase):
    def test_empty_still_empty(self):
        self.assertEqual(context.build_screen_state([], source_state=None), "")
        self.assertEqual(context.build_screen_state(None), "")

    def test_source_only_renders_block(self):
        ss = _valid_ss(row_count=1234, q="orange")
        s = context.build_screen_state([], source_state=ss)
        self.assertTrue(s.startswith("\n\n[ON SCREEN NOW"))
        self.assertIn("SOURCE-DATA VIEW", s)
        self.assertIn('dataset "DRIVE_Revenues"', s)
        self.assertIn('year = "2025"', s)
        self.assertIn('search: "orange".', s)
        self.assertIn("rows matching (DB count): 1234.", s)
        self.assertIn("still call the specialist", s)  # firewall preserved

    def test_agent_label_rendered(self):
        s = context.build_screen_state([], source_state=_valid_ss(agent="Revenue expert"))
        self.assertIn('agent "Revenue expert"', s)

    def test_filter_in_with_more(self):
        ss = _valid_ss(filters=[
            {"column": "carrier", "op": "IN", "values": ["A", "B"], "more": 3}])
        s = context.build_screen_state([], source_state=ss)
        self.assertIn('carrier IN ("A", "B", +3 more).', s)

    def test_filter_between(self):
        ss = _valid_ss(filters=[
            {"column": "d", "op": "BETWEEN", "values": ["2025-01-01", "2025-12-31"]}])
        s = context.build_screen_state([], source_state=ss)
        self.assertIn("d BETWEEN 2025-01-01 AND 2025-12-31.", s)

    def test_drill_line(self):
        ss = {"surface": "evidence", "dataset": "D",
              "drill": [{"column": "carrier", "value": "Orange"},
                        {"column": "year", "value": "2025"}]}
        s = context.build_screen_state([], source_state=ss)
        self.assertIn('drill-down: carrier = "Orange", year = "2025".', s)

    def test_calc_fn_labels(self):
        ss = {"surface": "explorer", "dataset": "D",
              "calc": {"column": "amount_eur", "measures": [
                  {"fn": "sum", "value": "1 000"},
                  {"fn": "avg", "value": "50"},
                  {"fn": "median", "value": "40"},
                  {"fn": "min", "value": "1"},
                  {"fn": "max", "value": "99"},
                  {"fn": "count", "value": "20"},
                  {"fn": "count_distinct", "value": "7"}]}}
        s = context.build_screen_state([], source_state=ss)
        self.assertIn("computed figures on amount_eur over the FULL filtered set:", s)
        self.assertIn("Sum = 1 000", s)
        self.assertIn("Average = 50", s)
        self.assertIn("Median = 40", s)
        self.assertIn("Min = 1", s)
        self.assertIn("Max = 99", s)
        self.assertIn("Row count = 20", s)
        self.assertIn("Distinct values = 7", s)

    def test_breakdown_line_with_bucket_and_truncation(self):
        ss = {"surface": "explorer", "dataset": "D",
              "analyze": {"group": "carrier", "bucket": "month", "fn": "sum",
                          "measure_column": "amount",
                          "rows": [{"key": "2025-01", "value": "10"},
                                   {"key": "2025-02", "value": "20"}],
                          "total": "30", "truncated": True}}
        s = context.build_screen_state([], source_state=ss)
        self.assertIn("breakdown - Sum of amount by carrier (per month):", s)
        self.assertIn("2025-01 = 10; 2025-02 = 20", s)
        self.assertIn("[top 5 shown; more groups exist]", s)

    def test_breakdown_count_uses_rows_subject(self):
        ss = {"surface": "explorer", "dataset": "D",
              "analyze": {"group": "carrier", "bucket": None, "fn": "count",
                          "measure_column": None,
                          "rows": [{"key": "Orange", "value": "5"}],
                          "total": None, "truncated": False}}
        s = context.build_screen_state([], source_state=ss)
        self.assertIn("breakdown - Row count of rows by carrier:", s)
        self.assertNotIn("(per", s)
        self.assertNotIn("more groups exist", s)

    def test_combined_artifacts_and_source_block(self):
        arts = [{"kind": "chart", "title": "Rev", "chart": {"type": "line", "x": "month", "y": ["a"]}}]
        s = context.build_screen_state(
            arts, last_answer_excerpt="Revenue peaked.", active_tab="sources",
            source_state=_valid_ss())
        self.assertIn("line chart", s)              # artifact part
        self.assertIn("'Source data' tab", s)       # 'sources' -> "Source data"
        self.assertIn("SOURCE-DATA VIEW", s)        # source part
        self.assertIn("Revenue peaked.", s)         # excerpt after source section
        # order: source section appears before the excerpt line.
        self.assertLess(s.index("SOURCE-DATA VIEW"), s.index("Revenue peaked."))

    def test_kpi_tab_named(self):
        s = context.build_screen_state([], active_tab="kpi", source_state=_valid_ss())
        self.assertIn("'kpi' tab", s)

    def test_budget_drops_breakdown_first(self):
        # A wide calc block (~400 chars) keeps the base under 1200, but adding the
        # wide breakdown pushes past it: the breakdown line is the first to go.
        big_rows = [{"key": "k" * 80, "value": "v" * 40} for _ in range(5)]
        ss = {"surface": "explorer", "dataset": "D",
              "filters": [{"column": "c", "op": "=", "values": ["x"]}],
              "calc": {"column": "amount", "measures": [
                  {"fn": "sum", "value": "9" * 40}] * 8},
              "analyze": {"group": "g", "bucket": "month", "fn": "sum",
                          "measure_column": "amount", "rows": big_rows,
                          "total": "1", "truncated": True}}
        s = context.build_screen_state([], source_state=ss)
        self.assertNotIn("breakdown -", s)
        self.assertIn('c = "x"', s)                 # filters survive at this stage
        self.assertIn("computed figures on amount", s)  # calc survives too

    def test_budget_collapses_filter_values(self):
        # Many wide filters + a breakdown: breakdown dropped, then filter values
        # collapsed to "<col> (<n> values)".
        wide_filters = [{"column": "col%02d" % i, "op": "IN",
                         "values": ["v" * 80] * 5, "more": 20} for i in range(8)]
        ss = {"surface": "explorer", "dataset": "D",
              "filters": wide_filters,
              "analyze": {"group": "g", "fn": "sum", "measure_column": "amount",
                          "rows": [{"key": "k", "value": "1"}], "total": None,
                          "truncated": False}}
        s = context.build_screen_state([], source_state=ss)
        self.assertNotIn("breakdown -", s)
        self.assertIn("values)", s)                 # collapsed form present
        self.assertIn("col00 (25 values)", s)       # 5 shown + 20 more

    def test_budget_never_exceeds_much(self):
        wide_filters = [{"column": "c" * 64, "op": "IN",
                         "values": ["v" * 80] * 5, "more": 99} for _ in range(8)]
        ss = {"surface": "explorer", "dataset": "D" * 120, "agent": "A" * 80,
              "filters": wide_filters,
              "drill": [{"column": "c" * 64, "value": "v" * 80} for _ in range(6)],
              "calc": {"column": "x" * 64, "measures": [
                  {"fn": "sum", "value": "9" * 40}] * 8},
              "analyze": {"group": "g" * 64, "bucket": "month", "fn": "sum",
                          "measure_column": "m" * 64,
                          "rows": [{"key": "k" * 80, "value": "1" * 40} for _ in range(5)],
                          "total": "9" * 40, "truncated": True}}
        s = context.build_screen_state([], source_state=ss)
        # the whole block stays comfortably bounded (section cap 1200 + fixed frame).
        self.assertLess(len(s), 2000)

    def _absolute_max_ss(self):
        """The worst-case sanitized state: every cap maxed (frontend-reachable)."""
        wide_filters = [{"column": "c" * 64, "op": "IN",
                         "values": ["v" * 80] * 5, "more": 99} for _ in range(8)]
        return {"surface": "explorer", "dataset": "D" * 120, "agent": "A" * 80,
                "filters": wide_filters,
                "drill": [{"column": "c" * 64, "value": "v" * 80} for _ in range(6)],
                "calc": {"column": "x" * 64, "measures": [
                    {"fn": "sum", "value": "9" * 40}] * 8},
                "analyze": {"group": "g" * 64, "bucket": "month", "fn": "sum",
                            "measure_column": "m" * 64,
                            "rows": [{"key": "k" * 80, "value": "1" * 40} for _ in range(5)],
                            "total": "9" * 40, "truncated": True}}

    def test_permission_survives_absolute_max_overflow(self):
        # The absolute-max state forces the hard-truncate rung; the verbatim permission
        # sentence must still be present (it is appended AFTER the truncate, never cut),
        # and the whole section stays within the cap.
        section = context._source_state_section(self._absolute_max_ss())
        self.assertIn("quote them VERBATIM", section)      # permission body verbatim
        self.assertIn("requires the specialist", section)  # its closing clause
        self.assertTrue(section.endswith(context._SS_PERMISSION))  # appended LAST
        # Invariant of the implementation: body + permission lands exactly on the cap.
        self.assertLessEqual(len(section), context.MAX_SOURCE_STATE_CHARS)
        # It genuinely hit the hard truncate (the body was cut with an ellipsis).
        self.assertIn("...", section)

    def test_permission_present_in_rendered_block_on_overflow(self):
        # Same guarantee through the public renderer: the [ON SCREEN NOW] block keeps
        # the permission framing even when the source section overflows.
        s = context.build_screen_state([], source_state=self._absolute_max_ss())
        self.assertIn("quote them VERBATIM", s)

    def test_budget_collapses_drill_before_truncating(self):
        # A state that overflows ONLY because of a long drill list (no breakdown / filters
        # for the earlier rungs to shrink): the drill-collapse rung fires, so the section
        # stays whole ("<n> levels.") and is NOT hard-truncated, permission intact.
        ss = {"surface": "explorer", "dataset": "D",
              "drill": [{"column": "c" * 64, "value": "v" * 80} for _ in range(6)]}
        # Sanity: the un-collapsed body alone overflows the body budget.
        self.assertGreater(len(context._render_source_section(ss)),
                           context.MAX_SOURCE_STATE_CHARS - len("\n" + context._SS_PERMISSION))
        section = context._source_state_section(ss)
        self.assertIn("drill-down: 6 levels.", section)     # collapsed form
        self.assertNotIn("...", section)                    # NOT hard-truncated
        self.assertTrue(section.endswith(context._SS_PERMISSION))
        self.assertLessEqual(len(section), context.MAX_SOURCE_STATE_CHARS)

    def test_non_overflow_section_byte_identical_shape(self):
        # A small state must render body + permission with the permission as the last line,
        # unchanged from the pre-fix rendering (the fit path never truncates or collapses).
        ss = _valid_ss(row_count=12)
        section = context._source_state_section(ss)
        self.assertEqual(section,
                         context._render_source_section(ss) + "\n" + context._SS_PERMISSION)
        self.assertNotIn("...", section)


# --- routes._sanitize_screen_context ------------------------------------------
class SanitizeScreenContextTests(unittest.TestCase):
    def test_open_only_unchanged_shape(self):
        out = routes._sanitize_screen_context(
            {"open": True, "exchange_id": 42, "active_tab": "chart"})
        self.assertEqual(out, {"open": True, "exchange_id": "42", "active_tab": "chart"})

    def test_open_new_tabs_accepted(self):
        for tab in ("kpi", "sources"):
            out = routes._sanitize_screen_context(
                {"open": True, "exchange_id": "e1", "active_tab": tab})
            self.assertEqual(out["active_tab"], tab)

    def test_open_unknown_tab_nulled(self):
        out = routes._sanitize_screen_context(
            {"open": True, "exchange_id": "e1", "active_tab": "bogus"})
        self.assertIsNone(out["active_tab"])

    def test_open_bool_exchange_rejected_but_source_still_wins(self):
        out = routes._sanitize_screen_context(
            {"open": True, "exchange_id": True, "source_state": _valid_ss()})
        # open part invalid (bool exchange) -> open:False, source_state carried.
        self.assertEqual(out["open"], False)
        self.assertIn("source_state", out)

    def test_source_state_only_panel_closed(self):
        out = routes._sanitize_screen_context({"open": False, "source_state": _valid_ss()})
        self.assertEqual(out["open"], False)
        self.assertEqual(out["source_state"]["dataset"], "DRIVE_Revenues")
        self.assertNotIn("exchange_id", out)

    def test_both_open_and_source_state(self):
        out = routes._sanitize_screen_context({
            "open": True, "exchange_id": "e9", "active_tab": "sources",
            "source_state": _valid_ss(surface="evidence")})
        self.assertEqual(out["open"], True)
        self.assertEqual(out["exchange_id"], "e9")
        self.assertEqual(out["active_tab"], "sources")
        self.assertEqual(out["source_state"]["surface"], "evidence")

    def test_neither_returns_none(self):
        self.assertIsNone(routes._sanitize_screen_context(None))
        self.assertIsNone(routes._sanitize_screen_context({}))
        self.assertIsNone(routes._sanitize_screen_context({"open": False}))
        # open true but no exchange, and no source_state -> nothing to describe.
        self.assertIsNone(routes._sanitize_screen_context({"open": True}))
        # source_state present but empty/incomplete -> dropped -> None.
        self.assertIsNone(routes._sanitize_screen_context(
            {"open": False, "source_state": {"surface": "explorer", "dataset": "D"}}))

    def test_forged_types_never_raise(self):
        for bad in (5, "x", [], {"open": 1, "exchange_id": {}, "source_state": 9}):
            # must not raise; returns None or a well-formed dict.
            out = routes._sanitize_screen_context(bad)
            self.assertTrue(out is None or isinstance(out, dict))


if __name__ == "__main__":
    unittest.main()
