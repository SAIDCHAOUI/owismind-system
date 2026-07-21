"""Guided run machine + SQL store tests (DSS-free).

Covers the console's step-by-step assistant (owismind_factory.guided):
- state shape and the frozen frontend contract (stage order, statuses);
- preflight hard gates (hub, dataset existence, PARTITIONED dataset, name
  collisions) - the partition gate encodes the 2026-07-21 field failure;
- auto stages delegating to the pipeline with the right steps subsets;
- manual stages: "C'est fait" NEVER advances without a successful DSS check;
- id capture chain (model -> tool -> agent -> capability -> enable);
- guided_store: parameterized SQL, COMMIT on write, identifier gates, caps.

Run from the repo root:
    python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests -v
"""

import json
import os
import sys
import types
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_PKG_PARENT = os.path.abspath(os.path.join(_HERE, "..", "project-library", "python"))
if _PKG_PARENT not in sys.path:
    sys.path.insert(0, _PKG_PARENT)


def _install_dataiku_sql_stub():
    """dataiku + dataiku.sql stubs so _sql_value works without DSS."""
    mod = sys.modules.get("dataiku")
    if mod is None:
        mod = types.ModuleType("dataiku")
        sys.modules["dataiku"] = mod
    sql_mod = types.ModuleType("dataiku.sql")

    class Constant(object):
        def __init__(self, value):
            self.value = value

    class Dialects(object):
        POSTGRES = "postgres"

    def toSQL(node, dialect=None):
        assert isinstance(node, Constant), "values MUST go through Constant"
        return "'" + str(node.value).replace("'", "''") + "'"

    sql_mod.Constant = Constant
    sql_mod.Dialects = Dialects
    sql_mod.toSQL = toSQL
    sys.modules["dataiku.sql"] = sql_mod
    mod.sql = sql_mod
    return mod


_install_dataiku_sql_stub()

from owismind_factory import guided, guided_store, hub  # noqa: E402
from owismind_factory import agent_builder, flow_builder, pipeline  # noqa: E402
from owismind_factory import semantic_builder, tool_builder, wizard  # noqa: E402
from owismind_factory.fctx import FactoryContext  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def _spec():
    return DomainSpec(domain="opportunities", base_dataset="DRIVE_Opportunities",
                      label_fr="Expert opportunités", label_en="Opportunities expert",
                      lookup_search_columns=["Account_name"])


class _FakeProject(object):
    project_key = "OWISMIND_TEST"

    def __init__(self, partitioned=False, settings_raise=False):
        self._partitioned = partitioned
        self._settings_raise = settings_raise

    def get_dataset(self, name):
        outer = self

        class _Settings(object):
            def get_raw(self_inner):
                if outer._settings_raise:
                    raise RuntimeError("boom")
                if outer._partitioned:
                    return {"partitioning": {"dimensions": [{"name": "year"}]}}
                return {"partitioning": {"dimensions": []}}

        class _Dataset(object):
            def get_settings(self_inner):
                return _Settings()

        return _Dataset()


class _Patcher(object):
    """Tiny monkeypatch helper with guaranteed restore."""

    def __init__(self):
        self._saved = []

    def set(self, obj, name, value):
        self._saved.append((obj, name, getattr(obj, name)))
        setattr(obj, name, value)

    def restore(self):
        while self._saved:
            obj, name, value = self._saved.pop()
            setattr(obj, name, value)


_GOOD_WIZARD_CONFIG = {
    "planner_description": "The OWI opportunities expert.",
    "attributes": [{"column": "Account_name"}],
    "golden_queries": [],
}


