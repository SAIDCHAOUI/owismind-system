All seams verified against real code. I have what I need to write a precise, grounded plan.

# Mission 2 Architecture: New Domains, Cross-Domain 360, and Cross-Cutting Governance

The factory thesis is **already true in code**: `CAPABILITIES` (line 187), `BUSINESS_DOMAINS` (240), `build_tool_specs` (285), `_run_subagents` fan-out (1777), and a sub-agent that is ~90% Profile-driven (`build_understand_prompt`, line 664) mean adding a domain is mostly config + calibration, not architecture. The expensive part is **calibration** (scenario/exclusion semantics, hierarchy, jargon aliases, golden queries), not plumbing. So the rollout plan is really a **calibration-cost ordering** plus a **governance layer that must ship before agent count grows**, because cost and hallucination scale super-linearly with agents and the 360 amplifies both.

---

## (1) Order of new specialist agents

Ranking is by **(value × simplicity) / calibration-risk**. The calibration risk is dominated by the three INTRINSIC-human items the revenue agent needed (verified in `res__agent-factory.md`): non-summable scenario/exclusion rules, hierarchy resolution priority, jargon aliases (`BUSINESS_ALIASES` in `build_value_catalog_recipe.py`).

**1. Tickets / incidents - FIRST (S/M, ~2 sessions).** Likely dataset: a ServiceNow/Remedy export keyed by account + status + priority + open/close timestamps.
- (b) **Value**: account manager ("any open P1 on my accounts?"), exec ("MTTR trend, SLA breaches"), product owner (recurring incident clusters). Highest because every persona asks it and it's the natural 360 partner to revenue.
- (c) **Approach**: new `CAPABILITIES['tickets_expert']` entry (kind/agent_id/domain='tickets'/tool_name='ask_tickets_expert'/lookup_dataset). Run the three recipes (`profile_dataset_recipe.py`, `build_value_index_recipe.py`, `build_value_catalog_recipe.py`) on the tickets dataset; clone `SalesDrive_revenue_expert.py` -> `Tickets_expert.py`, change the ~7 constants (`PROFILE_DATASET`, `VALUE_INDEX_DATASET`, `SEMANTIC_TOOL_ID`, `SEMANTIC_TOOL_NAME`, `TARGET_DATASET`) and **delete the offer-hierarchy prompt fragment** (no-op for tickets). New semantic model object + golden queries.
- (d) **S/M, no install.** (e) **Risk**: lowest calibration - status is a clean enum, no "never sum across phases" trap, few aliases. Charter N/A (agent). **Schema risk**: tickets often need *count* and *duration*, so verify `metric_unit`/`format_cell` handle non-currency + a duration metric.
- (f) **Depends on**: nothing new. Ships right after governance Phase A.

**2. Opportunities / pipeline - SECOND (M, ~3 sessions).** Dataset: CRM pipeline (stage, amount, close date, owner).
- (b) **Value**: account manager (pipeline by account), exec (forecast coverage), marketing (source attribution). Pairs with revenue for "won vs forecast."
- (c) Same factory path. (e) **Calibration risk MEDIUM**: stage is a hierarchy/ordering (like the offer hierarchy that bit revenue) and "weighted vs unweighted pipeline" is a non-summable-style trap - this is exactly where the `defer_multicolumn_offer_terms` (line 887) generic deferral and golden queries earn their keep. (f) After tickets.

**3. Customer experience / satisfaction - THIRD (S/M, ~2 sessions).** Dataset: NPS/CSAT survey rows.
- (b) **Value**: marketing director and exec primarily; weaker for account manager. (e) **Low calibration** (scores are numeric, few aliases) **but lower standalone value** - which is why it ranks below opportunities despite being simpler. Its real payoff is **inside the 360**. (f) After opportunities, or fast-followed if a 360 demo needs it.

**4. Billing (detailed) - FOURTH (M, ~2-3 sessions).** Note: revenue already owns billing-level figures (the `revenue_expert` planner_description literally claims "billing"). Only add a separate `billing` agent if there's a **distinct invoice-line dataset** (invoice id, due date, paid/unpaid, dispute). (e) **Risk**: overlaps revenue's domain claim -> the honesty firewall and `BUSINESS_DOMAINS` routing must disambiguate, or two agents fight for the same question. **Defer until a real invoice dataset exists** (YAGNI).

**5. Delivery / deployment - LAST (M, ~3 sessions).** Dataset: project/deployment milestones. (b) Narrowest persona reach (delivery managers, not the four target personas). (e) Often **multi-table by nature** (project + milestone), which collides with the absolute ONE-TABLE/no-JOIN rule - needs a pre-flattened dataset built upstream in the Flow. Highest friction, lowest reach -> last.

