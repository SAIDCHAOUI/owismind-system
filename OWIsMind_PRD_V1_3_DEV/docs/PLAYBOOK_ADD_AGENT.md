# PLAYBOOK - add a specialist sub-agent (worked for: tickets)

> **Environment (2026-07):** this is the repo mirror of the DSS **production**
> project `OWIsMind_PRD_V1_2` (key `OWISMIND_PRD_V1_2`), a **clone of DEV** with the
> DEV ids preserved. The **tickets** domain is therefore already INCLUDED in prod by
> the duplication (Code Agent, semantic model, and tool all present); the only
> remaining tickets work is to **launch the repoint script + finish curation** (see
> section A and the "Still pending" note in `../CLAUDE.md`).
>
> **How a NEW domain lands in prod.** There is no "develop in a second DSS project
> then promote" step anymore. Build the new specialist on the **next dev branch**
> (`OWIsMind_PRD_V1_3-dev`), validate it in the DSS clone, then promote by **dropping
> the `-dev` suffix**: the validated dev branch becomes the new prod branch and the
> next version starts (git model: `../README.md`, section "Regle de version git").
>
> The concrete, ordered runbook below takes a new domain from a base dataset to a
> live specialist routed by the orchestrator. The architecture is built for this:
> the sub-agent engine is dataset-agnostic (its expertise lives in the Flow recipes
> + the semantic model, not the code), and the orchestrator is registry-driven
> (adding a domain is one CAPABILITIES entry). The repo source of truth for the spec
> is [`../registry.json`](../registry.json); columns are in [`../flow/DATASETS.md`](../flow/DATASETS.md).
>
> Legend: **[repo]** = done in this repo (already done for tickets, see below).
> **[DSS]** = you do it on the instance. **[curate]** = the irreducible human
> data work. NO INSTALL anywhere. Read-only SQL, off-peak recipes.

---

## A. What is ALREADY done in the repo for tickets

These are committed; you do NOT need to write code. Because prod is a clone of DEV,
the tickets objects already EXIST in the DSS clone too: the steps below are the
remaining **repoint + curation**, not a from-scratch build.

- `../GenAI/Agents/CSSO_Trouble_Tickets_Expert.py` - the tickets sub-agent (same engine as
  revenue, CONFIG header pointed at the tickets datasets; `SEMANTIC_TOOL_ID` already
  set to `nEirlso`; `FALLBACK_TO_DIRECT=True` so it works from the profile even
  before the model is fully wired).
- `../GenAI/Agents/OWIsMind_orchestrator.py` - the `tickets_expert` CAPABILITIES entry
  (routing, timeline labels, lookup dataset + search allowlist), with `agent_id`
  already set to `agent:NcE9LD2i`.
- `../GenAI/agents-tools/attribute_lookup_tool.py` - accepts a per-domain `searchable_columns`
  allowlist (the orchestrator passes the tickets one server-side), and surfaces the
  generic catalog's `value`-domain rows as "did you mean" suggestions.
- `../flow/CSC_ticket_AI_Agent_zone/python-recipes/compute_TroubleTickets_year_value_catalogue.py` (and the
  profile + value_index recipes) - auto-IO + NA-safe + dataset-adaptive (revenue
  keeps its curated catalog; any other dataset gets a generic per-value catalog).
- `../GenAI/semantic-models/scripts/update_tickets_semantic_model.py` (brain) +
  `../GenAI/semantic-models/scripts/dump_semantic_model.py` (generic snapshot, TICKETS
  CONFIG) + `../GenAI/semantic-models/scripts/repoint_tickets_prod_clone.py` (repoints the
  tickets model `dM4jA4G` to the clone dataset; READY, simulated 4/4, NOT YET
  LAUNCHED on the clone).
- `registry.json` + `../flow/DATASETS.md` - the spec + column inventory.
- Tests are green: `python3 -m unittest discover -s OWIsMind_PRD_V1_3_DEV/tests`.

---

## B. The deploy order (DSS)

### 1. [DSS] Flow - build the three knowledge datasets

Wire the SAME recipes (no code edit; they read INPUT/OUTPUT from the recipe API):

- `../flow/CSC_ticket_AI_Agent_zone/python-recipes/compute_TroubleTickets_year_profile.py`: INPUT `TroubleTickets_year` (+ optional
  INPUT 2 `TroubleTickets_year_profile_overrides`, an editable `{key,field,value}`
  dataset) -> OUTPUT `TroubleTickets_year_profile`.
- `../flow/CSC_ticket_AI_Agent_zone/python-recipes/compute_TroubleTickets_year_value_index.py`: INPUT `TroubleTickets_year` -> OUTPUT
  `TroubleTickets_year_value_index` **on the `SQL_owi` connection** (the sub-agent
  queries it in live SQL). Optionally set, at the top of the recipe run:
  ```
  INCLUDE_COLUMNS = ["ticketType","priority","origin","category","CurrentStatus",
                     "problemCategory","Product","Account_name",
                     "CustomerRepresentative_Name"]
  EXCLUDE_COLUMNS = ["CurrentStatus_Reason","ticketEntry","id","Customer_id",
                     "Service_id","Service_Specification_id","Service_id_1"]
  ```
  (The auto-selector would mostly do this anyway; the explicit lists are
  deterministic.)
