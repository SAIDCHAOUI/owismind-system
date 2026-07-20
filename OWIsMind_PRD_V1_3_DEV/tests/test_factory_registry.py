"""Anti-drift tests: config hub <-> orchestrator embedded defaults <-> factory.

Three sources must stay identical or the hub override would silently change
behavior:
- the orchestrator's embedded CAPABILITIES_DEFAULT / PERSONA_DEFAULT,
- the hub seed files (OWIsMind_PRD_V1_3_DEV/project-library/owismind_hub/), pushed by 01_push_config_hub.py,
- the validators (owismind_factory.hub.REQUIRED_CAPABILITY_KEYS vs the
  orchestrator's _HUB_REQUIRED_CAPABILITY_KEYS) and the frozen dialect tuples.

DSS-free: the orchestrator constants are extracted from the SOURCE with ast
(no import of dataiku/langgraph needed).
"""

import ast
import json
import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MIRROR = os.path.dirname(_HERE)
_ORCH = os.path.join(_MIRROR, "GenAI", "Agents", "OWIsMind_orchestrator.py")
_HUB_DIR = os.path.join(_MIRROR, "project-library", "owismind_hub")
_LIB = os.path.join(_MIRROR, "project-library", "python")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from owismind_factory import hub, registry  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402


def _extract_constants(path, names):
    """ast-extract module-level literal assignments from a source file."""
    tree = ast.parse(open(path).read())
    found = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name in names:
                found[name] = ast.literal_eval(node.value)
    return found


class TestHubOrchestratorEquivalence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orch = _extract_constants(_ORCH, {
            "CAPABILITIES_DEFAULT", "PERSONA_DEFAULT",
            "_HUB_REQUIRED_CAPABILITY_KEYS",
            "_HUB_KNOWN_BLOCK_IDS", "_HUB_KNOWN_TOOL_NAMES",
        })

    def test_all_constants_extracted(self):
        for name in ("CAPABILITIES_DEFAULT", "PERSONA_DEFAULT",
                     "_HUB_REQUIRED_CAPABILITY_KEYS",
                     "_HUB_KNOWN_BLOCK_IDS", "_HUB_KNOWN_TOOL_NAMES"):
            self.assertIn(name, self.orch, "orchestrator constant %s missing" % name)

    def test_required_keys_match_factory(self):
        self.assertEqual(tuple(self.orch["_HUB_REQUIRED_CAPABILITY_KEYS"]),
                         tuple(hub.REQUIRED_CAPABILITY_KEYS))

    def test_frozen_dialect_matches_factory(self):
        self.assertEqual(tuple(self.orch["_HUB_KNOWN_BLOCK_IDS"]),
                         tuple(registry.KNOWN_BLOCK_IDS))
        self.assertEqual(tuple(self.orch["_HUB_KNOWN_TOOL_NAMES"]),
                         tuple(registry.KNOWN_TOOL_NAMES))

    def test_hub_capabilities_seed_equals_embedded_default(self):
        seed = json.load(open(os.path.join(_HUB_DIR, "capabilities.json")))
        self.assertEqual(seed, self.orch["CAPABILITIES_DEFAULT"])

    def test_hub_persona_seed_equals_embedded_default(self):
        seed = open(os.path.join(_HUB_DIR, "prompts", "orchestrator_persona.md")).read()
        self.assertEqual(seed, self.orch["PERSONA_DEFAULT"])

    def test_seed_passes_factory_validation(self):
        seed = json.load(open(os.path.join(_HUB_DIR, "capabilities.json")))
        self.assertEqual(hub.validate_capabilities(seed), [])

    def test_embedded_entries_carry_all_required_keys(self):
        for key, cap in self.orch["CAPABILITIES_DEFAULT"].items():
            for req in hub.REQUIRED_CAPABILITY_KEYS:
                self.assertIn(req, cap, "%s misses %s" % (key, req))

    def test_embedded_entries_use_frozen_label_keys(self):
        for key, cap in self.orch["CAPABILITIES_DEFAULT"].items():
            self.assertEqual(set(cap["block_labels"].keys()),
                             set(registry.KNOWN_BLOCK_IDS), key)
            self.assertEqual(set(cap["tool_labels"].keys()),
                             set(registry.KNOWN_TOOL_NAMES), key)


class TestFactoryEntryCompatibility(unittest.TestCase):
    """A factory-generated entry must satisfy BOTH validators."""

    def setUp(self):
        self.spec = DomainSpec(domain="satisfaction", base_dataset="CX_Surveys",
                               label_fr="Expert satisfaction", label_en="Satisfaction expert")
        self.entry = registry.capability_entry(self.spec, "agent:AbCd1234")

    def test_passes_factory_validation(self):
        self.assertEqual(hub.validate_capabilities({"satisfaction_expert": self.entry}), [])

    def test_ships_disabled(self):
        self.assertFalse(self.entry["enabled"])

    def test_appending_to_seed_stays_valid(self):
        seed = json.load(open(os.path.join(_HUB_DIR, "capabilities.json")))
        seed["satisfaction_expert"] = self.entry
        self.assertEqual(hub.validate_capabilities(seed), [])

    def test_second_enabled_capability_per_domain_rejected(self):
        seed = json.load(open(os.path.join(_HUB_DIR, "capabilities.json")))
        clone = json.loads(json.dumps(seed["revenue_expert"]))
        seed["revenue_expert_v2"] = clone  # same domain, also enabled
        problems = hub.validate_capabilities(seed)
        self.assertTrue(any("already has an enabled capability" in p for p in problems))


