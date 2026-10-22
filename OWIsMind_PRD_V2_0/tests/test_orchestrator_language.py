"""DSS-free tests for the orchestrator REPLY LANGUAGE rule and the Studio report
rules (V2.0 product-owner feedback, 2026-10-22).

Covered:
  - the fallback detector ``_detect_lang`` is a faithful mirror of the backend
    scorer ``owismind.agents.context.detect_prompt_language`` (same word lists,
    neutral nouns, suffix cues, regexes, threshold, and same verdicts on a corpus);
  - every language instruction of the orchestrator points at the ONE REPLY
    LANGUAGE rule (no "in the user's language", no "French when ...");
  - the STUDIO REPORT rules (themes, hero / pair alternation, KPI group of 3 or 4,
    90 to 140 word analyses, closing synthesis) in the embedded persona, the hub
    seed and the dev-harness mirror;
  - the dev-harness LiveTurn mirrors the language plumbing (userSuffix appended,
    machine tokens stripped, USER LANGUAGE pinned on the experts).
"""

import importlib.util
import os
import unittest

import _agent_stubs

_agent_stubs.install()

_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
_MIRROR_DIR = os.path.dirname(_TESTS_DIR)
_ORCH_PATH = os.path.join(_MIRROR_DIR, "GenAI", "Agents", "OWIsMind_orchestrator.py")
_CONTEXT_PATH = os.path.join(_MIRROR_DIR, "plugin", "owismind", "python-lib",
                             "owismind", "agents", "context.py")
_HARNESS_PATH = os.path.join(_MIRROR_DIR, "dev-harness", "mock", "live", "agents.mjs")
_SEED_PATH = os.path.join(_MIRROR_DIR, "project-library", "python", "owismind_hub",
                          "prompts", "orchestrator_persona.md")