class _GuidedBase(unittest.TestCase):
    """Common patched world: everything green unless a test overrides."""

    def setUp(self):
        self.p = _Patcher()
        self.project = _FakeProject()
        self.settings = {"sql_connection": "SQL_test", "code_env_311": "py311"}
        self.hub_files = {
            hub.TEMPLATE_AGENT_PATH: 'PROFILE_DATASET = "X"\nVALUE_INDEX_DATASET = "Y"\n'
                                     'SEMANTIC_TOOL_ID = "Z"\nSEMANTIC_TOOL_NAME = "W"\n',
        }
        self.hub_json = {
            hub.HUB_ROOT + "/probe_results.json": {"suggested_discovery": {"type": "T"},
                                                   "suggested_schema_hints": None},
        }
        self.capabilities = {}
        self.appended = {}
        self.written_caps = []

        self.p.set(hub, "read_capabilities", lambda project: dict(self.capabilities))
        self.p.set(hub, "read_text", lambda project, path: self.hub_files.get(path))
        self.p.set(hub, "read_json",
                   lambda project, path: self.hub_json.get(path))
        self.p.set(hub, "append_capability",
                   lambda project, key, entry: self.appended.update({key: entry}))
        self.p.set(hub, "write_capabilities",
                   lambda project, caps: self.written_caps.append(json.loads(json.dumps(caps))))
        self.p.set(flow_builder, "dataset_exists", lambda project, name: True)
        self.p.set(pipeline, "create_domain", self._fake_pipeline)
        self.p.set(semantic_builder, "find_model_by_name",
                   lambda project, name: types.SimpleNamespace(id="MODEL1"))
        self.p.set(tool_builder, "tool_exists", lambda project, name: "TOOL1")
        self.p.set(agent_builder, "agent_exists", lambda project, name: None)
        self.p.set(agent_builder, "load_engine_template",
                   lambda project: self.hub_files.get(hub.TEMPLATE_AGENT_PATH))
        self.p.set(agent_builder, "generate_subagent_code",
                   lambda template, spec, tool_id, deploy_project=None:
                   "# generated for %s tool=%s" % (spec.domain, tool_id))
        self.p.set(agent_builder, "create_code_agent", self._fake_create_agent)
        self.p.set(wizard, "get_physical_table",
                   lambda project, dataset: "%s_%s" % (self.project.project_key, dataset))
        self.pipeline_calls = []
        self.created_agent = None  # None = gated (manual paste), else "agent:<id>"
        self.rows = {}             # physical table -> has rows bool

        self.executor_factory = lambda: self._fail_executor()

    def _fail_executor(self):
        raise AssertionError("real executor must not be used in tests")

    def tearDown(self):
        self.p.restore()

    # --- fakes ------------------------------------------------------------

    def _fake_pipeline(self, ctx, spec, wizard_config=None, discovery=None,
                       schema_hints=None, steps=None, settings=None):
        self.pipeline_calls.append({"steps": steps, "wizard_config": wizard_config,
                                    "dry_run": ctx.dry_run})
        ctx.record("pipeline", "DONE" if not ctx.dry_run else "PLANNED",
                   "steps=%s" % (steps or "all"))

    def _fake_create_agent(self, ctx, spec, code, schema_hints, code_env=""):
        if self.created_agent:
            ctx.done("code_agent", "created")
            return self.created_agent
        ctx.act("code_agent_file", "write generated agent code", lambda: True)
        ctx.manual("code_agent", "paste by hand")
        return None

    def _store_stub(self):
        outer = self

        class _S(object):
            def table_has_rows(self_inner, table):
                return outer.rows.get(table)

        return _S()

    # --- drivers ----------------------------------------------------------

    def start(self):
        return guided.start_run(self.project, _spec(), settings=self.settings,
                                executor_factory=self.executor_factory)

    def run_stage(self, run):
        return guided.run_current_stage(self.project, run, settings=self.settings,
                                        executor_factory=self.executor_factory)

    def verify(self, run):
        return guided.verify_current_stage(self.project, run, settings=self.settings,
                                           executor_factory=self.executor_factory)

    def drive_to(self, target):
        """Advance a fresh run through green stages until ``target`` is current."""
        self.p.set(guided._Env, "store", lambda env: self._store_stub())
        run = self.start()
        guard = 0
        while run["current_stage"] != target and run["status"] == guided.RUN_ACTIVE:
            guard += 1
            self.assertLess(guard, 40, "did not reach %s (stuck at %s)"
                            % (target, run["current_stage"]))
            if guided.can_run(run):
                run = self.run_stage(run)
            elif guided.can_verify(run):
                before = run["current_stage"]
                run = self.verify(run)
                self.assertNotEqual(
                    (before, run["state"]["stages"][before]["status"]),
                    (run["current_stage"], guided.WAITING),
                    "verify did not advance at %s: %s"
                    % (before, run["state"]["stages"][before]["problems"]))
            else:
                self.fail("stage %s neither runnable nor verifiable" % run["current_stage"])
        return run


