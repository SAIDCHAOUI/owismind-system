# =============================================================================
# drop_column_and_reindex.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK to reconcile a semantic model with a source
# dataset that CHANGED, in two independent ways:
#
#   (A) ROWS were added/removed  -> just re-index the distinct values so new
#       cell values become searchable by the semantic layer (figures are
#       already live, computed by SQL at query time).
#   (B) a COLUMN was REMOVED     -> surgically strip every reference to it
#       (attribute, metrics, instructions, descriptions, glossary, golden
#       queries) BEFORE re-indexing, otherwise the model keeps generating SQL
#       that filters/aggregates a column that no longer exists.
#
# A plain string remap (find/replace of dataset/table names, e.g.
# remap_semantic_model.py) is NOT enough for (B): removing a column needs
# STRUCTURAL edits, not just substitutions.
#
# This instance is parameterised for the OWIsMind revenue model with the
# 'Solution' offer level removed (hierarchy becomes SolutionLine > Product,
# sirano_product as a secondary technical code). To drop a different column,
# set DROP_COLUMN and adapt NEW_HIERARCHY_SECTION / TEXT_FIXES.
#
# Documented API only:
#   project.get_semantic_model(id) -> get_active_version_id() -> get_version()
#   -> get_settings() -> get_raw()/save();  get_version(id)
#   -> start_update_distinct_values().wait_for_result()
# =============================================================================

import dataiku
import json
import re

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
PROJECT_KEY = "OWISMIND_DEV"   # the project that owns the live model
MODEL_ID    = ""                   # set if known; else auto-detect below
MODEL_NAME  = ""                   # or match by name; else auto-detect
DROP_COLUMN = "Solution"           # the dataset column that no longer exists
DRY_RUN     = True                 # True = preview only; flip to False to apply

# Replacement for the whole "Commercial offer hierarchy" section of the SQL
# instructions (Solution removed). Uses "-" / ":" (project rule: no em dash).
NEW_HIERARCHY_SECTION = """\
## Commercial offer hierarchy - ALWAYS prefer the most granular level (CRITICAL)

The offer is a hierarchy, broadest to most granular:
    SolutionLine  >  Product      (sirano_product is a secondary technical code).

The 'Solution' level was REMOVED from the dataset: there are now only SolutionLine,
Product and sirano_product. NEVER reference a 'Solution' column.

When a user term (e.g. "IPL", "IP Transit", "Roaming Sponsor", "IP") could match a value in
several of these columns, resolve it to the MOST GRANULAR level that contains it, in this
STRICT order of preference:
    1. Product           (default: most users speak at the product level)
    2. SolutionLine
    3. sirano_product    (last resort only)

So: filter on Product if the term is a Product value; else SolutionLine; else sirano_product.
Example: "IP" is a SolutionLine -> filter on SolutionLine. "IPL" and "Roaming Sponsor" are
Products -> filter on Product.

sirano_product is a SECONDARY TECHNICAL CODE: NEVER default an offer term to it. Use
sirano_product ONLY if the user explicitly gives a sirano code. In particular, BUDGET rows
may not carry a sirano_product, so resolving an offer term to sirano_product can wrongly drop
the budget (returning budget = 0): always prefer Product.

When a request flags a term as an "AMBIGUOUS OFFER TERM" (a value present in several offer
columns), YOU resolve it: pick the level from this hierarchy and the user's intent.

TRANSPARENCY (mandatory): when the value you picked ALSO exists at another level (e.g. a value
present both as a Product and as a SolutionLine), filter on the most granular level (Product)
AND say so explicitly. Never silently choose a level when the term is ambiguous across levels.
"""

# Free-text fixes for descriptions / glossary / golden-query questions that name
# the removed level outside the instructions block.
TEXT_FIXES = {
    "SolutionLine > Solution > Product": "SolutionLine > Product",
    "Product first, then Solution, then SolutionLine, then sirano_product":
        "Product first, then SolutionLine, then sirano_product",
    "(e.g. 'IP Transit' is both a Product and a Solution)":
        "(when a value exists at more than one offer level)",
    "(IP Transit is both a Product and a Solution; prefer the Product level)":
        "(IP Transit may exist at more than one offer level; prefer the Product level)",
}


# ----------------------------------------------------------------------------
# LOCATE THE MODEL
# ----------------------------------------------------------------------------
client  = dataiku.api_client()
project = client.get_project(PROJECT_KEY)


def _handles():
    out = []
    for h in project.list_semantic_models():
        mid  = h.get("id")   if isinstance(h, dict) else getattr(h, "id", None)
        name = h.get("name") if isinstance(h, dict) else getattr(h, "name", None)
        if mid:
            out.append((mid, name))
    return out


def _open(mid):
    sm  = project.get_semantic_model(mid)
    vid = sm.get_active_version_id()
    st  = sm.get_version(vid).get_settings()
    return sm, vid, st, st.get_raw()


if MODEL_ID:
    sm, vid, settings, raw = _open(MODEL_ID)
    model_name = MODEL_ID
