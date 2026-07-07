# =============================================================================
# add_solution_and_repoint_prod_clone.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK inside the PROD CLONE project (duplicated from
# OWISMIND_DEV; its datasets resolve to physical tables named OWISMIND_PRD_V1_2_*).
#
# It does TWO independent things to the REVENUE semantic model, in one pass:
#
#   (1) RE-ADD the 'Solution' offer level that was removed on 2026-06-22 (commit
#       e6ba899, by drop_column_and_reindex.py). Users need it back. This is the
#       exact INVERSE of that removal: it restores, verbatim from the pre-removal
#       version, the offer hierarchy Product > Solution > SolutionLine >
#       sirano_product across every place the removal stripped it -
#         - the SQL-generation INSTRUCTIONS ("Commercial offer hierarchy" section),
#         - the commercial_offer ENTITY description,
#         - the 'Solution' ATTRIBUTE (indexed COLUMN) + its two metrics,
#         - the Product attribute description + the "Commercial hierarchy" glossary,
#         - the ambiguous-offer-term golden-query wording,
#       and adds a standalone 'Solution' glossary term.
#
#   (2) REPOINT the model at THIS project's data. Duplicating a DSS project does
#       NOT rewrite the semantic model's dataset references: the copy still points
#       at "OWISMIND_DEV.DRIVE_Revenues" (entity datasetRef) and at the DEV table
#       "OWISMIND_DEV_drive_revenues" (golden-query SQL). The UI gives no way to
#       fix that. A pure project-key remap rewrites every such string to this
#       project's key (e.g. OWISMIND_PRD_V1_2), so the agent queries
#       OWISMIND_PRD_V1_2_drive_revenues and the webapp Evidence panel resolves the
#       FROM table to a dataset in THIS project.
#
# The hierarchy rule (which column wins for an offer term) lives ONLY in the model
# instructions, per project design - it is NOT hardcoded in any agent. Restoring
# it here is what makes the SQL writer prefer Product, then Solution, then
# SolutionLine, then sirano_product again.
#
# Re-indexing distinct values on apply requires this project's DRIVE_Revenues
# dataset SCHEMA to actually contain the 'Solution' column again (a script guard
# below prints whether it does). If the schema was not refreshed after re-adding
# the column, refresh it in DSS first, else the re-index of the Solution attribute
# fails.
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
                                            # reassignment); clone likely kept DEV id AHUh9hb
MODEL_NAME = "Drive_Revenues_Semantic_Model"
ADD_COLUMN = "Solution"                      # the offer level to restore
REVENUE_DATASET = "DRIVE_Revenues"           # to check the schema + name the table
DRY_RUN    = True                            # True = preview only; flip to False to apply
REBUILD_DISTINCT_VALUES = True               # re-index value matching (needs the column)


# ----------------------------------------------------------------------------
# CANONICAL PRE-REMOVAL TEXT (verbatim from the version where 'Solution' existed;
# project rule: no em/en dash - only '-', ':', '(', ')' and the '>' hierarchy /
# '->' arrows already present in that version).
# ----------------------------------------------------------------------------
RESTORED_HIERARCHY_SECTION = """\
## Commercial offer hierarchy - ALWAYS prefer the most granular level (CRITICAL)

The offer is a hierarchy, broadest to most granular:
    SolutionLine  >  Solution  >  Product      (sirano_product is a secondary technical code).

When a user term (e.g. "IPL", "IP Transit", "Roaming Sponsor", "IP") could match a value in
several of these columns, resolve it to the MOST GRANULAR level that contains it, in this
STRICT order of preference:
    1. Product           (default - most users speak at the product level)
    2. Solution
    3. SolutionLine
    4. sirano_product    (last resort only)

So: filter on Product if the term is a Product value; else Solution; else SolutionLine; else
sirano_product. Example: "IP" is a SolutionLine -> filter on SolutionLine. "IPL" and
"Roaming Sponsor" are Products -> filter on Product.

sirano_product is a SECONDARY TECHNICAL CODE: NEVER default an offer term to it. Use
sirano_product ONLY if the user explicitly gives a sirano code. In particular, BUDGET rows
may not carry a sirano_product, so resolving an offer term to sirano_product can wrongly drop
the budget (returning budget = 0) - always prefer Product.

When a request flags a term as an "AMBIGUOUS OFFER TERM" (a value present in several offer
columns), YOU resolve it - pick the level from this hierarchy and the user's intent; do not
assume the helper's column.

TRANSPARENCY (mandatory): when the value you picked ALSO exists at another level (e.g.
"IP Transit" is both a Product AND a Solution), filter on the most granular level (Product)
AND say so explicitly, e.g.: "Revenue for the IP Transit product was X. Note: IP Transit
also exists as a Solution - tell me if you meant the Solution level." Never silently choose a
level when the term is ambiguous across levels.
"""

