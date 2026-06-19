# Technology stack and dependencies

> Audience: Developer. Last updated: 2026-06-19. Summary: an exact inventory of the languages,
> frameworks and versions across OWIsMind's four layers (Vue/Vite frontend, Flask Python 3.9 backend,
> LangGraph Python 3.11 agents, PostgreSQL storage), an explanation of the dual 3.9/3.11 code environment
> and of the NO INSTALL rule that governs all dependency management.

OWIsMind is a Dataiku DSS plugin organized into four layers that share neither their runtime nor their
dependency chain. Understanding the stack starts with understanding that these layers live in distinct
execution environments: a built Vue SPA served as static assets, a Flask backend on the DSS Python 3.9, two
LangGraph Code Agents on a separate Python 3.11 code env, and PostgreSQL storage reached through direct SQL.
The structuring NO INSTALL rule (the agent never installs a dependency) explains several non-obvious choices,
among them the fact that the built frontend is versioned in the repository. For the high-level overview of the
layers and their interactions, see
[Architecture overview](01-system-overview.md); for the module map,
[Component map](02-component-map.md).

---

## 1. Synthetic view of the four layers

| Layer | Language / runtime | Main frameworks | Deployment | In the zip |
|---|---|---|---|---|
| Frontend | JavaScript (ES modules), Node for the build | Vue 3.5, Vite 8, Pinia 3, vue-router 5, vue-i18n 11 | Built into static assets under `resource/owismind-app/`, served by DSS | The BUILD (`resource/owismind-app/`), never the `frontend/` sources |
| Backend | Python 3.9.23 (observed in DSS) | Flask (via `dataiku.customwebapp`), direct SQL `SQLExecutor2` | `python-lib/owismind/` package in the zip, restart the backend after upload | Yes |
| Agents | Python 3.11 (separate DSS code env) | LangGraph, LangChain v1, native LLM Mesh calls | Code Agents pasted by hand from `dataiku-agents/agents/` | No (outside the zip) |
| Storage | PostgreSQL (DSS connection `SQL_owi`) | Reached via `SQLExecutor2`, parameterized queries, explicit COMMIT | Tables prefixed `OWISMIND_DEV_owismind_...`, created on first use | No (external) |

Canonical identifiers of the stack: plugin id `owismind` (version `0.0.1`, source of truth
`Plugin/owismind/plugin.json`), webapp `webapp-owismind-ai-agents`, python-lib package `owismind`, resource
folder `owismind-app`, API prefix `/owismind-api` (health `/owismind-api/ping`), SQL connection `SQL_owi`
(PostgreSQL, schema `public`), project key `OWISMIND_DEV` resolved server-side, DSS platform 14.4.x.

---

## 2. Frontend: Vue 3 + Vite

### 2.1 Exact versions

The frontend is a Vue 3 SPA under `Plugin/owismind/frontend/`. The
`Plugin/owismind/frontend/package.json` file pins the versions (`dependencies` / `devDependencies` fields):

| Dependency | Declared version | Role |
|---|---|---|
| `vue` | `^3.5.34` | Framework, Composition API and `<script setup>` |
| `pinia` | `^3.0.4` | State management (setup stores) |
| `vue-router` | `^5.1.0` | Routing in HASH mode (`createWebHashHistory`) |
| `vue-i18n` | `^11.4.4` | FR/EN i18n, `legacy:false` (Composition API) |
| `chart.js` | `^4.5.1` | Interactive charts in the Evidence panel (artifacts) |
| `markdown-it` | `^14.2.0` | Markdown rendering of agent responses |
| `dompurify` | `^3.4.8` | Sanitization of markdown HTML (the only `v-html` path) |
| `@vitejs/plugin-vue` | `^6.0.6` | Vue plugin for Vite (devDependency) |
| `vite` | `^8.0.12` | Bundler / dev server (devDependency) |

The `package.json` declares `"type": "module"` (native ES modules). No other dependency is present:
in particular, no test framework is installed (no Vitest). This is a choice tied to NO INSTALL,
detailed in section 5.

### 2.2 Why this core set of dependencies

Each dependency carries a precise responsibility rather than an accumulation of convenience:

- `vue` + `pinia` + `vue-router` + `vue-i18n` form the classic SPA foundation. The router runs in HASH
  mode (`createWebHashHistory`) because the DSS webapp is served at a fixed URL with no server-side SPA
  rewrite: a path-based history would yield a 404 on reload or deep-link. The detail of this choice lives
  in [ADR-0001](../08-decisions/0001-vue-spa-servie-par-dss.md).
- `markdown-it` renders the agent responses (markdown), and `dompurify` sanitizes them: rendering goes
  through `markdown-it` with `html:false` then DOMPurify, which is the only authorized `v-html` path. The
  pair guarantees that no uncontrolled HTML coming from a model reaches the DOM.