elif MODEL_NAME:
    match = [m for m, n in _handles() if n == MODEL_NAME]
    assert match, "No semantic model named %r in %s" % (MODEL_NAME, PROJECT_KEY)
    sm, vid, settings, raw = _open(match[0])
    model_name = MODEL_NAME
else:
    # auto-detect: the DRIVE_Revenues model that still carries the dropped column
    picked = None
    for mid, name in _handles():
        s2, v2, st2, r2 = _open(mid)
        blob = json.dumps(r2)
        if "DRIVE_Revenues" in blob and ('"column": "%s"' % DROP_COLUMN) in blob:
            picked = (mid, name, s2, v2, st2, r2)
            break
    assert picked, ("Could not auto-detect the model (no DRIVE_Revenues model "
                    "with a %r column). Set MODEL_ID or MODEL_NAME." % DROP_COLUMN)
    mid, name, sm, vid, settings, raw = picked
    model_name = "%s (%s)" % (name, mid)
    print("Auto-detected model:", model_name)


# ----------------------------------------------------------------------------
# (B) STRUCTURAL: strip the removed column
# ----------------------------------------------------------------------------
report = {"attributes": [], "metrics": [], "glossary": [], "text_fixes": 0,
          "hierarchy_replaced": False}
word = re.compile(r"\b%s\b" % re.escape(DROP_COLUMN))

# 1. drop the attribute + any metric that references the column
for ent in raw.get("entities", []) or []:
    kept_attrs = []
    for a in ent.get("attributes", []) or []:
        if a.get("column") == DROP_COLUMN or a.get("name") == DROP_COLUMN:
            report["attributes"].append("%s.%s" % (ent.get("name"), a.get("name")))
        else:
            kept_attrs.append(a)
    ent["attributes"] = kept_attrs

    kept_metrics = []
    for m in ent.get("metrics", []) or []:
        if word.search(m.get("pseudoSQLExpression") or ""):
            report["metrics"].append("%s :: %s" % (ent.get("name"), m.get("name")))
        else:
            kept_metrics.append(m)
    ent["metrics"] = kept_metrics

# 2. drop the standalone glossary term named exactly like the column
kept_gloss = []
for t in raw.get("glossaryTerms", []) or []:
    if (t.get("term") or "").strip().lower() == DROP_COLUMN.lower():
        report["glossary"].append(t.get("term"))
    else:
        kept_gloss.append(t)
raw["glossaryTerms"] = kept_gloss

# 3. rewrite the hierarchy section of the SQL instructions
cfg   = raw.setdefault("sqlGenerationConfig", {})
instr = cfg.get("instructions") or ""
if instr:
    lines, res, i, n, done = instr.split("\n"), [], 0, None, False
    n = len(lines)
    while i < n:
        if (not done and lines[i].startswith("## ")
                and "Commercial offer hierarchy" in lines[i]):
            res.extend(NEW_HIERARCHY_SECTION.rstrip("\n").split("\n"))
            res.append("")                      # blank line before next section
            i += 1
            while i < n and not lines[i].startswith("## "):
                i += 1                          # skip the old section body
            done = True
            continue
        res.append(lines[i])
        i += 1
    cfg["instructions"] = "\n".join(res)
    report["hierarchy_replaced"] = done

# 4. free-text fixes everywhere else (descriptions, glossary, golden questions)
def _fix(v):
    if isinstance(v, dict):
        return {k: _fix(x) for k, x in v.items()}
    if isinstance(v, list):
        return [_fix(x) for x in v]
    if isinstance(v, str):
        for old, new in TEXT_FIXES.items():
            if old in v:
                report["text_fixes"] += v.count(old)
                v = v.replace(old, new)
    return v

fixed = _fix(raw)
raw.clear()
raw.update(fixed)

# residual safety check: nothing structural should still name the column
residual = []
for ent in raw.get("entities", []) or []:
    for a in ent.get("attributes", []) or []:
        if a.get("column") == DROP_COLUMN:
            residual.append("attribute %s" % a.get("name"))
    for m in ent.get("metrics", []) or []:
        if word.search(m.get("pseudoSQLExpression") or ""):
            residual.append("metric %s" % m.get("name"))


# ----------------------------------------------------------------------------
# PREVIEW + APPLY
# ----------------------------------------------------------------------------
print("Model           :", model_name, "| active version", vid)
print("Removed attrs   :", report["attributes"] or "(none)")
print("Removed metrics :", report["metrics"] or "(none)")
print("Removed glossary:", report["glossary"] or "(none)")
print("Hierarchy section rewritten:", report["hierarchy_replaced"])
print("Free-text fixes applied     :", report["text_fixes"])
print("Residual references to %r   : %s" % (DROP_COLUMN, residual or "none"))

if DRY_RUN:
    print("\nDRY_RUN=True -> nothing saved. Review above, then set DRY_RUN=False.")
else:
    assert not residual, "Residual column references remain: %s" % residual
    settings.save()
    print("\nSaved. Re-indexing distinct values (covers added rows + dropped column)...")
    print(sm.get_version(vid).start_update_distinct_values().wait_for_result())
    print("Done. Re-test in the model Playground, then in the webapp.")
