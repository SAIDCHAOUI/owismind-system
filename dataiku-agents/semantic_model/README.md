# Semantic model — aligned rebuild (2026-06-15)

Goal: make the **semantic model** (SQL generator) and the **Dataset Expert sub-agent**
fully complementary and ultra-precise, and fix the incoherences found in the live `v4`
config. The old model (`2O2KcHw` / `Drive_Revenues_Model`) is **never touched** — we build a
**brand-new model** from a read-only copy of its active version.

## What changed and why

### Philosophy: the sub-agent ASSISTS, it does not DICTATE

The Semantic Model Query tool runs on a **smart model (Sonnet 4.6) WITH the semantic layer**,
so it understands the dataset far better than our small UNDERSTAND model. The sub-agent
therefore sends the tool the **user's real question (source of truth)** plus **HINTS**: the
intent shape, the values/columns its grounding helper matched in the live catalog, the
preferred presentation, scenario and period. Hints are **help, not orders — the tool keeps
the final say**. We never force a column choice; when a value spans offer levels we *suggest*
the most granular and flag the alternative.

The business rules below therefore live in **both** places: as firm rules in the model
instructions (the tool enforces them) and as supportive hints from the sub-agent.

1. **Offer hierarchy priority + transparency.** A term is resolved to the most granular level
   that contains it: **Product › Solution › SolutionLine › sirano_product**. "IP" is a
   SolutionLine; "IPL"/"Roaming Sponsor" are Products. When a value exists at several levels
   (e.g. *IP Transit* is both a Product and a Solution) we filter the most granular (Product)
   **and disclose it** ("…also exists as a Solution — tell me if you meant that level").
   - Model: `sqlGenerationConfig.instructions` + `commercial_offer` description.
   - Sub-agent: `column_priority` (driven by the `ambiguity_priority` profile overrides
     below — sirano_product has the most distinct values, so the default `distinct_count`
     heuristic would wrongly prefer it) + a deterministic disclosure note in RENDER
     (`build_disclosure_notes`, `refine_ambiguous` now records `alt_columns`).

2. **Customer identity: display name + carrier_code, diamond_id discreet.** `diamond_id` is
   the master key (kept in `GROUP BY` for exactness) but means nothing to the business — we
   lead with **Account_name + carrier_code** and keep diamond_id as the **last, de-emphasized**
   column.
   - Model: customer-grouping rule in the instructions + canonical pattern.
   - Sub-agent: `axis_sentence` now supports a `display_columns` list (profile override on
     `diamond_id` below) → `GROUP BY diamond_id, MAX(Account_name), MAX(carrier_code)`,
     diamond_id last.
   - ⚠️ `MAX(carrier_code)` picks one code if a customer has several — acceptable per the
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

## Deployment — do it in this order

1. **Build the new model.** Open `build_aligned_semantic_model.py` in a **Dataiku notebook**
   (project OWISMIND_DEV). STEP 1 opens the old model **READ-ONLY** (`get_raw()` on a deep
   copy — it never calls `save()` / `set_active` / `delete` on the old handle, so the old
   model is 100 % untouched) to start from the exact current config, prints the diff; review,
   then STEP 2 **creates a brand-new model** (`create_semantic_model`) + version v1, and
   STEP 3 indexes it. **Write down the new model id** it prints.

2. **Test in the new model's Playground** with: a Product also a Solution (*IP Transit*),
   "IP" at SolutionLine, "top customers" (check name + carrier_code, diamond_id last),
   indirect customers / per-partner, a named customer ("HALYS").

3. **Profile overrides for the sub-agent** — add these rows to the editable **overrides
   dataset** (INPUT 2 of the profile recipe, columns `key,field,value`) then **re-run the
   profile recipe** (`profile_dataset_recipe.py`, design-time, small/safe):

   | key            | field              | value                              |
   |----------------|--------------------|------------------------------------|
   | diamond_id     | display_columns    | `["Account_name","carrier_code"]`  |
   | Product        | ambiguity_priority | `0`                                |
   | Solution       | ambiguity_priority | `1`                                |
   | SolutionLine   | ambiguity_priority | `2`                                |
   | sirano_product | ambiguity_priority | `3`                                |

   (`value` is JSON-parsed when possible; the recipe flags these `human_override` and they
   survive re-runs.)

4. **Point the tool at the new model.** The Semantic Model Query tool **`v4oqA6R`**
   (`revenue_semantic_query`, used by the sub-agent constant `SEMANTIC_TOOL_ID`) still targets
   the OLD model. Edit that tool's settings → select the **new** model. The model is unchanged
   in code, so no sub-agent code edit is needed. (Alternative: create a new tool and update
   `SEMANTIC_TOOL_ID` — but editing the existing tool is simpler.)

5. **Re-paste the sub-agent** `dataset_expert_langgraph.py` into its Code Agent
   (`agent:AKQaQ0Am`, env 3.11). The repo is the source of truth.

6. **Smoke-test end to end** in the webapp, then keep the OLD model as rollback (do NOT
   delete it).

## Rollback

- Tool → re-point to the old model. Sub-agent → the originals `*_agent.py` are untouched
  (the enhancements live only in `*_langgraph.py`); revert the profile overrides + re-run the
  recipe to drop the priority/display changes.
