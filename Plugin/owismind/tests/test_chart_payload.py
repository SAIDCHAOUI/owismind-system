# Plugin/owismind/tests/test_chart_payload.py
"""chart_payload.build_chart_payload — the server-side 'blindé' chart builder.
Pure (stdlib only), so it imports without any dataiku stub."""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.evidence import chart_payload as cp  # noqa: E402


def _result(columns, rows, captured=True, truncated=False):
    return {"captured": captured, "columns": columns, "rows": rows,
            "row_count": len(rows), "truncated": truncated}


class TestNumberCoercion(unittest.TestCase):
    def test_passthrough(self):
        self.assertEqual(cp._to_number(1234), 1234.0)
        self.assertEqual(cp._to_number(12.5), 12.5)

    def test_formatted_strings(self):
        self.assertEqual(cp._to_number("1 234,5"), 1234.5)      # NBSP-ish + decimal comma
        self.assertEqual(cp._to_number("1,234.56"), 1234.56)    # US thousands + decimal dot
        self.assertEqual(cp._to_number("12.5%"), 12.5)
        self.assertEqual(cp._to_number("€ 90"), 90.0)

    def test_non_numeric(self):
        self.assertIsNone(cp._to_number("n/a"))
        self.assertIsNone(cp._to_number(None))
        self.assertIsNone(cp._to_number(True))


class TestLineBar(unittest.TestCase):
    def test_line_single_series(self):
        r = _result(["year", "revenue"], [["2024", 10], ["2025", 20], ["2026", 30]])
        out = cp.build_chart_payload(r, {"type": "line", "x": "year", "y": ["revenue"]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["labels"], ["2024", "2025", "2026"])
        self.assertEqual(len(out["datasets"]), 1)
        self.assertEqual(out["datasets"][0]["data"], [10.0, 20.0, 30.0])

    def test_bar_multi_series_case_insensitive(self):
        r = _result(["Product", "ACTUALS", "BUDGET"],
                    [["IPL", 100, 120], ["EVPL", 50, 40]])
        out = cp.build_chart_payload(r, {"type": "bar", "x": "product",
                                         "y": ["actuals", "budget"]})
        self.assertTrue(out["ok"])
        self.assertEqual([d["label"] for d in out["datasets"]], ["actuals", "budget"])
        self.assertEqual(out["datasets"][0]["data"], [100.0, 50.0])

    def test_non_numeric_cell_becomes_gap(self):
        r = _result(["m", "v"], [["jan", 10], ["feb", "n/a"], ["mar", 30]])
        out = cp.build_chart_payload(r, {"type": "line", "x": "m", "y": ["v"]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["datasets"][0]["data"], [10.0, None, 30.0])


class TestPie(unittest.TestCase):
    def test_pie_positive_only(self):
        r = _result(["client", "rev"], [["A", 60], ["B", 40], ["C", 0], ["D", -5]])
        out = cp.build_chart_payload(r, {"type": "pie", "x": "client", "y": ["rev"]})
        self.assertTrue(out["ok"])
        self.assertEqual(out["labels"], ["A", "B"])   # 0 and negative dropped, sorted desc
        self.assertEqual(out["datasets"][0]["data"], [60.0, 40.0])

    def test_pie_folds_other(self):
        rows = [[str(i), 100 - i] for i in range(20)]   # 20 positive slices
        out = cp.build_chart_payload(_result(["k", "v"], rows),
                                     {"type": "pie", "x": "k", "y": ["v"]})
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["labels"]), cp.MAX_SLICES)
        self.assertEqual(out["labels"][-1], "Other")
        self.assertTrue(out["truncated"])


class TestDegrade(unittest.TestCase):
    def test_no_data(self):
        self.assertEqual(cp.build_chart_payload(None, {"type": "line", "x": "a", "y": ["b"]})["reason"], "no_data")
        self.assertEqual(cp.build_chart_payload({"captured": False}, {"type": "line", "x": "a", "y": ["b"]})["reason"], "no_data")
        self.assertEqual(cp.build_chart_payload(_result(["a"], []), {"type": "line", "x": "a", "y": ["b"]})["reason"], "no_data")

    def test_bad_spec(self):
        r = _result(["a", "b"], [["x", 1]])
        self.assertEqual(cp.build_chart_payload(r, {"type": "scatter", "x": "a", "y": ["b"]})["reason"], "bad_spec")
        self.assertEqual(cp.build_chart_payload(r, {"type": "line", "x": "a", "y": []})["reason"], "bad_spec")

    def test_column_not_found(self):
        r = _result(["a", "b"], [["x", 1]])
        self.assertEqual(cp.build_chart_payload(r, {"type": "line", "x": "z", "y": ["b"]})["reason"], "x_not_found")
        self.assertEqual(cp.build_chart_payload(r, {"type": "line", "x": "a", "y": ["z"]})["reason"], "y_not_found")

    def test_no_numeric(self):
        r = _result(["a", "b"], [["x", "foo"], ["y", "bar"]])
        self.assertEqual(cp.build_chart_payload(r, {"type": "line", "x": "a", "y": ["b"]})["reason"], "no_numeric")

    def test_point_cap(self):
        rows = [[str(i), i] for i in range(cp.MAX_POINTS + 50)]
        out = cp.build_chart_payload(_result(["a", "b"], rows),
                                     {"type": "line", "x": "a", "y": ["b"]})
        self.assertTrue(out["ok"])
        self.assertEqual(len(out["labels"]), cp.MAX_POINTS)
        self.assertTrue(out["truncated"])


class TestKpiPayload(unittest.TestCase):
    def test_value_and_delta(self):
        out = cp.build_kpi_payload(
            _result(["Revenue_EUR", "delta_pct"], [[1234567, 5.2]]),
            {"label": "Revenue YTD", "value": "Revenue_EUR", "delta_pct": "delta_pct"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["value"], 1234567.0)
        self.assertEqual(out["delta_pct"], 5.2)
        self.assertEqual(out["label"], "Revenue YTD")

    def test_value_only(self):
        out = cp.build_kpi_payload(_result(["n"], [[42]]), {"value": "n"})
        self.assertTrue(out["ok"])
        self.assertEqual(out["value"], 42.0)
        self.assertNotIn("delta", out)

    def test_missing_column(self):
        out = cp.build_kpi_payload(_result(["n"], [[42]]), {"value": "missing"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "value_not_found")

    def test_no_data(self):
        out = cp.build_kpi_payload({"captured": False}, {"value": "n"})
        self.assertFalse(out["ok"])

    def test_non_numeric(self):
        out = cp.build_kpi_payload(_result(["n"], [["abc"]]), {"value": "n"})
        self.assertFalse(out["ok"])
        self.assertEqual(out["reason"], "no_numeric")


if __name__ == "__main__":
    unittest.main()
