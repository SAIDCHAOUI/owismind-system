# =============================================================================
# OWIsMind - REMAP a semantic model IN PLACE (Dataiku notebook).
#
# Rewrites dataset references and physical-table literals on an EXISTING model's
# active version (no copy, no new model), then re-indexes. Use it to repoint a
# model at a different table, or to FIX a botched migration where the table name
# is wrong (which makes the webapp Evidence panel "degraded": the agent's FROM
# table maps to no dataset in the project).
#
# Example (the case it was written for): a DEV->PROD migration that produced
# "OWISMIND.DRIVE_Revenues" / "OWISMIND_drive_revenues" instead of the real PROD
# table "OWISMIND_PROD_V1_drive_revenues". REPLACEMENTS below corrects both.
#
# Each REPLACEMENTS key should be DISTINCTIVE and not a substring of its own
# replacement, so the rewrite is safe and idempotent (re-running changes nothing).
# To COPY a model across projects (new model in the target), use
# migrate_semantic_model_to_project.py.
# =============================================================================

import dataiku

# CONFIG ----------------------------------------------------------------------
PROJECT_KEY = "OWISMIND_PROD_V1"
MODEL_ID = ""                              # set the model id, or resolve by name
MODEL_NAME = "Drive_Revenues_Model"        # used only when MODEL_ID is empty

REBUILD_DISTINCT_VALUES = True             # re-index value matching on the new table

# Wrong string -> correct string. Applied to every string in the config.
REPLACEMENTS = {
    "OWISMIND.DRIVE_Revenues": "OWISMIND_PROD_V1.DRIVE_Revenues",   # entity datasetRef
    "OWISMIND_drive_revenues": "OWISMIND_PROD_V1_drive_revenues",   # golden-query / instruction table
}


def remap(value):
    """Recursively apply REPLACEMENTS to every string in the config. Pure."""
    if isinstance(value, dict):
        return {k: remap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v) for v in value]
    if isinstance(value, str):
        for old, new in REPLACEMENTS.items():
            value = value.replace(old, new)
        return value
    return value


def resolve_model(project):
    """The model for MODEL_ID, else the one named MODEL_NAME. Raises if neither."""
    if MODEL_ID:
        return project.get_semantic_model(MODEL_ID)
    for h in project.list_semantic_models():
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        mid = h.get("id") if isinstance(h, dict) else getattr(h, "id", None)
        if name == MODEL_NAME and mid:
            return project.get_semantic_model(mid)
    raise RuntimeError("Model not found: set MODEL_ID or check MODEL_NAME=%r" % MODEL_NAME)


def main():
    project = dataiku.api_client().get_project(PROJECT_KEY)
    model = resolve_model(project)

    version_id = model.get_active_version_id()
    if not version_id:
        raise RuntimeError("The semantic model has no active version.")
    settings = model.get_version(version_id).get_settings()

    raw = settings.get_raw()
    fixed = remap(raw)
    raw.clear()
    raw.update(fixed)
    settings.save()
    print("Remapped model %s version %s" % (model.id, version_id))

    if REBUILD_DISTINCT_VALUES:
        result = model.get_version(version_id) \
            .start_update_distinct_values().wait_for_result()
        print("Distinct-values indexing completed:", result)

    print("Done. Verify the agent's generated SQL now uses the corrected table.")


if __name__ == "__main__":
    main()
