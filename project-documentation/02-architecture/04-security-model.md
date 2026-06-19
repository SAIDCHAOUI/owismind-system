# Security model (architecture)

> Audience: developer, admin, security. Last updated: 2026-06-19. Summary: this document
> frames OWIsMind's security posture at the architecture level (trust boundary, two identities,
> agent whitelist, SQL safety, owner-scoping, admin gating, data sent to the LLM, log hygiene)
> and points to the backend detail for the implementation rules.

OWIsMind is a MULTI-USER WebApp served by a SHARED Dataiku DSS instance: any user
authenticated on the instance can open it. Security therefore does not rest on "who can reach the app",
but on four pillars that this document describes, and that the implementation detail specifies in
[Backend - security and validation](../04-backend/06-security-and-validation.md). The code takes precedence over any
reference doc; the names cited here (functions, tables, constants, error codes) are verbatim.

## 1. Posture and trust boundary

The trust boundary is the browser. Everything that comes from it is UNTRUSTED: request body,
query parameters, application headers. Every request is validated and bounded before it reaches SQL or an
agent. Four invariants structure the posture:

1. Identity resolved server-side. The caller's identity is NEVER read from the request body: it
   is resolved from the browser's DSS authentication headers (`resolve_identity` in
   `security/identity.py`).
2. The front sends only LOGICAL data: `session_id`, `message`, an OPAQUE logical agent key
   (`agent_key`), a context-window size (`history_limit`), an optional `parent_exchange_id`, a
   feedback, a `mode` (`eco`/`medium`/`high`) and `webapp_lang`. It NEVER chooses a table, column,
   connection, query, or a raw `agent_id`.
3. No generic SQL surface. There is no `/execute-sql` or `/run-query` route; each SQL text is
   assembled server-side from controlled constants and parameterized values.
4. Systematic shape and bounds validation. The pure `security/validation.py` module validates the SHAPE and
   the BOUNDS of each payload and returns a stable machine error code (never an internal detail);
   the EXISTENCE of Evidence columns is re-validated separately against the live schema.

Execution model: the agent and the SQL run under the SINGLE identity of the WebApp backend (see
section 2), not under that of each end user. Isolation between users is therefore enforced
IN the application code (owner-scoping, section 5), not by DSS at the SQL level.

> IN FLUX: the polling model and the in-memory run state assume a SINGLE-PROCESS DSS backend (the identity
> cache, run ownership, the rate-gate and the Evidence caches are per-process). On deployment, you
> must force / verify 1 process. The `webapp.json` declares NO explicit run-as field: the WebApp
> uses the default DSS run-as behavior for its backend, to be locked down on deployment.

## 2. Two identities: connected user vs the backend's run-as-user

This is the most often misunderstood distinction in the system. Two identities coexist.

| Aspect | Connected DSS user (caller) | Backend run-as-user (WebApp identity) |
|---|---|---|
| Origin | Browser auth headers (DSS session cookie) | Identity under which the DSS WebApp backend runs |
| Resolution | `resolve_identity(request.headers)` -> `dataiku.api_client().get_auth_info_from_browser_headers(...)` | Implicit: it is under this identity that `dataiku.api_client()`, `SQLExecutor2`, LLM Mesh agent execution and discovery run |
| Key value | `user_id = info.get("authIdentifier")` (DSS login, e.g. `said.chaoui`) | Never appears as a value in the code; it is the DSS execution context |
| Role | Scoping of ALL chat and Evidence storage (owner-scoping); application admin election | Actually runs the SQL and calls the agents; sees projects/agents/datasets according to ITS permissions |
| Project/agent visibility | N/A | `discovery.list_project_keys()` reflects the run-as identity's permissions: only accessible projects are listed |

Major security consequence: the agent whitelist and project discovery reflect what the
WebApp run-as identity can see, not what the user's browser could see directly. And
the APPLICATION admin (the `is_admin` flag in the table) is distinct from DSS rights: a non-DSS-admin user can be
admin of the app, and vice versa. Security therefore rests on server scoping (owner-scope SQL) and the
whitelist, not on per-user DSS rights.

### Identity resolution and short cache

`resolve_identity(headers)` returns the dict `{user_id, display_name, groups}`. `user_id` is the DSS login
(`authIdentifier`); DSS provides NO display name, so `display_name` is a simple DEFAULT derived from
the login (`derive_display_name`, `said.chaoui` -> `Said`). Any failure raises `IdentityError`, mapped to
`401 unauthenticated` in EVERY route: a failed DSS lookup -> `auth_lookup_failed`, no `authIdentifier`
-> `no_auth_identifier`.

