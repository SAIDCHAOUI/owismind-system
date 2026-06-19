# Design spec - Auth gate, Admin conversation review (view-as), DEV/PROD plugin split

Date: 2026-06-19. Status: APPROVED (user). This file is the shared contract for the
implementation subagents. Repo-root CLAUDE.md rules apply (English code, NO em dash
`-`/`,`/`:`, Orange charter for any UI, NO installs, SQL-direct safety, never hand-edit
`resource/owismind-app/` or `ready-for-dataiku/`).

Three independent features, disjoint file ownership so they can be built in parallel.

---

## Feature 1 - Auth gate (not authenticated to DSS)

Problem (verified): `/owismind-api/me` already returns `401 {error:"unauthenticated"}`
when DSS cannot resolve the caller (identity.resolve_identity raises). The frontend
swallows the error and still renders the full shell ("Failed to load history" etc.).
Wanted: when the user is NOT authenticated, render ONE full-screen gate only (no
navigation), Orange-charted, EN by default with a language toggle (and theme toggle),
asking the user to sign in to DSS and reload (F5), or open OWIsMind from the DSS
workspace. NO internal URL anywhere.

### Files (Agent A - frontend only)
- `frontend/src/stores/session.js`
- `frontend/src/App.vue`
- `frontend/src/components/shell/AuthGate.vue` (new)

### Behaviour
- Session store: add `authState` ref with values `'pending' | 'ok' | 'unauthenticated'`,
  exported from the store. In `loadMe()`:
  - success -> `authState = 'ok'`
  - caught error whose `message` is `'unauthenticated'` or `'http_401'` -> `authState = 'unauthenticated'`
  - any other error (e.g. `getWebAppBackendUrl unavailable` in local dev, backend down)
    -> leave `authState = 'ok'` (keep the current degraded-shell behaviour; we only gate
    on the definitive 401). Default initial value `'pending'`.
- `App.vue`:
  - `authState === 'unauthenticated'` -> render ONLY `<AuthGate/>` (no AppLayout, no
    ToastHost router tree -> navigation is impossible).
  - `authState === 'pending'` -> render a minimal neutral splash (avoid flashing the shell
    before `/me` resolves).
  - else -> current `<AppLayout/> + <ToastHost/>`.
  - Keep `session.ensureLoaded()` on mount.
- `AuthGate.vue` (Orange charter, self-contained, read `docs/cadrage/CHARTE_ORANGE_UI.md`):
  full-screen centered card; real logo `frontend/src/assets/orange-logo.png` (`<img>`,
  NEVER a CSS square); eyebrow (orange MAJ) + H1 36/800 + orange title-bar 52x4; body text;
  a "Reload (F5)" button (`location.reload()`); a small **language toggle EN/FR**
  (`ui.setLang('en'|'fr')`) and a **theme toggle** (`ui.toggleTheme()`) reusing the ui
  store. All copy via i18n keys (namespace `authgate.*`).

### i18n (Agent A returns the keys; orchestrator merges into extra.js)
Namespace `authgate.*`, flat keys per locale (fr + en), matching extra.js convention. Text:
- `authgate.eyebrow`: en "Access" / fr "Acces"
- `authgate.title`: en "Sign in to Dataiku required" / fr "Connexion a Dataiku requise"
- `authgate.body`: en "We could not identify you. Please sign in to Dataiku DSS in this
  browser, then reload this page (F5). You can also open OWIsMind directly from the
  OWIsMind workspace in Dataiku DSS." / fr equivalent.
- `authgate.reload`: en "Reload (F5)" / fr "Recharger (F5)"
Agent A may add a couple more if needed; keep the namespace.

---

## Feature 2 - Admin conversation review (view-as, READ-ONLY, isolated & removable)

Admin-only screen to consult another user's conversations (messages + SQL + charts/tables)
exactly as the user sees them, for agent-improvement analysis. STRICTLY read-only (no send,
no feedback, no edit). Temporary / RGPD-sensitive -> must be deletable by removing one
folder + one route + one button + one backend module + one register line, touching NO core
chat/evidence file.

