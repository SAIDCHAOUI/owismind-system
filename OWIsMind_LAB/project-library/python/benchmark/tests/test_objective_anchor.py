"""Tests for benchmark.judge objective anchor + normalizers (PURE, stdlib only).

Proves: numeric / currency matching with thousands separators and relative
tolerance; the table-answer case (an exact-ish figure found inside a serialized
SQL result cell); date parsing of common formats; normalized string containment;
list set-match; and ``n/a`` when no expected value. No DSS, no pandas.
"""

import unittest

from benchmark import judge
from benchmark.agent_capture import assemble_full_answer


def _sql_item(columns, rows, row_count=None):
    """Build a generated-SQL item shaped like agent_capture output."""
    return {
        "sql": "SELECT ...",
        "success": True,
        "row_count": row_count if row_count is not None else len(rows),
        "result": {"columns": list(columns), "rows": [list(r) for r in rows]},
    }


class TestNormalizeNumber(unittest.TestCase):
    def test_plain_int_and_float(self):
        self.assertEqual(judge.normalize_number("42"), 42.0)
        self.assertEqual(judge.normalize_number("42.5"), 42.5)
        self.assertEqual(judge.normalize_number(1234), 1234.0)

    def test_us_thousands_separators(self):
        self.assertEqual(judge.normalize_number("1,234,567.89"), 1234567.89)
        self.assertEqual(judge.normalize_number("$1,234,567.89"), 1234567.89)

    def test_eu_thousands_separators(self):
        self.assertEqual(judge.normalize_number("1.234.567,89"), 1234567.89)
        self.assertEqual(judge.normalize_number("1 234 567,89"), 1234567.89)

    def test_currency_and_percent_stripped(self):
        self.assertEqual(judge.normalize_number("€1 200,50"), 1200.5)
        self.assertEqual(judge.normalize_number("12,5%"), 12.5)

    def test_single_separator_ambiguity(self):
        # 1,234 with a 3-digit tail -> thousands grouping.
        self.assertEqual(judge.normalize_number("1,234"), 1234.0)
        self.assertEqual(judge.normalize_number("1.234"), 1234.0)
        # Non-3-digit tail -> decimal.
        self.assertEqual(judge.normalize_number("12,5"), 12.5)
        self.assertEqual(judge.normalize_number("12.5"), 12.5)

    def test_unparseable_and_bool(self):
        self.assertIsNone(judge.normalize_number("not a number"))
        self.assertIsNone(judge.normalize_number(None))
        self.assertIsNone(judge.normalize_number(True))
        self.assertIsNone(judge.normalize_number(""))


class TestNormalizeNumberMagnitude(unittest.TestCase):
    """Magnitude-aware parsing: a human reference like '36 millions' means 36e6, not 36."""

    def test_millions_word(self):
        self.assertEqual(judge.normalize_number("36 millions"), 36_000_000.0)
        self.assertEqual(judge.normalize_number("36 million"), 36_000_000.0)

    def test_million_abbrev_attached(self):
        self.assertEqual(judge.normalize_number("36M"), 36_000_000.0)
        self.assertEqual(judge.normalize_number("36m"), 36_000_000.0)
        self.assertEqual(judge.normalize_number("1.5M"), 1_500_000.0)

    def test_thousands_k(self):
        self.assertEqual(judge.normalize_number("500k"), 500_000.0)
        self.assertEqual(judge.normalize_number("1.5 k"), 1_500.0)

    def test_billions(self):
        self.assertEqual(judge.normalize_number("2 milliards"), 2_000_000_000.0)
        self.assertEqual(judge.normalize_number("1,2 Md"), 1_200_000_000.0)
        self.assertEqual(judge.normalize_number("1.5 bn"), 1_500_000_000.0)

    def test_no_false_magnitude_on_unit_words(self):
        # A word that merely starts with a magnitude letter must NOT scale the number.
        self.assertEqual(judge.normalize_number("36 meters"), 36.0)
        self.assertEqual(judge.normalize_number("36 minutes"), 36.0)

    def test_plain_numbers_unchanged(self):
        # Non-regression: numbers without a magnitude word behave exactly as before.
        self.assertEqual(judge.normalize_number("1,234,567.89"), 1234567.89)
        self.assertEqual(judge.normalize_number("42"), 42.0)


