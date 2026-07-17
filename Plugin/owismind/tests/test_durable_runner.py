# Plugin/owismind/tests/test_durable_runner.py
"""Durable workflow runner (T3): state machine, retries, caps, finalisation.

DSS-free: run_state is replaced by an in-memory store honouring the SAME
contracts (fencing, retry scheduling, plan replacement), streaming is a scripted
generator keyed on the workflow command found in the message tail, and the
storage side-effects (chat_v5 / artifacts / settings) are recording fakes.
The worker body (_run_workflow) is driven SYNCHRONOUSLY: no threads in tests.
"""
import json
import os
import re
import sys
import threading
import types
import unittest
from datetime import datetime, timedelta, timezone

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
    for name, value in (("Constant", lambda v: v),
                        ("toSQL", lambda c, dialect=None: repr(c)),
                        ("Dialects", type("Dialects", (), {"POSTGRES": "postgres"}))):
        if not hasattr(sql_mod, name):
            setattr(sql_mod, name, value)
    dk.sql = sql_mod
    if "pandas" not in sys.modules:
        sys.modules["pandas"] = types.ModuleType("pandas")


_ensure_dataiku_stub()

from owismind.agents import context, durable_runner  # noqa: E402


TERMINAL = ("completed", "partial", "failed", "stopped",
            "deadline_reached", "quota_blocked")