class TestStateShape(_GuidedBase):
    def test_stage_order_and_initial_statuses(self):
        state = guided.new_state(_spec())
        self.assertEqual(state["stage_order"], guided.STAGE_ORDER)
        self.assertEqual(len(state["stages"]), 13)
        self.assertEqual(state["stages"]["preflight"]["status"], guided.READY)
        for key in guided.STAGE_ORDER[1:]:
            self.assertEqual(state["stages"][key]["status"], guided.PENDING)

    def test_no_banned_dashes_anywhere(self):
        state = guided.new_state(_spec())
        env = guided._Env(self.project, self.settings)
        texts = [json.dumps(state, ensure_ascii=False)]
        for key, builder in guided._INSTRUCTIONS.items():
            texts.append(builder(env, state))
        blob = "\n".join(texts)
        self.assertNotIn("\u2014", blob)
        self.assertNotIn("\u2013", blob)

    def test_every_stage_is_actionable(self):
        for key in guided.STAGE_ORDER:
            self.assertTrue(key in guided._RUNNERS or key in guided._CHECKERS,
                            "stage %s has neither runner nor checker" % key)
        for key in guided._CHECKERS:
            if key not in guided._RUNNERS:
                self.assertIn(key, guided._INSTRUCTIONS,
                              "manual stage %s has no instructions" % key)


class TestPreflight(_GuidedBase):
    def test_green_path_advances_to_plan(self):
        run = self.start()
        self.assertEqual(run["current_stage"], "plan")
        self.assertEqual(run["state"]["stages"]["preflight"]["status"], guided.DONE)
        self.assertEqual(run["state"]["stages"]["plan"]["status"], guided.READY)

    def test_partitioned_dataset_blocks(self):
        self.project = _FakeProject(partitioned=True)
        run = self.start()
        self.assertEqual(run["current_stage"], "preflight")
        self.assertEqual(run["state"]["stages"]["preflight"]["status"], guided.STAGE_FAILED)
        self.assertTrue(any("PARTITIONN" in p for p in
                            run["state"]["stages"]["preflight"]["problems"]))
        self.assertTrue(guided.can_run(run), "a failed preflight must be re-runnable")

    def test_unreadable_partitioning_warns_but_does_not_block(self):
        self.project = _FakeProject(settings_raise=True)
        run = self.start()
        self.assertEqual(run["current_stage"], "plan")

    def test_missing_dataset_blocks(self):
        self.p.set(flow_builder, "dataset_exists", lambda project, name: False)
        run = self.start()
        self.assertEqual(run["state"]["stages"]["preflight"]["status"], guided.STAGE_FAILED)

    def test_hub_absent_blocks(self):
        self.p.set(hub, "read_capabilities", lambda project: None)
        run = self.start()
        self.assertEqual(run["state"]["stages"]["preflight"]["status"], guided.STAGE_FAILED)

    def test_capability_collision_blocks(self):
        self.capabilities = {"opportunities_expert": {"domain": "opportunities"}}
        run = self.start()
        problems = run["state"]["stages"]["preflight"]["problems"]
        self.assertTrue(any("opportunities_expert" in p for p in problems))


class TestAutoStages(_GuidedBase):
    def test_plan_is_dry_run_and_advances(self):
        run = self.start()
        run = self.run_stage(run)
        self.assertEqual(run["current_stage"], "infra")
        plan_calls = [c for c in self.pipeline_calls if c["dry_run"]]
        self.assertEqual(len(plan_calls), 1)
        self.assertIsNone(plan_calls[0]["steps"], "plan must simulate ALL steps")

    def test_infra_uses_the_infra_steps_subset(self):
        run = self.start()
        run = self.run_stage(run)   # plan
        run = self.run_stage(run)   # infra
        infra_calls = [c for c in self.pipeline_calls if c["steps"] == guided._INFRA_STEPS]
        self.assertEqual(len(infra_calls), 1)
        self.assertEqual(run["current_stage"], "first_build")
        stage = run["state"]["stages"]["first_build"]
        self.assertEqual(stage["status"], guided.WAITING)
        self.assertIn("Refresh_Opportunities", stage["instructions_fr"])
        self.assertIn("partition", stage["instructions_fr"].lower())

    def test_infra_failure_surfaces_and_is_retryable(self):
        def failing_pipeline(ctx, spec, **kwargs):
            self.pipeline_calls.append({"steps": kwargs.get("steps"),
                                        "dry_run": ctx.dry_run})
            ctx.fail("recipes", "boom")
        self.p.set(pipeline, "create_domain", failing_pipeline)
        run = self.start()
        run = self.run_stage(run)   # plan (dry, no failure recorded by has_failures? fail recorded)
        # plan records a FAILED action -> plan itself fails first: rerun scenario
        self.assertEqual(run["state"]["stages"]["plan"]["status"], guided.STAGE_FAILED)
        self.assertTrue(guided.can_run(run))


