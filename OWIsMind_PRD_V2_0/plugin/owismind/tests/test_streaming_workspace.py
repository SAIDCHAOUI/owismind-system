"""WORKSPACE events end to end in the backend: streaming.py -> stream_manager worker.

  - run_agent_streamed: the fixture's raw orchestrator chunks yield EXACTLY the
    fixture's expected workspace events, in order; a WORKSPACE chunk never becomes a
    timeline agent_event; an invalid op is dropped; a missing ts is stamped by the
    backend chronometer;
  - _worker: workspace events are relayed live AND reduced; at the end of the run the
    reduced state is persisted ONCE, equal to the fixture's reduced ``final`` (done,
    stopped, orphan binding against the captured sql_ids); a run without workspace op
    writes nothing; the per-run cap (80) bounds what is reduced and relayed.
Fully stubbed (fake LLM Mesh client, no-op persistence), no DSS runtime.
"""
import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402

_dss_stub.install()

from owismind.agents import stream_manager, streaming  # noqa: E402

FIXTURES = os.path.join(_HERE, "..", "contracts", "fixtures")


def _load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return json.load(f)


class _Chunk(object):
    def __init__(self, data):
        self.data = data


def _fake_dataiku(chunks, on_end=None):
    """A ``dataiku`` stand-in whose agent streams ``chunks`` (then calls on_end)."""

    class _Completion(object):
        def with_message(self, content, role):
            return self

        def execute_streamed(self):
            for data in chunks:
                yield _Chunk(data)
            if on_end is not None:
                for data in on_end():
                    yield _Chunk(data)

    project = types.SimpleNamespace(
        get_llm=lambda agent_id: types.SimpleNamespace(new_completion=_Completion))
    client = types.SimpleNamespace(get_project=lambda key: project)
    return types.SimpleNamespace(api_client=lambda: client)


class _StreamingBase(unittest.TestCase):
    def setUp(self):
        self._orig_dataiku = streaming.dataiku

    def tearDown(self):
        streaming.dataiku = self._orig_dataiku

    def _events(self, chunks):
        streaming.dataiku = _fake_dataiku(chunks)
        return list(streaming.run_agent_streamed("P", "A", [{"role": "user", "content": "q"}]))


class StreamingTests(_StreamingBase):
    def test_fixture_runs_yield_expected_workspace_events(self):
        for name in ("workspace_run_multi_facet.json", "workspace_run_stopped.json",
                     "workspace_run_orphan_widget.json"):
            fx = _load(name)
            with self.subTest(fixture=name):
                events = self._events(fx["raw_chunks"])
                ws = [e for e in events if e["type"] == "workspace"]
                self.assertEqual(ws, fx["expected_events"])
                # No timeline step for WORKSPACE chunks.
                kinds = [e.get("eventKind") for e in events if e["type"] == "agent_event"]
                self.assertNotIn("WORKSPACE", kinds)
                # The relayed SQL (AGENT_DONE) still flows with its sql_id.
                sql_ids = [e.get("sqlId") for e in events if e["type"] == "generated_sql"]
                self.assertEqual(sql_ids, fx["known_sql_ids"])

    def test_invalid_op_dropped_and_ts_stamped(self):
        chunks = [
            {"type": "event", "eventKind": "WORKSPACE",
             "eventData": {"v": 1, "op": "widget.add", "seq": 1, "id": "w1", "kind": "chart",
                           "title": "no sql id", "chart": {"type": "bar", "x": "a", "y": ["b"]}}},
            {"type": "event", "eventKind": "WORKSPACE",
             "eventData": {"v": 1, "op": "plan.step", "seq": 2, "step_id": "p1",
                           "status": "done"}},
        ]
        with self.assertLogs("owismind.agents.streaming", level="WARNING"):
            events = self._events(chunks)
        ws = [e for e in events if e["type"] == "workspace"]
        self.assertEqual(len(ws), 1)
        self.assertEqual(ws[0]["op"], "plan.step")
        self.assertIsInstance(ws[0]["ts"], float)
        self.assertGreaterEqual(ws[0]["ts"], 0)


def _seed_run(run_id, session_id="sess-1"):
    with stream_manager._LOCK:
        stream_manager._RUNS[run_id] = {
            "events": [], "done": False, "error": None, "user_id": "u-test",
            "started_at": 0.0, "finished_at": None, "last_poll_at": None,
            "stop_requested": False, "mode": None, "session_id": session_id,
        }


