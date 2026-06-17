# Semantic model - aligned rebuild (2026-06-15)

> Part of the OWIsMind agent system: see [`../README.md`](../README.md) (master guide) and
> [`../tools/README.md`](../tools/README.md). The Semantic Model Query tool `revenue_semantic_query`
> (`v4oqA6R`) called by the sub-agent points at the model built/aligned by the scripts here.

Goal: make the **semantic model** (SQL generator) and the **Dataset Expert sub-agent**
fully complementary and ultra-precise, and fix the incoherences found in the live `v4`
config. The old model (`2O2KcHw` / `Drive_Revenues_Model`) is **never touched** - we build a
**brand-new model** from a read-only copy of its active version.

## What changed and why

### Philosophy: the sub-agent ASSISTS, it does not DICTATE

The Semantic Model Query tool runs on a **smart model (Sonnet 4.6) WITH the semantic layer**,
so it understands the dataset far better than our small UNDERSTAND model. The sub-agent
therefore sends the tool the **user's real question (source of truth)** plus **HINTS**: the
intent shape, the values/columns its grounding helper matched in the live catalog, the
preferred presentation, scenario and period. Hints are **help, not orders - the tool keeps
the final say**. We never force a column choice; when a value spans offer levels we *suggest*
the most granular and flag the alternative.

The business rules below therefore live in **both** places: as firm rules in the model
instructions (the tool enforces them) and as supportive hints from the sub-agent.

