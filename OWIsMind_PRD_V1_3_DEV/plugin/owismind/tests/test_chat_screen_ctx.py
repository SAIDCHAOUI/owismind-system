# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_chat_screen_ctx.py
"""Consented screen-context ("full transparency") persisted per exchange.

The user chose to hide NOTHING of what they hand to the agent, so the sanitized
``source_state`` shared for a turn is stored VERBATIM (as a compact JSON string) on the
exchange row and read back NULL-safe - the durable "what was given to the agent" record
that a later frontend wave renders.

Coverage (all provable without a live DSS runtime, mirrors test_chat_mode.py):
  - migrations - the chat_v5 CREATE DDL carries the nullable ``screen_ctx`` TEXT column
    AND the additive ADD COLUMN IF NOT EXISTS ALTER (idempotent, at most once per process);
  - chat_v5.save_user_message - the JSON is inlined verbatim on the INSERT (NULL when
    absent), and an over-long value is DROPPED to None (belt, never truncated);
  - chat_v5 conversation read - ``screen_ctx`` is in the stable _COLUMNS and passes through
    the row mapper untouched (NULL-safe) for reloaded conversations;
  - routes.chat_start - the sanitize call happens BEFORE the phase-one write; a shared
    source_state is stamped as json.dumps(source_state, ensure_ascii=False,
    separators=(',',':')), a panel-open-only pointer stamps None (not persisted) yet is
    still handed unchanged to the worker, and no screen_context stamps None.

A minimal ``dataiku`` (+ ``flask`` for the route test) stub is installed so the modules
import (NO install); unittest discover shares one sys.modules, so the stubs are additive.
"""
import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so chat_v5 / migrations / sql_config / routes import."""
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
    if not hasattr(dk, "api_client"):
        dk.api_client = lambda: None
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    if not hasattr(sql_mod, "Constant"):
        sql_mod.Constant = lambda value: value
    if not hasattr(sql_mod, "toSQL"):
        sql_mod.toSQL = lambda constant, dialect=None: "'" + str(constant) + "'"
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


def _ensure_flask_stub():
    flask = sys.modules.get("flask")
    if flask is not None and hasattr(flask, "_OWI_STUB"):
        return
    flask = types.ModuleType("flask")
    flask._OWI_STUB = True

    class Blueprint(object):
        def __init__(self, name, import_name, url_prefix=None):
            self.name = name
            self.url_prefix = url_prefix

        def route(self, *_a, **_k):
            def _decorator(fn):
                return fn
            return _decorator

        def before_request(self, fn):
            return fn

        def after_request(self, fn):
            return fn

    flask.Blueprint = Blueprint
    flask.jsonify = lambda payload: payload
    flask.request = types.SimpleNamespace(headers={}, args={}, method="GET")
    flask.g = types.SimpleNamespace()
    sys.modules["flask"] = flask


# The dataiku stub + the pure storage/migrations/context imports are safe at collection
# time. The flask stub and the ``routes`` import are DEFERRED to the route TestCase's
# setUpClass (below): importing routes binds ``routes.request`` to whatever ``flask.request``
# is at that instant, and another route-test module (test_impersonation) drives its OWN
# request object through that binding. Doing the flask stub + routes import at module top
# would - because this file sorts first - win that binding and break those sibling tests.
# Deferring it means the sibling (which imports routes at its own collection) keeps the
# binding in the full suite, while a standalone run of this file still self-bootstraps.
_ensure_dataiku_stub()

from owismind.agents import context                          # noqa: E402
from owismind.storage import chat_v5                         # noqa: E402
from owismind.storage import migrations                      # noqa: E402
from owismind.storage.migrations import CHAT_V5_LOGICAL       # noqa: E402


class ScreenCtxDDLTests(unittest.TestCase):
    """The screen_ctx column ships in the CREATE DDL AND as an additive idempotent ALTER."""

    def test_create_ddl_has_screen_ctx_column(self):
        ddl = migrations._CHAT_V5_DDL
        self.assertIn("screen_ctx", ddl)
        self.assertIn("screen_ctx         TEXT", ddl)

    def test_chat_v5_has_additive_alter_for_screen_ctx(self):
        alters = migrations._ALTERS_BY_LOGICAL.get(CHAT_V5_LOGICAL) or []
        self.assertIn("ADD COLUMN IF NOT EXISTS screen_ctx TEXT", alters)

    def test_alter_is_idempotent_shape(self):
        for clause in migrations._ALTERS_BY_LOGICAL[CHAT_V5_LOGICAL]:
            self.assertIn("IF NOT EXISTS", clause)


class EnsureChatTableAlterTests(unittest.TestCase):
    """_ensure_table emits the CREATE + the screen_ctx ALTER once per process (guarded)."""

    def setUp(self):
        self.calls = []

        class _FakeExec:
            def __init__(self, sink):
                self._sink = sink

            def query_to_df(self, sql, pre_queries=None, post_queries=None):
                self._sink.append({
                    "sql": sql, "pre": list(pre_queries or []),
                    "post": list(post_queries or []),
                })
                return None

        self._orig = {
            "new_executor": migrations.new_executor,
            "full_table": migrations.full_table,
            "physical_table": migrations.physical_table,
            "safe_index_name": migrations.safe_index_name,
            "ensured": migrations._ensured_tables,
        }
        migrations.new_executor = lambda: _FakeExec(self.calls)
        migrations.full_table = lambda logical: 'public."T_chat"'
        migrations.physical_table = lambda logical: "T_chat"
        migrations.safe_index_name = lambda phys, suffix: "idx_" + suffix
        migrations._ensured_tables = set()   # force the DDL to run in this test

    def tearDown(self):
        migrations.new_executor = self._orig["new_executor"]
        migrations.full_table = self._orig["full_table"]
        migrations.physical_table = self._orig["physical_table"]
        migrations.safe_index_name = self._orig["safe_index_name"]
        migrations._ensured_tables = self._orig["ensured"]

    def test_ensure_emits_create_and_screen_ctx_alter(self):
        migrations.ensure_chat_table()
        self.assertEqual(len(self.calls), 1)                 # one committed transaction
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        create = call["pre"][0]
        self.assertIn("CREATE TABLE IF NOT EXISTS", create)
        self.assertIn("screen_ctx", create)
        # The additive ALTER is issued in the SAME transaction, after the CREATE.
        self.assertTrue(
            any("ADD COLUMN IF NOT EXISTS screen_ctx TEXT" in q for q in call["pre"]),
            "screen_ctx ALTER not found in pre_queries",
        )


class _FakeExec:
    def __init__(self, sink):
        self._sink = sink

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self._sink.append({
            "sql": sql, "pre": list(pre_queries or []),
            "post": list(post_queries or []),
        })
        return None


class SaveUserMessageScreenCtxTests(unittest.TestCase):
    """save_user_message inlines the screen_ctx JSON on the INSERT (NULL when absent)."""

    IDENTITY = {"user_id": "u1", "display_name": "U One", "groups": []}

    def setUp(self):
        self.calls = []
        self._orig = {
            "new_executor": chat_v5.new_executor,
            "full_table": chat_v5.full_table,
        }
        chat_v5.new_executor = lambda: _FakeExec(self.calls)
        chat_v5.full_table = lambda logical: 'public."T_chat"'

    def tearDown(self):
        chat_v5.new_executor = self._orig["new_executor"]
        chat_v5.full_table = self._orig["full_table"]

    def _insert_sql(self):
        # Phase-one write puts the INSERT in pre_queries[0], COMMIT in post_queries.
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        return call["pre"][0]

    def test_insert_column_list_includes_screen_ctx(self):
        chat_v5.save_user_message(
            "s1", self.IDENTITY, "hello", "ag_x", None, mode="pro", screen_ctx="{}")
        sql = self._insert_sql()
        self.assertIn("parent_exchange_id, mode, answered_at, screen_ctx", sql)

    def test_json_inlined_verbatim(self):
        payload = '{"surface":"explorer","dataset":"DRIVE_Revenues"}'
        chat_v5.save_user_message(
            "s1", self.IDENTITY, "hello", "ag_x", None, screen_ctx=payload)
        # The exact JSON string lands inlined (the stub sql_value wraps in single quotes).
        self.assertIn(payload, self._insert_sql())

    def test_no_screen_ctx_writes_null(self):
        # Nothing shared -> the trailing screen_ctx value is a bare NULL keyword.
        chat_v5.save_user_message(
            "s1", self.IDENTITY, "hello", "ag_x", None, mode=None, screen_ctx=None)
        sql = self._insert_sql()
        # mode NULL, answered_at NULL, screen_ctx NULL -> three trailing NULLs.
        self.assertIn("NULL, NULL, NULL)", sql)

    def test_default_screen_ctx_is_none(self):
        # The kwarg defaults to None (a caller that does not pass it writes NULL).
        chat_v5.save_user_message("s1", self.IDENTITY, "hello", "ag_x", None)
        self.assertIn("NULL, NULL, NULL)", self._insert_sql())

    def test_oversize_dropped_to_null_not_truncated(self):
        # A pathological over-long value is dropped whole (never mid-JSON truncated).
        big = "x" * (chat_v5.MAX_SCREEN_CTX_CHARS + 1)
        chat_v5.save_user_message(
            "s1", self.IDENTITY, "hello", "ag_x", None, screen_ctx=big)
        sql = self._insert_sql()
        self.assertNotIn("xxxx", sql)                # the body never reaches the INSERT
        self.assertIn("NULL, NULL, NULL)", sql)      # stored as NULL instead

    def test_at_limit_kept(self):
        # Exactly at the cap is still stored verbatim (boundary is > cap, not >=).
        at_cap = "y" * chat_v5.MAX_SCREEN_CTX_CHARS
        chat_v5.save_user_message(
            "s1", self.IDENTITY, "hello", "ag_x", None, screen_ctx=at_cap)
        self.assertIn(at_cap, self._insert_sql())


class ConversationReadScreenCtxTests(unittest.TestCase):
    """The conversation read exposes ``screen_ctx`` per exchange (NULL-safe passthrough)."""

    def test_columns_include_screen_ctx(self):
        self.assertIn("screen_ctx", chat_v5._COLUMNS)

    def test_messages_for_session_carries_screen_ctx(self):
        fake_rows = [
            {"user_groups": None, "generated_sql": None, "feedback_reasons": None,
             "exchange_id": "x1", "screen_ctx": '{"surface":"explorer","dataset":"D"}'},
            {"user_groups": None, "generated_sql": None, "feedback_reasons": None,
             "exchange_id": "x2", "screen_ctx": None},   # legacy / nothing shared
        ]
        orig = {
            "new_executor": chat_v5.new_executor,
            "full_table": chat_v5.full_table,
            "rows_to_json_safe": chat_v5.rows_to_json_safe,
        }
        chat_v5.new_executor = lambda: _FakeExec([])
        chat_v5.full_table = lambda logical: 'public."T_chat"'
        chat_v5.rows_to_json_safe = lambda df: [dict(r) for r in fake_rows]
        try:
            rows = chat_v5.messages_for_session("u1", "s1")
        finally:
            chat_v5.new_executor = orig["new_executor"]
            chat_v5.full_table = orig["full_table"]
            chat_v5.rows_to_json_safe = orig["rows_to_json_safe"]
        # Returned VERBATIM (a JSON string the frontend decodes), NOT parsed here.
        self.assertEqual(rows[0]["screen_ctx"], '{"surface":"explorer","dataset":"D"}')
        self.assertIsNone(rows[1]["screen_ctx"])   # NULL reads back as None, no crash


# --- routes.chat_start: sanitize BEFORE the write + stamp the consented JSON ---
# The route env (flask stub + routes and its collaborators) is loaded lazily so this file
# never wins the module-load ``routes.request`` binding at collection (see note above).
routes = None
sql_config = None
settings_mod = None
budget_mod = None
impersonation = None
stream_manager = None


def _load_route_env():
    global routes, sql_config, settings_mod, budget_mod, impersonation, stream_manager
    if routes is not None:
        return
    _ensure_flask_stub()
    from owismind.api import routes as _routes
    from owismind.storage import sql_config as _sql_config
    from owismind.storage import settings as _settings_mod
    from owismind.storage import budget as _budget_mod
    from owismind.security import impersonation as _impersonation
    from owismind.agents import stream_manager as _stream_manager
    routes = _routes
    sql_config = _sql_config
    settings_mod = _settings_mod
    budget_mod = _budget_mod
    impersonation = _impersonation
    stream_manager = _stream_manager


class _FakeReq(object):
    def __init__(self, body):
        self.headers = {}
        self.args = {}
        self.method = "POST"
        self._json = body

    def get_json(self, silent=False, force=False):
        return self._json


class ChatStartScreenCtxStampTests(unittest.TestCase):
    """chat_start sanitizes screen_context BEFORE the phase-one write and stamps the
    consented source_state JSON onto save_user_message (None when nothing was shared),
    while still handing the SAME sanitized object to the worker."""

    @classmethod
    def setUpClass(cls):
        # Runs after full collection: in the whole suite routes is already imported (its
        # request binding intact for sibling tests); standalone it self-bootstraps here.
        _load_route_env()

    def setUp(self):
        self.saved = {}
        self.started = {}

        def _save(session_id, identity, message, agent_key, parent_exchange_id=None,
                  mode=None, screen_ctx=None):
            self.saved["screen_ctx"] = screen_ctx
            return "exch-1"

        def _start(*a, **k):
            self.started["screen_context"] = k.get("screen_context")
            return "run-1"

        self._orig = {
            "resolve_identity": routes.resolve_identity,
            "is_configured": sql_config.is_configured,
            "ensure_chat_table": routes.ensure_chat_table,
            "effective_identity": impersonation.effective_identity,
            "resolve_enabled_agent": settings_mod.resolve_enabled_agent,
            "can_accept": stream_manager.can_accept,
            "has_budget": budget_mod.has_budget,
            "start_run": stream_manager.start_run,
            "save_user_message": routes.chat_v5.save_user_message,
            "request": routes.request,
            "jsonify": routes.jsonify,
        }
        routes.resolve_identity = lambda headers: {
            "user_id": "u.one", "display_name": "U One", "groups": []}
        sql_config.is_configured = lambda: True
        routes.ensure_chat_table = lambda: None
        impersonation.effective_identity = lambda ident: dict(ident, impersonating=False)
        settings_mod.resolve_enabled_agent = lambda key: {
            "project_key": "P", "agent_id": "A", "profile": {}}
        stream_manager.can_accept = lambda uid: (True, None)
        budget_mod.has_budget = lambda uid: (True, {})
        stream_manager.start_run = _start
        routes.chat_v5.save_user_message = _save
        routes.jsonify = lambda payload: payload

    def tearDown(self):
        routes.resolve_identity = self._orig["resolve_identity"]
        sql_config.is_configured = self._orig["is_configured"]
        routes.ensure_chat_table = self._orig["ensure_chat_table"]
        impersonation.effective_identity = self._orig["effective_identity"]
        settings_mod.resolve_enabled_agent = self._orig["resolve_enabled_agent"]
        stream_manager.can_accept = self._orig["can_accept"]
        budget_mod.has_budget = self._orig["has_budget"]
        stream_manager.start_run = self._orig["start_run"]
        routes.chat_v5.save_user_message = self._orig["save_user_message"]
        routes.request = self._orig["request"]
        routes.jsonify = self._orig["jsonify"]

    def _run(self, screen_context):
        body = {"session_id": "s1", "message": "hi", "agent_key": "ag_x"}
        if screen_context is not None:
            body["screen_context"] = screen_context
        routes.request = _FakeReq(body)
        return routes.chat_start()

    _VALID_SS = {
        "surface": "explorer",
        "dataset": "DRIVE_Revenues",
        "filters": [{"column": "year", "op": "=", "values": ["2025"]}],
    }

    def test_shared_source_state_stamped_as_compact_json(self):
        result = self._run({"open": False, "source_state": dict(self._VALID_SS)})
        status = result[1] if isinstance(result, tuple) else 200
        self.assertEqual(status, 200)
        # The persisted JSON is EXACTLY json.dumps of the sanitized source_state the
        # worker received (one source of truth), compact + ensure_ascii=False.
        shared = self.started["screen_context"]["source_state"]
        self.assertEqual(
            self.saved["screen_ctx"],
            json.dumps(shared, ensure_ascii=False, separators=(",", ":")),
        )
        # Compact (no separator whitespace) is what "separators=(',',':')" guarantees.
        self.assertNotIn(", ", self.saved["screen_ctx"])
        self.assertIn('"dataset":"DRIVE_Revenues"', self.saved["screen_ctx"])

    def test_open_only_pointer_not_persisted_but_passed_to_worker(self):
        # A panel-open pointer with NO source_state: nothing is persisted (transient
        # viewport hint, not shared data), yet the worker still gets the pointer.
        result = self._run({"open": True, "exchange_id": "e9", "active_tab": "sources"})
        status = result[1] if isinstance(result, tuple) else 200
        self.assertEqual(status, 200)
        self.assertIsNone(self.saved["screen_ctx"])
        self.assertIsNotNone(self.started["screen_context"])
        self.assertEqual(self.started["screen_context"]["open"], True)

    def test_no_screen_context_stamps_none(self):
        result = self._run(None)
        status = result[1] if isinstance(result, tuple) else 200
        self.assertEqual(status, 200)
        self.assertIsNone(self.saved["screen_ctx"])
        self.assertIsNone(self.started["screen_context"])

    def test_non_unicode_preserved_ensure_ascii_false(self):
        ss = {"surface": "explorer", "dataset": "Chiffre_d_affaires",
              "q": "clients français"}
        self._run({"open": False, "source_state": ss})
        # ensure_ascii=False keeps accented characters literal (not \\uXXXX escaped).
        self.assertIn("français", self.saved["screen_ctx"])


if __name__ == "__main__":
    unittest.main()
