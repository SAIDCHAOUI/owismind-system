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
2. **The Config & Prompt Hub** (`/python/owismind_hub/` in the DSS project library,
   repo seeds in [`../project-library/python/owismind_hub/`](../project-library/python/owismind_hub/)): prompts and the runtime CAPABILITIES
   registry live OUTSIDE the pasted agent code. The agents load them once at
   start with strict validation and silent fallback to their embedded defaults.
   Adding a validated domain = one JSON entry, zero orchestrator re-paste.
3. **The Agent Factory Console** (`Standard-webapps/agent-factory-console/`): a Standard
   webapp (separate from the Vue plugin app for now) driving probe / plan /
   execute / wizard / prompt editing. Same paste-in deployment as the LAB webapps.

## Module map (owismind_factory)

| Module | Role | API risk |
|---|---|---|
| `fctx` | FactoryContext: dry-run plumbing, action journal, markdown report | none |
| `spec` | DomainSpec: validated domain description + ALL derived names (L110-safe) | none |
| `hub` | read/write of `/python/owismind_hub/` + capabilities validation + backups | none |
| `registry` | DomainSpec -> orchestrator CAPABILITIES entry (frozen dialect labels) | none |
| `flow_builder` | zone, managed datasets, recipes CLONED from the validated templates, INACTIVE step-based refresh scenario (one build step per knowledge dataset) + `run_scenario_and_wait` (bounded wait, outcome + `first_error_details`, re-attach to a live run) | none (confirmed APIs) |
| `semantic_builder` | create model + server-seeded v1 + schema-derived entity + wizard config + one-pass indexing | none (PROVEN on this instance) |
| `wizard` | LLM-assisted authoring: profile digest -> draft config + clarifying questions (ONE Mesh completion, `with_json_output`); the draft prompt bakes trap-shape guidance (COUNT DISTINCT, units, explicit time axis, display columns, one-table rule) and requires `clarifying_questions` + `profile_overrides`; offline `validate_golden_queries` gate | none |
| `tool_builder` | Semantic Model Query tool cloned from the live template | **GATED** (params schema undocumented: needs probe discovery) |
| `agent_builder` | sub-agent code generation (pure) + Code Agent creation & code injection | **GATED** (raw layout undocumented: needs probe hints) |
| `probes` | Phase 0: read-only capability probe + flag-gated write round-trip | write probe deletes ONLY its own zz objects |
| `pipeline` | the 13 ordered steps, each idempotent, gated steps degrade to MANUAL, downstream steps BLOCKED after a failed prerequisite | none |
| `align` | generic clone aligner: repoint ALL semantic models to the current project key | none (generalizes the validated repoint scripts) |
| `doctor` | prompt doctor: interaction logs + current prompt -> diagnosis + revised prompt PROPOSAL | none (never writes prompts) |
| `guided` | the console's step-by-step assistant: 13-stage state machine (dataset -> enabled capability), auto stages delegate to `pipeline`, manual stages carry French instructions and are VERIFIED against DSS before advancing (positive-only prechecks: "could not verify" never advances) | none (reuses the gated builders) |
| `guided_store` | one-row-per-run SQL persistence of guided runs (plugin storage pattern: `{PROJECT_KEY}_owismind_factory_guided_v1`, parameterized values, COMMIT, identifier gates) so a reload/restart resumes the run | none |
| `removal` | capability removal engine: probe-based inventory (only CONFIRMED objects enter it; the SOURCE dataset is protected) + `safe_delete` identity gate (re-read the live name, match it, only then delete) + per-family deletion executors with read-back verification | deletion module (sanctioned by the deletion-confinement guard) |

## The gates (why some steps may stay manual)

Two API surfaces exist in the official client but their payload schema is NOT
documented: the raw settings of a PYTHON_AGENT (where the source code and code
env live) and the params of a Semantic Model Query tool. The factory NEVER
guesses them. The Phase 0 probe (`Notebooks/00_probe_capabilities.py`) reads
both schemas from the LIVE validated objects (orchestrator `038G7mlF`, tool
`v4oqA6R`) and, optionally (write probe), confirms the round-trip on throwaway
objects. Confirmed -> the pipeline creates tool + agent fully automatically.
Not confirmed -> those two steps print an exact 2-minute UI checklist and the
generated agent code lands in `/python/owismind_hub/generated/` ready to paste.
Everything else (zone, datasets, recipes, scenario, semantic model, capability
registration) is documented API and runs either way.

## Safety model (Dataiku instance first)

- **Dry-run by default** everywhere; the console and notebooks show the full
  PLAN before anything executes.