- `TroubleTickets_year_value_catalogue`: `../flow/CSC_ticket_AI_Agent_zone/python-recipes/compute_TroubleTickets_year_value_catalogue.py` (now
  auto-IO + NA-safe + dataset-adaptive). On a non-revenue dataset it builds a
  GENERIC catalog of each categorical text column's distinct values
  (search_domain "value"), which feeds the orchestrator lookup's "did you mean"
  fallback for tickets. Optional but recommended for consistency; the sub-agent
  does not read it (it grounds on profile + value_index), so it can come later.

Run these as a **scheduled scenario, off-peak** (never from the webapp UI). 83,738
rows is small; no OOM risk. The three recipes auto-detect INPUT/OUTPUT from the
Flow wiring (no hardcoded dataset names) and are NA-safe.

### 2. [curate] Pin the profile overrides (overrides dataset)

**FIRST, re-run the profile recipe.** `profile_dataset_recipe.py` now DERIVES the
`indexed` flag from the value-index rule (`should_index_value_column`), so
groundable columns (Account_name, the enums, etc.) are advertised to UNDERSTAND and
RESOLVE can match named entities. This is mandatory: if `indexed` is empty, the
UNDERSTAND prompt says "labels of: (none)", the model never extracts a customer name
as a term, grounding is skipped and the SQL writer GUESSES the value (the
"Algerie Telecom" -> fabricated name bug). Re-running the recipe fixes it; no manual
`indexed` override is needed anymore (overrides still win if you want to force one).

The profile recipe infers metrics/axes generically; tickets still need a few human
overrides (they always win). In `TroubleTickets_year_profile_overrides` set:

**a) COUNT(DISTINCT id) default metric.** Each ticket id appears on SEVERAL rows
(historical snapshots: an update adds a new row, old rows are kept). `COUNT(*)`
over-counts updated tickets, so the count must be `COUNT(DISTINCT id)`:

- `key=__dataset__`, `field=metrics`, `value=` a JSON array including
  `{"name":"ticket_count","agg":"COUNT_DISTINCT","column":"id","format":"count","label_en":"Ticket count","label_fr":"Nombre de tickets"}`
  and
  `{"name":"avg_duration","agg":"AVG","column":"Duration_ticket_total","format":"number","label_en":"Average resolution time (minutes)","label_fr":"Duree moyenne de resolution (minutes)"}`.
- `key=__dataset__`, `field=default_metric`, `value=ticket_count`.

`agg=COUNT_DISTINCT` makes `metric_expr` emit `COUNT(DISTINCT "id")` in the
sub-agent's compose hint and direct-SQL fallback. Do NOT give any tickets metric
`format:"amount"` and do NOT name a column `*_eur/_usd` (that would make the engine
infer a phantom currency). `Duration_ticket_total` is in MINUTES - keep it in the
label.

**b) Default time axis = `creationDate`.** The profiler elects the first date
column alphabetically (`Latest_Closed_Date`), which is wrong. Force creation:

- `key=__dataset__`, `field=time`, `value={"column":"creationDate","format":"date"}`.

**c) Display Account_name for the customer id.** So a per-customer breakdown groups
by the stable key and shows the human label, id de-emphasized:

- `key=Customer_id`, `field=display_column`, `value=Account_name`.

**d) LD synonyms on `Service_id_1`** (the dominant lookup key) so the UNDERSTAND
model maps "LD" to the right column:

- `key=Service_id_1`, `field=synonyms`, `value=["LD","ld","ligne","line"]`.

### 3. [curate] Review the profile

Open `TroubleTickets_year_profile` and check the LLM-written column descriptions,
synonyms and enums (especially `CurrentStatus`, `priority`, `category`,
`problemCategory`). Fix anything wrong via the overrides dataset (it always wins).
The exact `CurrentStatus` open/closed values surface here and in the value index.

### 4. [DSS] Create the tickets semantic model

- In DSS, create a semantic model on `TroubleTickets_year` (the UI auto-discovers
  entities/attributes from the schema, with valid shapes). Name it
  `TroubleTickets_Semantic_Model`. Let it index distinct values once.
- [curate] Run `../GenAI/semantic-models/scripts/update_tickets_semantic_model.py` in a notebook
  (set `NEW_MODEL_ID`) to inject the tickets instructions + golden queries + the
  entity / attribute descriptions + the metrics (`COUNT(DISTINCT id)`). The
  duration unit (minutes) is already baked in; only the exact `CurrentStatus`
  open/closed values are data-dependent (read them from the value index, the
  instructions already tell the model to use the exact catalog values). Optionally
  add named filters / glossary synonyms in the model UI.
