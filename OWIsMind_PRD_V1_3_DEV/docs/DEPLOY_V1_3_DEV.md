# Deploying the Agent Factory on the v1.3-dev clone - step by step

> **Audience**: you, tomorrow morning. Each phase says what to click/run, what
> to expect, and what to paste back to Claude so the gated steps get unlocked
> or re-worked. Order matters. NOTHING here touches the v1.2 prod project.

## Phase 0 - security gates (from the 2026-07-16 dual audit, see `SECURITY_AUDIT_2026-07-16.md`)

Three conditions must hold BEFORE anything below runs on a real instance:

1. **Console exposure (G1)**: the `agent-factory-console` webapp reconfigures the
   orchestrator's persona and capabilities under its WRITE_CONF run-as identity,
   with no per-viewer authorization. NEVER put it on a shared dashboard: restrict
   who can open it to the admin group, and give it a dedicated run-as user scoped
   to this project only.
2. **Read-only SQL (G3)**: confirm at the DATABASE level that the connection the
   agents use (`SQL_owi`) runs with a SELECT-only role and a statement timeout.
   The factory's offline golden-query validator is defense in depth, not the
   boundary.
3. **Logging data (phase G)**: the interaction-logging dataset stores real
   conversations (client names, figures). Before enabling it, decide who can
   read that dataset and how long rows are kept.

## Phase A - create the v1.3-dev DSS project (clone)

1. [DSS] Duplicate the prod project `OWISMIND_PRD_V1_2` (Actions > Duplicate),
   name the new project e.g. `OWIsMind_PRD_V1_3_dev`. Duplication preserves all
   object ids (agents, tools, semantic models), like the v1.2 clone did.
2. [DSS notebook, in the CLONE] The clone's semantic models still reference the
   SOURCE project's datasets/tables (lesson L146). Install the factory package
   first (Phase B step 1), then run `Notebooks/02_align_clone.py` in THREE passes:
   (a) as-is (`EXPECTED_SOURCE_KEYS = []`) = DISCOVERY: it lists the foreign
   project keys per model and remaps NOTHING; (b) put the reported clone-source
   key(s) in `EXPECTED_SOURCE_KEYS` (e.g. `["OWISMIND_PRD_V1_2"]`), keep
   `DRY_RUN = True`, read the plan; (c) `DRY_RUN = False` + `REINDEX = True`.
   Only allowlisted keys are ever remapped: a deliberate reference to another
   project's shared dataset is reported and left untouched. This generalizes
   the validated repoint scripts to ALL models at once.
3. Sanity: open each semantic model, check `datasetRef` now says
   `<CLONE_KEY>.<Dataset>`, and test one question in the Playground.

## Phase B - install the factory

1. [DSS] Project library (the CLONE > Libraries, `python/` folder): create the
   folder `owismind_factory` and paste every file from the repo
   `OWIsMind_PRD_V1_3_DEV/project-library/python/owismind_factory/`.
   (Option: the DSS library editor has a Git import feature if you prefer
   pulling the repo folder instead of pasting.)
2. [DSS] Create python notebooks for `Notebooks/00_probe_capabilities.py`,
   `01_push_config_hub.py`, `02_align_clone.py`, `03_create_domain.py`,
   `04_semantic_wizard.py`, `05_enable_interaction_logging.py`,
   `06_prompt_doctor.py` (paste each file as a notebook).
3. [notebook] Run `00_probe_capabilities.py` as-is (READ-ONLY: RUN_WRITE_PROBES
   stays False). It prints the Phase 0 report and stores
   `/owismind_hub/probe_report.md` + `probe_results.json` in the library.
4. **Paste the probe report back to Claude** (or commit it as
   `docs/CAPABILITY_MATRIX.md`). It answers the two open questions:
   the Code Agent code key and the Semantic Model Query tool type/params.
5. [notebook] Run `01_push_config_hub.py` (seeds the hub: settings,
   capabilities.json, persona, engine template if the probe found the code key).
6. [DSS] Edit `/owismind_hub/factory_settings.json`: set `code_env_311` to the
   EXACT name of the Python 3.11 code env of this instance. Verify
   `sql_connection`, the template ids, `orchestrator_agent_id`.

## Phase C - hub-aware agents (behavior-neutral re-paste)

1. [DSS] Re-paste the three agent files from the repo into their Code Agents
   (env 3.11): `OWIsMind_orchestrator.py` (`038G7mlF`),
   `SalesDrive_revenue_expert.py` (`bHrWLyOL`),
   `CSSO_Trouble_Tickets_Expert.py` (`NcE9LD2i`).
2. The hub seeds are byte-equivalent to the embedded defaults (enforced by
   `tests/test_factory_registry.py`), so NOTHING changes in behavior. Check the
   agent log shows `CAPABILITIES loaded from the config hub (2 entries)`.
3. [webapp] One revenue question + one tickets question: same behavior as
   before. That validates the whole hub chain end to end.

## Phase D - unlock the gates (optional but recommended)

1. [notebook] Re-run `00_probe_capabilities.py` with `RUN_WRITE_PROBES = True`.
   It creates ONE throwaway agent (`zz_factory_probe`) + ONE throwaway tool,
   verifies the settings round-trip, then deletes both. The saved
   `probe_results.json` now carries `confirmed: true` flags: the pipeline's
   `code_agent` and `semantic_tool` steps become fully automatic.
2. If a round-trip fails, nothing is lost: those steps stay manual (one paste /
   2 minutes of UI) and everything else still runs.

## Phase E - the console webapp (optional, can come later)

