Local env has none of openpyxl/reportlab/matplotlib (expected; this is the agent's machine, not the DSS backend env). That confirms the install-gating is real and unverifiable here. I have enough verified grounding. Writing the adversarial critique through the cost/sequencing/YAGNI lens.

---

# ADVERSARIAL CRITIQUE - LENS: COST DISCIPLINE, SEQUENCING REALISM & YAGNI

The proposals are strong on plumbing accuracy but collectively **over-promise on speed, under-cost the LLM additions, and gold-plate the governance layer**. Findings ranked by severity.

## BLOCKER

**B1. The agent-factory "engine-byte-identical codegen" (arch:agent-factory §2 Path B) is sold as "M, no install" but is a multi-session slog that fights the frozen-contract reality.** The proposal claims `gen_specialist.py` stamps only a CONFIG header into a byte-identical engine, with a CI test asserting `engine-body(generated) == engine-body(canonical)`. But the revenue-specific bits are NOT all in a clean header: `defer_multicolumn_offer_terms`, the offer-hierarchy fragment in `build_semantic_question`, `metric_unit`/currency derivation, and the PERSONA money block are **interleaved in the engine body** (verified: orchestrator PERSONA hardcodes euro/ACTUALS; sub-agent offer fragment is inline at the QUERY node). Extracting them cleanly is itself the hard refactor, and every extraction risks the frozen `KNOWN_*`/`AGENT_RESULT`/span-shape contracts that the webapp depends on. Calling this "S-M, a day" (§1) and "M" (§2) is the exact "this will be easy" the lens asks me to flag. Realistic: **the first genericization pass is 1-2 sessions of careful surgery + adversarial review, before any second domain ships.** Do NOT promise day-scale.

## HIGH

**H1. "Add an agent in days, not a month" is dishonest about the irreducible calibration - and every proposal that cites it inherits the lie.** arch:agent-factory §5 and arch:domains-and-360 §1 both claim tickets is "S/M, ~2 sessions" and "lowest calibration." But the verified intrinsic-human cost (scenario/exclusion semantics, golden queries verified against real data, jargon `BUSINESS_ALIASES`, semantic-model entities/filters) is exactly what took revenue 4-5 sessions, and it is **per-domain, not amortizable**. The factory honestly removes the *code* work (which was already ~10% of the cost). So the headline should be: "the factory makes the cheap part free; the expensive part (semantic curation) stays expensive, just test-gated." arch:domains-and-360 is the most honest of the five here (it explicitly orders by calibration-risk), but it still calls tickets "~2 sessions" without evidence that the tickets dataset even exists or is single-table - which it flags only at the very end. **Reorder: validate dataset existence + single-table-ness BEFORE assigning any session budget to a domain.**

**H2. The AI-generated conversation title (arch:webapp-capabilities #4) is a per-conversation LLM call sold as "bounded/cheap" but it is gratuitous cost for near-zero value, and it is mis-sequenced into Phase 1.** The user's pride is Flash-Lite sufficiency. A title is display-only; the existing `CONV_TITLE_MAXLEN=56` regex derivation (verified, already shipped) is *adequate*. Adding an LLM call per conversation - plus a backend python-lib change requiring a restart - to shorten a sidebar label is the definition of low-impact/medium-effort. **CUT from Phase 1; defer indefinitely or do it deterministically (first N tokens of the resolved intent). It is the only Phase-1 item that burns tokens and forces a redeploy.**

**H3. Semantic cache is rated P0 by arch:domains-and-360 (§3 B1) and "must precede the 360," but it is premature optimization that the lens explicitly warns against.** arch:webapp-capabilities #14 gets this right ("YAGNI caution: only build when real cost data shows repeat questions; the cascade already routes 85-90% cheap"). The domains proposal contradicts it and elevates it to a 360 prerequisite. Reality: a cache keyed on `(question + resolved_filters)` only pays off if users *repeat* questions within 24h, which is unproven; and **cache invalidation on data refresh is a correctness hazard** for a trust-critical product where a stale revenue number is the exact disengagement risk. A 360 being "3x cost" of an already-Flash-Lite query is still cheap in absolute terms (3 small-model calls). **Defer the cache until audit-log data (A2) proves repeat-rate > ~25%.** Build the audit log first precisely so this decision is data-driven, not asserted.

**H4. Claim-vs-result reconciliation is proposed by THREE architects (webapp #8, deliverables, domains A1) as "the P0 anti-hallucination guard" via a regex pass - but a naive regex number-match has a false-positive/false-negative profile that could make trust WORSE.** Formatted numbers (`1,2 M€`, `1 200 000`, `1.2M`, rounded `~1,2M`) will not literally `==` a raw result cell `1199847.3`. Without careful format-tolerance (which `format_number` provides one-directionally, not as a fuzzy matcher), the badge will flag *correct* numbers as "unverified," training users to ignore the badge - the opposite of the goal. This is real work (a robust numeric extractor + tolerance + the agent's own rounding rules), not a "cheap Python 3.9 regex pass." It is worth doing, but **bound it: ship it in shadow/log-only mode first (write the flag to the audit log, do NOT surface a user-facing badge) until the false-positive rate is measured.** Surfacing a noisy confidence badge to executives is higher-risk than no badge.

## MEDIUM

**M1. PDF/email/XLSX are correctly install-gated, but the deliverables proposal buries the real sequencing risk: ReportLab + matplotlib + openpyxl are THREE separate user installs into a code env the agent cannot verify (confirmed: none present on this machine; the DSS backend env is 3.9 and unverified).** That is three install-approval round-trips with the user, each blocking. The honest MVP for the "more output types" mission is **PNG (client-side, zero install) + CSV (stdlib, zero install)** - full stop. Those two cover ~80% of "get it out" persona value (paste a chart, hand over raw numbers) at zero cost and zero blast radius. PDF/email are marquee but should be explicitly labelled "Phase 2+, gated on N user installs, may be declined." Both webapp and deliverables proposals say this, but both still front-load PDF as "the depth the user emphasized" - **do not let the marquee feature delay the two free wins.**

**M2. Track A Class 2 (`render_chart` for foreign agents, arch:tool-exposure §2) is a NEEDS-DSS-VALIDATION spike correctly flagged, but it is also the lowest-ROI item in any proposal and should be explicitly de-prioritized, not just caveated.** The verified conclusion (the side panel is a property of the webapp session, not the tool; a foreign agent has no `exchange_id`) means the realistic outcome is "tool returns JSON, no panel." Building a new `webapp_artifacts_v2`/`webapp_tool_artifacts_v1` table for a stretch goal nobody has asked for is gold-plating. **Defer the entire foreign-agent-into-side-panel idea until a real user wants a visual agent in our panel.** The spike is fine (one afternoon); building on it now is not.

**M3. Multiple proposals add new frozen event kinds (`SUGGESTIONS`, `confidence`, `deliverable`) to the whitelist.** Each is cheap individually, but the lens cares about discipline: follow-up suggestion chips (webapp #3) are good, but "gate an optional tiny eco-model call behind a flag" must stay a flag that is **off by default** - the deterministic-from-`AGENT_RESULT` path is the only one that respects cost. Make the deterministic version the shipped one and the LLM version a never-default escape hatch.

**M4. arch:domains-and-360 Phase A ("governance floor before any 2nd agent": reconcile + audit + soft-quota) is the right instinct but risks blocking domain delivery on a governance project of uncertain size.** Audit log (A2, "S", mirrors `usage.py`) is genuinely cheap and high-value - keep it as a true prerequisite. But gating the second domain on a *user-facing* reconciliation badge (H4's hazard) inverts priority. **Prerequisite = audit log only; reconciliation ships in log-only mode in parallel; soft-quota is a 1-field add that need not block anything.**

## LOW

**L1. Soft quota banner at 80% (webapp #5, domains B2): genuinely cheap, genuinely useful, do it in Phase 1.** No notes except: confirm `/usage` already returns spent+limit (it does per memory) so this is frontend-only.

**L2. "Explain this number" (webapp #7) is correctly identified as mostly-built frontend wiring over existing Evidence - good, cheap, high-trust-value. Keep it.** But detecting numbers in rendered markdown to link them to drill rows is fiddlier than "a frontend wiring job" (number formats again). Bound it to KPI values first, not every number in prose.

**L3. arch:webapp-capabilities's DROP list (Evidence multi-agent, pin-to-dashboard, voice, edit-profile, budget dashboard) is the single best YAGNI work in all five proposals. Amplify it.**

---

## TOP 5 THINGS THE FINAL PLANS MUST CHANGE OR CAVEAT

1. **Stop promising "add an agent in days."** The factory makes the *code* free; the *semantic calibration* (golden queries, scenario semantics, aliases, semantic-model tuning) is per-domain and irreducible - still ~2-3 sessions for a *simple* domain, and only after the dataset is confirmed single-table. State this plainly. Validate dataset existence + one-table-ness before budgeting any domain.

2. **The factory genericization (Path B codegen) is 1-2 sessions of contract-risky surgery, not "a day."** The revenue-specific bits are interleaved in the engine body, not in a clean header. Re-estimate, and require the engine-identity CI test + adversarial review before any second domain.

3. **Cut the AI conversation title and defer the semantic cache.** Both burn tokens/redeploys for unproven value; both violate the Flash-Lite-sufficiency ethos. The cache decision must be data-driven from the audit log, not asserted as a 360 prerequisite. The audit log itself is the one cheap governance prerequisite worth front-loading.

4. **Ship reconciliation/confidence in LOG-ONLY (shadow) mode first.** A naive regex number-match will false-flag correctly-formatted numbers and erode trust. Measure false-positive rate via the audit log before surfacing any user-facing badge. Do not let three proposals treat "regex pass" as trivially correct.

5. **The honest deliverables MVP is PNG (client) + CSV (stdlib) only - zero install, ship this week.** PDF/email/XLSX are three separate, declinable user-install round-trips into an unverified 3.9 env; label them Phase 2+ and never let them gate the two free wins. Reject WeasyPrint and server-SMTP outright (system libs / blast radius).

## GENUINELY GOOD IDEAS WORTH AMPLIFYING

- **Reuse the captured `generated_sql[].result` for ALL exports** (deliverables thesis) - never re-run SQL for a download. This is the correct, instance-safe, non-negotiable-#3-honoring spine; every export is a parameter on one owner-scoped route.
- **Resolve the 360 account ONCE up front via `attribute_lookup`** before fan-out (domains §2) - prevents each sub-agent resolving "Airbus" differently; the single highest-leverage correctness call in the 360, and nearly free.
- **Template-fill discipline (model fills bounded slots via `with_json_output`, never structure)** - the right safety property for PDF/email, and it reuses the verified-reliable JSON path.
- **The webapp-capabilities DROP list and YAGNI ruthlessness** - the best cost discipline in the set; the other four proposals should adopt its posture.
- **Audit log as the cheap, data-generating foundation** - build it first so cache, reconciliation thresholds, and quota tuning become evidence-based instead of asserted.

Files verified this session: `dataiku-agents/agents/OWIsMind_orchestrator.py` (LOOP_LLM_BY_MODE:116-120 = Flash-Lite/Flash/Sonnet, MAX_PARALLEL_AGENTS:141=3, MAX_TOOL_LOOPS:140=8, LOOKUP_SOURCE_CAP:172, offer/persona bits interleaved in engine body), `dataiku-agents/CLAUDE.md` (calibration cost, frozen contracts, one-table rule), `python-lib/owismind/storage/` (no openpyxl/reportlab/matplotlib locally; install-gating real and unverifiable here).