class TestMagnitudeAnchor(unittest.TestCase):
    """The '36 millions' case: a rounded human reference vs a precise agent figure."""

    def test_expected_millions_matches_rounded_answer(self):
        self.assertEqual(
            judge.objective_anchor("36 millions", "numeric", "the total is 36000000", []),
            judge.HIT)

    def test_expected_millions_vs_precise_is_miss(self):
        # 36 456 876 is 1.27% off 36e6, beyond the 0.5% anchor tolerance: the anchor MISSES
        # (the contextual judge is what rescues this case, not the anchor).
        self.assertEqual(
            judge.objective_anchor("36 millions", "numeric", "exactly 36456876", []),
            judge.MISS)

    def test_answer_side_magnitude_word(self):
        self.assertEqual(
            judge.objective_anchor("36 millions", "numeric", "around 36 millions", []),
            judge.HIT)

    def test_answer_side_unit_word_not_scaled(self):
        self.assertEqual(
            judge.objective_anchor("36 millions", "numeric", "it took 36 minutes", []),
            judge.MISS)


class TestNormalizeText(unittest.TestCase):
    def test_accents_case_whitespace(self):
        self.assertEqual(judge.normalize_text("  Maroc   Telecom  "),
                         "maroc telecom")
        # Accent folding.
        self.assertEqual(judge.normalize_text("Societe Generale"),
                         judge.normalize_text("Société Générale"))

    def test_none_and_non_string(self):
        self.assertEqual(judge.normalize_text(None), "")
        self.assertEqual(judge.normalize_text(123), "123")


class TestNumericAnchor(unittest.TestCase):
    def test_numeric_hit_in_text(self):
        full = "The total revenue is 1,234,567.89 EUR."
        self.assertEqual(
            judge.objective_anchor("1234567.89", "numeric", full, []), judge.HIT)

    def test_currency_hit_with_separators(self):
        full = "Revenue: 1.234.567,89"  # EU formatting in the answer
        self.assertEqual(
            judge.objective_anchor("1234567.89", "currency", full, []), judge.HIT)

    def test_numeric_within_relative_tolerance(self):
        # Default tolerance 0.5%: 1000 vs 1004 is within tolerance.
        self.assertEqual(
            judge.objective_anchor("1000", "numeric", "got 1004 units", []),
            judge.HIT)
        # 1000 vs 1010 (1%) is outside the default tolerance.
        self.assertEqual(
            judge.objective_anchor("1000", "numeric", "got 1010 units", []),
            judge.MISS)

    def test_numeric_miss(self):
        self.assertEqual(
            judge.objective_anchor("999999", "numeric", "the answer is 42", []),
            judge.MISS)

    def test_zero_target_exact(self):
        self.assertEqual(
            judge.objective_anchor("0", "numeric", "the budget is 0 EUR", []),
            judge.HIT)


class TestTableAnswerCase(unittest.TestCase):
    """The key fix: the figure lives in a serialized SQL result cell, not the text."""

    def test_number_found_in_flattened_sql_cell(self):
        items = [_sql_item(["account_name", "revenue"],
                           [["Maroc Telecom", 1234567.89], ["Airbus", 987654.0]])]
        # The agent's TEXT is generic; the figure is only in the table.
        full = assemble_full_answer("Here is the breakdown by account.", items, [])
        self.assertEqual(
            judge.objective_anchor("1234567.89", "numeric", full, items),
            judge.HIT)

    def test_string_found_in_table_cell(self):
        items = [_sql_item(["account_name", "revenue"],
                           [["Maroc Telecom", 1234567.89]])]
        full = assemble_full_answer("", items, [])
        self.assertEqual(
            judge.objective_anchor("Maroc Telecom", "string", full, items),
            judge.HIT)

    def test_anchor_searches_cells_even_if_full_answer_blank(self):
        # Defensive: the cells alone carry the value.
        items = [_sql_item(["v"], [[42.0]])]
        self.assertEqual(
            judge.objective_anchor("42", "numeric", "", items), judge.HIT)


