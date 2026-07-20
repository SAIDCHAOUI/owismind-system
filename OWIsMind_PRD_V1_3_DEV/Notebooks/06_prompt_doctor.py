# =============================================================================
# 06_prompt_doctor.py
# -----------------------------------------------------------------------------
# Run this IN A DATAIKU NOTEBOOK inside the OWIsMind project. It reads recent
# agent interactions from the logging dataset (turned on by
# 05_enable_interaction_logging.py), asks an LLM to diagnose behavior problems
# against the CURRENT system prompt, and writes a REVISED-prompt PROPOSAL to the
# hub for a human to review.
#
# THIS NOTEBOOK NEVER CHANGES AN AGENT PROMPT. It only:
#   1. reads logs (read-only),
#   2. calls ONE bounded LLM completion,
#   3. saves a markdown proposal to /python/owismind_hub/doctor/proposal-<k>.md.
# A human reviews the proposal, updates the hub prompt (capabilities.json /
# orchestrator_persona.md / prompts/<domain>/understand_extra.md) BY HAND, and
# re-runs the LAB benchmark before keeping the change. The doctor's output is a
# suggestion, not a deployment.
#
# DATA SENSITIVITY: the interaction logs contain REAL business data (client
# names, amounts). Restrict access to the logging dataset and to this
# notebook's outputs. Evidence excerpts are shown ONLY in the notebook output
# below; the proposal file saved to the hub withholds them (the project
# library is readable by every project reader).
# =============================================================================

import dataiku
from owismind_factory import hub, doctor

# --------------------------------------------------------------------------- CONFIG
TARGET = "orchestrator"        # "orchestrator" or a domain key (e.g. "revenue", "tickets")
N_INTERACTIONS = 30
COMPLAINT = ""                 # free text: describe the misbehavior you observed
LOGGING_DATASET = "owismind_agent_logs"
PERSONA_OVERRIDE = ""          # paste the current prompt here if the hub has none
DRY = True                     # this notebook never edits an agent; the proposal
                               # markdown is still SAVED to the hub for review

# --------------------------------------------------------------------------- resolve project + settings
client = dataiku.api_client()
project = client.get_default_project()
settings = hub.get_settings(project)
print("Prompt doctor (DRY=%s): this notebook never edits an agent, it only saves a "
      "review proposal." % DRY)

# --------------------------------------------------------------------------- resolve target prompt
if TARGET == "orchestrator":
    persona_path = hub.PERSONA_PATH
    agent_label = "Orchestrator"
else:
    persona_path = "%s/prompts/%s/understand_extra.md" % (hub.HUB_ROOT, TARGET)
    agent_label = "%s expert" % TARGET

persona = PERSONA_OVERRIDE.strip() or hub.read_text(project, persona_path)

if not persona:
    print("No prompt found at %s and PERSONA_OVERRIDE is empty." % persona_path)
    print("Paste the current system prompt into PERSONA_OVERRIDE and re-run.")
else:
    # ----------------------------------------------------------------------- collect + diagnose
    interactions = doctor.collect_interactions(project, LOGGING_DATASET, limit=N_INTERACTIONS)
    print("Collected %d interactions from %s." % (len(interactions), LOGGING_DATASET))

    result = doctor.run_doctor(project, settings.get("llm_sonnet"), persona,
                               interactions, complaint=(COMPLAINT or None))
    # Notebook output only: evidence excerpts are real conversation data.
    print("\n" + doctor.format_proposal_markdown(result, agent_label,
                                                 include_evidence=True))
    # Persisted copy: evidence withheld (default), the hub is project-readable.
    markdown = doctor.format_proposal_markdown(result, agent_label)

    # ----------------------------------------------------------------------- save the proposal
    # The ONLY DSS write here, and a harmless one: a markdown suggestion a human
    # reviews. It never touches an agent prompt. First free slot, bounded at 200.
    k = 1
    while hub.read_text(project, "%s/doctor/proposal-%d.md" % (hub.HUB_ROOT, k)) is not None:
        k += 1
        if k > 200:
            break
    proposal_path = "%s/doctor/proposal-%d.md" % (hub.HUB_ROOT, k)
    hub.write_text(project, proposal_path, markdown)
    print("\nProposal saved to %s" % proposal_path)
    print("Review it, update the hub prompt BY HAND, then re-run the LAB benchmark "
          "before keeping the change. The doctor never edits an agent.")
