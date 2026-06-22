# PLAYBOOK - add a specialist sub-agent (worked for: tickets)

> **Per-project layout (2026-06-22, L099):** agent files now live under
> `OWISMIND/OWISMIND_DEV/` (develop here) and `OWISMIND/OWISMIND_PROD_V1/` (promote
> here), prefixed with the project key, with per-project ids. Build a new specialist
> in **DEV** first; once validated, promote it to PROD with the PROD ids. Id map +
> workflow: [`OWISMIND/README.md`](OWISMIND/README.md). Below, read `registry.json`
> as the **DEV** project's `OWISMIND/OWISMIND_DEV/registry.json`.
>
> The concrete, ordered runbook to take a new domain from a base dataset to a live
> specialist routed by the orchestrator. The architecture is built for this: the
> sub-agent engine is dataset-agnostic (its expertise lives in the Flow recipes +
> the semantic model, not the code), and the orchestrator is registry-driven
> (adding a domain is one CAPABILITIES entry). The repo source of truth for the
> per-domain spec is [`registry.json`](registry.json); columns are in
> [`DATASETS.md`](DATASETS.md).
>
> Legend: **[repo]** = done in this repo (already done for tickets, see below).
> **[DSS]** = you do it on the instance. **[curate]** = the irreducible human
> data work. NO INSTALL anywhere. Read-only SQL, off-peak recipes.

---

## A. What is ALREADY done in the repo for tickets

These are committed; you do NOT need to write code. Re-paste / run them in DSS per
the steps below.

- `agents/TroubleTickets_expert.py` - the tickets sub-agent (same engine as
  revenue, CONFIG header pointed at the tickets datasets; `SEMANTIC_TOOL_ID` is a
  placeholder to fill in step 5; `FALLBACK_TO_DIRECT=True` so it works from the
  profile even before the model is wired).
- `agents/OWIsMind_orchestrator.py` - the `tickets_expert` CAPABILITIES entry
  (routing, timeline labels, lookup dataset + search allowlist). Fill `agent_id`
  in step 6.
- `tools/attribute_lookup_tool.py` - now accepts a per-domain `searchable_columns`
  allowlist (the orchestrator passes the tickets one server-side), and surfaces the
  generic catalog's `value`-domain rows as "did you mean" suggestions.
- `recipes/build_value_catalog_recipe.py` - now auto-IO + NA-safe +
  dataset-adaptive (revenue keeps its curated catalog; any other dataset gets a
  generic per-value catalog). The profile + value_index recipes are also NA-safe.
- `semantic_model/update_tickets_semantic_model.py` (brain) +
  `semantic_model/dump_semantic_model.py` (generic snapshot, TICKETS CONFIG).
- `registry.json` + `DATASETS.md` - the spec + column inventory.
- Tests are green: `python3 -m unittest discover -s dataiku-agents/tests`.

---

## B. The deploy order (DSS)

### 1. [DSS] Flow - build the three knowledge datasets

Wire the SAME recipes (no code edit; they read INPUT/OUTPUT from the recipe API):

- `recipes/profile_dataset_recipe.py`: INPUT `TroubleTickets_year` (+ optional
  INPUT 2 `TroubleTickets_year_profile_overrides`, an editable `{key,field,value}`
  dataset) -> OUTPUT `TroubleTickets_year_profile`.
- `recipes/build_value_index_recipe.py`: INPUT `TroubleTickets_year` -> OUTPUT
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
- `TroubleTickets_year_value_catalogue`: `build_value_catalog_recipe.py` (now
  auto-IO + NA-safe + dataset-adaptive). On a non-revenue dataset it builds a
  GENERIC catalog of each categorical text column's distinct values
  (search_domain "value"), which feeds the orchestrator lookup's "did you mean"
  fallback for tickets. Optional but recommended for consistency; the sub-agent
  does not read it (it grounds on profile + value_index), so it can come later.

Run these as a **scheduled scenario, off-peak** (never from the webapp UI). 83,738
rows is small; no OOM risk. The three recipes auto-detect INPUT/OUTPUT from the
Flow wiring (no hardcoded dataset names) and are NA-safe.

### 2. [curate] Pin the profile overrides (overrides dataset)

The profile recipe infers metrics/axes generically; tickets need a few human
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
- [curate] Run `semantic_model/update_tickets_semantic_model.py` in a notebook
  (set `NEW_MODEL_ID`) to inject the tickets instructions + golden queries + the
  entity / attribute descriptions + the metrics (`COUNT(DISTINCT id)`). The
  duration unit (minutes) is already baked in; only the exact `CurrentStatus`
  open/closed values are data-dependent (read them from the value index, the
  instructions already tell the model to use the exact catalog values). Optionally
  add named filters / glossary synonyms in the model UI.
- Snapshot it: run `semantic_model/dump_semantic_model.py` with the TICKETS config
  (see its CONFIG comment) and commit `TroubleTickets_Semantic_Model.v1.json`.

### 5. [DSS] Create the tickets Semantic Model Query tool

Create a NEW agent tool of type **Semantic Model Query** bound to
`TroubleTickets_Semantic_Model`: **Agent mode OFF** (linear pipeline), LLM
`vertex_ai/claude-sonnet-4-6`, access datasets as the calling user. Note its id.

- Put that id in `agents/TroubleTickets_expert.py` -> `SEMANTIC_TOOL_ID`
  (replace `TODO_TICKETS_SEMANTIC_TOOL_ID`).
- Update `registry.json` -> `tickets_expert.semantic_model.tool_id`.

### 6. [DSS] Create the tickets Code Agent + wire the orchestrator

- Create a new **Code Agent** on the **Python 3.11** code env; paste
  `agents/TroubleTickets_expert.py`. Note its `agent:` id.
- Put that id in `agents/OWIsMind_orchestrator.py` -> `CAPABILITIES["tickets_expert"]["agent_id"]`
  (replace `agent:TODO_TICKETS`) and in `registry.json`.
- **ORDER MATTERS**: fill the real `agent_id` (and create the Code Agent) BEFORE
  re-pasting the orchestrator. `tickets_expert` ships `enabled:True` with a
  placeholder id; if you re-paste the orchestrator while the id is still
  `agent:TODO_TICKETS` and the Code Agent does not exist yet, tickets questions
  get a graceful technical-error reply (not a crash) instead of an honest
  "no agent yet". If you must paste early, set `"enabled": False` on
  `tickets_expert` first (the `tickets` domain stays in `BUSINESS_DOMAINS`, so the
  orchestrator gives the honest capability-gap reply), then flip it back to `True`
  once the id is real.
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
5. [repo] Copy `SalesDrive_revenue_expert.py` -> `agents/<Domain>_expert.py`, swap
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
