# Orchestrator "Expert Authority" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the orchestrator structurally unable to assert a business fact it didn't get from a sub-agent, and turn its registry into a generic manifest so adding an expert = one entry - fixing the "budget 2026 → false denial" class of bugs at the root.

**Architecture:** One LLM plan call decides routing (unchanged cost). The orchestrator may only author (a) routing, (b) a deterministic "I have no agent for that domain" template, (c) a deterministic out-of-scope redirect, (d) bounded greeting/clarify/concept text - none of which can carry a business figure. A domain map distinguishes "real domain, no agent" (honest gap) from "non-OWI" (out of scope). An anti-drift test keeps the revenue manifest truthful against the sub-agent's own constants.

**Tech Stack:** Python 3.9 (standalone DSS Code Agent file, stdlib + `dataiku` only), `unittest` (DSS-free, `dataiku` stubbed via `importlib`).

**Spec:** `docs/superpowers/specs/2026-06-11-orchestrator-expert-authority-design.md`

**Conventions (verified):**
- All changes live in `orchestrator/orchestrator_agent.py` + its tests. The frontend keys on the frozen `eventKind` (`DIRECT_ANSWER`), NOT on the `intent` value → no UI change.
- Tests cover PURE functions only; the LLM routing *behaviour* is validated on the DSS instance (noted per task).
- Run tests from repo root: `python3 -m unittest discover -s orchestrator/tests -v`. Single test: append `-k <pattern>`.
- Commits: per task, never push. End every commit message with the `Co-Authored-By:` trailer (see steps).
- After all tasks: the orchestrator file is re-pasted into its DSS Code Agent (Task 8).

---

### Task 1: Business domain map + `staffed_domains` helper + `domain` field on the registry

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (registry section, after `get_capabilities()` ~L254)
- Test: `orchestrator/tests/test_orchestrator_agent.py`

- [ ] **Step 1: Write the failing test**

Add to `orchestrator/tests/test_orchestrator_agent.py`, and add `"domain": "revenue"` to the shared `CAPS["rev"]` fixture (insert the key next to `"enabled": True,` on `rev`):

```python
# ==========================================================================
# BUSINESS_DOMAINS + staffed_domains
# ==========================================================================
class DomainMapTests(unittest.TestCase):

    def test_domain_map_has_core_domains(self):
        for dom in ("revenue", "tickets", "satisfaction",
                    "opportunities", "delivery", "billing"):
            self.assertIn(dom, orc.BUSINESS_DOMAINS)
            self.assertIn("fr", orc.BUSINESS_DOMAINS[dom])
            self.assertIn("en", orc.BUSINESS_DOMAINS[dom])

    def test_staffed_domains_from_enabled_agents(self):
        self.assertEqual(orc.staffed_domains(CAPS), {"revenue"})

    def test_staffed_domains_ignores_tools_and_unstaffed(self):
        caps = {"clock": CAPS["clock"]}  # tool only, no agent
        self.assertEqual(orc.staffed_domains(caps), set())
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k Domain`
Expected: FAIL - `AttributeError: module ... has no attribute 'BUSINESS_DOMAINS'`

- [ ] **Step 3: Write minimal implementation**

In `orchestrator/orchestrator_agent.py`, immediately AFTER the `get_capabilities()` function (~L254) add:

```python
# Business domains the product knows about, with display labels. A domain is
# "staffed" when at least one ENABLED agent capability declares it via "domain".
# The planner uses this map to tell apart a real-but-unstaffed domain
# (-> CAPABILITY_GAP, honest) from a clearly non-OWI question (-> OUT_OF_SCOPE).
# Adding an agent later = give its registry entry the matching "domain"; the gap
# closes with NO prompt change. Names only - never a business value (rule P3).
BUSINESS_DOMAINS = {
    "revenue":       {"fr": "revenus / CA / budget / forecast",       "en": "revenue / billing / budget / forecast"},
    "tickets":       {"fr": "tickets d'incidents",                    "en": "incident tickets"},
    "satisfaction":  {"fr": "satisfaction / expérience client",       "en": "customer satisfaction / experience"},
    "opportunities": {"fr": "opportunités / pipeline",                "en": "opportunities / pipeline"},
    "delivery":      {"fr": "livraison (LD / SOF / déconnexions)",     "en": "delivery (LD / SOF / disconnections)"},
    "billing":       {"fr": "facturation",                            "en": "billing"},
}


def staffed_domains(caps):
    """Set of business domains covered by at least one enabled agent capability."""
    return {v["domain"] for v in caps.values()
            if v.get("kind") == "agent" and v.get("domain")}
```

