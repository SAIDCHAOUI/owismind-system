"""Reply-language detection (scored fr/en) and the end-of-message language rule.

The corpus is shared in spirit with dev-harness/mock/live/lang.test.mjs, which
checks the JS port gives the same answers as this module."""
import os, sys, unittest
from datetime import datetime
_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(_HERE, "..", "python-lib"))

from owismind.agents import context  # noqa: E402
from owismind.agents.context import (  # noqa: E402
    build_user_suffix, detect_prompt_language, detect_prompt_language_scored,
)

FRENCH = [
    "Quelle est l'évolution des revenus ?",
    "montre les revenus du client",
    "tu peux rajouter le forecast ?",
    "Peux-tu me faire une revue complète du chiffre d'affaires ?",
    "donne moi le top 10 des clients par revenu en 2025",
    "Compare les ACTUALS et le budget pour la phase 2",
    "pourquoi le CA baisse en mars ?",
    "affiche un graphique par mois",
    "merci",
    "Merci beaucoup !",
    "bonjour",
    "c'est quoi le total EMEA ?",
    "qu'est-ce qui explique cette hausse",
    "et pour l'année dernière ?",
    "ajoute les tickets ouverts",
    "combien de tickets sont encore ouverts ce mois-ci",
    "Fais une analyse détaillée des ventes",
    "explique moi ce widget",
    "je voudrais voir les clients en baisse",
    "Est-ce que tu peux comparer avec 2024 ?",
    "aujourd'hui",
    "svp",
]
ENGLISH = [
    "can you do for me a complete review of the revenues please ?",
    "What is the revenue trend?",
    "can you add the forecast?",
    "add the budget series",
    "show me the top 10 clients by revenue in 2025",
    "why did revenue drop in March?",
    "thanks",
    "Thank you!",
    "hello",
    "what's the total for EMEA?",
    "I'd like to see the open tickets",
    "compare ACTUALS with the budget for phase 2",
    "and for last year?",
    "explain this widget",
    "Give me a detailed breakdown of sales by region",
    "how many tickets are still open this month",
    "please",
    "don't include the cancelled deals",
    "Which customers are declining?",
    "let's look at the quarterly numbers",
]
# No language evidence at all: the web-app language (the default) decides.
NEUTRAL = ["42", "ok", "OK", "", "   ", "revenue 2025 EMEA", "revenus EVPL 2026",
           "ACTUALS budget total", "client phase 2", "?", "Q3 2025"]


class CorpusTests(unittest.TestCase):
    def test_french_corpus(self):
        for msg in FRENCH:
            with self.subTest(msg=msg):
                self.assertEqual(detect_prompt_language(msg, default="en"), "fr")

    def test_english_corpus(self):
        for msg in ENGLISH:
            with self.subTest(msg=msg):
                self.assertEqual(detect_prompt_language(msg, default="fr"), "en")

    def test_neutral_falls_back_to_default(self):
        for msg in NEUTRAL:
            with self.subTest(msg=msg):
                self.assertEqual(detect_prompt_language(msg, default="en"), "en")
                self.assertEqual(detect_prompt_language(msg, default="fr"), "fr")
                self.assertEqual(detect_prompt_language_scored(msg)[1], 0.0)

    def test_failing_harness_sentence_is_confident_english(self):
        lang, conf = detect_prompt_language_scored(
            "can you do for me a complete review of the revenues please ?")
        self.assertEqual(lang, "en")
        self.assertGreater(conf, 0.9)

    def test_unknown_default_falls_back_to_french(self):
        self.assertEqual(detect_prompt_language("42", default="zz"), "fr")
        self.assertEqual(detect_prompt_language("42", default=None), "fr")

    def test_none_message(self):
        self.assertEqual(detect_prompt_language(None, default="en"), "en")


