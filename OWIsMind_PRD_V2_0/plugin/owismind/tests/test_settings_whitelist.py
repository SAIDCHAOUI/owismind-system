# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_settings_whitelist.py
"""storage.settings - the agent whitelist ENFORCEMENT point, tested for real.

Non-negotiable rule #4: the frontend sends an opaque logical_key and the
backend resolves it against the admin-enabled whitelist; a forged, stale or
disabled key must resolve to None. Before this file the function was 0%
covered: every test that touched the path replaced resolve_enabled_agent with
a lambda, so nothing proved the real refusals (audit 2026-08-05, TS-01).

Also locks the TTL cache added on this hot path (audit BE-04): the RAW JSON
string is cached (never the decoded list), every caller gets private dicts,
and an admin save is visible immediately (explicit invalidation).
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402


_dss_stub.install()

import json  # noqa: E402

from owismind.storage import settings  # noqa: E402

_AGENTS = [
    {"logical_key": "ag_rev", "project_key": "P", "agent_id": "038G7mlF",
     "label": "Revenus", "profile": {"tagline": "x"}},
    {"logical_key": "ag_tick", "project_key": "P", "agent_id": "NcE9LD2i",
     "label": "Tickets", "profile": {}},
    {"label": "no logical key: must never resolve"},
]


class _RawPatch(object):
    """Patch settings._read_setting_raw with a scripted payload + call count."""

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def __call__(self, key):
        self.calls += 1
        return self.payload


class TestResolveEnabledAgent(unittest.TestCase):
    def setUp(self):
        settings._invalidate_enabled_cache()
        self._saved = settings._read_setting_raw
        self.raw = _RawPatch(json.dumps(_AGENTS))
        settings._read_setting_raw = self.raw
        self.addCleanup(self._restore)

    def _restore(self):
        settings._read_setting_raw = self._saved
        settings._invalidate_enabled_cache()

    def test_valid_key_resolves_to_its_whole_entry(self):
        entry = settings.resolve_enabled_agent("ag_rev")
        self.assertEqual(entry["agent_id"], "038G7mlF")
        self.assertEqual(entry["label"], "Revenus")

    def test_forged_key_resolves_to_none(self):
        self.assertIsNone(settings.resolve_enabled_agent("ag_forged"))

    def test_empty_and_none_keys_resolve_to_none(self):
        self.assertIsNone(settings.resolve_enabled_agent(""))
        self.assertIsNone(settings.resolve_enabled_agent(None))

    def test_stale_key_resolves_to_none_after_admin_removal(self):
        self.assertIsNotNone(settings.resolve_enabled_agent("ag_tick"))
        # The admin removed the agent: the raw payload changes and the cache is
        # invalidated (as set_enabled_agents does after every save).
        self.raw.payload = json.dumps([_AGENTS[0]])
        settings._invalidate_enabled_cache()
        self.assertIsNone(settings.resolve_enabled_agent("ag_tick"))

    def test_entry_without_logical_key_never_resolves(self):
        self.assertIsNone(settings.resolve_enabled_agent("no logical key"))

    def test_malformed_payload_yields_empty_whitelist(self):
        self.raw.payload = "{not json"
        settings._invalidate_enabled_cache()
        self.assertEqual(settings.get_enabled_agents(), [])
        self.assertIsNone(settings.resolve_enabled_agent("ag_rev"))

    def test_non_list_payload_yields_empty_whitelist(self):
        self.raw.payload = json.dumps({"logical_key": "ag_rev"})
        settings._invalidate_enabled_cache()
        self.assertEqual(settings.get_enabled_agents(), [])


class TestEnabledAgentsCache(unittest.TestCase):
    def setUp(self):
        settings._invalidate_enabled_cache()
        self._saved = settings._read_setting_raw
        self.raw = _RawPatch(json.dumps(_AGENTS))
        settings._read_setting_raw = self.raw
        self.addCleanup(self._restore)

    def _restore(self):
        settings._read_setting_raw = self._saved
        settings._invalidate_enabled_cache()

    def test_reads_within_ttl_hit_the_cache(self):
        settings.get_enabled_agents()
        settings.get_enabled_agents()
        settings.resolve_enabled_agent("ag_rev")
        self.assertEqual(self.raw.calls, 1)

    def test_invalidation_forces_a_fresh_read(self):
        settings.get_enabled_agents()
        settings._invalidate_enabled_cache()
        settings.get_enabled_agents()
        self.assertEqual(self.raw.calls, 2)

    def test_callers_get_private_dicts_never_shared_state(self):
        first = settings.get_enabled_agents()
        first[0]["agent_id"] = "TAMPERED"
        first[0]["profile"]["tagline"] = "TAMPERED"
        fresh = settings.get_enabled_agents()
        self.assertEqual(fresh[0]["agent_id"], "038G7mlF")
        self.assertEqual(fresh[0]["profile"]["tagline"], "x")
        self.assertEqual(self.raw.calls, 1)  # both served by the cached RAW string


class TestChatStartWhitelistRefusal(unittest.TestCase):
    """Route-level proof of rule #4: with an EMPTY whitelist, a valid
    /chat/start payload carrying any logical key answers
    ('agent_not_enabled', 404) before any run, write or content log."""

    def setUp(self):
        _dss_stub.install_flask()
        from owismind.api import routes
        self.routes = routes
        self._orig = {
            "resolve_identity": routes.resolve_identity,
            "is_configured": routes.sql_config.is_configured,
        }
        routes.resolve_identity = lambda headers: {
            "user_id": "u", "display_name": "U", "groups": []}
        routes.sql_config.is_configured = lambda: True
        settings._invalidate_enabled_cache()
        self._saved_raw = settings._read_setting_raw
        settings._read_setting_raw = lambda key: json.dumps([])
        _dss_stub.REQUEST.headers = {}
        _dss_stub.REQUEST._json = {"session_id": "sess-1", "message": "hello",
                                   "agent_key": "ag_forged"}
        _dss_stub.REQUEST.method = "POST"

    def tearDown(self):
        self.routes.resolve_identity = self._orig["resolve_identity"]
        self.routes.sql_config.is_configured = self._orig["is_configured"]
        settings._read_setting_raw = self._saved_raw
        settings._invalidate_enabled_cache()
        _dss_stub.REQUEST.headers = {}
        _dss_stub.REQUEST._json = None

    def test_forged_key_gets_agent_not_enabled_404(self):
        result = self.routes.chat_start()
        payload = result[0] if isinstance(result, tuple) else result
        status = result[1] if isinstance(result, tuple) else 200
        self.assertEqual(payload["error"], "agent_not_enabled")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()