class _WorkerBase(_StreamingBase):
    def setUp(self):
        super().setUp()
        self.saved = []
        self.sql_saved = []
        self._orig = {
            "chat_v5": stream_manager.chat_v5,
            "usage": stream_manager.usage,
            "chat_traces": stream_manager.chat_traces,
            "artifacts_storage": stream_manager.artifacts_storage,
            "workspaces_storage": stream_manager.workspaces_storage,
            "context": stream_manager.context,
            "time": stream_manager.time,
        }
        stream_manager.time = types.SimpleNamespace(monotonic=lambda: 1.0)
        stream_manager.chat_v5 = types.SimpleNamespace(
            chain_context_for_agent=lambda uid, pid, limit: ([], []),
            save_assistant_message=lambda ex, answer, sql, usage=None:
                self.sql_saved.append(sql),
        )
        stream_manager.usage = types.SimpleNamespace(record_usage=lambda *a, **k: None)
        stream_manager.chat_traces = types.SimpleNamespace(save_trace=lambda *a, **k: None)
        stream_manager.artifacts_storage = types.SimpleNamespace(
            save_artifacts=lambda *a, **k: None)
        stream_manager.workspaces_storage = types.SimpleNamespace(
            save_workspace=lambda ex, uid, sid, state: self.saved.append((ex, uid, sid, state)))
        stream_manager.context = types.SimpleNamespace(
            build_completion_messages=lambda history, message, suffix: [
                {"role": "user", "content": message}])
        self._run_ids = []

    def tearDown(self):
        for name, value in self._orig.items():
            setattr(stream_manager, name, value)
        with stream_manager._LOCK:
            for run_id in self._run_ids:
                stream_manager._RUNS.pop(run_id, None)
        super().tearDown()

    def _run(self, run_id, chunks, exchange_id, on_end=None):
        _seed_run(run_id)
        self._run_ids.append(run_id)
        streaming.dataiku = _fake_dataiku(chunks, on_end)
        stream_manager._worker(run_id, "P", "A", "hello", exchange_id, 0.0, "u-test",
                               None, 20, "", None, False)
        with stream_manager._LOCK:
            return list(stream_manager._RUNS[run_id]["events"])


class WorkerWorkspaceTests(_WorkerBase):
    def test_multi_facet_relayed_live_and_persisted_once(self):
        fx = _load("workspace_run_multi_facet.json")
        live = self._run("r-multi", fx["raw_chunks"], fx["exchange_id"])
        relayed = [e for e in live if e["type"] == "workspace"]
        self.assertEqual(relayed, fx["expected_events"])
        self.assertEqual(len(self.saved), 1)
        exchange_id, user_id, session_id, state = self.saved[0]
        self.assertEqual((exchange_id, user_id, session_id),
                         (fx["exchange_id"], "u-test", "sess-1"))
        self.assertEqual(state, _load(fx["expected_reduced"])["final"])
        self.assertEqual(live[-1], {"type": "run_done", "status": "success"})

    def test_orphan_widgets_bound_against_captured_sql(self):
        fx = _load("workspace_run_orphan_widget.json")
        self._run("r-orphan", fx["raw_chunks"], fx["exchange_id"])
        self.assertEqual(self.saved[0][3], _load(fx["expected_reduced"])["final"])

    def test_user_stop_persists_partial_workspace_as_stopped(self):
        fx = _load("workspace_run_stopped.json")

        def _stop_then_more():
            with stream_manager._LOCK:
                stream_manager._RUNS["r-stop"]["stop_requested"] = True
            return [{"type": "text", "text": " (never consumed)"}]

        live = self._run("r-stop", fx["raw_chunks"], fx["exchange_id"], on_end=_stop_then_more)
        self.assertEqual(self.saved[0][3], _load(fx["expected_reduced"])["final"])
        self.assertEqual(live[-1]["type"], "stopped")

    def test_agent_failure_persists_workspace_as_error(self):
        fx = _load("workspace_run_stopped.json")

        def _boom():
            raise RuntimeError("mesh down")

        live = self._run("r-err", fx["raw_chunks"], fx["exchange_id"], on_end=_boom)
        self.assertEqual(live[-1], {"type": "error", "message": "agent_unavailable"})
        self.assertEqual(self.saved[0][3]["status"], "error")

    def test_run_without_workspace_writes_nothing(self):
        self._run("r-none", [{"type": "text", "text": "hi"}], "ex-none")
        self.assertEqual(self.saved, [])

    def test_workspace_event_cap(self):
        chunks = [{"type": "event", "eventKind": "WORKSPACE",
                   "eventData": {"v": 1, "op": "note.add", "seq": i, "id": "n%d" % i,
                                 "kind": "note", "title": "t"}}
                  for i in range(1, 101)]
        with self.assertLogs("owismind.agents.stream_manager", level="WARNING"):
            live = self._run("r-cap", chunks, "ex-cap")
        relayed = [e for e in live if e["type"] == "workspace"]
        self.assertEqual(len(relayed), stream_manager.MAX_WORKSPACE_EVENTS)
        state = self.saved[0][3]
        self.assertEqual(state["last_seq"], stream_manager.MAX_WORKSPACE_EVENTS)
        self.assertEqual(len(state["notes"]), 30)


