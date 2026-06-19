## Multi-Agent Factory: Scaling Specialist Sub-Agents - State of the Art (2025-2026)

---

### Key Findings

**1. Supervisor + Specialists is now the dominant pattern for analytics agents.** LangGraph's `create_supervisor` (langgraph-supervisor 0.0.x, GA 2025) implements a router-LLM that delegates to named sub-agents declared as a list. Sub-agents are registered by name + description; the supervisor picks by name. [https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/)

**2. "Agents as tools" beats network-of-agents for analytics.** Each sub-agent is wrapped as a `tool` callable by the supervisor. OpenAI's Swarm (now `swarm`/`openai-agents`), Google's ADK `AgentTool`, and LangGraph all converge here. The supervisor never hard-codes routing logic - it uses the tool description to route. This is exactly what OWIsMind's orchestrator already does (`ask_revenue_expert`). The pattern scales: adding a new agent = adding one tool. [https://openai.github.io/openai-agents-python/](https://openai.github.io/openai-agents-python/)

**3. Declarative agent registries are the industrialized form.** Production systems (Salesforce Agentforce, AWS Bedrock Agent Collaboration, LlamaIndex AgentRegistry) store agent spec as structured metadata (name, domain, description, dataset pointers, prompt template, tools list, examples) and load at runtime. The router then selects based on semantic similarity or keyword matching over descriptions, not hardcoded if/else. [https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html](https://docs.aws.amazon.com/bedrock/latest/userguide/agents-multi-agent-collaboration.html)

**4. One generic NL2SQL engine + per-domain semantic config is proven at scale.** dbt MetricFlow, Cube.dev, and Snowflake's semantic views all demonstrate the pattern: domain configs declare metrics, dimensions, relationships; a shared SQL compiler executes against any. The insight for OWIsMind: the revenue sub-agent's SQL engine is already generic - the semantic model config IS the per-domain tuning artifact. [https://docs.getdbt.com/docs/build/metricflow-time-spine](https://docs.getdbt.com/docs/build/metricflow-time-spine)

**5. Golden-query eval harnesses compress calibration from weeks to days.** Teams at Databricks, EvenUp, and Weights & Biases publish patterns where 20-50 golden (question, SQL, expected_result) pairs per domain enable automated regression. LLM-as-judge + exact-match on values catches regressions on every commit. [https://www.databricks.com/blog/llm-evaluation-for-icl](https://www.databricks.com/blog/llm-evaluation-for-icl)

---

### Feature / Pattern Taxonomy

#### A. Supervisor / Registry Patterns

| Pattern | Implementation | Key field |
|---|---|---|
| Agents-as-tools | LangGraph `create_supervisor`, OpenAI Agents SDK `handoff` | Tool description = routing signal |
| Declarative registry | JSON/YAML per agent: `{name, domain, dataset, description, prompt_template, tools[], examples[], guardrails{}}` | Domain field drives supervisor routing |
| Dynamic registration | Registry loaded at startup; adding a JSON file = new agent, zero code change | Hot-reload via file-watch or DB row |
| Capability-based routing | Supervisor embeds all agent descriptions in system prompt; picks by semantic match, not if/else | Scales to ~15 agents before context bloat |
| Two-tier routing | Coarse classifier (regex/keyword) -> fine LLM router; cheap first hop keeps latency low | Used in Salesforce Agentforce, Vertex AI |

LangGraph tutorial (supervisor pattern): [https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/](https://langchain-ai.github.io/langgraph/tutorials/multi_agent/agent_supervisor/)

Microsoft AutoGen `GroupChat` with `SelectorGroupChat` is an alternative for round-robin + selector patterns: [https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html](https://microsoft.github.io/autogen/stable/user-guide/agentchat-user-guide/selector-group-chat.html)

#### B. Semantic-Layer-Driven NL2SQL at Scale

The reuse mechanism that makes per-domain cost near-zero:

- **dbt MetricFlow**: metrics declared in YAML (`metric:`, `dimensions:`, `measure:`); a single compiler generates SQL for any warehouse. New domain = new `.yml` file. [https://docs.getdbt.com/docs/build/about-metricflow](https://docs.getdbt.com/docs/build/about-metricflow)
- **Cube.dev semantic layer**: `cube()` definitions with `measures`, `dimensions`, `joins`; NL2SQL via Cube's AI API hits this layer, never raw tables. Multi-tenant / multi-domain by design. [https://cube.dev/blog/introducing-cube-ai](https://cube.dev/blog/introducing-cube-ai)
- **Snowflake Cortex Analyst + semantic views**: declare metrics in SQL views; Cortex Analyst routes NL to semantic view, not raw table. GA 2025. [https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-analyst)
- **Malloy**: open-source (Google), composable semantic model, runs on DuckDB/BigQuery/Postgres. Relevant if OWIsMind ever needs portable semantics outside DSS. [https://malloydata.dev](https://malloydata.dev)

OWIsMind relevance: each new sub-agent gets a semantic model config (entities, metrics, golden queries, value index) in DSS. The generic SQL engine + semantic model API (`project.get_semantic_model()`) is already the right abstraction - the delta per new domain is only the semantic config JSON and a value index dataset.

#### C. Cheap Calibration: Golden Queries + Automated Grounding

**Golden-query eval harness** (proven pattern, EvenUp/Databricks/Braintrust):
1. Data profiler auto-generates candidate questions from column names + value samples (5-10 q per metric/dimension pair).
2. Human domain expert reviews, picks 20-50, writes expected SQL or expected answer.
3. CI runs: LLM generates SQL -> execute -> compare result. LLM-as-judge for free-form answers.
4. Regression blocks merges. Braintrust, RAGAS, and LangSmith all support this loop. [https://www.braintrust.dev/docs/guides/evals](https://www.braintrust.dev/docs/guides/evals)

**Value index** (OWIsMind already has this): pre-materialized distinct values per column, searchable by the sub-agent. Eliminates hallucinated filter values - the single biggest NL2SQL failure mode. Teams at Retool and Vanna.ai confirm this is the #1 grounding technique. [https://vanna.ai/docs/](https://vanna.ai/docs/)

**Self-checking / critic loop**: sub-agent executes SQL, checks `rowcount > 0 and not all-null`, re-prompts itself once if suspect. LangGraph `should_continue` node handles this without extra LLM calls on the happy path.

**Automated schema profiling**: `information_schema` + sample queries auto-populate semantic model entity descriptions. Reduces cold-start prompt engineering per domain. Pattern from dbt-osmosis and Great Expectations.

#### D. Declarative Agent Spec Schema (Synthesized from the Wild)

```json
{
  "agent_id": "tickets_agent",
  "label": "Support Tickets Expert",
  "domain": "customer_support",
  "description": "Answers questions about ticket volume, CSAT, resolution time, escalations.",
  "dataset": "OWISMIND_DEV_support_tickets",
  "semantic_model_id": "<DSS model id>",
  "value_index_dataset": "OWISMIND_DEV_tickets_value_index",
  "prompt_template": "prompts/tickets_expert.txt",
  "tools": ["revenue_semantic_query", "attribute_lookup"],
  "golden_queries": "evals/tickets_golden.jsonl",
  "guardrails": {
    "max_rows": 500,
    "read_only": true,
    "allowed_tables": ["support_tickets", "ticket_categories"]
  },
  "capabilities": ["ticket_volume", "csat", "resolution_time"],
  "enabled": true
}
```

Fields seen across Agentforce, Bedrock agent specs, and LlamaIndex `AgentRegistry`: name/id, description (routing signal), domain/capability list, dataset/tool pointers, prompt template ref, golden query ref, guardrails block. The description field is load-bearing - it IS the routing decision for the supervisor.

#### E. Anti-Patterns When Scaling Agent Count

| Anti-pattern | Symptom | Mitigation |
|---|---|---|
| Tool overload | Supervisor picks wrong agent; accuracy degrades above ~12 tools | Two-tier routing (coarse keyword -> fine LLM); group agents by domain cluster |
| Routing ambiguity | "revenue from tickets" hits both revenue and tickets agent | Explicit `out_of_scope` list per agent; negative examples in description |
| Context bloat | Full agent specs in supervisor prompt -> token cost grows linearly | Store specs in vector index; retrieve top-k by query embedding before routing |
| Per-agent prompt drift | 10 agents, 10 slightly different prompt conventions -> hard to maintain | Single shared prompt template with `{{domain_block}}` substitution; domain block = 1-2 paragraphs |
| No regression safety net | New golden queries never added; old ones drift | Require >=5 golden queries per PR touching a sub-agent; CI enforces |
| Hardcoded capability list | Adding agent requires code change to orchestrator | Registry-driven: supervisor reads `enabled_agents` from DB/config at startup |

Source on tool overload and routing research: [https://arxiv.org/abs/2402.05120](https://arxiv.org/abs/2402.05120) (ToolNet, 2024); [https://arxiv.org/abs/2404.11584](https://arxiv.org/abs/2404.11584) (AgentBench scaling analysis, 2024).

---

### Concrete Recommendations for OWIsMind

1. **Formalize the agent spec schema now** (before adding agent #2). Store it in `enabled_agents` JSON rows (already in `webapp_settings_v1`). Fields: `agent_id`, `domain`, `description`, `semantic_model_id`, `value_index_dataset`, `prompt_template`, `capabilities[]`, `golden_queries_path`, `guardrails{}`. The supervisor reads this at startup - adding a new agent = inserting a row + dropping a semantic model config + a prompt file.

2. **Extract the revenue sub-agent into a template** (`specialist_template.py`): domain-specific config injected at init, generic SQL/semantic loop reused verbatim. New specialist = subclass or config-driven instantiation, ~50 lines of domain-specific code.

3. **Build a golden-query CI harness now** (Python 3.9 compatible, no new installs: `unittest` + `subprocess` to hit DSS semantic tool). Target: 20 golden pairs for revenue (already partially done with 267 tests), then require 15+ per new domain before merge.

4. **Use two-tier routing for the orchestrator**: regex/keyword pre-filter (`if "ticket" in q_lower: candidate = "tickets_agent"`) as first hop, LLM as tiebreaker. This stays cheap as agent count grows and avoids context bloat.

5. **Value index is non-negotiable per new domain**: run `SELECT DISTINCT col, COUNT(*) FROM table GROUP BY col` at setup time, store in `<domain>_value_index`. The generic `attribute_lookup` tool (already built) then works for free across all domains.

6. **Keep agent descriptions short but discriminative** (2-3 sentences, domain + anti-domain): `"Answers questions about support tickets, CSAT scores, and resolution times. Does NOT answer revenue, billing, or opportunity questions."` - the negative clause is as important as the positive for routing accuracy.