---
name: package-plugin-dev
description: Build and package the coexisting DEV copy of the OWIsMind DSS plugin (id owismind_dev) from the single source via tools/build_dev_plugin.py. Use when the user asks to build/package the DEV plugin, the dev zip, or a test plugin that installs alongside prod. Never uploads, never installs.
---

# /package-plugin-dev - Build the coexisting DEV plugin (id `owismind_dev`)

There is ONE source of truth: `Plugin/owismind/`. The PROD build/package (`/build-plugin`
+ `/package-plugin`) is unchanged. This skill emits a SECOND, independent plugin
(id `owismind_dev`) that installs ALONGSIDE the prod one on the same DSS instance, for testing.

Everything is done by one deterministic, reviewed script: **`tools/build_dev_plugin.py`**.
**It never installs anything and never edits the canonical source** (it builds into a scratch
dir and stages under `Plugin/ready-for-dataiku/`).

## Why a DEV plugin needs renaming
Two installed plugins on one instance collide unless three things differ:
1. **plugin id** - globally unique (`owismind` -> `owismind_dev`).
2. **Vite asset base** - `/plugins/<id>/resource/owismind-app/` (env-driven by `OWI_PLUGIN_ID`).
3. **python package name** - `import owismind` is process-global across plugins on the same code
   env (`owismind` -> `owismind_dev`).

What MUST NOT change (so DEV behaves like PROD, just isolated):
- `APP_NAMESPACE = "owismind"` (SQL table namespace).
- the HTTP prefix `/owismind-api` and the Flask blueprint name `owismind_api`.
- the build outDir folder name `owismind-app` inside `resource/` (only the `/plugins/<id>/`
  segment of the asset base carries the plugin id).

## Canonical paths
- Source plugin:  `Plugin/owismind` (untouched)
- Script:         `tools/build_dev_plugin.py`
- Staging dir:    `Plugin/ready-for-dataiku/owismind_dev-upload`
- Zip output:     `Plugin/ready-for-dataiku/owismind_dev-upload.zip`

## Steps

1. **Validate the rewrite first (no build, no zip).** This copies `python-lib` to `/tmp`,
   runs the package + logger rewrite, asserts the invariants, and discards the copy:
   ```bash
   python3 tools/build_dev_plugin.py --check
   ```
   Expect: `--check PASSED`, 0 `from owismind` / `import owismind` (word-boundary), the
   `APP_NAMESPACE`/`/owismind-api`/blueprint literals intact, `getLogger("owismind_dev")`.

2. **Preflight - never install.** The full build runs `vite build` and requires existing deps:
   ```bash
   test -d Plugin/owismind/frontend/node_modules && echo "node_modules OK" || echo "MISSING"
   ```
   If `MISSING`: STOP. Ask the user to install (`! cd Plugin/owismind/frontend && npm install`).
   The script itself errors out if `node_modules` is absent; it never installs.

3. **Build + stage + zip the DEV plugin:**
   ```bash
   python3 tools/build_dev_plugin.py
   ```
   The script:
   - builds the frontend with `OWI_PLUGIN_ID=owismind_dev` into a scratch outDir (the canonical
     `resource/owismind-app/` is NEVER touched);
   - stages `plugin.json` with `id` -> `owismind_dev`, `label` -> `OWIsMind (DEV)`;
   - copies `python-lib/owismind` -> `python-lib/owismind_dev` with the scoped rewrites
     (`from owismind` / `import owismind` word-boundary, `getLogger("owismind")`);
   - stages `resource/` (DEV-base app + `compute_available_connections.py`) and `webapps/`
     (`backend.py` import rewritten, `body.html` = DEV-base `index.html`);
   - zips to `Plugin/ready-for-dataiku/owismind_dev-upload.zip`, excluding the SAME dev-only
     files as `/package-plugin` (frontend, node_modules, CLAUDE.md, README.md, `__pycache__`,
     `*.pyc`, `.DS_Store`);
   - prints and ASSERTS the invariants (fails loudly if any is violated).

## Invariants the script asserts (and prints)
- Staged `python-lib/owismind_dev` has **0** matches for `from owismind\b` / `import owismind\b`
  (the `\b` word-boundary does not match `owismind_dev`).
- `APP_NAMESPACE = "owismind"` present, `/owismind-api` present, `Blueprint("owismind_api"` present.
- `getLogger("owismind")` -> `getLogger("owismind_dev")` (the root app logger only;
  `getLogger(__name__)` follows the package rename automatically).
- `python-lib/owismind_dev/__init__.py` present; staged `backend.py` imports
  `owismind_dev.api.routes`.
- `body.html` base = `/plugins/owismind_dev/resource/owismind-app/` (no prod base).
- `webapp.json` `meta.label` = `OWIsMind - AI Agents (DEV)` (+ `[DEV]` description prefix), so the
  two plugins' webapps are DISTINGUISHABLE in the DSS webapp list (the list shows the webapp label,
  not the plugin label).
- Zip is clean (no frontend/node_modules/docs/caches) and carries the required runtime files.

## Upload + data isolation (manual; this skill does NOT upload)
- Upload `owismind_dev-upload.zip` to DSS as an **Uploaded** plugin. Its id `owismind_dev` is
  distinct from the prod `owismind`, so both can be installed at once. (A *Development* plugin
  with the same id cannot be updated by zip upload; delete it first, then upload - see the build
  guide in `docs/cadrage/`.)
- **DEV data: same code as prod, create-if-not-exist.** The webapp creates its tables if absent
  and reuses them if present (`ensure_*` helpers / `CREATE TABLE IF NOT EXISTS`). So it is a
  DEPLOY-TIME choice (never code; prod tables are never renamed):
  - DEV webapp on the prod connection with **NO prefix** -> it connects to the SAME tables as prod
    (sees the real users/conversations). Use this when you want the admin impersonation feature to
    review REAL users.
  - DEV webapp with **`table_prefix = "dev"`** -> tables become `{PROJECT_KEY}_dev-owismind_...`, a
    separate sandbox with its own users/conversations. Use this to test in isolation.
- The admin **impersonation ("act as user")** feature is part of the webapp (Administration ->
  "Review conversations" -> pick a user -> the webapp reloads AS that user, READ-ONLY, admin-only).
  It reviews whatever users exist in the tables THIS instance is connected to (real prod data when
  no prefix; the dev sandbox when `table_prefix="dev"`).

## Notes
- Do not edit anything under `ready-for-dataiku/` by hand - it is regenerated by the script.
- The script writes only under `Plugin/ready-for-dataiku/` and a scratch `/tmp` dir; it never
  modifies `Plugin/owismind/` or `resource/owismind-app/`.
- The whole DEV target is additive: it does not change the PROD `/build-plugin` or `/package-plugin`
  flow (the default `OWI_PLUGIN_ID` is `owismind`).
