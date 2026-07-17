# Plugin/owismind/tests/test_run_state.py
"""Durable run storage (T2): 3 new _v1 tables + storage/run_state.py.

Provable without a live DSS runtime (project TEST-01 idiom, fake executor):
  - migrations: the 3 DDLs carry the EXACT spec section-10 columns + indexes;
  - run_state: lease claim/renew CAS, attempt_id fencing (the central test),
    plan replacement preserving completed steps, monotonic event sequencing,
    owner scoping, payload caps + truncation markers, bounded purge;
  - EVERY user-supplied value reaches SQL only through sql_value/nullable_value
    (with the stub, an escaped value renders as repr(value) - a raw single quote
    can therefore never appear bare-quoted in the statement text).
"""
import json
import os
import sys
import types
import unittest
import uuid

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so run_state / migrations import (NO install)."""
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

from owismind.storage import migrations   # noqa: E402
from owismind.storage import run_state    # noqa: E402


class FakeDf:
    """Tiny stand-in for a SQLExecutor2 DataFrame (len / empty / iloc[0][col])."""

    def __init__(self, rows=None):
        self.rows = [dict(r) for r in (rows or [])]

    def __len__(self):
        return len(self.rows)

    @property
    def empty(self):
        return not self.rows

    @property
    def iloc(self):
        return self.rows


class FakeExecutor:
    """Records every query_to_df call and pops scripted results in order."""

    def __init__(self, sink, results):
        self._sink = sink
        self._results = results

    def query_to_df(self, sql, pre_queries=None, post_queries=None):
        self._sink.append({
            "sql": sql,
            "pre": list(pre_queries or []),
            "post": list(post_queries or []),
        })
        if self._results:
            return self._results.pop(0)
        return FakeDf()


class RunStateTestCase(unittest.TestCase):
    """Shared fake-executor harness (no DB, no DDL, no pandas)."""

    def setUp(self):
        self.calls = []
        self.results = []
        names = (
            "new_executor",
            "ensure_agent_runs_table",
            "ensure_agent_run_steps_table",
            "ensure_agent_run_events_table",
            "ensure_users_table",
            "ensure_usage_monthly_table",
            "rows_to_json_safe",
        )
        self._orig = {name: getattr(run_state, name) for name in names}
        run_state.new_executor = lambda: FakeExecutor(self.calls, self.results)
        for name in names[1:-1]:
            setattr(run_state, name, lambda: None)
        run_state.rows_to_json_safe = (
            lambda df: df.rows if isinstance(df, FakeDf) else []
        )

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(run_state, name, fn)

    def all_sql(self):
        chunks = []
        for call in self.calls:
            chunks.append(call["sql"])
            chunks.extend(call["pre"])
        return "\n".join(chunks)


# --- Migrations: DDL of the 3 new _v1 tables ----------------------------------
class MigrationsDdlTests(unittest.TestCase):
    _RUNS_COLUMNS = (
        "run_id", "exchange_id", "session_id", "user_id", "agent_key", "mode",
        "status", "phase", "plan_revision", "replan_count", "step_cursor",
        "next_event_seq", "prompt_lang", "stop_requested", "lease_owner",
        "lease_until", "worker_heartbeat_at", "last_progress_at", "deadline_at",
        "retry_at", "error_code", "answer_text", "usage_json", "usage_accounted",
        "created_at", "updated_at", "finished_at",
    )
    _STEPS_COLUMNS = (
        "run_id", "step_id", "ordinal", "plan_revision", "kind", "title",
        "task_json", "depends_on_json", "output_ref", "checks_json", "status",
        "attempt_no", "attempt_id", "max_attempts", "next_retry_at",
        "result_status", "result_summary", "result_schema_json",
        "model_view_json", "generated_sql_json", "artifacts_json", "usage_json",
        "error_code", "started_at", "finished_at", "updated_at",
    )
    _EVENTS_COLUMNS = (
        "run_id", "seq", "attempt_id", "event_type", "payload", "created_at",
    )

    def test_three_logicals_registered_idempotent(self):
        for logical in (
            migrations.AGENT_RUNS_V1_LOGICAL,
            migrations.AGENT_RUN_STEPS_V1_LOGICAL,
            migrations.AGENT_RUN_EVENTS_V1_LOGICAL,
        ):
            self.assertIn(logical, migrations._DDL_BY_LOGICAL)
            self.assertIn(
                "CREATE TABLE IF NOT EXISTS", migrations._DDL_BY_LOGICAL[logical]
            )

    def test_runs_ddl_carries_exact_spec_columns(self):
        ddl = migrations._DDL_BY_LOGICAL[migrations.AGENT_RUNS_V1_LOGICAL]
        for column in self._RUNS_COLUMNS:
            self.assertIn(column, ddl)
        self.assertIn("PRIMARY KEY", ddl)
        self.assertIn("UNIQUE", ddl)  # exchange_id: one durable run per exchange

    def test_steps_ddl_carries_exact_spec_columns_and_composite_pk(self):
        ddl = migrations._DDL_BY_LOGICAL[migrations.AGENT_RUN_STEPS_V1_LOGICAL]
        for column in self._STEPS_COLUMNS:
            self.assertIn(column, ddl)
        self.assertIn("PRIMARY KEY (run_id, step_id)", ddl)

    def test_events_ddl_carries_exact_spec_columns_and_composite_pk(self):
        ddl = migrations._DDL_BY_LOGICAL[migrations.AGENT_RUN_EVENTS_V1_LOGICAL]
        for column in self._EVENTS_COLUMNS:
            self.assertIn(column, ddl)
        self.assertIn("PRIMARY KEY (run_id, seq)", ddl)

    def test_runs_indexes_match_spec(self):
        entries = dict(migrations._INDEXES_BY_LOGICAL[migrations.AGENT_RUNS_V1_LOGICAL])
        self.assertIn("(user_id, status, updated_at DESC)", entries.values())
        self.assertIn("(status, lease_until)", entries.values())
        self.assertIn("(session_id, updated_at DESC)", entries.values())

    def test_steps_indexes_match_spec(self):
        entries = dict(
            migrations._INDEXES_BY_LOGICAL[migrations.AGENT_RUN_STEPS_V1_LOGICAL]
        )
        self.assertIn("(run_id, ordinal)", entries.values())
        self.assertIn("(status, next_retry_at)", entries.values())

    def test_new_tables_have_no_alter_clauses(self):
        # Fresh _v1 tables: the no-ALTER rule applies with zero relaxation.
        for logical in (
            migrations.AGENT_RUNS_V1_LOGICAL,
            migrations.AGENT_RUN_STEPS_V1_LOGICAL,
            migrations.AGENT_RUN_EVENTS_V1_LOGICAL,
        ):
            self.assertNotIn(logical, migrations._ALTERS_BY_LOGICAL)

    def test_ensure_wrappers_exist(self):
        self.assertTrue(callable(migrations.ensure_agent_runs_table))
        self.assertTrue(callable(migrations.ensure_agent_run_steps_table))
        self.assertTrue(callable(migrations.ensure_agent_run_events_table))


# --- create_run / load_run / load_ledger --------------------------------------
class CreateAndLoadTests(RunStateTestCase):
    def test_create_run_inserts_queued_and_commits(self):
        run_id = run_state.create_run(
            "ex1", "sess1", "u1", "ag_abc", "smart", "2026-07-17T12:00:00Z"
        )
        uuid.UUID(run_id)  # a fresh uuid4, not an input echo
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        insert = call["pre"][1]
        self.assertIn("INSERT INTO", insert)
        self.assertIn(repr("queued"), insert)
        self.assertIn(repr("ex1"), insert)
        self.assertIn(repr("u1"), insert)
        self.assertIn(repr("ag_abc"), insert)

    def test_create_run_requires_exchange_user_agent(self):
        with self.assertRaises(ValueError):
            run_state.create_run("", "s", "u1", "ag", None, None)
        with self.assertRaises(ValueError):
            run_state.create_run("ex", "s", "", "ag", None, None)
        with self.assertRaises(ValueError):
            run_state.create_run("ex", "s", "u1", "", None, None)
        self.assertEqual(self.calls, [])

    def test_create_run_rejects_garbage_deadline(self):
        with self.assertRaises(ValueError):
            run_state.create_run("ex", "s", "u1", "ag", None, "not-a-date")
        self.assertEqual(self.calls, [])

    def test_load_run_owner_scoped_when_user_given(self):
        self.results.append(FakeDf([]))
        out = run_state.load_run("r1", user_id="u2")
        self.assertIsNone(out)  # logical 404 for a non-owner
        sql = self.calls[0]["sql"]
        self.assertIn("user_id = " + repr("u2"), sql)

    def test_load_run_without_user_has_no_owner_filter(self):
        self.results.append(FakeDf([{"run_id": "r1", "status": "queued"}]))
        out = run_state.load_run("r1")
        self.assertEqual(out["run_id"], "r1")
        self.assertNotIn("user_id", self.calls[0]["sql"])

    def test_load_run_is_read_only(self):
        self.results.append(FakeDf([]))
        run_state.load_run("r1")
        pre = "\n".join(self.calls[0]["pre"])
        self.assertIn("transaction_read_only", pre)
        self.assertEqual(self.calls[0]["post"], [])

    def test_load_ledger_orders_steps_by_ordinal(self):
        self.results.append(FakeDf([{"run_id": "r1", "status": "executing"}]))
        self.results.append(FakeDf([{"step_id": "s1", "ordinal": 0}]))
        out = run_state.load_ledger("r1")
        self.assertEqual(out["run"]["run_id"], "r1")
        self.assertEqual(out["steps"][0]["step_id"], "s1")
        self.assertIn("ORDER BY ordinal", self.calls[1]["sql"])

    def test_load_ledger_missing_run_is_none(self):
        self.results.append(FakeDf([]))
        self.assertIsNone(run_state.load_ledger("r1"))
        self.assertEqual(len(self.calls), 1)  # steps are never read


# --- Lease: claim / renew ------------------------------------------------------
class LeaseTests(RunStateTestCase):
    def test_claim_succeeds_on_expired_or_free_lease(self):
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.claim_run("r1", "worker-a", 45))
        call = self.calls[0]
        sql = call["sql"]
        self.assertIn("lease_owner IS NULL", sql)
        self.assertIn("lease_until < now()", sql)
        self.assertIn("(45 * interval '1 second')", sql)
        for status in run_state.RUN_ACTIVE_STATUSES:
            self.assertIn(repr(status), sql)
        self.assertEqual(call["post"], ["COMMIT"])

    def test_claim_refused_while_another_owner_holds_a_valid_lease(self):
        self.results.append(FakeDf([{"n": 0}]))
        self.assertFalse(run_state.claim_run("r1", "worker-b", 45))

    def test_claim_lease_seconds_clamped_and_validated(self):
        self.results.append(FakeDf([{"n": 1}]))
        run_state.claim_run("r1", "worker-a", 999999)
        self.assertIn("(3600 * interval '1 second')", self.calls[0]["sql"])
        with self.assertRaises(ValueError):
            run_state.claim_run("r1", "worker-a", "abc")

    def test_renew_refused_after_lease_theft(self):
        self.results.append(FakeDf([{"n": 0}]))
        self.assertFalse(run_state.renew_lease("r1", "worker-a", 45))
        sql = self.calls[0]["sql"]
        self.assertIn("lease_owner = " + repr("worker-a"), sql)

    def test_renew_succeeds_for_current_owner(self):
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.renew_lease("r1", "worker-a", 45))
        self.assertIn("worker_heartbeat_at = now()", self.calls[0]["sql"])


# --- Steps: start / complete (FENCING) / fail ----------------------------------
class StepTransitionTests(RunStateTestCase):
    def test_start_step_cas_from_pending_or_failed(self):
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.start_step("r1", "s1", "att-1"))
        sql = self.calls[0]["sql"]
        self.assertIn(repr("pending"), sql)
        self.assertIn(repr("failed"), sql)
        self.assertIn("attempt_no = attempt_no + 1", sql)
        self.assertIn("attempt_id = " + repr("att-1"), sql)
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])

    def test_start_step_refused_when_already_running(self):
        self.results.append(FakeDf([{"n": 0}]))
        self.assertFalse(run_state.start_step("r1", "s1", "att-2"))

    def test_complete_step_rejects_stale_attempt_id(self):
        # THE central fencing test: a zombie's late completion must not land.
        self.results.append(FakeDf([{"n": 0}]))
        ok = run_state.complete_step("r1", "s1", "att-old", {"summary": "late"})
        self.assertFalse(ok)
        sql = self.calls[0]["sql"]
        self.assertIn("attempt_id = " + repr("att-old"), sql)

    def test_complete_step_accepts_current_attempt(self):
        self.results.append(FakeDf([{"n": 1}]))
        ok = run_state.complete_step(
            "r1", "s1", "att-2",
            {"summary": "done", "result_status": "ok",
             "usage": {"promptTokens": 10}},
        )
        self.assertTrue(ok)
        sql = self.calls[0]["sql"]
        self.assertIn(repr("completed"), sql)
        self.assertIn("promptTokens", sql)

    def test_complete_step_caps_summary_at_2000(self):
        self.results.append(FakeDf([{"n": 1}]))
        run_state.complete_step("r1", "s1", "a", {"summary": "S" * 3000})
        sql = self.calls[0]["sql"]
        self.assertIn("S" * 2000, sql)
        self.assertNotIn("S" * 2001, sql)

    def test_complete_step_truncation_marker_on_oversized_model_view(self):
        self.results.append(FakeDf([{"n": 1}]))
        run_state.complete_step(
            "r1", "s1", "a", {"model_view": {"big": "M" * 30000}}
        )
        sql = self.calls[0]["sql"]
        self.assertIn("_truncated", sql)
        self.assertNotIn("M" * 25000, sql)

    def test_complete_step_caps_artifacts_at_8(self):
        self.results.append(FakeDf([{"n": 1}]))
        artifacts = [{"kind": "table", "title": "T%d" % i} for i in range(20)]
        run_state.complete_step("r1", "s1", "a", {"artifacts": artifacts})
        sql = self.calls[0]["sql"]
        self.assertIn("T7", sql)
        self.assertNotIn("T8", sql)

    def test_fail_step_is_fenced_and_records_retry(self):
        self.results.append(FakeDf([{"n": 1}]))
        ok = run_state.fail_step(
            "r1", "s1", "att-3", "mesh_timeout", retry_at="2026-07-17T12:00:05Z"
        )
        self.assertTrue(ok)
        sql = self.calls[0]["sql"]
        self.assertIn("attempt_id = " + repr("att-3"), sql)
        self.assertIn(repr("mesh_timeout"), sql)
        self.assertIn("next_retry_at = ", sql)
        self.assertNotIn("next_retry_at = NULL", sql)

    def test_fail_step_without_retry_stores_null(self):
        self.results.append(FakeDf([{"n": 1}]))
        run_state.fail_step("r1", "s1", "att-3", "hard_error")
        self.assertIn("next_retry_at = NULL", self.calls[0]["sql"])

    def test_fail_step_stale_attempt_refused(self):
        self.results.append(FakeDf([{"n": 0}]))
        self.assertFalse(run_state.fail_step("r1", "s1", "old", "x"))


# --- save_plan ------------------------------------------------------------------
class SavePlanTests(RunStateTestCase):
    def _plan(self, n):
        return {"steps": [
            {"step_id": "s%02d" % i, "kind": "mesh_call",
             "title": "Step %d" % i, "task": {"q": i}}
            for i in range(n)
        ]}

    def test_single_transaction_preserves_completed_steps(self):
        run_state.save_plan("r1", self._plan(2), 1)
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call["post"], ["COMMIT"])
        delete = call["pre"][1]
        insert = call["pre"][2]
        self.assertIn("DELETE FROM", delete)
        self.assertIn("<> " + repr("completed"), delete)
        self.assertIn("ON CONFLICT (run_id, step_id) DO NOTHING", insert)

    def test_updates_run_plan_revision(self):
        run_state.save_plan("r1", self._plan(1), 4)
        update = self.calls[0]["pre"][3]
        self.assertIn("plan_revision = 4", update)

    def test_step_count_capped_at_max_plan_steps(self):
        run_state.save_plan("r1", self._plan(50), 1)
        insert = self.calls[0]["pre"][2]
        self.assertIn(repr("s11"), insert)
        self.assertNotIn(repr("s12"), insert)
        self.assertEqual(run_state.MAX_PLAN_STEPS, 12)

    def test_ordinals_follow_plan_order(self):
        run_state.save_plan(
            "r1", {"steps": [{"step_id": "a"}, {"step_id": "b"}]}, 1
        )
        insert = self.calls[0]["pre"][2]
        self.assertIn(repr("b") + ", 1,", insert)

    def test_duplicate_step_ids_deduplicated(self):
        run_state.save_plan(
            "r1",
            {"steps": [{"step_id": "dup"}, {"step_id": "dup"},
                       {"step_id": "other"}]},
            1,
        )
        insert = self.calls[0]["pre"][2]
        self.assertEqual(insert.count(repr("dup")), 1)

    def test_task_json_over_cap_gets_truncation_marker(self):
        run_state.save_plan(
            "r1",
            {"steps": [{"step_id": "s1", "task": {"blob": "T" * 20000}}]},
            1,
        )
        insert = self.calls[0]["pre"][2]
        self.assertIn("_truncated", insert)
        self.assertNotIn("T" * 8001, insert)

    def test_task_json_carries_execution_payload_not_just_the_task_string(self):
        # Regression (v1.3 durable): task_json MUST persist capability_keys / args
        # (the whole execution payload), because _step_spec (durable_runner) rebuilds
        # the wfstep token from this column. Persisting only the bare task string
        # dropped them, so every execute step (specialist_query / correlate /
        # attribute_lookup) reached the agent with no capabilities and failed.
        run_state.save_plan(
            "r1",
            {"steps": [{"step_id": "S1", "kind": "specialist_query",
                        "title": "Revenue", "task": "get revenue for ACME",
                        "capability_keys": ["revenue_expert"],
                        "args": {"term": "ACME"}, "produces": "#S1"}]},
            1,
        )
        insert = self.calls[0]["pre"][2]
        self.assertIn("capability_keys", insert)
        self.assertIn("revenue_expert", insert)
        self.assertIn("args", insert)
        self.assertIn("get revenue for ACME", insert)


# --- append_events / read_events / read_activity --------------------------------
class EventTests(RunStateTestCase):
    def test_append_allocates_seq_from_runs_counter_in_one_batch(self):
        self.results.append(FakeDf([{"n": 7}]))
        out = run_state.append_events("r1", [
            {"event_type": "step_started", "payload": {"step": "s1"},
             "attempt_id": "a1"},
            {"event_type": "answer_delta", "payload": {"text": "hi"}},
        ])
        self.assertEqual(out, 7)
        self.assertEqual(len(self.calls), 1)  # ONE committed batch
        call = self.calls[0]
        self.assertIn("next_event_seq + 2", call["pre"][1])
        self.assertIn("next_event_seq - 2", call["pre"][2])
        self.assertIn(repr("step_started"), call["pre"][2])
        self.assertEqual(call["post"], ["COMMIT"])

    def test_append_caps_payload_with_truncation_marker(self):
        self.results.append(FakeDf([{"n": 1}]))
        run_state.append_events(
            "r1", [{"event_type": "x", "payload": {"blob": "P" * 9000}}]
        )
        insert = self.calls[0]["pre"][2]
        self.assertIn("_truncated", insert)
        self.assertNotIn("P" * 8001, insert)

    def test_append_drops_workflow_control_events(self):
        out = run_state.append_events(
            "r1", [{"event_type": "OWI_WORKFLOW_CONTROL", "payload": {}}]
        )
        self.assertIsNone(out)
        self.assertEqual(self.calls, [])

    def test_append_caps_batch_size(self):
        self.results.append(FakeDf([{"n": 200}]))
        events = [{"event_type": "e", "payload": {}} for _ in range(300)]
        run_state.append_events("r1", events)
        self.assertIn("next_event_seq + 200", self.calls[0]["pre"][1])

    def test_append_empty_is_noop(self):
        self.assertIsNone(run_state.append_events("r1", []))
        self.assertEqual(self.calls, [])

    def test_read_events_not_owner_is_logical_404(self):
        self.results.append(FakeDf([]))  # owner-scoped run read finds nothing
        out = run_state.read_events("r1", "intruder", 0)
        self.assertEqual(out["events"], [])
        self.assertTrue(out["done"])
        self.assertEqual(out["error"], "not_found")
        self.assertEqual(len(self.calls), 1)  # events are never read

    def test_read_events_advances_cursor_and_decodes_payload(self):
        self.results.append(FakeDf([{
            "run_id": "r1", "user_id": "u1", "status": "executing",
            "next_event_seq": 5, "error_code": None,
        }]))
        self.results.append(FakeDf([
            {"seq": 0, "attempt_id": "a", "event_type": "e",
             "payload": '{"a": 1}', "created_at": "t"},
            {"seq": 1, "attempt_id": "a", "event_type": "e",
             "payload": None, "created_at": "t"},
        ]))
        out = run_state.read_events("r1", "u1", 0)
        self.assertEqual(out["cursor"], 2)
        self.assertFalse(out["done"])
        self.assertIsNone(out["error"])
        self.assertEqual(out["events"][0]["payload"], {"a": 1})
        sql = self.calls[1]["sql"]
        self.assertIn("seq >= 0", sql)
        self.assertIn("LIMIT 500", sql)

    def test_read_events_done_on_terminal_run_fully_read(self):
        self.results.append(FakeDf([{
            "run_id": "r1", "user_id": "u1", "status": "completed",
            "next_event_seq": 2, "error_code": None,
        }]))
        self.results.append(FakeDf([
            {"seq": 0, "attempt_id": None, "event_type": "e",
             "payload": None, "created_at": "t"},
            {"seq": 1, "attempt_id": None, "event_type": "e",
             "payload": None, "created_at": "t"},
        ]))
        out = run_state.read_events("r1", "u1", 0)
        self.assertEqual(out["cursor"], 2)
        self.assertTrue(out["done"])

    def test_read_events_limit_clamped(self):
        self.results.append(FakeDf([{
            "run_id": "r1", "user_id": "u1", "status": "executing",
            "next_event_seq": 0, "error_code": None,
        }]))
        self.results.append(FakeDf([]))
        run_state.read_events("r1", "u1", "garbage", limit=99999)
        sql = self.calls[1]["sql"]
        self.assertIn("LIMIT 500", sql)
        self.assertIn("seq >= 0", sql)  # bad cursor coerces to 0

    def test_read_activity_joins_owner_scoped_on_exchange(self):
        self.results.append(FakeDf([
            {"seq": 0, "attempt_id": None, "event_type": "e",
             "payload": '{"k": 2}', "created_at": "t"},
        ]))
        out = run_state.read_activity("ex1", "u1")
        self.assertEqual(out[0]["payload"], {"k": 2})
        sql = self.calls[0]["sql"]
        self.assertIn("JOIN", sql)
        self.assertIn("exchange_id = " + repr("ex1"), sql)
        self.assertIn("user_id = " + repr("u1"), sql)

    def test_read_activity_without_identity_is_empty(self):
        self.assertEqual(run_state.read_activity("", "u1"), [])
        self.assertEqual(run_state.read_activity("ex1", ""), [])
        self.assertEqual(self.calls, [])


# --- Stop / recovery / status ----------------------------------------------------
class ControlTests(RunStateTestCase):
    def test_request_stop_is_owner_scoped_and_durable(self):
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.request_stop("r1", "u1"))
        sql = self.calls[0]["sql"]
        self.assertIn("stop_requested = true", sql)
        self.assertIn("user_id = " + repr("u1"), sql)
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])

    def test_request_stop_refused_for_non_owner(self):
        self.results.append(FakeDf([{"n": 0}]))
        self.assertFalse(run_state.request_stop("r1", "intruder"))

    def test_find_recoverable_runs_active_and_expired_lease_only(self):
        self.results.append(FakeDf([{"run_id": "r9"}]))
        out = run_state.find_recoverable_runs()
        self.assertEqual(out, ["r9"])
        sql = self.calls[0]["sql"]
        self.assertIn("lease_until IS NULL OR lease_until < now()", sql)
        self.assertIn("LIMIT 1", sql)
        for status in run_state.RUN_ACTIVE_STATUSES:
            self.assertIn(repr(status), sql)

    def test_find_recoverable_runs_limit_clamped(self):
        self.results.append(FakeDf([]))
        run_state.find_recoverable_runs(limit=999)
        self.assertIn("LIMIT 50", self.calls[0]["sql"])

    def test_set_run_status_rejects_unknown_status(self):
        with self.assertRaises(ValueError):
            run_state.set_run_status("r1", "exploded")
        self.assertEqual(self.calls, [])

    def test_set_run_status_terminal_stamps_finished_at(self):
        run_state.set_run_status("r1", "failed", error_code="mesh_down")
        update = self.calls[0]["pre"][1]
        self.assertIn("status = " + repr("failed"), update)
        self.assertIn("finished_at = COALESCE(finished_at, now())", update)
        self.assertIn("error_code = " + repr("mesh_down"), update)
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])

    def test_set_run_status_active_leaves_finished_at_and_error(self):
        run_state.set_run_status("r1", "executing")
        update = self.calls[0]["pre"][1]
        self.assertNotIn("finished_at", update)
        self.assertNotIn("error_code", update)


# --- finalize_exchange_guard ------------------------------------------------------
class FinalizeGuardTests(RunStateTestCase):
    def _run_row(self, usage_json=None):
        return {
            "run_id": "r1", "user_id": "u1", "status": "completed",
            "usage_json": usage_json, "next_event_seq": 0, "error_code": None,
        }

    def test_guard_flips_and_accounts_usage_in_one_statement(self):
        self.results.append(FakeDf([self._run_row()]))
        self.results.append(FakeDf([
            {"step_id": "s1", "usage_json":
                '{"promptTokens": 100, "completionTokens": 50, '
                '"estimatedCost": 0.01}'},
            {"step_id": "s2", "usage_json": None},
        ]))
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.finalize_exchange_guard("r1"))
        self.assertEqual(len(self.calls), 3)
        write = self.calls[2]
        sql = write["sql"]
        self.assertIn("usage_accounted = false", sql)   # the CAS arm
        self.assertIn("usage_accounted = true", sql)
        self.assertIn("ON CONFLICT (user_id, period_start)", sql)
        self.assertIn("total_input_tokens", sql)
        self.assertIn("100", sql)
        self.assertIn("0.0100000000", sql)
        self.assertEqual(write["post"], ["COMMIT"])

    def test_guard_second_call_is_false(self):
        self.results.append(FakeDf([self._run_row()]))
        self.results.append(FakeDf([]))
        self.results.append(FakeDf([{"n": 0}]))  # CAS matched no row
        self.assertFalse(run_state.finalize_exchange_guard("r1"))

    def test_guard_zero_usage_skips_increments(self):
        self.results.append(FakeDf([self._run_row()]))
        self.results.append(FakeDf([]))
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.finalize_exchange_guard("r1"))
        sql = self.calls[2]["sql"]
        self.assertNotIn("ON CONFLICT (user_id, period_start)", sql)

    def test_guard_missing_run_is_false_without_write(self):
        self.results.append(FakeDf([]))
        self.assertFalse(run_state.finalize_exchange_guard("r1"))
        self.assertEqual(len(self.calls), 1)

    def test_guard_falls_back_to_run_usage_json(self):
        self.results.append(FakeDf([self._run_row(
            usage_json='{"promptTokens": 7, "completionTokens": 3, '
                       '"estimatedCost": 0.5}')]))
        self.results.append(FakeDf([]))  # no steps carry usage
        self.results.append(FakeDf([{"n": 1}]))
        self.assertTrue(run_state.finalize_exchange_guard("r1"))
        sql = self.calls[2]["sql"]
        self.assertIn("ON CONFLICT (user_id, period_start)", sql)
        self.assertIn("0.5000000000", sql)


# --- purge -----------------------------------------------------------------------
class PurgeTests(RunStateTestCase):
    def test_purge_bounded_terminal_only_single_statement(self):
        self.results.append(FakeDf([{"n": 3}]))
        out = run_state.purge_finished_runs()
        self.assertEqual(out, 3)
        self.assertEqual(len(self.calls), 1)
        sql = self.calls[0]["sql"]
        self.assertIn("(14 * interval '1 day')", sql)
        self.assertIn("LIMIT 1000", sql)
        self.assertEqual(sql.count("DELETE FROM"), 3)  # events + steps + runs
        for status in run_state.RUN_TERMINAL_STATUSES:
            self.assertIn(repr(status), sql)
        self.assertEqual(self.calls[0]["post"], ["COMMIT"])

    def test_purge_clamps_bounds(self):
        self.results.append(FakeDf([{"n": 0}]))
        run_state.purge_finished_runs(older_than_days=0, max_runs=5000)
        sql = self.calls[0]["sql"]
        self.assertIn("(1 * interval '1 day')", sql)
        self.assertIn("LIMIT 1000", sql)


# --- Parameterization sweep --------------------------------------------------------
class ParameterizationTests(RunStateTestCase):
    """A value carrying a single quote must only ever appear ESCAPED - the
    bare-quoted concatenation is proof of raw interpolation. The shared-stub
    toSQL varies across sibling tests (repr, or true SQL quote-doubling), so
    both escaped renderings are accepted; the RAW form never is."""

    EVIL = "x'y"
    RAW = "'x'y'"
    ESCAPED_FORMS = (repr("x'y"), "x''y")

    def test_user_values_never_inlined_raw(self):
        self.results.extend([FakeDf([{"n": 1}]) for _ in range(6)])
        run_state.create_run("ex-" + self.EVIL, self.EVIL, self.EVIL,
                             "ag-" + self.EVIL, None, None)
        run_state.load_run("r-" + self.EVIL, user_id=self.EVIL)
        run_state.claim_run("r1", self.EVIL, 45)
        run_state.request_stop("r1", self.EVIL)
        run_state.complete_step("r1", "s-" + self.EVIL, self.EVIL,
                                {"summary": self.EVIL})
        run_state.read_activity("ex-" + self.EVIL, self.EVIL)
        blob = self.all_sql()
        self.assertNotIn(self.RAW, blob)
        self.assertTrue(any(form in blob for form in self.ESCAPED_FORMS),
                        "no escaped rendering of the evil value found")


if __name__ == "__main__":
    unittest.main()


class LoadRunByExchangeTests(unittest.TestCase):
    """Additive helpers (T3): by-exchange lookup + active-run-for-session."""

    def _patch_read(self, rows, captured):
        original_read = run_state._read
        original_safe = run_state.rows_to_json_safe
        original_ensure = run_state.ensure_agent_runs_table
        run_state._read = lambda sql: (captured.append(sql) or rows)
        run_state.rows_to_json_safe = lambda df: df
        run_state.ensure_agent_runs_table = lambda: None
        return original_read, original_safe, original_ensure

    def _unpatch(self, originals):
        run_state._read, run_state.rows_to_json_safe, \
            run_state.ensure_agent_runs_table = originals

    def test_by_exchange_owner_scoped_and_parameterized(self):
        captured = []
        originals = self._patch_read([{"run_id": "r1", "user_id": "u1"}], captured)
        try:
            row = run_state.load_run_by_exchange("ex'--1", user_id="u1")
        finally:
            self._unpatch(originals)
        self.assertEqual(row["run_id"], "r1")
        sql = captured[0]
        # escaped through sql_value: rendered either as the stub's repr form or
        # as SQL-standard quote doubling - NEVER as the bare-quoted raw value
        self.assertTrue(repr("ex'--1") in sql or "ex''--1" in sql, sql)
        self.assertNotIn("= 'ex'--1'", sql)
        self.assertIn("user_id = ", sql)

    def test_by_exchange_unknown_returns_none(self):
        captured = []
        originals = self._patch_read([], captured)
        try:
            self.assertIsNone(run_state.load_run_by_exchange("nope"))
        finally:
            self._unpatch(originals)
        self.assertIsNone(run_state.load_run_by_exchange(""))
        self.assertIsNone(run_state.load_run_by_exchange(None))

    def test_find_active_run_for_session_filters_active_statuses(self):
        captured = []
        originals = self._patch_read([{"run_id": "r2"}], captured)
        try:
            row = run_state.find_active_run_for_session("sess-1", user_id="u1")
        finally:
            self._unpatch(originals)
        self.assertEqual(row["run_id"], "r2")
        sql = captured[0]
        self.assertIn("status IN (", sql)
        self.assertIn("ORDER BY updated_at DESC LIMIT 1", sql)
        for terminal in ("'completed'", "'failed'"):
            self.assertNotIn(terminal, sql)

    def test_find_active_requires_session(self):
        self.assertIsNone(run_state.find_active_run_for_session(""))
        self.assertIsNone(run_state.find_active_run_for_session(None))