**Cumulative**: tickets+opportunities+satisfaction (~7 sessions) gets the 360 to genuine value. Billing/delivery are demand-driven.

---

## (2) Cross-domain 360 ("fiche client 360")

ONE-TABLE/no-JOIN is absolute, so the 360 **must live at the orchestrator**, composing per-domain sub-agents - never a SQL JOIN. The machinery already exists: `_run_subagents` (line 1777) fans out via `ThreadPoolExecutor(max_workers=min(MAX_PARALLEL_AGENTS, n))` with `MAX_PARALLEL_AGENTS=3` (line 141).

- (a) **What**: one question ("360 on account X") -> orchestrator fans out `ask_revenue_expert` + `ask_tickets_expert` + `ask_opportunities_expert` in parallel for the *same resolved account*, then synthesizes one narrative + one deliverable.
- (b) **Value**: this is the flagship for **account managers** (pre-meeting brief) and **executives** (account health). Marketing gets a segment-roll-up variant later.
- (c) **Orchestration**: NO new orchestration primitive. (i) **Resolve the account ONCE** up front via the existing `attribute_lookup` built-in (already wired, `LOOKUP_SOURCE_CAP`, line 172) so all sub-agents filter the *same canonical entity* - the #1 correctness risk is each agent resolving "Airbus" to a different key. (ii) Let `build_tool_specs` emit the existing `ask_<cap>` tools; the loop LLM issues 3 sub_calls in one turn -> `node_tools` splits to `_run_subagents` (already bounded to 3, instance-safe). (iii) Each sub-agent returns its frozen `AGENT_RESULT` + Evidence (untouched per-domain provenance). Because the schema is `webapp_artifacts_v1` PK `exchange_id` (single per exchange), **the 360 produces ONE synthesized answer with ONE deliverable**, and per-domain detail stays in each sub-agent's captured `generated_sql` - no schema change needed.
- **Synthesis prompt discipline (the safety property)**: add a `PERSONA`/synthesis fragment that says verbatim: *"You may ONLY state facts returned by a sub-agent in THIS turn. Attribute every number to its domain (revenue / tickets / pipeline). NEVER infer a fact in one domain from another (e.g. do not guess churn risk from ticket count). If a sub-agent returned nothing for the account, say 'no <domain> data for this account' - never fabricate."* This is the cross-domain extension of the existing per-agent honesty firewall and reuses the claim-vs-result reconciliation pass from §3 - **every number in the 360 narrative must trace to one sub-agent's captured result**.
- (d) **M, no install.** Mostly prompt + a thin "is this a 360 request" routing nudge in the orchestrator persona; the executor already exists.
- (e) **Instance safety**: fan-out is already capped at 3; a 360 = 3 sub-agents each doing 1-2 SQL = bounded. **Do NOT raise `MAX_PARALLEL_AGENTS`**. **Cost risk**: a 360 is 3× a normal query -> this is the single biggest reason the **semantic cache and soft-quota (§3) must precede the 360**, not follow it. (f) **Depends on** >=2 domains live + governance Phase A+B. The single deliverable ties directly into the PDF/email pipeline (mission 1): the synthesized 360 is the canonical first PDF template.

---

## (3) Cross-cutting governance / eval / cost (must ship ALONGSIDE more agents)

As agent count N grows, blast radius grows as N (hallucination surface) and cost as N (and 3N for 360s). These are **prerequisites, not nice-to-haves**, because the user's stated red line is "one hallucinated revenue number = permanent disengagement," and that risk multiplies per domain.

