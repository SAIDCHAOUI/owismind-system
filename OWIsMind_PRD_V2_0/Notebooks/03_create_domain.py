# =============================================================================
# 03_create_domain.py - THE FACTORY: source table -> full specialist chain.
# -----------------------------------------------------------------------------
# RUN THIS IN A DSS NOTEBOOK inside the target project, AFTER:
#   1. 00_probe_capabilities.py  (probe_results.json in the hub, gates unlocked)
#   2. 01_push_config_hub.py     (hub seeded: settings, capabilities, template)
#   3. optionally 04_semantic_wizard.py (wizard config in the hub)
#
# ALWAYS run once with DRY_RUN = True and READ THE PLAN before executing.
# The pipeline is idempotent: re-running skips what already exists. Steps whose
# API is not probe-confirmed degrade to MANUAL instructions in the report.
# The first knowledge build is NEVER triggered automatically: run the created
# scenario by hand, off-peak.
# =============================================================================

import dataiku

from owismind_factory import DomainSpec, FactoryContext, hub, pipeline

# ----------------------------------------------------------------- CONFIG ----
DRY_RUN = True

SPEC = {
    "domain": "satisfaction",                  # snake_case business domain
    "base_dataset": "CX_Surveys",              # existing dataset, or imported below
    # To import an external SQL table as base_dataset, uncomment:
    # "source": {"connection": "SQL_owi", "schema": "public", "table": "cx_surveys"},
    "label_fr": "Expert satisfaction (CX)",
    "label_en": "Satisfaction expert (CX)",
    # Optional: allowlist of text columns for the fast attribute_lookup.
    "lookup_search_columns": [],
}

# Wizard config produced by 04_semantic_wizard.py (hub path), or None.
WIZARD_CONFIG_PATH = None      # e.g. "/python/owismind_hub/wizard/satisfaction-config.json"

# Steps subset (None = all). See pipeline.STEP_NAMES.
STEPS = None
# ------------------------------------------------------------------------------

project = dataiku.api_client().get_default_project()
spec = DomainSpec.from_dict(SPEC)

probe = hub.read_json(project, hub.HUB_ROOT + "/probe_results.json") or {}
schema_hints = probe.get("suggested_schema_hints")
discovery = probe.get("suggested_discovery")
if schema_hints and not schema_hints.get("confirmed"):
    print("NOTE: schema_hints are UNCONFIRMED (write probe not run): the code agent "
          "step will still try them ONLY if you set them confirmed by hand; otherwise "
          "it falls back to the one-paste manual path.")
    schema_hints = None
if discovery and not discovery.get("confirmed"):
    print("NOTE: tool discovery UNCONFIRMED (write probe not run): keeping it anyway "
          "for the clone attempt is allowed because the created tool is REVIEWED in "
          "DSS before any use; set discovery = None below to force the manual path.")

wizard_config = hub.read_json(project, WIZARD_CONFIG_PATH) if WIZARD_CONFIG_PATH else None

ctx = FactoryContext(project=project, dry_run=DRY_RUN, abort_on_failure=False)
pipeline.create_domain(ctx, spec,
                       wizard_config=wizard_config,
                       discovery=discovery,
                       schema_hints=schema_hints,
                       steps=STEPS)

print(ctx.report_markdown(title="Factory report : domain %s (%s)"
                          % (spec.domain, "DRY RUN" if DRY_RUN else "EXECUTED")))
