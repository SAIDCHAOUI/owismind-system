# Agent Factory - industrialized creation of OWIsMind specialists (v1.3)

> **What this is.** The v1.3 machinery that turns "add a specialist sub-agent on
> dataset X" from a 2-day manual runbook into a guided, mostly automatic pipeline:
> source table -> Flow zone + 3 knowledge recipes/datasets -> semantic model
> (LLM-assisted authoring) -> Semantic Model Query tool -> Code Agent ->
> orchestrator registration. Design spec:
> `docs/superpowers/specs/2026-07-10-agent-factory-v1_3-design.md`.
> Deployment: [`DEPLOY_V1_3_DEV.md`](DEPLOY_V1_3_DEV.md).

## The three pillars

1. **`owismind_factory`** (`project-library/python/owismind_factory/`): the engine.
   Official Dataiku public API only, stdlib + `dataiku`, Python 3.9 compatible,
   dry-run by default, idempotent, ZERO deletion helpers.
2. **The Config & Prompt Hub** (`/owismind_hub/` in the DSS project library,
   repo seeds in [`../hub/`](../hub/)): prompts and the runtime CAPABILITIES
   registry live OUTSIDE the pasted agent code. The agents load them once at
   start with strict validation and silent fallback to their embedded defaults.
   Adding a validated domain = one JSON entry, zero orchestrator re-paste.
3. **The Agent Factory Console** (`webapps/agent-factory-console/`): a Standard
   webapp (separate from the Vue plugin app for now) driving probe / plan /
   execute / wizard / prompt editing. Same paste-in deployment as the LAB webapps.

## Module map (owismind_factory)

| Module | Role | API risk |
|---|---|---|
| `fctx` | FactoryContext: dry-run plumbing, action journal, markdown report | none |
| `spec` | DomainSpec: validated domain description + ALL derived names (L110-safe) | none |
| `hub` | read/write of `/owismind_hub/` + capabilities validation + backups | none |
| `registry` | DomainSpec -> orchestrator CAPABILITIES entry (frozen dialect labels) | none |
| `flow_builder` | zone, managed datasets, recipes CLONED from the validated templates, INACTIVE custom-python refresh scenario | none (confirmed APIs) |
| `semantic_builder` | create model + server-seeded v1 + schema-derived entity + wizard config + one-pass indexing | none (PROVEN on this instance) |
| `wizard` | LLM-assisted authoring: profile digest -> draft config + clarifying questions (ONE Mesh completion, `with_json_output`) | none |
| `tool_builder` | Semantic Model Query tool cloned from the live template | **GATED** (params schema undocumented: needs probe discovery) |
| `agent_builder` | sub-agent code generation (pure) + Code Agent creation & code injection | **GATED** (raw layout undocumented: needs probe hints) |
| `probes` | Phase 0: read-only capability probe + flag-gated write round-trip | write probe deletes ONLY its own zz objects |
| `pipeline` | the 13 ordered steps, each idempotent, gated steps degrade to MANUAL | none |
| `align` | generic clone aligner: repoint ALL semantic models to the current project key | none (generalizes the validated repoint scripts) |
| `doctor` | prompt doctor: interaction logs + current prompt -> diagnosis + revised prompt PROPOSAL | none (never writes prompts) |

## The gates (why some steps may stay manual)

Two API surfaces exist in the official client but their payload schema is NOT
documented: the raw settings of a PYTHON_AGENT (where the source code and code
env live) and the params of a Semantic Model Query tool. The factory NEVER
guesses them. The Phase 0 probe (`notebooks/00_probe_capabilities.py`) reads
both schemas from the LIVE validated objects (orchestrator `038G7mlF`, tool
`v4oqA6R`) and, optionally (write probe), confirms the round-trip on throwaway
objects. Confirmed -> the pipeline creates tool + agent fully automatically.
Not confirmed -> those two steps print an exact 2-minute UI checklist and the
generated agent code lands in `/owismind_hub/generated/` ready to paste.
Everything else (zone, datasets, recipes, scenario, semantic model, capability
registration) is documented API and runs either way.

## Safety model (Dataiku instance first)

- **Dry-run by default** everywhere; the console and notebooks show the full
  PLAN before anything executes.
- **Idempotent**: re-running skips existing objects; no step ever recreates.
- **No deletions**: the factory cannot delete anything (except the write probe
  removing the two zz objects it just created, behind an explicit flag).
- **Builds are human-triggered**: the refresh scenario is created INACTIVE with
  its nightly trigger defined; the first build is an explicit action, off-peak.
- **Indexing runs once** per model creation (embedding LLM cost), via
  `DSSFuture.wait_for_result()` (no tight polling).
- **The wizard sends aggregated profile metadata only**, never raw rows; ONE
  completion per draft.
- **New capabilities ship `enabled: false`** and only a human flips them after
  the smoke checklist.
- **Hub writes are validated + backed up** (`/owismind_hub/backups/`).

## Iterating prompts (the fast loop the hub unlocks)

1. Edit `/owismind_hub/prompts/orchestrator_persona.md` (DSS library editor or
   the console's Prompts screen).
2. Restart the orchestrator agent (re-save or shutdown/wake in DSS): the loader
   reads the hub once at process start.
3. Re-run the LAB benchmark before keeping the change.
The `06_prompt_doctor.py` notebook automates the diagnosis: interaction logs +
current prompt + your complaint -> structured proposal in
`/owismind_hub/doctor/`. It NEVER applies anything itself.

## Tests

DSS-free suite (with the rest of the mirror tests):

    python3 -m unittest discover -s OWIsMind_PRD_V1_2/tests

Anti-drift guarantees: hub seeds byte-equivalent to the orchestrator's embedded
defaults; validators (factory vs orchestrator) in sync; generation tested
against the REAL engine file; full pipeline dry-run on a read-only fake project.
