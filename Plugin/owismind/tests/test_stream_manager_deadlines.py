# Plugin/owismind/tests/test_stream_manager_deadlines.py
"""Per-mode legacy run deadlines + friendly terminal error codes (stream_manager).

The single MAX_RUN_SECONDS=300 wall killed long "claude" mode runs. The manager now
resolves a per-mode wall-clock deadline at registration (LEGACY_MAX_RUN_SECONDS_BY_MODE
via ``resolve_run_deadline``) and the cooperative stop check applies THAT deadline.
The terminal error code for a deadline hit is ``"deadline_reached"`` (was
``"run_timeout"``); the abandoned cut keeps its historical ``"run_abandoned"`` code.
The modeless path keeps exactly the historical 300.0s wall (anti-regression).

Coverage (all mocked, no DSS runtime - mirrors the sibling route/storage tests):
  - resolve_run_deadline: 300/300/600/1200 + fallback 300.0 on unknown/garbage modes,
    and the frozen LEGACY_MAX_RUN_SECONDS_BY_MODE interface table (consumed by T3);
  - _stop_reason(run_id, started_at, deadline_s): None under the deadline,
    "deadline_reached" beyond it, "stopped" priority, "abandoned" preserved
    (monkeypatched time.monotonic);
  - start_run: stores the mode on the run state and hands the RESOLVED per-mode
    deadline to the worker thread (worker captured, no agent ever runs);
  - _worker: applies the deadline it was handed - a 400s-elapsed run survives a
    1200s (claude) deadline, dies with "deadline_reached" under the 300s default,
    and an abandoned run still reports "run_abandoned";
  - HARD_TTL_SECONDS covers the longest per-mode deadline (a live claude run must
    never be memory-evicted before its own deadline).

A minimal ``dataiku`` stub is installed so the modules import (NO install);
unittest discover shares one sys.modules, so the stubs are additive.
"""
import os
import sys
import threading
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))


def _ensure_dataiku_stub():
    """Minimal import-time stubs so stream_manager and its collaborators import."""
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


_ensure_dataiku_stub()

from owismind.agents import stream_manager  # noqa: E402


class _FakeTime(object):
    """Drop-in for the module's ``time`` binding: a controllable monotonic clock."""

    def __init__(self, now):
        self.now = now

    def monotonic(self):
        return self.now


def _seed_run(run_id, started_at=0.0, last_poll_at=None, stop_requested=False):
    """Insert a minimal live run state directly (same shape start_run registers)."""
    with stream_manager._LOCK:
        stream_manager._RUNS[run_id] = {
            "events": [],
            "done": False,
            "error": None,
            "user_id": "u-test",
            "started_at": started_at,
            "finished_at": None,
            "last_poll_at": last_poll_at,
            "stop_requested": stop_requested,
            "mode": None,
        }


def _pop_run(run_id):
    with stream_manager._LOCK:
        return stream_manager._RUNS.pop(run_id, None)


class ResolveRunDeadlineTests(unittest.TestCase):
    """resolve_run_deadline: the frozen per-mode table + the 300.0 fallback."""

    def test_known_modes_resolve_their_deadline(self):
        self.assertEqual(stream_manager.resolve_run_deadline(None), 300.0)
        self.assertEqual(stream_manager.resolve_run_deadline("smart"), 300.0)
        self.assertEqual(stream_manager.resolve_run_deadline("pro"), 600.0)
        self.assertEqual(stream_manager.resolve_run_deadline("claude"), 1200.0)

    def test_unknown_mode_falls_back_to_300(self):
        self.assertEqual(stream_manager.resolve_run_deadline("turbo"), 300.0)
        self.assertEqual(stream_manager.resolve_run_deadline(""), 300.0)
        self.assertEqual(stream_manager.resolve_run_deadline(42), 300.0)

    def test_returns_float(self):
        for mode in (None, "smart", "pro", "claude", "unknown"):
            self.assertIsInstance(stream_manager.resolve_run_deadline(mode), float)

    def test_frozen_interface_table(self):
        # T3 builds on this exact mapping - it is a frozen interface, not a tunable.
        self.assertEqual(
            stream_manager.LEGACY_MAX_RUN_SECONDS_BY_MODE,
            {None: 300.0, "smart": 300.0, "pro": 600.0, "claude": 1200.0},
        )

    def test_modeless_fallback_is_exactly_the_legacy_wall(self):
        # Anti-regression: the no-mode path keeps the historical constant verbatim.
        self.assertEqual(stream_manager.MAX_RUN_SECONDS, 300.0)
        self.assertEqual(
            stream_manager.resolve_run_deadline(None), stream_manager.MAX_RUN_SECONDS
        )

    def test_hard_ttl_covers_longest_deadline(self):
        # A live claude run must never be memory-evicted before its own deadline:
        # the hard lifetime cap has to sit ABOVE the largest per-mode deadline.
        self.assertGreater(
            stream_manager.HARD_TTL_SECONDS,
            max(stream_manager.LEGACY_MAX_RUN_SECONDS_BY_MODE.values()),
        )


