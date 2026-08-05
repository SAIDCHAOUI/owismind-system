"""AG-01a (audit 2026-08-05): the revenue engine is THE single source and the
generator can rebind everything domain-specific: the CONFIG constants
(HUB_DOMAIN included), the deploy-header identity lines, and the delimited
domain-wording regions (the revenue offer-hierarchy vocabulary).

The core guarantee tested here: regenerating with the engine's OWN revenue
values and no overrides yields the engine byte-for-byte (generated banner
aside). That proves the whole mechanism is strictly neutral for the live
revenue agent - the precondition before the tickets file can ever be
regenerated from the engine (separate FUNCTIONAL ticket: it applies the
engine's behavior fixes to the tickets domain).
"""

import os
import sys
import unittest

_HERE = os.path.dirname(os.path.abspath(__file__))
_MIRROR = os.path.dirname(_HERE)
_LIB = os.path.join(_MIRROR, "project-library", "python")
if _LIB not in sys.path:
    sys.path.insert(0, _LIB)

from owismind_factory import agent_builder  # noqa: E402
from owismind_factory.spec import DomainSpec  # noqa: E402

_ENGINE_PATH = os.path.join(_MIRROR, "GenAI", "Agents",
                            "SalesDrive_revenue_expert.py")


def _revenue_spec():
    return DomainSpec(domain="revenue", base_dataset="DRIVE_Revenues",
                      label_fr="Expert revenus", label_en="Revenue expert")


def _other_spec():
    return DomainSpec(domain="satisfaction", base_dataset="CX_Surveys",
                      label_fr="Expert satisfaction",
                      label_en="Satisfaction expert")


class TestEngineRegeneration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(_ENGINE_PATH) as f:
            cls.engine = f.read()

    def test_revenue_regeneration_is_byte_identical(self):
        # Regenerating with the engine's own values must change NOTHING: the
        # output is exactly the generated banner + the engine, byte for byte.
        code = agent_builder.generate_subagent_code(
            self.engine, _revenue_spec(), "v4oqA6R")
        self.assertTrue(code.endswith(self.engine),
                        "regeneration with the revenue values altered the "
                        "engine body: the generator is no longer neutral")
        self.assertLess(len(code) - len(self.engine), 600)  # banner only

    def test_hub_domain_rebinds_for_a_new_domain(self):
        code = agent_builder.generate_subagent_code(
            self.engine, _other_spec(), "toolX")
        self.assertIn('HUB_DOMAIN = "satisfaction"', code)
        self.assertNotIn('HUB_DOMAIN = "revenue"', code)

    def test_header_identity_rewritten_only_when_agent_ref_given(self):
        code = agent_builder.generate_subagent_code(
            self.engine, _other_spec(), "toolX",
            deploy_project="PKEY", agent_ref="agent:AbC123xy")
        self.assertIn("# Code Agent: Satisfaction_expert = AbC123xy", code)
        self.assertIn("# DEPLOY TARGET: project PKEY", code)
        self.assertNotIn("SalesDrive_revenue_expert = bHrWLyOL", code)
        # Without agent_ref the header keeps the engine identity (historical
        # behavior, exercised by every existing caller).
        code2 = agent_builder.generate_subagent_code(
            self.engine, _other_spec(), "toolX")
        self.assertIn("# Code Agent: SalesDrive_revenue_expert = bHrWLyOL", code2)

    def test_every_wording_region_exists_exactly_once(self):
        for key in agent_builder.WORDING_KEYS:
            self.assertEqual(
                self.engine.count("# [DOMAIN-WORDING:%s]" % key), 1, key)
            self.assertEqual(
                self.engine.count("# [/DOMAIN-WORDING:%s]" % key), 1, key)

    def test_wording_region_is_replaceable(self):
        replacement = '            parts.append("NEUTRAL GUIDANCE")\n'
        code = agent_builder.generate_subagent_code(
            self.engine, _other_spec(), "toolX",
            wording={"enumerate_guidance": replacement})
        self.assertIn('parts.append("NEUTRAL GUIDANCE")', code)
        self.assertNotIn("sales channel + an offer", code)
        # The markers survive so a regenerated file stays regenerable.
        self.assertIn("# [DOMAIN-WORDING:enumerate_guidance]", code)

    def test_unknown_wording_key_is_refused(self):
        with self.assertRaises(ValueError):
            agent_builder.generate_subagent_code(
                self.engine, _other_spec(), "toolX", wording={"nope": "x"})

    def test_wording_drift_guard(self):
        broken = (self.engine
                  + "\n# [DOMAIN-WORDING:disclose_note]\nX = 1\n"
                    "# [/DOMAIN-WORDING:disclose_note]\n")
        with self.assertRaises(agent_builder.TemplateDriftError):
            agent_builder.generate_subagent_code(
                broken, _other_spec(), "toolX",
                wording={"disclose_note": "DISCLOSE_NOTE = {}\n"})


if __name__ == "__main__":
    unittest.main()
