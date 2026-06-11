# Plugin/owismind/tests/test_conversations_limit.py
"""Sidebar page-size clamp: [1, 60], default 30, never raises."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.security.validation import (  # noqa: E402
    DEFAULT_CONV_PAGE, MAX_CONV_PAGE, MIN_CONV_PAGE, validate_conversations_limit,
)


class ConvPageTests(unittest.TestCase):
    def test_constants(self):
        self.assertEqual((MIN_CONV_PAGE, MAX_CONV_PAGE, DEFAULT_CONV_PAGE), (1, 60, 30))

    def test_default_and_invalid(self):
        self.assertEqual(validate_conversations_limit(None), 30)
        self.assertEqual(validate_conversations_limit("x"), 30)

    def test_in_range(self):
        self.assertEqual(validate_conversations_limit(10), 10)
        self.assertEqual(validate_conversations_limit("45"), 45)

    def test_clamped(self):
        self.assertEqual(validate_conversations_limit(0), 1)
        self.assertEqual(validate_conversations_limit(-3), 1)
        self.assertEqual(validate_conversations_limit(61), 60)
        self.assertEqual(validate_conversations_limit(99999), 60)

if __name__ == "__main__":
    unittest.main()
