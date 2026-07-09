# semantic-models/ - the SQL brains the semantic-query tools run

> Part of the OWIsMind agent system (production project **OWISMIND_PRD_V1_2**): see
> [`../README.md`](../README.md) (master guide) and [`../tools/README.md`](../tools/README.md)
> (the two Semantic Model Query tools). The tools `revenue_semantic_query` (`v4oqA6R`)
> and `tickets_semantic_query` (`nEirlso`), called by the two sub-agents, point at
> the two models documented here.

This folder holds a **readable snapshot** of each live model, the **scripts** that
build / iterate them, and a **versioned JSON config dump** per model. The live
models themselves live in DSS (source of truth).

## Layout

| Path | What |
|---|---|
| [`MODEL.md`](MODEL.md) | Human-readable snapshot of the LIVE revenue model (entities, metric, filters, golden queries, glossary, instructions, tool config). **Read this first.** |
| [`TOOL_DESCRIPTIONS.md`](TOOL_DESCRIPTIONS.md) | Ready-to-paste "Description for LLM" text for each Semantic Model Query tool (revenue + tickets). Paste into the DSS tool settings. |
| `Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.v1.json` | Config dump (`get_raw()`) of the revenue model `AHUh9hb`. |
| `TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.v1.json` | Config dump of the tickets model `dM4jA4G`. |
| `scripts/` | The build / iterate / dump / repoint scripts (see the status table below). |

## The two live models

| Model | id | Bound tool | Dataset / physical table | Snapshot |
|---|---|---|---|---|
| `Drive_Revenues_Semantic_Model` | `AHUh9hb` | `revenue_semantic_query` (`v4oqA6R`) | `OWISMIND_PRD_V1_2.DRIVE_Revenues` -> `"OWISMIND_PRD_V1_2_drive_revenues"` | `MODEL.md` + `Drive_Revenues_Semantic_Model/*.v1.json` |
| `TroubleTickets_Semantic_Model` | `dM4jA4G` | `tickets_semantic_query` (`nEirlso`) | `OWISMIND_PRD_V1_2.TroubleTickets_year` | `TroubleTickets_Semantic_Model/*.v1.json` |

