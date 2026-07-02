# Plugin/owismind/tests/test_evidence_validation.py
"""validate_evidence_rows_request & co: shape + bounds before anything reaches SQL."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.security.validation import (  # noqa: E402
    DEFAULT_ROWS_LIMIT,
    MAX_ROWS_LIMIT,
    MAX_ROWS_OFFSET,
    MAX_SOURCE_QUERY_CHARS,
    ValidationError,
    _clean_source_query,
    _parse_rows_limit,
    _parse_rows_offset,
    validate_evidence_column,
    validate_evidence_rows_request,
    validate_required_exchange_id,
)


def _payload(**over):
    base = {
        "exchange_id": "ex1",
        "filters": [{"column": "solution", "op": "IN", "values": ["OBS", "OCD"]}],
        "kept_ids": [1, 3],
        "include_advanced": True,
        "limit": 25,
        "offset": 40,
        "sort": {"column": "period", "dir": "desc"},
    }
    base.update(over)
    return base


class RowsRequestTests(unittest.TestCase):
    def test_valid_payload_roundtrip(self):
        (ex, filters, kept, adv, limit, offset, sort, drill, table,
         q) = validate_evidence_rows_request(_payload())
        self.assertEqual(ex, "ex1")
        self.assertEqual(filters, [{"column": "solution", "op": "IN", "values": ["OBS", "OCD"]}])
        self.assertEqual(kept, [1, 3])
        self.assertTrue(adv)
        self.assertEqual(limit, 25)
        self.assertEqual(offset, 40)
        self.assertEqual(sort, {"column": "period", "dir": "desc"})
        self.assertEqual(drill, [])
        self.assertIsNone(table)
        self.assertEqual(q, "")

    def test_defaults(self):
        (ex, filters, kept, adv, limit, offset, sort, drill, table,
         q) = validate_evidence_rows_request({"exchange_id": "e"})
        self.assertEqual((filters, kept, adv, limit, offset, sort, drill, table, q),
                         ([], [], False, DEFAULT_ROWS_LIMIT, 0, None, [], None, ""))

    def test_table_selector(self):
        # A bounded string table name travels; anything else degrades to None.
        self.assertEqual(validate_evidence_rows_request(_payload(table="my_dataset"))[8],
                         "my_dataset")
        self.assertIsNone(validate_evidence_rows_request(_payload(table=""))[8])
        self.assertIsNone(validate_evidence_rows_request(_payload(table=123))[8])
        self.assertIsNone(validate_evidence_rows_request(_payload(table="x" * 257))[8])

    def test_q_search_term(self):
        # q is the LAST element (index 9), cleaned like /source/rows and never raising.
        self.assertEqual(validate_evidence_rows_request(_payload(q="  algerie "))[9], "algerie")
        self.assertEqual(validate_evidence_rows_request(_payload(q="a\t\nb   c"))[9], "a b c")
        # Non-str degrades to "" (no search), absent q also yields "".
        self.assertEqual(validate_evidence_rows_request(_payload(q=123))[9], "")
        self.assertEqual(validate_evidence_rows_request(_payload())[9], "")

    def test_limit_offset_clamped_never_raises(self):
        # The request wires the row window through the clamping helpers (index 4/5).
        self.assertEqual(validate_evidence_rows_request(_payload(limit=9999))[4], MAX_ROWS_LIMIT)
        self.assertEqual(validate_evidence_rows_request(_payload(limit=0))[4], 1)
        self.assertEqual(validate_evidence_rows_request(_payload(limit="junk"))[4], DEFAULT_ROWS_LIMIT)
        self.assertEqual(validate_evidence_rows_request(_payload(offset=-3))[5], 0)
        self.assertEqual(validate_evidence_rows_request(_payload(offset=9999))[5], MAX_ROWS_OFFSET)
        # int(float("inf")) raises OverflowError -> both degrade to their default.
        self.assertEqual(validate_evidence_rows_request(_payload(limit=float("inf")))[4],
                         DEFAULT_ROWS_LIMIT)
        self.assertEqual(validate_evidence_rows_request(_payload(offset=float("inf")))[5], 0)

    def test_rejections(self):
        bad = [
            ({"exchange_id": ""}, "invalid_exchange_id"),
            (_payload(filters=[{"column": "c", "op": ">=", "values": [1]}]), "invalid_filter_op"),
            (_payload(filters=[{"column": "c", "op": "=", "values": []}]), "invalid_filter_values"),
            (_payload(filters=[{"column": "c", "op": "=", "values": [{"x": 1}]}]), "invalid_filter_value"),
            (_payload(filters=[{"column": "c", "op": "=", "values": ["x" * 501]}]), "filter_value_too_long"),
            (_payload(filters="nope"), "invalid_filters"),
            (_payload(filters=[{"column": "c", "op": "=", "values": [1]}] * 21), "invalid_filters"),
            # Bounds: 51 IN values / 101 kept ids exceed the caps.
            (_payload(filters=[{"column": "c", "op": "IN", "values": list(range(51))}]), "invalid_filter_values"),
            (_payload(kept_ids=list(range(101))), "invalid_kept_ids"),
            # '=' arity is exactly 1 (defense in depth before render_predicate).
            (_payload(filters=[{"column": "c", "op": "=", "values": [1, 2]}]), "invalid_filter_values"),
            # NaN/Infinity parse as JSON literals but render as unquoted SQL tokens.
            (_payload(filters=[{"column": "c", "op": "=", "values": [float("nan")]}]), "invalid_filter_value"),
            (_payload(filters=[{"column": "c", "op": "=", "values": [float("inf")]}]), "invalid_filter_value"),
            (_payload(kept_ids=[True]), "invalid_kept_ids"),
            (_payload(kept_ids=[-1]), "invalid_kept_ids"),
            ("nope", "invalid_payload"),
        ]
        for payload, code in bad:
            with self.assertRaises(ValidationError, msg=code) as ctx:
                validate_evidence_rows_request(payload)
            self.assertEqual(ctx.exception.code, code)

    def test_bounds_accepted(self):
        # Exactly at the caps: 50 IN values and '=' with exactly 1 value pass.
        filters = validate_evidence_rows_request(
            _payload(filters=[
                {"column": "c", "op": "IN", "values": list(range(50))},
                {"column": "d", "op": "=", "values": ["one"]},
            ])
        )[1]
        self.assertEqual(len(filters[0]["values"]), 50)
        self.assertEqual(filters[1]["values"], ["one"])

    def test_sort_dir_normalized(self):
        sort = validate_evidence_rows_request(_payload(sort={"column": "p", "dir": "JUNK"}))[6]
        self.assertEqual(sort["dir"], "asc")
        self.assertIsNone(validate_evidence_rows_request(_payload(sort="x"))[6])
        # Present-but-malformed sort DEGRADES to None (optional input house rule).
        self.assertIsNone(validate_evidence_rows_request(_payload(sort={"column": 123}))[6])

    def test_bool_values_allowed(self):
        # boolean dataset columns are legitimate filter values (unlike feedback rating).
        filters = validate_evidence_rows_request(
            _payload(filters=[{"column": "active", "op": "=", "values": [True]}])
        )[1]
        self.assertEqual(filters[0]["values"], [True])


class DrillTests(unittest.TestCase):
    """Optional ``drill`` key: shape + bounds only (the drillable column SET is
    re-derived server-side from the stored SQL - never trusted from here)."""

    def _drill(self, drill):
        return validate_evidence_rows_request(_payload(drill=drill))[7]

    def _assert_invalid(self, drill):
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_rows_request(_payload(drill=drill))
        # One stable code for the whole drill block (mirrors the service side).
        self.assertEqual(ctx.exception.code, "invalid_drill")

    def test_valid_drill_roundtrip(self):
        drill = self._drill([{"column": "customer", "value": "Algerie Telecom"},
                             {"column": "year", "value": 2026}])
        self.assertEqual(drill, [{"column": "customer", "value": "Algerie Telecom"},
                                 {"column": "year", "value": 2026}])

    def test_none_value_allowed(self):
        # None is legal: it drills into the NULL group (renders IS NULL).
        self.assertEqual(self._drill([{"column": "phase", "value": None}]),
                         [{"column": "phase", "value": None}])

    def test_bool_value_allowed(self):
        # Boolean dataset columns are legitimate group keys.
        self.assertEqual(self._drill([{"column": "active", "value": True}]),
                         [{"column": "active", "value": True}])

    def test_eight_entries_accepted_nine_rejected(self):
        eight = [{"column": "c{}".format(i), "value": i} for i in range(8)]
        self.assertEqual(len(self._drill(eight)), 8)
        self._assert_invalid(eight + [{"column": "c8", "value": 8}])

    def test_column_too_long_rejected(self):
        self._assert_invalid([{"column": "x" * 129, "value": 1}])

    def test_missing_column_rejected(self):
        self._assert_invalid([{"value": 1}])

    def test_non_finite_numbers_rejected(self):
        # NaN/Infinity parse as JSON literals but would render as unquoted SQL.
        self._assert_invalid([{"column": "c", "value": float("nan")}])
        self._assert_invalid([{"column": "c", "value": float("inf")}])

    def test_value_too_long_rejected(self):
        self._assert_invalid([{"column": "c", "value": "x" * 501}])

    def test_non_list_drill_rejected(self):
        self._assert_invalid("nope")
        self._assert_invalid({"column": "c", "value": 1})

    def test_non_dict_entry_rejected(self):
        self._assert_invalid(["customer"])

    def test_absent_or_null_drill_degrades_to_empty(self):
        # Absent key and explicit null both mean "no drill" (never an error).
        self.assertEqual(validate_evidence_rows_request(_payload())[7], [])
        self.assertEqual(self._drill(None), [])


class HelpersTests(unittest.TestCase):
    def test_required_exchange_id(self):
        self.assertEqual(validate_required_exchange_id("ok"), "ok")
        for bad in (None, "", 12, "x" * 200):
            with self.assertRaises(ValidationError):
                validate_required_exchange_id(bad)

    def test_evidence_column(self):
        self.assertEqual(validate_evidence_column("Solution Name"), "Solution Name")
        for bad in (None, "", "x" * 200, 5):
            with self.assertRaises(ValidationError):
                validate_evidence_column(bad)


class SearchQueryCleanerTests(unittest.TestCase):
    """The shared ``q`` cleaner: the /evidence/distinct route calls it inline (no
    dedicated validator), so the picker search term is cleaned here exactly like
    /source/rows and /evidence/rows. It never raises: an unusable value -> "".
    """

    def test_absent_or_non_str_yields_empty(self):
        # Absent (None) and any non-str degrade to "" = no search (byte-identical scope).
        self.assertEqual(_clean_source_query(None), "")
        self.assertEqual(_clean_source_query(123), "")
        self.assertEqual(_clean_source_query({"x": 1}), "")

    def test_valid_term_trimmed(self):
        self.assertEqual(_clean_source_query("  algerie "), "algerie")

    def test_control_chars_collapse_to_single_spaces(self):
        # Tabs/newlines (non-printable) become spaces, then whitespace runs collapse.
        self.assertEqual(_clean_source_query("a\t\nb   c"), "a b c")

    def test_over_long_capped(self):
        long_q = _clean_source_query("x" * (MAX_SOURCE_QUERY_CHARS + 50))
        self.assertEqual(len(long_q), MAX_SOURCE_QUERY_CHARS)


class RowsWindowHelperTests(unittest.TestCase):
    """The shared limit/offset clampers: bounded, defaulting, never raising."""

    def test_limit_defaults_on_missing_or_malformed(self):
        # Missing / malformed -> DEFAULT_ROWS_LIMIT (never fails the request).
        for bad in (None, "", "junk", {}, [], float("nan"), float("inf")):
            self.assertEqual(_parse_rows_limit(bad), DEFAULT_ROWS_LIMIT)

    def test_limit_bool_rejected(self):
        # bool is an int subclass; True must not read as a limit of 1.
        self.assertEqual(_parse_rows_limit(True), DEFAULT_ROWS_LIMIT)
        self.assertEqual(_parse_rows_limit(False), DEFAULT_ROWS_LIMIT)

    def test_limit_clamped_to_band(self):
        self.assertEqual(_parse_rows_limit(0), 1)
        self.assertEqual(_parse_rows_limit(-5), 1)
        self.assertEqual(_parse_rows_limit(1), 1)
        self.assertEqual(_parse_rows_limit(20), 20)
        self.assertEqual(_parse_rows_limit(MAX_ROWS_LIMIT), MAX_ROWS_LIMIT)
        self.assertEqual(_parse_rows_limit(MAX_ROWS_LIMIT + 1), MAX_ROWS_LIMIT)
        self.assertEqual(_parse_rows_limit(10 ** 9), MAX_ROWS_LIMIT)
        # A numeric string is accepted then clamped.
        self.assertEqual(_parse_rows_limit("100000"), MAX_ROWS_LIMIT)

    def test_offset_defaults_on_missing_or_malformed(self):
        for bad in (None, "", "junk", {}, [], float("nan"), float("inf")):
            self.assertEqual(_parse_rows_offset(bad), 0)

    def test_offset_bool_rejected(self):
        self.assertEqual(_parse_rows_offset(True), 0)
        self.assertEqual(_parse_rows_offset(False), 0)

    def test_offset_clamped_to_band(self):
        self.assertEqual(_parse_rows_offset(-3), 0)
        self.assertEqual(_parse_rows_offset(0), 0)
        self.assertEqual(_parse_rows_offset(40), 40)
        self.assertEqual(_parse_rows_offset(MAX_ROWS_OFFSET), MAX_ROWS_OFFSET)
        self.assertEqual(_parse_rows_offset(MAX_ROWS_OFFSET + 1), MAX_ROWS_OFFSET)
        self.assertEqual(_parse_rows_offset(10 ** 9), MAX_ROWS_OFFSET)
        self.assertEqual(_parse_rows_offset("500"), MAX_ROWS_OFFSET)


if __name__ == "__main__":
    unittest.main()


class HugeIntegerValueTests(unittest.TestCase):
    """SQL-INST-02: arbitrary-precision JSON ints must not inline unbounded."""

    def test_huge_int_filter_value_rejected(self):
        huge = int("9" * 600)
        with self.assertRaises(ValidationError) as ctx:
            validate_evidence_rows_request({
                "exchange_id": "ex1",
                "filters": [{"column": "amount", "op": "=", "values": [huge]}],
            })
        self.assertEqual(ctx.exception.code, "filter_value_too_long")

    def test_normal_int_filter_value_passes(self):
        validate_evidence_rows_request({
            "exchange_id": "ex1",
            "filters": [{"column": "amount", "op": "=", "values": [123456789]}],
        })