class TestFirstBuildGate(_GuidedBase):
    def test_empty_profile_blocks_then_rows_advance(self):
        self.p.set(guided._Env, "store", lambda env: self._store_stub())
        self.rows = {"OWISMIND_TEST_DRIVE_Opportunities_profile": False,
                     "OWISMIND_TEST_DRIVE_Opportunities_value_index": False}
        run = self.start()
        run = self.run_stage(run)   # plan
        run = self.run_stage(run)   # infra
        run = self.verify(run)      # first_build : empty -> refused
        stage = run["state"]["stages"]["first_build"]
        self.assertEqual(stage["status"], guided.WAITING)
        self.assertTrue(any("VIDE" in p for p in stage["problems"]))
        self.rows = {"OWISMIND_TEST_DRIVE_Opportunities_profile": True,
                     "OWISMIND_TEST_DRIVE_Opportunities_value_index": True}
        run = self.verify(run)
        self.assertEqual(run["current_stage"], "profile_review")

    def test_unverifiable_rows_do_not_block(self):
        self.p.set(guided._Env, "store", lambda env: self._store_stub())
        self.rows = {}  # table_has_rows -> None (unknown)
        run = self.start()
        run = self.run_stage(run)
        run = self.run_stage(run)
        run = self.verify(run)
        self.assertEqual(run["current_stage"], "profile_review")


class TestWizardGate(_GuidedBase):
    def _to_wizard(self):
        self.p.set(guided._Env, "store", lambda env: self._store_stub())
        self.rows = {"OWISMIND_TEST_DRIVE_Opportunities_profile": True,
                     "OWISMIND_TEST_DRIVE_Opportunities_value_index": True}
        run = self.start()
        run = self.run_stage(run)   # plan
        run = self.run_stage(run)   # infra
        run = self.verify(run)      # first_build
        run = self.verify(run)      # profile_review
        self.assertEqual(run["current_stage"], "wizard")
        return run

    def test_wizard_requires_a_saved_valid_config(self):
        run = self._to_wizard()
        run = self.verify(run)
        self.assertEqual(run["state"]["stages"]["wizard"]["status"], guided.WAITING)
        self.assertTrue(run["state"]["stages"]["wizard"]["problems"])
        self.hub_json[guided.wizard_config_path("opportunities")] = dict(_GOOD_WIZARD_CONFIG)
        run = self.verify(run)
        self.assertEqual(run["current_stage"], "brain")

    def test_wizard_refuses_a_draft_stamped_for_another_dataset(self):
        run = self._to_wizard()
        stale = dict(_GOOD_WIZARD_CONFIG)
        stale["base_dataset"] = "OLD_Dataset"
        self.hub_json[guided.wizard_config_path("opportunities")] = stale
        run = self.verify(run)
        stage = run["state"]["stages"]["wizard"]
        self.assertEqual(stage["status"], guided.WAITING)
        self.assertTrue(any("OLD_Dataset" in p for p in stage["problems"]))

    def test_wizard_precheck_skips_only_on_proven_dataset_match(self):
        self.p.set(guided._Env, "store", lambda env: self._store_stub())
        self.rows = {"OWISMIND_TEST_DRIVE_Opportunities_profile": True,
                     "OWISMIND_TEST_DRIVE_Opportunities_value_index": True}
        # With provably built datasets, first_build precheck-skips: after infra
        # the current stage is profile_review, and ONE verify lands on wizard.
        # Unstamped (legacy) draft: valid for a human verify, NOT enough to skip.
        self.hub_json[guided.wizard_config_path("opportunities")] = dict(_GOOD_WIZARD_CONFIG)
        run = self.start()
        run = self.run_stage(run)   # plan
        run = self.run_stage(run)   # infra (first_build auto-skipped: rows proven)
        self.assertEqual(run["current_stage"], "profile_review")
        run = self.verify(run)      # profile_review
        self.assertEqual(run["current_stage"], "wizard",
                         "an unstamped draft must not auto-skip the wizard stage")
        # Stamped for THIS dataset: the walk may skip the wizard stage.
        stamped = dict(_GOOD_WIZARD_CONFIG)
        stamped["base_dataset"] = "DRIVE_Opportunities"
        self.hub_json[guided.wizard_config_path("opportunities")] = stamped
        run2 = self.start()
        run2 = self.run_stage(run2)
        run2 = self.run_stage(run2)
        run2 = self.verify(run2)    # profile_review -> wizard skipped -> brain
        self.assertEqual(run2["current_stage"], "brain")
        self.assertEqual(run2["state"]["stages"]["wizard"]["status"], guided.DONE)


