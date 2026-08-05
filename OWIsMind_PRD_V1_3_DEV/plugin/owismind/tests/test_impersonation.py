# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_impersonation.py
"""Admin impersonation ("act as user", read-only): the pure resolver
(``security.impersonation.effective_identity``) and the route-level behaviour
(READ routes scope to the TARGET, WRITE routes 403 while impersonating, a
non-admin header is ignored everywhere).

The test env has no Flask and no live DSS runtime, so two minimal stubs are
installed first: ``dataiku`` (so the storage modules import) and ``flask``
(Blueprint / jsonify / request) so ``api.routes`` + ``security.impersonation``
import and their view functions are CALLABLE directly. ``jsonify`` returns the
plain dict, so a route's return value is either that dict (200) or a
``(dict, status)`` tuple (error) - exactly what the handlers build. The shared
``flask.request`` stub also carries the ``X-OWI-Impersonate`` header per test.
"""
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402


# The shared request stub: mutating it drives what the routes see (it is the object
# ``flask.request`` - and therefore ``routes.request`` - is bound to).
_REQUEST = _dss_stub.REQUEST

_dss_stub.install()
_dss_stub.install_flask()

from owismind.api import routes                            # noqa: E402
from owismind.security import identity as identity_mod      # noqa: E402
from owismind.security import impersonation                 # noqa: E402
from owismind.storage import admin as admin_mod             # noqa: E402
from owismind.storage import chat_v5 as chat_v5_mod         # noqa: E402
from owismind.storage import sql_config                     # noqa: E402
from owismind.storage import settings as settings_mod       # noqa: E402
from owismind.storage import budget as budget_mod           # noqa: E402
from owismind.storage import migrations as migrations_mod   # noqa: E402
from owismind.agents import stream_manager                  # noqa: E402


def _set_request(headers=None, args=None, json=None, method="GET"):
    _REQUEST.headers = headers or {}
    _REQUEST.args = args or {}
    _REQUEST._json = json
    _REQUEST.method = method


def _status_of(result):
    """The HTTP status of a view return: 200 for a bare dict, the int for a tuple."""
    return result[1] if isinstance(result, tuple) else 200


def _body_of(result):
    return result[0] if isinstance(result, tuple) else result


# --- The pure resolver -------------------------------------------------------
class EffectiveIdentityTests(unittest.TestCase):
    """``effective_identity`` honors the header only for a configured store + an admin
    caller + a valid target; NEVER raises; no DB call when the header is absent."""

    REAL = {"user_id": "admin.user", "display_name": "Admin", "groups": ["g1"]}

    def setUp(self):
        self._orig = {
            "is_configured": sql_config.is_configured,
            "is_admin": admin_mod.is_admin,
        }
        sql_config.is_configured = lambda: True
        admin_mod.is_admin = lambda uid: True
        _set_request()

    def tearDown(self):
        sql_config.is_configured = self._orig["is_configured"]
        admin_mod.is_admin = self._orig["is_admin"]
        _set_request()

    def test_no_header_returns_real_not_impersonating(self):
        # No header -> act as self; admin.is_admin must NOT be called (no DB cost).
        admin_mod.is_admin = lambda uid: self.fail("is_admin called without a header")
        _set_request(headers={})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")
        self.assertEqual(eff["real_user_id"], "admin.user")
        # Real fields are preserved.
        self.assertEqual(eff["groups"], ["g1"])

    def test_admin_header_swaps_to_target(self):
        _set_request(headers={"X-OWI-Impersonate": "target.user"})
        eff = impersonation.effective_identity(self.REAL)
        self.assertTrue(eff["impersonating"])
        self.assertEqual(eff["user_id"], "target.user")
        self.assertEqual(eff["real_user_id"], "admin.user")
        self.assertEqual(eff["groups"], [])
        # Display name is derived from the target login (prenom.nom -> Prenom).
        self.assertEqual(eff["display_name"], "Target")

    def test_header_stripped_target(self):
        _set_request(headers={"X-OWI-Impersonate": "  target.user  "})
        eff = impersonation.effective_identity(self.REAL)
        self.assertTrue(eff["impersonating"])
        self.assertEqual(eff["user_id"], "target.user")

    def test_non_admin_header_ignored(self):
        admin_mod.is_admin = lambda uid: False
        _set_request(headers={"X-OWI-Impersonate": "target.user"})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")

    def test_storage_not_configured_ignored(self):
        sql_config.is_configured = lambda: False
        # is_admin must not even be reached when storage is not configured.
        admin_mod.is_admin = lambda uid: self.fail("is_admin called while unconfigured")
        _set_request(headers={"X-OWI-Impersonate": "target.user"})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")

    def test_blank_header_treated_as_absent(self):
        _set_request(headers={"X-OWI-Impersonate": "   "})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")

    def test_overlong_target_ignored(self):
        _set_request(headers={"X-OWI-Impersonate": "x" * 257})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")

    def test_admin_check_error_degrades_to_self(self):
        # Any unexpected error -> never raise, act as self.
        def _boom(uid):
            raise RuntimeError("db down")
        admin_mod.is_admin = _boom
        _set_request(headers={"X-OWI-Impersonate": "target.user"})
        eff = impersonation.effective_identity(self.REAL)
        self.assertFalse(eff["impersonating"])
        self.assertEqual(eff["user_id"], "admin.user")


