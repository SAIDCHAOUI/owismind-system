# Repository map

> Audience: Developer. Last updated: 2026-06-18. Summary: where everything lives in the
> OWIsMind repository (DSS plugin, agents, docs, memory, Claude tooling), what is source vs generated, and
> what must never be edited by hand.

This document is an orientation map: it describes the ROLE of each important folder, its Git status
(versioned source, generated output versioned as an exception, or ignored output), and the associated
editing rule. It does not detail the internal content of each layer: for that, follow the links in the
`## See also` section. The cross-cutting golden rule: edit the SOURCE, never the OUTPUT.

## 1. Overview: four zones, three Git statuses

The repository mixes four zones of different natures:

- `Plugin/owismind/`: the Dataiku DSS plugin itself (Vue frontend, Flask backend, webapp descriptor,
  resources). This is the core deliverable.
- `dataiku-agents/`: the LangGraph Code Agents and the design-time fabrication (recipes, tools, semantic
  model). This layer is deployed SEPARATELY (copy-paste into DSS), it never goes through the zip.
- `docs/`, `memory/`: the reference engineering documentation and the project's living memory.
- `.claude/`, `graphify-out/`: the assistant's tooling (skills, hooks, permissions) and the regenerated
  knowledge graph.

Three Git statuses coexist (defined in `.gitignore`):

| Status | Meaning | Examples |
|---|---|---|
| Versioned source | Edited by hand, authoritative | `frontend/src/`, `python-lib/owismind/`, `webapps/`, `dataiku-agents/`, `docs/`, `memory/`, `.claude/settings.json` |
| Versioned generated output (exception) | Produced by a build but TRACKED because it is indispensable for packaging without a reinstall | `Plugin/owismind/resource/owismind-app/` |
| Ignored generated output | Regenerated on demand, never committed | `Plugin/ready-for-dataiku/`, `node_modules/`, `graphify-out/`, `__pycache__/` |

The central exception, explained at the top of `.gitignore`: the built frontend
`Plugin/owismind/resource/owismind-app/` IS versioned. The NO INSTALL policy forbids the assistant from
reinstalling the Vite toolchain; a fresh clone could therefore not rebuild these assets. To stay
packageable everywhere, the payload must travel inside the repository. This is the only build output we commit.

## 2. `Plugin/owismind/`: the DSS plugin

Root of the plugin on disk. The descriptor `Plugin/owismind/plugin.json` carries `"id": "owismind"` and
`"version": "0.0.1"` (to be quoted verbatim; the id never changes, on pain of breaking the Vite paths
already wired in `body.html`).

| Path | Lives here | Status | Rule |
|---|---|---|---|
| `plugin.json` | Plugin manifest (id, version, meta) | Source | Edit then re-package. |
| `frontend/` | Vue 3 + Vite SPA (sources, config, toolchain, tests) | Source (except `node_modules/`) | See section 3. NEVER in the zip. |
| `python-lib/owismind/` | Modular Flask backend (all the server logic) | Source | Edit then re-package + restart the backend. |
| `webapps/webapp-owismind-ai-agents/` | DSS webapp descriptor + backend bootstrap | Source (except `body.html`, see below) | See section 4. |
| `resource/` | Resources served by DSS (built frontend + Settings script) | Mixed (see section 5) | `owismind-app/` never edited by hand. |
| `tests/` | Pure-logic backend `unittest` suite (outside `python-lib/`) | Source | See section 6. Never packaged. |
| `CLAUDE.md` (in `python-lib/`) | Local backend engineering notes | Source | Excluded from the zip by name. |

### 2.1 `python-lib/owismind/`: the backend sub-packages

The `owismind` Python package (note the double `__init__.py`: one at the root `python-lib/owismind/` and
one per sub-package, all indispensable to the import `from owismind.api.routes import register_routes` that
`backend.py` performs). Never exclude the `__init__.py` files when packaging.