A per-process cache with a short TTL (`_AUTH_TTL_SECONDS = 5.0`) keyed on a SHA-256 FINGERPRINT of the cookie
(`_identity_cache_key`) collapses the repeated DSS lookups from `/chat/poll` (around 2 Hz per live chat). Only
SUCCESSFUL lookups are cached; opportunistic eviction bounded by `_AUTH_CACHE_MAX = 512`. This cache is
NOT a flaw: a different cookie produces a different fingerprint, so it can never reveal
another user's identity. Header values that may carry credentials are NEVER
logged (only the key NAMES are, for diagnostics).

## 3. Server-side agent whitelist (opaque logical key)

Invariant (NON-NEGOTIABLE rule #4): the front only receives and sends an OPAQUE logical key; the backend
resolves `(project_key, agent_id)` only if the agent is enabled. A forged or disabled key resolves
`None`. The raw `agent_id` NEVER crosses over to the front.

The logical key is `_logical_key(project_key, agent_id)` = `"ag_" + sha1(f"{project_key}:{agent_id}")[:12]`:
stable (re-saving the selection keeps the same key, so conversations that reference an `agent_key`
remain valid) and opaque. `GET /agents` projects only `{key, label}`, never `agent_id` or `project_key`.

The chat enforcement point is `settings.resolve_enabled_agent(logical_key)`: it walks the enabled
list and returns `{logical_key, project_key, agent_id, label}` only if it matches a real agent
still enabled, otherwise `None`. In `POST /chat/start`, an unresolved key yields `404 agent_not_enabled` and the
run is NEVER launched; the resolved `agent_id` stays server-side end to end (passed to the worker, never surfaced
to the client, which only receives the opaque `run_id`).

On write (admin), `POST /admin/agents` RE-VALIDATES each requested agent against the LIVE DSS listings before
persisting: the project must be visible (`discovery.list_project_keys()`) AND the agent actually present
in that project (`discovery.list_project_agents`). An `agent_id` forged from the front can therefore never
be persisted (it is "skipped" with a warning). Defensive cap `MAX_ENABLED_AGENTS = 50`. The whitelist lives in
the global settings table `webapp_settings_v1` under the key `enabled_agents`. Each enabled agent entry
also carries a `profile` dict (the admin-authored editorial copy: tagline, description, capabilities, tools,
icon, badge), sanitized by `validate_agent_meta` before storage (see section 11). The front-side router guard
(UI) is only cosmetic: the real enforcement is server-side.

This decision is recorded in [ADR-0004 - Server-side agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md).

## 4. SQL safety: parameterized, read-only, no Flow, no generic route

Storage is in direct SQL (`SQLExecutor2`, PostgreSQL, schema `public`), WITHOUT Flow at runtime (NON-NEGOTIABLE
rule #3; the only exception: the write-only trace dataset). The safety invariants, detailed in
[Backend - security and validation](../04-backend/06-security-and-validation.md) and
[Backend - storage and data model](../04-backend/04-storage-and-data-model.md), are:

- PARAMETERIZED values, never an f-string around user input. The central helper `sql_value(value)` =
  `toSQL(Constant(value), dialect=Dialects.POSTGRES)` escapes any user value before inlining.
- Identifiers never built from input. `pg_identifier(name)` validates against a strict regex and rejects
  names > 63 bytes (anti silent PostgreSQL truncation), and is only called on controlled
  constants + a valid admin prefix.
- Connection chosen by the ADMIN (DSS Settings dropdown), never hardcoded. `new_executor()` returns a
  FRESH `SQLExecutor2` per call (transactional state not shared between threads) and RAISES if no connection
  is configured: never an implicit connection.
- Fixed and controlled table: `physical_table(logical) = {PROJECT_KEY}_{namespace}_{logical}` on CONSTANT
  logical names (`webapp_chat_v5`, `webapp_users_v1`, `webapp_settings_v1`, `webapp_usage_monthly_v1`,
  `webapp_artifacts_v1`). The front never chooses the table.
- Explicit COMMIT via `post_queries=["COMMIT"]` after each write; the `_vN` idiom (no structural `ALTER`);
  only `CREATE TABLE/INDEX IF NOT EXISTS`, `INSERT`, `UPDATE ... WHERE`, bounded `SELECT`.
- Caps everywhere (row bounds): a session's messages `SESSION_MESSAGES_CAP = 500`, agent context window
  `[10, 50]`, ancestor chain `MAX_CHAIN_DEPTH = 200` + LIMIT, message length
  `MAX_MESSAGE_LENGTH = 8000`, persisted text `MAX_PERSISTED_TEXT_CHARS = 262_144`.

Evidence Studio special case: it is the ONLY surface that re-executes SQL derived from agent content
(the SELECT stored in `generated_sql`). The front NEVER sends SQL: only an `exchange_id`, STRUCTURED
filters `{column, op, values}`, locked chip ids, a page and a sort. The
re-execution is locked read-only via two TRANSACTION-scoped pre-queries
(`SET LOCAL statement_timeout TO '30000'` = 30 s, `SET LOCAL transaction_read_only TO on`), on the connection
OF the discovered dataset, without COMMIT. The non-decomposable WHERE fragment is RE-VALIDATED on every request
(no `;`, no comment, no backslash, forbidden words, blocking of `pg_*` names). The full
detail of this chain lives in [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

This posture is recorded in [ADR-0003 - Direct SQL, no Flow at runtime](../08-decisions/0003-sql-direct-sans-flow.md).

## 5. Owner-scoping (per-owner isolation, anti-IDOR)

Since the SQL runs under a single identity (section 2), isolation between users is enforced
IN the code by systematic scoping on the `user_id` resolved from the headers. A caller can NEVER read
or modify another's data.

| Data | Scoping | Behavior if someone else's id |
|---|---|---|
| Conversation list | `WHERE user_id = {user}` | 0 rows |
| Messages of a session | `WHERE user_id = {user} AND session_id = {session}` | 0 rows |
| Ancestor chain (agent context) | `user_id = {user}` in BOTH members of the recursive CTE | 0 rows |
| Feedback | `UPDATE ... WHERE exchange_id AND user_id` | silent no-op |
| Poll / stop of a run | test `state.get("user_id") != user_id` | `None` -> `404 run_not_found` |
| Artifacts (screen context) | OWNER-SCOPED read by `exchange_id` + `user_id` | reveals only the caller's data |
| Evidence (meta / rows / distinct) | `generated_sql` re-read `WHERE exchange_id AND user_id` (LIMIT 1) | `404 exchange_not_found` |

The `parent_exchange_id` provided by the client is handled defensively: `validate_optional_exchange_id`
degrades it to `None` if it is malformed, and since every read stays user-scoped, a forged id can at worst only
match the caller's OWN rows. The owner-scope 404s never reveal WHICH case (unknown vs
belonging to someone else) was triggered, which avoids an existence oracle. The detail of the queries (ancestor CTE,
keyset, projections) is in [Backend - storage and data model](../04-backend/04-storage-and-data-model.md).

## 6. Data sent to the LLM (no raw rows)

The multi-turn payload built by `flatten_exchanges_to_messages` contains, for each prior exchange,
the `user_text` and the `assistant_text` VERBATIM, plus, when present, a BOUNDED SQL block from the stored
`generated_sql` (cap `MAX_SQL_CONTEXT_CHARS = 4000`). The replayed context therefore contains the TEXT of the responses and the
generated SQL as GROUNDING, but NOT the raw data rows of the results. The captured rows (Evidence)
are persistence-only: surfaced via `/evidence/meta`, never pushed into the agent context nor onto the
polled timeline.

The "ON SCREEN NOW" block (`build_screen_state`) describes what is on screen (artifact specs + column
NAMES + an excerpt of the previous response bounded to 300 characters), but remains a bounded description, not a
dump of rows; it is framed as DATA ALREADY GROUNDED so as not to fool the orchestrator's honesty firewall.
The per-turn context block (`build_user_suffix`) appends at the END of the current message (highest-recency slot)
the user's name, the server date, the app language and the language rule.

The control tokens `⟦owi:mode=…⟧` / `⟦owi:lang=…⟧` are MACHINE-ONLY: the orchestrator parses them THEN
STRIPS them, they never reach the model as visible text. The `mode` relayed by this token is validated server-side
against `MODEL_MODES` (and `webapp_lang` against `_LANG_LABEL`): a user who literally typed
these sequences does not change the real mode. The detail of this contract is in
[Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md).

## 7. Secrets and configuration

No secret is present in the repository. The sensitive configuration is fully managed by DSS and the admin:

- SQL connection: ADMIN-configured in the WebApp Settings (param `sql_connection`, dropdown populated by
  `resource/compute_available_connections.py`), resolved server-side by `connection_name()`, NEVER hardcoded.
  As long as no connection is configured, the app reports `storage_not_configured` rather than guessing.
- LLM Mesh connection: managed by DSS. The code calls the models and agents natively; no token or API key
  from an LLM provider transits through the repository.
- Other webapp params: `table_prefix` (optional, bounded), `traces_dataset` (optional Flow dataset,
  WRITE-ONLY, never re-read online), `log_level`.
- Project key: resolved env -> webapp config -> `dataiku.default_project_key()` -> fallback constant
  `OWISMIND_DEV`. It is an infrastructure constant, not a secret.

> IN FLUX: the per-mode LLM Mesh ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`, on the
> `dataiku-agents/` side) must match the instance's LLM Mesh connection; a wrong id breaks the corresponding
> mode and must be verified in DSS.

## 8. Admin gating: bootstrap, server guards, anti-lockout

`/me` accepts `GET` and `POST`, but the side effect (registering the user + electing the first admin)
happens ONLY on POST: a `GET`/prefetch/scanner can neither create a user row nor win
the election. The "first to open = admin" election is SERIALIZED by a transactional advisory lock
`pg_advisory_xact_lock`: two concurrent first users cannot both become admin.

> IN FLUX (operational, TOFU = Trust On First Use): the first user to open the app AFTER the
> configuration becomes admin. On deployment, make sure it is indeed the deploying admin.

The admin routes are guarded server-side by `_admin_guard()`: it resolves the identity (401 otherwise), requires
storage to be configured (409 otherwise), then requires `admin.is_admin(user_id)` (403 `forbidden` otherwise). The
front-side router guard (UI) is, here again, only cosmetic. Anti-lockout: `set-admin` never removes the LAST
remaining admin (`400 cannot_remove_last_admin` if you try to remove the flag and `count_admins() <= 1`).

## 9. Prompt injection

The message content is the untrusted input par excellence. The primary mitigation is NOT to filter the
text (impossible to do reliably) but to CONSTRAIN what the agent can do downstream. An instruction
injected into a message cannot make the database write nor read outside the project's datasets, because:

- the only WebApp-side SQL re-execution (Evidence) is locked by the read-only + timeout + bounds
  + re-validated fragment chain (section 4);
- on the agent side, only governed DSS tools and a read-only/bounded SQL engine execute SQL;
- the control tokens are parsed and stripped by the orchestrator, and `mode`/`webapp_lang` are re-validated
  against a server whitelist.

> IN FLUX: the robustness of the honesty firewall (the orchestrator never emits an unsourced business fact,
> never says that a piece of data "does not exist") lives in the PROMPTS of the Code Agents (`dataiku-agents/`), outside
> the backend scope and currently being edited by another engineer. See
> [The orchestrator](../05-agents/02-orchestrator.md).

## 10. Log hygiene and error codes

- Never logged: the CONTENT of user messages and agent responses. The blueprint-scoped request hooks
  trace only method, path, status and duration. `/chat/start` logs `user_id`,
  `session_id`, `agent_key`, `msg_len`, NEVER the message. Headers carrying credentials are
  never logged. On agent failure, no agent/SQL/connection internal is disclosed to the client
  (`error: agent_unavailable`).
- `/ping` is deliberately MINIMAL: it DOES NOT EXPOSE the storage config (connection, project key, table
  names), because it is reachable without authentication. The resolved config (`storage_status()`) is readable
  only by an admin via `/admin/storage`.
- Stable error codes, without internal detail: `ValidationError(code)` returns a stable machine code that is safe
  for the front (never an internal). The front maps them to i18n messages.
- READ-only DSS API (+ agent run): only read methods are called (auth resolution,
  webapp config, listing connections/projects/agents/datasets) plus agent execution; never
  `set_*`/`save`/`delete`/`set_variables`/`set_definition`. Discovery is strictly read-only and bounded.

> Budget enforcement is implemented (2026-06-18). See section 11 below for the detail.

## 11. Agent-profile server-side validation and bounding

When an admin saves the agent whitelist (`POST /admin/agents`), each agent's editorial profile (tagline,
description, capabilities list, tools list, icon, badge) passes through `validate_agent_meta` in
`security/validation.py` before being stored alongside the `enabled_agents` JSON in `webapp_settings_v1`.
This function NEVER raises: every field is clamped to its character or item cap, the icon is validated
against `ALLOWED_AGENT_ICONS` (fallback to `DEFAULT_AGENT_ICON`), and the badge against
`ALLOWED_AGENT_BADGES`. An over-long or malformed field is silently truncated, never an error that would
abort the whole whitelist save.

`GET /agents` projects the stored profile onto the public `{key, label, tagline, description,
capabilities, tools, icon, badge}` shape, never leaking `agent_id` or `project_key`. The agent-library
cards in `AgentsView.vue` and the profile sheet are sourced entirely from this endpoint: no hardcoded
descriptive copy exists client-side (the old `registries/agentMeta.js` was removed on 2026-06-18).

## 12. Monthly budget enforcement (fail-open, 402 gate)

The monthly credit (default 50 USD per user, calendar month, auto-reset on the 1st) is enforced by
`storage/budget.py`. The gate is `budget.has_budget(user_id)`, called in `POST /chat/start` BEFORE any
write, after admission but before `save_user_message`. It returns `(ok, status)` where `ok` is False only
when enforcement is on (config key `enabled`) AND the user's month spend (from `webapp_usage_monthly_v1`)
has reached their effective limit. A False result yields `402 monthly_quota_exceeded` with the current
budget status in the body (the frontend uses it to build the transparent budget banner message).

Fail-open contract: if `has_budget` RAISES (storage error), `within_budget` defaults to True and the run
proceeds. The spend is still recorded afterwards, so the next request is gated once the read recovers.
This prevents a storage blip from blocking users.

The effective limit follows a two-layer resolution order: an active per-user override in
`webapp_user_quota_v1` (NULL `expires_at` = permanent; a future timestamp = temporary boost) wins over a
global temporary boost, which wins over the global default from `webapp_settings_v1`. The `storage/budget.py`
module is the single source of truth for this resolution (`_resolve_limit`). The admin overview
(`GET /admin/budget`) and per-user override management (`POST /admin/budget/users`) are admin-gated.

On the frontend, `session.budgetBlocked` (computed from `session.usage`, read from `/usage`) feeds
`chat.canSend` (which becomes False when blocked) and the transparent `.budget-banner` div in `ChatView`.
The server-side gate remains authoritative; the client check is a proactive UI hint only.

## Summary: what is enforced, where and by whom

| Control | Mechanism | Locus |
|---|---|---|
| Authentication | browser headers -> `resolve_identity` -> `401` otherwise | backend (all routes except `/ping`) |
| Isolation between users | owner-scoping on `user_id` in every query | backend (storage + Evidence) |
| Agent choice | opaque logical key -> `resolve_enabled_agent` -> `None` otherwise | backend (server whitelist) |
| Agent profile bounding | `validate_agent_meta` (never raises, clamp + icon whitelist) before `enabled_agents` write | backend (`security/validation.py`, `api/routes.py`) |
| SQL safety | parameterized + read-only + caps + COMMIT + no generic route | backend (`storage/`, `evidence/`) |
| LLM confidentiality | no raw rows, control tokens stripped | backend (`agents/context.py`) + agents |
| Admin gating | `_admin_guard` (401/409/403) + bootstrap lock + anti-lockout | backend (`api/routes.py`, `storage/admin.py`) |
| Monthly budget | `budget.has_budget` -> `402` if blocked (fail-open); per-user override or global default | backend (`storage/budget.py`, `api/routes.py`) |
| Instance safety | concurrency caps, TTL, deadlines (single-process) | backend (`agents/stream_manager.py`) |

## See also

- [Backend - security and validation](../04-backend/06-security-and-validation.md) - the implementation detail of the controls framed here.
- [Backend - storage and data model](../04-backend/04-storage-and-data-model.md) - SQL owner-scoping, naming, caps, conversation tree.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - the defense chain of the read-only SQL re-execution.
- [Runtime flow (runtime)](03-runtime-flows.md) - where these controls fit into a chat turn.
- [ADR-0004 - Server-side agent whitelist](../08-decisions/0004-whitelist-agents-serveur.md) - the opaque logical key decision.
- [ADR-0003 - Direct SQL, no Flow at runtime](../08-decisions/0003-sql-direct-sans-flow.md) - the SQL safety posture.
- [The orchestrator](../05-agents/02-orchestrator.md) - the honesty firewall and the parsing of the control tokens.
