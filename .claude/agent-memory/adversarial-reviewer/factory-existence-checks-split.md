---
name: factory-existence-checks-split
description: owismind_factory has FIVE existence-check helpers across 3 modules; the 2026-07-12 hardening only fixed 3 of them
metadata:
  type: project
---

The factory package has five "does X already exist?" helpers, and they do NOT all
share the same error contract.

- `flow_builder.dataset_exists / recipe_exists / scenario_exists`: hardened
  2026-07-12 to raise `ExistenceCheckError` on a listing API failure (callers
  record FAILED and skip creation).
- `tool_builder.tool_exists` and `agent_builder.agent_exists`: STILL
  `except Exception: pass; return None`. On a transient `list_agent_tools()` /
  `list_agents()` failure they return None, and their callers
  (`create_semantic_query_tool_like`, the agent creator) then proceed to CREATE a
  duplicate object. Same idempotency bug the wave removed for datasets/recipes.

**Why:** requirement "existence checks never treat an API error as absent" was
only partially met; the two agent/tool checks were left behind.
**How to apply:** when reviewing any factory "existence check hardening" claim,
enumerate ALL FIVE helpers, not just the flow_builder three. Related:
[[security-invariants]], [[repo-review-pitfalls]].