Then add `"domain": "revenue",` to BOTH revenue registry entries (`"salesdrive"` ~L190 and `"salesdrive_v2"` ~L236), next to their existing `"enabled"` key.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k Domain`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): business domain map + staffed_domains + domain field\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 2: Deterministic templates - capability-gap & out-of-scope (no business-fact surface)

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (UX texts ~after L312; builders in helpers ~after `_build_capabilities_answer` L787)
- Test: `orchestrator/tests/test_orchestrator_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# ==========================================================================
# Deterministic non-business templates (R1/R2 firewall)
# ==========================================================================
class DeterministicTemplateTests(unittest.TestCase):

    def test_available_domains_phrase_lists_staffed_labels(self):
        phrase = orc._available_domains_phrase(CAPS, "fr")
        self.assertIn("revenus", phrase)

    def test_capability_gap_names_domain_and_offers_alternative(self):
        text = orc.build_capability_gap_answer("tickets", CAPS, "fr")
        self.assertIn("tickets d'incidents", text)   # the missing domain, named
        self.assertIn("revenus", text)               # what I CAN do
        # R1/R2: a gap message must never assert a figure or a zero.
        self.assertNotIn("0", text)
        self.assertFalse(any(ch.isdigit() for ch in text))

    def test_capability_gap_unknown_domain_falls_back_generic(self):
        text = orc.build_capability_gap_answer(None, CAPS, "en")
        self.assertIn("revenue", text)
        self.assertFalse(any(ch.isdigit() for ch in text))

    def test_out_of_scope_redirects_without_business_claim(self):
        text = orc.build_out_of_scope_answer(CAPS, "en")
        self.assertIn("revenue", text)
        self.assertFalse(any(ch.isdigit() for ch in text))
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k DeterministicTemplate`
Expected: FAIL - `AttributeError: ... '_available_domains_phrase'`

- [ ] **Step 3: Write minimal implementation**

Add the template texts AFTER `ALL_STEPS_FAILED` (~L312):

```python
# --- Deterministic non-business templates (R1/R2: no business-fact surface) ---
CAPABILITY_GAP_TEXT = {
    "fr": "Je n'ai pas encore d'agent pour {domain}, donc je préfère ne rien inventer. "
          "En revanche, je peux vous aider sur : {available}.",
    "en": "I don't have an agent for {domain} yet, so I won't make anything up. "
          "I can however help you with: {available}.",
}
CAPABILITY_GAP_GENERIC = {
    "fr": "Je n'ai pas encore d'agent pour répondre à ça, et je ne vais pas inventer. "
          "Je peux vous aider sur : {available}.",
    "en": "I don't have an agent for that yet, and I won't make anything up. "
          "I can help you with: {available}.",
}
OUT_OF_SCOPE_REDIRECT = {
    "fr": "Ça sort un peu de mon terrain de jeu 🙂 Je suis spécialisé dans les données métier OWI. "
          "Je peux vous aider sur : {available}.",
    "en": "That's a bit outside my playground 🙂 I focus on OWI business data. "
          "I can help you with: {available}.",
}
```

Add the builders AFTER `_build_capabilities_answer` (~L787):

```python
def _available_domains_phrase(caps, lang):
    """Comma-joined labels of the staffed business domains (registry-sourced,
    deterministic). Falls back to the agent capability labels if no domain is
    declared. Pure - never emits a business value."""
    labels = []
    for dom in sorted(staffed_domains(caps)):
        lab = BUSINESS_DOMAINS.get(dom, {})
        text = lab.get(lang) or lab.get("fr")
        if text and text not in labels:
            labels.append(text)
    if not labels:
        for v in caps.values():
            if v.get("kind") == "agent":
                text = v.get("label_%s" % lang) or v.get("label_fr")
                if text and text not in labels:
                    labels.append(text)
    return ", ".join(labels)


