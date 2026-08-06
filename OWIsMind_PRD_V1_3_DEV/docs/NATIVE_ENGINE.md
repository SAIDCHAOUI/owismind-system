# Native engine (in-backend orchestrator) - chantier B, 2026-08-06

## What it is

An alternative chat engine that runs the orchestration loop INSIDE the plugin
backend (`python-lib/owismind/agents/native_orchestrator.py`) through the LLM
Mesh completion API with tool calls (per the Dataiku developer guide:
`settings["tools"]`, `response.tool_calls`, `with_tool_calls`,
`with_tool_output`), instead of invoking the `OWIsMind_orchestrator` Code Agent.

- The existing Code Agents (revenue / tickets specialists) stay the SUB-agents:
  each enabled capability of the Config & Prompt Hub becomes one delegation
  tool, executed by streaming the sub-agent through the proven
  `streaming.run_agent_streamed` (Evidence capture, SQL surfacing and the
  timeline behave exactly as today).
- `show_chart` / `show_table` / `show_kpi` are executed natively by the backend
  (validation against the latest captured result + the frozen `artifact` event).
- The engine emits the exact same normalized event stream as the legacy path,
  so the worker, persistence and the frontend are untouched.

## Why

Direct access to everything the backend already knows (screen context, captured
results, run settings), no Code Agent re-paste cycle for orchestrator changes,
and a single place to iterate on orchestration behavior.

## How to enable (admin only, dual-path)

The engine is selected PER WHITELIST ENTRY by the admin profile flag
`native_engine` (strict bool, default OFF = the exact legacy Code Agent path):

1. In the webapp admin settings, edit the enabled agent entry and set
   `"native_engine": true` in its profile (the flag is sanitized by
   `security/validation.validate_agent_meta`).
2. The entry should also keep `"modes": true` so the mode dial + control tokens
   flow as usual (the native engine reads the route-resolved mode directly and
   strips every `owi:` token before any LLM call).
3. Rollback = flip the flag off. Nothing else changes.

## Configuration sources

| What | Source | Fallback |
|---|---|---|
| Capabilities (delegation tools, sub-agent ids) | `/python/owismind_hub/capabilities.json` read from the DSS project library (TTL cache 300 s) | `EMBEDDED_CAPABILITIES` (the two live specialists) |
| Mode -> model mapping | `LLM_BY_MODE` constant (mirror of the Code Agent CONFIG; change in lockstep, lesson L172/L173) | `smart` |
| Persona | `PERSONA` constant (honesty firewall + output contract, self-contained) | n/a |

## Bounds (instance safety)

`MAX_LLM_TURNS = 8` model iterations (the last one runs WITHOUT tools so the
model must conclude in text), `MAX_SUBAGENT_CALLS = 4` specialist rounds,
`MAX_ARTIFACTS = 6`, bounded task/tool-output strings. Every specialist call is
individually caught: one failing sub-agent degrades to an honest tool error,
never a dead run. The worker's per-mode wall-clock deadline and cooperative
stop apply unchanged.

## Validation checklist (DSS)

1. Enable the flag on a TEST entry (not the live orchestrator entry) pointing at
   the same project.
2. Smoke: one revenue question (delegation + Evidence SQL + chart), one tickets
   question, one follow-up using the on-screen context, one out-of-scope
   question (honest refusal, no invented figure).
3. Check `/evidence/meta` renders the chart/table artifacts and that the stored
   trace has `engine: "native"`.
4. Compare token usage vs the legacy path (the usage_summary aggregates the
   sub-agent footers plus the loop's own usage when the Mesh response exposes it).

## Known limitations (v1, reviewed 2026-08-06)

- **No `recall_prior_result` tool yet**: the route disables the prior-results
  recall block for native runs (`prior_recall_enabled` gate), so the model is
  never invited to call a tool it does not have. Backlog: implement recall
  natively.
- **Artifacts bind to the ACTIVE result when `sql_id` is absent**: the raw
  specialist trace does not tag sql_id (only the legacy Code Agent orchestrator
  does), so with TWO specialists in one turn all artifacts read the latest
  result. Degradation is honest (chart_payload refuses unknown columns - a
  missing chart, never a wrong one).
- **`durable_workflow` + `native_engine` on the same entry**: the /chat/start
  route takes the durable branch BEFORE engine selection, so planned turns run
  the legacy Code Agent and simple turns run the native engine. Do not combine
  the two flags until this is deliberate.
- **Delegation context** passes MODE + USER LANGUAGE + the user's raw current
  message (bounded); the legacy orchestrator also hands over the previous
  assistant message. Extend if disambiguation quality lags in DSS validation.

## Tests

`tests/test_native_orchestrator.py` (29 tests, DSS-free): tool specs, mode/lang
LAST-valid-token parsing (forgery guard), the PRODUCTION captured-result shape
(`{columns, rows, truncated}` - no `captured` key), artifact validation against
the frozen shape, hub fallback + duplicate tool_name guard, full-loop event
sequence, sqlIndex renumbering + enrichment, per-call capture notes, budgets,
failure paths. Engine selection + worker resilience (selection failure ends the
run cleanly): `tests/test_stream_manager_deadlines.py`.