COMMERCIAL_OFFER_DESCRIPTION = (
    "Commercial offer hierarchy, broadest to most granular: SolutionLine > Solution > "
    "Product (sirano_product is a secondary technical code). When a user term (e.g. 'IPL', "
    "'IP Transit', 'Roaming Sponsor', 'IP') could match several levels, resolve it to the "
    "MOST GRANULAR level that contains it, in strict order: Product first, then Solution, "
    "then SolutionLine, then sirano_product. When the value also exists at another level "
    "(e.g. 'IP Transit' is both a Product and a Solution), filter the most granular level "
    "(Product) and say so explicitly so the user can ask for the other level.")

# 'Solution' attribute (indexed COLUMN), mirroring the SolutionLine attribute shape.
# No pre-removal JSON of this attribute was ever committed, so the description is
# reconstructed faithfully from the hierarchy semantics (mid-level offer family).
SOLUTION_ATTRIBUTE = {
    "name": "Solution",
    "description": ("Mid-level commercial offer family: a group of Products forming a "
                    "solution, broader than Product and narrower than SolutionLine. Second "
                    "level in the offer resolution order (Product first, then Solution)."),
    "dssType": "string",
    "type": "COLUMN",
    "column": "Solution",
    "distinctValuesHandlingMode": "AUTO_INDEX",
    "manualValues": [],
    "indexDistinctValues": True,
    "resolveInUserRequests": True,
    "sqlGenerationConfig": {"autoValuesLimit": 50},
}

# The removal stripped two Solution metrics ("Distinct Solutions, Average Products per
# Solution"). Only "Distinct Solutions" is restored: it mirrors the live "Distinct
# Solution Lines" metric exactly, so it is certainly valid. The average metric's original
# expression was never committed; a guessed ratio could be an invalid metric, and it is
# not needed for the column or the priority rule, so it is intentionally left out.
SOLUTION_METRICS = [
    {"name": "Distinct Solutions",
     "description": "Number of unique solutions across all commercial offers",
     "pseudoSQLExpression": "COUNT(DISTINCT Solution)"},
]

SOLUTION_GLOSSARY_TERM = {
    "term": "Solution",
    "description": ("Mid-level commercial offer family grouping several Products; broader "
                    "than Product, narrower than SolutionLine. Offer resolution order: "
                    "Product first, then Solution, then SolutionLine, then sirano_product."),
    "synonyms": [],
}

# Targeted string restorations elsewhere (exact inverse of the removal's text fixes).
TEXT_RESTORES = {
    # revenue_record.Product attribute description + "Commercial hierarchy" glossary term
    "hierarchy (SolutionLine > Product)": "hierarchy (SolutionLine > Solution > Product)",
    "interpreted as SolutionLine > Product.": "interpreted as SolutionLine > Solution > Product.",
    # the ambiguous-offer-term golden query question
    "(IP Transit may exist at more than one offer level; prefer the Product level)":
        "(IP Transit is both a Product and a Solution; prefer the Product level)",
}


# ----------------------------------------------------------------------------
# RESOLVE THE RUNNING PROJECT (the clone) AND THE TARGET KEY
# ----------------------------------------------------------------------------
client  = dataiku.api_client()
project = client.get_default_project()       # the project this notebook runs in
target_key = TARGET_PROJECT_KEY or project.project_key

