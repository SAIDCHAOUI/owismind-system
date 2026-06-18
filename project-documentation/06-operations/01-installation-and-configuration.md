# Installation and configuration

> Audience: DSS admin, operator. Last updated: 2026-06-18. Summary: how to install the OWIsMind
> plugin, build the two code envs (3.9 backend, 3.11 agents), instantiate the webapp, configure it in
> the Settings (SQL connection, table prefix, traces dataset, log level), paste the two Code Agents and
> have an admin activate the agent whitelist.

OWIsMind is deployed as three independent building blocks: a **DSS plugin** (Flask backend + built Vue
frontend, shipped in a zip), two **LangGraph Code Agents** pasted in by hand (outside the zip), and a
little **runtime configuration** in the webapp Settings. This page walks through the complete sequence,
from the first upload to the first successful conversation. The build and packaging themselves (how to
produce the zip) are described in [Build, packaging and deployment](02-build-package-deploy.md); here we
assume the zip is already produced (or received) and we focus on installation and configuration on the
instance side.

Canonical identifiers to know: plugin id `owismind` (version `0.0.1`), webapp
`webapp-owismind-ai-agents`, python-lib package `owismind`, resource folder `owismind-app`, API prefix
`/owismind-api` (health `/owismind-api/ping`), default SQL connection `SQL_owi` (PostgreSQL, schema
`public`), fallback project key `OWISMIND_DEV`, DSS platform 14.4.x.

---

## 1. Prerequisites

| Prerequisite | Detail |
|---|---|
| DSS instance | Version 14.4.x, able to host plugins and STANDARD webapps. |
| PostgreSQL connection | A DSS connection of type `PostgreSQL` (schema `public`) on which the backend creates its tables. The code accepts ONLY PostgreSQL (`compute_available_connections.py`, `_SQL_TYPES = {"PostgreSQL"}`). |
| Python 3.9 code env | For the Flask backend. This is the env observed in DSS (`/owismind-api/ping` returns `3.9.23`), WITHOUT langchain. Flask + direct SQL only. |
| Python 3.11 code env | For the two LangGraph Code Agents (langchain/langgraph are installed there). LangGraph v1 requires Python >= 3.10. |
| LLM Mesh connection | Exposing the per-mode models (Gemini Flash-Lite, Gemini Flash, Claude Sonnet) and the `revenue_semantic_query` tool (`v4oqA6R`). Managed by DSS; no provider token transits through the repository. |
| Permissions | A DSS account able to install a plugin, create a webapp and configure its Settings. The very first user who POSTs `/me` after configuration becomes the application admin (see section 8). |

> NO INSTALL: the structuring rule of the project is that the agent (Claude) never installs a
> dependency. Building the code envs and adding langchain/langgraph is a MANUAL operation performed by
> the DSS operator, never automated from this tooling. This page therefore describes what YOU do on the
> instance, not a scripted procedure.

### 1.1 The two code envs (the 3.9 / 3.11 dual path)

OWIsMind deliberately lives on two distinct Python environments, and this is intentional, not a version
accident:

- **Flask backend = Python 3.9.23.** It only does Flask + direct SQL (`SQLExecutor2`). It never imports
  langchain. This is the code env attached to the webapp.
- **Agents = Python 3.11.** The two Code Agents import `langgraph`; they need a 3.11 code env where
  langchain/langgraph are installed. They are standalone files: they import only the stdlib, `dataiku`
  and `langgraph`, never the plugin's `owismind` package.

You cannot put langgraph in the 3.9 backend; that is why the agents do NOT travel inside the zip and are
deployed by copy-paste into Code Agents on a 3.11 env (section 7). This separation is formalized in
[ADR-0005](../08-decisions/0005-langgraph-code-agents-python-311.md).

---

## 2. Install the plugin (from zip or from Git)

The plugin is distributed as an `owismind-upload.zip` archive (canonical contents: `plugin.json` at the
root + `python-lib/` + `resource/` + `webapps/`; never `frontend/` nor `node_modules/`). Two installation
paths exist on the DSS side.

### 2.1 From the zip (nominal path)

Uploading is a MANUAL operation; nothing in the project tooling uploads on your behalf.

1. In DSS, open **Plugins** (plugin administration).
2. **Add plugin > Upload**, choose `owismind-upload.zip`, **Origin = Uploaded**.
3. Let DSS install the plugin (id `owismind`).

