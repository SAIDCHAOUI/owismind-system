# Plugin/owismind/tests/test_history_limit.py
"""Unit tests for validate_history_limit (pure, bounds the agent-context window)."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.security.validation import (  # noqa: E402
    DEFAULT_HISTORY_LIMIT, MAX_HISTORY_LIMIT, MIN_HISTORY_LIMIT,
    validate_history_limit, validate_optional_exchange_id,
)


class HistoryLimitTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((MIN_HISTORY_LIMIT, MAX_HISTORY_LIMIT, DEFAULT_HISTORY_LIMIT), (10, 50, 20))

    def test_default_when_missing_or_invalid(self):
        self.assertEqual(validate_history_limit(None), 20)
        self.assertEqual(validate_history_limit("abc"), 20)
        self.assertEqual(validate_history_limit({}), 20)

    def test_in_range(self):
        self.assertEqual(validate_history_limit(10), 10)
        self.assertEqual(validate_history_limit("35"), 35)
        self.assertEqual(validate_history_limit(50), 50)

    def test_clamped(self):
        self.assertEqual(validate_history_limit(9), 10)
        self.assertEqual(validate_history_limit(0), 10)
        self.assertEqual(validate_history_limit(51), 50)
        self.assertEqual(validate_history_limit(10000), 50)


class OptionalExchangeIdTests(unittest.TestCase):
    def test_none_and_empty(self):
        self.assertIsNone(validate_optional_exchange_id(None))
        self.assertIsNone(validate_optional_exchange_id(""))
    def test_valid(self):
        self.assertEqual(validate_optional_exchange_id("abc123"), "abc123")
    def test_too_long_or_nonstr_dropped(self):
        self.assertIsNone(validate_optional_exchange_id("x" * 200))
        self.assertIsNone(validate_optional_exchange_id(123))

if __name__ == "__main__":
    unittest.main()
