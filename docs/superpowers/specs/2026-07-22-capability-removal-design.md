# Capability removal and disable - design (approved 2026-07-22)

> User approved approach A (a second guided run type inside the existing guided
> machine) after brainstorming. Two user decisions recorded during design:
> (1) the SOURCE dataset is NEVER touched by removal (only factory-derived
> artifacts are deletable); (2) the two founder domains (revenue, tickets) are
> disablable AND removable like any other capability: the orchestrator becomes
> the durable core and every capability around it can be built, improved and
> removed through the console. Branch: `OWIsMind_PRD_V1_3-dev`.

## 1. Goal

Give the factory console the reverse of "create a domain": the operator can
either DISABLE a capability (detach it from the orchestrator, keep the whole
architecture, re-enable later in one click) or REMOVE it completely (delete the
derived datasets, recipes, refresh scenario, semantic model, semantic query
tool, Code Agent, hub entries and shared-catalog rows). Removal is a delicate,
irreversible operation: every deletion is shown to the operator (what, id,
where) and confirmed one by one BEFORE it runs, then VERIFIED by read-back
after it runs. Nothing unverified ever advances the run.

## 2. Context (what exists and is reused)

- `guided.py` is a persistent step-by-step state machine (SQL-persisted runs,
  auto/manual stages, verify-before-advance, resume after reload). The console
  frontend renders `state.stage_order` dynamically and already asks a modal
  confirmation before launching EVERY stage: per-deletion confirmation is
  native, no stepper change needed.
- `probes.py` already deletes probe agents and probe tools through the public
  API with a safety pattern: re-read the handle, verify the object name matches
  the expectation, only then `delete()`. Programmatic deletion of Code Agents
  and agent tools is therefore PROVEN on this instance, and the safe-delete
  pattern exists to be reused.
- `hub.py` owns `capabilities.json` with an automatic backup before every
  write; the `enabled` flag per capability is the official rollback lever.
- `capabilities.json` + `registry.json` (founders) carry the ids and names
  needed to build a probe-based inventory without trusting naming conventions.

## 3. UX entry points (overview screen)

Each capability card in the console overview gains two actions:

1. **Disable / Re-enable** (immediate, no run): writes `enabled: false/true`
   in `capabilities.json` (automatic backup). The UI reminds the operator of
   the hot-hub gotcha (L168): re-save the orchestrator in DSS, then open a new
   conversation, for the registry to reload. Architecture fully preserved.
2. **Remove domain** (guided run): opens a confirmation dialog where the
   operator must TYPE the domain name, then starts a guided run of type
   `removal`. Same machine, same SQL persistence, same resume semantics as the
   creation run. Only one guided run may be active at a time (existing guard).

## 4. The removal machine

A new `run_type: "removal"` on the run dict (creation runs keep working
unchanged; absent field means creation). Its own `stage_order`:

| # | Stage | Kind | What it does |
|---|-------|------|--------------|
| 1 | `inventory` | auto | Probe what ACTUALLY exists: capability entry + `registry.json` (founders) + per-object existence checks (datasets, recipes, scenario, model, tool, agent, hub files, catalog rows). Persist the inventory in run state; feed every later stage's card so the operator sees "what, id, where" BEFORE confirming. The source dataset never appears in the deletable inventory. |
| 2 | `disable` | auto | Set `enabled: false` (idempotent): the orchestrator stops routing to the expert before anything is deleted. |
| 3 | `delete_tool` | auto | Delete the Semantic Model Query tool (safe-delete pattern). |
| 4 | `delete_agent` | auto | Delete the Code Agent (safe-delete pattern). |
| 5 | `delete_model` | auto | Delete the semantic model. |
| 6 | `delete_scenario` | auto | Delete the refresh scenario. |
| 7 | `delete_recipes` | auto | Delete the 3 knowledge recipes. |
| 8 | `delete_datasets` | auto | Delete the 3 knowledge datasets WITH drop of their derived SQL tables. The SOURCE dataset is never listed nor touched. |
| 9 | `delete_zone` | auto | Delete the Flow zone ONLY if it is now empty; otherwise leave it and journal why (e.g. the source dataset still lives there). |
| 10 | `catalog_cleanup` | auto | Parametrized SQL DELETE of this capability's rows in the shared catalog dataset + COMMIT. |
| 11 | `hub_cleanup` | auto | Remove the wizard config, `prompts/<domain>/`, the generated agent file, then the `capabilities.json` entry (with backup). |
| 12 | `final_check` | auto | Re-probe the absence of everything, summarize, remind the operator to re-save the orchestrator (hot registry, L168). |