| Sub-package | Role |
|---|---|
| `api/` | The Flask blueprint and all the `/owismind-api/*` routes (`routes.py`). |
| `agents/` | Run lifecycle (`stream_manager.py`), normalization of LLM Mesh events (`streaming.py`), context suffix and modes (`context.py`), project/agent discovery (`discovery.py`). |
| `evidence/` | Evidence Studio pipeline: capture (`capture.py`), SQL parsing/explanation (`sql_parse.py`, `sql_explain.py`), query builders (`query_builders.py`), service (`service.py`), throttle (`throttle.py`), column whitelist (`whitelist.py`), Chart.js/KPI shaping (`chart_payload.py`). |
| `security/` | Identity resolution (`identity.py`) and pure payload validators (`validation.py`). |
| `storage/` | Direct PostgreSQL SQL: chat (`chat_v5.py`), admin/users (`admin.py`), agent whitelist (`settings.py`), config and naming (`sql_config.py`), idempotent DDL (`migrations.py`), pagination (`pagination.py`), safe serialization (`serialization.py`), usage/cost (`usage.py`), budget (`budget.py`), artifacts (`artifacts.py`), write-only Flow trace (`chat_traces.py`), pure SQL builders (`sql_builders.py`). |

The detailed module map by layer lives in
[the component map](../02-architecture/02-component-map.md): this table stays at the folder level, do not
redraw it as a diagram here.

## 3. `Plugin/owismind/frontend/`: the Vue SPA

