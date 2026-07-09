# tools

Repo-level Python helper scripts. Run them from the repository root with `python3`. Standard library
only, no installs. They never edit the canonical plugin source or generated build output.

## `build_dev_plugin.py`

Builds and packages a coexisting copy of the OWIsMind plugin from the single source in
`Plugin/owismind/`, so it can be installed alongside the prod plugin on the same DSS instance for
testing. Rewrites the three colliding axes (plugin id, Vite asset base, Python package name)
deterministically; the prod build/package (`/build-plugin` + `/package-plugin`) is left untouched.
`--check` validates the rewrite logic on a `/tmp` copy without building or zipping.

Three coexisting identities, selected by flag (mutually exclusive; default = DEV):
- (default) **DEV**: id `owismind_dev`, zip `owismind_dev-upload.zip`. Invoked by the
  `/package-plugin-dev` skill.
- `--v2`: a fixed **third** slot, id `owismind_dev_v2`, zip `owismind_dev_v2-upload.zip` - so a
  stable DEV install stays untouched while testing another change.
- `--version X.Y` (e.g. `--version 1.3`): a **version-named** slot, id `owismind_vX_Y`
  (`owismind_v1_3`), plugin label `OWIsMind vX.Y`, webapp label `OWIsMind AI Agents vX.Y`, zip
  `owismind-vX_Y-upload.zip` (`owismind-v1_3-upload.zip`). For testing a specific release
  side by side with prod, DEV, and other versions. A single internal helper
  (`_version_names`/`use_version_identity`) derives id/label/zip/asset-base from the version
  string, so `--version 1.4`, `1.5`, ... need no new code. Combine with `--check` to validate
  that version's rewrite only, without building or zipping (`--check --version 1.3`).

Every mode stages into its own tree under `Plugin/ready-for-dataiku/` and never touches the
canonical `Plugin/owismind/` source, `Plugin/owismind/resource/owismind-app/`, or the prod zip.

## `promote_agents_to_prod.py`

Regenerates the `OWISMIND_PROD_V1_*` Code Agent files from their `OWISMIND_DEV_*` sources, applying the
per-project id substitutions and surgically removing the tickets-expert block (intentionally absent
from prod until validated). Idempotent: it prints the DEV/PROD diff for review, refuses to write on any
unexpected state, and compile-checks the generated files. The id map lives in
`dataiku-agents/OWISMIND/README.md`.
