I have complete grounding. Writing the architecture now.

---

# Agent Factory: turning the revenue agent into a template (mission 2)

The good news up front: your orchestrator is already ~95% data-driven and your sub-agent is already ~90% Profile-driven. The "factory" is mostly **consolidating the ~7 revenue constants behind config, exposing the prompt fragments as injectable blocks, and building one calibration harness** - not a rewrite. The hard, irreducible cost is human semantic curation (golden queries, alias jargon, scenario semantics). The factory's job is to make everything *around* that curation free, and to make the curation itself *fast and verifiable*. Below, the five deliverables.

---

## 1. The DECLARATIVE AGENT SPEC schema and where it lives

**(a) WHAT:** One JSON object per specialist that fully describes a domain so the orchestrator routes to it and the sub-agent code self-configures from it - zero per-agent code edits beyond a paste.

**(b) BUSINESS VALUE:** Account manager / product owner / executive: a new domain (tickets, billing, opportunities, CX) appears in the assistant in days, not a month; the orchestrator honestly says "no agent yet" until then (already wired via `BUSINESS_DOMAINS`).

**(c) TECHNICAL APPROACH - exact seams.** Your `CAPABILITIES` dict (orchestrator lines 195-247) is **already the spec for the orchestrator side**. The change is to (1) enrich each entry with the sub-agent's config and (2) decide the home. Recommendation: **single source of truth = a versioned `dataiku-agents/registry.json`, mirrored into `webapp_settings_v1.enabled_agents` only for the fields the admin UI legitimately edits** (label, description, icon/badge - already done by `validate_agent_meta`, `enabled`, `source_url`). Reason: the standalone Code Agent files cannot import the plugin (frozen constraint), and `enabled_agents` JSON is admin-mutable - you do NOT want a non-dev toggling `semantic_model_id` or `lookup_dataset` (rule #3/#4: front/admin never picks table/connection). So:

- **`registry.json`** = the dev-owned, repo-versioned full spec (the contract). It is the build input that **generates the `CAPABILITIES` literal pasted into the orchestrator** and the **config header pasted into each sub-agent file** (see §2B). Code agents read it at runtime *only* if you choose path 2A; otherwise it's a build-time template input.
- **`enabled_agents` JSON** = the runtime *operator surface*: `enabled` flag, editorial meta, `source_url`. The orchestrator already filters on `enabled`; extend `get_capabilities()` to overlay the operator JSON onto the static literal at load (it already reads via `dataiku.api_client`, so a read of `webapp_settings_v1` is safe and bounded).

**Spec fields (every field):**
```
key, domain, kind:"agent", agent_id, label_fr/en, tool_name,
planner_description,                      # routing signal (the ONLY thing the supervisor uses to route)
block_labels{}, tool_labels{},           # timeline (MUST mirror KNOWN_* - anti-drift test)
dataset_label_fr/en, source_url,
lookup_dataset, lookup_catalog, pass_context, enabled,
# --- sub-agent config (new, drives §2) ---
profile_dataset, value_index_dataset, target_dataset,
semantic_model_id, semantic_tool_id, semantic_tool_name,
persona_block{fr,en},                    # the per-domain PERSONA paragraph (see §3)
currency_default, scope_language:{scenario_label, period_label},
resolution_hierarchy[] (optional),       # ordered column priority for ambiguous terms (offer-hierarchy generalized)
golden_queries_dataset,
guardrails:{max_rows, read_only:true, allowed_tables[]}
```

**(d) EFFORT:** S-M. No install. The `get_capabilities()` overlay + a `dataiku-agents/registry.json` + a tiny `gen_capabilities.py` codegen are a day.

**(e) RISK/charter/security:** Keep the **server-side whitelist invariant**: the front sends a logical key, never `agent_id`/table. `allowed_tables` + `lookup_dataset` stay dev-owned in `registry.json`, never admin-editable. Re-run the existing anti-drift test (`block_labels`/`tool_labels` ↔ `KNOWN_BLOCK_IDS`/`KNOWN_TOOL_NAMES`) per new agent.

**(f) DEPENDENCIES:** Foundation for everything below. Phase 1.

---