- **Idempotent**: re-running skips existing objects; no step ever recreates.
- **Never guesses "absent" on an API error**: an existence check whose `list_*`
  call itself fails raises `ExistenceCheckError`; the step FAILS without creating
  anything (a permission error or timeout is never read as "the object does not
  exist"). Dry-run planning tolerates an unverifiable existence.
- **Failure never flatters the report**: a step that raises is recorded FAILED
  (captured, not re-raised) and the steps that depend on it are marked BLOCKED
  rather than attempted (e.g. if the base dataset cannot be secured, the recipes
  and semantic-model steps are BLOCKED, not run against a missing input). The base
  import is also VERIFIED afterwards: if the imported dataset did not land under
  the expected name, the step fails loudly instead of leaving a dangling
  reference. The scenario trigger is its own action (`scenario_trigger`).
- **Never writes a placeholder agent id**: the capability step only appends an
  entry once a real Code Agent id exists; with no verified id it degrades to a
  MANUAL note (both the factory and orchestrator validators reject a non
  alphanumeric `agent:` suffix, so `agent:FILL_ME` can never reach the runtime
  registry).
- **No deletions**: the factory cannot delete anything (except the write probe
  removing the two zz objects it just created, behind an explicit flag).
- **Builds are operator-triggered**: the refresh scenario is created INACTIVE
  with its nightly trigger defined. The guided assistant's first-build stage
  runs it AFTER an explicit operator click (confirm modal), waits with a
  bounded poll, and re-attaches to an in-progress run instead of firing a
  second one; recurring refreshes stay opt-in (a human activates the scenario
  in DSS, and can add a "dataset modified" trigger there).
- **Indexing runs once** per model creation (embedding LLM cost), via
  `DSSFuture.wait_for_result()` (no tight polling).
- **The wizard sends aggregated profile metadata only**, never raw rows; ONE
  completion per draft.
- **New capabilities ship `enabled: false`** and only a human flips them after
  the smoke checklist.
- **Hub writes are validated + backed up** (`/python/owismind_hub/backups/`) and
  serialized in-process (a write lock shared by `write_capabilities` and
  `append_capability`) so two concurrent console jobs cannot lose an entry.
- **The wizard config is validated offline before it touches the model**: golden
  queries that are not read-only or that reference an invented column are stripped
  into a MANUAL curation action (never pushed to the semantic model). Applying a
  config uses explicit-empty semantics: a key present but empty CLEARS that
  section, an absent key leaves the model as is.

## Iterating prompts (the fast loop the hub unlocks)

1. Edit `/python/owismind_hub/prompts/orchestrator_persona.md` (DSS library editor or
   the console's Prompts screen).
2. Restart the orchestrator agent (re-save or shutdown/wake in DSS): the loader
   reads the hub once at process start.
3. Re-run the LAB benchmark before keeping the change.
The `06_prompt_doctor.py` notebook automates the diagnosis: interaction logs +
current prompt + your complaint -> structured proposal in
`/python/owismind_hub/doctor/`. It NEVER applies anything itself.

## Removing a capability (guided removal run)

The reverse of "create a domain", added 2026-07-22 (spec:
`docs/superpowers/specs/2026-07-22-capability-removal-design.md`). From the
console overview, every capability card carries two actions:

- **Desactiver / Activer** (immediate): flips the `enabled` flag in
  `capabilities.json` (validated, backed-up write). The architecture stays
  intact; re-enable is one click. The UI reminds the operator to RE-SAVE the
  orchestrator then open a NEW conversation (the registry loads at process
  start, lesson L168).
- **Supprimer...** (guided run): the operator must TYPE the domain name
  (checked server-side), then a `removal` run starts in the same guided state
  machine, 12 stages: `inventory` -> `disable` -> `delete_tool` ->
  `delete_agent` -> `delete_model` -> `delete_scenario` -> `delete_recipes` ->
  `delete_datasets` -> `delete_zone` -> `catalog_cleanup` -> `hub_cleanup` ->
  `final_check`.

Safety model:

- **Probe-based inventory**: only objects whose existence is CONFIRMED enter
  the inventory (capability entry + naming conventions + live listings; the
  founders' off-convention model resolves through the tool params). Absent
  candidates are journaled as "deja absent". A listing failure FAILS the stage:
  nothing is ever deleted on a partial inventory.
- **The SOURCE dataset (`lookup_dataset`) is never deletable** (user decision
  2026-07-22): it is listed as PROTECTED on the datasets card.
- **One confirmed stage at a time**: each deletion stage's card lists exactly
  what the click will delete (kind, name, id, location) BEFORE launching; a
  deletion is verified ABSENT by read-back before the run advances.
- **Identity gate**: every `delete()` goes through `removal.safe_delete`
  (re-read the live name, refuse on mismatch or unreadable name). Datasets are
  deleted with `drop_data=True` (derived tables, rebuildable).
- **Manual fallback**: an API refusal flips the stage to `waiting_user` with
  exact instructions; "C'est fait" verifies the ABSENCE against DSS before
  advancing.
- **Template guard**: if the domain's objects serve as factory templates
  (`factory_settings.json`), the inventory stops on an explicit acknowledgment:
  the factory cannot create new domains until the templates are repointed.
- **Last-entry rule**: the last capability entry is never removed, only
  disabled (an empty `capabilities.json` would make the orchestrator fall back
  to its embedded defaults and the removed expert could silently reappear).
- **Refusals**: removal never starts while the domain's refresh scenario runs
  or while another guided run is active; a capability pointing at the
  orchestrator itself is refused.
- The removal run stays in the guided store history (who removed what, when).

## Tests

DSS-free suite (with the rest of the mirror tests):

    python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests

Anti-drift guarantees: hub seeds byte-equivalent to the orchestrator's embedded
defaults; validators (factory vs orchestrator) in sync; generation tested
against the REAL engine file; full pipeline dry-run on a read-only fake project.
