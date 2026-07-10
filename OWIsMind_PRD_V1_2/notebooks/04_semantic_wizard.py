# =============================================================================
# 04_semantic_wizard.py - LLM-assisted semantic model authoring (the wizard).
# -----------------------------------------------------------------------------
# RUN THIS IN A DSS NOTEBOOK inside the target project, AFTER the domain's
# profile dataset has been built (factory step first_build + review).
#
# Round 1: leave ANSWERS = {} -> the wizard drafts the config AND asks its
#   clarifying questions (in French). Read them, fill ANSWERS, re-run.
# Round 2+: the answers are folded in; iterate until the questions are settled.
# The final config JSON is saved to the hub for 03_create_domain.py
# (WIZARD_CONFIG_PATH) or semantic_builder.apply_config.
#
# COST: exactly ONE LLM completion per run (aggregated profile metadata only,
# never raw rows). The output is a DRAFT: the official docs themselves say
# auto-generation gets you about 80 percent of the way; review every section.
# =============================================================================

import json

import dataiku

from owismind_factory import hub, wizard

# ----------------------------------------------------------------- CONFIG ----
DOMAIN = "satisfaction"
BASE_DATASET = "CX_Surveys"
PROFILE_DATASET = BASE_DATASET + "_profile"

ANSWERS = {
    # "default_metric": "survey_count",
    # "distinct_key": "survey_id",
    # "time_column": "response_date",
}
EXTRA_CONTEXT = ""              # free text: business context the profile lacks
SAVE_TO_HUB = True
# ------------------------------------------------------------------------------

project = dataiku.api_client().get_default_project()

config = wizard.draft_model_config(project, PROFILE_DATASET,
                                   answers=ANSWERS or None,
                                   base_dataset=BASE_DATASET,
                                   domain=DOMAIN,
                                   extra_context=EXTRA_CONTEXT or None)

if config.get("error"):
    print("WIZARD ERROR: %s" % config["error"])
else:
    questions = config.get("questions") or []
    print("=== QUESTIONS DE CLARIFICATION (%d) ===" % len(questions))
    for q in questions:
        print("- [%s] %s" % (q.get("id"), q.get("question_fr")))
        print("    pourquoi: %s" % q.get("why"))
        if q.get("options"):
            print("    options: %s" % ", ".join(q["options"]))
        if q.get("default"):
            print("    defaut propose: %s" % q["default"])

    print("\n=== DRAFT CONFIG ===")
    print(json.dumps(config, indent=1, ensure_ascii=False)[:8000])

    if SAVE_TO_HUB:
        path = "%s/wizard/%s-config.json" % (hub.HUB_ROOT, DOMAIN)
        hub.write_json(project, path, config)
        print("\n[saved to project library %s : use it as WIZARD_CONFIG_PATH in "
              "03_create_domain.py]" % path)
