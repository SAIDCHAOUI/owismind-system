"""Unit tests for owismind.security.validation (pure module — no DSS env required).

Run:  python3 -m unittest discover -s Plugin/owismind/tests

These guard the request-shape/bounds checks that protect every chat write. The
DSS-env-dependent invariants (SQL escaping, identity scoping, whitelist resolution, the
stream state machine) need the dataiku/pandas runtime and are listed in tests/README.md.
This directory lives OUTSIDE python-lib/, so it is never packaged into the plugin zip.
"""

import os
import sys
import unittest

# Put python-lib on the path so `owismind.*` imports resolve without installing anything.
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.security.validation import (  # noqa: E402
    MAX_AGENT_KEY_LENGTH,
    MAX_MESSAGE_LENGTH,
    MAX_SESSION_ID_LENGTH,
    ValidationError,
    validate_chat_start_request,
    validate_message,
)


class ValidateMessageTests(unittest.TestCase):
    def test_rejects_non_dict(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_message("nope")
        self.assertEqual(ctx.exception.code, "invalid_payload")

    def test_rejects_missing_message(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_message({})
        self.assertEqual(ctx.exception.code, "missing_message")

    def test_rejects_non_string_message(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_message({"message": 123})
        self.assertEqual(ctx.exception.code, "missing_message")

    def test_rejects_empty_after_strip(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_message({"message": "   "})
        self.assertEqual(ctx.exception.code, "empty_message")

    def test_rejects_too_long(self):
        with self.assertRaises(ValidationError) as ctx:
            validate_message({"message": "x" * (MAX_MESSAGE_LENGTH + 1)})
        self.assertEqual(ctx.exception.code, "message_too_long")

    def test_accepts_and_strips(self):
        self.assertEqual(validate_message({"message": "  hi  "}), "hi")


class ValidateChatStartTests(unittest.TestCase):
    def _ok(self):
        return {"session_id": "s-1", "message": "hello", "agent_key": "ag_abc123"}

    def test_happy_path(self):
        sid, msg, key = validate_chat_start_request(self._ok())
        self.assertEqual((sid, msg, key), ("s-1", "hello", "ag_abc123"))

    def test_missing_session_id(self):
        payload = self._ok()
        del payload["session_id"]
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "missing_session_id")

    def test_empty_session_id(self):
        payload = self._ok()
        payload["session_id"] = "  "
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "empty_session_id")

    def test_session_id_too_long(self):
        payload = self._ok()
        payload["session_id"] = "s" * (MAX_SESSION_ID_LENGTH + 1)
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "session_id_too_long")

    def test_missing_agent_key(self):
        payload = self._ok()
        del payload["agent_key"]
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "missing_agent_key")

    def test_empty_agent_key(self):
        payload = self._ok()
        payload["agent_key"] = "   "
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "empty_agent_key")

    def test_agent_key_too_long(self):
        payload = self._ok()
        payload["agent_key"] = "a" * (MAX_AGENT_KEY_LENGTH + 1)
        with self.assertRaises(ValidationError) as ctx:
            validate_chat_start_request(payload)
        self.assertEqual(ctx.exception.code, "agent_key_too_long")


if __name__ == "__main__":
    unittest.main()