- **A1. Claim-vs-result reconciliation (P0).** (a) Regex pass: every number in the narrative must appear in the captured SQL result, else flag "unverified." (c) **Seam**: new `evidence/reconcile.py`, pure-Python, called from `evidence/service.py` where `generated_sql[].result` is already joined - it already holds both narrative and result. Python 3.9-safe, no LLM. (e) Zero instance load (string/regex). (f) **Prerequisite to BOTH new domains and the 360** - it's the only mechanical anti-hallucination guard and it must exist before a second agent can lie.
- **A2. Audit log `webapp_audit_v1` (P0).** (a) Append-only: run_id, user_id, model, tokens, cost, tools, sql, quota_state, trust_level, reconcile_flag. (c) **Seam**: new `storage/audit.py` mirroring `storage/usage.py` (same `_vN` no-ALTER, parametrized + COMMIT + `statement_timeout`), written from `agents/streaming.py` at terminal event. (d) **S.** (e) Append-only insert, bounded - safe. (f) Prerequisite: with N agents and 360s you cannot debug cost/quality without per-run provenance.
- **B1. Semantic cache (P0 for cost).** (a) `(question + resolved_filters + agent_key) -> (result + narrative)`, 24h TTL. (c) **Seam**: new `storage/semantic_cache_v1`, checked in `_dispatch_subagent`/`_run_subagents` (line 1777) before invoking. (d) **M.** (e) One indexed read before LLM - cheaper than the call it avoids; key on *resolved* filters (post-`attribute_lookup`) so paraphrases hit. **40-70% cost cut** per research. (f) **Must precede the 360** (which is 3× cost) and the cascade of new agents.
- **B2. Soft quota at 80% (P1).** (a) Non-blocking banner before the existing 402 hard stop. (c) **Seam**: `storage/budget.py` already computes spend; add an 80% threshold returned by `/usage`; frontend banner (Orange charter: one rare orange accent, no glow). (d) **S.** (e) Read-only. (f) Needed before 360s spike per-user burn.
- **C1. Golden-query EX harness per domain (P1).** (a) 30-50 question->expected-result regression suite per domain, run off-instance against captured results. (c) **Seam**: extend `dataiku-agents/tests/` + the semantic model's golden queries; pure unittest (the project already runs `python3 -m unittest discover`). (d) **M per domain.** (e) **Run as an off-peak scheduled scenario** (full-table reads = DSS memory risk per `res__agent-factory.md`). (f) **This is what compresses calibration from ~4-5 sessions to ~2** - it is the factory's quality ratchet; ship the harness with tickets so domain #2 onward is cheaper.
- **C2. Confidence indicator + requires_confirmation (P1).** (a) low/med/high badge (already have `trustLevel`/`trustLevel(meta)` in Evidence) + a HITL confirm gate for any **deliverable** (email/export). (c) **Seam**: confidence from `reconcile_flag` (A1) surfaced via existing `EvidenceTrust.vue`; `requires_confirmation` enforced server-side in the deliverable route (mission 1), never client-only (non-negotiable #4 logic: front sends opaque intent, backend gates). (d) **S.** (e) Charter: confidence badge uses semantic tokens, no new orange. (f) Prerequisite to the email/export pipeline - blast radius of a wrong emailed number is unbounded.
- **C3. LLM-as-judge batch (P2, defer).** Sample 10% of runs nightly for quality scoring. (c) Reads `webapp_audit_v1`. (d) M, adds LLM cost. (e) Off-peak scheduled only. (f) **YAGNI until N>=3 agents** - the EX harness (C1) covers regression more cheaply first.

---

## (4) Phasing (whole agents mission)

- **Phase A - Governance floor (before any 2nd agent).** A1 reconcile, A2 audit, B2 soft-quota. *Value*: makes a multi-agent system safe to expand. *Effort S/M, no install.* *Prereq*: everything else.
- **Phase B - First new domain + cost floor.** Tickets agent (factory path) + B1 semantic cache + C1 EX harness seeded on tickets. *Value*: proves the factory end-to-end and locks cost before scale. *Effort M, no install.* *Depends on A.*
- **Phase C - Second domain + 360 enablement.** Opportunities agent + C2 confidence/HITL. *Value*: two domains unlock a meaningful 360. *Depends on B (cache before 3× cost).*
- **Phase D - 360 flagship + first deliverable.** Orchestrator 360 (single up-front `attribute_lookup` resolve, fan-out <=3, synthesis discipline) emitting the first PDF template (mission 1 join). *Value*: the headline demo for account managers/execs. *Depends on >=2 domains + A+B.*
- **Phase E - Demand-driven.** Satisfaction (cheap, boosts 360), then billing/delivery only on real datasets; C3 judge when N>=3.

**Single sharpest call**: ship **A1 (reconcile) + B1 (semantic cache) before the 360**, not after - the 360's 3× fan-out is where un-governed cost and cross-domain hallucination both detonate. **Flag (NEEDS-DSS-VALIDATION)**: whether a cloned `Tickets_expert.py` runs standalone in the 3.11 Code Agent env with only constant changes, and whether the tickets/opportunities datasets are truly single-table (delivery is likely NOT) - validate the one-table assumption per dataset before committing a domain to a session budget.

**Files named (all verified this session)**: `dataiku-agents/agents/OWIsMind_orchestrator.py` (CAPABILITIES:187, BUSINESS_DOMAINS:240, build_tool_specs:285, _run_subagents:1777, MAX_PARALLEL_AGENTS:141, LOOKUP_SOURCE_CAP:172), `dataiku-agents/agents/SalesDrive_revenue_expert.py` (constants:86-138, build_understand_prompt:664, defer_multicolumn_offer_terms:887, metric_unit:1034), recipes `profile_dataset_recipe.py`/`build_value_index_recipe.py`/`build_value_catalog_recipe.py`, `Plugin/owismind/python-lib/owismind/storage/{usage,budget}.py`, `evidence/{service,capture}.py`. New: `evidence/reconcile.py`, `storage/audit.py`, `storage/semantic_cache_v1`.