class StopReasonDeadlineTests(unittest.TestCase):
    """_stop_reason applies the CALLER-provided deadline_s (monkeypatched clock)."""

    RUN = "r-stop-reason"

    def setUp(self):
        self._orig_time = stream_manager.time
        self.clock = _FakeTime(1400.0)
        stream_manager.time = self.clock
        _seed_run(self.RUN, started_at=1000.0)

    def tearDown(self):
        stream_manager.time = self._orig_time
        _pop_run(self.RUN)

    def test_none_under_the_mode_deadline(self):
        # Elapsed 400s: over the legacy 300s wall but under a 600s (pro) deadline.
        self.assertIsNone(stream_manager._stop_reason(self.RUN, 1000.0, 600.0))

    def test_deadline_reached_beyond_the_mode_deadline(self):
        # Elapsed 400s over a 300s deadline: the code is "deadline_reached", NOT
        # the legacy "timeout".
        self.assertEqual(
            stream_manager._stop_reason(self.RUN, 1000.0, 300.0), "deadline_reached"
        )

    def test_claude_run_survives_past_the_legacy_wall(self):
        # Elapsed 1100s: dead under the old single 300s wall, alive under 1200s.
        self.clock.now = 2100.0
        self.assertIsNone(stream_manager._stop_reason(self.RUN, 1000.0, 1200.0))
        # And still cut once the claude deadline itself passes.
        self.clock.now = 2201.0
        self.assertEqual(
            stream_manager._stop_reason(self.RUN, 1000.0, 1200.0), "deadline_reached"
        )

    def test_explicit_stop_wins_over_deadline(self):
        with stream_manager._LOCK:
            stream_manager._RUNS[self.RUN]["stop_requested"] = True
        self.assertEqual(
            stream_manager._stop_reason(self.RUN, 1000.0, 300.0), "stopped"
        )

    def test_abandoned_preserved_under_the_deadline(self):
        # Poll heartbeat 400s stale (> ABANDON_AFTER_SECONDS), elapsed under deadline.
        with stream_manager._LOCK:
            stream_manager._RUNS[self.RUN]["last_poll_at"] = 1000.0
        self.assertEqual(
            stream_manager._stop_reason(self.RUN, 1000.0, 1200.0), "abandoned"
        )

    def test_deadline_wins_over_abandoned(self):
        # Priority order unchanged: deadline is checked before the abandoned cut.
        with stream_manager._LOCK:
            stream_manager._RUNS[self.RUN]["last_poll_at"] = 1000.0
        self.assertEqual(
            stream_manager._stop_reason(self.RUN, 1000.0, 300.0), "deadline_reached"
        )


class StartRunModeTests(unittest.TestCase):
    """start_run stores the mode on the run state and hands the RESOLVED per-mode
    deadline to the worker thread (retro-compatible: mode is a trailing keyword)."""

    def setUp(self):
        self._orig_worker = stream_manager._worker
        self.captured = {}
        self.ran = threading.Event()
        self._run_ids = []

        def _fake_worker(run_id, project_key, agent_id, message, exchange_id,
                         started_at, user_id, parent_exchange_id, history_limit,
                         user_suffix, screen_context=None, prior_recall_enabled=False,
                         deadline_s=None):
            # Mirrors the real signature so the test pins HOW start_run passes the
            # deadline, not just that some float exists somewhere in the args.
            self.captured["run_id"] = run_id
            self.captured["deadline_s"] = deadline_s
            self.ran.set()

        stream_manager._worker = _fake_worker

    def tearDown(self):
        stream_manager._worker = self._orig_worker
        with stream_manager._LOCK:
            for run_id in self._run_ids:
                stream_manager._RUNS.pop(run_id, None)
            stream_manager._LAST_START_BY_USER.pop("u-mode", None)

    def _start(self, **kwargs):
        run_id = stream_manager.start_run(
            "P", "A", "hello", "x1", "u-mode", None, 20, "", **kwargs
        )
        self._run_ids.append(run_id)
        self.assertTrue(self.ran.wait(2.0), "worker thread never ran")
        self.ran.clear()
        return run_id

    def test_claude_mode_stored_and_deadline_1200(self):
        run_id = self._start(mode="claude")
        with stream_manager._LOCK:
            self.assertEqual(stream_manager._RUNS[run_id]["mode"], "claude")
        self.assertEqual(self.captured["run_id"], run_id)
        self.assertEqual(self.captured["deadline_s"], 1200.0)

    def test_pro_mode_deadline_600(self):
        self._start(mode="pro")
        self.assertEqual(self.captured["deadline_s"], 600.0)

    def test_unknown_mode_falls_back_to_300(self):
        run_id = self._start(mode="turbo")
        self.assertEqual(self.captured["deadline_s"], 300.0)
        with stream_manager._LOCK:
            self.assertEqual(stream_manager._RUNS[run_id]["mode"], "turbo")

    def test_modeless_call_keeps_exactly_300(self):
        # Retro-compat: a caller that never passes mode (the pre-change signature)
        # gets the exact historical wall and a None mode on the state.
        run_id = self._start()
        self.assertEqual(self.captured["deadline_s"], 300.0)
        self.assertEqual(self.captured["deadline_s"], stream_manager.MAX_RUN_SECONDS)
        with stream_manager._LOCK:
            self.assertIsNone(stream_manager._RUNS[run_id]["mode"])