- Snapshot it: run `../GenAI/semantic-models/scripts/dump_semantic_model.py` with the TICKETS config
  (see its CONFIG comment) and commit `TroubleTickets_Semantic_Model.v1.json`.

### 5. [DSS] Create the tickets Semantic Model Query tool

Create a NEW agent tool of type **Semantic Model Query** bound to
`TroubleTickets_Semantic_Model`: **Agent mode OFF** (linear pipeline), LLM
`vertex_ai/claude-sonnet-4-6`, access datasets as the calling user. Note its id.
Paste the **Description for LLM** from
`../GenAI/semantic-models/TOOL_DESCRIPTIONS.md` (the `tickets_semantic_query` block) into the
tool's "Description for LLM" field - do NOT leave it empty.

- Confirm that id matches `SEMANTIC_TOOL_ID` (already set to `nEirlso`) in
  `../GenAI/Agents/CSSO_Trouble_Tickets_Expert.py`; update
  it if the DSS tool id differs.
- Keep `registry.json` -> `tickets_expert.semantic_model.tool_id` in sync.

### 6. [DSS] Create the tickets Code Agent + wire the orchestrator

- Create a new **Code Agent** on the **Python 3.11** code env; paste
  `../GenAI/Agents/CSSO_Trouble_Tickets_Expert.py`. Confirm
  its `agent:` id matches `CAPABILITIES["tickets_expert"]["agent_id"]` (already set
  to `agent:NcE9LD2i`) in
  `../GenAI/Agents/OWIsMind_orchestrator.py` and in
  `registry.json`; update all three if the DSS id differs.
- **ORDER MATTERS**: the real `agent_id` must be live (Code Agent created) BEFORE
  re-pasting the orchestrator. `tickets_expert` ships `enabled:True` with the id
  `agent:NcE9LD2i`; if you re-paste the orchestrator while that Code Agent does not
  exist yet, tickets questions get a graceful technical-error reply (not a crash)
  instead of an honest "no agent yet". If you must paste early, set
  `"enabled": False` on `tickets_expert` first (the `tickets` domain stays in
  `BUSINESS_DOMAINS`, so the orchestrator gives the honest capability-gap reply),
  then flip it back to `True` once the Code Agent is live.
- **Re-paste the orchestrator** (Python 3.11) so it learns `ask_tickets_expert`
  and the second lookup domain. Re-paste the **revenue** sub-agent only if you also
  changed it (you did not).
- If you also changed `python-lib` (you did NOT this session), upload the zip +
  restart the backend. **Agent-only changes need no zip.**

### 7. [DSS] Smoke-test through the orchestrator

Ask in the webapp (the orchestrator routes by `planner_description`, no routing
code touched):

- "How many tickets per priority?" -> tickets specialist, count breakdown.
- "Top 10 customers by number of tickets in 2025" -> GROUP BY Customer_id, display
  Account_name, id last.
- "Average resolution time by category" -> AVG(Duration_ticket_total) with the
  unit stated.
- "What does the tickets data contain?" -> about_data card, zero SQL.
- "Is there a customer named <X>?" -> fast `attribute_lookup` on the tickets
  allowlist (Account_name etc.), not the long prose columns.
- A revenue question still routes to the revenue expert (unchanged).
- (Later) "360 on account <X>" -> the orchestrator fans out revenue + tickets in
  parallel for the same account (`Account_name` is the bridge).

---

## C. Generic checklist (the same shape for the next domain)

1. [DSS] Flow: `profile_dataset_recipe` + `build_value_index_recipe` on the new
   base dataset -> `<base>_profile` + `<base>_value_index` (on `SQL_owi`).
2. [curate] Overrides for the default metric + review the profile.
3. [DSS] Create the semantic model (UI) + inject the brain via an `update_*`
   script + snapshot via a `dump_*` script.
4. [DSS] Create its Semantic Model Query tool (Agent OFF, Sonnet).
5. [repo] Copy `SalesDrive_revenue_expert.py` -> `../GenAI/Agents/<Domain>_expert.py`, swap
   the CONFIG header (datasets + semantic tool id/name), neutralize any
   revenue-specific prompt wording (`build_semantic_question`), keep the engine
   body and all frozen contracts byte-identical.
6. [repo] Add one `CAPABILITIES` entry (copy `revenue_expert`; set domain, ids,
   labels, `lookup_dataset`, `lookup_search_columns`). Add it to `registry.json`
   and a `DATASETS.md` section. The anti-drift test loops all enabled caps, so it
   covers the new agent automatically.
7. [DSS] New Code Agent (3.11) + re-paste the orchestrator. Smoke-test.

The factory makes the CODE free; the **curation** (metric, golden queries, exact
status/scenario values, synonyms) is the real per-domain work, and the test suite
+ this playbook make it bounded and repeatable.