- `chart.js` (imported as `chart.js/auto`) renders the interactive charts of the Evidence Studio panel. The
  chart payload is built on the backend side (Python), not on the front: the front only renders an
  already-secured spec.

On the build side, `vite` and `@vitejs/plugin-vue` suffice: the Vite config
(`Plugin/owismind/frontend/vite.config.js`) fits in a few lines and fixes two canonical names,
`base: '/plugins/owismind/resource/owismind-app/'` and `build.outDir: '../resource/owismind-app'`
(with `emptyOutDir: true`). These two names are never changed without a full rebuild and re-wiring of
`body.html`. The build pipeline detail lives in
[Frontend - build and assets](../03-frontend/05-build-and-assets.md) and
[Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

### 2.3 Node to build, not to serve

Node is used ONLY to build (and for the local dev server outside DSS). In production, DSS serves the
build output (content-hashed assets under `resource/owismind-app/assets/`) as static files; there is no
server-side Node runtime. The DSS webapp injects the `dataiku` lib, which exposes
`window.getWebAppBackendUrl(path)`; the backend client (`services/backend.js`) resolves this function
lazily, and no URL is hardcoded.

---

## 3. Backend: Flask on Python 3.9.23

### 3.1 Version and frameworks

The backend is a Flask module under `Plugin/owismind/python-lib/owismind/`. The runtime observed in DSS
(via `/owismind-api/ping`) is **Python 3.9.23**: this is the DSS webapp environment, and the project rule
is explicit (rule #8) - do not assume that Python 3.11 or FastAPI work here. The rule is
restated in `Plugin/owismind/python-lib/CLAUDE.md`: "observed backend is 3.9.23 (Flask)".

The backend does NOT bundle langchain or langgraph: it only does Flask plus direct SQL. Its runtime stack
reduces to:

| Element | Detail |
|---|---|
| Runtime | Python 3.9.23 (DSS webapp env) |
| Web framework | Flask, provided by DSS via `from dataiku.customwebapp import *` (the `app` object) |
| SQL access | `dataiku.SQLExecutor2`, a fresh executor per call, parameterized values, explicit COMMIT |
| SQL parameterization | `from dataiku.sql import Constant, toSQL, Dialects` |
| LLM Mesh | Reached through the Code Agents (resolved by whitelist), via the native LLM Mesh API |

The entry point is thin: `Plugin/owismind/webapps/webapp-owismind-ai-agents/backend.py` merely
imports `register_routes` from `owismind.api.routes` and calls it. DSS injects the Flask `app` object
through the `customwebapp` star-import. Everything else is in `python-lib/owismind/`, organized into
sub-packages (`agents`, `api`, `evidence`, `security`, `storage`). The detailed structure lives in
[Backend - overview and structure](../04-backend/01-overview-and-structure.md).

### 3.2 Why no FastAPI or additional framework

The backend stays deliberately minimal. Flask is imposed by DSS (the STANDARD webapp provides the Flask
`app` object), and the code adds no layer on top of it: no ORM (storage is in parameterized direct SQL,
no Flow at runtime), no third-party HTTP client, no agent library. This sobriety
serves two goals: the safety of the Dataiku instance (no heavy or unbounded work in the handlers)
and portability on the DSS Python 3.9, where recent agent libraries are in any case
not installable. Chat streaming is carried by a worker thread and polling, not by an asynchronous
framework; see [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md).

---

## 4. Agents: LangGraph on Python 3.11 (the dual environment)

### 4.1 Versions and frameworks

The two Code Agents live in `dataiku-agents/agents/` (the repository is the source of truth):
`OWIsMind_orchestrator.py` (the orchestrator) and `SalesDrive_revenue_expert.py` (the revenue expert
sub-agent, `agent:bHrWLyOL`). They are pasted by hand into DSS Code Agents, on a **Python 3.11 code
env** distinct from the backend.

Their import stack is strictly standalone: stdlib plus `dataiku` plus `langchain`/`langgraph`,
**no import of the plugin**. This is verifiable in the header of `OWIsMind_orchestrator.py`, which only
imports `json`, `logging`, `operator`, `queue`, `re`, `threading`, `time`, `concurrent.futures`, `datetime`,
`typing`, then `dataiku`, `dataiku.llm.python.BaseLLM`, and from LangGraph
`StateGraph, START, END` plus `get_stream_writer`. The sub-agent follows the same pattern
(it only adds `difflib`, `math`, `unicodedata` on the stdlib side). This autonomy is what makes the
copy-paste possible: an agent file depends on nothing other than its 3.11 env and DSS.

| Element | Detail |
|---|---|
| Runtime | Python 3.11 (separate DSS code env, where langchain/langgraph are installed) |
| Agent framework | LangGraph (StateGraph, sync nodes, `get_stream_writer`), LangChain v1 |
| Model calls | Native LLM Mesh API (`project.get_llm(id).new_completion()`), NEVER `as_langchain_chat_model` |
| DSS tools | `project.get_agent_tool(id).run()` (e.g. the Semantic Model Query tool `v4oqA6R`) |
| Imports | stdlib + `dataiku` + `langchain`/`langgraph` only, zero import of the plugin |

Important architectural note: even though the agents use LangGraph, model calls are made
NATIVELY through LLM Mesh (`new_completion()`), not via the `as_langchain_chat_model` adapter. This is a
deliberate decision that preserves the model's reasoning and tool-calling; see
[ADR-0006](../08-decisions/0006-appels-natifs-llm-mesh.md). A corollary: `with_json_output` is never
forced on the orchestrator (in DSS 14 it silently disables reasoning), but it IS used on
the sub-agent's deterministic extractions (the UNDERSTAND step); see
[ADR-0007](../08-decisions/0007-json-output-force-sur-understand.md).

### 4.2 Why two Python environments (3.9 and 3.11)

This is the "dual path" of the OWIsMind stack, and it is a platform constraint, not a whim:

- The Flask backend runs on the DSS webapp Python **3.9.23** env. This is what is observed on
  the instance, and the code there is limited to Flask plus direct SQL.
- LangGraph / LangChain v1 require Python **>= 3.10**. langgraph therefore cannot be placed in the
  backend's 3.9 env.

The direct consequence: the agents must live in a separate 3.11 code env, and their deployment is done
by copy-pasting into DSS Code Agents rather than through the plugin zip. An agent-only change never
touches the zip; the webapp resolves the orchestrator by its whitelist key (the sub-agent is resolved
by id `agent:bHrWLyOL` on the orchestrator side). This separation is formalized in
[ADR-0005](../08-decisions/0005-langgraph-code-agents-python-311.md), and the deployment procedure (re-paste
BOTH Code Agents, check the ids) lives in
[Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

### 4.3 Per-mode model ids (LLM Mesh)

The loop models are selected by the user mode (eco / medium / high), a single model
driving the entire turn (no escalation). The ids are declared VERBATIM at the top of each agent
(`OWIsMind_orchestrator.py`, constants `GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`, mapped
in `LOOP_LLM_BY_MODE`):

| Mode | Constant | LLM Mesh id (verbatim) | Model |
|---|---|---|---|
| eco (default) | `GEMINI_FLASH_LITE_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite` | Gemini 3.1 Flash-Lite |
| medium | `GEMINI_FLASH_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash` | Gemini 3.5 Flash |
| high | `SONNET_ID` | `openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6` | Claude Sonnet 4.6 |

> IN FLUX: these ids must match an id actually exposed by the instance's LLM Mesh connection. A wrong id
> breaks the corresponding mode (the mode stops responding). They must be re-checked in DSS after each
> re-paste of the Code Agents. The `dataiku-agents/` folder is moreover being edited live by another
> engineer: the managed `dataset_lookup` tool (`9FEzVZk`) and its `lookup` intent were REMOVED on
> 2026-06-18, and their replacement `attribute_lookup` (`tools/attribute_lookup_tool.py`) is BUILT and
> unit-tested, now wired as a built-in tool of the orchestrator but with `LOOKUP_TOOL_ID` still
> empty (not operational until the tool is created in DSS). The detail lives in
> [Agent tools and Semantic Model](../05-agents/04-tools-and-semantic-model.md).

The Semantic Model Query tool (`revenue_semantic_query`, `v4oqA6R`), which actually writes the analytical
SQL, stays on its own strong model (Sonnet) in ALL modes, independently of the loop mode. The detail
of the models, prompts and control tokens (`⟦owi:mode=…⟧`, `⟦owi:lang=…⟧`) lives in
[Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md).

---

## 5. Dependency management: the NO INSTALL rule

### 5.1 The principle

NO INSTALL is the project's structuring rule #1: the agent (the assistant) NEVER installs a dependency.
No install command is run, neither on the frontend side (`npm install`/`ci`/`i`/`add`, `yarn`, `pnpm`),
nor on the Python side (`pip`/`pip3 install`, `pipenv`, `poetry`, `conda`), nor system (`brew`), nor `npx` install.
Only the user installs (safety first). The documentation therefore never proposes an install command
as a "normal" step: when a dependency is missing, we stop and ask the user.

This guardrail is enforced at three levels (defense in depth):

1. **Harness permissions**: `.claude/settings.json` lists each install command in
   `permissions.deny`, and blocks direct writing (`Edit`/`Write`) to the built frontend
   `resource/owismind-app/`.
2. **PreToolUse hook**: `.claude/hooks/guardrail.sh` intercepts any `Bash` whose command matches an
   install (regex covering npm/yarn/pnpm/pip/pipenv/poetry/conda/brew/npx) and BLOCKS (exit 2). It is pure
   bash plus grep on the raw JSON, with no jq/python dependency, so it never breaks a session.
3. **Documentation and SessionStart**: the rule is recalled at session start and in all
   skills (`/build-plugin`, `/package-plugin`).

### 5.2 The non-trivial consequence: the built frontend is versioned

Because a fresh clone cannot reinstall the toolchain (NO INSTALL forbids `npm install`), the plugin
payload must travel WITHIN the repository to remain packageable. That is why `resource/owismind-app/` (the
built frontend) is **git-tracked**, even though it is a regenerated output. It is the single exception to the
usual "regeneratable outputs = ignored" philosophy. It must NEVER be edited by hand: you edit the sources
`frontend/src/` then rebuild.

| Path | Git status | Why |
|---|---|---|
| `frontend/src/**`, `webapps/**`, `python-lib/**`, `plugin.json` | tracked | plugin source |
| `resource/owismind-app/**` (built frontend) | tracked (exception) | plugin payload; NO INSTALL requires it to stay in the repository |
| `node_modules/`, `dist/`, `.vite/` | ignored | reinstallable / scratch toolchain |
| `__pycache__/`, `*.py[cod]` | ignored | Python bytecode |
| `Plugin/ready-for-dataiku/**` (the deliverable zip) | ignored | regenerated by `/package-plugin` |

### 5.3 Tests: native runners, no test dependency

NO INSTALL also explains the absence of an installed test framework. The suites are pure-logic, with no
DSS environment and no install, via native runners:

- Frontend: `node --test test/*.test.js` (the native `node:test` runner, not Vitest). Pure tests under
  `Plugin/owismind/frontend/test/`, outside `src/`, so never built or zipped.
- Backend: `python3 -m unittest discover -s Plugin/owismind/tests`. Tests outside `python-lib/`, so never
  packaged.
- Agents: `python3 -m unittest discover -s dataiku-agents/tests`. DSS-free.

These suites lock the invariants testable outside the instance; they do not replace validation IN
DSS (some modules import `dataiku`/`pandas` at load time and require the DSS Python or a stub). There
is no CI to date. The detail of the suites, their scope and what requires DSS lives in
[Test strategy](../07-testing/01-test-strategy.md).

> Test counts evolve (the repository is edited live): do not pin an exact figure. The reference
> documentation `docs/` is moreover sometimes stale on the counts (tests, zip entries); the code prevails.

---

## 6. Recap of the versions to cite

| Element | Value to cite |
|---|---|
| OWIsMind plugin | id `owismind`, version `0.0.1` |
| Platform | Dataiku DSS 14.4.x |
| Frontend | Vue `^3.5.34`, Vite `^8.0.12`, Pinia `^3.0.4`, vue-router `^5.1.0`, vue-i18n `^11.4.4`, chart.js `^4.5.1`, markdown-it `^14.2.0`, dompurify `^3.4.8` |
| Backend | Python 3.9.23, Flask (via DSS `customwebapp`), `SQLExecutor2` |
| Agents | Python 3.11, LangGraph / LangChain v1, native LLM Mesh calls |
| Storage | PostgreSQL (connection `SQL_owi`, schema `public`) |

---

## See also
- [Architecture overview](01-system-overview.md) - the four layers and the system context.
- [Component map](02-component-map.md) - the modules per layer (Pinia stores, python-lib sub-packages, recipes).
- [Security model](04-security-model.md) - trust boundary, run-as-user, agent whitelist.
- [Frontend - build and assets](../03-frontend/05-build-and-assets.md) - the Vite pipeline, body.html, hashes.
- [Backend - overview and structure](../04-backend/01-overview-and-structure.md) - Flask blueprint and sub-packages.
- [Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md) - per-mode models and native calls.
- [Build, packaging and deployment](../06-operations/02-build-package-deploy.md) - the what-to-rebuild-when matrix.
- [Test strategy](../07-testing/01-test-strategy.md) - pure-logic suites and NO INSTALL.
- [ADR-0005 - LangGraph Code Agents in Python 3.11](../08-decisions/0005-langgraph-code-agents-python-311.md) - the 3.9/3.11 dual path.
- [ADR-0006 - Native LLM Mesh calls](../08-decisions/0006-appels-natifs-llm-mesh.md) - no `as_langchain_chat_model`.
- [Contributing - conventions and rules](../09-maintenance/01-contributing-and-conventions.md) - NO INSTALL and non-negotiable rules.
