# Plugin/owismind/tests/test_budget.py
"""Monthly budget: SQL builders (shape & scoping), limit resolution (override > global
temp > default, enforcement switch, exactly-at-limit block) and the storage helpers
(per-user upsert/clear in one committed transaction).

Pure layers provable without a live DSS runtime: the builders carry no ``dataiku``
import; budget.py does, so the shared minimal stub is set up first. The DB-touching
helpers are exercised with a fake executor + a passthrough rows decoder (pandas is
stubbed empty), so no pandas / SQL runtime is needed.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
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

from owismind.storage.sql_builders import (  # noqa: E402
    build_admin_usage_overview_query,
    build_user_quota_clear,
    build_user_quota_upsert,
    build_user_usage_status_query,
)


class StatusQueryBuilderTests(unittest.TestCase):
    def _q(self):
        return build_user_usage_status_query(
            'public."T_monthly"', 'public."T_quota"', 'public."T_users"', "'u1'"
        )

    def test_period_and_reset_are_server_month(self):
        q = self._q()
        self.assertIn("date_trunc('month', now())::date", q)
        self.assertIn("interval '1 month'", q)  # next_reset = first of next month

    def test_current_month_bucket_join(self):
        q = self._q()
        self.assertIn("m.period_start = date_trunc('month', now())::date", q)

    def test_override_active_decided_in_sql(self):
        q = self._q()
        self.assertIn("q.expires_at IS NULL OR q.expires_at > now()", q)

    def test_scoped_to_one_user(self):
        # The anchor row pins the single user_id everything LEFT JOINs onto.
        self.assertIn("SELECT 'u1' AS uid", self._q())

    def test_left_joins_keep_a_row_for_a_brand_new_user(self):
        q = self._q()
        self.assertEqual(q.count("LEFT JOIN"), 3)


class AdminOverviewBuilderTests(unittest.TestCase):
    def _q(self):
        return build_admin_usage_overview_query(
            'public."T_users"', 'public."T_monthly"', 'public."T_quota"', 1000
        )

    def test_anchored_on_users_registry(self):
        # Anchored on users so a user with no spend this month still appears.
        q = self._q()
        self.assertIn('FROM public."T_users" u', q)
        self.assertEqual(q.count("LEFT JOIN"), 2)

    def test_orders_by_spend_desc_and_bounds(self):
        q = self._q()
        self.assertIn("ORDER BY COALESCE(m.total_cost, 0) DESC", q)
        self.assertIn("LIMIT 1000", q)


class QuotaUpsertBuilderTests(unittest.TestCase):
    def test_permanent_override_stores_null_expiry(self):
        q = build_user_quota_upsert(
            'public."T_quota"', "'u1'", "80.000000", None, "NULL", "'admin'"
        )
        self.assertIn("VALUES ('u1', 80.000000, NULL, NULL, now(), 'admin')", q)
        self.assertIn("ON CONFLICT (user_id) DO UPDATE", q)
        self.assertIn("limit_usd  = EXCLUDED.limit_usd", q)

    def test_temporary_override_uses_day_interval(self):
        q = build_user_quota_upsert(
            'public."T_quota"', "'u1'", "120.000000", 7, "'boost'", "'admin'"
        )
        self.assertIn("now() + (interval '1 day' * 7)", q)

    def test_days_are_int_coerced_no_injection(self):
        # A string day count is int-coerced (a non-int would raise) - never inlined raw.
        q = build_user_quota_upsert('public."T_quota"', "'u1'", "10.0", "30", "NULL", "NULL")
        self.assertIn("interval '1 day' * 30)", q)


class QuotaClearBuilderTests(unittest.TestCase):
    def test_deletes_for_the_user_set(self):
        q = build_user_quota_clear('public."T_quota"', "'u1', 'u2'")
        self.assertEqual(
            q.strip(), "DELETE FROM public.\"T_quota\" WHERE user_id IN ('u1', 'u2')"
        )


class LimitResolutionTests(unittest.TestCase):
    """budget._resolve_limit: override > active global temp > default; enforcement gate."""

    def setUp(self):
        from owismind.storage import budget
        self.budget = budget
        self.base = {"limit_usd": 50.0, "enabled": True,
                     "temp_limit_usd": None, "temp_expires_at": None}

    def test_default_limit_when_no_override(self):
        r = self.budget._resolve_limit(10.0, False, None, None, self.base)
        self.assertEqual(r["limit_usd"], 50.0)
        self.assertEqual(r["limit_source"], "default")
        self.assertEqual(r["remaining_usd"], 40.0)
        self.assertFalse(r["blocked"])

    def test_blocked_exactly_at_limit(self):
        r = self.budget._resolve_limit(50.0, False, None, None, self.base)
        self.assertTrue(r["blocked"])
        self.assertEqual(r["remaining_usd"], 0.0)

    def test_blocked_over_limit(self):
        r = self.budget._resolve_limit(51.23, False, None, None, self.base)
        self.assertTrue(r["blocked"])
        self.assertEqual(r["remaining_usd"], 0.0)

    def test_enforcement_disabled_never_blocks(self):
        cfg = dict(self.base, enabled=False)
        r = self.budget._resolve_limit(999.0, False, None, None, cfg)
        self.assertFalse(r["enforced"])
        self.assertFalse(r["blocked"])

    def test_user_permanent_override_wins(self):
        r = self.budget._resolve_limit(60.0, True, 100.0, None, self.base)
        self.assertEqual(r["limit_usd"], 100.0)
        self.assertEqual(r["limit_source"], "user_permanent")
        self.assertFalse(r["blocked"])  # 60 < 100

    def test_user_temp_override_source(self):
        r = self.budget._resolve_limit(10.0, True, 100.0, "2999-01-01T00:00:00", self.base)
        self.assertEqual(r["limit_source"], "user_temp")
        self.assertEqual(r["limit_expires_at"], "2999-01-01T00:00:00")

    def test_expired_user_override_falls_back_to_global(self):
        # override_active=False (SQL already decided it lapsed) -> global default applies.
        r = self.budget._resolve_limit(10.0, False, 100.0, "2000-01-01T00:00:00", self.base)
        self.assertEqual(r["limit_usd"], 50.0)
        self.assertEqual(r["limit_source"], "default")

    def test_active_global_temp_boost(self):
        cfg = dict(self.base, temp_limit_usd=80.0, temp_expires_at="2999-01-01T00:00:00")
        r = self.budget._resolve_limit(60.0, False, None, None, cfg)
        self.assertEqual(r["limit_usd"], 80.0)
        self.assertEqual(r["limit_source"], "global_temp")
        self.assertFalse(r["blocked"])

    def test_expired_global_temp_ignored(self):
        cfg = dict(self.base, temp_limit_usd=80.0, temp_expires_at="2000-01-01T00:00:00")
        r = self.budget._resolve_limit(60.0, False, None, None, cfg)
        self.assertEqual(r["limit_usd"], 50.0)
        self.assertTrue(r["blocked"])  # 60 >= 50 (boost lapsed)

    def test_user_override_beats_global_temp(self):
        cfg = dict(self.base, temp_limit_usd=80.0, temp_expires_at="2999-01-01T00:00:00")
        r = self.budget._resolve_limit(10.0, True, 200.0, None, cfg)
        self.assertEqual(r["limit_usd"], 200.0)
        self.assertEqual(r["limit_source"], "user_permanent")


class BudgetConfigSanitizationTests(unittest.TestCase):
    def setUp(self):
        from owismind.storage import budget, settings
        self.budget = budget
        self.settings = settings
        self._orig = settings.get_setting
        budget._invalidate_config_cache()  # start from a cold config cache

    def tearDown(self):
        self.settings.get_setting = self._orig
        self.budget._invalidate_config_cache()  # don't leak a test value into the cache

    def _with_setting(self, value):
        self.settings.get_setting = lambda key, default=None: value
        self.budget._invalidate_config_cache()  # force a re-read of the new patched value

    def test_defaults_when_unset(self):
        self._with_setting(None)
        cfg = self.budget.get_budget_config()
        self.assertEqual(cfg["limit_usd"], 50.0)
        self.assertTrue(cfg["enabled"])
        self.assertIsNone(cfg["temp_limit_usd"])

    def test_valid_config_passes_through(self):
        self._with_setting({"limit_usd": 75, "enabled": False,
                            "temp_limit_usd": 90, "temp_expires_at": "2999-01-01T00:00:00"})
        cfg = self.budget.get_budget_config()
        self.assertEqual(cfg["limit_usd"], 75.0)
        self.assertFalse(cfg["enabled"])
        self.assertEqual(cfg["temp_limit_usd"], 90.0)

    def test_bool_limit_rejected(self):
        # True is an int subclass - must not be taken as a numeric limit.
        self._with_setting({"limit_usd": True})
        self.assertEqual(self.budget.get_budget_config()["limit_usd"], 50.0)

    def test_temp_needs_both_amount_and_expiry(self):
        self._with_setting({"limit_usd": 50, "temp_limit_usd": 90})  # no expiry
        cfg = self.budget.get_budget_config()
        self.assertIsNone(cfg["temp_limit_usd"])
        self.assertIsNone(cfg["temp_expires_at"])

    def test_negative_limit_rejected(self):
        self._with_setting({"limit_usd": -5})
        self.assertEqual(self.budget.get_budget_config()["limit_usd"], 50.0)


class BudgetConfigCacheTests(unittest.TestCase):
    """get_budget_config is served from a short-TTL in-process cache so the chat hot
    path does ONE DB read, not two; a config write busts it."""

    def setUp(self):
        from owismind.storage import budget, settings
        self.budget = budget
        self.settings = settings
        self._orig = settings.get_setting
        self.reads = []
        settings.get_setting = lambda key, default=None: self.reads.append(key) or {
            "limit_usd": 50, "enabled": True}
        budget._invalidate_config_cache()

    def tearDown(self):
        self.settings.get_setting = self._orig
        self.budget._invalidate_config_cache()

    def test_second_call_is_cache_hit(self):
        self.budget.get_budget_config()
        self.budget.get_budget_config()
        self.assertEqual(len(self.reads), 1)  # only one underlying DB read

    def test_invalidate_forces_reread(self):
        self.budget.get_budget_config()
        self.budget._invalidate_config_cache()
        self.budget.get_budget_config()
        self.assertEqual(len(self.reads), 2)

    def test_returns_independent_copies(self):
        a = self.budget.get_budget_config()
        a["limit_usd"] = 9999  # mutating the returned dict must not poison the cache
        b = self.budget.get_budget_config()
        self.assertEqual(b["limit_usd"], 50.0)


class _FakeExec:
    def __init__(self, sink, rows=None):
        self._sink = sink
        self._rows = rows if rows is not None else []

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self._sink.append({"sql": sql, "pre": list(pre_queries or []),
                           "post": list(post_queries or [])})
        return self._rows


class BudgetValidatorTests(unittest.TestCase):
    """The budget input validators reject hostile/edge inputs with a stable 400 code,
    never an uncaught exception (which would surface as an opaque 500)."""

    def setUp(self):
        from owismind.security import validation
        self.v = validation

    def test_amount_rejects_huge_int_overflow(self):
        # A bare huge JSON integer (10**400) overflows float() with OverflowError, NOT
        # ValueError - must still raise the clean ValidationError, not bubble up as 500.
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_budget_amount(10 ** 400)

    def test_amount_rejects_bool_nan_negative_and_over_cap(self):
        for bad in (True, False, float("nan"), float("inf"), -1, self.v.MAX_BUDGET_USD + 1, "x", None):
            with self.assertRaises(self.v.ValidationError):
                self.v.validate_budget_amount(bad)

    def test_amount_accepts_valid(self):
        self.assertEqual(self.v.validate_budget_amount(0), 0.0)
        self.assertEqual(self.v.validate_budget_amount(50), 50.0)
        self.assertEqual(self.v.validate_budget_amount(49.99), 49.99)

    def test_expires_days_bounds_and_bool_trap(self):
        self.assertIsNone(self.v.validate_expires_days(None))
        self.assertIsNone(self.v.validate_expires_days(0))
        self.assertEqual(self.v.validate_expires_days(7), 7)
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_expires_days(True)   # bool int-subclass trap
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_expires_days(4000)   # over MAX_QUOTA_DAYS

    def test_user_id_list_dedup_and_bounds(self):
        self.assertEqual(self.v.validate_user_id_list(["a", "b", "a"]), ["a", "b"])
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_user_id_list([])
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_user_id_list("not-a-list")
        with self.assertRaises(self.v.ValidationError):
            self.v.validate_user_id_list([123])


class StatusFromStorageTests(unittest.TestCase):
    """usage_status / admin_overview end-to-end over a fake executor (no pandas/SQL)."""

    def setUp(self):
        from owismind.storage import budget
        self.budget = budget
        self.calls = []
        self._orig = {
            "new_executor": budget.new_executor,
            "rows_to_json_safe": budget.rows_to_json_safe,
            "get_budget_config": budget.get_budget_config,
            "ensure_usage_monthly_table": budget.ensure_usage_monthly_table,
            "ensure_user_quota_table": budget.ensure_user_quota_table,
            "ensure_users_table": budget.ensure_users_table,
        }
        budget.rows_to_json_safe = lambda df: df  # rows already plain dicts
        budget.get_budget_config = lambda: {
            "limit_usd": 50.0, "enabled": True,
            "temp_limit_usd": None, "temp_expires_at": None,
        }
        budget.ensure_usage_monthly_table = lambda: None
        budget.ensure_user_quota_table = lambda: None
        budget.ensure_users_table = lambda: None

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self.budget, name, fn)

    def test_usage_status_resolves_from_row(self):
        row = {
            "period_start": "2026-06-01", "next_reset": "2026-07-01",
            "spent_usd": 12.5, "input_tokens": 1000, "output_tokens": 500,
            "request_count": 7, "override_active": False, "override_limit": None,
            "override_expires": None, "lifetime_input_tokens": 9000,
            "lifetime_output_tokens": 4000, "lifetime_cost": 3.21,
            "last_usage_at": "2026-06-18T10:00:00",
        }
        self.budget.new_executor = lambda: _FakeExec(self.calls, [row])
        st = self.budget.usage_status("u1")
        self.assertEqual(st["spent_usd"], 12.5)
        self.assertEqual(st["total_tokens"], 1500)
        self.assertEqual(st["limit_usd"], 50.0)
        self.assertEqual(st["remaining_usd"], 37.5)
        self.assertFalse(st["blocked"])
        self.assertEqual(st["lifetime"]["total_tokens"], 13000)

    def test_usage_status_blocked_user(self):
        row = {"spent_usd": 55.0, "input_tokens": 0, "output_tokens": 0,
               "request_count": 99, "override_active": False, "override_limit": None,
               "override_expires": None, "lifetime_cost": 55.0}
        self.budget.new_executor = lambda: _FakeExec(self.calls, [row])
        ok, st = self.budget.has_budget("u1")
        self.assertFalse(ok)
        self.assertTrue(st["blocked"])

    def test_admin_overview_shape(self):
        rows = [
            {"period_start": "2026-06-01", "next_reset": "2026-07-01", "user_id": "a",
             "display_name": "A", "user_groups": None, "is_admin": True,
             "lifetime_cost": 5.0, "last_usage_at": None, "spent_usd": 60.0,
             "input_tokens": 1, "output_tokens": 2, "request_count": 3,
             "override_limit": None, "override_expires": None, "override_note": None,
             "override_active": False},
        ]
        self.budget.new_executor = lambda: _FakeExec(self.calls, rows)
        ov = self.budget.admin_overview()
        self.assertEqual(ov["config"]["default_limit_usd"], 50.0)
        self.assertEqual(len(ov["users"]), 1)
        u = ov["users"][0]
        self.assertTrue(u["blocked"])           # 60 >= 50 default
        self.assertEqual(u["limit_source"], "default")


class BudgetConfigWriteTests(unittest.TestCase):
    """set_budget_config: arm / clear / PRESERVE an active temp boost (the default-limit
    edit must never disturb or be blocked by an active boost - review fix)."""

    def setUp(self):
        from owismind.storage import budget, settings
        self.budget = budget
        self.settings = settings
        self.store = {}
        self._orig = {"set_setting": settings.set_setting, "get_setting": settings.get_setting}
        settings.set_setting = lambda key, value, updated_by=None: self.store.update({"value": value})
        settings.get_setting = lambda key, default=None: self.store.get("value", default)
        budget._invalidate_config_cache()  # cold cache so preserve_temp reads the seeded store

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self.settings, name, fn)
        self.budget._invalidate_config_cache()

    def test_arm_temp_boost(self):
        cfg = self.budget.set_budget_config(50, True, 80, 7)
        self.assertEqual(cfg["temp_limit_usd"], 80.0)
        self.assertIsNotNone(cfg["temp_expires_at"])

    def test_clear_temp_boost(self):
        self.store["value"] = {"limit_usd": 50, "enabled": True,
                               "temp_limit_usd": 80.0, "temp_expires_at": "2999-01-01T00:00:00"}
        cfg = self.budget.set_budget_config(50, True, clear_temp=True)
        self.assertIsNone(cfg["temp_limit_usd"])
        self.assertIsNone(cfg["temp_expires_at"])

    def test_preserve_keeps_active_boost_on_default_edit(self):
        self.store["value"] = {"limit_usd": 50, "enabled": True,
                               "temp_limit_usd": 80.0, "temp_expires_at": "2999-01-01T00:00:00"}
        cfg = self.budget.set_budget_config(60, True, preserve_temp=True)
        self.assertEqual(cfg["limit_usd"], 60.0)         # default changed
        self.assertEqual(cfg["temp_limit_usd"], 80.0)    # boost preserved
        self.assertEqual(cfg["temp_expires_at"], "2999-01-01T00:00:00")

    def test_plain_save_without_preserve_clears(self):
        cfg = self.budget.set_budget_config(60, True)  # no temp, no preserve
        self.assertIsNone(cfg["temp_limit_usd"])


class QuotaWriteTests(unittest.TestCase):
    """set_user_quotas / clear_user_quotas: one committed transaction, right shape."""

    def setUp(self):
        from owismind.storage import budget
        self.budget = budget
        self.calls = []
        self._orig = {
            "new_executor": budget.new_executor,
            "ensure_user_quota_table": budget.ensure_user_quota_table,
        }
        budget.new_executor = lambda: _FakeExec(self.calls)
        budget.ensure_user_quota_table = lambda: None

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(self.budget, name, fn)

    def test_set_multiple_users_one_transaction(self):
        n = self.budget.set_user_quotas(["u1", "u2", "u3"], 120.0, 30, "boost", "admin")
        self.assertEqual(n, 3)
        self.assertEqual(len(self.calls), 1)             # one transaction
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])
        # statement_timeout pre-query + one upsert per user.
        self.assertIn("SET LOCAL statement_timeout", self.calls[0]["pre"][0])
        self.assertEqual(len(self.calls[0]["pre"]), 4)
        joined = "\n".join(self.calls[0]["pre"])
        self.assertIn("120.000000", joined)
        self.assertIn("interval '1 day' * 30", joined)

    def test_permanent_when_no_days(self):
        self.budget.set_user_quotas(["u1"], 80.0, None, "", "admin")
        self.assertIn("NULL", self.calls[0]["pre"][1])   # upsert (after the timeout pre-query)

    def test_clear_is_single_delete(self):
        self.budget.clear_user_quotas(["u1", "u2"], "admin")
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])
        self.assertIn("SET LOCAL statement_timeout", self.calls[0]["pre"][0])
        self.assertIn("DELETE FROM", self.calls[0]["pre"][1])

    def test_empty_list_noop(self):
        self.assertEqual(self.budget.set_user_quotas([], 10.0, None, "", "a"), 0)
        self.assertEqual(self.budget.clear_user_quotas([], "a"), 0)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
