"""DSS-free unit tests for dataiku-agents/agents/orchestrator_agent.py (v3).

Loads BOTH the orchestrator and the dataset expert files (dataiku stubbed) to
enforce the cross-file event contract (anti-drift), and exercises the v3
parallel fan-out machinery end-to-end with a fake streaming LLM — threads
included, no DSS required.

Run from the repo root:
    python3 -m unittest discover -s dataiku-agents/tests -v
"""

import importlib.util
import os
import re
import sys
import types
import unittest


def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
    dataiku_mod.Dataset = lambda *a, **k: None
    dataiku_mod.SQLExecutor2 = lambda *a, **k: None

    llm_pkg = types.ModuleType("dataiku.llm")
    llm_python = types.ModuleType("dataiku.llm.python")

    class BaseLLM(object):
        pass

    llm_python.BaseLLM = BaseLLM
    llm_pkg.python = llm_python
    dataiku_mod.llm = llm_pkg

    sys.modules.setdefault("dataiku", dataiku_mod)
    sys.modules.setdefault("dataiku.llm", llm_pkg)
    sys.modules.setdefault("dataiku.llm.python", llm_python)


_install_dataiku_stub()

_HERE = os.path.dirname(__file__)


def _load(name, rel_path):
    path = os.path.abspath(os.path.join(_HERE, "..", rel_path))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


orch = _load("orchestrator_v3_under_test", "agents/orchestrator_agent.py")
dx = _load("dataset_expert_for_drift", "agents/dataset_expert_agent.py")

_EXPERT_SOURCE = open(os.path.abspath(os.path.join(
    _HERE, "..", "agents", "dataset_expert_agent.py")), encoding="utf-8").read()


# ==========================================================================
# Registry / manifest (v3 entry + anti-drift vs the dataset expert file)
# ==========================================================================
class TestRegistry(unittest.TestCase):

    def test_revenue_expert_entry_complete(self):
        cap = orch.CAPABILITIES["revenue_expert"]
        for key in ("kind", "agent_id", "domain", "label_fr", "label_en",
                    "planner_description", "dataset_label_fr",
                    "dataset_label_en", "dataset_ref", "block_labels",
                    "tool_labels", "pass_context", "enabled"):
            self.assertIn(key, cap)
        self.assertEqual(cap["kind"], "agent")
        self.assertEqual(cap["domain"], "revenue")
        self.assertTrue(cap["pass_context"])

    def test_one_revenue_capability_enabled_at_a_time(self):
        enabled = [k for k, v in orch.CAPABILITIES.items()
                   if v.get("kind") == "agent" and v.get("domain") == "revenue"
                   and v.get("enabled")]
        self.assertEqual(len(enabled), 1,
                         "exactly ONE revenue agent must be enabled, got %s"
                         % enabled)

    def test_block_labels_match_expert_contract(self):
        """Anti-drift: the registry must label EXACTLY the blockIds/toolNames
        the dataset expert file declares (KNOWN_BLOCK_IDS/KNOWN_TOOL_NAMES)."""
        cap = orch.CAPABILITIES["revenue_expert"]
        self.assertEqual(set(cap["block_labels"].keys()),
                         set(dx.KNOWN_BLOCK_IDS))
        self.assertEqual(set(cap["tool_labels"].keys()),
                         set(dx.KNOWN_TOOL_NAMES))

    def test_expert_source_emits_only_declared_ids(self):
        """Every _block("...") / _tool_start("...") literal in the expert file
        must be declared in its KNOWN_* constants."""
        emitted_blocks = set(re.findall(r'_block\("([a-z_]+)"\)', _EXPERT_SOURCE))
        emitted_tools = set(re.findall(r'_tool_start\("([a-z_]+)"\)', _EXPERT_SOURCE))
        self.assertTrue(emitted_blocks)
        self.assertTrue(emitted_tools)
        self.assertLessEqual(emitted_blocks, set(dx.KNOWN_BLOCK_IDS),
                             "undeclared blockId emitted: %s"
                             % (emitted_blocks - set(dx.KNOWN_BLOCK_IDS)))
        self.assertLessEqual(emitted_tools, set(dx.KNOWN_TOOL_NAMES),
                             "undeclared toolName emitted: %s"
                             % (emitted_tools - set(dx.KNOWN_TOOL_NAMES)))

    def test_planner_sees_expert_when_enabled(self):
        caps = {k: dict(v) for k, v in orch.CAPABILITIES.items()}
        caps["revenue_expert"]["enabled"] = True
        caps["salesdrive_v2"]["enabled"] = False
        enabled = {k: v for k, v in caps.items() if v.get("enabled")}
        prompt = orch.build_planner_prompt(enabled)
        self.assertIn("revenue_expert", prompt)
        self.assertIn("DESCRIBE the data", prompt)
        self.assertNotIn("salesdrive_v2", prompt)

    def test_v3_constants(self):
        self.assertGreaterEqual(orch.MAX_PARALLEL_AGENTS, 2)
        self.assertGreater(orch.PARALLEL_TOTAL_TIMEOUT_S, 60)