def build_capability_gap_answer(domain, caps, lang):
    """Honest 'I have no agent for <domain>' message (R2), built from the
    registry - never an LLM free-text and never a figure."""
    available = _available_domains_phrase(caps, lang)
    dom = BUSINESS_DOMAINS.get(domain or "", {})
    dom_label = dom.get(lang) or dom.get("fr")
    if not dom_label:
        return CAPABILITY_GAP_GENERIC[lang].format(available=available)
    return CAPABILITY_GAP_TEXT[lang].format(domain=dom_label, available=available)


def build_out_of_scope_answer(caps, lang):
    """Deterministic out-of-scope redirect - no business assertion surface."""
    return OUT_OF_SCOPE_REDIRECT[lang].format(available=_available_domains_phrase(caps, lang))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k DeterministicTemplate`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): deterministic capability-gap & out-of-scope templates\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 3: `render_non_business_text` - the testable firewall router

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (helpers, after `build_out_of_scope_answer`)
- Test: `orchestrator/tests/test_orchestrator_agent.py`

- [ ] **Step 1: Write the failing test**

```python
# ==========================================================================
# render_non_business_text - routes each non-BUSINESS intent to safe text
# ==========================================================================
class RenderNonBusinessTests(unittest.TestCase):

    def test_capability_gap_uses_template(self):
        plan = {"domain": "tickets"}
        text = orc.render_non_business_text("CAPABILITY_GAP", plan, CAPS, "fr")
        self.assertIn("tickets d'incidents", text)
        self.assertFalse(any(ch.isdigit() for ch in text))

    def test_out_of_scope_uses_redirect(self):
        text = orc.render_non_business_text("OUT_OF_SCOPE", {}, CAPS, "en")
        self.assertIn("playground", text)

    def test_greeting_relays_direct_answer(self):
        plan = {"direct_answer": "Bonjour Said !"}
        self.assertEqual(
            orc.render_non_business_text("GREETING", plan, CAPS, "fr"),
            "Bonjour Said !")

    def test_concept_relays_direct_answer(self):
        plan = {"direct_answer": "SS7 is legacy signalling; LTE Diameter is its IP successor."}
        text = orc.render_non_business_text("CONCEPT", plan, CAPS, "en")
        self.assertIn("LTE Diameter", text)

    def test_clarify_empty_direct_answer_falls_back(self):
        text = orc.render_non_business_text("CLARIFY", {}, CAPS, "fr")
        self.assertEqual(text, orc.PLANNER_FALLBACK_CLARIFY["fr"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k RenderNonBusiness`
Expected: FAIL - `AttributeError: ... 'render_non_business_text'`

- [ ] **Step 3: Write minimal implementation**

Add AFTER `build_out_of_scope_answer`:

```python
def render_non_business_text(intent, plan, caps, lang):
    """Pure text for a non-BUSINESS, non-CAPABILITIES intent (CAPABILITIES streams
    via its own LLM path). CAPABILITY_GAP / OUT_OF_SCOPE -> deterministic registry
    templates (no business-fact surface, R1/R2). GREETING / CLARIFY / CONCEPT ->
    the bounded planner direct_answer, or the clarify fallback when empty."""
    if intent == "CAPABILITY_GAP":
        return build_capability_gap_answer(plan.get("domain"), caps, lang)
    if intent == "OUT_OF_SCOPE":
        return build_out_of_scope_answer(caps, lang)
    return (plan.get("direct_answer") or "").strip() or PLANNER_FALLBACK_CLARIFY[lang]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k RenderNonBusiness`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): pure render_non_business_text firewall router\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 4: `_validate_plan` + schema - accept `CAPABILITY_GAP` / `CONCEPT` and the `domain` field

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (`PLANNER_JSON_SCHEMA` ~L364; `_validate_plan` ~L1205)
- Test: `orchestrator/tests/test_orchestrator_agent.py`

- [ ] **Step 1: Write the failing test**

Add to the existing `ValidatePlanTests` class:

```python
    def test_capability_gap_intent_accepted_with_domain(self):
        plan = self._validate({"intent": "CAPABILITY_GAP", "language": "fr",
                               "domain": "tickets"})
        self.assertIsNotNone(plan)
        self.assertEqual(plan["intent"], "CAPABILITY_GAP")
        self.assertEqual(plan["domain"], "tickets")

    def test_capability_gap_unknown_domain_nulled(self):
        plan = self._validate({"intent": "CAPABILITY_GAP", "language": "fr",
                               "domain": "astrology"})
        self.assertIsNone(plan["domain"])

    def test_concept_intent_accepted(self):
        plan = self._validate({"intent": "CONCEPT", "language": "en",
                               "direct_answer": "SS7 vs LTE general explanation."})
        self.assertEqual(plan["intent"], "CONCEPT")

    def test_capability_gap_purges_steps(self):
        plan = self._validate({"intent": "CAPABILITY_GAP", "language": "fr",
                               "domain": "tickets", "steps": [_business_step()]})
        self.assertEqual(plan["steps"], [])

    def test_business_plan_has_null_domain_by_default(self):
        plan = self._validate({"intent": "BUSINESS", "language": "fr",
                               "steps": [_business_step()]})
        self.assertIsNone(plan["domain"])
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k ValidatePlan`
Expected: FAIL - `CONCEPT`/`CAPABILITY_GAP` rejected (returns None) and/or `KeyError: 'domain'`

- [ ] **Step 3: Write minimal implementation**

In `PLANNER_JSON_SCHEMA` (~L364) change the `intent` enum and add a `domain` property:

```python
        "intent": {"type": "string",
                   "enum": ["BUSINESS", "GREETING", "CAPABILITIES", "CLARIFY",
                            "OUT_OF_SCOPE", "CAPABILITY_GAP", "CONCEPT"]},
        "domain": {"type": "string"},
```

In `_validate_plan` (~L1205) replace the intent guard and the returned dict:

```python
        intent = parsed.get("intent")
        if intent not in ("BUSINESS", "GREETING", "CAPABILITIES", "CLARIFY",
                          "OUT_OF_SCOPE", "CAPABILITY_GAP", "CONCEPT"):
            return None
```

and, in the final `return {...}` of `_validate_plan`, add the validated `domain`:

```python
        domain = parsed.get("domain")
        return {"intent": intent,
                "language": parsed.get("language", "fr"),
                "user_first_name": (parsed.get("user_first_name") or "").strip()[:40],
                "direct_answer": parsed.get("direct_answer"),
                "synthesis_hint": parsed.get("synthesis_hint"),
                "domain": domain if domain in BUSINESS_DOMAINS else None,
                "steps": steps}
```

(The existing `if intent == "BUSINESS"` steps-building block already purges steps for every non-BUSINESS intent, so `CAPABILITY_GAP` / `CONCEPT` get `steps == []` for free.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k ValidatePlan`
Expected: PASS (all ValidatePlan tests, old + 5 new)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): validate CAPABILITY_GAP/CONCEPT intents + domain field\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 5: Rewrite the revenue manifest + anti-drift test (kills the budget bug at the source)

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (`planner_description` of `"salesdrive"` ~L149 and `"salesdrive_v2"` ~L201)
- Create: `orchestrator/tests/test_manifest_antidrift.py`

- [ ] **Step 1: Write the failing test**

Create `orchestrator/tests/test_manifest_antidrift.py`:

```python
"""Anti-drift: the revenue manifest in the orchestrator registry MUST keep
advertising the sub-agent's real coverage (all phases + the main axes). If
someone shrinks the description back to "revenue only", this test fails - which
is exactly the bug that made the orchestrator deny "budget 2026". The phases and
axes are sourced from the sub-agent's OWN constants, never re-hardcoded here.

Run from the repo root:
    python3 -m unittest discover -s orchestrator/tests -v -k AntiDrift
"""
import importlib.util
import os
import sys
import types
import unittest


def _install_dataiku_stub():
    dataiku_mod = types.ModuleType("dataiku")
    dataiku_mod.api_client = lambda: None
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


def _load(name, relpath):
    path = os.path.abspath(os.path.join(os.path.dirname(__file__), relpath))
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_install_dataiku_stub()
orc = _load("orc_under_test", "../orchestrator_agent.py")
sd = _load("sd_under_test", "../../salesdrive/salesdrive_agent.py")


class AntiDriftTests(unittest.TestCase):

    def _revenue_manifests(self):
        return [v["planner_description"].lower()
                for v in orc.CAPABILITIES.values()
                if v.get("kind") == "agent" and v.get("domain") == "revenue"]

    def test_at_least_one_revenue_manifest_exists(self):
        self.assertTrue(self._revenue_manifests())

    def test_every_revenue_manifest_covers_all_known_phases(self):
        for desc in self._revenue_manifests():
            for phase in sd.KNOWN_PHASES:                  # ACTUALS,BUDGET,FORECAST,Q3F,HLF
                self.assertIn(phase.lower(), desc,
                              "manifest must advertise phase %r" % phase)

    def test_every_revenue_manifest_covers_main_axes(self):
        for desc in self._revenue_manifests():
            for axis in ("customer", "product", "solution", "month", "year"):
                self.assertIn(axis, desc, "manifest must advertise axis %r" % axis)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k AntiDrift`
Expected: FAIL - current manifests say only "Revenue … Data source: DRIVE_Revenues" (no `budget`/`forecast`/`q3f`/`hlf`).

- [ ] **Step 3: Write minimal implementation**

Replace the `planner_description` value on BOTH `"salesdrive"` (~L149) and `"salesdrive_v2"` (~L201) with the identical full-truth manifest:

```python
        "planner_description": (
            "Revenue and billing on OWI customers across ALL scenarios/phases - "
            "actuals, budget, forecast, Q3F, HLF - broken down by customer, "
            "product, solution, solution line, sirano product, partner, "
            "distribution type, sales entity, sales zone, parent group, month or "
            "year; totals, top-N rankings, period comparisons, actuals-vs-budget "
            "deltas and variance, trends and YTD. Handles multi-period and "
            "multi-phase comparisons WITHIN ONE single step. Data source: "
            "DRIVE_Revenues. You do NOT pre-judge what this data contains - route "
            "the question; only this agent can confirm or deny a specific figure."
        ),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k AntiDrift`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_manifest_antidrift.py
git commit -m "$(printf 'feat(orchestrator): full-truth revenue manifest + anti-drift test\n\nManifest now advertises all phases (actuals/budget/forecast/Q3F/HLF) and\naxes, sourced from the sub-agent constants. Kills the budget false-denial.\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 6: `build_planner_prompt` - humility rules, domain map, new intents, examples

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (`build_planner_prompt` ~L390-495)
- Test: `orchestrator/tests/test_orchestrator_agent.py`

Note: this changes the LLM *behaviour*; the unit tests only guard that the rules are PRESENT in the prompt string (cheap regression guard). Real routing is validated on DSS (Task 8).

- [ ] **Step 1: Write the failing test**

```python
# ==========================================================================
# build_planner_prompt - humility rules + domain map are present
# ==========================================================================
class PlannerPromptTests(unittest.TestCase):

    def setUp(self):
        self.prompt = orc.build_planner_prompt(CAPS)

    def test_lists_the_domain_map(self):
        self.assertIn("BUSINESS DOMAINS", self.prompt)
        self.assertIn("tickets", self.prompt)
        self.assertIn("HAS an agent", self.prompt)
        self.assertIn("NO agent", self.prompt)

    def test_documents_new_intents(self):
        self.assertIn("CAPABILITY_GAP", self.prompt)
        self.assertIn("CONCEPT", self.prompt)

    def test_states_the_humility_rule(self):
        low = self.prompt.lower()
        self.assertIn("you do not know what the data contains", low)
        # Never assert absence/zero of data.
        self.assertIn("never", low)
        self.assertIn("does not exist", low)

    def test_capability_gap_only_for_unstaffed_domain(self):
        # 'revenue' is staffed in CAPS -> the prompt must mark it HAS an agent.
        self.assertRegexpMatches(self.prompt, r"revenue \(HAS an agent\)")
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k PlannerPrompt`
Expected: FAIL - current prompt has no domain map / new intents / humility rule.

- [ ] **Step 3: Write minimal implementation**

In `build_planner_prompt`, after the `tools_block` is computed (~L395), add a domain map block:

```python
    staffed = staffed_domains(caps)
    domain_lines = []
    for dom, lab in BUSINESS_DOMAINS.items():
        mark = "HAS an agent" if dom in staffed else "NO agent yet"
        domain_lines.append('- %s (%s): %s' % (dom, mark, lab["en"]))
    domains_block = "\n".join(domain_lines)
```

In the big returned string, insert the domain block right after the `AVAILABLE TOOLS` block:

```python
        "AVAILABLE TOOLS (direct actions):\n" + tools_block + "\n\n"
        "BUSINESS DOMAINS (the product's known domains; an agent may or may not be "
        "wired for each):\n" + domains_block + "\n\n"
```

Replace the `INTENTS` block (the `"INTENTS (field \"intent\"):\n"` … up to the blank line before `PLANNING RULES`) with:

```python
        "INTENTS (field \"intent\"):\n"
        "- \"BUSINESS\": needs business data or an action -> build \"steps\". This is "
        "the DEFAULT for anything touching a domain that HAS an agent, EVEN IF you "
        "are unsure the specific figure exists - only the agent can confirm.\n"
        "- \"CAPABILITY_GAP\": the question is about a real BUSINESS DOMAIN that has "
        "NO agent yet -> set \"domain\" to that domain key. Do NOT answer; the code "
        "emits an honest 'no agent for this yet' message.\n"
        "- \"CONCEPT\": a GENERAL telco/business notion with no OWI-specific data "
        "(e.g. 'difference between SS7 and LTE'). Put a short, general-knowledge "
        "answer in \"direct_answer\", explicitly framed as general knowledge, with "
        "NO OWI figure. If an agent OWNS the methodology (e.g. 'how do you compute "
        "the forecast' -> the revenue agent), prefer BUSINESS instead.\n"
        "- \"GREETING\": greetings, thanks, small talk, personal/session questions "
        "(name, date, who you are) -> \"direct_answer\" from the session context.\n"
        "- \"CAPABILITIES\": the user asks what you can do -> handled by code.\n"
        "- \"CLARIFY\": business-related but genuinely contentless/ambiguous -> "
        "\"direct_answer\" = ONE short question. Prefer BUSINESS (the agent's own "
        "clarification is grounded in real data) whenever an agent could handle it.\n"
        "- \"OUT_OF_SCOPE\": clearly unrelated to OWI business data (weather, trivia) "
        "-> handled by code.\n\n"
```

In `HARD RULES`, replace the existing line about revenues never being GREETING/OUT_OF_SCOPE with the humility clauses:

```python
        "HARD RULES:\n"
        "- Output ONLY the JSON object. No markdown fences, no commentary.\n"
        "- NEVER put figures, amounts or any business data in \"direct_answer\".\n"
        "- You do NOT know what the data contains. You NEVER tell the user that a "
        "metric, a scenario (budget/forecast/actuals/Q3F/HLF), a figure or a record "
        "is unavailable, missing, or zero - that is ONLY the agent's call.\n"
        "- You MAY state you lack an AGENT for a domain (CAPABILITY_GAP). You may "
        "NEVER state that the DATA does not exist.\n"
        "- A question about revenues, customers, tickets, products, amounts, budget "
        "or forecast is NEVER GREETING/OUT_OF_SCOPE.\n"
        "- \"language\" = language of the CURRENT question: \"fr\" or \"en\".\n\n"
```

Append three examples to the `examples` list (before the prompt is assembled, near ~L434, after the existing `examples.append(...)` calls):

```python
    if first_agent:
        examples.append(
            'User: "Give me the budget 2026 for the Roaming Hub" -> the revenue '
            'agent owns ALL phases, route it (do NOT deny budget): '
            '{"intent": "BUSINESS", "language": "en", "steps": [{"kind": "agent", '
            '"capability": "%s", "instruction": "Give me the budget 2026 revenue '
            'for the Roaming Hub"}]}' % first_agent)
    examples.append(
        'User: "combien de tickets d\'incidents avec 1&1 en 2025 ?" and NO agent '
        'covers the tickets domain -> {"intent": "CAPABILITY_GAP", "language": '
        '"fr", "domain": "tickets"}')
    examples.append(
        'User: "quelle est la différence entre le SS7 et le LTE ?" (general '
        'concept, no OWI data) -> {"intent": "CONCEPT", "language": "fr", '
        '"direct_answer": "<short general explanation, framed as general '
        'knowledge, no OWI figure>"}')
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m unittest discover -s orchestrator/tests -v -k PlannerPrompt`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/tests/test_orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): planner humility rules + domain map + gap/concept intents\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 7: Wire `process_stream` to the firewall + harden synthesis + header note

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (non-business branch ~L891-901; `SYNTHESIS_PROMPT` ~L498; module header ~L42)

