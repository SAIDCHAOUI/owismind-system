# Glossary

> Audience: everyone (both business and technical readers). Last updated: 2026-06-18.
> Summary: this document lays out, in alphabetical order, the business AND technical terms of OWIsMind,
> with a short definition, what NOT to confuse it with, and a pointer to the document that
> goes deeper on the term.

This glossary is the project's shared lexical reference. The definitions are deliberately
short: for the detail, follow the link given at the end of each entry or the
[See also](#see-also) section. Code identifiers (file names, function names, table names,
column names, configuration ids) are kept VERBATIM in English; only the explanatory text is in
English.

How to read an entry: a term, its definition, a `Do not confuse with` line when
the ambiguity is recurring, and the reference document. Items in transition at the time of
writing are flagged with an `IN FLUX` or `ROADMAP` blockquote.

---

## A

### agent_key (opaque logical key)
The key the frontend sends to the backend to designate an agent, of the form `ag_<hash>`. It is
OPAQUE: the frontend never knows the real `agent_id` (`agent:...`). The backend resolves it to
`(project_key, agent_id)` via `resolve_enabled_agent` (`storage/settings.py`), against the list of
agents an admin has enabled. A forged or stale key resolves to `None` and therefore cannot trigger
anything.
Do not confuse with: a raw `agent_id` (`agent:bHrWLyOL`), which is never accepted from the front.
Detail: [server agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md).

### AGENT_RESULT
A machine status emitted by the sub-agent in the event stream, read by the orchestrator to learn
the outcome of a delegation (status + intent). It is NOT text shown to the user.
Do not confuse with: the sub-agent's prose reply (the `answer`), which can be read by
the model. Detail: [the revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md).

