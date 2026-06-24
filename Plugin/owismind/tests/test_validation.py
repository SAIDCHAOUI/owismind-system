"""Unit tests for owismind.security.validation (pure module - no DSS env required).

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


from owismind.security.validation import (  # noqa: E402
    DEFAULT_AGENT_ICON,
    MAX_AGENT_DESC_CHARS,
    MAX_AGENT_TAGLINE_CHARS,
    validate_agent_meta,
)


class TestAgentMeta(unittest.TestCase):
    """Admin-authored agent profile: sanitized + bounded, never raising."""

    def test_none_or_garbage_yields_empty_profile(self):
        for raw in (None, "x", 42, [], True):
            meta = validate_agent_meta(raw)
            self.assertEqual(meta["tagline"], "")
            self.assertEqual(meta["description"], "")
            self.assertEqual(meta["capabilities"], [])
            self.assertEqual(meta["tools"], [])
            self.assertEqual(meta["icon"], DEFAULT_AGENT_ICON)
            self.assertEqual(meta["badge"], "")

    def test_strings_are_stripped_and_clamped(self):
        meta = validate_agent_meta(
            {"tagline": "  hello  ", "description": "x" * (MAX_AGENT_DESC_CHARS + 50)}
        )
        self.assertEqual(meta["tagline"], "hello")
        self.assertEqual(len(meta["description"]), MAX_AGENT_DESC_CHARS)

    def test_tagline_is_length_capped(self):
        meta = validate_agent_meta({"tagline": "a" * (MAX_AGENT_TAGLINE_CHARS + 10)})
        self.assertEqual(len(meta["tagline"]), MAX_AGENT_TAGLINE_CHARS)

    def test_lists_drop_empties_and_cap_count(self):
        meta = validate_agent_meta(
            {
                "capabilities": ["a", "  ", "", "b", 1, None] + ["c"] * 20,
                "tools": ["t1", "  t2  ", ""],
            }
        )
        # Empties / non-strings dropped, count capped at 8.
        self.assertEqual(len(meta["capabilities"]), 8)
        self.assertEqual(meta["capabilities"][0], "a")
        self.assertEqual(meta["capabilities"][1], "b")
        self.assertEqual(meta["tools"], ["t1", "t2"])

    def test_icon_must_be_whitelisted(self):
        self.assertEqual(validate_agent_meta({"icon": "trendUp"})["icon"], "trendUp")
        # An unknown / unsafe icon name falls back to the default (never rendered raw).
        self.assertEqual(validate_agent_meta({"icon": "<script>"})["icon"], DEFAULT_AGENT_ICON)
        self.assertEqual(validate_agent_meta({"icon": 123})["icon"], DEFAULT_AGENT_ICON)

    def test_badge_must_be_in_enum(self):
        self.assertEqual(validate_agent_meta({"badge": "new"})["badge"], "new")
        self.assertEqual(validate_agent_meta({"badge": "bogus"})["badge"], "")

    def test_unhashable_icon_or_badge_never_raises(self):
        # JSON arrays/objects arrive as list/dict: the membership test must not raise.
        for raw in ({"icon": [], "badge": {}}, {"icon": {"a": 1}, "badge": ["x"]}):
            meta = validate_agent_meta(raw)
            self.assertEqual(meta["icon"], DEFAULT_AGENT_ICON)
            self.assertEqual(meta["badge"], "")

    def test_control_chars_are_stripped(self):
        meta = validate_agent_meta({"tagline": "ab\x00\x07cd", "description": "x\ny"})
        self.assertNotIn("\x00", meta["tagline"])
        self.assertNotIn("\x07", meta["tagline"])

    def test_modes_flag_defaults_off_and_coerces_to_bool(self):
        # Absent / garbage profile -> modes off (the picker stays hidden, no token sent).
        self.assertIs(validate_agent_meta(None)["modes"], False)
        self.assertIs(validate_agent_meta({})["modes"], False)
        # Explicit truthy/falsey values coerce to a strict bool.
        self.assertIs(validate_agent_meta({"modes": True})["modes"], True)
        self.assertIs(validate_agent_meta({"modes": False})["modes"], False)
        self.assertIs(validate_agent_meta({"modes": 1})["modes"], True)
        self.assertIs(validate_agent_meta({"modes": "yes"})["modes"], True)
        self.assertIs(validate_agent_meta({"modes": 0})["modes"], False)
        self.assertIs(validate_agent_meta({"modes": ""})["modes"], False)


if __name__ == "__main__":
    unittest.main()