### API contract (Agent B implements, Agent C consumes) - all admin-gated, read-only
New blueprint in `python-lib/owismind/admin_inspect.py`, prefix `/owismind-api/admin/inspect`.
Each route: resolve identity, require configured storage + admin (reuse the same checks as
`api/routes._admin_guard`; import/replicate cleanly), validate a bounded `target_user_id`,
then delegate to existing storage/evidence functions passing `target_user_id` as the user
id. Log an audit line "admin <id> inspected user <target> ...". Errors mirror the existing
routes' shapes/status codes.

- `GET /admin/inspect/users` -> `{users:[...]}` via `admin.list_users()` (reuse; same shape
  as `/admin/users`). (Or Agent C may reuse the existing `/admin/users` directly; provide
  this anyway for a self-contained feature.)
- `GET /admin/inspect/conversations?target_user_id=&cursor=&limit=` ->
  `chat_v5.list_conversations(target_user_id, cursor_token, limit)` (clamp limit via
  `validate_conversations_limit`). Returns `{conversations, next_cursor, has_more}`.
- `GET /admin/inspect/conversation?target_user_id=&session_id=` ->
  `chat_v5.messages_for_session(target_user_id, session_id)`. Returns `{session_id, count, rows}`.
- `GET /admin/inspect/evidence/meta?target_user_id=&exchange_id=` ->
  `evidence_service.evidence_meta(target_user_id, exchange_id)` AND attach artifacts +
  chart/kpi payloads exactly like `api/routes.evidence_meta` does (reuse
  `artifacts_storage.read_artifacts` + `chart_payload.build_chart_payload/build_kpi_payload`).
  Returns `{...meta, artifacts}`.
- `POST /admin/inspect/evidence/rows` body `{target_user_id, ...same as /evidence/rows}` ->
  `evidence_service.evidence_rows(target_user_id, ...)` (reuse `validate_evidence_rows_request`).
- `GET /admin/inspect/evidence/distinct?target_user_id=&exchange_id=&column=&exclude_id=` ->
  `evidence_service.evidence_distinct(target_user_id, ...)`.

`target_user_id` validation: non-empty string, stripped, length <= 256; else 400
`invalid_target`. Add `validate_target_user_id` to `security/validation.py` (Agent B owns
that file for this addition). Re-use existing validators for the rest.

Register: ONE line at the end of `api/routes.register_routes(app)`:
`from owismind.admin_inspect import register_inspect_routes; register_inspect_routes(app)`
(Agent B owns this single edit in routes.py.) `register_inspect_routes` registers the new
blueprint. Removal of the whole feature = delete `admin_inspect.py` + that one line.

Backend signatures (verified):
- `chat_v5.list_conversations(user_id, cursor_token, limit)`
- `chat_v5.messages_for_session(user_id, session_id, cap=...)`
- `evidence_service.evidence_meta(user_id, exchange_id)`
- `evidence_service.evidence_rows(user_id, exchange_id, filters, kept_ids, include_advanced, page, sort, drill, table)`
- `evidence_service.evidence_distinct(user_id, exchange_id, column, exclude_id=None)`

### Files (Agent B - backend)
- `python-lib/owismind/admin_inspect.py` (new)
- `python-lib/owismind/security/validation.py` (add `validate_target_user_id` only)
- `python-lib/owismind/api/routes.py` (ONE register line + import)
- `tests/test_admin_inspect.py` (new; mirror existing test style in `Plugin/owismind/tests/`,
  run with `python3 -m unittest`). Cover: admin gate (non-admin -> 403), invalid target -> 400,
  happy path delegates to the storage fns with the target id (monkeypatch/stub the storage layer
  like existing tests do).

### Files (Agent C - frontend, self-contained folder)
- `frontend/src/features/admin-inspect/InspectView.vue` (new)
- `frontend/src/features/admin-inspect/inspectStore.js` (new, Pinia id `adminInspect`,
  independent of chat/evidence stores)
- `frontend/src/features/admin-inspect/inspectBackend.js` (new; dedicated thin client for the
  `/admin/inspect/*` routes via `getWebAppBackendUrl`, mirroring services/backend.js patterns -
  do NOT add to services/backend.js, keep it isolated)
