# Plugin/owismind/tests/test_source_search.py
"""evidence.source_search: pure free-text search condition builder (accent-folded ILIKE)."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
from owismind.evidence.source_search import (  # noqa: E402
    build_search_condition,
    fold_needle,
    like_escape,
    MIN_NEEDLE_CHARS,
)

# Stub quoters keep the assertions readable and DSS-free.
def qi(name):
    return '"' + name + '"'
def ql(value):
    return "'" + str(value).replace("'", "''") + "'"


class FoldNeedleTests(unittest.TestCase):
    def test_lowercases_and_strips(self):
        self.assertEqual(fold_needle("  Algerie  "), "algerie")

    def test_accent_folds(self):
        # Every mapped accent collapses to its ascii base (à->a, é->e, ç->c, ...).
        self.assertEqual(fold_needle("Algérie Télécom"), "algerie telecom")
        # Uppercase accents lowercase first, then fold through the same map.
        self.assertEqual(fold_needle("çÇàÀ"), "ccaa")

    def test_accent_map_char_for_char(self):
        self.assertEqual(fold_needle("àáâãäåçèéêëìíîïñòóôõöùúûüýÿ"),
                         "aaaaaaceeeeiiiinooooouuuuyy")

    def test_none_and_non_str(self):
        self.assertEqual(fold_needle(None), "")
        self.assertEqual(fold_needle(123), "123")


class LikeEscapeTests(unittest.TestCase):
    def test_escapes_wildcards_and_backslash(self):
        # Backslash first so it cannot double-escape a following wildcard.
        self.assertEqual(like_escape("a%b_c"), "a\\%b\\_c")
        self.assertEqual(like_escape("a\\b"), "a\\\\b")
        self.assertEqual(like_escape("100%_done\\"), "100\\%\\_done\\\\")

    def test_plain_text_untouched(self):
        self.assertEqual(like_escape("algerie telecom"), "algerie telecom")


class BuildSearchConditionTests(unittest.TestCase):
    def test_short_needle_returns_none(self):
        # A folded needle shorter than MIN_NEEDLE_CHARS is "no search".
        self.assertLess(1, MIN_NEEDLE_CHARS + 1)  # sanity: min is 2
        self.assertIsNone(build_search_condition(["a", "b"], "x", qi, ql))
        self.assertIsNone(build_search_condition(["a"], "  ", qi, ql))
        self.assertIsNone(build_search_condition(["a"], None, qi, ql))

    def test_no_columns_returns_none(self):
        self.assertIsNone(build_search_condition([], "algerie", qi, ql))

    def test_single_ilike_over_concat_of_all_columns(self):
        cond = build_search_condition(["c1", "c2", "amount"], "Algerie", qi, ql)
        # ONE predicate: an accent-folded translate() over a concat_ws of EVERY column.
        self.assertIn("concat_ws(' ', \"c1\", \"c2\", \"amount\")", cond)
        self.assertIn("translate(lower(CAST(", cond)
        self.assertIn("ILIKE", cond)
        self.assertTrue(cond.rstrip().endswith("ESCAPE '\\'"))
        # Exactly one ILIKE (a single condition, not one per column).
        self.assertEqual(cond.count("ILIKE"), 1)

    def test_needle_folded_and_wrapped(self):
        cond = build_search_condition(["c"], "Algérie", qi, ql)
        # The needle is lowercased + accent-folded, then wrapped as %needle%.
        self.assertIn("'%algerie%'", cond)

    def test_accent_maps_inlined_as_literals(self):
        cond = build_search_condition(["c"], "abc", qi, ql)
        self.assertIn("'àáâãäåçèéêëìíîïñòóôõöùúûüýÿ'", cond)
        self.assertIn("'aaaaaaceeeeiiiinooooouuuuyy'", cond)

    def test_wildcards_in_needle_escaped(self):
        # A typed % / _ must match literally (escaped, then ESCAPE '\' on the ILIKE).
        cond = build_search_condition(["c"], "50%_x", qi, ql)
        self.assertIn("'%50\\%\\_x%'", cond)

    def test_single_quote_in_needle_doubled_by_quoter(self):
        cond = build_search_condition(["c"], "O'Brien", qi, ql)
        # fold lowercases -> o'brien; the literal quoter doubles the quote.
        self.assertIn("'%o''brien%'", cond)

    def test_identifiers_quoted_via_injected_fn(self):
        cond = build_search_condition(["weird name"], "abc", qi, ql)
        self.assertIn('"weird name"', cond)


if __name__ == "__main__":
    unittest.main()
