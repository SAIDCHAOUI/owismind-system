---
name: factory-hub-loader-review
description: Review points for the v1.3 agent factory + Config/Prompt Hub loaders in the 3 agents
metadata:
  type: project
---

Durable checks for the v1.3 agent factory (`OWIsMind_PRD_V1_2/project-library/python/owismind_factory/`,
`webapps/agent-factory-console/`, hub loaders in `agents/`).

**Two capability validators that must agree but DON'T (found 2026-07-10).** There are TWO validators
for a hub `capabilities.json` entry:
- factory `owismind_factory.hub.validate_capabilities`: block_labels/tool_labels must be a dict IF
  present (any keys) OR None. Guards isinstance BEFORE `.keys()`, never crashes.
- orchestrator `_hub_capabilities_problems` (inlined in `agents/OWIsMind_orchestrator.py`, standalone-file
  rule): requires block_labels keys == EXACTLY `_HUB_KNOWN_BLOCK_IDS`, tool_labels == `_HUB_KNOWN_TOOL_NAMES`,
  and does `set((cap.get("block_labels") or {}).keys())` -> CRASHES (AttributeError) on a non-dict truthy
  (e.g. block_labels as a JSON array).
Consequences: (1) `_load_hub_capabilities` does NOT wrap `_hub_capabilities_problems` in try/except, and
the module-level `_hub_capabilities = _load_hub_capabilities()` is bare -> a hand-edited hub with
block_labels as an array aborts the agent import (agent won't start). Violates the "any exception ->
silent fallback" contract. (2) block_labels=None or dict-with-wrong-keys passes the factory validator
(so the console `/api/hub/capabilities` POST writes it and reports OK) but the orchestrator rejects the
WHOLE file and falls back to embedded defaults, silently ignoring the operator's hub (only an agent-side
`logger.warning`). The anti-drift test `tests/test_factory_registry.py` claims validators are "in sync"
but only compares the CONSTANT tuples (`_HUB_REQUIRED_CAPABILITY_KEYS`, KNOWN ids), never runs the
orchestrator's validation logic - so it does not guard this divergence.

**Method that works here.** The orchestrator can't be imported DSS-free (needs dataiku/langgraph). To
test its hub loaders on the REAL code, AST-extract the functions/consts (`_hub_read_text`,
`_hub_capabilities_problems`, `_load_hub_capabilities`, `_HUB_*`) with `ast.parse` + compile a synthetic
Module, stub `logger`/`json`/`_hub_read_text`, and exec. See [[verifying-zero-behavior-cleanup]] for the
AST approach.

**Factory dry-run safety pattern (verified clean 2026-07-10).** Every mutating DSS call in
flow_builder/semantic_builder/tool_builder/agent_builder/align/pipeline is inside a closure passed to
`FactoryContext.act(step, detail, fn)`; in dry_run `fn` is never called. `remap_raw` in align.py is pure
(doesn't mutate its input; the mutation is in the `_save` closure). The ONLY deletions in the whole
package are `probes.run_write_probes` deleting the `zz_factory_probe`/`zz_factory_probe_tool` it created,
gated by `allow=True` (default False), in `finally` only if created. `run_read_probes` is read-only.
The console backend gates every mutating route on `{"confirm": true}` (`/api/plan` is dry_run-only, no
confirm needed); jobs registry guarded by `_JOBS_LOCK` + GIL for the `list(ctx.actions)` copy.

**Test dry-run harness is honest.** `test_factory_core.py::_FakeProject` exposes only read-only listing
methods; every mutating `project.*` (and get-by-id) raises, so a mutation moved outside `act` fails the
`TestPipelineDryRun` test. But it only exercises the default `steps=None` / no-wizard / no-discovery path.