# ==========================================================================
# Plan validation (v2.4 behaviour preserved)
# ==========================================================================
class TestValidatePlan(unittest.TestCase):

    CAPS = {"revenue_expert": {"kind": "agent"},
            "current_date": {"kind": "tool"}}

    def _validate(self, parsed):
        return orch.MyLLM._validate_plan(parsed, self.CAPS)

    def test_business_without_valid_steps_is_rejected(self):
        self.assertIsNone(self._validate({"intent": "BUSINESS",
                                          "language": "fr", "steps": []}))
        self.assertIsNone(self._validate({"intent": "BUSINESS", "language": "fr",
                                          "steps": [{"kind": "agent",
                                                     "capability": "ghost",
                                                     "instruction": "x"}]}))

    def test_steps_purged_on_non_business(self):
        plan = self._validate({"intent": "GREETING", "language": "fr",
                               "steps": [{"kind": "agent",
                                          "capability": "revenue_expert",
                                          "instruction": "x"}]})
        self.assertEqual(plan["steps"], [])

    def test_kind_mismatch_purged(self):
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [
                                   {"kind": "tool", "capability": "revenue_expert",
                                    "instruction": "x"},
                                   {"kind": "agent", "capability": "revenue_expert",
                                    "instruction": "ok"}]})
        self.assertEqual(len(plan["steps"]), 1)
        self.assertEqual(plan["steps"][0]["instruction"], "ok")

    def test_unknown_intent_rejected(self):
        self.assertIsNone(self._validate({"intent": "ALIEN", "language": "fr"}))


# ==========================================================================
# v3 parallel fan-out — exercised end-to-end with fakes (threads included)
# ==========================================================================
class _FakeChunk(object):
    def __init__(self, data):
        self.data = data


class _FakeCompletion(object):
    """Stands in for a streamed sub-agent completion."""

    def __init__(self, chunks):
        self._chunks = chunks
        self.messages = []

    def with_message(self, content, role="user"):
        self.messages.append((role, content))
        return self

    def execute_streamed(self):
        for c in self._chunks:
            yield _FakeChunk(c)


class _FakeLLM(object):
    def __init__(self, chunks):
        self._chunks = chunks

    def new_completion(self):
        return _FakeCompletion(list(self._chunks))


class _FakeProject(object):
    """get_llm(agent_id) -> scripted stream per agent id."""

    def __init__(self, scripts):
        self._scripts = scripts

    def get_llm(self, agent_id):
        return _FakeLLM(self._scripts[agent_id])


class _FakeSpan(object):
    def __init__(self):
        self.attributes, self.inputs, self.outputs = {}, {}, {}

    def append_trace(self, trace):
        self.appended = trace


class _FakeTrace(object):
    def __init__(self):
        self.spans = []

    def subspan(self, name):
        span = _FakeSpan()
        span.name = name
        self.spans.append(span)
        outer = self

        class _Ctx(object):
            def __enter__(self_inner):
                return span

            def __exit__(self_inner, *a):
                return False
        return _Ctx()


def _drain(gen):
    """Run a generator to completion; returns (yielded_items, return_value)."""
    items = []
    while True:
        try:
            items.append(next(gen))
        except StopIteration as stop:
            return items, stop.value