class TestBrainAndTool(_GuidedBase):
    def _to_brain(self):
        self.hub_json[guided.wizard_config_path("opportunities")] = dict(_GOOD_WIZARD_CONFIG)
        return self.drive_to("brain")

    def test_tool_created_captures_ids_and_skips_manual(self):
        run = self._to_brain()
        run = self.run_stage(run)
        self.assertEqual(run["state"]["captured"]["model_id"], "MODEL1")
        self.assertEqual(run["state"]["captured"]["tool_id"], "TOOL1")
        # template present -> precheck-skipped; next actionable stage: agent_code
        self.assertEqual(run["current_stage"], "agent_code")
        self.assertEqual(run["state"]["stages"]["template"]["status"], guided.DONE)

    def test_gated_tool_degrades_to_guided_manual(self):
        self.p.set(tool_builder, "tool_exists", lambda project, name: None)
        run = self._to_brain()
        run = self.run_stage(run)
        stage = run["state"]["stages"]["brain"]
        self.assertEqual(stage["status"], guided.WAITING)
        self.assertIn("opportunities_semantic_query", stage["instructions_fr"])
        self.p.set(tool_builder, "tool_exists", lambda project, name: "TOOL9")
        run = self.verify(run)
        self.assertEqual(run["state"]["captured"]["tool_id"], "TOOL9")

    def test_missing_model_fails_hard(self):
        self.p.set(semantic_builder, "find_model_by_name", lambda project, name: None)
        run = self._to_brain()
        run = self.run_stage(run)
        self.assertEqual(run["state"]["stages"]["brain"]["status"], guided.STAGE_FAILED)


class TestAgentChain(_GuidedBase):
    def _to_agent_code(self):
        self.hub_json[guided.wizard_config_path("opportunities")] = dict(_GOOD_WIZARD_CONFIG)
        run = self.drive_to("agent_code")
        return run

    def test_gated_generation_waits_for_manual_paste_then_captures(self):
        run = self._to_agent_code()
        run = self.run_stage(run)
        self.assertEqual(run["current_stage"], "code_agent")
        self.assertIn("generated/Opportunities_expert.py",
                      run["state"]["captured"]["generated_path"])
        stage = run["state"]["stages"]["code_agent"]
        self.assertEqual(stage["status"], guided.WAITING)
        self.assertIn("Opportunities_expert", stage["instructions_fr"])
        self.assertIn("3.11", stage["instructions_fr"])
        # "C'est fait" without the agent -> refused
        run = self.verify(run)
        self.assertEqual(run["state"]["stages"]["code_agent"]["status"], guided.WAITING)
        # the agent now exists -> captured and advanced
        self.p.set(agent_builder, "agent_exists", lambda project, name: "AG1")
        run = self.verify(run)
        self.assertEqual(run["state"]["captured"]["agent_id"], "agent:AG1")
        self.assertEqual(run["current_stage"], "capability")

    def test_auto_created_agent_skips_the_manual_stage(self):
        self.created_agent = "agent:AUTO1"
        self.p.set(agent_builder, "agent_exists", lambda project, name: "AUTO1")
        run = self._to_agent_code()
        run = self.run_stage(run)
        self.assertEqual(run["state"]["captured"]["agent_id"], "agent:AUTO1")
        self.assertEqual(run["state"]["stages"]["code_agent"]["status"], guided.DONE)
        self.assertEqual(run["current_stage"], "capability")


