# =============================================================================
# repoint_tickets_prod_clone.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK inside the PROD CLONE project (the project that
# was duplicated from OWISMIND_DEV, whose datasets resolve to physical tables
# named OWISMIND_PRD_V1_2_*). It repoints the TICKETS semantic model at the
# clone's OWN dataset instead of the DEV dataset it still points at after the
# project duplication.
#
# WHY THIS IS NEEDED: duplicating a DSS project does NOT rewrite the semantic
# model's dataset references. The model keeps pointing at "OWISMIND_DEV.
# TroubleTickets_year" (entity datasetRef) and, in any golden-query SQL, at the
# DEV physical table "OWISMIND_DEV_troubletickets_year". The UI gives no way to
# change that; the config edit below does. After this, the clone's tickets agent
# queries OWISMIND_PRD_V1_2_troubletickets_year, and the webapp Evidence panel can
# map the FROM table to a dataset in this project.
#
# SCOPE: TABLE ONLY. No instructions / golden-query text / attribute / metric
# change (the user asked for none on tickets). This is a pure string remap of the
# project-key prefix, exactly like remap_semantic_model.py, done in place.
#
# Documented API only:
#   project.get_semantic_model(id) -> get_active_version_id() -> get_version()
#   -> get_settings() -> get_raw()/save();  get_version(id)
#   -> start_update_distinct_values().wait_for_result()
# =============================================================================

import dataiku

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
SOURCE_PROJECT_KEY = "OWISMIND_DEV"        # what the refs (wrongly) still point at
TARGET_PROJECT_KEY = ""                     # "" -> derive from the running project
                                            # (this notebook's project = the clone)
MODEL_ID   = ""                              # "" -> resolve by MODEL_NAME (robust to id
                                            # reassignment); clone likely kept DEV id dM4jA4G
MODEL_NAME = "TroubleTickets_Semantic_Model"
DRY_RUN    = True                            # True = preview only; flip to False to apply
REBUILD_DISTINCT_VALUES = True               # re-index value matching on the new table


# ----------------------------------------------------------------------------
# RESOLVE THE RUNNING PROJECT (the clone) AND THE TARGET KEY
# ----------------------------------------------------------------------------
client  = dataiku.api_client()
project = client.get_default_project()       # the project this notebook runs in
target_key = TARGET_PROJECT_KEY or project.project_key

assert target_key != SOURCE_PROJECT_KEY, (
    "Target key == source key (%s). This notebook must run in the PROD CLONE "
    "project, not in %s. Refusing to touch the DEV model." % (target_key, SOURCE_PROJECT_KEY))

# The two forms the project key appears in inside the config:
#   dataset refs : "<KEY>.<Dataset>"   (entity datasetRef)
#   phys tables  : "<KEY>_<dataset>"   (golden-query / instruction SQL literal)
REPLACEMENTS = {
    SOURCE_PROJECT_KEY + ".": target_key + ".",
    SOURCE_PROJECT_KEY + "_": target_key + "_",
}


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
def remap(value):
    """Recursively rewrite every string: source-key prefix -> target-key prefix. Pure."""
    if isinstance(value, dict):
        return {k: remap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v) for v in value]
    if isinstance(value, str):
        for old, new in REPLACEMENTS.items():
            value = value.replace(old, new)
        return value
    return value


def resolve_model():
    """The model for MODEL_ID, else the one named MODEL_NAME. Raises if neither."""
    if MODEL_ID:
        return project.get_semantic_model(MODEL_ID)
    for h in project.list_semantic_models():
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        mid  = h.get("id")   if isinstance(h, dict) else getattr(h, "id", None)
        if name == MODEL_NAME and mid:
            return project.get_semantic_model(mid)
    raise RuntimeError("Model not found: set MODEL_ID or check MODEL_NAME=%r" % MODEL_NAME)


def source_refs(config):
    """Every string still mentioning the SOURCE key (for the before/after preview)."""
    hits = []

    def walk(v):
        if isinstance(v, dict):
            for c in v.values():
                walk(c)
        elif isinstance(v, list):
            for c in v:
                walk(c)
        elif isinstance(v, str) and SOURCE_PROJECT_KEY in v:
            hits.append(v[:160])

    walk(config)
    return hits


# ----------------------------------------------------------------------------
# REMAP IN PLACE
# ----------------------------------------------------------------------------
model = resolve_model()
version_id = model.get_active_version_id()
assert version_id, "The tickets semantic model has no active version."
settings = model.get_version(version_id).get_settings()
raw = settings.get_raw()

before = source_refs(raw)
fixed  = remap(raw)
after  = source_refs(fixed)

print("Project (clone) :", project.project_key)
print("Model           :", model.id, "| active version", version_id)
print("Remap           : %s.* -> %s.*  and  %s_* -> %s_*"
      % (SOURCE_PROJECT_KEY, target_key, SOURCE_PROJECT_KEY, target_key))
print("Strings mentioning %s BEFORE: %d" % (SOURCE_PROJECT_KEY, len(before)))
for s in before[:20]:
    print("   -", s)
print("Strings still mentioning %s AFTER remap: %d %s"
      % (SOURCE_PROJECT_KEY, len(after), "(should be 0)" if not after else "<-- CHECK"))
for s in after[:20]:
    print("   !!", s)

if DRY_RUN:
    print("\nDRY_RUN=True -> nothing saved. Review the AFTER count is 0, then set DRY_RUN=False.")
else:
    raw.clear()
    raw.update(fixed)
    settings.save()
    print("\nSaved. Model repointed to the %s datasets/tables." % target_key)
    if REBUILD_DISTINCT_VALUES:
        print("Re-indexing distinct values on the new table...")
        print(model.get_version(version_id).start_update_distinct_values().wait_for_result())
    print("Done. Verify the tickets agent's generated SQL now uses "
          "%s_troubletickets_year, then re-test in the webapp." % target_key)
