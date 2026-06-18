# =============================================================================
# OWIsMind - SEMANTIC MODEL SNAPSHOT (Dataiku notebook script, read-only)
# -----------------------------------------------------------------------------
# Exports the LIVE semantic model config to a JSON file so the SQL brain is
# versioned in the repo (entities, metric, named filters, golden queries,
# glossary, sqlGenerationConfig.instructions). Run it in a DSS notebook on the
# OWISMIND_DEV project after every change to the model, then commit the JSON.
#
# Why a dump script instead of a hand-written JSON: the model config is machine
# state. Exporting get_raw() keeps the snapshot byte-faithful to DSS and avoids
# transcription drift on the long instructions string. The human-readable view
# lives in MODEL.md.
#
# It is strictly READ-ONLY: it never calls save() / set_active / delete; it only
# reads the active version settings and writes a local file.
# =============================================================================

import json

import dataiku

# CONFIG ----------------------------------------------------------------------
# The semantic model the revenue_semantic_query tool (v4oqA6R) points at.
# Fill MODEL_ID with the model's technical id (DSS: the tool's "Semantic Model"
# setting), or leave it empty to resolve by name.
MODEL_ID = ""                                   # e.g. "AbCdEf01"
MODEL_NAME = "Drive_Revenues_Semantic_Model"    # used only when MODEL_ID is empty
OUTPUT_PATH = "Drive_Revenues_Semantic_Model.v1.json"


def resolve_model(project):
    """Return the DSSSemanticModel for MODEL_ID, else the one named MODEL_NAME.
    Read-only; raises a clear error if neither resolves."""
    if MODEL_ID:
        return project.get_semantic_model(MODEL_ID)
    for handle in project.list_semantic_models():
        name = handle.get("name") if isinstance(handle, dict) else getattr(handle, "name", None)
        mid = handle.get("id") if isinstance(handle, dict) else getattr(handle, "id", None)
        if name == MODEL_NAME and mid:
            return project.get_semantic_model(mid)
    raise RuntimeError(
        "Cannot resolve the semantic model: set MODEL_ID, or check MODEL_NAME=%r"
        % MODEL_NAME)


def active_version_raw(model):
    """The active version's raw settings dict (read-only get_raw())."""
    active_id = None
    try:
        active_id = model.get_active_version_id()
    except Exception:
        ids = model.list_versions_ids()
        active_id = ids[-1] if ids else None
    if not active_id:
        raise RuntimeError("No version found on the semantic model")
    settings = model.get_version(active_id).get_settings()
    return active_id, settings.get_raw()


def main():
    project = dataiku.api_client().get_default_project()
    model = resolve_model(project)
    version_id, raw = active_version_raw(model)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as fh:
        json.dump(raw, fh, ensure_ascii=False, indent=2, sort_keys=False)
    print("Wrote %s (version %s)" % (OUTPUT_PATH, version_id))


if __name__ == "__main__":
    main()
