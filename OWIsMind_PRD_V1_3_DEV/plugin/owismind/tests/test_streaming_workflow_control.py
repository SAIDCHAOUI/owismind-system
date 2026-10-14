# OWIsMind_PRD_V1_3_DEV/plugin/owismind/tests/test_streaming_workflow_control.py
"""The OWI_WORKFLOW_CONTROL machine channel is DROPPED by streaming.py.

The durable workflow that consumed it was removed (2026-10-14). Should the
orchestrator ever emit it, it must never surface on the public timeline.
"""
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))
sys.path.insert(0, _HERE)

import _dss_stub  # noqa: E402


_dss_stub.install()

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


class WorkflowControlDroppedTests(unittest.TestCase):
    def test_control_chunk_is_dropped(self):
        events = _run([
            _Chunk({"type": "event", "eventKind": "OWI_WORKFLOW_CONTROL",
                    "eventData": {"command": "plan",
                                  "payload": {"plan": {"goal": "g"}}}}),
            _Chunk({"type": "event", "eventKind": "AGENT_TURN_START",
                    "eventData": {}}),
        ])
        for e in events:
            self.assertNotEqual(e.get("type"), "workflow_control")
            if e.get("type") == "agent_event":
                self.assertNotEqual(e.get("eventKind"), "OWI_WORKFLOW_CONTROL")

    def test_other_events_untouched(self):
        events = _run([
            _Chunk({"type": "event", "eventKind": "PLANNING",
                    "eventData": {"blockId": "b1"}}),
            _Chunk({"type": "text", "text": "hello"}),
        ])
        kinds = [e.get("type") for e in events]
        self.assertIn("agent_event", kinds)


if __name__ == "__main__":
    unittest.main()
