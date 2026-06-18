# ADR-0001 - Vue SPA served by DSS as static assets

> Audience: Developer. Last updated: 2026-06-18. Summary: why the OWIsMind frontend is a
> Vue 3 + Vite SPA built into `resource/owismind-app/` and served by DSS as static assets, with a
> router in HASH history mode and a generated `body.html`.

## Status

Accepted and validated in DSS. The Vue 3 conversion is complete (the original HTML mockup was converted and then
removed from the repository on 2026-06-11). This decision is foundational and stable.

## Context

OWIsMind is a Dataiku DSS plugin (id `owismind`, version `0.0.1`). Its WebApp (`webapp-owismind-ai-agents`)
is served by DSS at a fixed URL: the static assets live under
`/plugins/owismind/resource/owismind-app/` and the entry page is a `body.html` injected by DSS into its
own HTML shell. Two constraints of the DSS model drive the entire decision:

- DSS serves the static files from the plugin's `resource/` folder at an imposed path. There is no
  Node server in production: the frontend must be pre-built HTML/CSS/JS.
- DSS applies NO server-side URL rewriting for a SPA (no "history fallback" to
  `index.html`). A router in "history path" mode would therefore produce a 404 on page reload or when
  sharing a deep link.

In addition, the project NO INSTALL rule forbids any agent from installing a dependency: library versions
are frozen once and for all, and only the user installs. We therefore need a locked-down, reproducible
frontend stack with no version surprises.

## Decision

The frontend is a Single Page Application built with **Vue 3** and **Vite**, delivered as static assets that
DSS serves directly. Five concrete choices follow from this.

### 1. Vue 3 + Vite stack, frozen versions

The source code lives in `Plugin/owismind/frontend/` (Composition API, ES modules). The dependencies in
`frontend/package.json` are pinned (`vue@^3.5.34`, `vue-router@^5.1.0`, `vue-i18n@^11.4.4`,
`pinia@^3.0.4`, plus `chart.js`, `markdown-it`, `dompurify`), built by `vite@^8` with
`@vitejs/plugin-vue`. NO INSTALL imposes this locking: the agent never upgrades these versions, only
the user installs.

### 2. Build base and output aligned with the DSS path

`Plugin/owismind/frontend/vite.config.js` sets two canonical values that must never be renamed:

```js
base: '/plugins/owismind/resource/owismind-app/',
build: {
  outDir: '../resource/owismind-app',
  emptyOutDir: true,
},
```

The `base` prefixes ALL asset URLs emitted by Vite (scripts, CSS, modulepreload, favicon) with the
exact path where DSS serves the `resource/` folder. The build writes into `resource/owismind-app/` (with
`emptyOutDir: true`, so a clean output on each build). Because the `base` is absolute and already correct, the
generated `index.html` references its assets at the right DSS URL without any manual editing.

### 3. Router in HASH history (mandatory)

`frontend/src/router/index.js` uses `createWebHashHistory()` (from `vue-router`), not
`createWebHistory()`:

```js
export const router = createRouter({
  history: createWebHashHistory(),
  routes,
})
```

The routes (`/chat/:sessionId?`, `/settings`, `/agents/:agentId?`, `/admin` guard, etc.) therefore live after
the `#` (URLs like `#/chat/<sessionId>`). Reload and deep-linking stay client-side: DSS always serves
the same entry page, and it is the browser that resolves the route from the fragment. The admin
route is protected by a `router.beforeEach` that resolves the identity (memoized via the session store) before
granting access.

### 4. Theme set on `body[data-theme]` BEFORE the mount

`frontend/src/main.js` writes `document.body.dataset.theme` (read from `localStorage`, default `light`) BEFORE
`app.mount('#app')`. The semantic tokens (light/dark colors) live under
`body[data-theme="..."]`; setting them before the mount avoids a flash of unstyled tokens. The `ui` store
then reconciles the state.

### 5. `body.html` is a GENERATED file, rewired after each build

DSS injects the content of
`Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html` as the page body. After each build, the
`/build-plugin` skill copies `resource/owismind-app/index.html` to this `body.html`. Because the Vite `base` is
absolute, the generated `index.html` already carries the correct URLs (scripts and CSS pointing to
`/plugins/owismind/resource/owismind-app/assets/...`), so the copy is sufficient: `body.html` references the
hashed bundles (for example `assets/index-<hash>.js` and the associated CSS) as produced by Vite.