Follow `Standard-webapps/agent-factory-console/README.md`: create a Standard webapp,
paste the 4 panes, give it project WRITE_CONF, start the backend. Everything
the console does is also doable through notebooks 00 to 06.

## Phase F - first new domain, end to end

1. [notebook 03] Fill SPEC (domain, base_dataset or source table, labels),
   `DRY_RUN = True`: READ THE PLAN. In the console the plan also surfaces
   non-blocking preflight warnings (key/domain collisions, empty
   lookup_search_columns, tight dataset-name headroom, identical FR/EN labels, a
   generic planner_description) and a copy-pastable operator runbook.
2. `DRY_RUN = False`: creates zone + datasets + recipes + INACTIVE scenario (with
   its daily trigger defined as a separate `scenario_trigger` action) + semantic
   model shell (+ tool + agent if Phase D confirmed the gates). If a prerequisite
   fails (e.g. the base dataset cannot be secured or its post-import verification
   fails), that step is FAILED and the steps that read it are reported BLOCKED,
   not silently run; read the runbook the report prints for the ordered to-do.
3. [DSS] Run the `Refresh_<Domain>` scenario ONCE by hand, off-peak. Review the
   profile dataset (the business brain) like the playbook says.
4. [notebook 04] Wizard round 1 (ANSWERS = {}): read its French clarifying
   questions (the draft always returns them). Fill ANSWERS, re-run: config saved
   to the hub at `/owismind_hub/wizard/<domain>-config.json` (the console uses the
   same path and auto-attaches this config to plan/execute when the request body
   has none). The `semantic_config` step runs an offline gate first: any golden
   query that is not read-only or references an unknown column is stripped into a
   MANUAL curation action instead of being pushed to the model.
5. [notebook 03] Re-run with `WIZARD_CONFIG_PATH` set and
   `STEPS = ["semantic_config", "semantic_index", "semantic_tool", "code_agent",
   "capability"]`.
6. Curation + smoke (the factory report prints the checklist): Playground tests,
   profile overrides, tool description, THEN flip `enabled: true` on the new
   entry in `/owismind_hub/capabilities.json` and restart the orchestrator agent.
7. Update the repo: commit the wizard config, the generated agent file, the new
   `registry.json` entry and the model dump (mirror discipline unchanged).

## Phase G - logging + prompt doctor

1. [notebook 05] `05_enable_interaction_logging.py` (DRY_RUN first): creates the
   `owismind_agent_logs` dataset and enables interaction logging on the three
   agents. Logging writes are buffered (they lag a little).
2. After some real usage: [notebook 06] `06_prompt_doctor.py` with your
   complaint in COMPLAINT. Read the proposal in `/owismind_hub/doctor/`,
   apply what you like to the persona hub file, restart the orchestrator,
   re-run the LAB benchmark.

## Phase H - Durable Step Shell (v1.3 long-run workflow layer, built 2026-07-17)

The durable workflow runtime (spec `docs/superpowers/specs/2026-07-17-agentic-runtime-design.md`)
ships OFF by default: nothing changes for any agent until its admin profile
carries `durable_workflow: true`. Deployment order:

1. **Plugin zip**: the backend changes (durable_runner, run_state, 3 new `_v1`
   tables auto-created on first use, routes `/chat/active` + `/chat/activity`)
   ride the normal plugin upload + backend restart. The webapp MUST have
   **Auto-start enabled** (recovery after a DSS restart depends on it).
2. **Orchestrator re-paste** (env 3.11): the workflow command protocol +
   correlate step are in `GenAI/Agents/OWIsMind_orchestrator.py`. Legacy path is
   byte-identical without the machine token (golden-tested) - re-pasting is safe
   before the flag is ever enabled.
3. **Hub seeds**: push `owismind_hub/run_settings.json` +
   `owismind_hub/prompts/orchestrator_workflow.md` (notebook 01 path). Embedded
   fallbacks exist; a missing hub never breaks a run.
4. **Enable on DEV ONLY**: set `durable_workflow: true` (+ optional
   `domain_keywords: {revenue: [...], tickets: [...]}`) on the orchestrator's
   profile in the webapp admin settings. `correlate` additionally needs the
   Phase F catalog publication (`catalog_generation` on >= 2 capabilities).
5. **Validation campaign (16 scenarios, spec section 14)**: long smart run
   (> 5 min), long claude run (> 10 min), `stop_backend` between two steps,
   browser refresh mid-run (reconnect via `/chat/active`), closed tab (run must
   FINISH anyway), prolonged Mesh silence, rate limit, blocking quota, disabled
   specialist mid-run, rejected SQL, revenue x tickets correlation, 5-dataset
   plan, Stop during a blocked call, double poll, double `/chat/start` retry
   (idempotent), and the frontend-forge check (no SQL/agent id/physical table
   accepted from the client).
6. **One claim/complete smoke on the REAL executor**: the runs tables use one
   NEW SQL pattern (data-modifying CTE + `SELECT count(*)`, run_state.py) - run
   one full durable exchange and verify `webapp_agent_runs_v1` reached
   `completed` with `usage_accounted = true`.

Only after 5-6 pass on DEV: enable the flag on the prod clone.

## What to report back to Claude

- The Phase 0 probe report (step B4) - unlocks/locks the gates for good.
- Anything that FAILED with its exact error message + the factory report
  (every notebook prints `ctx.report_markdown()`).
- After Phase F: the wizard's questions and whether the drafted model needed
  heavy corrections (that calibrates the wizard prompt).
- After Phase H: which of the 16 scenarios failed (exact behavior + webapp log
  excerpt), and the durable runs table state after the smoke.
