# ADR-0007 - with_json_output forced on UNDERSTAND

> Audience: Agents engineer. Last updated: 2026-06-18. Summary: why the sub-agent forces
> `with_json_output` on its deterministic extraction step (UNDERSTAND) while the orchestrator NEVER
> does (in DSS 14, forcing JSON silently disables the model's reasoning).

## Status

Accepted and validated in DSS (lesson L056: "everything works"). The rule is carved into the agents folder
contract: "with_json_output is FORCED on the sub-agent's UNDERSTAND (deterministic extraction) and NEVER on
the orchestrator (it disables reasoning in DSS 14)" (`dataiku-agents/CLAUDE.md`, section "Rules you must
not break", point 5).

## Context and problem

The revenue expert sub-agent (`SalesDrive_revenue_expert`) begins each turn with an UNDERSTAND step:
extracting a structured object from the user question (scope, intent, metric, period, group_by, terms to
resolve, optional clarification). This object is consumed by CODE, not by a human: the function
`validate_understanding` (in `SalesDrive_revenue_expert.py`) parses it, validates it against the profile, then
the RESOLVE -> QUERY -> RENDER pipeline relies on it.

In an earlier version, this step ran at `reasoning effort=high` WITHOUT forcing JSON output. The observed
symptom (L056): the model "thought" for roughly 15 seconds, then returned prose text that the parser could
not read. `validate_understanding` then returned `None`, and the `n_understand` node short-circuited the
entire pipeline by emitting `INTERNAL_ERROR_TEXT` and setting `{"done": True}`, BEFORE any SQL. Concretely:
an internal error was displayed to the user instead of an answer, without a single analytical query ever
being attempted.

The underlying observation: a deterministic extraction does not need to "think". Reasoning consumed token
budget and latency for nothing, and worse, it made the parse fragile. The need for reasoning lies elsewhere:
in the REAL decisions (the orchestrator's tool-calling routing) and in verified prose (the headline).

## Decision

Two symmetric rules, one for the sub-agent, the other for the orchestrator.

### 1. Force JSON on UNDERSTAND (sub-agent)

The UNDERSTAND call goes through the sub-agent's `_call_json_llm` method. It proceeds in two attempts, in
this order:

| Attempt | Mode | Behavior |
|---|---|---|
| 1 | `use_json_mode=True` | calls `completion.with_json_output(schema=...)` then `execute()`: clean JSON, reliable parse. In DSS 14 this mode disables reasoning FOR THIS CALL, which is exactly the intended effect. |
| 2 | `use_json_mode=False` | prompt-only fallback: if the model or the connection refuses native JSON mode, the call falls back to a plain completion where the prompt alone requests the JSON (the least reliable on small models). |

The JSON schema is built by `build_understand_schema(profile)`: its enums are anchored on the profile
(known intents, available `Phase` scenarios, `fr`/`en` languages), so the model cannot invent an
out-of-domain value. The comment in `_call_json_llm` sums up the intent:

```python
"""2 attempts: native JSON mode (with_json_output) then prompt-only.

UNDERSTAND is a deterministic extraction (scope / intent / terms), not a
reasoning task, so forcing the JSON schema is what makes it reliable. Forced
JSON disables the model's reasoning for this call only, which is what we want
here: a clean, fast parse instead of a long 'thinking' pass that returns prose
the parser cannot read. Reasoning stays on where it helps (the orchestrator's
routing, the verified headline)."""
```

Important operational point: if `with_json_output` raises an exception (JSON mode unavailable on the
model/connection), we do not degrade silently. We record the cause in `span.attributes
["json_mode_unavailable"]` and log a warning, BEFORE falling back to the prompt-only parse.

### 2. NEVER force JSON on the orchestrator

The orchestrator (`OWIsMind_orchestrator`) calls the model natively via Mesh (`new_completion()` /
`execute()` / `execute_streamed()`) so that both reasoning AND tool-calling are honored. It does not call
`with_json_output` anywhere: the only occurrence of that name in the file is the header comment that
explicitly FORBIDS it:

```text
# We NEVER force a native JSON output (with_json_output) on the orchestrator -
# in DSS 14 that silently disables reasoning. The model emits tool calls
# (function calling) and free text; reasoning stays on.
```

The orchestrator's model emits tool calls (function calling, therefore already structured by the tool's
contract) and free text. Reasoning stays active: it is what drives the routing to the right sub-agent and
the application of the honesty firewall.

## Rationale

The real rule hiding behind this ADR is general: `with_json_output` for ANY output consumed by code
(deterministic, fast, reliable), and reasoning reserved for decisions and prose. The distinction is not
"small model vs large model", it is "extraction vs decision".

- UNDERSTAND is an extraction: the code needs it in an exact, parseable form. Native JSON mode guarantees
  that form and avoids the pointless "thinking" pass that was breaking the parse.
- The orchestrator's routing is a decision: choosing the agent, deciding to route rather than to deny,
  formulating. Forcing it to JSON would break the reasoning (in DSS 14, native JSON mode disables it), and
  tool-calling already provides the structure needed to call a sub-agent or a built-in.

This split is consistent with ADR-0006 (native LLM Mesh calls): we keep reasoning and tool-calling native,
and we only enable forced JSON where it serves a purpose.

## Consequences

Positive:

- Validated in DSS: extraction becomes reliable and fast again, the internal error before SQL disappears (L056).
- Controlled cost: extraction no longer burns reasoning budget for nothing.
- Schema anchored on the profile: the model cannot produce an out-of-domain value on the enums.
- Defense in depth: if JSON mode is unavailable, we FLAG it (span + log) and keep a prompt-only fallback
  instead of crashing.

Negatives or points of attention:

- The extraction no longer "thinks" (intended: an extraction does not need to think).
- The prompt-only fallback (attempt 2) is the least reliable on small models; if native JSON mode becomes
  unavailable on the connection, robustness drops. This is traced, hence observable.
- The model for the UNDERSTAND call is driven by the mode (see ADR-0009): it is chosen via
  `pick_subagent_llm(mode)` and passed as `llm_id`. When no mode is forced (batch or autonomous run), the
  `UNDERSTAND_LLM_ID` fallback applies, which equals `LLM_BY_MODE[DEFAULT_MODE]` (therefore the eco model by
  default). The historical fallback cited by L056 was `vertex_ai/claude-sonnet-4-6`; today the code derives
  this fallback from the default mode. Detail confirmed in `SalesDrive_revenue_expert.py`.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Keep reasoning everywhere on UNDERSTAND | Burns the budget and breaks the parse (prose text unreadable by the code): this was precisely the original bug (L056). |
| Force `with_json_output` on the orchestrator (to structure its decisions) | In DSS 14, native JSON mode silently disables reasoning, which is indispensable to routing and the honesty firewall. Tool-calling already provides the structure. |
| Parse prose freely (no JSON, no schema) | This is the starting state that was failing: no guarantee of form, hence a fragile parse and `validate_understanding -> None`. |

## See also

- [ADR-0006 - Native LLM Mesh calls in the nodes](0006-appels-natifs-llm-mesh.md) - the technical
  context (reasoning + tool-calling preserved) on which this ADR builds.
- [ADR-0009 - Per-mode models](0009-modeles-par-mode.md) - how the model for the UNDERSTAND call is
  chosen (`pick_subagent_llm`, `UNDERSTAND_LLM_ID`, `DEFAULT_MODE`).
- [ADR-0005 - LangGraph Code Agents in Python 3.11](0005-langgraph-code-agents-python-311.md) - the runtime
  of the two Code Agents concerned.
- [Models, prompts and LLM Mesh](../05-agents/06-models-prompts-and-llm-mesh.md) - the detailed reference
  (modes, `with_json_output`, native calls, control tokens).
- [The revenue expert sub-agent](../05-agents/03-revenue-expert-subagent.md) - the UNDERSTAND ->
  RESOLVE -> QUERY -> RENDER pipeline this call belongs to.
- [The orchestrator](../05-agents/02-orchestrator.md) - the routing loop where reasoning must stay
  active.
- [ADR index](README.md) - the complete list of architecture decisions.