class MemoryRunState(object):
    """In-memory stand-in honouring run_state's contracts used by the runner."""

    def __init__(self):
        self.runs = {}
        self.steps = {}            # (run_id, step_id) -> dict
        self.events = []           # (run_id, event_type, payload)
        self.accounted = set()

    # -- runs -------------------------------------------------------------------
    def create_run(self, exchange_id, session_id, user_id, agent_key, mode,
                   deadline_at):
        for run in self.runs.values():
            if run["exchange_id"] == exchange_id:
                raise Exception("duplicate key value violates unique constraint")
        run_id = "run-%d" % (len(self.runs) + 1)
        self.runs[run_id] = {
            "run_id": run_id, "exchange_id": exchange_id,
            "session_id": session_id, "user_id": user_id,
            "agent_key": agent_key, "mode": mode, "status": "queued",
            "plan_revision": 0, "replan_count": 0, "stop_requested": False,
            "deadline_at": deadline_at, "error_code": None, "usage_json": None,
        }
        return run_id

    def load_run(self, run_id, user_id=None):
        run = self.runs.get(run_id)
        if run is None:
            return None
        if user_id is not None and run["user_id"] != user_id:
            return None
        return dict(run)

    def load_run_by_exchange(self, exchange_id, user_id=None):
        for run in self.runs.values():
            if run["exchange_id"] == exchange_id:
                if user_id is not None and run["user_id"] != user_id:
                    return None
                return dict(run)
        return None

    def claim_run(self, run_id, lease_owner, lease_seconds):
        return run_id in self.runs

    def renew_lease(self, run_id, lease_owner, lease_seconds):
        return True

    def set_run_status(self, run_id, status, error_code=None):
        run = self.runs[run_id]
        run["status"] = status
        if error_code is not None:
            run["error_code"] = error_code

    def request_stop(self, run_id, user_id):
        run = self.runs.get(run_id)
        if run is None or run["user_id"] != user_id:
            return False
        run["stop_requested"] = True
        return True

    def find_recoverable_runs(self, limit=1):
        return [rid for rid, r in self.runs.items()
                if r["status"] not in TERMINAL][:limit]

    def find_active_run_for_session(self, session_id, user_id=None):
        for run in self.runs.values():
            if run["session_id"] == session_id and run["status"] not in TERMINAL:
                if user_id is not None and run["user_id"] != user_id:
                    continue
                return dict(run)
        return None

    # -- plan + steps -------------------------------------------------------------
    def save_plan(self, run_id, plan_dict, plan_revision):
        run = self.runs[run_id]
        run["plan_revision"] = plan_revision
        kept = {k: v for k, v in self.steps.items()
                if k[0] != run_id or v["status"] == "completed"}
        self.steps = kept
        ordinal = 0
        for step in plan_dict["steps"]:
            key = (run_id, step["id"])
            if key in self.steps:
                continue
            self.steps[key] = {
                "run_id": run_id, "step_id": step["id"], "ordinal": ordinal,
                "kind": step.get("kind"), "title": step.get("title"),
                "task_json": json.dumps({
                    "task": step.get("task"),
                    "capability_keys": step.get("capability_keys"),
                    "args": step.get("args"),
                    "depends_on": step.get("depends_on") or [],
                    "checks": step.get("checks") or [],
                }),
                "depends_on_json": json.dumps(step.get("depends_on") or []),
                "checks_json": json.dumps(step.get("checks") or []),
                "status": "pending", "attempt_no": 0, "attempt_id": None,
                "next_retry_at": None, "error_code": None,
                "result_summary": None, "result_schema_json": None,
                "model_view_json": None, "generated_sql_json": None,
                "artifacts_json": None, "usage_json": None, "output_ref": None,
            }
            ordinal += 1

    def load_ledger(self, run_id):
        run = self.load_run(run_id)
        if run is None:
            return None
        steps = sorted((dict(s) for (rid, _), s in self.steps.items()
                        if rid == run_id), key=lambda s: s["ordinal"])
        return {"run": run, "steps": steps}

    def start_step(self, run_id, step_id, attempt_id):
        step = self.steps.get((run_id, step_id))
        if step is None or step["status"] not in ("pending", "failed"):
            return False
        step.update(status="running", attempt_id=attempt_id,
                    attempt_no=step["attempt_no"] + 1, next_retry_at=None,
                    error_code=None)
        return True

    def complete_step(self, run_id, step_id, attempt_id, result):
        step = self.steps.get((run_id, step_id))
        if step is None or step["attempt_id"] != attempt_id:
            return False                      # the fence
        step.update(
            status="completed",
            result_summary=result.get("summary"),
            result_schema_json=json.dumps(result.get("schema"))
            if result.get("schema") is not None else None,
            model_view_json=json.dumps(result.get("model_view"))
            if result.get("model_view") is not None else None,
            generated_sql_json=json.dumps(result.get("generated_sql"))
            if result.get("generated_sql") is not None else None,
            artifacts_json=json.dumps(result.get("artifacts"))
            if result.get("artifacts") is not None else None,
            usage_json=json.dumps(result.get("usage"))
            if result.get("usage") is not None else None,
            output_ref=result.get("output_ref"),
        )
        return True

    def fail_step(self, run_id, step_id, attempt_id, error_code, retry_at=None):
        step = self.steps.get((run_id, step_id))
        if step is None or step["attempt_id"] != attempt_id:
            return False
        step.update(status="failed", error_code=error_code,
                    next_retry_at=retry_at)
        return True

    # -- events + finalisation ------------------------------------------------------
    def append_events(self, run_id, events):
        for e in events:
            self.events.append((run_id, e.get("event_type"), e.get("payload")))
        return len(self.events)

    def read_events(self, run_id, user_id, cursor, limit=500):
        run = self.load_run(run_id, user_id)
        if run is None:
            return None
        mine = [{"event_type": t, "payload": p}
                for rid, t, p in self.events if rid == run_id]
        return {"events": mine[cursor:], "cursor": len(mine), "done": False,
                "error": None, "status": run["status"]}

    def read_activity(self, exchange_id, user_id):
        run = self.load_run_by_exchange(exchange_id, user_id)
        if run is None:
            return []
        return [{"event_type": t, "payload": p}
                for rid, t, p in self.events if rid == run["run_id"]]

    def finalize_exchange_guard(self, run_id):
        if run_id in self.accounted:
            return False
        self.accounted.add(run_id)
        return True


class RecorderChat(object):
    def __init__(self):
        self.saved = []
        self.exchanges = {}

    def read_exchange(self, user_id, exchange_id):
        return self.exchanges.get(exchange_id)

    def save_assistant_message(self, exchange_id, text, generated_sql=None,
                               usage=None):
        self.saved.append({"exchange_id": exchange_id, "text": text,
                           "generated_sql": generated_sql, "usage": usage})


