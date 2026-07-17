# Plugin/owismind/tests/test_streaming_workflow_control.py
"""T5: normalisation of the OWI_WORKFLOW_CONTROL machine channel in streaming.py.

The orchestrator's workflow path emits its machine result as ONE custom event
chunk; streaming must normalise it to the dedicated internal type
``workflow_control`` (consumed by the durable runner) and NEVER let it surface
as a public ``agent_event`` - run_state.append_events denylists the raw kind,
and the legacy worker drops the normalised type as defense in depth.
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
    if not hasattr(dk, "api_client"):
        dk.api_client = lambda: None
    sql_mod = sys.modules.get("dataiku.sql")
    if sql_mod is None:
        sql_mod = types.ModuleType("dataiku.sql")
        sys.modules["dataiku.sql"] = sql_mod
    for name, value in (("Constant", lambda v: v),
                        ("toSQL", lambda c, dialect=None: repr(c)),
                        ("Dialects", type("Dialects", (), {"POSTGRES": "p"}))):
        if not hasattr(sql_mod, name):
            setattr(sql_mod, name, value)
    dk.sql = sql_mod


_ensure_dataiku_stub()

from owismind.agents import streaming  # noqa: E402


class _Chunk(object):
    def __init__(self, data):
        self.data = data


class _FakeCompletion(object):
    def __init__(self, chunks):
        self._chunks = chunks

    def with_message(self, content, role):
        return self

    def execute_streamed(self):
        for c in self._chunks:
            yield c


class _FakeClient(object):
    def __init__(self, chunks):
        self._chunks = chunks

    def get_project(self, key):
        return self

    def get_llm(self, agent_id):
        return self

    def new_completion(self):
        return _FakeCompletion(self._chunks)


def _run(chunks):
    original = streaming.dataiku
    streaming.dataiku = types.SimpleNamespace(
        api_client=lambda: _FakeClient(chunks))
    try:
        return list(streaming.run_agent_streamed(
            "PK", "agent:x", [{"role": "user", "content": "hi"}]))
    finally:
        streaming.dataiku = original


class WorkflowControlNormalisationTests(unittest.TestCase):
    def test_control_chunk_normalises_to_internal_type(self):
        events = _run([
            _Chunk({"type": "event", "eventKind": "OWI_WORKFLOW_CONTROL",
                    "eventData": {"command": "plan",
                                  "payload": {"plan": {"goal": "g"}}}}),
            _Chunk({"type": "event", "eventKind": "AGENT_TURN_START",
                    "eventData": {}}),
        ])
        controls = [e for e in events if e.get("type") == "workflow_control"]
        self.assertEqual(len(controls), 1)
        self.assertEqual(controls[0]["command"], "plan")
        self.assertEqual(controls[0]["payload"], {"plan": {"goal": "g"}})
        # NEVER surfaced as a public agent_event, under any name
        for e in events:
            if e.get("type") == "agent_event":
                self.assertNotEqual(e.get("eventKind"), "OWI_WORKFLOW_CONTROL")

    def test_malformed_payload_falls_back_to_event_data(self):
        events = _run([
            _Chunk({"type": "event", "eventKind": "OWI_WORKFLOW_CONTROL",
                    "eventData": {"command": "execute", "payload": "oops"}}),
        ])
        controls = [e for e in events if e.get("type") == "workflow_control"]
        self.assertEqual(len(controls), 1)
        # non-dict payload -> the whole eventData is kept (runner classifies)
        self.assertEqual(controls[0]["payload"]["command"], "execute")

    def test_other_events_untouched(self):
        events = _run([
            _Chunk({"type": "event", "eventKind": "PLANNING",
                    "eventData": {"blockId": "b1"}}),
            _Chunk({"type": "text", "text": "hello"}),
        ])
        kinds = [e.get("type") for e in events]
        self.assertIn("agent_event", kinds)
        self.assertNotIn("workflow_control", kinds)


if __name__ == "__main__":
    unittest.main()