> Important trap: a **Development** plugin carrying the same id `owismind` CANNOT be updated by a ZIP
> upload ("you cannot update it"). To keep the SAME id (and therefore the Vite asset paths already wired
> in `body.html`), you must first **delete** the existing Development plugin, then upload the ZIP with
> **Origin = Uploaded**. Keeping the same id avoids re-wiring the asset URLs.

### 2.2 From Git

DSS can also install a plugin from a Git repository. This is useful if you sync the source code. Be
careful: the built frontend (`resource/owismind-app/`) is VERSIONED in the repository (a deliberate
exception to the "outputs ignored" philosophy), precisely so that a fresh clone stays deployable without
re-building. If you install from Git, make sure that branch indeed contains an up-to-date
`resource/owismind-app/` and a `body.html` wired to the correct asset hashes; otherwise DSS will serve
assets as 404. When in doubt, prefer the zip path, or re-build beforehand (see
[Build, packaging and deployment](02-build-package-deploy.md)).

### 2.3 Build the two code envs

Before instantiating the webapp, prepare the two environments:

- **3.9 code env** for the backend: Flask is enough (the backend does not need langchain). This is the
  env the webapp will use.
- **3.11 code env** for the agents: install `langchain` and `langgraph` there. This env will be attached
  to the two Code Agents (section 7), not to the webapp.

---

## 3. Instantiate the webapp

Once the plugin is installed:

1. Create a webapp based on the `webapp-owismind-ai-agents` component of the `owismind` plugin (displayed
   label: "OWIsMind - AI Agents").
2. Attach the **Python 3.9 code env** to the webapp (the backend runs on it).
3. After every upload of a new version, perform **Start/Restart backend** of the webapp, then a **forced
   refresh** of the browser (the browser's asset cache may serve an old bundle).

The component is of `baseType` STANDARD with backend (`hasBackend: "true"`). The `backend.py` is a thin
bootstrap that simply wires the OWIsMind API blueprint (`register_routes(app)`) onto the Flask `app`
object provided by DSS; at boot, it applies the configured log level and logs the resolved storage
configuration, which makes it possible to confirm in the DSS log which build is running and how storage
resolved.

> Runtime identity (run-as-user): the webapp executes under the DSS **run backend as** identity, distinct
> from the end user. It is under this identity that the SQL, the agent calls and the project/dataset
> discovery execute. The real caller identity, for its part, comes from the browser's authentication
> headers and is only used for application scoping. See section 9 and the
> [Security model](../02-architecture/04-security-model.md).

---

## 4. Configure the webapp in the Settings

As long as no SQL connection is chosen, the application declares "storage not configured" rather than
guessing: this is intentional. The four parameters below are found in the webapp's **Settings** tab. The
two dynamic dropdowns (`sql_connection` and `traces_dataset`) are populated by the
`compute_available_connections.py` script, which is STRICTLY read-only (it only LISTS, never
creates/modifies/deletes, and only runs while the form is being rendered).

| Parameter | Type | Required | Role |
|---|---|---|---|
| `sql_connection` | Dynamic SELECT | no (but the app does not work without it) | The PostgreSQL connection where the backend stores its tables. The list offers ONLY PostgreSQL connections. |
| `table_prefix` | STRING | no | Optional prefix inserted after the project key, max 16 characters, charset `[A-Za-z0-9_-]`. A prefix that is too long or invalid is IGNORED. |
| `traces_dataset` | Dynamic SELECT | no | Trace dataset (write-only) where each agent run appends its final trace. A `(none)` entry disables trace storage. |
| `log_level` | SELECT (`DEBUG`/`INFO`/`WARNING`) | no (default `INFO`) | Verbosity of the webapp backend log. |

> Rendering gotcha: a parameter of type MULTISELECT does NOT render correctly in the DSS Settings. None
> of the OWIsMind parameters use it; do not introduce one.

### 4.1 SQL connection (`sql_connection`)

This is the only truly indispensable setting. Select the dedicated PostgreSQL connection (by convention
`SQL_owi`). Points to know:

- The connection is **resolved server-side** (`sql_config.connection_name()`), never hard-coded. The
  frontend never chooses the connection.
- As long as it is not chosen, `is_configured()` returns `False` and the app reports
  `storage_not_configured`. The `new_executor()` backstop RAISES a `RuntimeError` if you try to open an
  unconfigured connection: there is never an implicit connection.
- The population script only lists PostgreSQL connections. If `list_connections()` is admin-restricted or
  unavailable in the form-rendering context, the dropdown shows a CLEARLY LABELED fallback (for example
  `SQL_owi (fallback - listing failed: ...)`) rather than a silent fake; choosing that fallback remains
  possible if the connection does indeed exist on the DSS side.
- On the first write, the backend lazily creates its tables (`CREATE TABLE IF NOT EXISTS`). The complete
  data model (tables `webapp_chat_v5`, `webapp_users_v1`, `webapp_settings_v1`,
  `webapp_usage_monthly_v1`, `webapp_artifacts_v1`) is described in
  [Backend - storage and data model](../04-backend/04-storage-and-data-model.md).

### 4.2 Optional table prefix (`table_prefix`)

Allows several OWIsMind instances to coexist on the same connection / same project key. The physical
table naming is `{PROJECT_KEY}_{namespace}_{logical}` where the namespace is `owismind` without a prefix,
or `{prefix}-owismind` with a valid prefix. Example with project key `OWISMIND_DEV`:

- without prefix: `OWISMIND_DEV_owismind_webapp_chat_v5`;
- with prefix `bidule`: `OWISMIND_DEV_bidule-owismind_webapp_chat_v5`.

The prefix is validated against `^[A-Za-z0-9_-]{1,16}$`. A prefix that is too long or invalid is
**ignored** (the app runs without a prefix) and a warning is emitted ONCE only. The admin space
(`/admin/storage`, see section 10) exposes the triplet `table_prefix` (effective), `table_prefix_input`
(raw) and `table_prefix_ignored`, so that an ignored prefix is visible instead of failing silently.

### 4.3 Optional traces dataset (`traces_dataset`)

If you want to archive the raw trace of each agent run for offline analysis, first create the dataset in
the Flow, then select it here. The dataset must carry **exactly these 3 columns** (order does not
matter):

| Column | Expected type |
|---|---|
| `exchange_id` | string |
| `trace` | string |
| `created_at` | date |

Mechanics and constraints to respect:

- The webapp only WRITES to it (append), it never reads it back. Choosing `(none)` disables trace storage
  (reversible at any time).
- The dataset must be **SQL-table-backed**, NOT CSV/filesystem: a file dataset has its own line-length
  limit (`ERR_FORMAT_LINE_TOO_LARGE`) that large JSON traces would exceed. The write goes through
  `write_with_schema`, which does not pass through DSS's SQL query logging (the very reason for the
  dataset rather than an SQL column). This point is marked "MUST be validated in DSS" in the code: confirm
  it on the instance.
