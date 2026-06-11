# Plugin/owismind/tests/test_pagination.py
"""Opaque keyset cursor round-trips; malformed input degrades safely to None."""
import os, sys, unittest
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.storage.pagination import encode_cursor, decode_cursor  # noqa: E402


class CursorTests(unittest.TestCase):
    def test_round_trip(self):
        tok = encode_cursor("2026-06-09T14:30:00", "abc123")
        self.assertIsInstance(tok, str)
        self.assertEqual(decode_cursor(tok), ("2026-06-09T14:30:00", "abc123"))

    def test_none_and_empty(self):
        self.assertIsNone(decode_cursor(None))
        self.assertIsNone(decode_cursor(""))

    def test_malformed_is_none(self):
        self.assertIsNone(decode_cursor("not-base64!!"))
        self.assertIsNone(decode_cursor("YWJj"))  # 'abc' -> no separator

    def test_session_id_with_separator_is_rejected(self):
        # separator is \x1f; a session id never contains it, but guard anyway.
        self.assertIsNone(decode_cursor(encode_cursor("t", "a\x1fb")))

if __name__ == "__main__":
    unittest.main()
