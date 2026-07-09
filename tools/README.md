# tools

Repo-level Python helper scripts. Run them from the repository root with `python3`. Standard library
only, no installs. They never edit the canonical plugin source or generated build output.

## `build_dev_plugin.py`

Builds and packages a coexisting **DEV copy** of the OWIsMind plugin (id `owismind_dev`) from the
single source in `Plugin/owismind/`, so it can be installed alongside the prod plugin on the same DSS
instance for testing. Rewrites the three colliding axes (plugin id, Vite asset base, Python package
name) deterministically; the prod build/package is left untouched. Invoked by the `/package-plugin-dev`
skill. `--v2` emits a third coexisting plugin (`owismind_dev_v2`); `--check` validates the rewrite logic
without building.

Artifact names are **version-derived** from `Plugin/owismind/plugin.json` (`major_minor` with
underscores, e.g. `1.2.0` -> `1_2`), matching the one-branch-per-version model:

- DEV:    `Plugin/ready-for-dataiku/owismind-v{VER}-dev-upload.zip`
- DEV v2: `Plugin/ready-for-dataiku/owismind-v{VER}-dev-v2-upload.zip`

Before a build the script clears stale `owismind-v*-dev-*upload*` artifacts and the legacy fixed
`owismind_dev-upload*` names, keeping only the current version's DEV / DEV-v2 pair.

> Prod promotion is no longer a script. Since 2026-07, PROD is a **clone of the DEV DSS project**
> (`OWISMIND_PRD_V1_2` duplicates `OWISMIND_DEV`, all object ids preserved), so there is no per-project
> id substitution to run. When an agent needs re-pasting, its source lives at `OWIsMind_PRD_V1_2/agents/`
> (id map in `OWIsMind_PRD_V1_2/README.md` + `OWIsMind_PRD_V1_2/registry.json`).