- The write aligns the DataFrame by POSITION. If the dataset schema does not carry exactly these 3
  columns, the write fails ("Name/Type mismatch"); the dropdown therefore filters SQL-backed datasets.
- Trace writing is **best-effort**: a missing, incompatible or erroring dataset NEVER breaks the
  conversation; the trace is simply skipped (and logged). Cap `MAX_TRACE_BYTES` 4,000,000 bytes (beyond
  that, a truncation marker is written).

This is the only exception to the "no Flow at runtime" principle: all the rest of the storage is in direct
SQL.

### 4.4 Log level (`log_level`)

Choice of `DEBUG` / `INFO` / `WARNING`, default `INFO`. Applied to the webapp backend log. The logs are
deliberately content-free: the content of user messages and agent responses is never logged (only length
and metadata), and credential-bearing headers are never logged. See
[Monitoring and logs](03-monitoring-and-logs.md).

---

## 5. Paste the two Code Agents (3.11 env)

The chat path requires the orchestrator to be reachable. The two Code Agents live in the repository
(`dataiku-agents/agents/`, source of truth) and are pasted BY HAND into DSS, onto the **Python 3.11 code
env**. They never go through the zip.

| Source file (repo) | Target DSS Code Agent | Env |
|---|---|---|
| `dataiku-agents/agents/OWIsMind_orchestrator.py` | OWIsMind_orchestrator | Python 3.11 |
| `dataiku-agents/agents/SalesDrive_revenue_expert.py` | SalesDrive_revenue_expert (`agent:bHrWLyOL`) | Python 3.11 |