class RecorderArtifacts(object):
    def __init__(self):
        self.saved = []

    def save_artifacts(self, exchange_id, user_id, artifacts):
        self.saved.append((exchange_id, user_id, artifacts))


class FakeSettings(object):
    def __init__(self, entry=None):
        self.entry = entry if entry is not None else {
            "project_key": "PK", "agent_id": "agent:x", "profile": {}}

    def resolve_enabled_agent(self, key):
        return self.entry


_CMD_RE = re.compile(r"⟦owi:workflow=v1;command=([a-z]+);")

_PLAN = {
    "goal": "Compare revenue and tickets",
    "steps": [
        {"id": "S1", "kind": "specialist_query", "title": "Revenue by client",
         "capability_keys": ["revenue_expert"], "task": "get revenue",
         "depends_on": [], "checks": ["non_empty", "metric_present"]},
        {"id": "S2", "kind": "render", "title": "Render the comparison",
         "capability_keys": [], "task": "render", "depends_on": ["S1"],
         "checks": []},
    ],
}

_OK_EXEC = {"status": "ok", "summary": "10 rows of revenue",
            "row_count": 10, "columns": ["customer", "revenue"],
            "schema": ["customer", "revenue"],
            "model_view": {"columns": ["customer", "revenue"],
                           "rows": [["a", 1]], "row_count": 10},
            "generated_sql": [{"sql": "SELECT 1", "success": True}],
            "usage": {"promptTokens": 10, "completionTokens": 5,
                      "estimatedCost": 0.001},
            "output_ref": "#S1"}


def scripted_streaming(script):
    """streaming.run_agent_streamed stand-in: pops the next reaction per command."""

    def run_agent_streamed(project_key, agent_id, messages):
        message = messages[-1]["content"]
        m = _CMD_RE.search(message)
        command = m.group(1) if m else "?"
        queue = script.get(command) or []
        reaction = queue.pop(0) if queue else {"control": {}}
        if isinstance(reaction, Exception):
            raise reaction
        if "control" in reaction:
            yield {"type": "workflow_control", "command": command,
                   "payload": reaction["control"]}
        for text in reaction.get("answer", []):
            yield {"type": "answer_delta", "text": text}

    return run_agent_streamed


class RunnerHarness(unittest.TestCase):
    """Base: patch durable_runner collaborators with recording fakes."""

    def setUp(self):
        self.store = MemoryRunState()
        self.chat = RecorderChat()
        self.artifacts = RecorderArtifacts()
        self.settings = FakeSettings()
        self._saved = {name: getattr(durable_runner, name) for name in
                       ("run_state", "chat_v5", "artifacts_storage",
                        "settings", "streaming")}
        durable_runner.run_state = self.store
        durable_runner.chat_v5 = self.chat
        durable_runner.artifacts_storage = self.artifacts
        durable_runner.settings = self.settings
        durable_runner._WORKERS.clear()

    def tearDown(self):
        for name, value in self._saved.items():
            setattr(durable_runner, name, value)
        durable_runner._WORKERS.clear()

    def _mk_run(self, mode="smart", deadline_in=900):
        deadline = (datetime.now(timezone.utc)
                    + timedelta(seconds=deadline_in)).isoformat()
        return self.store.create_run("ex-1", "sess-1", "u1", "ag_key",
                                     mode, deadline)

    def _drive(self, run_id, script, question="compare revenue and tickets"):
        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=scripted_streaming(script))
        lost = threading.Event()
        durable_runner._run_workflow(run_id, "owner-1", question, None, lost)

    def _event_types(self):
        return [t for _, t, _ in self.store.events]