class WorkerDeadlineTests(unittest.TestCase):
    """_worker applies the deadline it was handed and emits the new error codes.

    The worker runs SYNCHRONOUSLY here with every collaborator stubbed (no DSS, no
    threads): a fake streamed generator, no-op persistence, a frozen clock at
    started_at + 400s.
    """

    def setUp(self):
        self._orig = {
            "time": stream_manager.time,
            "streaming": stream_manager.streaming,
            "chat_v5": stream_manager.chat_v5,
            "usage": stream_manager.usage,
            "chat_traces": stream_manager.chat_traces,
            "artifacts_storage": stream_manager.artifacts_storage,
            "context": stream_manager.context,
        }
        self.clock = _FakeTime(1400.0)   # started_at=1000.0 -> elapsed 400s
        stream_manager.time = self.clock

        def _fake_stream(project_key, agent_id, messages):
            yield {"type": "answer_delta", "text": "part1 "}
            yield {"type": "answer_delta", "text": "part2"}

        stream_manager.streaming = types.SimpleNamespace(
            run_agent_streamed=_fake_stream
        )
        stream_manager.chat_v5 = types.SimpleNamespace(
            chain_context_for_agent=lambda uid, pid, limit: ([], []),
            save_assistant_message=lambda *a, **k: None,
        )
        stream_manager.usage = types.SimpleNamespace(record_usage=lambda *a, **k: None)
        stream_manager.chat_traces = types.SimpleNamespace(
            save_trace=lambda *a, **k: None
        )
        stream_manager.artifacts_storage = types.SimpleNamespace(
            save_artifacts=lambda *a, **k: None
        )
        stream_manager.context = types.SimpleNamespace(
            build_completion_messages=lambda history, message, suffix: [
                {"role": "user", "content": message}
            ],
        )
        self._run_ids = []

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(stream_manager, name, value)
        for run_id in self._run_ids:
            _pop_run(run_id)

    def _run_worker(self, run_id, last_poll_at=None, **kwargs):
        _seed_run(run_id, started_at=1000.0, last_poll_at=last_poll_at)
        self._run_ids.append(run_id)
        stream_manager._worker(
            run_id, "P", "A", "hello", "x1", 1000.0, "u-test", None, 20, "",
            None, False, **kwargs
        )
        with stream_manager._LOCK:
            return dict(stream_manager._RUNS[run_id])

    def test_claude_deadline_lets_a_long_run_finish(self):
        # 400s elapsed under a 1200s deadline: the run completes normally.
        state = self._run_worker("r-claude", deadline_s=1200.0)
        self.assertIsNone(state["error"])
        self.assertTrue(state["done"])
        types_seen = [e.get("type") for e in state["events"]]
        self.assertIn("run_done", types_seen)
        finals = [e for e in state["events"] if e.get("type") == "final_answer"]
        self.assertEqual(finals[0]["text"], "part1 part2")

    def test_default_deadline_cuts_at_the_legacy_wall(self):
        # Same 400s-elapsed run WITHOUT a deadline kwarg: the historical 300s wall
        # applies and the terminal code is the NEW "deadline_reached" (bare, no
        # "run_" prefix, and never the legacy "run_timeout").
        state = self._run_worker("r-legacy")
        self.assertEqual(state["error"], "deadline_reached")
        errors = [e for e in state["events"] if e.get("type") == "error"]
        self.assertEqual(errors[0]["message"], "deadline_reached")
        messages = [e.get("message") for e in state["events"]]
        self.assertNotIn("run_timeout", messages)
        self.assertNotIn("run_deadline_reached", messages)
        types_seen = [e.get("type") for e in state["events"]]
        self.assertNotIn("run_done", types_seen)

    def test_abandoned_code_unchanged(self):
        # Stale poll heartbeat (400s > 30s) under a roomy deadline: the historical
        # "run_abandoned" code is preserved verbatim.
        state = self._run_worker("r-aband", last_poll_at=1000.0, deadline_s=1200.0)
        self.assertEqual(state["error"], "run_abandoned")
        errors = [e for e in state["events"] if e.get("type") == "error"]
        self.assertEqual(errors[0]["message"], "run_abandoned")


if __name__ == "__main__":
    unittest.main()