## 2. The SHARED SPECIALIST TEMPLATE (resolving the standalone-file constraint)

**(b) VALUE:** Every persona benefits indirectly: one engine fixed once propagates to all domains; no per-domain divergence of the UNDERSTAND→RESOLVE→QUERY→RENDER pipeline.

**(c) The trade-off - two paths:**

- **Path A - packaged base module in the 3.11 env.** Build `owismind_specialist` as a real Python package installed into the 3.11 code env (the env that already has langgraph). Each sub-agent file becomes a thin shim: `from owismind_specialist import build_specialist; AGENT = build_specialist(SPEC)`. One source of truth, true DRY.
  - *Cost:* **requires the user to install** the package into the 3.11 env (rule #1: agent never installs - the plan must say "user installs `owismind_specialist` into the 3.11 code env"). It also *partially breaks* the "standalone paste" property: a paste is no longer self-sufficient; the env must carry the lib. And it's a new release/version-pinning surface (lib bumps must be coordinated with pasted agents).

- **Path B - codegen from one canonical template + marked-duplication.** Keep `SalesDrive_revenue_expert.py` as the **canonical engine**; extract the per-domain bits to the top config header (already 90% there). A build script `gen_specialist.py` reads `registry.json` + the canonical engine and emits `dataiku-agents/agents/<Agent>.py` with the ~7 constants, `persona_block`, `resolution_hierarchy`, and the frozen `KNOWN_*`/`AGENT_RESULT`/span-shape blocks injected. The engine body is **byte-identical** across files; only a clearly-marked `# === GENERATED CONFIG (do not edit) ===` header differs.

**Recommendation: Path B.** It honors the standalone constraint absolutely (each file remains a complete paste, no env coupling, instant rollback), needs **no install**, and keeps DSS deployment exactly as today (paste two files). The single-source-of-truth property is preserved *by construction*: the engine lives once in the canonical file; `gen_specialist.py` is a deterministic stamping pass, and a CI test asserts `engine-body(generated) == engine-body(canonical)` (diff only inside the CONFIG header). You get DRY's real benefit (one place to fix the pipeline) without DRY's coupling cost. Path A is the right *eventual* move once you have 5+ agents and the install ceremony amortizes - but YAGNI now.

**Keeping UNDERSTAND→RESOLVE→QUERY→RENDER as one truth:** these nodes are already fully Profile-driven (`build_understand_prompt` generated from Profile, RESOLVE on `VALUE_INDEX_DATASET`, `build_semantic_question`, `format_cell`/`metric_unit`). They reference only `PROFILE_DATASET`, `VALUE_INDEX_DATASET`, `SEMANTIC_TOOL_*`, `TARGET_DATASET` - all in the config header. So codegen touches *only the header*; the four nodes never change per domain.

**(d) EFFORT:** M for `gen_specialist.py` + the "engine-body identical" CI test. No install (Path B).

**(e) RISK:** The frozen contracts (`KNOWN_BLOCK_IDS`, `KNOWN_TOOL_NAMES`, `AGENT_RESULT` keys, `semantic-model-query` span `{sql,success,row_count,rows,columns,source_url}`, Profile v1) must be **identical in every generated file** - they are part of the engine body, not the config, so codegen never varies them. Add an assertion test.

**(f) DEPENDENCIES:** Needs §1 (registry). Phase 2.

---

## 3. Genericizing the revenue-specific bits

**(c) Exact targets and the fix for each:**

- **PERSONA (orchestrator lines 1031-1107).** Split into a **domain-neutral spine** (WHO/VOICE/LANGUAGE/HONESTY/OUTPUT-CONTRACT/SCREEN - all already generic) plus a **per-domain injected block**. Today "MONEY, NUMBERS & TRANSPARENCY" hardcodes `€`, EUR, ACTUALS/BUDGET/FORECAST. Generalize: `build_system_prompt` already concatenates `cap_lines`; add a **"# DATA DISCIPLINE PER DOMAIN"** section assembled from each enabled cap's `scope_language` + `currency_default`. For revenue it renders today's euro/scenario text; for tickets it renders "state CSAT scale and the time window; resolution time in hours". The transparency *mechanism* (specialist prefixes `[Scope]/[Périmètre]`) is already domain-neutral - keep it; only the *example words* move into the spec.

- **Offer-hierarchy fragment (sub-agent `build_semantic_question` lines 1607-1617, `defer_multicolumn_offer_terms`).** This is already generic *machinery* ("a term spanning ≥2 columns is deferred") - only the *guidance string* ("Product, then Solution… never sirano_product") is revenue-specific. Replace the hardcoded guidance with `SPEC.resolution_hierarchy` (ordered list of column names + a "never default to <last>" note). When the list is empty (most domains have no offer hierarchy) the deferral still fires generically and the prompt simply says "resolve using your semantic-model rules". `defer_multicolumn_offer_terms` itself is unchanged - it's already profile-driven via `column_priority`.

- **`LOOKUP_SOURCE_CAP="revenue_expert"` (orchestrator line 172).** Already half-generic via `lookup_domains()`. Drop the constant; the lookup built-in already resolves dataset/catalog/source_url *per domain* from the registry. The one remaining hardcode (`agent_key=LOOKUP_SOURCE_CAP` fallback) becomes the resolved `cap_key` from `lookup_domains()` - the code at line 1351 already does `info.get("cap_key")`, so just remove the constant fallback.

- **Currency/scope language.** `metric_unit` already derives currency from the column name (`amount_eur→€`, `_CURRENCY_BY_CODE`) - fully generic, keep as-is. The only hardcode is the PERSONA's "Amounts are euros (EUR) unless the data says otherwise"; move that default to `SPEC.currency_default`.

**(b) VALUE / (d) EFFORT:** S-M, no install - these are surgical string-to-spec moves. **(e) RISK:** none structural; the mechanisms already exist. **(f):** Phase 2, alongside §2.

---

## 4. The CALIBRATION-COMPRESSION harness (5 sessions → 2)

**(a) WHAT:** A Python-3.9 `unittest` golden-query EX (execution-accuracy) regression suite, auto-seeded from the profile, plus a self-check/critic node in the pipeline.

**(b) VALUE:** Executive/product owner: trust. A domain ships only when its golden suite is green; regressions are caught before deploy, not by a user seeing a wrong revenue number (the disengagement risk you flagged).

**(c) APPROACH, grounded:**
- **Auto-seed candidates** from the profile: a `seed_golden_queries.py` reads `<ds>_profile` (metrics, scenario col+values, groupable axes+enums) and emits ~30-50 candidate `(question, expected_filters, expected_intent)` rows - exactly the structured questions the pipeline already understands. *Automatable.* The human only *picks and confirms expected results* (the irreducible curation).
- **Storage:** `<ds>_golden_queries` dataset (JSONL: `question, lang, expected_intent, expected_filters, expected_value_or_rowcount, tolerance`). Lives in DSS so it's curated next to the data.
- **The test (no install):** a `unittest` case per domain runs the **UNDERSTAND + RESOLVE** nodes offline (deterministic, no LLM needed for structured questions because UNDERSTAND uses `with_json_output` and RESOLVE is pure SQL on the value_index) and asserts `intent` + `resolved filters` match. This is the **cheap, no-LLM, CI-able 80%** - it catches profile/value-index drift, the exact failure that cost you the EVPL=budget-0 bug. For the value-accuracy 20%, an opt-in `--live` flag runs the full QUERY against the semantic tool and reconciles the number (gated, off-peak, instance-safe).
- **Self-check/critic node:** add an optional `node_critic` after QUERY (LangGraph `should_continue`, **zero extra LLM on the happy path**): if `rowcount==0` or all-null on a structured intent, re-RESOLVE once with relaxed matching before answering. Pure Python guard; respects the honesty firewall (empty is a valid answer, never invented).
- **Claim-vs-result reconciliation** (your P0 governance item) doubles as a calibration signal: every number in the narrative must appear in the captured `generated_sql[].result` (regex pass, 3.9). Run it inside the harness to score answers.

**How this compresses 5→2:** session 1 was *discovering* the failure modes (scenario summing, sirano default, alias jargon) by hand. With the harness, the auto-seeded suite surfaces those failures *immediately and reproducibly*; the human spends their two sessions only on (a) confirming golden expected values against real data and (b) writing the 5-10 business aliases (`BUSINESS_ALIASES`) and scenario/exclusion rules - the genuinely irreducible curation. Everything mechanical (profile pass, value_index, candidate questions, regression scaffold) is free.

**(d) EFFORT:** M. No install (`unittest` + stdlib only; lazy-import pandas per L089). **(e) RISK/instance-safety:** the no-LLM tier is free; the `--live` tier must run as a scheduled off-peak scenario (recipes do full-table pandas scans - 2M-row cap risk). **(f):** Phase 3; depends on §1-§2.

---

## 5. The "ADD A NEW AGENT" playbook (automatable vs human-curated)

For a new domain `tickets` (dataset `OWISMIND_DEV_support_tickets`):

1. **Run the 3 Flow recipes** (profiler → value_index → value_catalog), config = INPUT/OUTPUT at top. *Automatable* (scheduled off-peak). Human: nothing, except `BUSINESS_ALIASES` jargon (**human-curated**).
2. **Create the DSS semantic model** (entities on the one table, named filters, glossary). *Semi-automatable*: `build_aligned_semantic_model.py` scaffolds entities/filters from the profile; **human-curated**: golden queries, scenario/exclusion semantics, scope language. This is the slow part - the harness (§4) makes it verifiable.
3. **Add the `registry.json` spec entry** (§1) - `domain:tickets`, `profile_dataset`, `value_index_dataset`, `semantic_tool_id`, `persona_block`, `resolution_hierarchy` (often empty), `enabled:false` until green. *Automatable* (template entry).
4. **Run `gen_specialist.py`** (§2B) → produces `agents/Tickets_expert.py` (engine identical, header stamped). *Automatable*. Run `gen_capabilities.py` → updated `CAPABILITIES` literal for the orchestrator. *Automatable*.
5. **Seed + curate golden queries** (§4): `seed_golden_queries.py` emits candidates; **human confirms expected values** against real data. Run the no-LLM `unittest` suite → must be green.
6. **Paste the 2 files into DSS** (the new Code Agent in env 3.11 + re-paste the orchestrator with the new `CAPABILITIES`), set `enabled:true` in `enabled_agents`. *Human action* (DSS paste - the standalone constraint is honored). No backend zip/restart unless python-lib changed.
7. **Smoke-test** via orchestrator (it routes by `planner_description` automatically - no routing code touched, point 2/3 of your verified findings).

**Net:** steps 1, 3, 4, 7 are automatable; steps 2 and 5 carry the irreducible human curation; step 6 is a mechanical paste. The factory removes all code work; what remains is *semantic curation*, now bounded and test-gated.

---

**Phasing:** Phase 1 = registry spec + `get_capabilities()` overlay + codegen scaffolds (§1). Phase 2 = genericize PERSONA/offer-hierarchy/lookup/currency + `gen_specialist.py` with engine-identity CI test (§2B, §3). Phase 3 = calibration harness + critic node + reconciliation (§4). Then onboard a *second simple domain* (opportunities or a cut-down tickets) end-to-end as the proof, refining the harness from real friction. Do NOT build Path A (packaged lib), MCP, dynamic hot-reload, or semantic-similarity routing now - YAGNI; the literal-paste + tool-description routing you already have scales to ~15 agents.

**Files/contracts to touch (precise):** `OWIsMind_orchestrator.py` (`CAPABILITIES`, `get_capabilities`, `build_system_prompt`/`PERSONA`, `lookup_domains`, drop `LOOKUP_SOURCE_CAP`); `SalesDrive_revenue_expert.py` config header + `build_semantic_question` offer fragment + `defer_multicolumn_offer_terms` guidance; new `dataiku-agents/registry.json`, `tools/factory/gen_specialist.py`, `gen_capabilities.py`, `seed_golden_queries.py`; new `tests/test_golden_<domain>.py`. **Frozen, never varied by codegen:** `KNOWN_BLOCK_IDS`, `KNOWN_TOOL_NAMES`, `AGENT_RESULT` keys, `semantic-model-query` span shape, Profile v1, event kinds, `CAPABILITIES` keys + `tool_name`.