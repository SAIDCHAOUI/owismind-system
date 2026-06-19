## Trust, Evaluation, Governance and Cost-Control for Agentic Analytics at Scale

---

### 1. Evaluation Harnesses for NL->SQL / Analytics Agents

**Gold standard metrics.** The field converged on two metrics: **Execution Accuracy (EX)** - result sets match, not just SQL text - and **Valid Efficiency Score (VES)** from the BIRD benchmark, which penalizes correct but slow queries. EX is the only metric that catches cases where syntactically different SQL yields an identical answer. [NL2SQL-BUGs benchmark (ACM 2025)](https://nl2sql-bugs.github.io/) introduced a semantic-error detection layer on top of BIRD and found current LLMs detect semantic SQL bugs at only 75.16% accuracy - meaning roughly 1 in 4 subtly wrong queries slips through.

**Regression suite pattern.** [NL2SQLBench (arXiv 2025)](https://arxiv.org/html/2604.16493v1) recommends a modular pipeline: (a) a frozen golden query set, (b) per-intent test slices (aggregation, filter, join, date arithmetic), (c) automated EX checks on every model/prompt change, (d) paraphrase robustness checks. LLaMA 3.3-70B drops 10.23% EX on paraphrased Spider queries - a risk for business users who phrase things unpredictably.

**LLM-as-judge for analytics.** For answers that go beyond raw SQL correctness (e.g. "did the agent state the right period/currency?"), a fast judge model (Flash-Lite) can score the final text against the captured SQL result. This is cheaper than human review and catches metric hallucination (agent states a number not in the SQL result). Implement this as a background job after each production run, not inline.

**Confidence estimation.** [Confidence Estimation for Text-to-SQL (arXiv 2025)](https://arxiv.org/pdf/2508.14056) shows full-token confidence scores from the LLM correlate well with EX. Expose a `confidence` field on each answer (low/medium/high) computed from token probabilities. Gate high-stakes exports or email actions on `confidence >= high`.

**OWIsMind recommendation:** Build a `tests/golden/` directory with 30-50 business questions tagged by intent (actuals/budget/forecast/lookup). Run EX checks on CI against a test Dataiku instance snapshot. Add a weekly LLM-as-judge job over production runs sampling 10% of exchanges.

---

### 2. Guardrail Patterns for Analytics

**Semantic layer as the contract.** Gartner elevated semantic layers to essential AI infrastructure in 2025. [Atlan's 2026 AI agent guardrails guide](https://atlan.com/know/ai-agent-risks-guardrails/) confirms: a governed semantic layer reduces hallucinations ~60% vs raw schema access, because it eliminates field-name ambiguity at query time. OWIsMind's existing semantic model is the correct architectural choice.

**"Never invent a number" rule.** [Promethium's enterprise AI grounding guide](https://promethium.ai/guides/building-ai-agents-that-dont-hallucinate-enterprise-data/) prescribes a "claim-vs-result reconciliation" step: every numerical claim in the narrative must be present verbatim in the captured SQL result rows. Implement server-side as a post-render check: extract numbers from agent text, diff against `generated_sql[].result`. Flag mismatches as `unverified` in the trust badge. This is feasible with a regex pass in Python 3.9.

**Abstention / confidence gate.** If the semantic model returns `AMBIGUOUS OFFER TERM` or the lookup returns `not_found`, the agent must ask or disclose - never hallucinate a default. OWIsMind already does this partially. Extend it: if `rows_capped=True` and the question requires totals, add a disclaimer ("result may be partial - cap reached").

**Value grounding.** The `value_index` pattern OWIsMind uses (ILIKE over concat_ws) is best-practice. The only upgrade: add a `match_confidence` score (exact=1.0, fuzzy<1.0) to the lookup result and surface it in the trust layer when fuzzy.

---

### 3. Cost-Control at Scale

**Model cascade, quantified.** [Routing, Cascades, and User Choice (arXiv 2026)](https://arxiv.org/pdf/2602.09902) shows that routing 85-90% of traffic to small models and escalating only complex queries to large models achieves 60-80% cost reduction with <5% quality drop. OWIsMind's eco/medium/high routing is exactly this pattern. Key refinement: measure *actual* model-switch rate per intent in production and tighten the heuristic.

**Semantic caching (highest ROI).** [GPT Semantic Cache (arXiv 2024/2025)](https://arxiv.org/abs/2411.05276) reports 61-69% cache hit rates with embedding-based fuzzy matching, cutting API calls by the same fraction. A practitioner reported 72% cost reduction ($47k -> $13k/month) using FAISS + sentence-transformers. For OWIsMind: cache the (question + active filters) -> (SQL result + narrative) pair with a 24h TTL. Use Python's `sentence-transformers` (already available in many Dataiku envs) or a lightweight in-process hash. Exact-match on the normalized SQL is also valuable for repeated dashboard-style queries.

**Prompt caching.** Anthropic prefix caching cuts costs up to 90% and latency 85% for long repeated prefixes. OWIsMind's agent system prompts and semantic model context are ideal candidates - they are long and stable per session. Verify the Dataiku LLM Mesh exposes the `cache_control` parameter for Anthropic models.

**Prompt compression.** [LLMLingua](https://github.com/microsoft/LLMLingua) achieves 4-20x token reduction with <2% quality loss by dropping non-essential tokens from long context. Apply to the value_index grounding block (longest variable part) before sending to Sonnet. Runs on Python 3.9, no heavy dependencies.

**Result caching at the SQL layer.** For queries that hit the same SQL with the same filters, PostgreSQL's built-in query cache (or application-level memoization keyed on normalized SQL + parameters) avoids re-running expensive analytics queries. The OWIsMind `TTL` cache on `attribute_lookup` is a good precedent - extend to full SQL results.

**Small-model sufficiency.** For attribute lookups, date computations, and intent classification, Flash-Lite is sufficient. Sonnet should be reserved for: multi-step reasoning, ambiguous offer resolution, and final narrative generation when `high` mode is selected. This maps to OWIsMind's current mode routing.

---

### 4. Governance and Observability

**Tracing standard.** OpenTelemetry with semantic conventions for LLM spans (LLM input/output tokens, model id, latency, tool calls) is the 2025 standard. [Portkey (Gartner Cool Vendor 2025)](https://portkey.ai/blog/the-complete-guide-to-llm-observability/) and [MLflow's agent observability guide](https://mlflow.org/top-5-agent-observability-tools/) both recommend: trace every tool call with `span_id`, `parent_span_id`, `model_id`, `input_tokens`, `output_tokens`, `cost_usd`. OWIsMind's existing subspan `semantic-model-query` is the right pattern - expand it to cover all tool calls.

**Per-user quota enforcement.** OWIsMind's $50/month/user system is aligned with enterprise practice. Key additions: (a) expose the current month's spend in the API response headers so the frontend can pre-emptively warn before the 402, (b) add a `soft_limit` at 80% ($40) that triggers a banner but does not block, (c) log every quota decision (`allowed`/`soft_warned`/`blocked`) with user_id, timestamp, and cost to a dedicated audit table (not the chat table).

**Dataset-level access control.** [Quinnox data governance guide (2025)](https://www.quinnox.com/blogs/data-governance-for-ai/) and [Kiteworks zero-trust AI guide](https://www.kiteworks.com/cybersecurity-risk-management/zero-trust-ai-data-privacy-protection-guide/) both recommend attribute-based access control (ABAC): a user's role determines which datasets/semantic entities they can query. In OWIsMind, implement this as a server-side filter on `enabled_agents` and on Evidence dataset discovery - a user with role `account_manager` can only query their own accounts' data. This is a Dataiku project-level permission that can be enforced in the Flask route before the agent call.

**PII handling.** Tag columns containing PII in the semantic model metadata. Before returning Evidence drill rows, apply a server-side column masking function that replaces PII fields with `[REDACTED]` for users without the `pii_view` permission. This is a Python 3.9-compatible transform.

**Human-in-the-loop for risky actions.** [Strata.io agentic HITL guide (2026)](https://www.strata.io/blog/agentic-identity/practicing-the-human-in-the-loop/) defines a "blast radius" criterion: actions that send emails, export >1000 rows, or write back to a system of record require an explicit user confirmation step before execution. Implement as a frontend "confirm before action" modal triggered by a `requires_confirmation: true` flag in the agent event payload, with the action queued server-side until confirmed.

**Audit log.** Every agent run should write a tamper-evident audit record: `{run_id, user_id, timestamp, model_used, input_tokens, cost, tools_called[], sql_executed[], quota_state, trust_level}`. Store in a dedicated `webapp_audit_v1` table (append-only, no UPDATE). This satisfies enterprise compliance requirements and enables retroactive debugging.

---

### 5. Adoption and UX Trust

**Trust is the 2026 adoption blocker.** [CMSWire (2026)](https://www.cmswire.com/digital-experience/2026-the-year-user-experience-finally-rewrites-the-rules-of-ai/) reports that organizations operationalizing AI transparency see 50% improvement in user acceptance. The shift is from "can it do the task" to "can I rely on it."

**Concrete UX patterns that build trust:**
- **Show your work:** displaying the SQL (even collapsed) increases trust significantly among technical business users. OWIsMind already does this.
- **Cite the exact number:** the captured result mini-table in Evidence is the single highest-trust feature. Keep it prominent and always show it before the narrative.
- **Confidence indicators, not error messages:** low-confidence answers should show a "verify before sharing" badge, not an error. Users accept uncertainty; they reject surprises.
- **Abstention > hallucination:** business users (account managers, execs) will disengage permanently after one hallucinated revenue number. A polite "I don't have that data" is always preferable.
- **Progressive disclosure:** the Evidence panel's drill/SQL/sources hierarchy is the right pattern - business users see the number first, analysts dig into the SQL.

**What does not build trust:** verbose "thinking" traces, percentage confidence scores without explanation, and answers that contradict the previous answer without acknowledgment.

---

### Prioritized Recommendations for OWIsMind

| Priority | Action | Effort | Impact |
|---|---|---|---|
| P0 | Add claim-vs-result reconciliation check server-side (catch metric hallucination before users do) | Low (Python regex) | Critical |
| P0 | Expand audit log to `webapp_audit_v1` (quota decision + tools called + SQL) | Low | Compliance + debug |
| P1 | Build golden query regression suite (30-50 questions, EX checks on CI) | Medium | Catch regressions |
| P1 | Semantic cache on (question + filters) with 24h TTL + embedding similarity | Medium | 40-70% cost cut |
| P1 | Soft quota warning at 80% spend ($40 banner, non-blocking) | Low | UX + retention |
| P2 | LLM-as-judge background job on 10% of production runs (weekly batch) | Medium | Quality monitoring |
| P2 | Column-level PII masking in Evidence drill for non-pii_view users | Medium | Compliance |
| P2 | `requires_confirmation` flag for export/email actions (HITL modal) | Medium | Safety |
| P3 | Prompt prefix caching for system prompts (if Mesh exposes cache_control) | Low | 50-90% latency/cost |
| P3 | Apply LLMLingua compression to value_index grounding block | Medium | 4-20x token reduction |

---

Sources:
- [NL2SQL-BUGs Benchmark (ACM 2025)](https://nl2sql-bugs.github.io/)
- [NL2SQLBench Modular Framework (arXiv 2025)](https://arxiv.org/html/2604.16493v1)
- [Confidence Estimation for Text-to-SQL (arXiv 2025)](https://arxiv.org/pdf/2508.14056)
- [Routing, Cascades, and User Choice for LLMs (arXiv 2026)](https://arxiv.org/pdf/2602.09902)
- [GPT Semantic Cache (arXiv 2024)](https://arxiv.org/abs/2411.05276)
- [Semantic Cache 72% cost reduction (DEV Community)](https://dev.to/vinay_budideti/i-built-a-semantic-cache-that-cuts-llm-api-costs-by-72-what-actually-worked-and-what-didnt-19ia)
- [Promethium: Building AI Agents That Don't Hallucinate on Enterprise Data](https://promethium.ai/guides/building-ai-agents-that-dont-hallucinate-enterprise-data/)
- [Atlan: AI Agent Risks and Guardrails 2026](https://atlan.com/know/ai-agent-risks-guardrails/)
- [Coalesce: Semantic Layers in 2025 Playbook](https://coalesce.io/data-insights/semantic-layers-2025-catalog-owner-data-leader-playbook/)
- [Portkey: Complete Guide to LLM Observability 2026](https://portkey.ai/blog/the-complete-guide-to-llm-observability/)
- [MLflow: Top 5 Agent Observability Tools 2026](https://mlflow.org/top-5-agent-observability-tools/)
- [Strata.io: Human in the Loop Agentic AI 2026](https://www.strata.io/blog/agentic-identity/practicing-the-human-in-the-loop/)
- [Quinnox: Data Governance for AI 2025](https://www.quinnox.com/blogs/data-governance-for-ai/)
- [Kiteworks: Zero Trust AI Data Privacy 2025](https://www.kiteworks.com/cybersecurity-risk-management/zero-trust-ai-data-privacy-protection-guide/)
- [CMSWire: Trust is the New AI Benchmark 2026](https://www.cmswire.com/digital-experience/2026-the-year-user-experience-finally-rewrites-the-rules-of-ai/)
- [LLM Cost Optimization 80% reduction (PreMAI 2026)](https://blog.premai.io/llm-cost-optimization-8-strategies-that-cut-api-spend-by-80-2026-guide/)