> IN FLUX: the `/build-plugin` skill currently documents the `body.html` wiring step via an authorized
> Bash `cp` (direct editing of files under `resource/owismind-app/` remains blocked). A historical
> lesson (L033) reported a `cp` to `body.html` refused by the permissions, worked around via
> the Write tool by rewriting the hashes. Follow the actual behavior of the `/build-plugin` skill at
> build time; the invariant principle is: `body.html` is generated from the built `index.html`, never edited by
> hand.

## Diagram

The official build goes through the `/build-plugin` skill (never build directly into `resource/` during
dev: a compile-check is done into `/tmp` then `rm -rf`). The detailed diagram of the build pipeline and
assets is canonical in [Frontend - build and assets](../03-frontend/05-build-and-assets.md). In one sentence:
`frontend/src` -> `vite build` -> `resource/owismind-app/` (hashed assets + `index.html`) -> copy to
`body.html` -> DSS serves it all.

## Rationale

| Choice | Why |
|---|---|
| Vue 3 + Vite SPA, built | DSS serves static assets at a fixed path; no Node server in prod. Deployment reduces to uploading a zip of assets. |
| Absolute `base` = DSS path | DSS imposes the serving URL of the `resource/` folder; aligning the `base` on it makes all asset links correct without post-processing. |
| HASH history | DSS does not rewrite SPA URLs; the hash keeps everything client-side and survives reload and deep-linking. |
| Frozen versions | NO INSTALL: no install by the agent, hence a reproducible and predictable stack. |
| `body.html` generated from `index.html` | A single source of truth (the build); no divergence between the asset hashes and the entry page. |

## Consequences

### Positive

- Simple deployment: an upload of a static-asset zip, no server runtime on the frontend side.
- Modular, registry-based architecture: shared UI primitives, Pinia stores per domain, lazy views
  (`() => import(...)`) to keep the chat's initial bundle light. Adding a page = adding a route
  entry.
- Robust reload and deep links: `#/chat/<sessionId>` reopens without a 404 thanks to the hash.
- The frontend always calls the backend via `getWebAppBackendUrl('/owismind-api/...')` (never a hardcoded
  URL): the DSS prefix is resolved by DSS (see
  [Frontend - backend communication](../03-frontend/04-backend-communication.md)).

### Negative / constraints

- URLs in `#/route`, less "clean" than pure paths (an accepted trade-off of the DSS model).
- `body.html` is a GENERATED artifact: it must be rewired after each build (a step of the
  `/build-plugin` skill). NEVER edit by hand `resource/owismind-app/` or `body.html`: edit the source
  (`frontend/src`) then rebuild.
- In DEV (Vite dev server, without DSS), there is no backend: `getWebAppBackendUrl` is absent, so the
  stores must degrade gracefully (no crash without a backend).
- The canonical names (`base`, `outDir`, the `owismind-app` folder) are foundational: renaming them breaks the
  serving of assets by DSS.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Router in HISTORY path (`createWebHistory`) | 404 on reload and deep-link, because DSS has no server-side history fallback. |
| Serve via a Node server in production | Outside the DSS model (no Node runtime for a plugin WebApp); needless complexity and surface. |
| Keep the original HTML mockup | Converted to Vue 3 then removed from the repository on 2026-06-11: the Vue SPA is the reference, no longer the mockup. |
| Freely upgrade library versions | Forbidden by NO INSTALL: only the user installs; versions stay frozen for reproducibility. |

## See also

- [Frontend - overview and structure](../03-frontend/01-overview-and-structure.md) - bootstrap, hash router, i18n, theme in detail.
- [Frontend - build and assets](../03-frontend/05-build-and-assets.md) - canonical home of the `base`/`outDir`/`body.html` pipeline and the hashes.
- [Frontend - backend communication](../03-frontend/04-backend-communication.md) - `getWebAppBackendUrl`, call catalog, error codes.
- [Build, packaging and deployment](../06-operations/02-build-package-deploy.md) - `/build-plugin` and `/package-plugin` skills, what-to-rebuild-when matrix.
- [Architecture overview](../02-architecture/01-system-overview.md) - the frontend's place within the four layers.
- [Architecture Decision Records (ADR) - index](README.md) - list of the twelve ADRs.
