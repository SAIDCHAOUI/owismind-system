# semantic_model/ - the SQL brain that revenue_semantic_query queries

> Part of the OWIsMind agent system: see [`../../../README.md`](../../../README.md) (master guide) and
> the tool's deploy-target header (`../tools/`) (tools). The Semantic Model Query tool `revenue_semantic_query`
> (`v4oqA6R`), called by the sub-agent, points at the model documented here.

This folder holds the **scripts** that build/iterate the aligned semantic model, plus a
human-readable snapshot of its config. The live model itself lives in DSS.

| File | What |
|---|---|
| [`MODEL.md`](MODEL.md) | Human-readable snapshot of the LIVE model (entities, metric, filters, golden queries, glossary, instructions, tool config). **Read this first.** |
| `build_aligned_semantic_model.py` | One-time CREATE of the aligned model from a read-only copy of the old one (corrections, golden queries, instructions, index). |
| `update_aligned_semantic_model.py` | In-place MODIFY of an existing aligned model: refresh instructions + golden queries on the active version (no create, no re-index). The going-forward iteration path. |
| `dump_semantic_model.py` | Export the live model `get_raw()` to `Drive_Revenues_Semantic_Model.v1.json` (refresh the snapshot, no transcription drift). |
| `update_tickets_semantic_model.py` | In-place MODIFY of the TICKETS model: inject the tickets instructions + golden queries on the active version (no create, no re-index). The iteration path for tickets. |
| `dump_tickets_semantic_model.py` | Export the live tickets model to `TroubleTickets_Semantic_Model.v1.json`. |
| `migrate_semantic_model_to_project.py` | COPY a model to another project (e.g. DEV -> PROD), remapping dataset refs + table names automatically from the project keys. Creates a new model in the target. |
| `remap_semantic_model.py` | Rewrite an EXISTING model's dataset refs / table literals IN PLACE (no copy), then re-index. Fixes a botched migration or repoints a model at a different table. |

> **The model config is versioned here as JSON.** Each model's full `get_raw()` config lives in
> `<ModelName>.v1.json` in this folder (e.g. `Drive_Revenues_Model.v1.json` /
> `Drive_Revenues_Semantic_Model.v1.json`). Paste a fresh `dump_*.py` output into it after every
> model change, so the config is in the repo and never needs pasting in chat. The canonical
> SQL-generation rules also live verbatim in `build_aligned_semantic_model.py` (`NEW_INSTRUCTIONS`,
> byte-identical to `update_aligned_semantic_model.py`).

## Live model and tool (source of truth = DSS)

- Active model: **`Drive_Revenues_Semantic_Model`**, version `v1` (Active). Built as the aligned
  rebuild of the old model (`2O2KcHw` / `Drive_Revenues_Model`, kept intact as rollback).
- Bound to the tool **`revenue_semantic_query`** (`v4oqA6R`): LLM `vertex_ai/claude-sonnet-4-6`,
  embedding `vertex_ai/text-embedding-005`, **Agent mode OFF** (the faster linear SQL pipeline,
  not a multi-step agent), access datasets as the calling user, project `OWISMIND_DEV`.