class MixedTests(unittest.TestCase):
    def test_majority_wins(self):
        # 3 English function words vs 1 French one.
        self.assertEqual(detect_prompt_language("show me the revenus par region for 2025",
                                                default="fr"), "en")
        # Mostly French with an English business word.
        self.assertEqual(detect_prompt_language("tu peux faire le reporting du forecast ?",
                                                default="en"), "fr")

    def test_tie_falls_back(self):
        # "montre" (fr) vs "the" (en): a tie -> the web-app language.
        self.assertEqual(detect_prompt_language("montre the revenue", default="en"), "en")
        self.assertEqual(detect_prompt_language("montre the revenue", default="fr"), "fr")

    def test_business_nouns_have_no_weight(self):
        for word in ("revenue", "revenu", "revenues", "revenus", "client", "budget",
                     "total", "phase", "ACTUALS", "reporting", "management"):
            with self.subTest(word=word):
                self.assertEqual(detect_prompt_language_scored(word), ("fr", 0.0))

    def test_lone_suffix_cue_never_decides(self):
        # A single 0.5 suffix cue ("valeur", "growing") is below the threshold.
        self.assertEqual(detect_prompt_language("valeur 2025", default="en"), "en")
        self.assertEqual(detect_prompt_language("growing 2025", default="fr"), "fr")

    def test_typographic_apostrophe(self):
        self.assertEqual(detect_prompt_language("l’évolution", default="en"), "fr")
        self.assertEqual(detect_prompt_language("what’s up", default="fr"), "en")

    def test_word_lists_are_disjoint(self):
        self.assertFalse(context._FR_WORDS & context._EN_WORDS)
        self.assertFalse(context._FR_WORDS & context._NEUTRAL_WORDS)
        self.assertFalse(context._EN_WORDS & context._NEUTRAL_WORDS)
        for shared in ("a", "an", "as", "but", "me", "on", "or", "son", "plus", "dont", "compare"):
            self.assertNotIn(shared, context._FR_WORDS | context._EN_WORDS)


class SuffixLanguageRuleTests(unittest.TestCase):
    NOW = datetime(2026, 6, 9, 14, 30)

    def test_rule_names_language_and_covers_tool_arguments(self):
        s = build_user_suffix("X", self.NOW, webapp_lang="fr", prompt_lang="en")
        last = s.splitlines()[-1]
        self.assertTrue(last.startswith("IMPORTANT - reply in English"))
        self.assertIn("EVERYTHING in English", last)
        for part in ("chat reply", "every tool argument", "plan steps", "widget titles",
                     "subtitles", "texts", "scope"):
            self.assertIn(part, last)
        self.assertIn("The web-app language (French) is NOT the reply language.", last)
        self.assertIn("priority over earlier turns", last)

    def test_same_languages_rule(self):
        s = build_user_suffix("X", self.NOW, webapp_lang="fr", prompt_lang="fr")
        last = s.splitlines()[-1]
        self.assertIn("reply in French", last)
        self.assertIn("The web-app language never sets the reply language.", last)
        self.assertNotIn("is NOT the reply language", last)

    def test_header_format_unchanged(self):
        s = build_user_suffix("Said Chaoui", self.NOW, webapp_lang="en", prompt_lang="fr",
                              mode="smart")
        self.assertEqual(
            s.splitlines()[2],
            "[Context - User: Said Chaoui · Today: Tuesday, June 09, 2026 at 14:30 · "
            "Web app language: English] ⟦owi:mode=smart⟧⟦owi:lang=fr⟧")
        self.assertTrue(s.startswith("\n\n[Context - "))
        self.assertEqual(len(s.splitlines()), 4)

    def test_no_rule_without_prompt_lang(self):
        s = build_user_suffix("X", self.NOW, webapp_lang="fr")
        self.assertNotIn("IMPORTANT", s)
        self.assertNotIn("owi:lang", s)

    def test_orchestrator_strip_pattern_removes_the_whole_block(self):
        # Mirror of the orchestrator's _CTX_BLOCK_RE: the rule line must go with it.
        import re
        ctx_re = re.compile(
            r"\n\n\[(?:ON SCREEN NOW|PRIOR DATA|CURRENT STUDIO|Context -).*\Z", re.DOTALL)
        msg = "can you review the revenues?"
        s = msg + build_user_suffix("X", self.NOW, webapp_lang="fr", prompt_lang="en",
                                    mode="pro")
        self.assertEqual(ctx_re.sub("", s), msg)


if __name__ == "__main__":
    unittest.main()
