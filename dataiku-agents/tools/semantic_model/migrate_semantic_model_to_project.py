# =============================================================================
# OWIsMind - MIGRATE a semantic model to another project (Dataiku notebook).
#
# Copies a semantic model from a SOURCE project to a TARGET project, remapping
# every dataset reference and physical-table literal so the copy points at the
# TARGET project's data (entity datasetRef + golden-query SQL + instructions).
# Creates a NEW model in the target, copies the active version, activates it,
# and re-indexes the distinct values.
#
# Why the remap matters: the table the agent queries is decided by the model
# (entity datasetRef -> generated SQL; golden queries are few-shot examples the
# LLM copies). If a DEV->PROD copy keeps the DEV table name, the webapp Evidence
# panel cannot map the agent's FROM table to a PROD dataset and stays "degraded",
# and the SQL may hit the wrong/absent table.
#
# The remapping is DERIVED from the two project keys (not hand-typed), so it is
# impossible to drop part of the key. Physical tables are named
# {PROJECT_KEY}_<dataset> and dataset refs are {PROJECT_KEY}.<Dataset>, so both
# are covered by replacing the SOURCE key prefix with the TARGET key prefix.
#
# Run it in a notebook on EITHER project (it uses both project handles by key).
# To FIX an existing model in place (no copy), use remap_semantic_model.py.
# =============================================================================

import copy

import dataiku

# CONFIG ----------------------------------------------------------------------
SOURCE_PROJECT_KEY = "OWISMIND_DEV"
TARGET_PROJECT_KEY = "OWISMIND_PROD_V1"

SOURCE_MODEL_ID = "AHUh9hb"               # the source model to copy (active version)
TARGET_MODEL_NAME = "Drive_Revenues_Model"
TARGET_VERSION_ID = "v1"

REBUILD_DISTINCT_VALUES = True            # re-index value matching on the new table

# Optional explicit replacements applied IN ADDITION to the automatic project-key
# remapping, for anything the key prefix does not cover (e.g. a dataset renamed in
# the target). Leave empty when the dataset names are identical across projects.
EXTRA_REPLACEMENTS = {}                    # {"old string": "new string", ...}


# The two derived rules that cover both forms a project key appears in:
#   - dataset references : "<PROJECT_KEY>.<Dataset>"
#   - physical tables    : "<PROJECT_KEY>_<dataset>"
_KEY_REPLACEMENTS = {
    SOURCE_PROJECT_KEY + ".": TARGET_PROJECT_KEY + ".",
    SOURCE_PROJECT_KEY + "_": TARGET_PROJECT_KEY + "_",
}


def remap(value):
    """Recursively rewrite every string in the config: project-key prefixes first,
    then the optional explicit overrides. Pure."""
    if isinstance(value, dict):
        return {k: remap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [remap(v) for v in value]
    if isinstance(value, str):
        for old, new in _KEY_REPLACEMENTS.items():
            value = value.replace(old, new)
        for old, new in EXTRA_REPLACEMENTS.items():
            value = value.replace(old, new)
        return value
    return value


def warn_leftover_source_refs(config):
    """List any string still mentioning the SOURCE key after remapping (a missed
    reference the automatic rules did not cover). Best-effort, non-fatal."""
    leftovers = []

    def walk(v):
        if isinstance(v, dict):
            for c in v.values():
                walk(c)
        elif isinstance(v, list):
            for c in v:
                walk(c)
        elif isinstance(v, str) and SOURCE_PROJECT_KEY in v:
            leftovers.append(v[:120])

    walk(config)
    if leftovers:
        print("WARNING: %d string(s) still mention %s after remap (add them to "
              "EXTRA_REPLACEMENTS):" % (len(leftovers), SOURCE_PROJECT_KEY))
        for s in leftovers[:20]:
            print("  -", s)


def main():
    client = dataiku.api_client()
    source_project = client.get_project(SOURCE_PROJECT_KEY)
    target_project = client.get_project(TARGET_PROJECT_KEY)

    # Guard: refuse to create a duplicate. Fix an existing model in place instead.
    for h in target_project.list_semantic_models():
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        if name == TARGET_MODEL_NAME:
            raise RuntimeError(
                "A model named %r already exists in %s. Delete it first, or use "
                "remap_semantic_model.py to fix it in place (no duplicate)."
                % (TARGET_MODEL_NAME, TARGET_PROJECT_KEY))

    # Read the source active version (READ-ONLY copy; the source is never touched).
    source_model = source_project.get_semantic_model(SOURCE_MODEL_ID)
    source_version_id = source_model.get_active_version_id()
    if not source_version_id:
        raise RuntimeError("The source semantic model has no active version.")
    source_raw = copy.deepcopy(
        source_model.get_version(source_version_id).get_settings().get_raw())

    target_content = remap(source_raw)
    warn_leftover_source_refs(target_content)

    # Create the target model + version, copy the remapped settings, activate.
    target_model = target_project.create_semantic_model(TARGET_MODEL_NAME)
    print("Created target semantic model:", target_model.id)

    existing = target_model.list_versions_ids()
    if existing:
        target_version_id = existing[0]
        target_settings = target_model.get_version(target_version_id).get_settings()
    else:
        target_version_id = TARGET_VERSION_ID
        target_settings = target_model.new_version(target_version_id)

    target_raw = target_settings.get_raw()
    internal_id = target_raw.get("id")     # keep the version's generated id
    target_raw.clear()
    target_raw.update(target_content)
    if internal_id is not None:
        target_raw["id"] = internal_id
    target_settings.save()
    target_model.set_active_version_id(target_version_id)
    print("Copied source version %s -> active target version %s"
          % (source_version_id, target_version_id))

    if REBUILD_DISTINCT_VALUES:
        result = target_model.get_version(target_version_id) \
            .start_update_distinct_values().wait_for_result()
        print("Distinct-values indexing completed:", result)

    print("Migration completed. Target model id:", target_model.id)
    print("Next: point the target project's revenue_semantic_query tool at this model.")


if __name__ == "__main__":
    main()