- Queried by the sub-agent `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) via
  `SEMANTIC_TOOL_ID = "v4oqA6R"` when `SQL_ENGINE = "semantic_tool"` (the default).

## What the aligned rebuild fixed (vs the old `2O2KcHw`)

### Philosophy: the sub-agent ASSISTS, it does not DICTATE

The tool runs on a **smart model (Sonnet) WITH the semantic layer**, so it understands the
dataset far better than the sub-agent's small UNDERSTAND model. The sub-agent sends the tool the
**user's real question (source of truth)** plus **HINTS**: the intent shape, the values/columns
its grounding helper matched in the live catalog, the preferred presentation, scenario and
period. Hints are **help, not orders - the tool keeps the final say**. We never force a column
choice; when a value spans offer levels we *suggest* the most granular and flag the alternative.

The business rules below live in **both** places: as firm rules in the model instructions (the
tool enforces them) and as supportive hints from the sub-agent.

1. **Offer hierarchy priority + transparency.** A term is resolved to the most granular level
   that contains it: **Product > SolutionLine > sirano_product** (the `Solution` level was
   removed from the dataset). "IP" is a SolutionLine; "IPL" / "Roaming Sponsor" are Products.
   When a value exists at several levels (e.g. a value that is both a Product and a SolutionLine)
   the most granular (Product) is used **and disclosed** ("... also exists as a SolutionLine,
   tell me if you meant that level").
   - **The semantic model owns this decision** (hierarchy rules in
     `sqlGenerationConfig.instructions` + `commercial_offer` description, incl. *never default to
     sirano_product*).
   - **The sub-agent does NOT pin a column for an ambiguous offer term**: it flags
     `AMBIGUOUS OFFER TERM - "EVPL" is present in (Product, sirano_product); YOU
     resolve it` and leaves the choice to the model. (Regression that motivated this: pinning
     `sirano_product = 'EVPL'` while BUDGET rows have no sirano_product, so budget = 0.)
     Confident single-column values (e.g. a customer name) are still suggested as typo-free hints.

2. **Customer identity: display name + carrier_code, diamond_id discreet.** `diamond_id` is the
   master key (kept in `GROUP BY` for exactness) but means nothing to the business: lead with
   **Account_name + carrier_code** and keep diamond_id as the **last, de-emphasized** column.

3. **Account_partner & Parent_Group.** `Account_partner` = the reseller in an **indirect** deal
   (we sell to Airbus, who resells to Maroc Telecom: end customer = Maroc Telecom, partner =
   Airbus). `Parent_Group` is **not** used unless explicitly asked.

### Incoherences fixed in the model

- `Phase = 'ACTUAL'` -> **`'ACTUALS'`** in the `revenue_record` description, the `Phase`
  attribute, and the **`Actual Revenue Only` filter** (which was matching **zero rows**).
- Removed the **bogus `diamond_id` glossary term** (it described `original_dataset` / lineage).
- Removed the **`roaming hub` synonym** from *Roaming Sponsor*.
- Golden queries: **no self-join** (all 3 entities map to one physical table), name +
  carrier_code display, diamond_id last; Product-priority, named-customer, indirect, per-partner.
- YTD aligned to "latest available reporting month" (no hardcoded "today" -> no partial month).
- Instructions now state **one physical table, never JOIN**.

## Two scripts

- `build_aligned_semantic_model.py` - **one-time CREATE**: reads the old model read-only
  (`get_raw()` on a deep copy, never `save()` / `set_active` / `delete` on the old handle, so the
  old model stays 100 % untouched), applies all corrections, creates the new model + version v1,
  indexes. Prints the new model id.
- `update_aligned_semantic_model.py` - **MODIFY in place**: refreshes instructions + golden
  queries on the active version (no create, no re-index). Set `NEW_MODEL_ID` first.
  (`NEW_INSTRUCTIONS` / `GOLDEN_QUERIES` are byte-identical in both files; edit them in `update_`
  going forward.)

## How the live model was built, and how to iterate now

The aligned model already exists and `revenue_semantic_query` is already bound to it; the steps
below are the iteration path, not a first-time deploy.

1. **Iterate the rules.** Edit `NEW_INSTRUCTIONS` / `GOLDEN_QUERIES`, set `NEW_MODEL_ID` to the
   live model id, run `update_aligned_semantic_model.py` in a DSS notebook (project OWISMIND_DEV).
   In place, no re-index.
2. **Test in the model's Playground**: a Product that overlaps another level (*IP Transit*), "IP" at
   SolutionLine, "top customers" (name + carrier_code, diamond_id last), indirect / per-partner,
   a named customer ("HALYS").
3. **Refresh the repo snapshot**: run `dump_semantic_model.py` and commit
   `Drive_Revenues_Semantic_Model.v1.json` + update `MODEL.md` if the structure changed.
4. **Profile overrides for the sub-agent** (optional reinforcement, not on the critical path):
   add rows to the editable overrides dataset (INPUT 2 of the profile recipe) then re-run
   `profile_dataset_recipe.py`. The model instructions are the source of truth for the offer /
   display rules.

   | key | field | value | needed? |
   |---|---|---|---|
   | `diamond_id` | `display_columns` | `["Account_name","carrier_code"]` | recommended (reinforces name + carrier display) |
   | `Product` | `ambiguity_priority` | `0` | optional (the model already resolves ambiguity) |
   | `SolutionLine` | `ambiguity_priority` | `1` | optional |
   | `sirano_product` | `ambiguity_priority` | `2` | optional |

5. **No sub-agent re-paste needed for a model-only change** (the sub-agent references the tool by
   id). Re-paste `SalesDrive_revenue_expert.py` into its Code Agent (`agent:bHrWLyOL`, env 3.11)
   only when the agent code itself changes.

## The tickets semantic model (second domain)

The tickets domain gets its OWN dedicated model `TroubleTickets_Semantic_Model`
and its own tool `tickets_semantic_query` (a shared model is forbidden: the
one-table-never-JOIN rule and the 1:1 tool-to-model binding). Unlike revenue (built
by cloning the old model), the tickets model is created in the **DSS UI on the
`TroubleTickets_year` dataset** (the UI auto-discovers entities/attributes with
valid shapes), then the brain is injected by script:

1. DSS UI: create `TroubleTickets_Semantic_Model` on `TroubleTickets_year`; index
   distinct values once.
2. `update_tickets_semantic_model.py` (set `NEW_MODEL_ID`): inject the tickets
   `TICKETS_INSTRUCTIONS` + golden queries (in place, no re-index). Refine the
   `[CONFIRM]` items (Duration_ticket_total unit; exact `CurrentStatus` values).
3. `dump_tickets_semantic_model.py`: snapshot to
   `TroubleTickets_Semantic_Model.v1.json`.
4. Create the `tickets_semantic_query` tool (Agent OFF, Sonnet, access-as-user)
   bound to the model; put its id in `agents/TroubleTickets_expert.py`
   (`SEMANTIC_TOOL_ID`) and in `registry.json`.

Full runbook: [`../../../PLAYBOOK_ADD_AGENT.md`](../../../PLAYBOOK_ADD_AGENT.md).

## DSS housekeeping tied to the model

- **Update the tool's "Description for LLM"** (see the tool's deploy-target header (`../tools/`)): drop the stale
  *"only after Drive_Revenues_resolve_filter_value ..."* precondition (that tool is being deleted;
  grounding is now inline).
- Keep the OLD model (`2O2KcHw`) as rollback; do NOT delete it.

## Rollback

- Tool -> re-point to the old model (`2O2KcHw`). The aligned model and the sub-agent code live in
  git history; revert there. The profile overrides can be removed by editing the overrides
  dataset and re-running the profile recipe.
