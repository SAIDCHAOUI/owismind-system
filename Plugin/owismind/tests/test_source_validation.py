# Plugin/owismind/tests/test_source_validation.py
"""Source Data Explorer validators: sources block + rows/meta/distinct request bounds."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.security.validation import (  # noqa: E402
    DEFAULT_ROWS_LIMIT,
    MAX_AGENT_SOURCES,
    MAX_AGG_MEASURES,
    MAX_AGG_GROUP_ROWS,
    MAX_ROWS_LIMIT,
    MAX_ROWS_OFFSET,
    MAX_SOURCE_QUERY_CHARS,
    ValidationError,
    validate_agent_meta,
    validate_evidence_rows_request,
    validate_source_aggregate_request,
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
        agent, source_id, q, filters, limit, offset, sort = validate_source_rows_request(_rows(
            q="  algerie ",
            filters=[{"column": "customer", "op": "IN", "values": ["A", "B"]}],
            limit=25,
            offset=40,
            sort={"column": "period", "dir": "desc"},
        ))
        self.assertEqual(agent, "ag_abc123")
        self.assertEqual(source_id, 0)
        self.assertEqual(q, "algerie")
        self.assertEqual(filters, [{"column": "customer", "op": "IN", "values": ["A", "B"]}])
        self.assertEqual(limit, 25)
        self.assertEqual(offset, 40)
        self.assertEqual(sort, {"column": "period", "dir": "desc"})

    def test_defaults(self):
        agent, source_id, q, filters, limit, offset, sort = validate_source_rows_request(_rows())
        self.assertEqual((q, filters, limit, offset, sort), ("", [], DEFAULT_ROWS_LIMIT, 0, None))

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

    def test_limit_offset_clamped_never_raises(self):
        # limit is index 4, offset index 5 - both clamp to their bands, never raise.
        self.assertEqual(validate_source_rows_request(_rows(limit=9999))[4], MAX_ROWS_LIMIT)
        self.assertEqual(validate_source_rows_request(_rows(limit=0))[4], 1)
        self.assertEqual(validate_source_rows_request(_rows(limit="junk"))[4], DEFAULT_ROWS_LIMIT)
        self.assertEqual(validate_source_rows_request(_rows(limit=float("inf")))[4], DEFAULT_ROWS_LIMIT)
        self.assertEqual(validate_source_rows_request(_rows(offset=-3))[5], 0)
        self.assertEqual(validate_source_rows_request(_rows(offset=9999))[5], MAX_ROWS_OFFSET)
        self.assertEqual(validate_source_rows_request(_rows(offset="junk"))[5], 0)
        self.assertEqual(validate_source_rows_request(_rows(offset=float("inf")))[5], 0)

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
        self.assertEqual(validate_source_rows_request(_rows(sort={"column": "p", "dir": "JUNK"}))[6],
                         {"column": "p", "dir": "asc"})
        self.assertIsNone(validate_source_rows_request(_rows(sort="x"))[6])

    def test_between_filter_accepted_on_source(self):
        # /source/* accepts a BETWEEN date-range chip (exactly 2 values = low/high).
        out = validate_source_rows_request(_rows(
            filters=[{"column": "period", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}]))[3]
        self.assertEqual(out, [{"column": "period", "op": "BETWEEN",
                                "values": ["2025-01-01", "2025-12-31"]}])

    def test_between_requires_exactly_two_values(self):
        # 1 or 3 values -> invalid_filter_values (BETWEEN is a range, not an IN list).
        for vals in ([1], [1, 2, 3]):
            with self.assertRaises(ValidationError) as ctx:
                validate_source_rows_request(_rows(
                    filters=[{"column": "c", "op": "BETWEEN", "values": vals}]))
            self.assertEqual(ctx.exception.code, "invalid_filter_values")


class EvidenceFilterOpsTests(unittest.TestCase):
    """/evidence/rows now accepts BETWEEN too (unified with /source/*): the evidence
    table takes the same date-range chip the Source Data explorer does."""

    def _ev(self, **over):
        base = {"exchange_id": "ex_1"}
        base.update(over)
        return base

    def test_evidence_accepts_between(self):
        # BETWEEN is now on the /evidence/rows op whitelist (SOURCE_FILTER_OPS), rendered
        # as-is with both range bounds - byte-identical to /source/rows.
        out = validate_evidence_rows_request(self._ev(
            filters=[{"column": "period", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}]))[1]
        self.assertEqual(out, [{"column": "period", "op": "BETWEEN",
                                "values": ["2025-01-01", "2025-12-31"]}])

    def test_evidence_between_requires_exactly_two_values(self):
        # Arity is enforced by the shared parser: 1 or 3 values -> invalid_filter_values.
        for vals in ([1], [1, 2, 3]):
            with self.assertRaises(ValidationError) as ctx:
                validate_evidence_rows_request(self._ev(
                    filters=[{"column": "c", "op": "BETWEEN", "values": vals}]))
            self.assertEqual(ctx.exception.code, "invalid_filter_values")

    def test_evidence_still_refuses_other_comparison_ops(self):
        # Only equality / IN / BETWEEN travel; >=, <, ... stay off the whitelist.
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_rows_request(self._ev(
                filters=[{"column": "c", "op": ">=", "values": [1]}]))
        self.assertEqual(ctx.exception.code, "invalid_filter_op")

    def test_evidence_still_accepts_eq_and_in(self):
        exchange_id, filters = validate_evidence_rows_request(self._ev(
            filters=[{"column": "c", "op": "=", "values": ["FR"]},
                     {"column": "d", "op": "IN", "values": ["A", "B"]}]))[:2]
        self.assertEqual(exchange_id, "ex_1")
        self.assertEqual(filters, [{"column": "c", "op": "=", "values": ["FR"]},
                                   {"column": "d", "op": "IN", "values": ["A", "B"]}])


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
        # q is absent -> the 4th element is "" (no search), byte-identical scope.
        self.assertEqual(validate_source_distinct_params("ag_x", "2", "Customer Id"),
                         ("ag_x", 2, "Customer Id", ""))
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_params("ag_x", "0", "")
        self.assertEqual(ctx.exception.code, "invalid_filter_column")
        with self.assertRaises(ValidationError) as ctx:
            validate_source_distinct_params("ag_x", "0", "x" * 129)
        self.assertEqual(ctx.exception.code, "invalid_filter_column")

    def test_distinct_params_q_cleaned(self):
        # A valid q is trimmed/collapsed; a non-str degrades to "" (never raises);
        # an over-long q is capped; multiple/control spaces collapse to single ones.
        self.assertEqual(
            validate_source_distinct_params("ag_x", "0", "Customer Id", "  algerie ")[3],
            "algerie")
        self.assertEqual(
            validate_source_distinct_params("ag_x", "0", "Customer Id", "a\t\nb   c")[3],
            "a b c")
        self.assertEqual(
            validate_source_distinct_params("ag_x", "0", "Customer Id", 123)[3], "")
        self.assertEqual(
            validate_source_distinct_params("ag_x", "0", "Customer Id", None)[3], "")
        long_q = validate_source_distinct_params(
            "ag_x", "0", "Customer Id", "x" * (MAX_SOURCE_QUERY_CHARS + 50))[3]
        self.assertEqual(len(long_q), MAX_SOURCE_QUERY_CHARS)


def _agg(**over):
    base = {"agent": "ag_abc123", "source": 0,
            "measures": [{"fn": "count", "column": None}]}
    base.update(over)
    return base


class AggregateRequestTests(unittest.TestCase):
    def test_valid_ungrouped_roundtrip(self):
        agent, source_id, q, filters, group, measures, limit = (
            validate_source_aggregate_request(_agg(
                q="  algerie ",
                filters=[{"column": "customer", "op": "IN", "values": ["A", "B"]}],
                measures=[{"fn": "count", "column": None},
                          {"fn": "sum", "column": "amount"}],
                limit=20,
            )))
        self.assertEqual(agent, "ag_abc123")
        self.assertEqual(source_id, 0)
        self.assertEqual(q, "algerie")
        self.assertEqual(filters, [{"column": "customer", "op": "IN", "values": ["A", "B"]}])
        self.assertIsNone(group)
        self.assertEqual(measures, [{"fn": "count", "column": None},
                                    {"fn": "sum", "column": "amount"}])
        self.assertEqual(limit, 20)

    def test_valid_grouped_with_bucket(self):
        _, _, _, _, group, measures, _ = validate_source_aggregate_request(_agg(
            group={"column": "created", "bucket": "month"},
            measures=[{"fn": "avg", "column": "amount"}],
        ))
        self.assertEqual(group, {"column": "created", "bucket": "month"})
        self.assertEqual(measures, [{"fn": "avg", "column": "amount"}])

    def test_group_none_and_bucketless(self):
        # Absent group -> None (ungrouped); a dict with no bucket -> bucket None.
        self.assertIsNone(validate_source_aggregate_request(_agg())[4])
        self.assertEqual(
            validate_source_aggregate_request(_agg(group={"column": "c"}))[4],
            {"column": "c", "bucket": None})

    def test_defaults(self):
        # q/filters default, limit defaults to the group-rows cap.
        _, _, q, filters, group, _, limit = validate_source_aggregate_request(_agg())
        self.assertEqual((q, filters, group, limit), ("", [], None, MAX_AGG_GROUP_ROWS))

    def test_limit_clamped_never_raises(self):
        self.assertEqual(validate_source_aggregate_request(_agg(limit=9999))[6], MAX_AGG_GROUP_ROWS)
        self.assertEqual(validate_source_aggregate_request(_agg(limit=0))[6], 1)
        self.assertEqual(validate_source_aggregate_request(_agg(limit="junk"))[6], MAX_AGG_GROUP_ROWS)
        self.assertEqual(validate_source_aggregate_request(_agg(limit=True))[6], MAX_AGG_GROUP_ROWS)
        self.assertEqual(validate_source_aggregate_request(_agg(limit=float("inf")))[6], MAX_AGG_GROUP_ROWS)

    def test_measures_whitelist_and_shape(self):
        bad = [
            (_agg(measures=None), "invalid_aggregate"),
            (_agg(measures=[]), "invalid_aggregate"),
            (_agg(measures="nope"), "invalid_aggregate"),
            # An unknown fn is rejected (median is now whitelisted; stddev is not).
            (_agg(measures=[{"fn": "stddev", "column": "a"}]), "invalid_aggregate"),
            (_agg(measures=["not a dict"]), "invalid_aggregate"),
            # count must NOT carry a column.
            (_agg(measures=[{"fn": "count", "column": "amount"}]), "invalid_aggregate"),
            # 9 measures (MAX is 8).
            (_agg(measures=[{"fn": "count", "column": None}] * (MAX_AGG_MEASURES + 1)),
             "invalid_aggregate"),
            # a non-count fn needs a valid column string (reuses the filter-column code).
            (_agg(measures=[{"fn": "sum", "column": None}]), "invalid_filter_column"),
            (_agg(measures=[{"fn": "sum", "column": ""}]), "invalid_filter_column"),
            (_agg(measures=[{"fn": "sum", "column": "x" * 129}]), "invalid_filter_column"),
        ]
        for payload, code in bad:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_source_aggregate_request(payload)
            self.assertEqual(ctx.exception.code, code)

    def test_all_functions_accepted(self):
        for fn in ("count_distinct", "sum", "avg", "median", "min", "max"):
            out = validate_source_aggregate_request(_agg(
                measures=[{"fn": fn, "column": "amount"}]))[5]
            self.assertEqual(out, [{"fn": fn, "column": "amount"}])

    def test_between_filter_accepted_on_aggregate(self):
        # The aggregate core reuses SOURCE_FILTER_OPS: a BETWEEN date-range chip is accepted.
        out = validate_source_aggregate_request(_agg(
            filters=[{"column": "period", "op": "BETWEEN",
                      "values": ["2025-01-01", "2025-12-31"]}]))[3]
        self.assertEqual(out, [{"column": "period", "op": "BETWEEN",
                                "values": ["2025-01-01", "2025-12-31"]}])

    def test_group_shape_and_bucket(self):
        bad = [
            (_agg(group="nope"), "invalid_group"),
            (_agg(group=5), "invalid_group"),
            (_agg(group={"column": "c", "bucket": "week"}), "invalid_group_bucket"),
            (_agg(group={"column": "c", "bucket": "day"}), "invalid_group_bucket"),
            # a group dict still needs a valid column string.
            (_agg(group={"bucket": "month"}), "invalid_filter_column"),
            (_agg(group={"column": "", "bucket": "month"}), "invalid_filter_column"),
        ]
        for payload, code in bad:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_source_aggregate_request(payload)
            self.assertEqual(ctx.exception.code, code)

    def test_core_codes_reused(self):
        # The agent/source/filters core reuses the same stable codes as /source/rows.
        for payload, code in [
            ("not a dict", "invalid_payload"),
            (_agg(agent=""), "invalid_agent"),
            (_agg(source=MAX_AGENT_SOURCES), "invalid_source"),
            (_agg(filters=[{"column": "c", "op": ">=", "values": [1]}]), "invalid_filter_op"),
        ]:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_source_aggregate_request(payload)
            self.assertEqual(ctx.exception.code, code)


if __name__ == "__main__":
    unittest.main()