### artifact
A display SPEC requested by the orchestrator through the `show_chart` / `show_table` /
`show_kpi` tools. It carries `{kind, title, chart|kpi}` but NEVER the data rows. The data is the
`result` already captured, recombined with the spec at read time (the Chart.js payload is built
on the backend by `chart_payload.py`).
Do not confuse with: the captured `result` (the DATA); an already rendered chart. Note: the code
always writes `artifact` (never "artefact"); in everyday English prose "artifact" is fine.
Detail: [Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

### attribute_lookup
A standalone Custom Python tool (`tools/attribute_lookup_tool.py`) that looks up a named value in
the revenue dataset (does it exist, in which column, what is the exact spelling, which attribute
of a record). It short-circuits the slow semantic path for simple questions such as
"who is the account manager for X".
> IN FLUX: `attribute_lookup` is BUILT and unit-tested, and now wired as a built-in tool
> of the orchestrator, but the `LOOKUP_TOOL_ID` constant is still empty (not operational until the
> Custom Python tool is created in DSS). Its predecessor, the managed tool `dataset_lookup`
> (`9FEzVZk`) and the `lookup` intent, were REMOVED on 2026-06-18: they no longer appear in
> `KNOWN_INTENTS`. Attribute lookups are therefore in transition.
Detail: [agent tools and Semantic Model](../05-agents/04-tools-and-semantic-model.md).

## B

### BUSINESS_DOMAINS
The list, in the orchestrator, of the business domains OWI considers (`revenue`, `tickets`,
`satisfaction`, `opportunities`, `delivery`, `billing`). A domain is "staffed" only when an
enabled agent covers it. This list enables the honest capability gap ("no agent yet for
tickets").
Do not confuse with: `CAPABILITIES` (the registry of actually active sub-agents). In v3, only
`revenue` is staffed. Detail: [the orchestrator](../05-agents/02-orchestrator.md).

## C

### capability / whitelist
Two related things. On the orchestrator side: the `CAPABILITIES` registry, a manifest of the active
sub-agents (one entry per specialist, single extension point). On the backend side: the server
whitelist of agents that can be enabled (persisted in `webapp_settings_v1`). The front only sends an
opaque `agent_key`; the backend and the orchestrator resolve the ids.
Do not confuse with: a raw `agent_id` (never exposed); `BUSINESS_DOMAINS` (the list of
domains, staffed or not). Detail: [the orchestrator](../05-agents/02-orchestrator.md) and
[server agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md).

### capability gap
The ONLY form of "no" the orchestrator is allowed: "there is no AGENT yet for this
domain". It is carried by the generated system prompt (a section listing the unstaffed domains).
Do not confuse with: "the data does not exist" (forbidden); a technical error; an out-of-scope
(outside the business scope). Detail: [the orchestrator](../05-agents/02-orchestrator.md).

### Code Agent
A DSS agent implemented in Python code (env 3.11), re-pasted by hand from the repository (the source of truth).
OWIsMind has exactly TWO Code Agents: the orchestrator (`OWIsMind_orchestrator`) and the sub-agent
(`SalesDrive_revenue_expert`).
Do not confuse with: the Flask backend (Python 3.9.23, never any langchain); a visual DSS agent.
Detail: [LangGraph Code Agents in Python 3.11](../08-decisions/0005-langgraph-code-agents-python-311.md).

## E

### Evidence Studio
The "evidence" panel to the right of the chat. It DETERMINISTICALLY re-derives (zero LLM call) how
a reply was produced: verification-level badge, sources, filter chips, business explanation,
exact captured result, drill-down, paginated source-table exploration, raw SQL, plus
the artifacts. The SQL stored by the agent is the source of truth; nothing new is written at
evidence time (except the artifact specs, persisted once at the end of the run).
Do not confuse with: Dataset Explorer (free exploration, possibly on a sample); a plain
SQL viewer. Detail:
[Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) and, on the user side,
[understanding the results](../01-user-guide/03-understanding-evidence.md).

### exchange (`exchange_id`)
A chat exchange = one row of the `webapp_chat_v5` table (one user turn + the assistant's reply).
Its id is a `uuid4().hex` generated in Python.
Do not confuse with: the session (`session_id`, which groups several exchanges); the run (the
generation cycle in flight). Detail:
[storage and data model](../04-backend/04-storage-and-data-model.md).

## F

### Flow
The orchestration of DSS datasets and recipes. At RUNTIME: zero Flow (the only exception is the
execution trace, appended write-only to an optional dataset). The Flow recipes run
DESIGN-TIME to build the profile and the value index.
Do not confuse with: the direct SQL runtime (`SQLExecutor2`); the Semantic Model's SQL engine.
Detail: [direct SQL, no Flow at runtime](../08-decisions/0003-sql-direct-sans-flow.md) and
[Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

## G

### grounding
Anchoring the terms typed by the user onto EXACT cell values, via read-only inline SQL
on the value index (the sub-agent's `_resolve_terms` method: exact, then normalized, then
fuzzy via `difflib`). This is the RESOLVE step of the pipeline. It is NOT a tool.
Do not confuse with: a DSS tool call; the analytical SQL engine (which actually computes the
answer). Detail: [Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

## H

### honesty firewall
The orchestrator's central rule, carried by its system prompt: emit NO unsourced business
fact; never say that a piece of data, a metric or a figure "does not exist", "is zero" or "is
unavailable" (only a specialist can say so, after searching); at most flag a
capability gap. The structural invariant that makes it credible: the orchestrator NEVER holds a
figure, so it cannot invent one.
Do not confuse with: a simple payload validation; a generic refusal. Detail:
[the orchestrator](../05-agents/02-orchestrator.md).

## L

### LLM Mesh
The DSS layer that exposes models and agents. It is called NATIVELY
(`new_completion()`, `get_agent_tool(id).run()`), never via `as_langchain_chat_model`, to preserve
the model's reasoning and tool-calling.
Do not confuse with: LangGraph (the framework that structures the Code Agents' loop, distinct from
the Mesh transport). Detail:
[native LLM Mesh calls](../08-decisions/0006-appels-natifs-llm-mesh.md) and
[models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md).

## M

### mode (eco / medium / high)
The LOGICAL key chosen by the user, which drives the loop model. A single model drives the whole
turn (no escalation, no switch mid-turn), and the mode propagates to the sub-agent.

| Mode | Loop model | Live narration |
|---|---|---|
| `eco` (default) | Gemini 3.1 Flash-Lite (`GEMINI_FLASH_LITE_ID`) | OFF (strict act-first) |
| `medium` | Gemini 3.5 Flash (`GEMINI_FLASH_ID`) | ON |
| `high` | Claude Sonnet 4.6 (`SONNET_ID`) | ON |

> IN FLUX: the LLM Mesh ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`) must match
> the instance's LLM Mesh connection; a wrong id breaks the corresponding mode (to be verified in DSS).
Do not confuse with: a raw model id (the front never sends one); the model of the Semantic
Model Query tool (which stays Sonnet in ALL modes). Detail:
[per-mode models](../08-decisions/0009-modeles-par-mode.md).

## O

### orchestrator (`OWIsMind_orchestrator`)
The LangGraph Code Agent (env 3.11), the default entry point: it converses, reasons, routes to a
sub-agent, renders chart/table/kpi in the Evidence panel, and writes the analysis in the user's
language. It NEVER holds a business figure.
Do not confuse with: the sub-agent (which does hold the figures); the Flask backend (which does not
reason). Detail: [the orchestrator](../05-agents/02-orchestrator.md).

### OWIsMind
The product: a Dataiku DSS plugin, an agentic business chat portal (id `owismind`, version
`0.0.1`). It combines a Vue 3 frontend, a Flask backend and two LLM Mesh Code Agents.
Do not confuse with: "the webapp" (which only refers to the frontend + Flask backend layer, not the
agents). Detail: [product overview](01-product-overview.md).

## P

### Phase / scenario
The `Phase` column of `DRIVE_Revenues` = the version of the measure: `ACTUALS` (default), `BUDGET`,
`FORECAST`, `Q3F`, `HLF`. Firm business rule: NEVER SUM across Phases.
Do not confuse with: the `booking_type`; a time period (`year_month`). Always `ACTUALS`
in the PLURAL, never `ACTUAL`. Detail:
[Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

### polling (streaming-by-polling)
The transport: the agent runs in a daemon worker thread (backend side, in-memory `_RUNS` dict),
and the front polls `/chat/poll` every ~500 ms. There is no SSE: a
`text/event-stream` response is buffered by the DSS proxy, so SSE was abandoned. The usable live
signal is the timeline, not a word-by-word text stream (the reply often arrives in one block at the end).
Do not confuse with: SSE (`text/event-stream`, abandoned); a word-by-word text stream. Detail:
[streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) and
[streaming by polling](../08-decisions/0002-streaming-par-polling.md).

### profile (`DRIVE_Revenues_profile`)
The "business brain" built design-time by a Flow recipe: schema, metrics, scenario column,
time column, axes, synonyms, display pairs. It can be revised by human overrides
(`DRIVE_Revenues_profile_overrides`) which always win and survive re-runs. It only sends the
LLM aggregated metadata, never raw rows.
Do not confuse with: the value index (the grounding); the Value_Catalog (roadmap). Detail:
[Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

## R

### run (`run_id`)
A generation cycle in flight on the backend side: a worker thread + a state in the `_RUNS` dict. Its
handle is an opaque `uuid4().hex`, tied to its owner so that only the owner can poll it.
Do not confuse with: the exchange (the row persisted in `webapp_chat_v5`); the session (the
conversation). Detail:
[streaming and run lifecycle](../04-backend/03-streaming-and-runs.md).

### run-as-user (backend identity)
The DSS identity under which the webapp backend runs: it is the one that actually executes the
SQL and calls the agents.
Do not confuse with: the logged-in user (the caller), resolved server-side from the browser's
authentication headers (never from the request body), and used only for application-level
scoping (a user only sees THEIR conversations). Detail:
[security model](../02-architecture/04-security-model.md).

## S

### session (`session_id`)
The conversation: it groups the exchanges and is stamped in the `/chat/<sessionId>` URL.
Do not confuse with: the exchange (one row); the conversation tree (the exchanges linked by
`parent_exchange_id` for edits and branches). Detail:
[storage and data model](../04-backend/04-storage-and-data-model.md).

### Semantic Model Query tool / `revenue_semantic_query` (`v4oqA6R`)
The ONLY real DSS tool called at runtime in v3 by the sub-agent: it WRITES AND EXECUTES the
analytical SQL on an aligned Semantic Model (strong model, Sonnet) in ALL modes.
Do not confuse with: the grounding (inline, not a tool); `resolve_filter_value` and
`dataset_sql_query` (which are event LABELS on the timeline, not tools). Detail:
[agent tools and Semantic Model](../05-agents/04-tools-and-semantic-model.md) and
[grounding and Semantic Model](../08-decisions/0010-grounding-et-semantic-model.md).

### sirano_product
The lowest technical level of the offer hierarchy (`Product` > `Solution` > `SolutionLine` >
`sirano_product`). It is NEVER the default: BUDGET rows may not carry it, which
would yield a misleading budget=0.
Do not confuse with: `Product` (the default granular level); the displayable product name.
Detail: [the revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md).

### sub-agent / revenue expert sub-agent (`SalesDrive_revenue_expert`)
The LangGraph Code Agent (env 3.11, `agent:bHrWLyOL`), the revenue specialist: pipeline UNDERSTAND ->
RESOLVE -> QUERY -> RENDER. It holds ALL the revenue figures, across all Phases.
Do not confuse with: the orchestrator; the Semantic Model Query tool (which writes the SQL, whereas
the sub-agent orchestrates it). Detail:
[the revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md).

### SQLExecutor2
The DSS direct-SQL API used by the backend: a FRESH executor per call, parameterized values
(`toSQL(Constant(value), ...)`), explicit `COMMIT` after a write. It is the only persistence
and re-read path at runtime.
Do not confuse with: the Flow; a generic SQL route (there is NONE; the front never chooses
table/connection/query). Detail:
[direct SQL, no Flow at runtime](../08-decisions/0003-sql-direct-sans-flow.md) and
[backend security and validation](../04-backend/06-security-and-validation.md).

## T

### trust layer / verification level
Evidence's deterministic scale that qualifies the reliability of a piece of evidence:
`declared` -> `source_identified` -> `scope_partial` -> `scope_exact` -> `calc_decomposed`, with an
orthogonal `result_captured` flag (stored rows present or not). The badge is NEVER green
(solid=certified / dotted=partial / gray=declared), a product choice to avoid false assurance.
Do not confuse with: an LLM confidence score; a run status. Detail:
[Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) and
[trust layer and artifacts](../08-decisions/0008-evidence-trust-layer-et-artifacts.md).

## V

### value_index (`DRIVE_Revenues_value_index`)
The `{column_name, value, value_norm, occurrences}` dataset (~3.6 k rows) queried via inline SQL
for the grounding. It MUST live on the source SQL connection, because the sub-agent queries it at
runtime.
Do not confuse with: the profile (`DRIVE_Revenues_profile`, the "business brain"); the Value_Catalog
(roadmap). Detail: [Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

### Value_Catalog (`DRIVE_Revenues_Value_Catalog`)
A richer catalog of aliases and variants (business concepts, short account names), built
design-time in the Flow.
> ROADMAP: `DRIVE_Revenues_Value_Catalog` and the associated Python resolver
> `Drive_Revenues_resolve_filter_value` are NOT wired in the v3 sub-agent (which grounds on the
> value index).
Do not confuse with: the value index (which IS used by v3); the profile. Detail:
[Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md).

---

## Canonical identifiers (reminder)

A handful of identifiers recur throughout the documentation and are cited VERBATIM:

| Identifier | What it is |
|---|---|
| `owismind` | the plugin id (version `0.0.1`) |
| `webapp-owismind-ai-agents` | the DSS webapp |
| `owismind-app` | the resource folder serving the built frontend |
| `/owismind-api` | the API prefix (health: `/owismind-api/ping`) |
| `SQL_owi` | the PostgreSQL SQL connection (schema `public`) |
| `OWISMIND_DEV` | the project key (resolved server-side) |
| `agent:bHrWLyOL` | the `agent_id` of the `SalesDrive_revenue_expert` sub-agent |
| `v4oqA6R` | the id of the `revenue_semantic_query` Semantic Model Query tool |

---

## See also
- [Product overview](01-product-overview.md) - the problem solved and the differentiating trio.
- [Scope and limitations](02-scope-and-limitations.md) - what the product does and does not do, items in flux.
- [Architecture overview](../02-architecture/01-system-overview.md) - the 4 layers situated together.
- [The orchestrator](../05-agents/02-orchestrator.md) - registry, honesty firewall, modes.
- [Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - capture, levels, chart_payload.
- [Flow recipes and grounding](../05-agents/05-flow-recipes-and-grounding.md) - profile, value index, value catalog.
- [Streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - polling, worker, `_RUNS`.