Stage protocol per deletion stage: card lists the exact objects from the
inventory -> operator clicks "Lancer" + modal confirm (existing UX) ->
execute -> VERIFY disappearance by read-back -> journal. A failed verification
marks the stage `failed` and never advances.

**Manual fallback**: if the API refuses a deletion (rights, unsupported
object), the stage flips to manual: exact French instructions to delete the
object in DSS, the operator clicks "C'est fait", and the stage verifies the
ABSENCE against DSS before advancing (same discipline as creation manual
stages).

## 5. Safety rails

- Never two deletions without a confirmation in between (one stage = one
  confirmed family of objects).
- Identity check before every `delete()` (probes pattern: re-read, compare
  name, refuse on mismatch).
- Refuse to start a removal run if the domain's refresh scenario is running or
  another guided run is active.
- **Template guard**: founder objects may serve as factory templates
  (`template_semantic_tool_id`, `template_semantic_model_id`,
  `template_zone_recipes` all point at revenue objects today). Removing a
  domain whose objects are referenced as templates is allowed (user decision)
  but must be explicitly acknowledged: when the guard fires, the `inventory`
  stage returns the WAITING outcome (existing status `waiting_user`) with
  instructions explaining that the factory cannot create new domains until the
  templates are repointed in `factory_settings.json`; the operator clicks
  "C'est fait" to acknowledge and the run advances. No new status needed.
- Deletions are idempotent on retry: an already-absent object is verified
  absent and journaled, not re-deleted, so a failed run can be relaunched.
- `heal_interrupted` covers removal runs (a stage left `running` by a backend
  restart is healed like creation stages).
- The removal run stays in the guided store history (who removed what, when).

## 6. Error handling

A DSS error during a deletion marks the stage `failed` with the surfaced DSS
detail, relaunchable. Partial states are safe by construction: the order above
detaches the capability first (disable), then deletes leaves before trunks
(tool/agent/model before recipes/datasets before zone), so an interrupted run
never leaves the orchestrator routing to a half-deleted expert.

## 7. Scope of changes

- `owismind_factory/guided.py`: removal stage order + stage handlers + meta;
  `new_state` variant for removal; `heal_interrupted` awareness; run_type.
- New `owismind_factory/removal.py` for inventory probing and safe deletion
  helpers (the `probes.py` read-back-verify-delete pattern is extracted into a
  shared helper and reused, not duplicated).
- `hub.py`: disable/enable helper + capability entry removal (both with the
  existing backup discipline).
- Console `backend.py`: routes to disable/enable a capability and to start a
  removal run (typed-name check server-side too); existing run/verify/current
  routes reused as-is.
- Console `script.js` + `style.css`: overview card actions, typed-name
  confirmation dialog, removal run reuses the existing guided panel. French
  texts, Orange charter for any styling.
- Frontend contract FROZEN: no new stage status, no new event kind.

## 8. Testing

DSS-free unit tests in the existing style (fake project / fake store):

- `test_factory_guided.py` additions: removal stage order and meta, inventory
  probing (found vs absent objects, source dataset exclusion, template guard),
  safe-delete identity refusal, verify-absence semantics, manual fallback
  flip, idempotent retry, heal of an interrupted removal run.
- `test_console_guided.py` additions: disable/enable routes, start-removal
  route (typed-name mismatch rejected, active-run guard), run/verify passthrough
  for a removal run.
- Frontend: compile check via the existing build; no stepper logic change.

## 9. Out of scope

- Deleting the SOURCE dataset or any base business data (user decision).
- Deleting the orchestrator itself.
- The durable hot-hub reload fix (TTL per conversation, L168 backlog) stays a
  separate change; this feature only reminds the operator to re-save.
- Editing/improving an existing capability (mentioned by the user as the
  longer-term vision; separate design when it comes).
