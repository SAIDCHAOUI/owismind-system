# Plugin/owismind/tests/test_chat_mode.py
"""Ephemeral response mode (smart / pro / claude) is resolved to an EFFECTIVE mode,
persisted per exchange in webapp_chat_v5, and read back NULL-safe.

Coverage (all provable without a live DSS runtime, project TEST-01 idiom):
  - context.resolve_effective_mode - the pure stamp contract (valid / missing-with-dial
    -> smart / no-dial -> None);
  - migrations - the chat_v5 CREATE DDL carries the ``mode`` column AND the additive
    ADD COLUMN IF NOT EXISTS ALTER (idempotent, applied at most once per process);
  - chat_v5.save_user_message - the effective mode is inlined on the INSERT (NULL when
    absent), verified with a fake executor;
  - chat_v5 conversation read - ``mode`` is in the stable _COLUMNS and passes through
    the row mapper untouched (NULL-safe) for reloaded conversations.

A minimal ``dataiku`` stub is set up so sql_config / migrations / chat_v5 import (NO
install); unittest discover shares one sys.modules, so the stub is additive.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so chat_v5 / migrations / sql_config import (NO install)."""
    dk = sys.modules.get("dataiku")
    if dk is None:
        dk = types.ModuleType("dataiku")
        sys.modules["dataiku"] = dk
    if not hasattr(dk, "SQLExecutor2"):
        dk.SQLExecutor2 = type("SQLExecutor2", (), {})
    if not hasattr(dk, "default_project_key"):
        dk.default_project_key = lambda: "OWISMIND_DEV"
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


_ensure_dataiku_stub()

from owismind.agents import context                        # noqa: E402
from owismind.storage import chat_v5                       # noqa: E402
from owismind.storage import migrations                    # noqa: E402
from owismind.storage.migrations import CHAT_V5_LOGICAL     # noqa: E402


class ResolveEffectiveModeTests(unittest.TestCase):
    """The pure stamp contract behind /chat/start (no Flask, no DB)."""

    def test_valid_mode_with_dial_kept(self):
        for m in ("smart", "pro", "claude"):
            self.assertEqual(context.resolve_effective_mode(m, True), m)

    def test_missing_mode_with_dial_defaults_to_smart(self):
        self.assertEqual(context.resolve_effective_mode(None, True), "smart")

    def test_unknown_mode_with_dial_defaults_to_smart(self):
        # A forged / stale value never leaks through - it clamps to the default tier.
        self.assertEqual(context.resolve_effective_mode("turbo", True), "smart")
        self.assertEqual(context.resolve_effective_mode("", True), "smart")

    def test_agent_without_dial_is_none_regardless(self):
        # No response-mode dial -> the run carries no mode (NULL on the row, no token).
        self.assertIsNone(context.resolve_effective_mode("pro", False))
        self.assertIsNone(context.resolve_effective_mode(None, False))
        self.assertIsNone(context.resolve_effective_mode("turbo", False))


class ChatV5ModeDDLTests(unittest.TestCase):
    """The mode column ships in the CREATE DDL AND as an additive idempotent ALTER."""

    def test_create_ddl_has_mode_column(self):
        ddl = migrations._CHAT_V5_DDL
        self.assertIn("mode", ddl)
        self.assertIn("VARCHAR(16)", ddl)

    def test_chat_v5_has_additive_alter_for_mode(self):
        alters = migrations._ALTERS_BY_LOGICAL.get(CHAT_V5_LOGICAL) or []
        self.assertIn("ADD COLUMN IF NOT EXISTS mode VARCHAR(16)", alters)

    def test_alter_is_idempotent_shape(self):
        # IF NOT EXISTS is what makes the ALTER a no-op on every process start and on a
        # fresh table that already has the column from its CREATE DDL.
        for clause in migrations._ALTERS_BY_LOGICAL[CHAT_V5_LOGICAL]:
            self.assertIn("IF NOT EXISTS", clause)


class EnsureChatTableAlterTests(unittest.TestCase):
    """_ensure_table emits the CREATE + additive ALTER once per process (guarded)."""

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

    def test_ensure_emits_create_and_mode_alter(self):
        migrations.ensure_chat_table()
        self.assertEqual(len(self.calls), 1)                 # one committed transaction
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        create = call["pre"][0]
        self.assertIn("CREATE TABLE IF NOT EXISTS", create)
        self.assertIn("mode", create)
        self.assertIn("VARCHAR(16)", create)
        # The additive ALTER is issued in the SAME transaction, after the CREATE.
        self.assertTrue(
            any("ADD COLUMN IF NOT EXISTS mode VARCHAR(16)" in q for q in call["pre"]),
            "mode ALTER not found in pre_queries",
        )

    def test_ensure_runs_at_most_once_per_process(self):
        migrations.ensure_chat_table()
        migrations.ensure_chat_table()                       # guarded no-op
        self.assertEqual(len(self.calls), 1)


class _FakeExec:
    def __init__(self, sink):
        self._sink = sink

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self._sink.append({
            "sql": sql, "pre": list(pre_queries or []),
            "post": list(post_queries or []),
        })
        return None


class SaveUserMessageModeTests(unittest.TestCase):
    """save_user_message inlines the effective mode on the INSERT (NULL when absent)."""

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

    def test_insert_column_list_includes_mode(self):
        chat_v5.save_user_message("s1", self.IDENTITY, "hello", "ag_x", None, mode="pro")
        sql = self._insert_sql()
        self.assertIn("parent_exchange_id, mode, answered_at", sql)

    def test_valid_mode_inlined(self):
        chat_v5.save_user_message("s1", self.IDENTITY, "hello", "ag_x", None, mode="claude")
        self.assertIn("claude", self._insert_sql())

    def test_no_mode_writes_null(self):
        # Modes-disabled agent path (effective mode None) -> SQL NULL for the column.
        chat_v5.save_user_message("s1", self.IDENTITY, "hello", "ag_x", None, mode=None)
        sql = self._insert_sql()
        self.assertNotIn("'smart'", sql)
        self.assertNotIn("'pro'", sql)
        self.assertNotIn("'claude'", sql)
        # Both the mode and the always-NULL answered_at land as bare NULL keywords.
        self.assertIn("NULL, NULL)", sql)

    def test_default_mode_is_none(self):
        # The kwarg defaults to None (a caller that does not pass a mode writes NULL).
        chat_v5.save_user_message("s1", self.IDENTITY, "hello", "ag_x", None)
        sql = self._insert_sql()
        self.assertNotIn("'smart'", sql)


class ConversationReadModeTests(unittest.TestCase):
    """The conversation read exposes ``mode`` on each exchange (NULL-safe passthrough)."""

    def test_columns_include_mode(self):
        self.assertIn("mode", chat_v5._COLUMNS)

    def test_messages_for_session_carries_mode(self):
        fake_rows = [
            {"user_groups": None, "generated_sql": None, "feedback_reasons": None,
             "exchange_id": "x1", "mode": "pro"},
            {"user_groups": None, "generated_sql": None, "feedback_reasons": None,
             "exchange_id": "x2", "mode": None},   # legacy / modes-disabled row
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
        self.assertEqual(rows[0]["mode"], "pro")
        self.assertIsNone(rows[1]["mode"])   # NULL reads back as None, no crash


if __name__ == "__main__":
    unittest.main()
