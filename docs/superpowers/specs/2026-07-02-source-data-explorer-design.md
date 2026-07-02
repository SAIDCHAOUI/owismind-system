# Source Data Explorer - design (2026-07-02, approved by user)

Goal: users can explore the RAW datasets an agent relies on, BEFORE prompting (New
Conversation empty screen) and AFTER an answer (Evidence Studio), so prompts get precise
and the agent guesses less.

## Admin config
- `validate_agent_meta` gains a `sources` block: bounded list (max 8) of
  `{dataset, label}` (dataset = project SQL dataset name, label sanitized, per-locale not
  required - single label). Stored in the `enabled_agents` JSON (webapp_settings_v1), same
  pattern as the `benchmark` block. Admin UI: in the agent profile modal, pick datasets
  from the project's discovered SQL datasets (reuse evidence discovery) + editable label.

## API (server resolves everything; front never names tables - rules #3/#4)
- `/agents` exposes per agent: `sources: [{id, label}]` (id = stable index/slug).
- New read-only routes (mirror Evidence guards: parametrized SQL, `transaction_read_only`,
  `statement_timeout`, row/filter caps, all users incl. impersonation READ):
  - `source/meta` (agent key + source id -> columns)
  - `source/rows` (chips filters + NEW `q` global search + offset pagination, cap 500/page)
  - `source/distinct` (chip value picker)
- Global search `q`: case-insensitive AND accent-insensitive - ILIKE on
  `concat_ws(...)` of all columns with `translate()` accent folding at query time (same
  pattern as the agents' attribute_lookup tool; data untouched).

## Frontend (charte Orange, rule #10)
- New `SourceExplorer` component: one tab per configured dataset (admin labels) + global
  search bar + per-column filter chips (reuse `EvidenceChips`) + infinite-scroll table
  (reuse existing explore table mechanics).
- New Conversation empty screen: prominent button "Explore the data this agent uses"
  (hidden when the picker's agent has no sources). Click -> prompt zone slides left,
  panel opens right (same grid mechanics as Evidence panel).
- Evidence Studio: new top-level tab "Source data" hosting the same `SourceExplorer`;
  the current "Explore source data" section MOVES out of the Evidence tab into it.
  Fallback: agent without configured sources -> tab shows the exchange's detected
  tables (current behavior preserved).

## Non-goals
- No write path, no generic SQL route, no per-user source config, no export.

## Safety net
- Backend unittest (sources block validation, agent+id -> table resolution, `q` SQL,
  guards) + frontend node:test (pure models) + Vite build + DEV zip only (prod intact).
- Deploy: upload DEV zip + restart backend. No agent re-paste (plugin-only feature).