Note: `process_stream` and `_synthesize` are streaming generators that need a live DSS project/LLM - NOT DSS-free unit-testable. The behaviour is validated on the instance (Task 8). The logic they now call (`render_non_business_text`) is already covered by Task 3.

- [ ] **Step 1: Rewire the non-business branch**

In `process_stream`, replace the body of `if intent != "BUSINESS":` (~L891-901) with:

```python
            if intent != "BUSINESS":
                yield _ev_l("DIRECT_ANSWER", lang, {"kind": intent or "CLARIFY"})
                if intent == "CAPABILITIES":
                    # Grounded LLM tone, deterministic fallback (unchanged path).
                    yield from self._answer_capabilities(project, caps, lang, trace, total_usage)
                else:
                    # R1/R2 firewall: CAPABILITY_GAP / OUT_OF_SCOPE -> deterministic
                    # registry templates; GREETING / CLARIFY / CONCEPT -> bounded
                    # planner direct_answer. No business fact can be authored here.
                    yield {"chunk": {"text": render_non_business_text(intent, plan, caps, lang)}}
                yield _ev_l("DONE", lang, {"durationMs": int((time.perf_counter() - t0) * 1000),
                                                "totalUsage": total_usage})
                return
```

- [ ] **Step 2: Harden the synthesis prompt**

