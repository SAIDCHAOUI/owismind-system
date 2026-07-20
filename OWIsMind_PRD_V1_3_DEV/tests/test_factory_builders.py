"""Builder coverage tests for the least-covered factory modules (2026-07-12).

Locks the CURRENT behavior (not a desired one) of the four builders that the
hardening suite barely touches: the Phase 0 probes (read + write round-trip +
report), the semantic model seeder, the semantic-query tool cloner and the Code
Agent generator/creator. Everything runs on fakes: no dataiku import, no DSS.

Reuses the fake-project style and the sys.path bootstrap of
test_factory_hardening.py.
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..",
                                "project-library", "python"))

from owismind_factory import agent_builder, probes, semantic_builder, tool_builder  # noqa: E402
from owismind_factory import hub as hub_module  # noqa: E402
from owismind_factory.flow_builder import ExistenceCheckError  # noqa: E402
from owismind_factory.fctx import FactoryContext, DONE, FAILED, MANUAL, PLANNED, SKIPPED  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def make_spec(**overrides):
    kwargs = dict(domain="satisfaction", base_dataset="CX_Surveys",
                  label_fr="Satisfaction", label_en="Customer satisfaction")
    kwargs.update(overrides)
    return DomainSpec(**kwargs)


def statuses(ctx):
    return {a["step"]: a["status"] for a in ctx.actions}


def details(ctx):
    return " ".join(a["detail"] for a in ctx.actions)


# A python-source string long enough (> 300 chars) to be detected as a code leaf.
LONG_CODE = ("import os\n"
             "from dataiku.llm.python import BaseLLM\n"
             "def process(self, query, settings, trace):\n"
             "    return {'text': 'hello'}\n" + "# padding line\n" * 30)


# ------------------------------------------------------------- read-probe fakes

class _Settings(object):
    def __init__(self, raw):
        self._raw = raw

    def get_raw(self):
        return self._raw


class _Handle(object):
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


class _ReadProbeProject(object):
    """Happy read-probe path: orchestrator with a discoverable code key + a
    template tool whose type/params the tool discovery can clone."""

    project_key = "OWISMIND_TEST"

    def __init__(self, tools_have_template=True):
        self._tools_have_template = tools_have_template
        self._agent_raw = {
            "activeVersion": "v1",
            "name": "OWIsMind_orchestrator",
            "versions": [{
                "versionId": "v1",
                "pythonAgentSettings": {"code": LONG_CODE, "codeEnvName": "py311"},
            }],
        }

    def get_library(self):
        return _EmptyLibrary()

    def list_agents(self):
        return [{"id": "038G7mlF", "name": "OWIsMind_orchestrator"}]

    def get_agent(self, agent_id):
        return _Handle(self._agent_raw)

    def list_agent_tools(self):
        if self._tools_have_template:
            return [_NamedItem("v4oqA6R", "revenue_semantic_query", "semantic_model_query")]
        return []

    def get_agent_tool(self, tool_id):
        settings = _Settings({"params": {"model_id": "AHUh9hb"}, "description": "template"})
        settings.params = {"model_id": "AHUh9hb"}
        return _ToolHandle(settings)

    def list_semantic_models(self):
        return [_NamedItem("AHUh9hb", "Drive_Revenues_Semantic_Model")]


class _ToolHandle(object):
    def __init__(self, settings):
        self._settings = settings

    def get_settings(self):
        return self._settings


class TestReadProbes(unittest.TestCase):
    def test_happy_path_detects_methods_layout_and_hints(self):
        results = probes.run_read_probes(_ReadProbeProject())
        # client method detection is recorded for every probed method.
        self.assertTrue(results["client_methods"]["list_agents"])
        self.assertIn("create_agent", results["client_methods"])
        # agent raw layout probing.
        self.assertEqual(results["agent_versions_count"], 1)
        self.assertTrue(results["python_agent_settings_present"])
        # layout is the types-only view of the pythonAgentSettings dict itself.
        self.assertIn("code", results["python_agent_settings_layout"])
        self.assertTrue(results["candidate_code_keys"])
        # a top-level code key becomes a schema hint (unconfirmed).
        hints = results["suggested_schema_hints"]
        self.assertEqual(hints["internal_key"], "pythonAgentSettings")
        self.assertEqual(hints["code_key"], "code")
        self.assertEqual(hints["confirmed"], False)
        self.assertIn("codeEnvName", hints["env_template"])
        # tool discovery suggestion from the live template tool.
        self.assertIsNotNone(results["suggested_discovery"])
        self.assertEqual(results["suggested_discovery"]["type"], "semantic_model_query")
        # code_env_311 empty -> warning; template tool found -> no missing warning.
        self.assertTrue(any("code_env_311" in w for w in results["warnings"]))
        self.assertFalse(any("template tool" in w for w in results["warnings"]))

    def test_missing_template_tool_warns_and_no_discovery(self):
        results = probes.run_read_probes(_ReadProbeProject(tools_have_template=False))
        self.assertIsNone(results["suggested_discovery"])
        self.assertTrue(any("template tool" in w for w in results["warnings"]))

    def test_format_report_survives_partial_results(self):
        # Only a project key: every optional section must render, not crash.
        text = probes.format_probe_report({"project_key": "P"})
        self.assertIn("Phase 0 probe report", text)
        self.assertIsInstance(text, str)
        # A fuller dict with a discovery block also renders.
        full = probes.format_probe_report(probes.run_read_probes(_ReadProbeProject()))
        self.assertIn("Semantic Model Query tool discovery", full)


# ------------------------------------------------------------ write-probe fakes

class _WriteAgentSettings(object):
    def __init__(self, name):
        self._raw = {"name": name, "versions": [{"versionId": "v1"}]}
        self.saved = False

    def get_raw(self):
        return self._raw

    def save(self):
        self.saved = True


class _WriteAgent(object):
    def __init__(self, name, fail_delete=False):
        self.id = "probe_agent_1"
        self.deleted = False
        self._fail_delete = fail_delete
        self._settings = _WriteAgentSettings(name)

    def get_settings(self):
        return self._settings

    def delete(self):
        if self._fail_delete:
            raise RuntimeError("delete exploded")
        self.deleted = True


class _WriteToolSettings(object):
    def __init__(self, name):
        self.params = {}
        self._name = name
        self.saved = False

    def get_raw(self):
        return {"params": self.params, "name": self._name}

    def save(self):
        self.saved = True


class _WriteTool(object):
    def __init__(self, name, fail_delete=False):
        self.id = "probe_tool_1"
        self.deleted = False
        self._fail_delete = fail_delete
        self._settings = _WriteToolSettings(name)

    def get_settings(self):
        return self._settings

    def delete(self):
        if self._fail_delete:
            raise RuntimeError("delete exploded")
        self.deleted = True


class _WriteProject(object):
    def __init__(self, fail_delete=False):
        self._fail_delete = fail_delete
        self.agent = None
        self.tool = None

    def create_agent(self, name, agent_type):
        self.agent = _WriteAgent(name, self._fail_delete)
        return self.agent

    def get_agent(self, agent_id):
        return self.agent

    def new_agent_tool(self, tool_type, name=None):
        project = self

        class _Creator(object):
            def create(self):
                project.tool = _WriteTool(name, project._fail_delete)
                return project.tool
        return _Creator()

    def get_agent_tool(self, tool_id):
        return self.tool


def _write_results():
    return {
        "suggested_schema_hints": {"internal_key": "pythonAgentSettings",
                                   "code_key": "code", "env_template": None,
                                   "confirmed": False},
        "suggested_discovery": {"type": "semantic_model_query",
                                "params_template": {"model_id": "AHUh9hb"},
                                "template_model_id": "AHUh9hb"},
    }


class TestWriteProbes(unittest.TestCase):
    def test_gate_off_adds_warning_and_does_nothing(self):
        results = {}
        out = probes.run_write_probes(object(), results, allow=False)
        self.assertTrue(any("write probes skipped" in w for w in out["warnings"]))
        self.assertNotIn("write_probe_log", out)

    def test_happy_round_trip_confirms_and_deletes_only_probes(self):
        project = _WriteProject()
        results = _write_results()
        probes.run_write_probes(project, results, allow=True)
        self.assertTrue(results["suggested_schema_hints"]["confirmed"])
        self.assertTrue(results["suggested_discovery"]["confirmed"])
        # both throwaway objects were deleted (via the name-matching guard).
        self.assertTrue(project.agent.deleted)
        self.assertTrue(project.tool.deleted)
        log = " ".join(results["write_probe_log"])
        self.assertIn("probe agent deleted", log)
        self.assertIn("probe tool deleted", log)

    def test_failing_delete_logs_cleanup_and_does_not_raise(self):
        project = _WriteProject(fail_delete=True)
        results = _write_results()
        results["suggested_discovery"] = None  # exercise only the agent path
        probes.run_write_probes(project, results, allow=True)
        log = " ".join(results["write_probe_log"])
        self.assertIn("PROBE CLEANUP FAILED", log)
        self.assertFalse(project.agent.deleted)


# ----------------------------------------------------------- semantic_builder

class _Dataset(object):
    def __init__(self, columns):
        self._columns = columns

    def get_schema(self):
        return {"columns": self._columns}


class _EntityProject(object):
    project_key = "OWISMIND_TEST"

    def get_dataset(self, name):
        return _Dataset([{"name": "col_a", "type": "string"},
                         {"name": "col_b", "type": "bigint"}])


class _TemplateSettings(object):
    def get_raw(self):
        return {"indexingSettings": {"foo": 1},
                "privateEditorData": {"embeddingLlmId": "emb-1"}}


class _TemplateVersion(object):
    def get_settings(self):
        return _TemplateSettings()


class _TemplateModel(object):
    def get_active_version_id(self):
        return "v1"

    def get_version(self, vid):
        return _TemplateVersion()


class _NewVersionSettings(object):
    def __init__(self):
        self._raw = {}
        self.saved = False

    def get_raw(self):
        return self._raw

    def save(self):
        self.saved = True


class _NewModel(object):
    def __init__(self):
        self.id = "new_model_1"
        self.settings = _NewVersionSettings()
        self.active = None

    def new_version(self, name):
        return self.settings

    def set_active_version_id(self, vid):
        self.active = vid


class _SeedProject(object):
    project_key = "OWISMIND_TEST"

    def __init__(self):
        self.new_model = _NewModel()
        self.created = False

    def list_semantic_models(self):
        return []  # find_model_by_name -> None

    def get_dataset(self, name):
        return _Dataset([{"name": "col_a", "type": "string"},
                         {"name": "col_b", "type": "bigint"}])

    def create_semantic_model(self, name):
        self.created = True
        return self.new_model

    def get_semantic_model(self, model_id):
        return _TemplateModel()  # only used as the read-only indexing template


class TestSemanticBuilderStructure(unittest.TestCase):
    def test_build_attribute_resolvable_flags(self):
        resolvable = semantic_builder.build_attribute("c", "string", resolvable=True)
        self.assertEqual(resolvable["distinctValuesHandlingMode"], "AUTO_INDEX")
        self.assertTrue(resolvable["indexDistinctValues"])
        self.assertTrue(resolvable["resolveInUserRequests"])
        plain = semantic_builder.build_attribute("c", "string")
        self.assertEqual(plain["distinctValuesHandlingMode"], "NONE")
        self.assertFalse(plain["indexDistinctValues"])

    def test_build_entity_maps_schema_to_attributes(self):
        entity = semantic_builder.build_entity(_EntityProject(), make_spec())
        self.assertEqual(entity["name"], "satisfaction_record")
        self.assertEqual(entity["datasetRef"], "OWISMIND_TEST.CX_Surveys")
        self.assertEqual([a["column"] for a in entity["attributes"]], ["col_a", "col_b"])


class TestSemanticBuilderSeed(unittest.TestCase):
    def _settings(self):
        return {"template_semantic_model_id": "AHUh9hb"}

    def test_dry_run_plans_and_touches_nothing(self):
        project = _SeedProject()
        ctx = FactoryContext(project=project, dry_run=True)
        result = semantic_builder.seed_model(ctx, make_spec(), self._settings())
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_model"], PLANNED)
        self.assertFalse(project.created)

    def test_real_run_injects_entity_and_copies_template_indexing(self):
        project = _SeedProject()
        ctx = FactoryContext(project=project, dry_run=False)
        result = semantic_builder.seed_model(ctx, make_spec(), self._settings())
        self.assertEqual(result, "new_model_1")
        raw = project.new_model.settings._raw
        self.assertEqual(raw["entities"][0]["datasetRef"], "OWISMIND_TEST.CX_Surveys")
        self.assertEqual(raw["indexingSettings"], {"foo": 1})
        self.assertEqual(raw["privateEditorData"]["embeddingLlmId"], "emb-1")
        self.assertEqual(project.new_model.active, "v1")
        self.assertEqual(statuses(ctx)["semantic_model"], DONE)

    def test_start_indexing_without_model_id_is_skipped(self):
        ctx = FactoryContext(project=object(), dry_run=False)
        result = semantic_builder.start_indexing(ctx, None)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_index"], SKIPPED)

    def test_apply_config_without_model_id_is_manual(self):
        ctx = FactoryContext(project=object(), dry_run=False)
        result = semantic_builder.apply_config(ctx, None, {"metrics": []})
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_config"], MANUAL)


# --------------------------------------------------------------- tool_builder

class _ToolDescribeProject(object):
    def __init__(self, listed=True):
        self._listed = listed

    def list_agent_tools(self):
        if self._listed:
            return [_NamedItem("v4oqA6R", "revenue_semantic_query", "semantic_model_query")]
        return []

    def get_agent_tool(self, tool_id):
        settings = _Settings({"params": {"model_id": "AHUh9hb"}, "description": "d"})
        settings.params = {"model_id": "AHUh9hb"}
        return _ToolHandle(settings)


class _RaisingToolProject(object):
    def list_agent_tools(self):
        raise RuntimeError("HTTP 500")


class TestToolBuilder(unittest.TestCase):
    def test_tool_exists_raises_on_listing_error(self):
        # 'absent' must never be concluded from an API error (anti-duplicate).
        with self.assertRaises(ExistenceCheckError):
            tool_builder.tool_exists(_RaisingToolProject(), "revenue_semantic_query")

    def test_listing_error_fails_caller_without_creating(self):
        ctx = FactoryContext(project=_RaisingToolProject(), dry_run=False)
        result = tool_builder.create_semantic_query_tool_like(
            ctx, make_spec(), "m1", {"type": "x", "params_template": {}})
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_tool"], FAILED)
        self.assertIn("existence check failed", details(ctx))

    def test_dry_run_swallows_listing_error_and_plans(self):
        # In dry-run nothing is created, so an unverifiable existence is tolerated
        # and the run proceeds to the gate (here MANUAL: no discovery given).
        ctx = FactoryContext(project=_RaisingToolProject(), dry_run=True)
        tool_builder.create_semantic_query_tool_like(ctx, make_spec(), "m1", None)
        self.assertEqual(statuses(ctx)["semantic_tool"], MANUAL)

    def test_describe_existing_tool_reads_type_and_params(self):
        info = tool_builder.describe_existing_tool(_ToolDescribeProject(), "v4oqA6R")
        self.assertEqual(info["type"], "semantic_model_query")
        self.assertEqual(info["params"], {"model_id": "AHUh9hb"})

    def test_build_discovery_returns_clone_source(self):
        discovery = tool_builder.build_discovery(_ToolDescribeProject(), "v4oqA6R", "AHUh9hb")
        self.assertEqual(discovery["type"], "semantic_model_query")
        self.assertEqual(discovery["template_model_id"], "AHUh9hb")
        self.assertEqual(discovery["params_template"], {"model_id": "AHUh9hb"})

    def test_build_discovery_none_when_type_absent(self):
        # Tool id not listed -> type stays None -> discovery is refused.
        discovery = tool_builder.build_discovery(_ToolDescribeProject(listed=False),
                                                 "v4oqA6R", "AHUh9hb")
        self.assertIsNone(discovery)

    def test_gated_without_discovery_is_manual_with_checklist(self):
        ctx = FactoryContext(project=_ToolDescribeProject(listed=False), dry_run=False)
        result = tool_builder.create_semantic_query_tool_like(ctx, make_spec(), "m1", None)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_tool"], MANUAL)
        self.assertIn("GATED", details(ctx))
        self.assertIn("Create the Semantic Model Query tool BY HAND", details(ctx))

    def test_no_model_id_is_manual_plain_checklist(self):
        ctx = FactoryContext(project=_ToolDescribeProject(listed=False), dry_run=False)
        result = tool_builder.create_semantic_query_tool_like(ctx, make_spec(), None,
                                                              {"type": "x", "params_template": {}})
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["semantic_tool"], MANUAL)
        self.assertNotIn("GATED", details(ctx))
        self.assertIn("BY HAND", details(ctx))

    def test_build_tool_description_mentions_dataset_and_planner(self):
        text = tool_builder.build_tool_description(make_spec())
        self.assertIn("CX_Surveys", text)
        self.assertIn("satisfaction", text)


# -------------------------------------------------------------- agent_builder

class _HubFile(object):
    def __init__(self, content):
        self._content = content

    def read(self):
        return self._content


class _HubLibrary(object):
    def __init__(self, files):
        self._files = files

    def get_file(self, path):
        return self._files.get(path)


class _HubProject(object):
    def __init__(self, files):
        self._library = _HubLibrary(files)

    def get_library(self):
        return self._library


class _AgentListProject(object):
    def __init__(self, agents):
        self._agents = agents

    def list_agents(self):
        return self._agents


class _RaisingAgentProject(object):
    def list_agents(self):
        raise RuntimeError("HTTP 500")


class _CreateAgentSettings(object):
    def __init__(self):
        self._raw = {"activeVersion": "v1", "versions": [{"versionId": "v1"}]}
        self.saved = False

    def get_raw(self):
        return self._raw

    def save(self):
        self.saved = True


class _CreatedAgent(object):
    def __init__(self):
        self.id = "new_agent_9"
        self._settings = _CreateAgentSettings()

    def get_settings(self):
        return self._settings


class _CreateAgentProject(object):
    def __init__(self, existing=None):
        self._existing = existing
        self.created = None

    def list_agents(self):
        if self._existing:
            return [{"id": self._existing, "name": "Satisfaction_expert"}]
        return []

    def create_agent(self, name, agent_type):
        self.created = _CreatedAgent()
        return self.created


class TestAgentBuilder(unittest.TestCase):
    def test_load_engine_template_present_and_absent(self):
        present = _HubProject({hub_module.TEMPLATE_AGENT_PATH: _HubFile("ENGINE")})
        self.assertEqual(agent_builder.load_engine_template(present), "ENGINE")
        absent = _HubProject({})
        self.assertIsNone(agent_builder.load_engine_template(absent))

    def test_agent_exists_true_false_error(self):
        found = _AgentListProject([{"id": "abc123", "name": "Satisfaction_expert"}])
        self.assertEqual(agent_builder.agent_exists(found, "Satisfaction_expert"), "abc123")
        missing = _AgentListProject([{"id": "abc123", "name": "Other"}])
        self.assertIsNone(agent_builder.agent_exists(missing, "Satisfaction_expert"))
        # a listing error must NOT be concluded as 'absent': it raises so a rerun
        # during a DSS hiccup cannot create a duplicate agent.
        with self.assertRaises(ExistenceCheckError):
            agent_builder.agent_exists(_RaisingAgentProject(), "X")

    def test_paste_checklist_mentions_agent_and_path(self):
        text = agent_builder.paste_checklist(make_spec(), "/python/owismind_hub/generated/Satisfaction_expert.py")
        self.assertIn("Satisfaction_expert", text)
        self.assertIn("/python/owismind_hub/generated/Satisfaction_expert.py", text)

    def test_gated_without_hints_writes_file_and_manual(self):
        ctx = FactoryContext(project=_CreateAgentProject(), dry_run=True)
        result = agent_builder.create_code_agent(ctx, make_spec(), "CODE", schema_hints=None)
        self.assertIsNone(result)
        st = statuses(ctx)
        self.assertEqual(st["code_agent_file"], PLANNED)
        self.assertEqual(st["code_agent"], MANUAL)
        self.assertIn("GATED", details(ctx))

    def test_unconfirmed_hints_are_gated(self):
        # The engine enforces the probe gate itself: hints without confirmed=True
        # fall back to the manual paste path (a notebook overrides consciously by
        # setting confirmed=True on hints it trusts).
        project = _CreateAgentProject()
        ctx = FactoryContext(project=project, dry_run=False)
        hints = {"internal_key": "pythonAgentSettings", "code_key": "code"}
        result = agent_builder.create_code_agent(ctx, make_spec(), "CODE", schema_hints=hints)
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["code_agent"], MANUAL)
        self.assertIsNone(project.created)

    def test_confirmed_hints_create_agent(self):
        project = _CreateAgentProject()
        ctx = FactoryContext(project=project, dry_run=False)
        hints = {"internal_key": "pythonAgentSettings", "code_key": "code",
                 "confirmed": True}
        result = agent_builder.create_code_agent(ctx, make_spec(), "CODE", schema_hints=hints)
        self.assertEqual(result, "agent:new_agent_9")
        self.assertEqual(statuses(ctx)["code_agent"], DONE)
        version = project.created.get_settings().get_raw()["versions"][0]
        self.assertEqual(version["pythonAgentSettings"]["code"], "CODE")

    def test_listing_error_fails_create_without_creating(self):
        # create_code_agent turns an existence-check error into a FAILED action
        # and never attempts creation (unlike the tool builder, it does so even
        # in dry-run: it has no dry-run swallow).
        project = _RaisingAgentProject()
        ctx = FactoryContext(project=project, dry_run=False)
        result = agent_builder.create_code_agent(
            ctx, make_spec(), "CODE",
            schema_hints={"internal_key": "pythonAgentSettings", "code_key": "code"})
        self.assertIsNone(result)
        self.assertEqual(statuses(ctx)["code_agent"], FAILED)
        self.assertIn("existence check failed", details(ctx))

    def test_existing_agent_is_skipped(self):
        project = _CreateAgentProject(existing="live999")
        ctx = FactoryContext(project=project, dry_run=False)
        result = agent_builder.create_code_agent(ctx, make_spec(), "CODE",
                                                 schema_hints={"internal_key": "p", "code_key": "c"})
        self.assertEqual(result, "agent:live999")
        self.assertEqual(statuses(ctx)["code_agent"], SKIPPED)
        self.assertIsNone(project.created)


if __name__ == "__main__":
    unittest.main()
