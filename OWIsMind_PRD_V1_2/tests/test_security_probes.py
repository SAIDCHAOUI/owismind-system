"""Security regression tests for the Phase 0 probes (2026-07-16 audit lot A).

Locks the two hardened behaviors of probes.py:
- the probe deletion guard is FAIL-CLOSED: an unreadable live name (getter
  raising or returning None) refuses the deletion instead of proceeding;
- probe artefacts are redacted: _redact_sensitive masks the value of every
  sensitive-looking key before raw tool/agent params reach the probe results,
  the persisted probe_results.json or the printed report.

Everything runs on fakes: no dataiku import, no DSS. Reuses the fake-project
style and the sys.path bootstrap of test_factory_builders.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import probes  # noqa: E402


# --------------------------------------------------------------- delete guard

class _Handle(object):
    deleted = False

    def delete(self):
        self.deleted = True


class TestDeleteProbeObjectFailClosed(unittest.TestCase):
    def test_getter_raising_refuses_deletion(self):
        handle = _Handle()

        def getter():
            raise RuntimeError("re-read exploded")

        with self.assertRaises(RuntimeError) as ctx:
            probes._delete_probe_object(handle, "zz_factory_probe", getter)
        self.assertIn("refusing to delete", str(ctx.exception))
        self.assertIn("zz_", str(ctx.exception))
        self.assertFalse(handle.deleted)

    def test_getter_returning_none_refuses_deletion(self):
        handle = _Handle()
        with self.assertRaises(RuntimeError) as ctx:
            probes._delete_probe_object(handle, "zz_factory_probe", lambda: None)
        self.assertIn("could not re-read the live name", str(ctx.exception))
        self.assertFalse(handle.deleted)

    def test_matching_name_deletes(self):
        handle = _Handle()
        probes._delete_probe_object(handle, "zz_factory_probe",
                                    lambda: "zz_factory_probe")
        self.assertTrue(handle.deleted)

    def test_different_name_refuses_deletion(self):
        handle = _Handle()
        with self.assertRaises(RuntimeError):
            probes._delete_probe_object(handle, "zz_factory_probe",
                                        lambda: "REAL_PRODUCTION_AGENT")
        self.assertFalse(handle.deleted)


# ------------------------------------------------------------------ redaction

class TestRedactSensitive(unittest.TestCase):
    def test_masks_sensitive_keys_at_every_level_and_keeps_the_rest(self):
        data = {
            "Token": "t",
            "PASSWORD": "p",
            "client_secret": "s",
            "credentials": {"user": "u", "pass": "p"},
            "apiKey": "k1",
            "api_key": "k2",
            "private_key": "pk",
            "Authorization": "Bearer abc",
            "model_id": "AHUh9hb",
            "nested": {
                "authorization_header": "h",
                "keep": 2,
                "items": [{"password": "deep", "label": "ok"}, "plain"],
            },
        }
        out = probes._redact_sensitive(data)
        for key in ("Token", "PASSWORD", "client_secret", "credentials",
                    "apiKey", "api_key", "private_key", "Authorization"):
            self.assertEqual(out[key], "[REDACTED]", key)
        self.assertEqual(out["model_id"], "AHUh9hb")
        self.assertEqual(out["nested"]["authorization_header"], "[REDACTED]")
        self.assertEqual(out["nested"]["keep"], 2)
        self.assertEqual(out["nested"]["items"][0]["password"], "[REDACTED]")
        self.assertEqual(out["nested"]["items"][0]["label"], "ok")
        self.assertEqual(out["nested"]["items"][1], "plain")

    def test_returns_a_copy_and_passes_scalars_through(self):
        data = {"token": "t", "nested": {"secret": "s"}}
        probes._redact_sensitive(data)
        # the input structure is never mutated (deep-copy semantics).
        self.assertEqual(data["token"], "t")
        self.assertEqual(data["nested"]["secret"], "s")
        self.assertIsNone(probes._redact_sensitive(None))
        self.assertEqual(probes._redact_sensitive("plain"), "plain")
        self.assertEqual(probes._redact_sensitive(3), 3)


# --------------------------------------- redaction applied inside the probes

# A python-source string long enough (> 300 chars) to be detected as a code leaf.
LONG_CODE = ("import os\n"
             "from dataiku.llm.python import BaseLLM\n"
             "def process(self, query, settings, trace):\n"
             "    return {'text': 'hello'}\n" + "# padding line\n" * 30)


class _Settings(object):
    def __init__(self, raw):
        self._raw = raw

    def get_raw(self):
        return self._raw


class _Handle2(object):
    def __init__(self, raw):
        self._raw = raw

    def get_settings(self):
        return _Settings(self._raw)


class _NamedItem(object):
    def __init__(self, item_id, name, item_type=None):
        self.id = item_id
        self.name = name
        self.type = item_type


class _EmptyLibrary(object):
    def get_file(self, path):
        return None


class _LeakyReadProbeProject(object):
    """Read-probe project whose template tool params and agent env settings
    carry credential-looking values that must never reach the results."""

    project_key = "OWISMIND_TEST"

    def __init__(self):
        self._agent_raw = {
            "activeVersion": "v1",
            "name": "OWIsMind_orchestrator",
            "versions": [{
                "versionId": "v1",
                "pythonAgentSettings": {"code": LONG_CODE,
                                        "codeEnvName": "py311",
                                        "envSecretToken": "AGENT_ENV_SECRET"},
            }],
        }

    def get_library(self):
        return _EmptyLibrary()

    def list_agents(self):
        return [{"id": "038G7mlF", "name": "OWIsMind_orchestrator"}]

    def get_agent(self, agent_id):
        return _Handle2(self._agent_raw)

    def list_agent_tools(self):
        return [_NamedItem("v4oqA6R", "revenue_semantic_query", "semantic_model_query")]

    def get_agent_tool(self, tool_id):
        params = {"model_id": "AHUh9hb",
                  "api_key": "TOOL_SUPERSECRET",
                  "nested": {"authToken": "TOOL_NESTED_SECRET",
                             "keep": "ok"}}
        settings = _Settings({"params": params, "description": "template"})
        settings.params = params
        return _ToolHandle(settings)

    def list_semantic_models(self):
        return [_NamedItem("AHUh9hb", "Drive_Revenues_Semantic_Model")]


class _ToolHandle(object):
    def __init__(self, settings):
        self._settings = settings

    def get_settings(self):
        return self._settings


class TestReadProbesRedaction(unittest.TestCase):
    def test_discovery_params_are_redacted_in_results(self):
        results = probes.run_read_probes(_LeakyReadProbeProject())
        params = results["suggested_discovery"]["params_template"]
        self.assertEqual(params["api_key"], "[REDACTED]")
        self.assertEqual(params["nested"]["authToken"], "[REDACTED]")
        # non-sensitive params survive intact (the clone strategy needs them).
        self.assertEqual(params["model_id"], "AHUh9hb")
        self.assertEqual(params["nested"]["keep"], "ok")

    def test_env_candidates_and_hints_are_redacted_in_results(self):
        results = probes.run_read_probes(_LeakyReadProbeProject())
        by_path = {c["path"]: c["value"] for c in results["candidate_env_keys"]}
        self.assertEqual(by_path["envSecretToken"], "[REDACTED]")
        self.assertEqual(by_path["codeEnvName"], "py311")
        env_template = results["suggested_schema_hints"]["env_template"]
        self.assertEqual(env_template["envSecretToken"], "[REDACTED]")
        self.assertEqual(env_template["codeEnvName"], "py311")

    def test_report_never_contains_the_raw_secrets(self):
        results = probes.run_read_probes(_LeakyReadProbeProject())
        report = probes.format_probe_report(results)
        self.assertNotIn("TOOL_SUPERSECRET", report)
        self.assertNotIn("TOOL_NESTED_SECRET", report)
        self.assertNotIn("AGENT_ENV_SECRET", report)
        self.assertIn("[REDACTED]", report)

    def test_report_redacts_even_unredacted_results(self):
        # Defense in depth: format_probe_report redacts its own copy, so a
        # results dict built elsewhere cannot leak through the report either.
        report = probes.format_probe_report({
            "project_key": "P",
            "suggested_discovery": {"type": "semantic_model_query",
                                    "params_template": {"api_key": "RAW_LEAK"}},
        })
        self.assertNotIn("RAW_LEAK", report)
        self.assertIn("[REDACTED]", report)


if __name__ == "__main__":
    unittest.main()