In `SYNTHESIS_PROMPT` (~L498), add one rule line after the existing "If a step failed or returned nothing…" line:

```python
    "- If a step returned 'no data' / 'out of scope' / a capability gap, report "
    "that honestly for that part. NEVER replace a missing result with a guessed "
    "or zero figure.\n"
```

- [ ] **Step 3: Update the module header**

At the top of `orchestrator_agent.py`, add a `v2.4` block to the header comment (after the `v2.3` block ~L42):

```python
# v2.4 (Expert Authority - foundation): the orchestrator never authors a business
#   fact. Routing is the default (R3); the only "no" it may write is "no agent for
#   this domain" (CAPABILITY_GAP, deterministic template) - never "the data does
#   not exist". OUT_OF_SCOPE is templated too; CONCEPT answers general notions
#   (no OWI figure). Registry is a manifest: add an agent = one entry {key,
#   agent_id, label, description, domain}. BUSINESS_DOMAINS tells a real-but-
#   unstaffed domain (gap) from non-OWI (out of scope). Anti-drift test keeps the
#   revenue manifest truthful vs the sub-agent's KNOWN_PHASES. Spec:
#   docs/superpowers/specs/2026-06-11-orchestrator-expert-authority-design.md
```

- [ ] **Step 4: Compile + run the FULL suite**

