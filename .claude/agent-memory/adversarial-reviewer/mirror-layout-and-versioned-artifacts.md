---
name: mirror-layout-and-versioned-artifacts
description: OWIsMind agent-mirror now lives at repo root OWIsMind_PRD_V1_3_DEV/ (not dataiku-agents/); plugin artifacts are version-derived from plugin.json
metadata:
  type: project
---

Restructure landed 2026-07-10 (branch `OWIsMind_PRD_V1_2`, move commit `5565a0f`).

**Layout.** The agent system is mirrored at repo ROOT under `OWIsMind_PRD_V1_3_DEV/`
(was `dataiku-agents/OWISMIND/OWISMIND_DEV|OWISMIND_PROD_V1/`). Zones:
`agents/` (3 Code Agent .py), `tools/attribute_lookup_tool.py`,
`flow/{SalesDrive_Revenue_Expert,CSC_ticket_AI_Agent,Webapp_Zone}/` (the 6 recipes,
named `compute_*`), `semantic-models/{<Model>/*.v1.json, scripts/, MODEL.md, README.md,
TOOL_DESCRIPTIONS.md}`, `registry.json`, `tests/`, README/CLAUDE/PLAYBOOK. The old
`dataiku-agents/` tree and `tools/promote_agents_to_prod.py` are DELETED.

**Byte-identity contract of the mirror.** The 3 agents + attribute_lookup_tool + 6
recipes are AST-identical to their a07ee1e ancestors; only comment/docstring path
fixes differ (`dataiku-agents/tests/... -> OWIsMind_PRD_V1_3_DEV/tests/...`,
`OWISMIND/README.md -> OWIsMind_PRD_V1_3_DEV/README.md`, filename mentions). The 3
tickets-zone recipes are BYTE-identical to their revenue-zone siblings. Verify with
`ast.dump` (docstrings stripped) + a plain `diff` of each zone sibling pair.

**Version-derived artifacts.** `OWIsMind_PRD_V1_3_DEV/plugin/tools/build_dev_plugin.py` and the `/package-plugin`
skill read `plugin.json` `"version"` (JSONC, regex not json.load) and reduce to
`major_minor` with `_` (1.2.0 -> `1_2`). Prod zip = `owismind-v1_2-upload.zip`; DEV =
`owismind-v1_2-dev-upload.zip` (+ `-dev-v2-`). Both sweep older
`owismind-v*-*upload*` / legacy `owismind-upload`/`owismind_dev-upload` before build.
`DEV_ID`/`PROD_ID` and the id-rewrite logic in build_dev_plugin.py are UNCHANGED (only
naming + a new `_cleanup_stale_dev_artifacts()`). Prod zip had 95 entries, no
frontend/node_modules/CLAUDE.md/README.md/__pycache__.

**Known doc drift (mineur, not blocking):** the `/package-plugin` skill + on-disk
staging dir are versioned (`owismind-v1_2-upload/`), but `memory/PROJECT_STATE.md`
prose still names the staging DIR `owismind-upload/` (zip name is correct everywhere).
`OWIsMind_PRD_V1_3_DEV/GenAI/agents-tools/README.md` labels `tickets_semantic_query` status "LIVE"
while registry/CLAUDE/README/DEPLOY_V1_2 say its model repoint is still pending.
See [[repo-review-pitfalls]] and [[verifying-zero-behavior-cleanup]].