class TestDateAnchor(unittest.TestCase):
    def test_iso_date(self):
        self.assertEqual(
            judge.objective_anchor("2025-12-31", "date",
                                   "closed on 2025-12-31.", []),
            judge.HIT)

    def test_cross_format_match(self):
        # Expected ISO, answer uses dd/mm/yyyy: same date -> hit.
        self.assertEqual(
            judge.objective_anchor("2025-12-31", "date",
                                   "le 31/12/2025 exactement", []),
            judge.HIT)

    def test_date_miss(self):
        self.assertEqual(
            judge.objective_anchor("2025-12-31", "date",
                                   "it was 2024-01-01", []),
            judge.MISS)


class TestStringAnchor(unittest.TestCase):
    def test_normalized_contains(self):
        self.assertEqual(
            judge.objective_anchor("maroc telecom", "string",
                                   "The top account is Maroc Telecom!", []),
            judge.HIT)

    def test_accent_insensitive(self):
        self.assertEqual(
            judge.objective_anchor("societe generale", "string",
                                   "Client: Société Générale", []),
            judge.HIT)

    def test_string_miss(self):
        self.assertEqual(
            judge.objective_anchor("orange", "string", "the client is vodafone", []),
            judge.MISS)


class TestListAnchor(unittest.TestCase):
    def test_set_match_all_present(self):
        full = "The phases are ACTUALS, BUDGET and FORECAST."
        self.assertEqual(
            judge.objective_anchor("ACTUALS, BUDGET, FORECAST", "list", full, []),
            judge.HIT)

    def test_list_order_independent(self):
        full = "Forecast and budget and actuals."
        self.assertEqual(
            judge.objective_anchor("ACTUALS; BUDGET; FORECAST", "list", full, []),
            judge.HIT)

    def test_list_miss_when_one_missing(self):
        full = "Only ACTUALS and BUDGET are present."
        self.assertEqual(
            judge.objective_anchor("ACTUALS, BUDGET, FORECAST", "list", full, []),
            judge.MISS)

    def test_list_items_across_table_cells(self):
        items = [_sql_item(["phase"], [["ACTUALS"], ["BUDGET"], ["FORECAST"]])]
        full = assemble_full_answer("Phases below.", items, [])
        self.assertEqual(
            judge.objective_anchor("ACTUALS, BUDGET, FORECAST", "list", full, items),
            judge.HIT)


class TestNaAndUnknownType(unittest.TestCase):
    def test_na_when_no_expected_value(self):
        self.assertEqual(
            judge.objective_anchor(None, "numeric", "anything", []), judge.NA)
        self.assertEqual(
            judge.objective_anchor("", "string", "anything", []), judge.NA)
        self.assertEqual(
            judge.objective_anchor("   ", "string", "anything", []), judge.NA)

    def test_unknown_type_falls_back_to_string(self):
        self.assertEqual(
            judge.objective_anchor("orange", "weird_type",
                                   "the brand is Orange", []),
            judge.HIT)

    def test_never_raises_on_garbage(self):
        # Hostile inputs must degrade to miss / n-a, never raise.
        self.assertEqual(
            judge.objective_anchor("x", "numeric", None, None), judge.MISS)
        self.assertEqual(
            judge.objective_anchor(None, None, None, None), judge.NA)


class TestNanInputs(unittest.TestCase):
    """Pandas renders an empty cell as a float NaN; the anchor must not crash."""

    def test_nan_expected_value_is_na(self):
        nan = float("nan")
        self.assertEqual(
            judge.objective_anchor(nan, nan, "the answer is 42", []), judge.NA)

    def test_nan_type_with_value_uses_string_rule(self):
        nan = float("nan")
        self.assertEqual(
            judge.objective_anchor("Paris", nan, "the city is Paris", []),
            judge.HIT)

    def test_float_expected_value_numeric(self):
        # An expected_value read as a float (numeric column) still matches.
        self.assertEqual(
            judge.objective_anchor(42.0, "numeric", "there are 42 tickets", []),
            judge.HIT)

    def test_nan_full_answer_does_not_crash(self):
        nan = float("nan")
        item = _sql_item(["amount"], [[1234]])
        self.assertEqual(
            judge.objective_anchor("1234", "numeric", nan, [item]), judge.HIT)


if __name__ == "__main__":
    unittest.main()