Always re-paste BOTH together when one changes: the orchestrator resolves the sub-agent by its id
(`agent:bHrWLyOL`), and some fixes live on both sides. The detailed procedure (and the id checks) is in
[Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

### 5.1 Verify the config ids against the instance

After pasting, verify that the ids indeed referenced objects exposed by your LLM Mesh connection. A wrong
id does not crash at boot: it is the corresponding mode that does not respond. Ids to check:

| Constant (in both agents) | Value observed in the code | Use |
|---|---|---|
| `GEMINI_FLASH_LITE_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite` | eco mode (default) |
| `GEMINI_FLASH_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash` | medium mode |
| `SONNET_ID` | `openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6` | high mode + Semantic Model |
| `SEMANTIC_TOOL_ID` (sub-agent) | `v4oqA6R` | `revenue_semantic_query` tool (writes/executes the SQL) |
| sub-agent `agent_id` (orchestrator) | `agent:bHrWLyOL` | resolution of the sub-agent by id |

> IN FLUX: the `dataiku-agents/` layer is being edited live. The LLM Mesh ids above must match YOUR
> instance's connection; re-verify them on every re-paste. Furthermore, the managed tool `dataset_lookup`
> (`9FEzVZk`) and its `lookup` intent were REMOVED on 2026-06-18; their replacement `attribute_lookup`
> (`tools/attribute_lookup_tool.py`) is built and unit-tested but NOT yet wired into the sub-agent. The
> `DRIVE_Revenues_Value_Catalog` and the Python resolver `Drive_Revenues_resolve_filter_value` remain
> ROADMAP, not wired in v3.

---

## 6. Activate the agent whitelist (admin)

Pasting the Code Agents is not enough: the backend only routes chat to agents that an **admin** has
explicitly activated. The frontend never sends a raw `agent_id`, only an opaque logical key
(`ag_<hash>`); the backend resolves `(project_key, agent_id)` only if the agent is in the server
whitelist. A forged or stale key resolves to `None` and the run is never started.

The whitelist is persisted in the global settings table `webapp_settings_v1` under the key
`enabled_agents` (JSON list of `{logical_key, project_key, agent_id, label}`). It is driven by the admin
routes:

1. `GET /owismind-api/admin/projects` lists the project keys visible to the webapp identity (read-only).
2. `GET /owismind-api/admin/projects/<project_key>/agents` lists a project's agents (read-only).
3. `POST /owismind-api/admin/agents` persists the selection `{agents: [{project_key, agent_id}, ...]}`.

Inviolable guardrail at write time: `POST /admin/agents` RE-VALIDATES each requested agent against the
LIVE DSS listings (project visible AND agent actually present in that project) before persisting. An
`agent_id` forged from the frontend is silently "skipped". Defensive cap `MAX_ENABLED_AGENTS = 50`.
Discovery is strictly read-only (an agent = any LLM whose id starts with `agent:`). For OWIsMind chat,
activate at minimum the orchestrator `OWIsMind_orchestrator`; it is what then routes to the revenue
sub-agent.

> The UI-side guard (the frontend admin menu) is merely cosmetic: the real enforcement is server-side
> (`_admin_guard()` + `resolve_enabled_agent`). The whitelist logic is detailed in
> [Backend - security and validation](../04-backend/06-security-and-validation.md) and
> [ADR-0004](../08-decisions/0004-whitelist-agents-serveur.md).

---

## 7. Run-as-user and permissions

Two identities coexist, and confusing them is the most frequent source of error:

- **Logged-in DSS user (caller)**: resolved server-side from the browser's authentication headers. Used
  for application scoping (each chat read/write is `WHERE user_id = <caller>`) and for the admin election.
  The frontend never sends it in the request body.
- **Backend run-as-user (the webapp identity)**: the identity under which the DSS backend runs. It is the
  one that actually executes the SQL, calls the agents via LLM Mesh, and discovers the projects, agents
  and datasets. It only sees what ITS permissions allow.

Operational consequences to lock down at deployment:

| Point | To do |
|---|---|
| Run-as-user permissions | The backend identity must see the project and the agents to activate (`list_project_keys` / `list_project_agents` reflect ITS rights), and be able to execute SQL on the chosen connection. |
| SQL connection permissions | The run-as-user must be able to create/read/write its tables on the connection (the DDL is idempotent `IF NOT EXISTS`, never destructive). |
| Evidence datasets | Evidence re-executes the agent's SELECT read-only on the SQL-backed datasets OF the project, discovered automatically (no whitelist to configure). The run-as-user must be able to read those datasets. |
| Single-process | All in-memory state (in-flight runs, identity cache, rate-limit buckets) is per-process. Force the backend to 1 process: in multi-process, a cross-process poll would return 404 and the caps would be multiplied. To verify on the instance. |
| Isolation between users | Since the SQL runs under a SINGLE identity, isolation does not come from DSS at the SQL level: it is enforced in the code by owner-scoping on `user_id`. Any whitelisted agent is reachable by any authenticated user; the responsibility for exposure falls to the admin via the whitelist. |

The detail of this model is in the [Security model](../02-architecture/04-security-model.md).

---

## 8. First admin (TOFU)

The very first user who POSTs `/owismind-api/me` AFTER storage is configured becomes the application admin
(Trust On First Use). The election is serialized by a PostgreSQL advisory lock
(`pg_advisory_xact_lock`): two concurrent first users cannot both become admin. A plain `GET`/prefetch
triggers nothing: only the POST (emitted once by the frontend at init) registers the user and plays the
election.

Consequence: after configuring the SQL connection, make sure it is indeed the deploying admin who opens
the application first. Anti-lockout guard: `set-admin` never removes the last remaining admin
(`cannot_remove_last_admin`).

---

## 9. Ordered checklist

Complete sequence, from zero to the first conversation:

1. **Code envs**: build a Python 3.9 code env (backend) and a Python 3.11 code env (agents, with
   langchain/langgraph installed by the operator).
2. **PostgreSQL connection**: make sure a PostgreSQL DSS connection exists (by convention `SQL_owi`) and
   that the backend run-as-user can write to it.
3. **Install the plugin**: upload `owismind-upload.zip` with Origin = Uploaded (if a Development version
   of the same id exists, delete it first).
4. **Instantiate the webapp** from the `webapp-owismind-ai-agents` component, attach the 3.9 code env to
   it.
5. **Settings**: select `sql_connection`; optionally fill in `table_prefix`, `traces_dataset` (3-column
   SQL-backed dataset), `log_level`.
6. **Start backend** of the webapp, then forced refresh of the browser.
7. **Paste the 2 Code Agents** (`OWIsMind_orchestrator` + `SalesDrive_revenue_expert`) onto the 3.11 code
   env; verify the ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`, `v4oqA6R`,
   `agent:bHrWLyOL`).
8. **First admin**: open the app as the deploying admin (POST `/me` => TOFU election).
9. **Whitelist**: via the admin space, activate at minimum the orchestrator `OWIsMind_orchestrator`.
10. **Smoke test**: `GET /owismind-api/ping` must return `{"status":"ok","python":"3.9.23"}`;
    `/admin/storage` must show `configured: true` and the connection; ask a simple question in the chat
    and verify that a response arrives.

> After every upload of a new plugin version that touches `python-lib/` or `backend.py`, perform **Restart
> backend** again. An agent-only change requires NO zip upload: it is enough to re-paste the Code Agents.
> The complete "what to rebuild/redeploy when" matrix is in
> [Build, packaging and deployment](02-build-package-deploy.md).

---

## 10. Verify the configuration (afterwards)

| Verification | How | Expected result |
|---|---|---|
| The backend is running | `GET /owismind-api/ping` (reachable without auth) | `{"status":"ok","python":"3.9.23"}`; never reveals the storage config. |
| Storage is resolved | `GET /owismind-api/admin/storage` (admin) | `configured: true`, the `connection`, the `project_key` (+ its source), the effective `table_prefix` and `table_prefix_ignored`, the `traces_dataset`, and the physical table names. |
| The whitelist is active | `GET /owismind-api/admin/agents` (admin) | the list of activated agents (with `project_key`/`agent_id` on the admin side). |
| Identity and need for config | `POST /owismind-api/me` | `user_id`, `is_admin`, `needs_config` (= `true` as long as the connection is not chosen). |

If `/me` returns `needs_config: true`, it means `sql_connection` is not selected: go back to section 4.1.
The application error codes useful on the operator side: `storage_not_configured` (409, on the admin
routes if there is no connection), `agent_not_enabled` (404, non-whitelisted agent), `forbidden` (403,
non-admin), `unauthenticated` (401, identity not resolved).

---

## See also
- [Build, packaging and deployment](02-build-package-deploy.md) - produce the zip, the what-to-rebuild-when matrix.
- [Monitoring and logs](03-monitoring-and-logs.md) - content-free logs, observability, storage_status.
- [Runbooks](04-runbooks.md) - incident procedures (backend to restart, mode that does not respond, storage not configured).
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - re-paste the 2 Code Agents, verify the ids.
- [Backend - storage and data model](../04-backend/04-storage-and-data-model.md) - the `_vN` tables created on the first write.
- [Backend - security and validation](../04-backend/06-security-and-validation.md) - server whitelist, validation, admin guards.
- [Security model](../02-architecture/04-security-model.md) - run-as-user, owner-scoping, single-process.
- [ADR-0004 - Server-side agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md).
- [ADR-0005 - LangGraph Code Agents in Python 3.11](../08-decisions/0005-langgraph-code-agents-python-311.md).