Run:
```bash
python3 -m py_compile orchestrator/orchestrator_agent.py
python3 -m unittest discover -s orchestrator/tests -v
```
Expected: py_compile silent (exit 0); ALL tests PASS (existing + every new test from Tasks 1-6).

- [ ] **Step 5: Commit**

```bash
git add orchestrator/orchestrator_agent.py
git commit -m "$(printf 'feat(orchestrator): wire firewall into process_stream + harden synthesis (v2.4)\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

---

### Task 8: DSS reconciliation + on-instance validation

**Files:**
- Modify: `orchestrator/orchestrator_agent.py` (registry `enabled` flags + `agent_id` ~L190/L237) - **needs the user's real v2 agent id**
- Modify: `orchestrator/README.md` (note the v2.4 behaviour)

Note: the repo currently has `"salesdrive"` (visual `rNTZ781a`) enabled and `"salesdrive_v2"` disabled with `agent_id: "agent:FILL_ME_SALESDRIVE_V2"`, but the user runs the **code agent v2** in DSS. The repo must match that reality before the file is pasted back.

- [ ] **Step 1: Get the real id and reconcile the registry**

ASK THE USER for the real DSS agent id of the SalesDrive v2 Code Agent (looks like `agent:XXXXXXXX`). Then:
- set `"salesdrive_v2"` → `"agent_id": "<the real id>"`, `"enabled": True`
- set `"salesdrive"` → `"enabled": False`

(Both already carry the truthful manifest + `"domain": "revenue"` from Task 5/1, so the anti-drift test still passes against the now-live v2 entry.)

- [ ] **Step 2: Re-run the full suite after the flip**

Run: `python3 -m unittest discover -s orchestrator/tests -v`
Expected: ALL PASS (anti-drift now targets the enabled v2 entry too).

- [ ] **Step 3: Add a README note**

In `orchestrator/README.md`, under "Role", add one line: the orchestrator never authors a business fact (v2.4 Expert Authority); add an agent = one registry entry; see the spec.

- [ ] **Step 4: Commit**

```bash
git add orchestrator/orchestrator_agent.py orchestrator/README.md
git commit -m "$(printf 'chore(orchestrator): make SalesDrive v2 the live revenue agent + README\n\nCo-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>')"
```

- [ ] **Step 5: Validate on the DSS instance (paste + smoke test)**

Paste the full `orchestrator/orchestrator_agent.py` into its DSS Code Agent (replace all), save. Then run these real-corpus questions and confirm the new behaviour:
- "Give me the budget 2026 for the Roaming Hub, Roaming sponsor, IPX, Services and Signalling" → routes to the revenue agent, returns real figures (NO "I don't have budget data").
- "combien de tickets d'incidents avec 1&1 en 2025 ?" → honest "I don't have an agent for incident tickets yet" + offers revenue (NO invented "0").
- "quelle est la météo à Paris ?" → polite out-of-scope redirect.
- "et pour Virtual Network ?" (after a budget turn) → routes with a self-contained instruction.
- "quelle est la différence entre le SS7 et le LTE ?" → general concept answer, no OWI figure.

Expected: each matches the description above. Log any divergence as a new lesson in `memory/LESSONS.md` (per the project protocol) and iterate on the planner prompt (Task 6) only - never by hardcoding a business value (rule P3).

---

## Self-Review

**Spec coverage:**
- §1 honesty rules R1-R3 → Tasks 2/3/6 (templates + firewall router + planner humility rules).
- §2 intent model + firewall → Tasks 4 (validate intents) + 3/7 (render + wire) + 6 (prompt).
- §3 manifest registry + anti-drift + domain map → Tasks 1 (domain map/field) + 5 (manifest + anti-drift).
- §4 dispatch/synthesis, constant LLM cost → unchanged execution + Task 7 synthesis hardening.
- §5 concept routing → Task 6 (CONCEPT intent + example) + Task 4 (validation).
- §6 unchanged surface → no event-kind/streaming/Evidence edits; confirmed frontend keys on eventKind only.
- §7 tests → Tasks 1-6 unit tests + Task 8 DSS smoke tests.
- §8 deployment reconciliation → Task 8.

**Placeholder scan:** the only deferred value is the real v2 `agent_id` (Task 8 Step 1) - an external credential the user supplies, explicitly flagged, not a code TBD. All code/test blocks are complete.

**Type/name consistency:** `BUSINESS_DOMAINS`, `staffed_domains`, `_available_domains_phrase`, `build_capability_gap_answer`, `build_out_of_scope_answer`, `render_non_business_text` are defined in Tasks 1-3 and reused with identical signatures in Tasks 6-7. Intent strings `CAPABILITY_GAP` / `CONCEPT` are consistent across schema, `_validate_plan`, render, and prompt. `domain` field consistent across schema/validate/render.
