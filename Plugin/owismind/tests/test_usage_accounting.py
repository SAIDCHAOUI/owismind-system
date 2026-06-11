# Plugin/owismind/tests/test_usage_accounting.py
"""Token/cost usage accounting must INCREMENT (never overwrite), be period-scoped, and
inline only safe server-computed numeric literals.

Three pure layers are provable without a live DSS runtime (project TEST-01 idiom):
  - the SQL builders (monthly UPSERT + lifetime increment) — shape & scoping;
  - chat_v5._usage_literal — coercion of trace values to safe SQL literals / NULL;
  - usage.record_usage — one-transaction increment, zero-usage no-op (fake executor).
The builders carry no ``dataiku`` import; chat_v5/usage do, so a minimal stub is set up
(extending any sibling test's stubs — unittest discover shares one sys.modules).
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so chat_v5 / usage / sql_config import (NO install)."""
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
        sql_mod.toSQL = lambda constant, dialect=None: repr(constant)
    if not hasattr(sql_mod, "Dialects"):
        sql_mod.Dialects = type("Dialects", (), {"POSTGRES": "postgres"})
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.storage.sql_builders import (  # noqa: E402
    build_usage_monthly_upsert,
    build_users_usage_increment,
)


class MonthlyUpsertBuilderTests(unittest.TestCase):
    def _q(self):
        return build_usage_monthly_upsert(
            table_ref='public."T_usage"', user_value_sql="'u1'",
            in_tokens_sql="100", out_tokens_sql="200", cost_sql="0.0500000000",
        )

    def test_period_is_calendar_month_server_clock(self):
        # The bucket key is the first day of the month per the SERVER clock — no
        # Python/DB tz mismatch, and a new month is naturally a new PK row.
        self.assertIn("date_trunc('month', now())::date", self._q())

    def test_conflict_on_user_and_period(self):
        self.assertIn("ON CONFLICT (user_id, period_start)", self._q())

    def test_counters_increment_never_overwrite(self):
        q = self._q()
        self.assertIn("input_tokens  = m.input_tokens  + EXCLUDED.input_tokens", q)
        self.assertIn("output_tokens = m.output_tokens + EXCLUDED.output_tokens", q)
        self.assertIn("total_cost    = m.total_cost    + EXCLUDED.total_cost", q)
        self.assertIn("request_count = m.request_count + 1", q)

    def test_values_inlined(self):
        q = self._q()
        self.assertIn("'u1'", q)
        self.assertIn("100", q)
        self.assertIn("200", q)
        self.assertIn("0.0500000000", q)
        self.assertIn("VALUES", q)

    def test_request_count_seeded_to_one_on_insert(self):
        # The first insert tallies one request (the VALUES list ends with 1, now()).
        self.assertIn(", 1, now())", self._q())


class UsersIncrementBuilderTests(unittest.TestCase):
    def _q(self):
        return build_users_usage_increment(
            table_ref='public."T_users"', user_value_sql="'u1'",
            in_tokens_sql="100", out_tokens_sql="200", cost_sql="0.0500000000",
        )

    def test_increment_never_overwrite(self):
        q = self._q()
        self.assertIn("total_input_tokens  = total_input_tokens  + 100", q)
        self.assertIn("total_output_tokens = total_output_tokens + 200", q)
        self.assertIn("total_cost          = total_cost          + 0.0500000000", q)

    def test_stamps_last_usage_at(self):
        self.assertIn("last_usage_at       = now()", self._q())

    def test_user_scoped(self):
        self.assertIn("WHERE user_id = 'u1'", self._q())


class UsageLiteralTests(unittest.TestCase):
    """chat_v5._usage_literal turns a trace value into a safe SQL literal or NULL."""

    def setUp(self):
        from owismind.storage import chat_v5
        self.lit = chat_v5._usage_literal

    def test_int_value(self):
        self.assertEqual(self.lit(1662), "1662")

    def test_int_from_float_truncates(self):
        self.assertEqual(self.lit(806.0), "806")

    def test_float_fixed_decimals_no_sci_notation(self):
        # A tiny cost must not become '1e-05' (still valid SQL, but we pin the format).
        self.assertEqual(self.lit(0.0000125, is_float=True), "0.0000125000")

    def test_none_is_null(self):
        self.assertEqual(self.lit(None), "NULL")
        self.assertEqual(self.lit(None, is_float=True), "NULL")

    def test_negative_is_null(self):
        self.assertEqual(self.lit(-5), "NULL")
        self.assertEqual(self.lit(-0.1, is_float=True), "NULL")

    def test_garbage_is_null(self):
        self.assertEqual(self.lit("abc"), "NULL")
        self.assertEqual(self.lit({}, is_float=True), "NULL")


class RecordUsageTests(unittest.TestCase):
    """record_usage runs ONE committed transaction with both increments, and is a
    no-op when there is nothing to record — verified with a fake executor."""

    def setUp(self):
        from owismind.storage import usage
        self.usage = usage
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

        # Avoid any DB: stub table-ensures and the executor factory on the module.
        self._orig = {
            "new_executor": usage.new_executor,
            "ensure_users_table": usage.ensure_users_table,
            "ensure_usage_monthly_table": usage.ensure_usage_monthly_table,
        }
        usage.new_executor = lambda: _FakeExec(self.calls)
        usage.ensure_users_table = lambda: None
        usage.ensure_usage_monthly_table = lambda: None

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self.usage, name, fn)

    def test_records_one_committed_transaction_with_both_increments(self):
        self.usage.record_usage("said.chaoui", {
            "promptTokens": 1662, "completionTokens": 806,
            "totalTokens": 2468, "estimatedCost": 0.0101375,
        })
        self.assertEqual(len(self.calls), 1)              # one transaction
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])        # explicit COMMIT
        self.assertEqual(len(call["pre"]), 2)             # monthly UPSERT + users UPDATE
        joined = "\n".join(call["pre"])
        self.assertIn("ON CONFLICT (user_id, period_start)", joined)   # monthly bucket
        self.assertIn("total_input_tokens  = total_input_tokens", joined)  # lifetime
        self.assertIn("1662", joined)
        self.assertIn("806", joined)
        self.assertIn("0.0101375000", joined)             # cost, fixed decimals

    def test_noop_when_all_zero(self):
        # An early-stopped run with no footer yields zeros -> nothing to record.
        self.usage.record_usage("said.chaoui", {
            "promptTokens": 0, "completionTokens": 0, "estimatedCost": 0.0,
        })
        self.assertEqual(self.calls, [])

    def test_noop_when_no_user_or_bad_usage(self):
        self.usage.record_usage("", {"promptTokens": 10})
        self.usage.record_usage("u", None)
        self.assertEqual(self.calls, [])

    def test_negative_or_garbage_values_coerced_to_zero(self):
        # Garbage in completion/cost coerces to 0; a positive prompt still records.
        self.usage.record_usage("u", {
            "promptTokens": 50, "completionTokens": -9, "estimatedCost": "x",
        })
        self.assertEqual(len(self.calls), 1)
        joined = "\n".join(self.calls[0]["pre"])
        self.assertIn("50", joined)
        self.assertIn("0.0000000000", joined)  # cost coerced to 0.0


if __name__ == "__main__":
    unittest.main()
