"""DSS-free unit tests for owismind_factory.doctor (the prompt doctor engine).

The pure prompt/schema/format helpers are tested directly. collect_interactions
is tested against a stubbed ``dataiku`` module (same technique as
test_attribute_lookup.py), so the column-role heuristics and the field/row caps
are exercised without a DSS instance.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests -v
"""

import os
import sys
import types
import unittest

_PKG_PARENT = os.path.abspath(os.path.join(
    os.path.dirname(__file__), "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)


def _install_dataiku_stub():
    mod = sys.modules.get("dataiku")
    if mod is None:
        mod = types.ModuleType("dataiku")
        sys.modules["dataiku"] = mod
    # Dataset is replaced per-test via _use_dataset; default raises so a test that
    # forgot to set it fails loudly instead of silently returning [].
    if not hasattr(mod, "Dataset"):
        def _unset(*_a, **_k):
            raise RuntimeError("dataiku.Dataset not configured for this test")
        mod.Dataset = _unset
    return mod


_install_dataiku_stub()

from owismind_factory import doctor   # noqa: E402


class _FakeDataset(object):
    def __init__(self, schema, rows):
        self._schema = schema
        self._rows = rows

    def read_schema(self):
        return [{"name": name} for name in self._schema]

    def iter_rows(self):
        for row in self._rows:
            yield dict(row)


def _use_dataset(schema, rows):
    sys.modules["dataiku"].Dataset = lambda name: _FakeDataset(schema, rows)


class TestBuildDoctorPrompt(unittest.TestCase):
    def test_includes_persona_complaint_interactions_and_contract_warning(self):
        interactions = [{"input": "how much revenue in 2024", "answer": "I cannot say"}]
        prompt = doctor.build_doctor_prompt(
            "PERSONA-MARKER-123", interactions,
            complaint="it refuses valid questions")
        self.assertIn("PERSONA-MARKER-123", prompt)
        self.assertIn("it refuses valid questions", prompt)
        self.assertIn("how much revenue in 2024", prompt)
        # The frozen-contract guardrail must be present.
        self.assertIn("honesty firewall", prompt)
        self.assertIn("frozen", prompt.lower())
        # It must ask for a full revised prompt + regression questions.
        self.assertIn("REVISED_PROMPT", prompt)
        self.assertIn("TEST_QUESTIONS", prompt)

    def test_handles_no_interactions_and_no_complaint(self):
        prompt = doctor.build_doctor_prompt("PERSONA-ONLY", [])
        self.assertIn("PERSONA-ONLY", prompt)
        self.assertIsInstance(prompt, str)


class TestSchema(unittest.TestCase):
    def test_schema_has_all_top_level_keys(self):
        props = doctor.DOCTOR_OUTPUT_SCHEMA["properties"]
        for key in ("diagnosis", "issues", "revised_prompt",
                    "change_summary", "risks", "test_questions"):
            self.assertIn(key, props)
        self.assertEqual(sorted(doctor.DOCTOR_OUTPUT_SCHEMA["required"]),
                         sorted(props.keys()))

    def test_issue_item_shape(self):
        item = doctor.DOCTOR_OUTPUT_SCHEMA["properties"]["issues"]["items"]["properties"]
        for key in ("title", "evidence", "severity"):
            self.assertIn(key, item)


class TestFormatProposal(unittest.TestCase):
    RESULT = {
        "diagnosis": "DIAG-TEXT",
        "issues": [{"title": "ISSUE-T", "evidence": "ISSUE-E", "severity": "high"}],
        "revised_prompt": "REVISED-PROMPT-BODY",
        "change_summary": ["CHANGE-1"],
        "risks": ["RISK-1"],
        "test_questions": ["QUESTION-1"],
    }

    def test_all_sections_rendered(self):
        # include_evidence=True is the ephemeral notebook-display path; the
        # persisted default withholds evidence (test_security_hub_doctor.py).
        markdown = doctor.format_proposal_markdown(self.RESULT, "Orchestrator",
                                                   include_evidence=True)
        for token in ("DIAG-TEXT", "ISSUE-T", "ISSUE-E", "REVISED-PROMPT-BODY",
                      "CHANGE-1", "RISK-1", "QUESTION-1", "Orchestrator"):
            self.assertIn(token, markdown)

    def test_error_result_is_readable(self):
        markdown = doctor.format_proposal_markdown({"error": "boom"}, "Orchestrator")
        self.assertIn("boom", markdown)
        self.assertIn("could not produce", markdown)


class TestClassifyColumns(unittest.TestCase):
    def test_maps_common_column_names(self):
        roles = doctor.classify_columns(
            ["user_query", "agent_output", "tool_calls", "event_ts"])
        self.assertEqual(roles.get("input"), "user_query")
        self.assertEqual(roles.get("answer"), "agent_output")
        self.assertEqual(roles.get("tools"), "tool_calls")
        self.assertEqual(roles.get("ts"), "event_ts")


class TestCollectInteractions(unittest.TestCase):
    def test_role_heuristics_map_columns(self):
        _use_dataset(
            ["user_query", "agent_output", "tool_calls", "ts"],
            [{"user_query": "q1", "agent_output": "a1", "tool_calls": "t1", "ts": "2026"},
             {"user_query": "q2", "agent_output": "a2", "tool_calls": "t2", "ts": "2026"}])
        out = doctor.collect_interactions(None, "logs", limit=10)
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["input"], "q1")
        self.assertEqual(out[0]["answer"], "a1")
        self.assertEqual(out[0]["tools"], "t1")
        self.assertEqual(out[0]["ts"], "2026")
        self.assertIn("raw", out[0])

    def test_row_limit_enforced(self):
        rows = [{"input": "x%d" % i} for i in range(50)]
        _use_dataset(["input"], rows)
        out = doctor.collect_interactions(None, "logs", limit=5)
        self.assertEqual(len(out), 5)

    def test_field_capped(self):
        big = "z" * 5000
        _use_dataset(["input"], [{"input": big}])
        out = doctor.collect_interactions(None, "logs", limit=1)
        capped = out[0]["raw"]["input"]
        self.assertLess(len(capped), 5000)
        self.assertLessEqual(len(capped), doctor.MAX_FIELD_CHARS + 32)

    def test_failure_returns_empty(self):
        def _boom(name):
            raise RuntimeError("no such dataset")
        sys.modules["dataiku"].Dataset = _boom
        self.assertEqual(doctor.collect_interactions(None, "logs"), [])


if __name__ == "__main__":
    unittest.main()