1. **Offer hierarchy priority + transparency.** A term is resolved to the most granular level
   that contains it: **Product › Solution › SolutionLine › sirano_product**. "IP" is a
   SolutionLine; "IPL"/"Roaming Sponsor" are Products. When a value exists at several levels
   (e.g. *IP Transit*/*EVPL* are both a Product and a Solution) the most granular (Product) is
   used **and disclosed** ("…also exists as a Solution - tell me if you meant that level").
   - **The semantic model owns this decision** (it has the layer + the hierarchy rules in
     `sqlGenerationConfig.instructions` + `commercial_offer` description, incl. *never default
     to sirano_product*). The Playground proved Sonnet resolves these correctly on its own.
   - **The sub-agent does NOT pin a column for an ambiguous offer term** - it only flags
     `AMBIGUOUS OFFER TERM - "EVPL" is present in (Product, Solution, sirano_product); YOU
     resolve it`, and leaves the choice to the model. (Regression that motivated this: the
     sub-agent's `column_priority` fell back to `-distinct_count`, so it pinned
     `sirano_product = 'EVPL'` - and BUDGET rows have no sirano_product → budget = 0.)
     Confident single-column values (e.g. a customer name) are still suggested as typo-free
     hints. A neutral disclosure note (`build_disclosure_notes`) lists the ambiguity.

2. **Customer identity: display name + carrier_code, diamond_id discreet.** `diamond_id` is
   the master key (kept in `GROUP BY` for exactness) but means nothing to the business - we
   lead with **Account_name + carrier_code** and keep diamond_id as the **last, de-emphasized**
   column.
   - Model: customer-grouping rule in the instructions + canonical pattern.
   - Sub-agent: `axis_sentence` now supports a `display_columns` list (profile override on
     `diamond_id` below) → `GROUP BY diamond_id, MAX(Account_name), MAX(carrier_code)`,
     diamond_id last.
   - ⚠️ `MAX(carrier_code)` picks one code if a customer has several - acceptable per the
     business (name + carrier identify an account); revisit if a customer spans many codes.

3. **Account_partner & Parent_Group.** `Account_partner` = the reseller in an **indirect**
   deal (we sell to Airbus, who resells to Maroc Telecom → end customer = Maroc Telecom,
   partner = Airbus). `Parent_Group` is **not** used unless explicitly asked. Both documented
   in the instructions and the attribute descriptions.

### Incoherences fixed in the model

- `Phase = 'ACTUAL'` → **`'ACTUALS'`** in the `revenue_record` description, the `Phase`
  attribute, and the **`Actual Revenue Only` filter** (which was matching **zero rows**).
- Removed the **bogus `diamond_id` glossary term** (it described `original_dataset` / lineage
  and collided with the real *Diamond ID*).
- Removed the **`roaming hub` synonym** from *Roaming Sponsor* (Roaming Hub is a Solution).
- Golden queries: **no self-join** (all 3 entities map to one physical table), name +
  carrier_code display, diamond_id last; added Product-priority, named-customer, indirect and
  per-partner examples.
- YTD aligned to "latest available reporting month" (no hardcoded "today" → no partial month).
- Instructions now state **one physical table, never JOIN**.

## Two scripts

- `build_aligned_semantic_model.py` - **one-time CREATE** of the new model (reads the old
  model read-only, applies all corrections, creates the new model + version, indexes).
- `update_aligned_semantic_model.py` - **MODIFY in place** an existing aligned model: refreshes
  the SQL-generation instructions + golden queries on its active version (no create, no
  re-index). Use this for every prompt / golden-query iteration once the model exists. Set
  `NEW_MODEL_ID` first. (`NEW_INSTRUCTIONS` / `GOLDEN_QUERIES` are kept byte-identical in both
  files - edit them in `update_…` going forward.)

## Deployment - do it in this order

1. **Build the new model.** Open `build_aligned_semantic_model.py` in a **Dataiku notebook**
   (project OWISMIND_DEV). STEP 1 opens the old model **READ-ONLY** (`get_raw()` on a deep
   copy - it never calls `save()` / `set_active` / `delete` on the old handle, so the old
   model is 100 % untouched) to start from the exact current config, prints the diff; review,
   then STEP 2 **creates a brand-new model** (`create_semantic_model`) + version v1, and
   STEP 3 indexes it. **Write down the new model id** it prints.

2. **Test in the new model's Playground** with: a Product also a Solution (*IP Transit*),
   "IP" at SolutionLine, "top customers" (check name + carrier_code, diamond_id last),
   indirect customers / per-partner, a named customer ("HALYS").

3. **Profile overrides for the sub-agent** - add these rows to the editable **overrides
   dataset** (INPUT 2 of the profile recipe, columns `key,field,value`) then **re-run the
   profile recipe** (`profile_dataset_recipe.py`, design-time, small/safe):

   | key            | field              | value                              | needed? |
   |----------------|--------------------|------------------------------------|---------|
   | diamond_id     | display_columns    | `["Account_name","carrier_code"]`  | recommended (reinforces name+carrier display) |
   | Product        | ambiguity_priority | `0`                                | optional now |
   | Solution       | ambiguity_priority | `1`                                | optional now |
   | SolutionLine   | ambiguity_priority | `2`                                | optional now |
   | sirano_product | ambiguity_priority | `3`                                | optional now |

   (`value` is JSON-parsed when possible; the recipe flags these `human_override` and they
   survive re-runs.) The `ambiguity_priority` rows are now **optional**: ambiguous offer terms
   are resolved by the semantic model, not by the sub-agent's `column_priority`. The
   `display_columns` row is a useful reinforcement of the name+carrier display, but the model
   instructions already enforce it. **The model instructions are the source of truth for all
   these rules** - re-running the recipe is no longer on the critical path.

4. **Point the tool at the new model.** The Semantic Model Query tool **`v4oqA6R`**
   (`revenue_semantic_query`, used by the sub-agent constant `SEMANTIC_TOOL_ID`) still targets
   the OLD model. Edit that tool's settings → select the **new** model. The model is unchanged
   in code, so no sub-agent code edit is needed. (Alternative: create a new tool and update
   `SEMANTIC_TOOL_ID` - but editing the existing tool is simpler.)

5. **Re-paste the sub-agent** `dataset_expert_langgraph.py` into its Code Agent
   (`agent:AKQaQ0Am`, env 3.11). The repo is the source of truth.

6. **Smoke-test end to end** in the webapp, then keep the OLD model as rollback (do NOT
   delete it).

## Rollback

- Tool → re-point to the old model. Sub-agent → the originals `*_agent.py` are untouched
  (the enhancements live only in `*_langgraph.py`); revert the profile overrides + re-run the
  recipe to drop the priority/display changes.
