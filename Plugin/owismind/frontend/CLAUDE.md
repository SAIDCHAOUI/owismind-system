# Frontend rules - frontend/ (OWIsMind Vue 3 + Vite)

Path-scoped guidance for the Vue source. Full context: repo-root CLAUDE.md + memory/.

## Build & output
- Build via the `/build-plugin` skill (`npm run build`). Output goes to `../resource/owismind-app/`
  (`outDir`), with `base: '/plugins/owismind/resource/owismind-app/'`. **Never change these names** -
  they are canonical (see memory/PROJECT_STATE.md).
- **Never hand-edit** `resource/owismind-app/` (generated). Edit source here, then rebuild.
- After each build, copy `resource/owismind-app/index.html` → `webapps/.../body.html` (done by `/build-plugin`).

## Hard rules
- **NO installs**: never run `npm install` / `npm i` / `npx` installs etc. If a package is needed, ask the
  user to install it - only the user installs (safety first).
- `frontend/` and `node_modules/` must **never** be packaged into the zip.
- Code & comments in **English**, optimized, professional, well-commented.

## Target UI
- The Vue 3 conversion is COMPLETE and validated in DSS: design system (Orange branding, light/dark),
  Chat + live timeline + Evidence Studio, FR/EN i18n. The original mockup (`maquette/`) was removed from
  the repo on 2026-06-11 after conversion - the references are now the app itself, `docs/frontend.md`,
  and memory/PROJECT_STATE.md §13.
- Backend calls go through `getWebAppBackendUrl('/owismind-api/...')` - never hardcode URLs.