assert target_key != SOURCE_PROJECT_KEY, (
    "Target key == source key (%s). This notebook must run in the PROD CLONE project, "
    "not in %s. Refusing to touch the DEV model." % (target_key, SOURCE_PROJECT_KEY))

# Project-key remap: the two forms the key appears in inside the config.
#   dataset refs : "<KEY>.<Dataset>"   (entity datasetRef)
#   phys tables  : "<KEY>_<dataset>"   (golden-query SQL literal, e.g. _drive_revenues)
KEY_REPLACEMENTS = {
    SOURCE_PROJECT_KEY + ".": target_key + ".",
    SOURCE_PROJECT_KEY + "_": target_key + "_",
}


# ----------------------------------------------------------------------------
# HELPERS
# ----------------------------------------------------------------------------
def resolve_model():
    if MODEL_ID:
        return project.get_semantic_model(MODEL_ID)
    for h in project.list_semantic_models():
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        mid  = h.get("id")   if isinstance(h, dict) else getattr(h, "id", None)
        if name == MODEL_NAME and mid:
            return project.get_semantic_model(mid)
    raise RuntimeError("Model not found: set MODEL_ID or check MODEL_NAME=%r" % MODEL_NAME)


def replace_hierarchy_section(instructions):
    """Swap the '## Commercial offer hierarchy' section for the restored one, leaving
    every other section byte-identical. Returns (new_instructions, replaced_bool)."""
    if not instructions:
        return instructions, False
    lines, out, i, n, done = instructions.split("\n"), [], 0, len(instructions.split("\n")), False
    while i < n:
        if (not done and lines[i].startswith("## ")
                and "Commercial offer hierarchy" in lines[i]):
            out.extend(RESTORED_HIERARCHY_SECTION.rstrip("\n").split("\n"))
            out.append("")
            i += 1
            while i < n and not lines[i].startswith("## "):
                i += 1
            done = True
            continue
        out.append(lines[i])
        i += 1
    return "\n".join(out), done


def offer_entity(raw):
    """The entity holding the offer columns (has a Product/SolutionLine COLUMN attr)."""
    for ent in raw.get("entities", []) or []:
        cols = {(a.get("column") or a.get("name")) for a in ent.get("attributes", []) or []}
        if "SolutionLine" in cols or ent.get("name") == "commercial_offer":
            return ent
    return None


def has_attr(ent, col):
    return any((a.get("column") == col or a.get("name") == col)
               for a in ent.get("attributes", []) or [])


def has_metric(ent, name):
    return any(m.get("name") == name for m in ent.get("metrics", []) or [])


def apply_text_restores(value, counter):
    if isinstance(value, dict):
        return {k: apply_text_restores(v, counter) for k, v in value.items()}
    if isinstance(value, list):
        return [apply_text_restores(v, counter) for v in value]
    if isinstance(value, str):
        for old, new in TEXT_RESTORES.items():
            if old in value:
                counter[0] += value.count(old)
                value = value.replace(old, new)
        return value
    return value


def key_remap(value):
    """Rewrite source-key prefixes -> target-key prefixes in every string. Pure."""
    if isinstance(value, dict):
        return {k: key_remap(v) for k, v in value.items()}
    if isinstance(value, list):
        return [key_remap(v) for v in value]
    if isinstance(value, str):
        for old, new in KEY_REPLACEMENTS.items():
            value = value.replace(old, new)
        return value
    return value


def source_refs(config):
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


def schema_has_solution():
    """Non-fatal: does THIS project's revenue dataset schema list the Solution column?"""
    try:
        cols = dataiku.Dataset(REVENUE_DATASET).read_schema()
        return ADD_COLUMN in {c.get("name") for c in cols}
    except Exception as exc:
        print("  (could not read %s schema: %s)" % (REVENUE_DATASET, exc))
        return None


# ----------------------------------------------------------------------------
# BUILD THE UPDATED CONFIG
# ----------------------------------------------------------------------------
model = resolve_model()
version_id = model.get_active_version_id()
assert version_id, "The revenue semantic model has no active version."
settings = model.get_version(version_id).get_settings()
raw = settings.get_raw()

