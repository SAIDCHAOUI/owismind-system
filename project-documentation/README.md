# OWIsMind - Project documentation (portal)

> Audience: everyone (users, frontend and backend developers, agent engineers,
> admins/operators). Last updated: 2026-06-19. Summary: this portal introduces OWIsMind in
> a few lines, directs each audience to its entry point, and maps the entire
> documentation set.

## OWIsMind in three lines

OWIsMind is a **business-oriented agentic chat portal** packaged as a **Dataiku DSS** plugin (id `owismind`,
version `0.0.1`): a **Vue 3** webapp served as static assets by DSS, backed by a **Flask** backend
that talks to **LLM Mesh** agents and stores conversations in **direct SQL** on PostgreSQL.
The business user asks a question in natural language (primarily about telecom revenue,
`DRIVE_Revenues`) and gets a quantified answer, **without writing any SQL**. The promise is not text
generation but **trust through evidence**: a differentiating trio of **Conversation + Live
Execution Timeline + Evidence Studio**, where every figure comes from a real, inspectable SQL result.

## Where to start based on your profile

Pick your row in the map below: it points to the first page to read, then to the
sections to explore next.

| Audience | Start with | Then explore |
|---|---|---|
| **User** (analyst, salesperson, manager) | [Getting started](01-user-guide/01-getting-started.md) | [Using the chat](01-user-guide/02-using-the-chat.md), [Understanding the results](01-user-guide/03-understanding-evidence.md), [FAQ and troubleshooting](01-user-guide/04-faq-and-troubleshooting.md), [My account and budget](01-user-guide/05-account-and-budget.md) |
| **Admin** (enables agents, sets budgets) | [Agents and Administration](01-user-guide/06-agents-and-administration.md) | [Getting started](01-user-guide/01-getting-started.md), [Installation and configuration](06-operations/01-installation-and-configuration.md), [Security and validation](04-backend/06-security-and-validation.md) |
| **Frontend developer** | [Frontend - overview](03-frontend/01-overview-and-structure.md) | [State and stores](03-frontend/02-state-and-stores.md), [Components and views](03-frontend/03-components-and-views.md), [Backend communication](03-frontend/04-backend-communication.md), [Build and assets](03-frontend/05-build-and-assets.md) |
| **Backend developer** | [Backend - overview](04-backend/01-overview-and-structure.md) | [API reference](04-backend/02-api-reference.md), [Streaming and runs](04-backend/03-streaming-and-runs.md), [Storage and data model](04-backend/04-storage-and-data-model.md), [Evidence and artifacts](04-backend/05-evidence-and-artifacts.md), [Security and validation](04-backend/06-security-and-validation.md) |
| **Agent engineer** | [Agent system - overview](05-agents/01-agent-system-overview.md) | [Orchestrator](05-agents/02-orchestrator.md), [Revenue sub-agent](05-agents/03-revenue-expert-subagent.md), [Tools and Semantic Model](05-agents/04-tools-and-semantic-model.md), [Recipes and grounding](05-agents/05-flow-recipes-and-grounding.md), [Models, prompts and LLM Mesh](05-agents/06-models-prompts-and-llm-mesh.md), [Deploying and editing the agents](05-agents/07-deploying-and-editing-agents.md) |
| **Admin / operator** | [Installation and configuration](06-operations/01-installation-and-configuration.md) | [Build, packaging and deployment](06-operations/02-build-package-deploy.md), [Monitoring and logs](06-operations/03-monitoring-and-logs.md), [Runbooks](06-operations/04-runbooks.md) |
| **Architect / technical decision-maker** | [Architecture overview](02-architecture/01-system-overview.md) | [Component map](02-architecture/02-component-map.md), [Runtime flows](02-architecture/03-runtime-flows.md), [Security model](02-architecture/04-security-model.md), [Architecture decisions (ADR)](08-decisions/README.md) |

The system context diagram (the four layers) lives in the
[Architecture overview](02-architecture/01-system-overview.md). To understand how the
four layers talk to each other at runtime (a complete chat turn), see the
[Runtime flows](02-architecture/03-runtime-flows.md).

## Documentation tree

Each folder below groups a family of documents. One sentence per folder; the link leads to its
entry document.

| Folder | What you find there |
|---|---|
| [`00-overview/`](00-overview/01-product-overview.md) | Product overview: problem solved, differentiating trio, scope and limitations, glossary. |
| [`01-user-guide/`](01-user-guide/01-getting-started.md) | User guide: getting started, using the chat, reading the results (Evidence), FAQ, account and budget, agents library and Administration. |
| [`02-architecture/`](02-architecture/01-system-overview.md) | Architecture: the four layers, component map, runtime flows, security model, technical stack. |
| [`03-frontend/`](03-frontend/01-overview-and-structure.md) | Vue 3 + Vite frontend: structure, Pinia stores, components, backend communication, build and assets. |
| [`04-backend/`](04-backend/01-overview-and-structure.md) | Flask backend: structure, API reference, streaming/runs, SQL storage, Evidence/artifacts, security. |
| [`05-agents/`](05-agents/01-agent-system-overview.md) | Agent system: orchestrator, revenue sub-agent, tools and Semantic Model, recipes/grounding, models, deployment. |
| [`06-operations/`](06-operations/01-installation-and-configuration.md) | Operations: installation/configuration, build-package-deploy, monitoring/logs, incident runbooks. |
| [`07-testing/`](07-testing/01-test-strategy.md) | Testing: strategy (pure-logic suites, NO INSTALL, what requires DSS) and agent evaluation. |
| [`08-decisions/`](08-decisions/README.md) | Architecture decisions (ADR): the 15 structuring choices and their rationale. |
| [`09-maintenance/`](09-maintenance/01-contributing-and-conventions.md) | Maintenance: contribution conventions, repository map, known pitfalls and lessons. |

