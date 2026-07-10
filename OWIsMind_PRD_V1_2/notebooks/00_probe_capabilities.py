# =============================================================================
# 00_probe_capabilities.py - PHASE 0: capability probe of THIS Dataiku instance.
# -----------------------------------------------------------------------------
# RUN THIS IN A DSS NOTEBOOK inside the target project (the v1.3-dev clone).
# Requires: the project library contains owismind_factory (paste project-library/
# python/owismind_factory from the repo into the library python/ folder first).
#
# What it does:
# - READ-ONLY probes (always safe): which factory API methods this server
#   exposes, the key layout of the live orchestrator Code Agent raw settings
#   (locates the source-code and code-env keys), the live Semantic Model Query
#   tool's type string + params template, library/wiki/semantic-models checks.
# - WRITE probes (OFF by default, flip RUN_WRITE_PROBES): create ONE throwaway
#   agent + ONE throwaway tool, verify the settings round-trip, DELETE them.
#   This is the only deletion anywhere in the factory and it only targets the
#   two probe objects it just created.
#
# OUTPUT: a markdown report. Paste it back to Claude (or commit it as
# OWIsMind_PRD_V1_2/factory-docs/CAPABILITY_MATRIX.md) so the gated factory
# steps (code agent creation, tool creation) can be unlocked.
# =============================================================================

import json

import dataiku

from owismind_factory import hub, probes

# ----------------------------------------------------------------- CONFIG ----
RUN_WRITE_PROBES = False        # True = create+verify+DELETE zz_factory_probe objects
WRITE_REPORT_TO_HUB = True      # store the report at /owismind_hub/probe_report.md
# ------------------------------------------------------------------------------

project = dataiku.api_client().get_default_project()
print("Probing project %s (read-only: %s)" % (project.project_key, not RUN_WRITE_PROBES))

results = probes.run_read_probes(project)
results = probes.run_write_probes(project, results, allow=RUN_WRITE_PROBES)

report = probes.format_probe_report(results)
print(report)

if WRITE_REPORT_TO_HUB:
    hub.write_text(project, hub.HUB_ROOT + "/probe_report.md", report)
    print("\n[saved to project library %s/probe_report.md]" % hub.HUB_ROOT)

# The two payloads the factory gates need (paste into 03_create_domain.py CONFIG
# or let the console read them from the hub):
print("\nSCHEMA_HINTS = %s" % json.dumps(results.get("suggested_schema_hints"), indent=1))
discovery = results.get("suggested_discovery") or {}
print("\nDISCOVERY type = %r, confirmed = %s (params template in the report above)"
      % (discovery.get("type"), discovery.get("confirmed", False)))

if WRITE_REPORT_TO_HUB:
    hub.write_json(project, hub.HUB_ROOT + "/probe_results.json", {
        "suggested_schema_hints": results.get("suggested_schema_hints"),
        "suggested_discovery": results.get("suggested_discovery"),
    })
    print("[saved machine-readable results to %s/probe_results.json]" % hub.HUB_ROOT)
