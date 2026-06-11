---
name: build-plugin
description: Build the OWIsMind Vue 3 + Vite frontend into the DSS plugin (resource/owismind-app/) and wire body.html. Use when the user asks to build the plugin, build the frontend, rebuild assets, or refresh body.html. Never installs dependencies.
---

# /build-plugin — Build the Vue frontend into the DSS plugin

Builds `Plugin/owismind/frontend/` with Vite and wires the result into the DSS webapp.
**This skill never installs anything.** If `node_modules/` is missing, STOP and ask the user to install.

## Canonical paths (do not invent — see memory/PROJECT_STATE.md)
- Plugin root:   `Plugin/owismind`
- Frontend:      `Plugin/owismind/frontend`
- Build output:  `Plugin/owismind/resource/owismind-app` (Vite `outDir`, `emptyOutDir: true`)
- DSS entry:     `Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html`
- Asset base:    `/plugins/owismind/resource/owismind-app/`

## Steps

1. **Preflight — never install.** Verify dependencies exist:
   ```bash
   test -d Plugin/owismind/frontend/node_modules && echo "node_modules OK" || echo "MISSING"
   ```
   If `MISSING`: STOP. Tell the user to run `npm install` themselves (e.g. `! cd Plugin/owismind/frontend && npm install`). Do **not** attempt any install — it is denied by policy.

2. **Build** from the frontend directory:
   ```bash
   npm --prefix Plugin/owismind/frontend run build
   ```
   Confirm the output landed in `Plugin/owismind/resource/owismind-app/` (hashed `assets/index-*.js` / `*.css`).

3. **Wire body.html** — copy the built entry point (this Bash `cp` is allowed; do NOT use Edit/Write on the output, it is blocked):
   ```bash
   cp Plugin/owismind/resource/owismind-app/index.html \
      Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html
   ```

4. **Verify** the asset paths are correct:
   ```bash
   grep -q '/plugins/owismind/resource/owismind-app/' \
      Plugin/owismind/webapps/webapp-owismind-ai-agents/body.html \
      && echo "body.html OK" || echo "ERROR: asset base missing in body.html"
   ```

5. **Report** to the user (in French): what was built, output files, and whether `body.html` is wired.
   Remind that packaging is a separate step (`/package-plugin`) and that nothing is uploaded.

## Notes
- If `vite.config.js` `base` ever changes, the build + body.html copy must be redone.
- `frontend/` and `node_modules/` must never enter the zip — that is handled by `/package-plugin`.
- Do not edit files under `resource/owismind-app/` by hand; always regenerate via this skill.
