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

## `promote_agents_to_prod.py`

Regenerates the `OWISMIND_PROD_V1_*` Code Agent files from their `OWISMIND_DEV_*` sources, applying the
per-project id substitutions and surgically removing the tickets-expert block (intentionally absent
from prod until validated). Idempotent: it prints the DEV/PROD diff for review, refuses to write on any
unexpected state, and compile-checks the generated files. The id map lives in
`dataiku-agents/OWISMIND/README.md`.