class TestCapabilityAndEnable(_GuidedBase):
    def _to_capability(self):
        self.hub_json[guided.wizard_config_path("opportunities")] = dict(_GOOD_WIZARD_CONFIG)
        self.created_agent = "agent:AUTO1"
        self.p.set(agent_builder, "agent_exists", lambda project, name: "AUTO1")
        return self.drive_to("capability")

    def test_capability_written_disabled_with_wizard_routing(self):
        run = self._to_capability()
        run = self.run_stage(run)
        entry = self.appended["opportunities_expert"]
        self.assertEqual(entry["agent_id"], "agent:AUTO1")
        self.assertIs(entry["enabled"], False)
        self.assertEqual(entry["planner_description"],
                         _GOOD_WIZARD_CONFIG["planner_description"])
        self.assertEqual(run["current_stage"], "smoke")
        self.assertEqual(run["state"]["stages"]["smoke"]["status"], guided.WAITING)

    def test_enable_flips_the_flag_and_finishes_the_run(self):
        run = self._to_capability()
        run = self.run_stage(run)                       # capability
        self.capabilities = {"opportunities_expert":
                             dict(self.appended["opportunities_expert"])}
        run = self.verify(run)                          # smoke (human confirm)
        self.assertEqual(run["current_stage"], "enable")
        run = self.run_stage(run)                       # enable
        self.assertEqual(run["status"], guided.RUN_DONE)
        self.assertIs(self.written_caps[-1]["opportunities_expert"]["enabled"], True)

    def test_enable_validation_error_fails_cleanly(self):
        def raising_write(project, caps):
            raise ValueError("one enabled capability per domain")
        run = self._to_capability()
        run = self.run_stage(run)
        self.capabilities = {"opportunities_expert":
                             dict(self.appended["opportunities_expert"])}
        run = self.verify(run)
        self.p.set(hub, "write_capabilities", raising_write)
        run = self.run_stage(run)
        stage = run["state"]["stages"]["enable"]
        self.assertEqual(stage["status"], guided.STAGE_FAILED)
        self.assertTrue(any("per domain" in p for p in stage["problems"]))


class TestWizardLlmCall(unittest.TestCase):
    """draft_model_config: model picked by the operator, connection knobs untouched."""

    def _fake_llm_project(self, captured):
        class _Completion(object):
            def __init__(self):
                self.settings = {}

            def with_message(self, prompt):
                captured["prompt"] = prompt

            def with_json_output(self, schema=None):
                captured["json_output"] = True

            def execute(self):
                return types.SimpleNamespace(
                    success=True,
                    text=json.dumps({"planner_description": "d",
                                     "attributes": [{"column": "c"}]}))

        class _Llm(object):
            def new_completion(self):
                completion = _Completion()
                captured["completion"] = completion
                return completion

        class _Project(object):
            project_key = "OWISMIND_TEST"

            def get_llm(self, llm_id):
                captured["llm_id"] = llm_id
                return _Llm()

        return _Project()

    def test_llm_wizard_override_wins_and_no_sampling_override(self):
        captured = {}
        project = self._fake_llm_project(captured)
        saved_settings = hub.get_settings
        saved_profile = wizard.read_profile
        hub.get_settings = lambda p: {"llm_sonnet": "mesh:sonnet", "llm_wizard": "mesh:custom"}
        wizard.read_profile = lambda dataset, project_key=None: {"__dataset__": {"row_count": 1}}
        try:
            config = wizard.draft_model_config(project, "Delivery_Snapshot_profile",
                                               base_dataset="Delivery_Snapshot",
                                               domain="delivery")
        finally:
            hub.get_settings = saved_settings
            wizard.read_profile = saved_profile
        self.assertEqual(captured["llm_id"], "mesh:custom")
        self.assertNotIn("temperature", captured["completion"].settings,
                         "sampling knobs belong to the admin-tuned connection "
                         "(thinking-enabled Claude rejects temperature != 1)")
        self.assertEqual(config["base_dataset"], "Delivery_Snapshot")
        self.assertEqual(config["domain"], "delivery")

    def test_llm_wizard_empty_falls_back_to_llm_sonnet(self):
        captured = {}
        project = self._fake_llm_project(captured)
        saved_settings = hub.get_settings
        saved_profile = wizard.read_profile
        hub.get_settings = lambda p: {"llm_sonnet": "mesh:sonnet", "llm_wizard": ""}
        wizard.read_profile = lambda dataset, project_key=None: {"__dataset__": {"row_count": 1}}
        try:
            wizard.draft_model_config(project, "Delivery_Snapshot_profile",
                                      base_dataset="Delivery_Snapshot", domain="delivery")
        finally:
            hub.get_settings = saved_settings
            wizard.read_profile = saved_profile
        self.assertEqual(captured["llm_id"], "mesh:sonnet")