- `frontend/src/router/index.js` (add ONE route `{ path:'/admin/inspect', name:'adminInspect',
  component: ()=>import('../features/admin-inspect/InspectView.vue'),
  meta:{ requiresAdmin:true, eyebrow:'inspect.eyebrow', title:'inspect.title' } })`
- `frontend/src/views/AdminView.vue` (add ONE clearly-fenced entry: a button/link
  "Review conversations (read-only)" -> `router.push('/admin/inspect')`, admin section)

### InspectView behaviour (faithful read-only)
- A user picker populated from `/admin/inspect/users` (or `/admin/users`); on pick, load that
  user's conversation list; on conversation click, load its rows via `/admin/inspect/conversation`.
- Render each exchange read-only: user text bubble + assistant answer (markdown via
  `composables/useMarkdown`), the per-exchange SQL via `components/evidence/EvidenceSql.vue`
  (prop `sql`), and the captured evidence via `/admin/inspect/evidence/meta`:
  - charts/kpis from `meta.artifacts` using `components/evidence/ArtifactChart.vue`
    (props `chart`,`data`,`title`) / `ArtifactKpi.vue` (props `data`,`title`),
  - captured result table via `components/evidence/ArtifactTable.vue` (prop `result` = `meta.result`).
  (Reuse leaf presentational components only; they are prop-driven. Agent C verifies each
  component's props by reading it. NEVER reuse store-coupled shells - ChatThread / MessageAgent /
  EvidencePanel - and NEVER touch chat.js / evidence.js.)
- Permanent banner: "READ-ONLY - viewing <user> conversations (admin review)". NO prompt bar,
  NO send / feedback / edit / version arrows. Orange charter throughout.
- i18n namespace `inspect.*` (Agent C returns keys EN+FR; orchestrator merges into extra.js).

---

## Feature 3 - DEV/PROD plugin (single source, two build targets)

Keep `Plugin/owismind/` as the ONE source. PROD build/package unchanged. Add a DEV target that
emits a coexisting `owismind_dev` plugin zip. Coexistence needs a distinct plugin id + distinct
Vite base + a renamed python package (`owismind` -> `owismind_dev`) to avoid `import owismind`
collisions across two installed plugins. Data isolation for DEV is a DEPLOY-TIME setting
(dedicated project or `table_prefix="dev"`), NOT code.

Verified rename surface (small): the plugin id appears in a path ONLY via the Vite `base`; 14
files + `webapps/.../backend.py` import the `owismind` package; the literal string `"owismind"`
also appears as the SQL `APP_NAMESPACE` (sql_config.py), the root logger name in
`apply_log_level` (`getLogger("owismind")`), the blueprint url prefix `/owismind-api`, and the
blueprint name `owismind_api`. ONLY the PACKAGE references and the root logger name must be
renamed; APP_NAMESPACE, `/owismind-api`, blueprint name MUST stay.

### Files (Agent D)
- `frontend/vite.config.js`: derive base from env ->
  `const PLUGIN_ID = process.env.OWI_PLUGIN_ID || 'owismind'`
  `base: '/plugins/' + PLUGIN_ID + '/resource/owismind-app/'`
  (default unchanged -> prod build byte-compatible).
- `tools/build_dev_plugin.py` (new): a deterministic, reviewed transform that stages the DEV
  plugin and produces the zip. Steps:
  1. Build the frontend with `OWI_PLUGIN_ID=owismind_dev` into a SCRATCH outDir (do NOT touch
     the canonical `resource/owismind-app/`); read the produced index.html for body.html.
     NOTE: the script must NOT run `npm install`; it relies on existing node_modules and uses
     `vite build --outDir <scratch>` with the env var. If node_modules missing -> error out.
  2. Stage `plugin.json` with `id`->`owismind_dev`, label `OWIsMind`->`OWIsMind (DEV)`.
  3. Copy `python-lib/owismind` -> staged `python-lib/owismind_dev`; rewrite in every staged
     `.py` (python-lib + backend.py):
       - `from owismind` (word-boundary) -> `from owismind_dev`
       - `import owismind` (word-boundary, not already `owismind_dev`) -> `import owismind_dev`
       - `getLogger("owismind")` -> `getLogger("owismind_dev")`
     Leave `APP_NAMESPACE = "owismind"`, `/owismind-api`, `Blueprint("owismind_api"` untouched.
  4. Stage `resource/` (the DEV-base build output for owismind-app + compute_available_connections.py)
     and `webapps/` (backend.py with rewritten import; body.html = DEV-base index.html; other files as-is).
  5. Zip -> `Plugin/ready-for-dataiku/owismind_dev-upload.zip` (exclude the same dev-only files as
     `/package-plugin`: frontend, node_modules, CLAUDE.md, README.md, __pycache__, *.pyc, .DS_Store).
  6. Verify invariants and print them: staged tree has 0 matches for `from owismind\b` /
     `import owismind\b` (regex `\b` does not match `owismind_dev`), `APP_NAMESPACE = "owismind"`
     present, `/owismind-api` present, `python-lib/owismind_dev/__init__.py` present, body.html
     base = `/plugins/owismind_dev/resource/owismind-app/`.
  The script must be SAFE to run in this repo (no install, no edits to the canonical source,
  scratch dirs under /tmp or `Plugin/ready-for-dataiku/`).
- `.claude/skills/package-plugin-dev/SKILL.md` (new): documents running `tools/build_dev_plugin.py`,
  the invariants, and that the upload is a separate *Uploaded* plugin (id `owismind_dev`, distinct
  from prod `owismind`); DEV data isolation = create the DEV webapp in a dedicated project or with
  `table_prefix="dev"`.
- `.claude/skills/build-plugin/SKILL.md`: add a short note that `base` is now env-driven
  (`OWI_PLUGIN_ID`, default `owismind`) and the prod path is unchanged.

Agent D restrictions during parallel phase: write the files and STATICALLY validate the
transform on a /tmp COPY of `python-lib` (run the rewrite + grep invariants). Do NOT run the
real `npm`/vite build, do NOT touch `resource/owismind-app/` or produce the real zip in the
shared tree (the orchestrator runs the real DEV packaging after integration, when the source
is final).

---

## Feature 2 v2 - Source selector (review ANY env's conversations, decided 2026-06-19)

Refinement of Feature 2 after the user clarified: keep DEV/PROD tables SEPARATE, but let the
admin CHOOSE, at runtime, which conversation table (source) to review (e.g. "review this user's
conversations on PROD" from the DEV/analysis instance). Tables are NOT renamed in place (that
would orphan live prod conversations); the DEV instance uses `table_prefix="dev"` + the SAME SQL
connection as prod, so it can see both `..._owismind_webapp_chat_v5` (prod) and
`..._dev-owismind_webapp_chat_v5` (dev). The selector labels them clearly.

ISOLATION DECISION: the inspect feature reads its data with its OWN self-contained, bounded,
read-only, parameterized queries against the CHOSEN tables (validated against a discovered
whitelist). It does NOT modify core storage (chat_v5 / evidence_service / artifacts) and does
NOT use the live dataset-matching evidence path (which is instance/project-specific and would
not work cross-env). It reuses only PURE helpers (capture.build_result_block, chart_payload.*,
parse_json_list, rows_to_json_safe, sql_value, pg_identifier, cap constants). Removing the
feature = delete the module + frontend folder + route + button + register line (unchanged).

Stored data is sufficient for a faithful historical review: the chat row's `generated_sql`
carries the SQL and the captured `result`; charts live in `webapp_artifacts_v1`. No live
re-query / chips / drill (those are dropped from the inspect routes).

### API contract v2 (all admin-gated, read-only; `source` validated against the whitelist)
- `GET /admin/inspect/sources` -> `{sources:[{id,label,is_current}]}`. Discover via
  `information_schema.tables` (schema public, `table_name LIKE '%owismind\_webapp\_chat\_v5'`
  ESCAPE, parameterized) on the configured connection. `id` = the physical chat table name
  (re-validated with pg_identifier + whitelist membership on every later use). `label` =
  friendly, parsed from `{PROJECT_KEY}_{namespace}_webapp_chat_v5` (show project key + prefix,
  or "(default)" when none). `is_current` = (id == physical_table('webapp_chat_v5')). Current
  first, then alpha. Bounded list.
- `GET /admin/inspect/conversations?source=&target_user_id=&cursor=&limit=` -> `{conversations,
  next_cursor, has_more}` read from the chosen chat table (title from the first user message,
  bounded; keyset OR a simple bounded list - admin tool). Owner-scoped on target_user_id.
- `GET /admin/inspect/conversation?source=&target_user_id=&session_id=` -> `{session_id, count,
  rows}` from the chosen chat table; rows carry `generated_sql` (decoded; the `sql` per item is
  kept for inline display; the captured `result` may be projected out here - it comes via the
  evidence route).
- `GET /admin/inspect/evidence/meta?source=&target_user_id=&exchange_id=` -> `{available,
  result, artifacts}`. Read that exchange's stored `generated_sql` (WITH result) from the chosen
  chat table -> `capture.build_result_block(item)` (last successful item with a result, mirror
  the existing selection); read artifacts from the chosen artifacts table (derive its name from
  the source: same `{PROJECT_KEY}_{namespace}_` base + `webapp_artifacts_v1`) -> attach
  chart/kpi `data` via chart_payload.*. No dataset/chips/drilldown/verification. Throttled
  (evidence_throttle, keyed on the admin).
- REMOVE `/admin/inspect/evidence/rows` and `/admin/inspect/evidence/distinct` (no live re-query
  in the cross-env stored review).

Safety: every query is SELECT-only, parameterized (sql_value), the table is built ONLY from a
whitelist-validated physical name via pg_identifier, bounded by row/char caps, and runs with
`SET LOCAL statement_timeout` + `transaction_read_only` (mirror artifacts.py / evidence reads)
so a large prod table can never pin the mono-process backend (rule #2).

### Frontend v2
- Add a SOURCE selector (square select) at the top of InspectView, populated from
  `/admin/inspect/sources`; default to the current instance OR the first source. Thread the
  chosen `source` through every call (conversations / conversation / evidence/meta). Reset the
  user/conversation/evidence state when the source changes. Drop any rows/distinct usage. The
  rest (read-only render via leaf components) is unchanged.

### Deploy guidance (package-plugin-dev SKILL + this spec)
The DEV/analysis instance (`owismind_dev`) uses the SAME SQL connection as prod + `table_prefix
="dev"`. It reviews prod conversations read-only via the source selector. DEV chat writes only to
the `dev-` tables. Prod tables are never renamed.

## Feature 2 v3 - REPLACED by admin impersonation "act as user" (decided 2026-06-19)

User pivot: the separate read-only review screen + source selector + table-naming story were
over-scoped. REMOVE all of Feature 2 (v1 + v2) and replace with a much simpler mechanism:
in the admin space, the "Review conversations" button shows the user list; clicking a user
RELOADS the webapp identified AS that user (impersonation), so the admin sees that user's real
interface + conversations. Admin-only, temporary, easily removable. Tables: UNCHANGED - the
existing `CREATE TABLE IF NOT EXISTS` (ensure_* helpers) already creates-or-reuses; prod/dev use
the same code; the user adds a `dev` table_prefix themselves for a sandbox. NO table renaming,
NO source selector, NO discovery.

### REMOVE (both agents)
- Backend: delete `python-lib/owismind/admin_inspect.py` + `tests/test_admin_inspect.py`; remove
  the `from owismind.admin_inspect import register_inspect_routes` import + `register_inspect_routes(app)`
  call from `api/routes.register_routes`. Keep `validate_target_user_id` (reused for impersonation).
- Frontend: delete `frontend/src/features/admin-inspect/`; remove the `/admin/inspect` route from
  router; remove ALL `inspect.*` keys from `i18n/extra.js` (KEEP `authgate.*`).

### Impersonation contract (shared)
- HTTP header `X-OWI-Impersonate: <target_user_id>` carried by EVERY frontend API call when active.
- Honored ONLY server-side when the REAL caller (from DSS auth headers) is an admin. A non-admin
  sending the header gets no impersonation (effective user = themselves). Target validated by
  `validate_target_user_id`.
- READ routes scope data to the EFFECTIVE user (the impersonated target). WRITE routes are BLOCKED
  while impersonating (consultation only): `/chat/start`, `/chat/feedback`, `/chat/stop` return
  403 `impersonation_read_only`. (No sending / no budget spend under the user's name.)
- `/me` returns the EFFECTIVE identity for display plus `impersonating: bool` and `real_user_id`;
  `is_admin` reflects the effective user (so admin UI hides while impersonating - exit via the
  banner). `/me` does NOT record/bootstrap the impersonated user (skip the side effect when
  impersonating).

### Backend (Agent: python only)
- New `python-lib/owismind/security/impersonation.py`: `IMPERSONATION_HEADER = "X-OWI-Impersonate"`;
  `effective_identity(real_identity)` -> if storage configured AND header present AND
  `admin.is_admin(real_identity["user_id"])` AND target validates -> `{"user_id": target,
  "display_name": derive_display_name(target), "groups": [], "impersonating": True,
  "real_user_id": <admin>}` (audit-log it); else `{**real_identity, "impersonating": False,
  "real_user_id": <self>}`. NEVER raises; no extra DB call when no header is present.
- `api/routes.py` (FENCE every edit with clear BEGIN/END impersonation comments for easy removal):
  READ routes - after `resolve_identity`, set `identity = impersonation.effective_identity(identity)`
  in: `/me`, `/usage`, `/conversations`, `/conversation`, and `_evidence_guard`. `/me` also adds the
  two flags + skips `record_user` when impersonating. WRITE routes - `/chat/start`, `/chat/feedback`,
  `/chat/stop`: after `resolve_identity`, if `impersonation.effective_identity(identity)["impersonating"]`
  return 403 `impersonation_read_only` before any work. Leave `/chat/poll`, `/agents`, `_admin_guard`
  on the REAL identity (admin actions stay the real admin).
- Tests: `tests/test_impersonation.py` (effective_identity: no header=real, non-admin header ignored,
  admin header swaps, bad target ignored; route-level: a read route returns the target's data under
  admin impersonation, a write route 403s while impersonating, a non-admin cannot impersonate).
  Run the full suite.

### Frontend (Agent: vue/js + extra.js)
- New isolated folder `frontend/src/features/admin-impersonate/`: `impersonation.js` (get/set/clear the
  target in sessionStorage key `owismind.impersonate`; `impersonationHeaders()` -> `{ 'X-OWI-Impersonate':
  target }` or `{}`); `ImpersonateBanner.vue` (persistent top banner "Viewing as <user> (admin review) -
  read-only" + Exit that clears + `location.reload()`); a user-picker (reuse `Modal`) listing
  `/admin/users` -> on click: set sessionStorage + `location.reload()`.
- `services/backend.js`: in the shared `request()`, merge `impersonationHeaders()` into the headers
  (one FENCED block) so ALL calls carry it.
- `views/AdminView.vue`: the existing "Review conversations" button now opens the user-picker modal
  (not a route push). FENCED.
- `stores/session.js`: read `impersonating` + `real_user_id` from `/me`; expose `impersonating`.
- `stores/chat.js`: add `&& !session.impersonating` to `canSend` (FENCED). `ChatView`/`PromptBar`
  show a small "read-only, viewing <user>" note when impersonating (server also blocks - defense).
- `components/shell/AppLayout.vue` (or App.vue): render `<ImpersonateBanner v-if="session.impersonating"/>`
  at the top. FENCED.
- i18n: add `impersonate.*` keys (en + fr, proper French accents) to `extra.js`; remove `inspect.*`.
- Removal later = delete `features/admin-impersonate/` + revert the FENCED one-liners + the impersonate.* keys.

## Verification (orchestrator, after agents)
- Merge `frontend/src/i18n/extra.js` with the `authgate.*` (A) and `inspect.*` (C) keys (fr+en).
- Frontend compile check (no install): `./node_modules/.bin/vite build --outDir /tmp/owi_bc --emptyOutDir` then `rm -rf /tmp/owi_bc`.
- Backend tests: `python3 -m unittest discover -s Plugin/owismind/tests`.
- Frontend pure tests: `node --test test/*.test.js` from `Plugin/owismind/frontend/`.
- No em dash anywhere (Python scan, not BSD grep -P; L093).
- Then `/build-plugin` (prod) + `/package-plugin` (prod) AND run `tools/build_dev_plugin.py` (DEV zip).
- NON validated DSS (the user uploads + smoke-tests).