class HappyPathTests(RunnerHarness):
    def test_plan_execute_render_synthesize_completed(self):
        run_id = self._mk_run()
        render_ok = dict(_OK_EXEC, summary="rendered", output_ref="#S2")
        self._drive(run_id, {
            "plan": [{"control": {"plan": _PLAN}}],
            "execute": [{"control": _OK_EXEC}, {"control": render_ok}],
            "synthesize": [{"control": {"answer": "Final analysis."}}],
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertEqual(len(self.chat.saved), 1)
        self.assertEqual(self.chat.saved[0]["text"], "Final analysis.")
        # merged SQL + usage reached chat_v5
        self.assertEqual(len(self.chat.saved[0]["generated_sql"]), 2)
        self.assertEqual(self.chat.saved[0]["usage"]["promptTokens"], 20)
        types_seen = self._event_types()
        self.assertIn("PLAN_READY", types_seen)
        self.assertIn("STEP_STARTED", types_seen)
        self.assertIn("STEP_COMPLETED", types_seen)
        self.assertIn("DONE", types_seen)
        # usage accounted exactly once
        self.assertIn(run_id, self.store.accounted)

    def test_message_layout_contract_honoured(self):
        run_id = self._mk_run()
        captured = []

        def capture_stream(project_key, agent_id, messages):
            captured.append(messages[-1]["content"])
            m = _CMD_RE.search(messages[-1]["content"])
            cmd = m.group(1) if m else "?"
            if cmd == "plan":
                yield {"type": "workflow_control", "command": "plan",
                       "payload": {"plan": _PLAN}}
            elif cmd == "execute":
                yield {"type": "workflow_control", "command": "execute",
                       "payload": _OK_EXEC}
            else:
                yield {"type": "workflow_control", "command": cmd,
                       "payload": {"answer": "done"}}

        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=capture_stream)
        lost = threading.Event()
        durable_runner._run_workflow(run_id, "o", "q", None, lost)
        self.assertGreaterEqual(len(captured), 3)
        for message in captured:
            first = message.index("⟦")
            tail = message[first:]
            # after the first token char: only control tokens and whitespace
            # (the agent's frozen rule: "only whitespace and other owi control
            # tokens may follow" - anything else silently degrades to legacy)
            self.assertEqual(
                re.sub(r"⟦owi:[a-z_]+=[^⟧]*⟧", "", tail).strip(), "")
        # the execute message carries the wfstep token
        exec_msgs = [m for m in captured if "command=execute" in m]
        self.assertTrue(all("⟦owi:wfstep=" in m for m in exec_msgs))


class RetryTests(RunnerHarness):
    def test_transient_failure_retries_then_completes(self):
        run_id = self._mk_run()
        self._drive(run_id, {
            "plan": [{"control": {"plan": _PLAN}}],
            "execute": [ConnectionError("connection reset by peer"),
                        {"control": _OK_EXEC},
                        {"control": dict(_OK_EXEC, output_ref="#S2")}],
            "synthesize": [{"control": {"answer": "ok"}}],
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertIn("STEP_RETRYING", self._event_types())
        s1 = self.store.steps[(run_id, "S1")]
        self.assertEqual(s1["attempt_no"], 2)

    def test_failed_check_goes_to_replan_not_blind_retry(self):
        # A deterministic check failure is a VALIDATION error: no backoff retry
        # of the identical call - the repair mechanism is the replan.
        run_id = self._mk_run()
        empty = dict(_OK_EXEC, row_count=0)
        self._drive(run_id, {
            "plan": [{"control": {"plan": _PLAN}}],
            "execute": [{"control": empty},           # S1 fails its non_empty check
                        {"control": _OK_EXEC},         # S1 after replan
                        {"control": dict(_OK_EXEC, output_ref="#S2")}],
            "replan": [{"control": {"plan": _PLAN}}],  # fresh revision, same shape
            "synthesize": [{"control": {"answer": "ok"}}],
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "completed")
        self.assertIn("REPLANNING", self._event_types())
        self.assertEqual(run["plan_revision"], 2)      # replan persisted in SQL

    def test_quota_terminates_the_run_without_retry(self):
        run_id = self._mk_run()
        self._drive(run_id, {
            "plan": [{"control": {"plan": _PLAN}}],
            "execute": [Exception("blocking quota reached for this connection")],
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "quota_blocked")
        s1 = self.store.steps[(run_id, "S1")]
        self.assertEqual(s1["attempt_no"], 1)      # never retried
        # an honest partial reached the exchange
        self.assertEqual(len(self.chat.saved), 1)

    def test_fatal_step_failure_goes_to_replan_then_partial(self):
        run_id = self._mk_run()
        self._drive(run_id, {
            "plan": [{"control": {"plan": _PLAN}}],
            # structured refusal (fatal): no retry_at -> replan path
            "execute": [{"control": {"status": "error", "error": "bad step"}}],
            "replan": [{"control": {}}],           # replan yields nothing usable
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "partial")
        self.assertIn("REPLANNING", self._event_types())


class ControlFlowTests(RunnerHarness):
    def test_stop_requested_yields_stopped_partial(self):
        run_id = self._mk_run()
        store = self.store

        def stopping_stream(project_key, agent_id, messages):
            m = _CMD_RE.search(messages[-1]["content"])
            cmd = m.group(1) if m else "?"
            if cmd == "plan":
                yield {"type": "workflow_control", "command": "plan",
                       "payload": {"plan": _PLAN}}
                return
            # user stops during the first execute
            store.runs[run_id]["stop_requested"] = True
            yield {"type": "workflow_control", "command": cmd,
                   "payload": _OK_EXEC}

        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=stopping_stream)
        durable_runner._run_workflow(run_id, "o", "q", None, threading.Event())
        self.assertEqual(self.store.load_run(run_id)["status"], "stopped")
        self.assertEqual(len(self.chat.saved), 1)  # partial persisted

    def test_deadline_reached_yields_partial(self):
        run_id = self._mk_run(deadline_in=-5)      # already past
        self._drive(run_id, {"plan": [{"control": {"plan": _PLAN}}]})
        self.assertEqual(self.store.load_run(run_id)["status"],
                         "deadline_reached")

    def test_lost_lease_stands_down_silently(self):
        run_id = self._mk_run()
        lost = threading.Event()
        lost.set()
        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=scripted_streaming(
                {"plan": [{"control": {"plan": _PLAN}}]}))
        durable_runner._run_workflow(run_id, "o", "q", None, lost)
        # no terminal status was forced by the standing-down worker
        self.assertNotIn(self.store.load_run(run_id)["status"], TERMINAL)

    def test_invalid_plan_fails_closed(self):
        run_id = self._mk_run()
        bad = {"steps": [{"id": "S1"}]}            # missing kind/title
        self._drive(run_id, {"plan": [{"control": {"plan": bad}}]})
        self.assertEqual(self.store.load_run(run_id)["status"], "failed")


class StartWorkflowTests(RunnerHarness):
    def setUp(self):
        super(StartWorkflowTests, self).setUp()
        self._spawned = []
        self._orig_spawn = durable_runner._spawn_worker
        durable_runner._spawn_worker = (
            lambda *a, **k: self._spawned.append(a))

    def tearDown(self):
        durable_runner._spawn_worker = self._orig_spawn
        super(StartWorkflowTests, self).tearDown()

    def test_start_creates_and_spawns(self):
        out = durable_runner.start_workflow("ex-9", "s", "u1", "k", "smart", "q")
        self.assertEqual(out["exchange_id"], "ex-9")
        self.assertEqual(len(self._spawned), 1)

    def test_start_is_idempotent_on_existing_exchange(self):
        first = durable_runner.start_workflow("ex-9", "s", "u1", "k", "smart", "q")
        again = durable_runner.start_workflow("ex-9", "s", "u1", "k", "smart", "q")
        self.assertEqual(first["run_id"], again["run_id"])

    def test_global_capacity_cap_raises_busy(self):
        for i in range(durable_runner.MAX_ACTIVE_WORKFLOWS):
            durable_runner._WORKERS["r%d" % i] = {
                "user_id": "u%d" % i,
                "thread": types.SimpleNamespace(is_alive=lambda: True)}
        with self.assertRaises(durable_runner.BusyError):
            durable_runner.start_workflow("ex-9", "s", "u1", "k", "smart", "q")

    def test_per_user_cap_raises_busy(self):
        durable_runner._WORKERS["r0"] = {
            "user_id": "u1",
            "thread": types.SimpleNamespace(is_alive=lambda: True)}
        with self.assertRaises(durable_runner.BusyError):
            durable_runner.start_workflow("ex-9", "s", "u1", "k", "smart", "q")

    def test_reservation_survives_the_reaper(self):
        # A concurrent same-user start must NOT purge a sibling's reservation
        # (thread=None) before counting - else the per-user cap is defeated.
        durable_runner._WORKERS["resv-ex-a"] = {
            "user_id": "u1", "thread": None, "reservation": True}
        durable_runner._reap_dead_workers_locked()
        self.assertIn("resv-ex-a", durable_runner._WORKERS)
        # a genuinely dead worker (thread not alive, not a reservation) IS reaped
        durable_runner._WORKERS["r-dead"] = {
            "user_id": "u2",
            "thread": types.SimpleNamespace(is_alive=lambda: False)}
        durable_runner._reap_dead_workers_locked()
        self.assertNotIn("r-dead", durable_runner._WORKERS)
        self.assertIn("resv-ex-a", durable_runner._WORKERS)

    def test_second_same_user_start_blocked_while_reservation_held(self):
        # Simulate the TOCTOU window: a live reservation for u1 is present when a
        # second start for u1 arrives - it must be refused, not slip through.
        durable_runner._WORKERS["resv-ex-a"] = {
            "user_id": "u1", "thread": None, "reservation": True}
        with self.assertRaises(durable_runner.BusyError):
            durable_runner.start_workflow("ex-b", "s", "u1", "k", "smart", "q")


class AdapterTests(RunnerHarness):
    def test_poll_durable_projects_without_lease_fields(self):
        run_id = self._mk_run()
        self.store.append_events(run_id, [
            {"event_type": "PLAN_READY", "payload": {"goal": "g"}}])
        out = durable_runner.poll_durable(run_id, "u1", 0)
        self.assertEqual(len(out["events"]), 1)
        self.assertFalse(out["done"])
        flat = json.dumps(out)
        for banned in ("lease_owner", "lease_until", "worker_heartbeat_at"):
            self.assertNotIn(banned, flat)

    def test_poll_durable_owner_scoped(self):
        run_id = self._mk_run()
        self.assertIsNone(durable_runner.poll_durable(run_id, "intruder", 0))

    def test_active_run_projection_strips_lease_fields(self):
        self._mk_run()
        out = durable_runner.active_run_for_session("sess-1", "u1")
        self.assertEqual(out["session_id"], "sess-1")
        for banned in ("lease_owner", "lease_until", "worker_heartbeat_at",
                       "agent_key"):
            self.assertNotIn(banned, out)


class ReviewFixTests(RunnerHarness):
    """Locks for the Codex cross-review findings on T3."""

    def test_recovery_rearms_steps_left_running_by_a_dead_worker(self):
        run_id = self._mk_run()
        self.store.save_plan(run_id, _PLAN, 1)
        self.store.runs[run_id]["status"] = "executing"
        # simulate a worker that died mid-Mesh-call: S1 stuck in 'running'
        s1 = self.store.steps[(run_id, "S1")]
        s1.update(status="running", attempt_id="dead-attempt", attempt_no=1)
        self._drive(run_id, {
            "execute": [{"control": _OK_EXEC},
                        {"control": dict(_OK_EXEC, output_ref="#S2")}],
            "synthesize": [{"control": {"answer": "recovered fine"}}],
        })
        run = self.store.load_run(run_id)
        self.assertEqual(run["status"], "completed")   # S1 was re-run, not skipped
        self.assertEqual(self.store.steps[(run_id, "S1")]["status"], "completed")
        self.assertNotEqual(self.store.steps[(run_id, "S1")]["attempt_id"],
                            "dead-attempt")            # fresh fenced attempt

    def test_raw_control_chunk_never_leaks_to_public_feed(self):
        run_id = self._mk_run()

        def leaky_stream(project_key, agent_id, messages):
            m = _CMD_RE.search(messages[-1]["content"])
            cmd = m.group(1) if m else "?"
            if cmd == "plan":
                # pre-T5 shape: the control arrives as a RAW agent_event
                yield {"type": "agent_event",
                       "eventKind": "OWI_WORKFLOW_CONTROL",
                       "eventData": {"payload": {"plan": _PLAN}}}
            elif cmd == "execute":
                yield {"type": "workflow_control", "command": "execute",
                       "payload": _OK_EXEC}
            else:
                yield {"type": "workflow_control", "command": cmd,
                       "payload": {"answer": "done"}}

        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=leaky_stream)
        durable_runner._run_workflow(run_id, "o", "q", None, threading.Event())
        self.assertEqual(self.store.load_run(run_id)["status"], "completed")
        for _, event_type, _payload in self.store.events:
            self.assertNotIn("OWI_WORKFLOW_CONTROL", event_type or "")

    def test_side_channel_sql_and_usage_attach_to_the_step(self):
        run_id = self._mk_run()
        bare = {k: v for k, v in _OK_EXEC.items()
                if k not in ("generated_sql", "usage")}

        def side_channel_stream(project_key, agent_id, messages):
            m = _CMD_RE.search(messages[-1]["content"])
            cmd = m.group(1) if m else "?"
            if cmd == "plan":
                yield {"type": "workflow_control", "command": "plan",
                       "payload": {"plan": _PLAN}}
            elif cmd == "execute":
                # real orchestrator shape: SQL + usage arrive as stream events
                yield {"type": "generated_sql", "sql": "SELECT 42",
                       "success": True, "rowCount": 1}
                yield {"type": "usage_summary",
                       "usage": {"promptTokens": 7, "completionTokens": 3,
                                 "estimatedCost": 0.0005}}
                yield {"type": "workflow_control", "command": "execute",
                       "payload": bare}
            else:
                yield {"type": "workflow_control", "command": cmd,
                       "payload": {"answer": "done"}}

        durable_runner.streaming = types.SimpleNamespace(
            run_agent_streamed=side_channel_stream)
        durable_runner._run_workflow(run_id, "o", "q", None, threading.Event())
        self.assertEqual(self.store.load_run(run_id)["status"], "completed")
        s1 = self.store.steps[(run_id, "S1")]
        self.assertIn("SELECT 42", s1["generated_sql_json"] or "")
        self.assertIn("promptTokens", s1["usage_json"] or "")
        # merged into the exchange too
        self.assertTrue(self.chat.saved[0]["generated_sql"])


class UnitTests(unittest.TestCase):
    def test_classify_failure(self):
        cf = durable_runner.classify_failure
        self.assertEqual(cf(ConnectionError("connection refused")), "transient")
        self.assertEqual(cf(Exception("HTTP 429 rate limit")), "transient")
        self.assertEqual(cf(Exception("blocking quota reached")), "quota")
        self.assertEqual(cf(ValueError("rate limit")), "fatal")   # bugs stay fatal
        self.assertEqual(cf(Exception("weird explosion")), "fatal")

    def test_evaluate_checks(self):
        ev = durable_runner.evaluate_checks
        good = {"row_count": 3, "columns": ["k", "v"]}
        self.assertIsNone(ev(["non_empty", "metric_present",
                              "join_key_present"], good))
        self.assertEqual(ev(["non_empty"], {"row_count": 0}), "non_empty")
        self.assertEqual(ev(["metric_present"], {"columns": ["k"]}),
                         "metric_present")
        self.assertIsNone(ev(["unknown_gate"], {}))               # forward-compat

    def test_supervisor_start_is_idempotent(self):
        # patch the loop body so no real scanning happens
        original = durable_runner._supervisor_loop
        durable_runner._supervisor_loop = lambda: threading.Event().wait(0.05)
        try:
            durable_runner._SUPERVISOR["thread"] = None
            durable_runner.start_supervisor()
            first = durable_runner._SUPERVISOR["thread"]
            durable_runner.start_supervisor()
            self.assertIs(durable_runner._SUPERVISOR["thread"], first)
        finally:
            durable_runner._supervisor_loop = original
            durable_runner._SUPERVISOR["thread"] = None


if __name__ == "__main__":
    unittest.main()