class TestReadProfile(unittest.TestCase):
    """read_profile: the PROVEN iter_tuples pattern, both paths, loud guard."""

    def _install_dataset(self, dataset_cls):
        mod = sys.modules["dataiku"]
        saved = getattr(mod, "Dataset", None)
        mod.Dataset = dataset_cls
        return saved

    def _restore_dataset(self, saved):
        mod = sys.modules["dataiku"]
        if saved is None:
            if hasattr(mod, "Dataset"):
                del mod.Dataset
        else:
            mod.Dataset = saved

    def test_iter_tuples_path_parses_business_columns(self):
        payloads = {"__dataset__": {"row_count": 2237},
                    "Family": {"dss_type": "string", "distinct_count": 7},
                    "Customer": {"dss_type": "string", "distinct_count": 130}}

        class _DS(object):
            def __init__(self, name, project_key=None):
                pass

            def read_schema(self):
                return [{"name": "key"}, {"name": "payload"}]

            def iter_tuples(self):
                for key, value in payloads.items():
                    yield (key, json.dumps(value))

        saved = self._install_dataset(_DS)
        try:
            profile = wizard.read_profile("Delivery_Snapshot_profile")
        finally:
            self._restore_dataset(saved)
        self.assertEqual(set(profile), {"__dataset__", "Family", "Customer"})
        self.assertEqual(profile["Family"]["distinct_count"], 7)

    def test_dataframe_fallback_path(self):
        class _DF(object):
            def head(self, n):
                return self

            def to_dict(self, orient):
                return [{"key": "Order_id", "payload": json.dumps({"dss_type": "string"})}]

        class _DS(object):
            def __init__(self, name, project_key=None):
                pass

            def read_schema(self):
                raise RuntimeError("no schema API here")

            def get_dataframe(self):
                return _DF()

        saved = self._install_dataset(_DS)
        try:
            profile = wizard.read_profile("Delivery_Snapshot_profile")
        finally:
            self._restore_dataset(saved)
        self.assertEqual(set(profile), {"Order_id"})

    def test_degenerate_profile_fails_loudly_in_draft(self):
        captured = {}

        class _Project(object):
            project_key = "OWISMIND_TEST"

            def get_llm(self, llm_id):
                captured["llm_called"] = True
                raise AssertionError("the LLM must not be called on a degenerate profile")

        saved_settings = hub.get_settings
        saved_profile = wizard.read_profile
        hub.get_settings = lambda p: {"llm_sonnet": "mesh:sonnet", "llm_wizard": ""}
        # The exact degenerate shape the iter_rows bug produced on the field.
        wizard.read_profile = lambda dataset, project_key=None: {"key": {"raw": "payload"}}
        try:
            config = wizard.draft_model_config(_Project(), "Delivery_Snapshot_profile",
                                               base_dataset="Delivery_Snapshot",
                                               domain="delivery")
        finally:
            hub.get_settings = saved_settings
            wizard.read_profile = saved_profile
        self.assertIn("error", config)
        self.assertIn("degenerate", config["error"])
        self.assertNotIn("llm_called", captured)


class TestHealAndGuards(_GuidedBase):
    def test_heal_interrupted_running_stage(self):
        run = self.start()
        run["state"]["stages"]["plan"]["status"] = guided.RUNNING
        self.assertTrue(guided.heal_interrupted(run))
        self.assertEqual(run["state"]["stages"]["plan"]["status"], guided.STAGE_FAILED)
        self.assertFalse(guided.heal_interrupted(run))

    def test_entry_points_refuse_inactive_or_wrong_state(self):
        run = self.start()
        guided.abandon_run(run)
        with self.assertRaises(ValueError):
            guided.run_current_stage(self.project, run, settings=self.settings)
        with self.assertRaises(ValueError):
            guided.verify_current_stage(self.project, run, settings=self.settings)


# --------------------------------------------------------------------- store