## Canonical identifiers

To be quoted as-is throughout the documentation (verified in `Plugin/owismind/plugin.json` and
`Plugin/owismind/webapps/webapp-owismind-ai-agents/webapp.json`):

| Element | Value |
|---|---|
| Plugin id (version) | `owismind` (`0.0.1`) |
| WebApp | `webapp-owismind-ai-agents` |
| python-lib package | `owismind` |
| resource folder | `owismind-app` |
| API prefix (health) | `/owismind-api` (`/owismind-api/ping`) |
| SQL connection | `SQL_owi` (PostgreSQL, schema `public`) |
| Project key | `OWISMIND_DEV` (resolved server-side) |
| Flask backend | Python 3.9.23 |
| Code Agents (orchestrator + sub-agent) | Python 3.11 env |
| Platform | DSS 14.4.x |

The two Code Agents carry the canonical names `OWIsMind_orchestrator` (orchestrator) and
`SalesDrive_revenue_expert` (revenue sub-agent, `agent:bHrWLyOL`). The old names
(`orchestrator_agent.py`, `dataset_expert_langgraph.py`, `agent:AKQaQ0Am`) are remnants of
earlier renamings: do not reuse them.

## Key conventions (read before contributing)

A few rules govern all the documentation and all the code. The full detail lives in
[Contributing - conventions and rules](09-maintenance/01-contributing-and-conventions.md).

- **Language**: this documentation set is written in **English** (the owner's decision); every code
  identifier (file names, functions, tables, columns, config ids) stays in **English VERBATIM**, never
  translated. The legacy `docs/` and `memory/` folders remain in French.
- **Typographic rule #9 (NON-NEGOTIABLE)**: the em dash (U+2014) and the en dash
  (U+2013) are banned everywhere. Use `-`, `:`, `,` or parentheses. It is an AI signature
  forbidden by the project.
- **The repository is the source of truth** for the agents: the two Code Agents are **re-pasted by hand**
  from `dataiku-agents/` into DSS (3.11 env). In case of conflict between the historical guides
  (`docs/`) and the code, the **code prevails**.
- **Never edit the generated folders**: `Plugin/owismind/resource/owismind-app/` and
  `Plugin/ready-for-dataiku/` are produced by the build and the packaging; you edit the sources
  (`frontend/src`, `python-lib`, `webapps`) then rebuild. `body.html` is re-wired by the build.
- **NO INSTALL**: the documentation never proposes a dependency-installation command as a
  normal step; only the user installs.
- **DSS instance safety**: direct SQL only, parameterized queries, read-only and bounded,
  explicit `COMMIT`; no Flow at runtime (except the write-only trace), no generic SQL route
  exposed, and the frontend never chooses table/connection/query.

## Points in flux (as of 2026-06-19)

The agent layer (`dataiku-agents/`) is currently being edited. Several UI and backend features are
built and packaged but not yet confirmed in DSS. The relevant pages document each item explicitly.

> IN FLUX: the `attribute_lookup` tool (`dataiku-agents/tools/attribute_lookup_tool.py`) is BUILT,
> unit-tested, and wired as a built-in tool of the ORCHESTRATOR. Its predecessor, the managed
> `dataset_lookup` tool (`9FEzVZk`) and the `lookup` intent, were REMOVED on 2026-06-18. The
> `LOOKUP_TOOL_ID` constant remains empty until the Custom Python tool is created in DSS and its
> id filled in. See ADR-0010.

> IN FLUX: the monthly budget quota (50 USD/user/month) is fully implemented - storage
> (`webapp_usage_monthly_v1`, `webapp_user_quota_v1`) AND server-side enforcement (HTTP 402 gate
> at `/chat/start`, fail-open) - but not yet validated in DSS (backend restart required after
> python-lib upload). See ADR-0014 and [My account and budget](01-user-guide/05-account-and-budget.md).

> IN FLUX: the Orange charter UI refactor (zip `index-BHeG2NRY.js`, 79 entries) is built and
> packaged but not yet confirmed in DSS. See ADR-0015.

> ROADMAP: `DRIVE_Revenues_Value_Catalog` and the Python resolver `Drive_Revenues_resolve_filter_value`
> are NOT wired in v3. The per-mode LLM Mesh ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`,
> `SONNET_ID`) must match the instance connection; a wrong id breaks the corresponding mode.

## See also

- [Product overview](00-overview/01-product-overview.md) - the problem solved, the differentiating trio, the value.
- [Getting started](01-user-guide/01-getting-started.md) - open the app and ask your first question.
- [Architecture overview](02-architecture/01-system-overview.md) - the four layers and the system context.
- [Installation and configuration](06-operations/01-installation-and-configuration.md) - deploy the plugin and connect the storage.
- [Architecture decisions (ADR)](08-decisions/README.md) - the index of structuring choices.
