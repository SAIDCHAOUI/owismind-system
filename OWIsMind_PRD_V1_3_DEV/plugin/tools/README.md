# tools

Repo-level Python helper scripts. Run them from the repository root with `python3`. Standard library
only, no installs. They never edit the canonical plugin source or generated build output.

## `build_dev_plugin.py`

Builds and packages a coexisting copy of the OWIsMind plugin from the single source in
`OWIsMind_PRD_V1_3_DEV/plugin/owismind/`, so it can be installed alongside the prod plugin on the same DSS instance for
testing. Rewrites the three colliding axes (plugin id, Vite asset base, Python package name)
deterministically; the prod build/package (`/build-plugin` + `/package-plugin`) is left untouched.
`--check` validates the rewrite logic on a `/tmp` copy without building or zipping.

Three coexisting identities, selected by flag (mutually exclusive; default = DEV):
- (default) **DEV**: id `owismind_dev`, zip `owismind-v{VER}-dev-upload.zip`. Invoked by the
  `/package-plugin-dev` skill.
- `--v2`: a fixed **third** slot, id `owismind_dev_v2`, zip `owismind-v{VER}-dev-v2-upload.zip` - so a
  stable DEV install stays untouched while testing another change.
- `--version X.Y` (e.g. `--version 1.3`): a **version-named** slot, id `owismind_vX_Y`
  (`owismind_v1_3`), plugin label `OWIsMind vX.Y`, webapp label `OWIsMind AI Agents vX.Y`, zip
  `owismind_vX_Y-upload.zip` (`owismind_v1_3-upload.zip`; underscore form = the plugin id, so it
  never collides with the prod zip `owismind-vX_Y-upload.zip`). For testing a specific release
  side by side with prod, DEV, and other versions. A single internal helper
  (`_version_names`/`use_version_identity`) derives id/label/zip/asset-base from the version
  string, so `--version 1.4`, `1.5`, ... need no new code. Combine with `--check` to validate
  that version's rewrite only, without building or zipping (`--check --version 1.3`).

Every mode stages into its own tree under `OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/` and never touches the
canonical `OWIsMind_PRD_V1_3_DEV/plugin/owismind/` source, `OWIsMind_PRD_V1_3_DEV/plugin/owismind/resource/owismind-app/`, or the prod zip.

Artifact names are **version-derived** from `OWIsMind_PRD_V1_3_DEV/plugin/owismind/plugin.json` (`major_minor` with
underscores, e.g. `1.2.0` -> `1_2`), matching the one-branch-per-version model:

- DEV:    `OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/owismind-v{VER}-dev-upload.zip`
- DEV v2: `OWIsMind_PRD_V1_3_DEV/plugin/ready-for-dataiku/owismind-v{VER}-dev-v2-upload.zip`

Before a build the script clears stale `owismind-v*-dev-*upload*` artifacts and the legacy fixed
`owismind_dev-upload*` names, keeping only the current version's DEV / DEV-v2 pair.

> Prod promotion is no longer a script. Since 2026-07, PROD is a **clone of the DEV DSS project**
> (`OWISMIND_PRD_V1_2` duplicates `OWISMIND_DEV`, all object ids preserved), so there is no per-project
> id substitution to run. When an agent needs re-pasting, its source lives at `OWIsMind_PRD_V1_3_DEV/GenAI/Agents/`
> (id map in `OWIsMind_PRD_V1_3_DEV/README.md` + `OWIsMind_PRD_V1_3_DEV/registry.json`).