Both tools run **Agent mode OFF** (linear SQL pipeline), LLM `vertex_ai/claude-sonnet-4-6`,
embedding `vertex_ai/text-embedding-005`, access datasets as the calling user. The
revenue model is queried by `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) and the
tickets model by `CSSO_Trouble_Tickets_Expert` (`agent:NcE9LD2i`), each via its
`SEMANTIC_TOOL_ID` when `SQL_ENGINE = "semantic_tool"` (the default).

> **The JSON dumps are point-in-time snapshots.** The revenue dump
> (`Drive_Revenues_Semantic_Model.v1.json`) dates from 2026-06-22 and therefore
> **predates the 2026-07-08 `Solution` re-add + repoint to the clone dataset**
> (`add_solution_and_repoint_prod_clone.py`): a **re-dump is pending** (run
> `dump_semantic_model.py` against the live model and commit the refreshed JSON).
> Until then the JSON reflects the pre-re-add structure; the live model in DSS is
> the truth.

## scripts/ - status table

**Current (going-forward path):**

| Script | Role | Status |
|---|---|---|
| `update_aligned_semantic_model.py` | In-place MODIFY of the REVENUE model: refresh instructions + golden queries on the active version (no create, no re-index). The revenue iteration path. | current |
| `update_tickets_semantic_model.py` | In-place MODIFY of the TICKETS model: inject instructions + golden queries + entity/attribute descriptions + metrics (`COUNT(DISTINCT id)`). The tickets iteration path. | current |
| `dump_semantic_model.py` | Generic export of a live model `get_raw()` to its `*.v1.json` snapshot. Run after EVERY model change (set the CONFIG block for REVENUE or TICKETS). | current |
| `add_solution_and_repoint_prod_clone.py` | Re-add the `Solution` offer column to the revenue model AND repoint it (datasetRef + golden-query table literals) at the clone dataset `OWISMIND_PRD_V1_2.DRIVE_Revenues`, then re-index. | **executed + validated in DSS 2026-07-08** |
| `repoint_tickets_prod_clone.py` | Pure repoint of the TICKETS model at the clone dataset (datasetRef + table literals), then re-index. | **ready, simulated 4/4, NOT yet launched on the clone** |

**Legacy / reference (kept for history, not the current path):**

| Script | Role | Status |
|---|---|---|
| `build_aligned_semantic_model.py` | One-time CREATE of the aligned revenue model `AHUh9hb` from a read-only copy of the old model (corrections, golden queries, instructions, index). | legacy (one-time build, done) |
| `drop_column_and_reindex.py` | Generic column-drop / re-index utility. Its `Solution`-removal parameterization is **historical** (the 2026-06-22 removal, since reverted by the re-add). | reference |
| `migrate_semantic_model_to_project.py` | Generic promotion-era util: COPY a model to another project, remapping dataset refs + table names. | legacy (superseded by `*_prod_clone.py`) |
| `remap_semantic_model.py` | Generic promotion-era util: rewrite an EXISTING model's dataset refs / table literals in place, then re-index. | legacy (superseded by `*_prod_clone.py`) |

The two `*_prod_clone.py` scripts replaced the old DEV->PROD promotion utilities
(`migrate_*` / `remap_*`): prod is now a **clone** of the DEV project (ids
preserved), so cloning a project does NOT repoint its semantic models (datasetRef +
golden-query table literals stay on the DEV table, and the DSS UI does not fix it).
The `*_prod_clone.py` scripts are the notebook-run repoint (DRY_RUN first, then
re-index; remap both `<KEY>.` and `<KEY>_` forms).

## Design of the revenue model - the sub-agent ASSISTS, it does not DICTATE

The tool runs on a **smart model (Sonnet) WITH the semantic layer**, so it
understands the dataset far better than the sub-agent's small UNDERSTAND model. The
sub-agent sends the tool the **user's real question (source of truth)** plus
**HINTS**: the intent shape, the values/columns its grounding helper matched in the
live catalog, the preferred presentation, scenario and period. Hints are **help,
not orders - the tool keeps the final say**. We never force a column choice; when a
value spans offer levels we *suggest* the most granular and flag the alternative.

The business rules below live in **both** places: as firm rules in the model
instructions (the tool enforces them) and as supportive hints from the sub-agent.

1. **Offer hierarchy priority + transparency.** A term is resolved to the most
   granular offer level that contains it. Hierarchy, broadest to most granular:
   **SolutionLine > Solution > Product**; grounding preference order:
   1. `Product`, 2. `Solution`, 3. `SolutionLine`, 4. `sirano_product` (a
   secondary technical code, **never** the default: BUDGET rows can lack it, so
   defaulting to it can drop the budget to 0). When a value exists at several
   levels the most granular is used **and disclosed** ("... also exists as a
   SolutionLine, tell me if you meant that level").
   - **The semantic model owns this decision** (hierarchy rules in
     `sqlGenerationConfig.instructions` + the `commercial_offer` entity description).
   - **The sub-agent does NOT pin a column for an ambiguous term**: it flags
     `AMBIGUOUS TERM - "EVPL" is a real data value present in SEVERAL columns (...)`
     and leaves the choice to the model. Confident single-column values (e.g. a
     customer name) are still suggested as typo-free hints.
2. **Customer identity: display name + carrier_code, diamond_id discreet.**
   `diamond_id` is the master key (kept in `GROUP BY` for exactness) but means
   nothing to the business: lead with **Account_name + carrier_code** and keep
   diamond_id as the **last, de-emphasized** column.
3. **Account_partner & Parent_Group.** `Account_partner` = the reseller in an
   **indirect** deal (we sell to Airbus, who resells to Maroc Telecom: end customer
   = Maroc Telecom, partner = Airbus). `Parent_Group` is **not** used unless
   explicitly asked.

### Incoherences fixed when the aligned model was built

- `Phase = 'ACTUAL'` -> **`'ACTUALS'`** in the `revenue_record` description, the
  `Phase` attribute, and the **`Actual Revenue Only` filter** (which was matching
  **zero rows**).
- Removed the **bogus `diamond_id` glossary term** (it described `original_dataset`
  / lineage).
- Removed the **`roaming hub` synonym** from *Roaming Sponsor*.
- Golden queries: **no self-join** (all 3 entities map to one physical table), name
  + carrier_code display, diamond_id last; offer-priority, named-customer, indirect,
  per-partner.
- YTD aligned to "latest available reporting month" (no hardcoded "today" -> no
  partial month).
- Instructions now state **one physical table, never JOIN**.

## How to iterate the revenue model

The aligned model already exists and `revenue_semantic_query` is already bound to
it; these steps are the iteration path, not a first-time deploy.

1. **Iterate the rules.** Edit `NEW_INSTRUCTIONS` / `GOLDEN_QUERIES` in
   `update_aligned_semantic_model.py`, set `NEW_MODEL_ID` to `AHUh9hb`, run it in a
   DSS notebook (project OWISMIND_PRD_V1_2). In place, no re-index.
2. **Test in the model's Playground**: a Product that overlaps another level, a term
   at SolutionLine, "top customers" (name + carrier_code, diamond_id last),
   indirect / per-partner, a named customer ("HALYS"), and a `Solution`-level term
   (grounding the re-added column).
3. **Refresh the repo snapshot**: run `dump_semantic_model.py` (REVENUE CONFIG) and
   commit `Drive_Revenues_Semantic_Model/Drive_Revenues_Semantic_Model.v1.json` +
   update `MODEL.md` if the structure changed.
4. **Profile overrides for the sub-agent** (optional reinforcement, not on the
   critical path): add rows to the editable overrides dataset (INPUT 2 of the
   profile recipe) then re-run the profile recipe. The model instructions are the
   source of truth for the offer / display rules.

   | key | field | value | needed? |
   |---|---|---|---|
   | `diamond_id` | `display_columns` | `["Account_name","carrier_code"]` | recommended (reinforces name + carrier display) |
   | `Product` | `ambiguity_priority` | `0` | optional (the model already resolves ambiguity) |
   | `Solution` | `ambiguity_priority` | `1` | optional |
   | `SolutionLine` | `ambiguity_priority` | `2` | optional |
   | `sirano_product` | `ambiguity_priority` | `3` | optional |

5. **No sub-agent re-paste needed for a model-only change** (the sub-agent
   references the tool by id). Re-paste `SalesDrive_revenue_expert.py` into its Code
   Agent (`agent:bHrWLyOL`, env 3.11) only when the agent code itself changes.

## The tickets semantic model (second domain)

The tickets domain has its OWN dedicated model `TroubleTickets_Semantic_Model`
(`dM4jA4G`) and its own tool `tickets_semantic_query` (`nEirlso`) - a shared model
is forbidden (the one-table-never-JOIN rule and the 1:1 tool-to-model binding).
Unlike revenue (built by cloning the old model), the tickets model was created in
the **DSS UI on the `TroubleTickets_year` dataset** (the UI auto-discovers
entities/attributes with valid shapes), then the brain is injected by script:

1. DSS UI: create the model on `TroubleTickets_year`; index distinct values once.
2. `update_tickets_semantic_model.py` (`NEW_MODEL_ID = dM4jA4G`): inject the tickets
   `TICKETS_INSTRUCTIONS` + golden queries + entity/attribute descriptions +
   metrics (`COUNT(DISTINCT id)`), in place, no re-index. The duration unit
   (minutes) and the count-DISTINCT / latest-snapshot rules are baked in; only the
   exact `CurrentStatus` open/closed values are data-dependent (the instructions
   tell the model to use the exact catalog values from the index).
3. `dump_semantic_model.py` (TICKETS CONFIG): snapshot to
   `TroubleTickets_Semantic_Model/TroubleTickets_Semantic_Model.v1.json`.
4. `repoint_tickets_prod_clone.py`: repoint the model at the clone dataset
   (**ready, simulated 4/4, not yet launched** - run it on the clone, then re-index).
5. The `tickets_semantic_query` tool (Agent OFF, Sonnet, access-as-user) is bound to
   the model; confirm its id `nEirlso` matches `SEMANTIC_TOOL_ID` in
   `../agents/CSSO_Trouble_Tickets_Expert.py` and `tickets_expert.semantic_model.tool_id`
   in `../registry.json`.

Full runbook: [`../PLAYBOOK_ADD_AGENT.md`](../PLAYBOOK_ADD_AGENT.md).

## DSS housekeeping tied to the models

- **Update each tool's "Description for LLM"** (see [`TOOL_DESCRIPTIONS.md`](TOOL_DESCRIPTIONS.md)):
  the revenue text drops the stale *"only after Drive_Revenues_resolve_filter_value
  ..."* precondition (that tool is LEGACY and pending deletion; grounding is now
  inline).
- **Re-dump the revenue JSON** after the 2026-07-08 `Solution` re-add (see the note
  above): the committed snapshot predates it.