def _load(mod_name, path):
    spec = importlib.util.spec_from_file_location(mod_name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


orch = _load("orchestrator_language_under_test", _ORCH_PATH)
ctx = _load("backend_context_under_test", _CONTEXT_PATH)

_CORPUS = (
    "What is the revenue trend?",
    "Quelle est l'évolution des revenus ?",
    "Analyse the revenue of EVPL vs budget for 2026",
    "Analyse le CA EVPL vs budget 2026",
    "show me the top 10 accounts by revenue",
    "montre-moi le top 10 des clients",
    "can't you add the forecast?",
    "c'est quoi le total 2025",
    "what's the budget",
    "revenue 2025 EMEA",
    "42",
    "ok",
    "",
    "Give me the revenue of the client in 2025 et le budget",
    "Peux-tu ajouter les tickets ouverts par sévérité",
    "management reporting pricing",
    "Je voudrais comprendre pourquoi les revenus baissent",
    "Why are revenues dropping since last quarter?",
)


class TestFallbackDetectorMirrorsBackend(unittest.TestCase):
    def test_same_constants(self):
        for name in ("_FR_WORDS", "_EN_WORDS", "_NEUTRAL_WORDS", "_FR_SUFFIXES",
                     "_EN_SUFFIXES", "_SUFFIX_MIN_LEN", "_SUFFIX_WEIGHT",
                     "LANG_MIN_CONFIDENCE"):
            self.assertEqual(getattr(orch, name), getattr(ctx, name), name)
        for name in ("_TOKEN_RE", "_APOSTROPHES_RE", "_FR_ACCENT_RE",
                     "_FR_ELISION_RE", "_EN_NEG_RE", "_EN_CONTRACTION_RE"):
            self.assertEqual(getattr(orch, name).pattern,
                             getattr(ctx, name).pattern, name)

    def test_same_verdicts(self):
        for text in _CORPUS:
            self.assertEqual(orch._detect_lang_scored(text),
                             ctx.detect_prompt_language_scored(text), text)
            for default in ("fr", "en"):
                self.assertEqual(orch._detect_lang(text, default=default),
                                 ctx.detect_prompt_language(text, default=default),
                                 (text, default))

    def test_token_wins_over_fallback(self):
        self.assertEqual(orch.parse_lang("What is it? ⟦owi:lang=fr⟧"), "fr")
        self.assertIsNone(orch.parse_lang("What is it?"))


class TestOneReplyLanguageRule(unittest.TestCase):
    def test_no_competing_language_wording(self):
        src = _read(_ORCH_PATH)
        self.assertNotIn("in the user's language", src)
        self.assertNotIn("French when", src)
        harness = _read(_HARNESS_PATH)
        self.assertNotIn("in the user's language", harness)
        self.assertNotIn("French when", harness)

    def test_persona_language_section(self):
        p = orch.PERSONA_DEFAULT
        for needle in ("# LANGUAGE (NON-NEGOTIABLE)", "NEVER the reply language",
                       "REPLY LANGUAGE is the language of the user's CURRENT",
                       "every tool argument", "only a tie-break",
                       "rewrite its words in the REPLY LANGUAGE",
                       "Never mix two languages"):
            self.assertIn(needle, p, needle)

    def test_system_prompt_restates_the_reply_language_last(self):
        for lang, label in (("en", "English"), ("fr", "French")):
            sp = orch.build_system_prompt(orch.CAPABILITIES, lang)
            tail = sp[sp.rindex("# REPLY LANGUAGE"):]
            self.assertIn("REPLY LANGUAGE = %s" % label, tail)
            self.assertIn("EVERY tool argument", tail)
            self.assertIn("web-app language", tail)

    def test_tool_specs_ask_for_the_reply_language(self):
        specs = {t["function"]["name"]: t["function"] for t in orch._ws_tool_specs()}
        plan = specs["write_plan"]["parameters"]["properties"]
        self.assertIn("REPLY LANGUAGE", plan["mission"]["description"])
        self.assertIn("REPLY LANGUAGE",
                      plan["steps"]["items"]["properties"]["label"]["description"])
        pub = specs["publish_widget"]
        self.assertIn("REPLY LANGUAGE", pub["description"])
        self.assertIn("REPLY LANGUAGE", pub["parameters"]["properties"]["text"]["description"])
        self.assertIn("REPLY LANGUAGE", orch.PROGRESS_TOOL_SPEC["function"]["description"])


_REPORT_NEEDLES = (
    "ONE SECTION PER BUSINESS THEME", "HERO", "PAIR", "ALTERNATE hero and pair",
    "never three sections of the same shape in a row",
    "a group of 3 or 4", "NEVER a single KPI", "the KPI row is EXPECTED",
    "Skip it only for a single-question analysis",
    "never republish a widget already on the board",
    "90 to 140 words", "headline sentence in bold", "business implication",
    "previous period, share of total, delta", "60 to 100 words",
    "the 2 or 3 decisions or watch points", "NEVER a table that duplicates a chart",
    "never two texts in a row except the closing synthesis",
    "at most 12 widgets", "3 to 6 lines",
)


class TestStudioReportRules(unittest.TestCase):
    def test_persona_report_rules(self):
        for needle in _REPORT_NEEDLES:
            self.assertIn(needle, orch.PERSONA_DEFAULT, needle)

    def test_hub_seed_carries_the_report_rules(self):
        seed = _read(_SEED_PATH)
        for needle in _REPORT_NEEDLES + ("# LANGUAGE (NON-NEGOTIABLE)",):
            self.assertIn(needle, seed, needle)

    def test_harness_mirrors_the_report_and_language_rules(self):
        harness = _read(_HARNESS_PATH)
        for needle in _REPORT_NEEDLES + ("LANGUAGE (NON-NEGOTIABLE)",
                                         "EARLIER TURNS ARE GROUNDED"):
            self.assertIn(needle, harness, needle)

    def test_harness_language_plumbing(self):
        harness = _read(_HARNESS_PATH)
        for needle in ("o.promptLang", "this.userSuffix", "stripTokens(",
                       "USER LANGUAGE: ${this.replyLang} - write any message "
                       "addressed to the user (clarification, no-data, "
                       "out-of-scope) in THIS language.",
                       "LABELS[this.replyLang]"):
            self.assertIn(needle, harness, needle)

    def test_no_dashes(self):
        for path in (_ORCH_PATH, _HARNESS_PATH, _SEED_PATH):
            text = _read(path)
            self.assertNotIn(chr(0x2014), text, path)
            self.assertNotIn(chr(0x2013), text, path)


if __name__ == "__main__":
    unittest.main()