def _script(answer_text, status_event=True):
    chunks = [
        {"type": "event", "eventKind": "AGENT_BLOCK_START",
         "eventData": {"blockId": "resolve"}},
        {"type": "content", "text": answer_text},
    ]
    if status_event:
        chunks.append({"type": "event", "eventKind": "AGENT_RESULT",
                       "eventData": {"status": "ready", "rowCount": 1}})
    chunks.append({"type": "footer", "trace": {"usageMetadata": {
        "promptTokens": 10, "completionTokens": 5, "totalTokens": 15,
        "estimatedCost": 0.001}}})
    return chunks


def _caps_two_agents():
    base = {
        "kind": "agent", "domain": "revenue",
        "label_fr": "Agent A", "label_en": "Agent A",
        "planner_description": "d", "dataset_label_fr": "Base A",
        "dataset_label_en": "Base A", "dataset_ref": {},
        "block_labels": {"resolve": {"fr": "résolution", "en": "resolving"}},
        "tool_labels": {}, "enabled": True,
    }
    a = dict(base, agent_id="agent:AAA")
    b = dict(base, agent_id="agent:BBB", label_fr="Agent B", label_en="Agent B",
             dataset_label_fr="Base B", dataset_label_en="Base B")
    return {"cap_a": a, "cap_b": b}


