"""Security lot E tests: strict hub settings overlay + doctor evidence withholding.

Locks two audit findings (GPT-5.6 Sol + internal, 2026-07-16):
- hub.get_settings must only overlay keys declared in DEFAULT_SETTINGS, so an
  unknown key planted in /owismind_hub/factory_settings.json can never ride
  through (and get republished by the console's /api/state).
- doctor.format_proposal_markdown must withhold the issues' verbatim
  conversation evidence by default, because the proposal markdown is persisted
  to the project library (readable by every project reader); include_evidence
  stays an explicit opt-in for the notebook's ephemeral output only.

DSS-free: everything runs on fakes.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests -v
"""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import doctor, hub  # noqa: E402


class _MemHubLibrary(object):
    """Dict-backed fake of the DSS project library (read + write + folders)."""

    def __init__(self, files=None):
        self.files = dict(files or {})

    class _File(object):
        def __init__(self, lib, path):
            self.lib, self.path = lib, path

        def read(self):
            return self.lib.files[self.path]

        def write(self, content):
            self.lib.files[self.path] = content

    class _Folder(object):
        def __init__(self, lib, path):
            self.lib, self.path = lib, path

        def add_folder(self, name):
            return _MemHubLibrary._Folder(self.lib, self.path.rstrip("/") + "/" + name)

        def add_file(self, name):
            path = self.path.rstrip("/") + "/" + name
            self.lib.files[path] = ""
            return _MemHubLibrary._File(self.lib, path)

    @property
    def root(self):
        return self._Folder(self, "")

    def get_file(self, path):
        return self._File(self, path) if path in self.files else None

    def get_folder(self, path):
        prefix = path.rstrip("/") + "/"
        if any(p.startswith(prefix) for p in self.files):
            return self._Folder(self, path)
        return None


class _MemHubProject(object):
    def __init__(self, files=None):
        self.library = _MemHubLibrary(files)

    def get_library(self):
        return self.library


class TestGetSettingsStrictOverlay(unittest.TestCase):
    def test_unknown_key_is_ignored(self):
        project = _MemHubProject({hub.SETTINGS_PATH: json.dumps({
            "sql_connection": "SQL_other",
            "rogue_key": "INJECTED",
        })})
        settings = hub.get_settings(project)
        self.assertNotIn("rogue_key", settings)
        # Known keys still overlay, the rest keep their defaults.
        self.assertEqual(settings["sql_connection"], "SQL_other")
        self.assertEqual(settings["orchestrator_agent_id"],
                         hub.DEFAULT_SETTINGS["orchestrator_agent_id"])
        self.assertEqual(set(settings.keys()), set(hub.DEFAULT_SETTINGS.keys()))

    def test_overlay_of_known_keys_is_kept(self):
        project = _MemHubProject({hub.SETTINGS_PATH: json.dumps({
            "code_env_311": "py311_agents",
            "llm_sonnet": "openai:CONN:model-x",
        })})
        settings = hub.get_settings(project)
        self.assertEqual(settings["code_env_311"], "py311_agents")
        self.assertEqual(settings["llm_sonnet"], "openai:CONN:model-x")

    def test_missing_file_returns_pure_defaults(self):
        settings = hub.get_settings(_MemHubProject())
        self.assertEqual(settings, hub.DEFAULT_SETTINGS)

    def test_defaults_are_never_mutated(self):
        project = _MemHubProject({hub.SETTINGS_PATH: json.dumps({
            "sql_connection": "SQL_other",
        })})
        hub.get_settings(project)
        self.assertEqual(hub.DEFAULT_SETTINGS["sql_connection"], "SQL_owi")


class TestProposalMarkdownEvidenceWithheld(unittest.TestCase):
    RESULT = {
        "diagnosis": "DIAG-TEXT",
        "issues": [
            {"title": "ISSUE-T1", "severity": "high",
             "evidence": "user: how much did ACME pay; agent: 9.2M EUR"},
            {"title": "ISSUE-T2", "severity": "low",
             "evidence": "user: Orange Belgium churn; agent: 132 tickets"},
        ],
        "revised_prompt": "REVISED-PROMPT-BODY",
        "change_summary": ["CHANGE-1"],
        "risks": ["RISK-1"],
        "test_questions": ["QUESTION-1"],
    }

    def test_default_markdown_contains_no_evidence_text(self):
        markdown = doctor.format_proposal_markdown(self.RESULT, "Orchestrator")
        for leak in ("ACME", "9.2M EUR", "Orange Belgium", "132 tickets"):
            self.assertNotIn(leak, markdown)
        self.assertIn("evidence withheld", markdown)
        # The rest of the proposal is intact.
        for token in ("DIAG-TEXT", "ISSUE-T1", "ISSUE-T2", "REVISED-PROMPT-BODY",
                      "CHANGE-1", "RISK-1", "QUESTION-1", "Orchestrator"):
            self.assertIn(token, markdown)

    def test_include_evidence_true_keeps_evidence(self):
        markdown = doctor.format_proposal_markdown(self.RESULT, "Orchestrator",
                                                   include_evidence=True)
        self.assertIn("how much did ACME pay", markdown)
        self.assertIn("Orange Belgium churn", markdown)
        self.assertNotIn("evidence withheld", markdown)

    def test_empty_evidence_gets_no_placeholder(self):
        result = dict(self.RESULT)
        result["issues"] = [{"title": "ISSUE-T", "severity": "?", "evidence": ""}]
        markdown = doctor.format_proposal_markdown(result, "Orchestrator")
        self.assertNotIn("evidence withheld", markdown)
        self.assertIn("ISSUE-T", markdown)


if __name__ == "__main__":
    unittest.main()