def _extract_orchestrator_validator():
    """Compile the orchestrator's REAL _hub_capabilities_problems (via ast).

    Executing the actual source (not a re-implementation) is what makes the
    validator-equivalence test meaningful.
    """
    with open(_ORCH) as f:
        source = f.read()
    tree = ast.parse(source)
    namespace = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in ("_HUB_REQUIRED_CAPABILITY_KEYS",
                                           "_HUB_KNOWN_BLOCK_IDS",
                                           "_HUB_KNOWN_TOOL_NAMES"):
            namespace[node.targets[0].id] = ast.literal_eval(node.value)
        if isinstance(node, ast.FunctionDef) and node.name == "_hub_capabilities_problems":
            segment = ast.get_source_segment(source, node)
            exec(segment, namespace)  # noqa: S102 - our own source, test only
    return namespace["_hub_capabilities_problems"]


class TestValidatorsAgree(unittest.TestCase):
    """The factory validator and the orchestrator's loader validator must give
    the SAME verdict on the same input, and the orchestrator's must NEVER raise
    (a crash at agent import would be a hard outage: adversarial finding 1)."""

    @classmethod
    def setUpClass(cls):
        cls.orch_validate = staticmethod(_extract_orchestrator_validator())
        with open(os.path.join(_HUB_DIR, "capabilities.json")) as f:
            cls.seed = json.load(f)

    def _entry(self, **overrides):
        entry = json.loads(json.dumps(self.seed["revenue_expert"]))
        entry.update(overrides)
        return entry

    def _cases(self):
        return {
            "valid_seed": self.seed,
            "block_labels_none": {"x": self._entry(block_labels=None)},
            "block_labels_list": {"x": self._entry(block_labels=["resolve"])},
            "block_labels_wrong_keys": {"x": self._entry(block_labels={"foo": "bar"})},
            "block_labels_extra_key": {"x": self._entry(
                block_labels=dict(self.seed["revenue_expert"]["block_labels"], extra={"fr": "x", "en": "x"}))},
            "tool_labels_subset": {"x": self._entry(tool_labels={"resolve_filter_value": {"fr": "a", "en": "b"}})},
            "bad_agent_id": {"x": self._entry(agent_id="bHrWLyOL")},
            "dup_enabled_domain": {"a": self._entry(), "b": self._entry()},
            "non_dict_entry": {"x": 42},
            "empty": {},
        }

    def test_same_verdict_and_no_crash(self):
        for name, case in self._cases().items():
            try:
                orch_problems = self.orch_validate(case)
            except Exception as exc:  # noqa: BLE001 - the assertion IS the point
                self.fail("orchestrator validator RAISED on %r: %s (must return problems)"
                          % (name, exc))
            factory_problems = hub.validate_capabilities(case)
            self.assertEqual(bool(orch_problems), bool(factory_problems),
                             "validators disagree on %r: orchestrator=%s factory=%s"
                             % (name, orch_problems[:2], factory_problems[:2]))

    def test_only_valid_seed_accepted(self):
        cases = self._cases()
        self.assertEqual(hub.validate_capabilities(cases["valid_seed"]), [])
        for name, case in cases.items():
            if name != "valid_seed":
                self.assertTrue(hub.validate_capabilities(case),
                                "factory validator should reject %r" % name)


class TestSubAgentHubBlocks(unittest.TestCase):
    """The two specialists carry the additive hub loader with the right domain."""

    def _source(self, filename):
        with open(os.path.join(_MIRROR, "GenAI", "Agents", filename)) as f:
            return f.read()

    def test_revenue_hub_domain(self):
        src = self._source("SalesDrive_revenue_expert.py")
        self.assertIn('HUB_DOMAIN = "revenue"', src)
        self.assertIn("_build_understand_prompt_base", src)
        self.assertIn("ADDITIONAL TEAM RULES", src)

    def test_tickets_hub_domain(self):
        src = self._source("CSSO_Trouble_Tickets_Expert.py")
        self.assertIn('HUB_DOMAIN = "tickets"', src)
        self.assertIn("_build_understand_prompt_base", src)
        self.assertIn("ADDITIONAL TEAM RULES", src)

    def test_orchestrator_resolves_capabilities(self):
        src = self._source("OWIsMind_orchestrator.py")
        self.assertIn("CAPABILITIES = CAPABILITIES_DEFAULT", src)
        self.assertIn("_load_hub_capabilities", src)
        self.assertIn("PERSONA = _load_hub_persona() or PERSONA_DEFAULT", src)


if __name__ == "__main__":
    unittest.main()
