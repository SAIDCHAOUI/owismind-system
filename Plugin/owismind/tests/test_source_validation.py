# Plugin/owismind/tests/test_source_validation.py
"""Source Data Explorer validators: sources block + rows/meta/distinct request bounds."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.security.validation import (  # noqa: E402
    MAX_AGENT_SOURCES,
    MAX_SOURCE_QUERY_CHARS,
    ValidationError,
    validate_agent_meta,
    validate_source_distinct_params,
    validate_source_meta_params,
    validate_source_rows_request,
    validate_sources_block,
)


class SourcesBlockTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        out = validate_sources_block([
            {"dataset": "DRIVE_Revenues", "label": "Revenue base"},
            {"dataset": "TroubleTickets_year", "label": "Tickets"},
        ])
        self.assertEqual(out, [
            {"dataset": "DRIVE_Revenues", "label": "Revenue base"},
            {"dataset": "TroubleTickets_year", "label": "Tickets"},
        ])

    def test_label_falls_back_to_dataset(self):
        out = validate_sources_block([{"dataset": "DRIVE_Revenues", "label": "  "},
                                      {"dataset": "T2"}])
        self.assertEqual(out[0]["label"], "DRIVE_Revenues")
        self.assertEqual(out[1]["label"], "T2")

    def test_label_bounded(self):
        out = validate_sources_block([{"dataset": "d", "label": "x" * 200}])
        self.assertEqual(len(out[0]["label"]), 60)

    def test_dataset_pattern_enforced(self):
        # A name with spaces / slashes / quotes / a query fragment is dropped.
        bad = [
            {"dataset": "has space"},
            {"dataset": "a/b"},
            {"dataset": 'a";DROP'},
            {"dataset": "SELECT * FROM t"},
            {"dataset": "x" * 129},
            {"dataset": ""},
            {"dataset": None},
            {"dataset": 5},
            {"label": "no dataset key"},
            "not a dict",
            None,
        ]
        self.assertEqual(validate_sources_block(bad), [])

    def test_allowed_dataset_charset(self):
        out = validate_sources_block([{"dataset": "Proj.Data_set-v1"}])
        self.assertEqual(out[0]["dataset"], "Proj.Data_set-v1")

    def test_dataset_stripped(self):
        out = validate_sources_block([{"dataset": "  DRIVE_Revenues  "}])
        self.assertEqual(out[0]["dataset"], "DRIVE_Revenues")

    def test_dedup_case_insensitive_first_wins(self):
        out = validate_sources_block([
            {"dataset": "DRIVE_Revenues", "label": "first"},
            {"dataset": "drive_revenues", "label": "second"},
        ])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["label"], "first")

    def test_capped_at_max(self):
        many = [{"dataset": "d{}".format(i)} for i in range(MAX_AGENT_SOURCES + 5)]
        out = validate_sources_block(many)
        self.assertEqual(len(out), MAX_AGENT_SOURCES)

    def test_non_list_returns_empty(self):
        self.assertEqual(validate_sources_block(None), [])
        self.assertEqual(validate_sources_block({"dataset": "d"}), [])
        self.assertEqual(validate_sources_block("d"), [])

    def test_wired_into_agent_meta(self):
        meta = validate_agent_meta({"sources": [{"dataset": "DRIVE_Revenues"}]})
        self.assertEqual(meta["sources"], [{"dataset": "DRIVE_Revenues", "label": "DRIVE_Revenues"}])
        # Absent input yields an empty block (never raises).
        self.assertEqual(validate_agent_meta({})["sources"], [])
        self.assertEqual(validate_agent_meta({"sources": "junk"})["sources"], [])


def _rows(**over):
    base = {"agent": "ag_abc123", "source": 0}
    base.update(over)
    return base


class RowsRequestTests(unittest.TestCase):
    def test_valid_roundtrip(self):
        agent, source_id, q, filters, page, sort = validate_source_rows_request(_rows(
            q="  algerie ",
            filters=[{"column": "customer", "op": "IN", "values": ["A", "B"]}],
            page=2,
            sort={"column": "period", "dir": "desc"},
        ))
        self.assertEqual(agent, "ag_abc123")
        self.assertEqual(source_id, 0)
        self.assertEqual(q, "algerie")
        self.assertEqual(filters, [{"column": "customer", "op": "IN", "values": ["A", "B"]}])
        self.assertEqual(page, 2)
        self.assertEqual(sort, {"column": "period", "dir": "desc"})

    def test_defaults(self):
        agent, source_id, q, filters, page, sort = validate_source_rows_request(_rows())
        self.assertEqual((q, filters, page, sort), ("", [], 0, None))

    def test_agent_cleaned_and_required(self):
        self.assertEqual(validate_source_rows_request(_rows(agent="  ag_x "))[0], "ag_x")
        for bad in ("", "   ", None, 5, "x" * 65):
            with self.assertRaises(ValidationError) as ctx:
                validate_source_rows_request(_rows(agent=bad))
            self.assertEqual(ctx.exception.code, "invalid_agent")

    def test_source_id_range(self):
        # Accepts int or numeric string in [0, MAX_AGENT_SOURCES).
        self.assertEqual(validate_source_rows_request(_rows(source=MAX_AGENT_SOURCES - 1))[1],
                         MAX_AGENT_SOURCES - 1)
        for bad in (-1, MAX_AGENT_SOURCES, MAX_AGENT_SOURCES + 3, "abc", None, True,
                    float("inf")):
            with self.assertRaises(ValidationError) as ctx:
                validate_source_rows_request(_rows(source=bad))
            self.assertEqual(ctx.exception.code, "invalid_source")

    def test_q_cleaned_and_capped(self):
        # Non-str -> "", control chars -> collapsed spaces, capped at MAX_SOURCE_QUERY_CHARS.
        self.assertEqual(validate_source_rows_request(_rows(q=123))[2], "")
        self.assertEqual(validate_source_rows_request(_rows(q="a\t\nb   c"))[2], "a b c")
        long_q = validate_source_rows_request(_rows(q="x" * (MAX_SOURCE_QUERY_CHARS + 50)))[2]
        self.assertEqual(len(long_q), MAX_SOURCE_QUERY_CHARS)

    def test_page_clamped_never_raises(self):
        self.assertEqual(validate_source_rows_request(_rows(page=-3))[4], 0)
        self.assertEqual(validate_source_rows_request(_rows(page=9999))[4], 20)
        self.assertEqual(validate_source_rows_request(_rows(page="junk"))[4], 0)
        self.assertEqual(validate_source_rows_request(_rows(page=float("inf")))[4], 0)

    def test_filter_bounds_reused(self):
        bad = [
            (_rows(filters=[{"column": "c", "op": ">=", "values": [1]}]), "invalid_filter_op"),
            (_rows(filters=[{"column": "c", "op": "=", "values": []}]), "invalid_filter_values"),
            (_rows(filters=[{"column": "c", "op": "=", "values": [1, 2]}]), "invalid_filter_values"),
            (_rows(filters=[{"column": "c", "op": "IN", "values": list(range(51))}]), "invalid_filter_values"),
            (_rows(filters=[{"column": "c", "op": "=", "values": ["x" * 501]}]), "filter_value_too_long"),
            (_rows(filters="nope"), "invalid_filters"),
            (_rows(filters=[{"column": "c", "op": "=", "values": [1]}] * 21), "invalid_filters"),
            (_rows(filters=[{"column": "c", "op": "=", "values": [float("nan")]}]), "invalid_filter_value"),
            ("not a dict", "invalid_payload"),
        ]
        for payload, code in bad:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_source_rows_request(payload)
            self.assertEqual(ctx.exception.code, code)

    def test_sort_normalized(self):
        self.assertEqual(validate_source_rows_request(_rows(sort={"column": "p", "dir": "JUNK"}))[5],
                         {"column": "p", "dir": "asc"})
        self.assertIsNone(validate_source_rows_request(_rows(sort="x"))[5])


class MetaDistinctParamTests(unittest.TestCase):
    def test_meta_params(self):
        self.assertEqual(validate_source_meta_params("ag_x", "3"), ("ag_x", 3))
        with self.assertRaises(ValidationError) as ctx:
            validate_source_meta_params("", "0")
        self.assertEqual(ctx.exception.code, "invalid_agent")
        with self.assertRaises(ValidationError) as ctx:
            validate_source_meta_params("ag_x", "9")
        self.assertEqual(ctx.exception.code, "invalid_source")
        with self.assertRaises(ValidationError) as ctx:
            validate_source_meta_params("ag_x", None)
        self.assertEqual(ctx.exception.code, "invalid_source")

    def test_distinct_params(self):
        self.assertEqual(validate_source_distinct_params("ag_x", "2", "Customer Id"),
                         ("ag_x", 2, "Customer Id"))
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_params("ag_x", "0", "")
        self.assertEqual(ctx.exception.code, "invalid_filter_column")
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_params("ag_x", "0", "x" * 129)
        self.assertEqual(ctx.exception.code, "invalid_filter_column")


if __name__ == "__main__":
    unittest.main()
