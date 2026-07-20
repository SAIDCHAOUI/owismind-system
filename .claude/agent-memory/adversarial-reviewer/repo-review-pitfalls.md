---
name: repo-review-pitfalls
description: Recurring verification points and gotchas when adversarially reviewing OWIsMind diffs
metadata:
  type: project
---

Durable checks for OWIsMind adversarial reviews.

**Read-only SQL guard consolidation.** `storage/sql_config.readonly_pre_queries()` is the single
source of truth for the two transaction pre-queries every dataset READ runs under:
`["SET LOCAL statement_timeout TO '30000'", "SET LOCAL transaction_read_only TO on"]` (in that
order, fresh list per call). Sites: evidence/service, evidence/source_service (via import), storage/
{artifacts,budget,settings,suggestions}, benchmark_view/lab_io. WRITE paths use only the timeout
(`_WRITE_TIMEOUT_PRE_QUERY`), never read-only. When reviewing a "consolidation", confirm each
converted site previously held EXACTLY those two strings in order.

**Prod = clone of DEV (no promotion script).** As of 2026-07-10 the DSS prod project `OWISMIND_PRD_V1_2`
is a CLONE of DEV (ids preserved, tickets expert INCLUDED), mirrored under `OWIsMind_PRD_V1_3_DEV/`. The old
`tools/promote_agents_to_prod.py` script and the separate `OWISMIND_PROD_V1` twin are LEGACY, DELETED:
there is no longer a DEV->PROD id substitution / tickets-block removal pass to verify. Map of real DSS
ids: `OWIsMind_PRD_V1_3_DEV/README.md` + `OWIsMind_PRD_V1_3_DEV/registry.json`.

**Agent Code Agent files.** Module docstrings and `#` comments are NOT sent to the LLM (the prompt is a
separate string variable). Comment/docstring edits in `OWIsMind_PRD_V1_3_DEV/GenAI/Agents/OWIsMind_orchestrator.py` /
`SalesDrive_revenue_expert.py` / `CSSO_Trouble_Tickets_Expert.py` / `tools/` / `flow/` recipe files are
behavior-neutral. `OWIsMind_PRD_V1_3_DEV/registry.json` has a `not_runtime` field: it is NOT imported at
runtime (CAPABILITIES is inlined in the orchestrator), so `last_reviewed` date bumps are harmless.

**Generated frontend assets.** `OWIsMind_PRD_V1_3_DEV/plugin/owismind/resource/owismind-app/` is build output (skip line-level
review). Sanity-check: body.html and index.html are byte-identical and reference exactly the hashed
asset files present in `resource/owismind-app/assets/`. Comment-only source changes still change the
bundle hashes (Vite strips comments) but not behavior.

**Rule #9 (banned dashes).** Repo forbids em dash U+2014 and en dash U+2013 everywhere. Scan added diff
lines with Python (test `chr(0x2014) in line` and `chr(0x2013) in line`), NOT BSD grep -P (fails
silently on this Mac). Right-arrow U+2192
is allowed.

**Baseline test counts (2026-07-06, snapshot):** backend 790, node 352, agents
316 (2 skipped), LAB 343. Commands: backend `python3 -m unittest discover -s tests` from
`OWIsMind_PRD_V1_3_DEV/plugin/owismind`; agents `... -s OWIsMind_PRD_V1_3_DEV/tests`; LAB `... -s OWIsMind_LAB/project-library/python
-t OWIsMind_LAB/project-library/python`; node `node --test test/*.test.js` from `OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend`.
Current prod branch: `OWIsMind_PRD_V1_2` (one branch per DSS prod version; `main` deprecated).
