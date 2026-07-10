# =============================================================================
# 02_align_clone.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK inside the CLONED project (the project that was
# duplicated from another OWIsMind project). Duplicating a DSS project does NOT
# rewrite the semantic models' dataset references: every copied model keeps
# pointing at the SOURCE project's datasets (logical "<OLDKEY>.<Dataset>" refs and
# physical "<OLDKEY>_<table>" SQL literals). The UI cannot fix that; this notebook
# does, by remapping every foreign project-key prefix to THIS project's key.
#
# It generalizes the two validated one-off scripts (semantic-models/scripts/
# repoint_tickets_prod_clone.py and add_solution_and_repoint_prod_clone.py) to
# ALL models of the current project, discovering the old key automatically.
#
# Read-only by default: DRY_RUN=True prints the PLAN and the SCAN, nothing is
# saved. Review the plan, then flip DRY_RUN=False (and REINDEX=True to rebuild the
# value-matching index on the new tables) and re-run.
#
# Uses owismind_factory.align (paste this repo's project-library into the DSS
# project library first) and the documented semantic-model API only.
# =============================================================================

import dataiku
from owismind_factory import align
from owismind_factory.fctx import FactoryContext

# --------------------------------------------------------------------------- CONFIG
DRY_RUN = True      # True = preview only; flip to False to apply the remap
REINDEX = False     # True = rebuild distinct-value index on the new table after saving

# --------------------------------------------------------------------------- resolve project
client = dataiku.api_client()
project = client.get_default_project()
print("Project (this notebook runs in):", project.project_key)

# --------------------------------------------------------------------------- scan (read-only)
print("=" * 72)
print("SCAN - semantic models still pointing at another project's datasets")
print("=" * 72)
report = align.scan(project)
if not report:
    print("No semantic models found in this project.")
for row in report:
    print("\n- model:", row.get("model_name"),
          "(id %s) version %s" % (row.get("model_id"), row.get("version_id")))
    if row.get("error"):
        print("    could not read:", row["error"])
        continue
    print("    dataset refs      :", row.get("dataset_refs"))
    print("    foreign keys found:", row.get("foreign_keys_found") or "(none - already aligned)")
    print("    golden-query hits :", row.get("golden_query_hits"))

# --------------------------------------------------------------------------- align (planned/executed)
print("\n" + "=" * 72)
print("ALIGN - remap foreign project-key prefixes to %s" % project.project_key)
print("=" * 72)
ctx = FactoryContext(project, dry_run=DRY_RUN)
align.align(project, ctx, reindex=REINDEX)
print(ctx.report_markdown("Align clone semantic models"))

if DRY_RUN:
    print("\nDRY_RUN=True -> nothing was saved. Review the SCAN (foreign keys) and the "
          "plan above, then set DRY_RUN=False (and REINDEX=True to re-index value "
          "matching) and re-run. After applying, confirm each agent's generated SQL "
          "uses %s_* tables and re-test in the webapp." % project.project_key)