class TestParallelFanOut(unittest.TestCase):

    def test_run_agent_step_blocking_collects_everything(self):
        import queue as q_mod
        out_q = q_mod.Queue()
        caps = _caps_two_agents()
        project = _FakeProject({"agent:AAA": _script("Réponse A")})
        step = {"kind": "agent", "capability": "cap_a", "instruction": "q?"}
        orch.MyLLM()._run_agent_step_blocking(project, 1, step, caps["cap_a"],
                                              "fr", "CTX", out_q)
        items = []
        while not out_q.empty():
            items.append(out_q.get_nowait())
        kinds = [k for k, _, _ in items]
        self.assertIn("event", kinds)
        self.assertEqual(kinds[-1], "done")
        done = items[-1][2]
        self.assertEqual(done["res"]["status"], "ok")
        self.assertEqual(done["res"]["output"], "Réponse A")
        self.assertEqual(done["res"]["agent_result"]["status"], "ready")
        self.assertIsNotNone(done["sub_trace"])
        # relayed sub-event got the human label + step index
        ev = [p for k, _, p in items if k == "event"][0]
        self.assertEqual(ev["chunk"]["eventKind"], "SUB_AGENT_AGENT_BLOCK_START")
        self.assertEqual(ev["chunk"]["eventData"]["stepIndex"], 1)
        self.assertIn("résolution", ev["chunk"]["eventData"]["label"])

    def test_run_agent_step_blocking_no_context_for_non_optin(self):
        import queue as q_mod
        out_q = q_mod.Queue()
        caps = _caps_two_agents()       # no pass_context flag
        scripts = {"agent:AAA": _script("A")}
        project = _FakeProject(scripts)
        step = {"kind": "agent", "capability": "cap_a", "instruction": "q?"}
        # capture messages via a wrapper completion
        llm = project.get_llm("agent:AAA")
        completion_holder = {}
        orig_new = llm.new_completion

        def capturing_new():
            c = orig_new()
            completion_holder["c"] = c
            return c
        llm.new_completion = capturing_new

        class _P(object):
            def get_llm(self, agent_id):
                return llm
        orch.MyLLM()._run_agent_step_blocking(_P(), 1, step, caps["cap_a"],
                                              "fr", "CTX", out_q)
        roles = [r for r, _ in completion_holder["c"].messages]
        self.assertNotIn("system", roles)

    def test_execute_steps_parallel_two_agents(self):
        caps = _caps_two_agents()
        project = _FakeProject({"agent:AAA": _script("Réponse A"),
                                "agent:BBB": _script("Réponse B",
                                                     status_event=False)})
        steps = [{"kind": "agent", "capability": "cap_a", "instruction": "qa"},
                 {"kind": "agent", "capability": "cap_b", "instruction": "qb"}]
        trace = _FakeTrace()
        total_usage = {"promptTokens": 0, "completionTokens": 0,
                       "totalTokens": 0, "estimatedCost": 0.0}
        gen = orch.MyLLM()._execute_steps_parallel(
            project, steps, caps, trace, "fr", "", total_usage, len(steps))
        items, results = _drain(gen)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["capability"], "cap_a")
        self.assertEqual(results[0]["output"], "Réponse A")
        self.assertEqual(results[1]["output"], "Réponse B")
        self.assertEqual(results[0]["agent_result"]["status"], "ready")
        self.assertIsNone(results[1]["agent_result"])

        events = [i["chunk"] for i in items
                  if isinstance(i, dict) and i["chunk"].get("type") == "event"]
        kinds = [e["eventKind"] for e in events]
        self.assertEqual(kinds.count("CALLING_AGENT"), 2)
        self.assertEqual(kinds.count("AGENT_DONE"), 2)
        # usage accumulated for both steps (10+5 twice)
        self.assertEqual(total_usage["totalTokens"], 30)
        # one post-hoc span per agent step, flagged parallel
        agent_spans = [s for s in trace.spans if s.name.startswith("step_")]
        self.assertEqual(len(agent_spans), 2)
        self.assertTrue(all(s.attributes.get("parallel") for s in agent_spans))

    def test_execute_steps_parallel_keeps_step_order_in_results(self):
        caps = _caps_two_agents()
        # B answers instantly, A is scripted the same way — order of results
        # must follow the PLAN order regardless of completion order.
        project = _FakeProject({"agent:AAA": _script("A"),
                                "agent:BBB": _script("B")})
        steps = [{"kind": "agent", "capability": "cap_b", "instruction": "qb"},
                 {"kind": "agent", "capability": "cap_a", "instruction": "qa"}]
        trace = _FakeTrace()
        total_usage = {"promptTokens": 0, "completionTokens": 0,
                       "totalTokens": 0, "estimatedCost": 0.0}
        gen = orch.MyLLM()._execute_steps_parallel(
            project, steps, caps, trace, "fr", "", total_usage, 2)
        _, results = _drain(gen)
        self.assertEqual(results[0]["capability"], "cap_b")
        self.assertEqual(results[1]["capability"], "cap_a")

    def test_failed_agent_is_error_not_crash(self):
        caps = _caps_two_agents()

        class _BoomProject(object):
            def get_llm(self, agent_id):
                if agent_id == "agent:AAA":
                    raise RuntimeError("boom")
                return _FakeLLM(_script("B"))
        steps = [{"kind": "agent", "capability": "cap_a", "instruction": "qa"},
                 {"kind": "agent", "capability": "cap_b", "instruction": "qb"}]
        trace = _FakeTrace()
        total_usage = {"promptTokens": 0, "completionTokens": 0,
                       "totalTokens": 0, "estimatedCost": 0.0}
        gen = orch.MyLLM()._execute_steps_parallel(
            _BoomProject(), steps, caps, trace, "fr", "", total_usage, 2)
        items, results = _drain(gen)
        self.assertEqual(results[0]["status"], "error")
        self.assertEqual(results[1]["status"], "ok")
        kinds = [i["chunk"]["eventKind"] for i in items
                 if isinstance(i, dict) and i["chunk"].get("type") == "event"]
        self.assertIn("ERROR", kinds)
        self.assertEqual(kinds.count("AGENT_DONE"), 2)


# ==========================================================================
# Sources / deterministic templates (v2.4 behaviour preserved)
# ==========================================================================
class TestDeterministicSurfaces(unittest.TestCase):

    def test_sources_block_uses_registry_labels(self):
        caps = _caps_two_agents()
        results = [{"status": "ok", "capability": "cap_a"},
                   {"status": "error", "capability": "cap_b"}]
        block = orch._sources_block(results, caps, "fr")
        self.assertIn("Base A", block)
        self.assertNotIn("Base B", block)

    def test_capability_gap_and_out_of_scope_templates(self):
        caps = {k: v for k, v in orch.CAPABILITIES.items() if v.get("enabled")}
        gap = orch.build_capability_gap_answer("tickets", caps, "fr")
        self.assertIn("tickets", gap)
        oos = orch.build_out_of_scope_answer(caps, "fr")
        self.assertIn("revenus", oos)


if __name__ == "__main__":
    unittest.main()