report = {"hierarchy_replaced": False, "attribute_added": False,
          "metrics_added": [], "glossary_added": False, "entity_desc_set": False,
          "text_restores": 0}

# 1. instructions - restore the hierarchy section
cfg = raw.setdefault("sqlGenerationConfig", {})
cfg["instructions"], report["hierarchy_replaced"] = replace_hierarchy_section(
    cfg.get("instructions") or "")

# 2. commercial_offer entity - description + Solution attribute + metrics
ent = offer_entity(raw)
assert ent is not None, "Could not find the commercial_offer entity (no SolutionLine attr)."
ent["description"] = COMMERCIAL_OFFER_DESCRIPTION
report["entity_desc_set"] = True

if not has_attr(ent, ADD_COLUMN):
    attrs = ent.setdefault("attributes", [])
    insert_at = next((i + 1 for i, a in enumerate(attrs)
                      if (a.get("column") or a.get("name")) == "Product"), len(attrs))
    attrs.insert(insert_at, dict(SOLUTION_ATTRIBUTE))
    report["attribute_added"] = True

for m in SOLUTION_METRICS:
    if not has_metric(ent, m["name"]):
        ent.setdefault("metrics", []).append(dict(m, created={}))
        report["metrics_added"].append(m["name"])

# 3. glossary - add the standalone Solution term (if missing)
gloss = raw.setdefault("glossaryTerms", [])
if not any((t.get("term") or "").strip().lower() == ADD_COLUMN.lower() for t in gloss):
    gloss.append(dict(SOLUTION_GLOSSARY_TERM))
    report["glossary_added"] = True

# 4. targeted text restores (Product attr desc, "Commercial hierarchy" glossary, golden Q)
counter = [0]
fixed = apply_text_restores(raw, counter)
raw.clear()
raw.update(fixed)
report["text_restores"] = counter[0]

# 5. REPOINT - remap the DEV project key to this project's key everywhere
before_refs = source_refs(raw)
remapped = key_remap(raw)
raw.clear()
raw.update(remapped)
after_refs = source_refs(raw)


# ----------------------------------------------------------------------------
# PREVIEW + APPLY
# ----------------------------------------------------------------------------
sol_in_schema = schema_has_solution()

print("Project (clone)          :", project.project_key)
print("Model                    :", model.id, "| active version", version_id)
print("--- (1) restore 'Solution' ---")
print("Hierarchy section restored:", report["hierarchy_replaced"])
print("commercial_offer desc set :", report["entity_desc_set"])
print("Solution attribute added  :", report["attribute_added"],
      "" if report["attribute_added"] else "(already present)")
print("Metrics added             :", report["metrics_added"] or "(already present)")
print("Solution glossary term    :", "added" if report["glossary_added"] else "(already present)")
print("Text restores applied     :", report["text_restores"])
print("Solution in %s schema     : %s" % (REVENUE_DATASET, sol_in_schema),
      "" if sol_in_schema else "<-- refresh the dataset schema before re-indexing!")
print("--- (2) repoint to this project ---")
print("Remap                     : %s.* -> %s.*  and  %s_* -> %s_*"
      % (SOURCE_PROJECT_KEY, target_key, SOURCE_PROJECT_KEY, target_key))
print("Refs to %s before / after : %d / %d %s"
      % (SOURCE_PROJECT_KEY, len(before_refs), len(after_refs),
         "(after should be 0)" if not after_refs else "<-- CHECK"))
for s in after_refs[:20]:
    print("   !!", s)

if DRY_RUN:
    print("\nDRY_RUN=True -> nothing saved. Review above (AFTER refs = 0, Solution in "
          "schema = True), then set DRY_RUN=False and re-run.")
else:
    settings.save()
    print("\nSaved. Restored 'Solution' and repointed to the %s datasets/tables." % target_key)
    if REBUILD_DISTINCT_VALUES:
        print("Re-indexing distinct values (needs the Solution column on the new table)...")
        print(model.get_version(version_id).start_update_distinct_values().wait_for_result())
    print("Done. In the model Playground, test an offer term that lives at the Solution "
          "level, then confirm the agent's SQL uses %s_drive_revenues and re-test in the "
          "webapp." % target_key)