class _FakeDF(object):
    def __init__(self, rows):
        self._rows = rows

    def __len__(self):
        return len(self._rows)

    @property
    def iloc(self):
        return self._rows


class _FakeExecutor(object):
    def __init__(self, rows=None, raise_on_read=False):
        self.calls = []
        self.rows = rows or []
        self.raise_on_read = raise_on_read

    def query_to_df(self, query, pre_queries=None, post_queries=None):
        self.calls.append({"query": query, "pre": list(pre_queries or []),
                           "post": list(post_queries or [])})
        if pre_queries and any(q.startswith("SET statement_timeout") for q in pre_queries) \
                and self.raise_on_read:
            raise RuntimeError("read failed")
        return _FakeDF(self.rows)


class TestGuidedStore(unittest.TestCase):
    def setUp(self):
        guided_store._ENSURED.clear()
        self.executor = _FakeExecutor()
        self.store = guided_store.GuidedStore(
            "SQL_test", "OWISMIND_TEST", executor_factory=lambda: self.executor)

    def test_physical_table_naming_and_shortening(self):
        self.assertEqual(guided_store.physical_table("OWISMIND_TEST"),
                         "OWISMIND_TEST_owismind_factory_guided_v1")
        long_key = "P" * 80
        short = guided_store.physical_table(long_key)
        self.assertLessEqual(len(short.encode("utf-8")), 63)
        other = guided_store.physical_table("P" * 81)
        self.assertNotEqual(short, other, "shortened names must not collide")
        with self.assertRaises(guided_store.GuidedStoreError):
            guided_store.physical_table('bad"key')

    def test_quote_table_rejects_injection(self):
        for bad in ('x"; DROP TABLE y; --', "a b", "", 'a"b'):
            with self.assertRaises(guided_store.GuidedStoreError):
                guided_store.quote_table(bad)

    def test_save_is_parameterized_and_committed(self):
        run = {"run_id": "r1", "domain": "opportunities", "status": "active",
               "current_stage": "plan",
               "state": {"note": "l'apostrophe d'essai"}}
        self.store.save(run)
        write_calls = [c for c in self.executor.calls if c["post"] == ["COMMIT"]]
        self.assertEqual(len(write_calls), 2, "DDL then upsert, each committed")
        upsert = write_calls[-1]["pre"][0]
        self.assertIn("ON CONFLICT (run_id) DO UPDATE", upsert)
        self.assertIn('public."OWISMIND_TEST_owismind_factory_guided_v1"', upsert)
        self.assertIn("''", upsert, "quotes inside values must be escaped by the param layer")

    def test_load_active_parses_state(self):
        self.executor.rows = [{"run_id": "r1", "domain": "d", "status": "active",
                               "current_stage": "plan",
                               "state_json": json.dumps({"version": 1})}]
        run = self.store.load_active()
        self.assertEqual(run["run_id"], "r1")
        self.assertEqual(run["state"], {"version": 1})
        read = self.executor.calls[-1]
        self.assertIn("LIMIT 1", read["query"])
        self.assertTrue(any(q.startswith("SET statement_timeout") for q in read["pre"]))

    def test_serialize_state_trims_then_refuses(self):
        journal = [{"step": "s", "status": "DONE", "detail": "x" * 200}] * 600
        state = {"stages": {"infra": {"journal": list(journal)}},
                 "spec": {}}
        text = guided_store.serialize_state(state)
        self.assertLessEqual(len(text), guided_store._STATE_SOFT_CAP + 20000)
        huge = {"blob": "x" * (guided_store._STATE_HARD_CAP + 1)}
        with self.assertRaises(guided_store.GuidedStoreError):
            guided_store.serialize_state(huge)

    def test_table_has_rows_true_false_unknown(self):
        self.executor.rows = [{"ok": 1}]
        self.assertTrue(self.store.table_has_rows("OWISMIND_TEST_x_profile"))
        self.executor.rows = []
        self.assertFalse(self.store.table_has_rows("OWISMIND_TEST_x_profile"))
        self.assertIsNone(self.store.table_has_rows('weird"name'))
        failing = guided_store.GuidedStore(
            "SQL_test", "OWISMIND_TEST",
            executor_factory=lambda: _FakeExecutor(raise_on_read=True))
        self.assertIsNone(failing.table_has_rows("OWISMIND_TEST_x_profile"))


if __name__ == "__main__":
    unittest.main()