# --- Route-level behaviour ---------------------------------------------------
class _BaseRouteTest(unittest.TestCase):
    """Patch identity / admin / config so the impersonation resolver in the routes
    grants (admin caller + configured store). Subclasses script the data layer."""

    REAL_ADMIN = {"user_id": "admin.user", "display_name": "Admin", "groups": []}

    def setUp(self):
        self._orig = {
            "resolve_identity": routes.resolve_identity,
            "is_configured": sql_config.is_configured,
            "is_admin": admin_mod.is_admin,
            "ensure_chat_table": routes.ensure_chat_table,
        }
        routes.resolve_identity = lambda headers: dict(self.REAL_ADMIN)
        sql_config.is_configured = lambda: True
        admin_mod.is_admin = lambda uid: True
        routes.ensure_chat_table = lambda: None
        _set_request()

    def tearDown(self):
        routes.resolve_identity = self._orig["resolve_identity"]
        sql_config.is_configured = self._orig["is_configured"]
        admin_mod.is_admin = self._orig["is_admin"]
        routes.ensure_chat_table = self._orig["ensure_chat_table"]
        _set_request()


class ReadRouteScopesToTargetTests(_BaseRouteTest):
    def test_conversations_scopes_to_target(self):
        seen = {}

        def _list(user_id, cursor_token, limit):
            seen["user_id"] = user_id
            return {"conversations": [{"session_id": "s1"}],
                    "next_cursor": None, "has_more": False}

        orig = chat_v5_mod.list_conversations
        chat_v5_mod.list_conversations = _list
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         args={"limit": "30"})
            result = routes.conversations()
        finally:
            chat_v5_mod.list_conversations = orig
        self.assertEqual(_status_of(result), 200)
        # The list read was scoped to the IMPERSONATED target, not the admin.
        self.assertEqual(seen["user_id"], "target.user")

    def test_conversation_scopes_to_target(self):
        seen = {}

        def _msgs(user_id, session_id):
            seen["user_id"] = user_id
            seen["session_id"] = session_id
            return [{"exchange_id": "x1"}]

        orig = chat_v5_mod.messages_for_session
        chat_v5_mod.messages_for_session = _msgs
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         args={"session_id": "sess-1"})
            result = routes.conversation()
        finally:
            chat_v5_mod.messages_for_session = orig
        self.assertEqual(_status_of(result), 200)
        self.assertEqual(seen["user_id"], "target.user")
        self.assertEqual(seen["session_id"], "sess-1")

    def test_conversations_non_admin_header_scopes_to_self(self):
        # A non-admin sending the header gets no impersonation: scope = themselves.
        admin_mod.is_admin = lambda uid: False
        seen = {}

        def _list(user_id, cursor_token, limit):
            seen["user_id"] = user_id
            return {"conversations": [], "next_cursor": None, "has_more": False}

        orig = chat_v5_mod.list_conversations
        chat_v5_mod.list_conversations = _list
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"})
            result = routes.conversations()
        finally:
            chat_v5_mod.list_conversations = orig
        self.assertEqual(_status_of(result), 200)
        self.assertEqual(seen["user_id"], "admin.user")