Sources of the Vue 3 + Vite SPA. The toolchain (`node_modules/`) is ignored; everything else is source.
Important target: the frontend NEVER ENTERS the zip (non-negotiable rule #5); what travels inside the
plugin is its built OUTPUT under `resource/owismind-app/` (section 5).

| Path | Lives here | Status |
|---|---|---|
| `src/` | Application code: `main.js`, `App.vue`, `components/`, `views/`, `stores/`, `services/`, `router/`, `i18n/`, `styles/`, `composables/`, `registries/`, `assets/` | Source |
| `public/` | Assets copied as-is (`favicon.svg`) | Source |
| `test/` | Pure `node:test` tests (outside `src/`, without Vue or dataiku) | Source, never built/zipped |
| `vite.config.js` | CANONICAL Vite config: `base: /plugins/owismind/resource/owismind-app/`, `outDir: ../resource/owismind-app`, `emptyOutDir: true` | Source, do not change without a rebuild + re-wiring of `body.html` |
| `index.html` | Source entry HTML (`<div id="app">` + `<script src="/src/main.js">`) | Source |
| `package.json`, `package-lock.json` | Dependencies and scripts (`build`, `test`) | Source |
| `node_modules/` | Toolchain installed by the user | Ignored (NO INSTALL) |

The internal structure (bootstrap, hash router, i18n, theme, stores) is documented in the
[Frontend](../03-frontend/01-overview-and-structure.md) section. The build pipeline is detailed in
[Frontend - build and assets](../03-frontend/05-build-and-assets.md).

## 4. `Plugin/owismind/webapps/webapp-owismind-ai-agents/`: the DSS webapp component

The webapp descriptor and its entry point. Mostly source, with one generated file:

| File | Lives here | Status |
|---|---|---|
| `webapp.json` | DSS descriptor: `baseType STANDARD`, `hasBackend`, Settings params (`sql_connection`, `table_prefix`, `traces_dataset`, `log_level`), `paramsPythonSetup` | Source |
| `backend.py` | Thin bootstrap: star-import `customwebapp` then `register_routes(app)` | Source |
| `body.html` | Entry HTML served by DSS | GENERATED by `/build-plugin` (byte-identical copy of the built `index.html`); do not edit by hand, it is re-wired on every build |
| `app.js` | STANDARD JS slot, deliberately empty (the frontend comes from `body.html`) | Source, present but empty; DSS requires it, do not delete |
| `style.css` | STANDARD CSS slot, deliberately empty (styling is in the Vite bundle) | Source, present but empty; do not delete |

`body.html` is technically an output: it is regenerated on every build because the built `index.html`
references a hashed bundle that changes every time. If we forget to recopy it, DSS serves a `body.html`
pointing to an old hash and the assets return 404.

## 5. `Plugin/owismind/resource/`: served resources, including the built frontend

| Path | Lives here | Status |
|---|---|---|
| `owismind-app/` | The frontend built by Vite (hashed assets `index-*.js`/`*.css`, rewritten `index.html`, `favicon.svg`) | VERSIONED generated output (exception); NEVER edited by hand |
| `compute_available_connections.py` | `paramsPythonSetup` script (READ-ONLY) that populates the Settings dropdowns (PostgreSQL connections, trace datasets) | Source; ships in the zip |

`owismind-app/` is the versioning exception described in section 1: produced by `npm run build`, but
committed because the payload must travel inside the repository. Two protections prevent touching it by hand:
the harness permissions (`.claude/settings.json`) and the `guardrail.sh` hook block any `Edit`/`Write`
under that path. We regenerate it only via the `/build-plugin` skill.

`compute_available_connections.py` lives under `resource/` so it ships in the zip; it only LISTS the
connections and datasets (never creates/modifies/deletes) and runs only while the Settings form is being rendered.

## 6. `Plugin/owismind/tests/`: the pure-logic backend suite

Backend `unittest` tests, placed OUTSIDE `python-lib/` so they are NEVER packaged. They put
`python-lib/` on `sys.path` to resolve `owismind.*` and remain DSS-free (native runner, no install).
Coverage: payload validation, pure SQL builders, pagination, agent context assembly, name derivation, and
the whole Evidence suite (SQL parsing/explanation, capture, chart_payload, throttle) plus artifacts and
usage. Run: `python3 -m unittest discover -s Plugin/owismind/tests -v`.

The complete test strategy (backend/frontend/agents suites, what requires DSS, absence of CI) is in
[Test strategy](../07-testing/01-test-strategy.md).

## 7. `Plugin/ready-for-dataiku/`: the packaged deliverable (generated, ignored)

| Path | Lives here | Status |
|---|---|---|
| `owismind-upload.zip` | The archive uploadable into DSS (root `plugin.json` + `python-lib/` + `resource/` + `webapps/`) | IGNORED generated output |
| `owismind-upload/` | Intermediate packaging staging folder | IGNORED generated output |

Entirely regenerated by the `/package-plugin` skill. The whole `Plugin/ready-for-dataiku/` folder is in
`.gitignore`. Never edit it by hand, never commit it. The canonical content of the zip excludes, by
NAME (never by a broad glob `*.py`/`*.md`, on pain of sweeping up the `__init__.py` files), `frontend/`,
`node_modules/`, `CLAUDE.md`/`README.md`, `__pycache__/`, `*.pyc`. The complete procedure is in
[Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

## 8. `dataiku-agents/`: the Code Agents and design-time fabrication

Documented mini-repo, deployed SEPARATELY from the plugin: the agents are pasted by hand into DSS Code
Agents on the Python 3.11 code env (the Flask backend, for its part, is on Python 3.9). This layer NEVER
goes through the zip; an agent-only change does not touch `ready-for-dataiku/`.

> IN FLUX: this folder is being edited live by another engineer. The file names and the list of
> tools may shift from one day to the next; always confirm the actual state before relying on a precise
> detail.

| Path | Lives here | Status |
|---|---|---|
| `agents/OWIsMind_orchestrator.py` | The orchestrator (LangGraph Code Agent, env 3.11): loop, `CAPABILITIES` registry, honesty firewall, modes | Source (= truth of the DSS Code Agent) |
| `agents/SalesDrive_revenue_expert.py` | The revenue expert sub-agent (`agent:bHrWLyOL`): UNDERSTAND -> RESOLVE -> QUERY -> RENDER pipeline | Source |
| `agents/README.md` | Agent system documentation (pipeline, deployment) | Source |
| `recipes/` | Design-time Flow recipes: `profile_dataset_recipe.py`, `build_value_index_recipe.py`, `build_value_catalog_recipe.py` (+ `README.md`) | Source; deployed as Python recipes in the Flow, not via the zip |
| `tools/` | Agent tools and semantic model: `attribute_lookup_tool.py`, `semantic_model/` sub-folder (`build_aligned_semantic_model.py`, `update_aligned_semantic_model.py`, `README.md`), `README.md` | Source |
| `tests/` | DSS-free agents `unittest` suite: `test_profiler.py`, `test_dataset_expert.py`, `test_langgraph_agents.py` (registry anti-drift test), `test_attribute_lookup.py` | Source |
| `README.md`, `CLAUDE.md` | Master documentation and engineering notes | Source |

The agents are standalone files: they import only stdlib + `dataiku` + `langgraph`, never the plugin
package. Running the tests: `python3 -m unittest discover -s dataiku-agents/tests`.

> IN FLUX: `tools/attribute_lookup_tool.py` is BUILT and unit-tested
> (`tests/test_attribute_lookup.py`), but NOT yet wired into the sub-agent. Its predecessor, the
> managed tool `dataset_lookup` (`9FEzVZk`) and the `lookup` intent, were REMOVED on 2026-06-18.

> ROADMAP: the recipe `build_value_catalog_recipe.py` produces `DRIVE_Revenues_Value_Catalog`, and the
> Python resolver `Drive_Revenues_resolve_filter_value` that would consume it, are planned but NOT wired
> in v3. The current grounding remains read-only inline SQL on `DRIVE_Revenues_value_index`.

The detail of the agent system lives in [Agent system](../05-agents/01-agent-system-overview.md) and the
re-paste procedure in [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

## 9. `docs/`: reference engineering documentation

Historical technical documentation of the project. STARTING source, not the ultimate source of truth: in
case of conflict with the code or the memory, the code and the memory prevail (some docs carry stale
figures, for example `chat_v4` vs the actual `chat_v5`, or old test/zip-entry counts).

| Path | Lives here | Status |
|---|---|---|
| `architecture.md`, `backend-api.md`, `frontend.md`, `data-model.md`, `security.md`, `build-test-deploy.md`, `evidence-trust-layer.md` | Engineering guides by theme | Source (sometimes stale on the figures) |
| `cadrage/` | Functional specification + Dataiku reference guide + validated snippets | Source |
| `superpowers/specs/`, `superpowers/plans/` | Frozen design specs and plans | Source |
| `questions_asked.md` | Corpus of 817 real questions used for the analysis | Source |
| `screenshots/` | Reference screenshots | Source |
| `agentic-research/` | Provenance research corpus of the agentic skill | IGNORED (kept on disk, gitignore L49) |

## 10. `memory/`: the project's living memory

The memory prevails over the `docs/cadrage/` guides. Maintained by the `/log-session` skill.

| Path | Lives here | Status |
|---|---|---|
| `CONTEXT.md` | Short-term memory, loaded every session (current focus, gotchas, next steps) | Source |
| `PROJECT_STATE.md` | Detailed durable state (canonical identifiers, feature state) | Source |
| `LESSONS.md` | Journal of the `L0xx` lessons (context / failure / solution / proof / source / date) | Source |
| `sessions/` | One log per session day (~16 files `YYYY-MM-DD.md`) | Source |

## 11. `.claude/` and `graphify-out/`: assistant tooling

Claude Code tooling: skills, hooks, permissions. The `settings.json` and the skills are versioned; the
local overrides and the graph are ignored.

| Path | Lives here | Status |
|---|---|---|
| `.claude/settings.json` | Permissions (deny of install commands), hook wiring | Source |
| `.claude/settings.local.json` | Local permissions override | IGNORED (gitignore L43) |
| `.claude/skills/` | Project skills: `build-plugin`, `package-plugin`, `log-session`, `agentique-python-dataiku` | Source |
| `.claude/hooks/guardrail.sh` | PreToolUse hook: blocks installs, writes under `resource/owismind-app` and `ready-for-dataiku`, reminds of SQL safety | Source |
| `.claude/hooks/session-start.sh` | SessionStart hook: injects the memory reminders and the non-negotiable rules | Source |
| `graphify-out/` | Knowledge graph (HTML + index), regenerated by `/graphify` and the `post-commit` git hook | IGNORED (gitignore L46) |

Two additional Git hooks live under `.git/hooks/` (outside the versioned tree, installed by
`graphify hook install`): `post-commit` and `post-checkout` rebuild the code-only graph (AST, without
an LLM) in the background. The detail of the build/hooks chain is in
[Build, packaging and deployment](../06-operations/02-build-package-deploy.md).

## 12. Memo: the editing rule by zone

| You modify... | You edit... | You do NOT touch... |
|---|---|---|
| The UI | `frontend/src/` | `resource/owismind-app/`, `body.html` (regenerated by `/build-plugin`) |
| The backend | `python-lib/owismind/` | `ready-for-dataiku/` (regenerated by `/package-plugin`) |
| An agent | `dataiku-agents/agents/` (then re-paste the 2 Code Agents) | The zip (agent outside the zip) |
| The webapp config | `webapps/.../webapp.json` | `app.js`/`style.css` (empty, required by DSS, to keep) |
| The memory / docs | `memory/`, `docs/` | `graphify-out/` (regenerated) |

## See also
- [Component map](../02-architecture/02-component-map.md) - the modules by layer (canonical home of the diagram).
- [Frontend - overview and structure](../03-frontend/01-overview-and-structure.md) - internal structure of `frontend/src/`.
- [Backend - overview and structure](../04-backend/01-overview-and-structure.md) - the sub-packages of `python-lib/owismind/`.
- [Agent system - overview](../05-agents/01-agent-system-overview.md) - the content of `dataiku-agents/`.
- [Build, packaging and deployment](../06-operations/02-build-package-deploy.md) - who generates what, hooks and zip.
- [Contributing - conventions and rules](01-contributing-and-conventions.md) - the non-negotiable rules (NO INSTALL, do not edit the outputs).