class LiveResultRelayTests(_WorkerBase):
    """V2.0: captured rows reach /chat/poll live (sqlId + result), bounded."""

    def _sql_events(self, live):
        return [e for e in live if e["type"] == "generated_sql"]

    def test_rows_relayed_live_with_sql_id(self):
        fx = _load("workspace_run_multi_facet.json")
        live = self._run("r-live", fx["raw_chunks"], fx["exchange_id"])
        events = self._sql_events(live)
        self.assertEqual([e["sqlId"] for e in events], ["s1q1", "s1q2", "s2q1"])
        self.assertEqual(events[0]["result"]["rows"][0], ["Nord", 1200])
        # Persistence still gets the full item.
        self.assertEqual(self.sql_saved[0][0]["result"]["columns"], ["region", "revenue"])

    def _agent_done(self, n, cells):
        rows = [["x" * cells] for _ in range(50)]
        return {"type": "event", "eventKind": "AGENT_DONE", "eventData": {
            "generatedSql": [{"sql": "SELECT %d" % n, "success": True, "row_count": 50,
                              "sql_id": "s%dq1" % n,
                              "result": {"columns": ["c"], "rows": rows,
                                         "truncated": False}}]}}

    def test_oversize_result_stripped_from_live_copy_only(self):
        live = self._run("r-big", [self._agent_done(1, 2000)], "ex-big")
        event = self._sql_events(live)[0]
        self.assertEqual(event["sqlId"], "s1q1")
        self.assertNotIn("result", event)
        self.assertIn("result", self.sql_saved[0][0])

    def test_per_run_live_budget(self):
        # ~50 KB each: under the per-event cap, the run budget (400 KB) stops at 7.
        chunks = [self._agent_done(i, 1000) for i in range(1, 11)]
        live = self._run("r-budget", chunks, "ex-budget")
        with_rows = [e for e in self._sql_events(live) if "result" in e]
        self.assertEqual(len(with_rows), 7)
        self.assertEqual(len(self.sql_saved[0]), 10)


class SpanSqlIdTests(unittest.TestCase):
    def test_orchestrator_span_sql_id_captured(self):
        trace = {"children": [
            {"name": "semantic-model-query",
             "outputs": {"sql": "SELECT a", "sql_id": "s2lk1", "columns": ["a"],
                         "rows": [[1]]}},
            {"name": "semantic-model-query",
             "outputs": {"sql": "SELECT b", "sql_id": "latest"}},
            {"name": "semantic-model-query", "outputs": {"sql": "SELECT c"}}]}
        items = streaming._find_generated_sql(trace)
        self.assertEqual([it.get("sql_id") for it in items], ["s2lk1", None, None])


class StartRunSessionTests(unittest.TestCase):
    def test_session_id_kept_on_run_state_not_in_worker_args(self):
        orig = stream_manager._worker
        seen = {}

        def _fake_worker(*args):
            seen["argc"] = len(args)

        stream_manager._worker = _fake_worker
        try:
            run_id = stream_manager.start_run("P", "A", "m", "ex", "u-sess", None, 20, "",
                                              session_id="sess-9")
            with stream_manager._LOCK:
                self.assertEqual(stream_manager._RUNS[run_id]["session_id"], "sess-9")
                stream_manager._RUNS.pop(run_id, None)
                stream_manager._LAST_START_BY_USER.pop("u-sess", None)
        finally:
            stream_manager._worker = orig


if __name__ == "__main__":
    unittest.main()
