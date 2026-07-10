"""Anti-drift tests: config hub <-> orchestrator embedded defaults <-> factory.

Three sources must stay identical or the hub override would silently change
behavior:
- the orchestrator's embedded CAPABILITIES_DEFAULT / PERSONA_DEFAULT,
- the hub seed files (OWIsMind_PRD_V1_2/hub/), pushed by 01_push_config_hub.py,
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
_ORCH = os.path.join(_MIRROR, "agents", "OWIsMind_orchestrator.py")
_HUB_DIR = os.path.join(_MIRROR, "hub")
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


class TestSubAgentHubBlocks(unittest.TestCase):
    """The two specialists carry the additive hub loader with the right domain."""

    def _source(self, filename):
        return open(os.path.join(_MIRROR, "agents", filename)).read()

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
