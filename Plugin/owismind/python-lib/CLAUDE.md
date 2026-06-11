# Backend rules — python-lib/ (OWIsMind DSS plugin)

Path-scoped guidance for the Flask/DSS backend. Full context: repo-root CLAUDE.md + memory/.

## Dataiku instance safety (always ask first)
Before writing backend code, ask: *is this risky / slow / overloading for the Dataiku instance?*
Avoid heavy, blocking, or unbounded work in request handlers. No code that can harm or slow the instance.

## SQL storage (direct, no Flow)
- Exact API (do not guess): `from dataiku import SQLExecutor2` → `SQLExecutor2(connection=...)`
  (PostgreSQL, schema `public`). The connection is **admin-configured** in the webapp Settings and
  resolved through `storage.sql_config` (default `SQL_owi`) — do NOT hardcode it. **No Flow at runtime.**
- Physical table names: `f"{PROJECT_KEY}_owismind_{logical_name}"` (an optional admin prefix sits before
  the `owismind` namespace), cited as `public."OWISMIND_DEV_owismind_webapp_chat_v4"`. Build the reference
  via `sql_config.full_table(...)`. `PROJECT_KEY = dataiku.default_project_key()`.
- **Always `COMMIT`** after CREATE/INSERT/UPDATE: writes go in `pre_queries=[...]` + `post_queries=["COMMIT"]`.
- **Parametrize** all user input: `from dataiku.sql import Constant, toSQL, Dialects`; value form is
  `toSQL(Constant(value), dialect=Dialects.POSTGRES)`. Never build SQL with f-strings around user content.
- **No generic SQL route** (`/execute-sql`, `/run-query`). The frontend never picks table/connection/query.

## Agents (LLM Mesh)
- Server-side **whitelist** (dynamic, NOT hardcoded): the frontend sends an OPAQUE logical key
  (e.g. `ag_<hash>`); the backend resolves it to `(project_key, agent_id)` via
  `storage.settings.resolve_enabled_agent`, against the agents an admin enabled (persisted in
  `webapp_settings_v1`). A forged or disabled key resolves to `None`. Never accept a raw `agent_id` from the front.
- Streaming: normalize agent chunks to events (`run_started`, `agent_event`, `answer_delta`,
  `generated_sql`, `usage_summary`, `final_answer`, `run_done`, `error`).

## Structure & conventions
- Modular layout: `python-lib/owismind/api/routes.py` (Blueprint `url_prefix="/owismind-api"`,
  `register_routes(app)`); `webapps/.../backend.py` is a thin bootstrap.
- Code & comments in **English**, optimized, professional, well-commented.
- Do not assume Python 3.11 / FastAPI work — observed backend is 3.9.23 (Flask).
- NO installs: if a dependency is missing, ask the user.