class MeRouteTests(_BaseRouteTest):
    def test_me_reports_impersonation_and_skips_record(self):
        recorded = {"called": False}

        def _record(identity):
            recorded["called"] = True

        orig_record = admin_mod.record_user
        admin_mod.record_user = _record
        # Effective user (a normal target) is NOT admin -> is_admin False while
        # impersonating; the admin's own row drove the swap.
        admin_mod.is_admin = lambda uid: uid == "admin.user"
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"}, method="POST")
            result = routes.me()
        finally:
            admin_mod.record_user = orig_record
        self.assertEqual(_status_of(result), 200)
        body = _body_of(result)
        self.assertTrue(body["impersonating"])
        self.assertEqual(body["real_user_id"], "admin.user")
        self.assertEqual(body["user_id"], "target.user")
        # is_admin reflects the EFFECTIVE (target) user -> False.
        self.assertFalse(body["is_admin"])
        # record_user/bootstrap is SKIPPED for the impersonated user.
        self.assertFalse(recorded["called"])

    def test_me_records_real_user_when_not_impersonating(self):
        recorded = {"user_id": None}

        def _record(identity):
            recorded["user_id"] = identity["user_id"]

        orig_record = admin_mod.record_user
        admin_mod.record_user = _record
        try:
            _set_request(headers={}, method="POST")
            result = routes.me()
        finally:
            admin_mod.record_user = orig_record
        body = _body_of(result)
        self.assertFalse(body["impersonating"])
        self.assertEqual(body["real_user_id"], "admin.user")
        self.assertEqual(body["user_id"], "admin.user")
        self.assertTrue(body["is_admin"])
        # The real, non-impersonated caller IS recorded.
        self.assertEqual(recorded["user_id"], "admin.user")


class WriteRouteBlockedTests(_BaseRouteTest):
    def test_chat_start_403_while_impersonating(self):
        # If the write block is missing, the run would proceed; guard the data layer
        # so a regression is loud rather than silently spending under the user's name.
        def _boom(*a, **k):
            self.fail("save_user_message reached while impersonating")

        orig = chat_v5_mod.save_user_message
        chat_v5_mod.save_user_message = _boom
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         json={"session_id": "s", "message": "hi", "agent_key": "ag_x"},
                         method="POST")
            result = routes.chat_start()
        finally:
            chat_v5_mod.save_user_message = orig
        self.assertEqual(_status_of(result), 403)
        self.assertEqual(_body_of(result)["error"], "impersonation_read_only")

    def test_chat_feedback_403_while_impersonating(self):
        def _boom(*a, **k):
            self.fail("save_feedback reached while impersonating")

        orig = chat_v5_mod.save_feedback
        chat_v5_mod.save_feedback = _boom
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         json={"exchange_id": "x1", "rating": 1}, method="POST")
            result = routes.chat_feedback()
        finally:
            chat_v5_mod.save_feedback = orig
        self.assertEqual(_status_of(result), 403)
        self.assertEqual(_body_of(result)["error"], "impersonation_read_only")

    def test_chat_stop_403_while_impersonating(self):
        def _boom(*a, **k):
            self.fail("request_stop reached while impersonating")

        orig = stream_manager.request_stop
        stream_manager.request_stop = _boom
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         json={"run_id": "r1"}, method="POST")
            result = routes.chat_stop()
        finally:
            stream_manager.request_stop = orig
        self.assertEqual(_status_of(result), 403)
        self.assertEqual(_body_of(result)["error"], "impersonation_read_only")

    def test_chat_start_non_admin_header_not_blocked(self):
        # A non-admin's header is ignored, so the WRITE route is NOT blocked for them
        # (they act as themselves). It proceeds past the impersonation guard into the
        # normal validation path; we stop it at the data layer to keep the test pure.
        admin_mod.is_admin = lambda uid: False
        saved = {"called": False}

        def _save(*a, **k):
            saved["called"] = True
            return "exch-1"

        orig_save = chat_v5_mod.save_user_message
        orig_resolve = settings_mod.resolve_enabled_agent
        orig_can = stream_manager.can_accept
        orig_budget = budget_mod.has_budget
        orig_start = stream_manager.start_run
        chat_v5_mod.save_user_message = _save
        settings_mod.resolve_enabled_agent = lambda key: {
            "project_key": "P", "agent_id": "A"}
        stream_manager.can_accept = lambda uid: (True, None)
        budget_mod.has_budget = lambda uid: (True, {})
        stream_manager.start_run = lambda *a, **k: "run-1"
        try:
            _set_request(headers={"X-OWI-Impersonate": "target.user"},
                         json={"session_id": "s", "message": "hi", "agent_key": "ag_x"},
                         method="POST")
            result = routes.chat_start()
        finally:
            chat_v5_mod.save_user_message = orig_save
            settings_mod.resolve_enabled_agent = orig_resolve
            stream_manager.can_accept = orig_can
            budget_mod.has_budget = orig_budget
            stream_manager.start_run = orig_start
        # Not blocked: the run proceeded under the NON-admin's own identity.
        self.assertEqual(_status_of(result), 200)
        self.assertTrue(saved["called"])
        self.assertEqual(_body_of(result)["run_id"], "run-1")


if __name__ == "__main__":
    unittest.main()
