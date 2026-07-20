# ADR-0006 - Native LLM Mesh calls inside nodes

> Audience: agent engineer. Last updated: 2026-06-18. Summary: why the two LangGraph Code Agents
> call models, sub-agents and DSS tools in NATIVE LLM Mesh mode (`new_completion()`,
> `execute_streamed()`, `get_agent_tool(id).run()`), never through `as_langchain_chat_model`, in order to
> preserve reasoning and tool-calling.

## Status

Accepted and validated in DSS. The two Code Agents run on the instance with this pattern (proof: a DSS
log shows LangGraph executing on the Python 3.11 Code Agent). See lesson L055 in the project memory. This
ADR is closely tied to [ADR-0005](0005-langgraph-code-agents-python-311.md) (the LangGraph / Python
3.11 choice) and to [ADR-0007](0007-json-output-force-sur-understand.md) (`with_json_output` on UNDERSTAND):
together, the three describe the LLM integration discipline of the agents.

## Context and problem

OWIsMind is built on two LangGraph Code Agents (Python 3.11 env): the orchestrator
`OWIsMind_orchestrator` (`dataiku-agents/agents/OWIsMind_orchestrator.py`) and the revenue expert
sub-agent `SalesDrive_revenue_expert` (`dataiku-agents/agents/SalesDrive_revenue_expert.py`,
`agent:bHrWLyOL`). Each one needs two simultaneous capabilities that the business cannot afford to lose:

- **reasoning**: the orchestrator must reason about the question to route it to the right sub-agent
  and decide what to present (chart, table, kpi); the sub-agent's verified headline also relies on the
  model's reasoning.
- **tool-calling** (function calling): the orchestrator exposes tools to the model (`ask_<capability>`,
  `show_chart`, `show_table`, `current_date`, plus the attribute lookup described below); the entire loop
  turn consists of alternating tool calls and text.

The design question is therefore: through which path does a LangGraph node talk to the model? LangChain
offers an adapter, `as_langchain_chat_model()`, which wraps a Mesh model in a standard LangChain ChatModel
interface. The catch: this adapter normalizes the exchange to the LangChain format and, in doing so,
**loses the Mesh's native reasoning and tool-calling**. An orchestrator deprived of those two capabilities
can no longer route reliably nor drive its tools.

## Decision

In all (synchronous) nodes of the two Code Agents, calls to the model, sub-agents and DSS
tools are made in **NATIVE LLM Mesh** mode, never through `as_langchain_chat_model`. Concretely:

| Need | Native Mesh call used | Where (file) |
|---|---|---|
| Call a model (agentic loop, extraction, prose) | `project.get_llm(llm_id).new_completion()` then `.execute()` | both agents (`LoopChat._fresh`, `_call_json_llm`, `_llm_text`) |
| Stream a sub-agent from the orchestrator | `project.get_llm(agent_id).new_completion()` then `.execute_streamed()` | `OWIsMind_orchestrator.py`, method `_consume_subagent` |
| Call a managed DSS tool | `project.get_agent_tool(tool_id).run({key: value})` | sub-agent (semantic tool) and orchestrator (lookup) |

The header of the orchestrator file freezes this rule in black and white:

```python
#   - The LLM is called via the NATIVE LLM Mesh completion API (new_completion)
#     so that the model's REASONING is honored (configure reasoning effort ON the
#     model in the LLM Mesh connection when the model supports it). We NEVER force
#     a native JSON output (with_json_output) on the orchestrator - in DSS 14 that
#     silently disables reasoning.
```

### The orchestrator's agentic loop

The heart of the orchestrator is the `LoopChat` class (`OWIsMind_orchestrator.py`). It materializes the
conversation as an ordered list of operations (`("msg", ...)`, `("calls", ...)`, `("out", ...)`)
replayed on a FRESH completion via `new_completion()`. The tool calls and tool outputs are attached
by the native methods `with_tool_calls(...)` and `with_tool_output(...)`, which preserves the exact
`tool_call -> tool_output` pairing (a broken pairing triggers a 400 on the Mesh side on Claude/Vertex).
This is precisely the transcript contract that the LangChain adapter does not expose as such.

The model that drives the entire turn is chosen by the user mode (`pick_loop_llm(mode)`), with no
escalation and no model change mid-turn: eco uses `GEMINI_FLASH_LITE_ID`, medium
`GEMINI_FLASH_ID`, high `SONNET_ID` (see [ADR-0009](0009-modeles-par-mode.md) for the detail of the modes).

### Streaming through a custom writer, not through an adapter

The live timeline is produced by the nodes that emit events via
`get_stream_writer()` from LangGraph, and the `process_stream` method drives
`graph.stream(initial, stream_mode="custom", ...)` then re-yields each emitted chunk. Key point proven in
DSS: `get_stream_writer()` is BROKEN in async mode on versions < 3.11, but works in a SYNCHRONOUS node
under Python 3.11. The nodes are therefore all synchronous, which fits naturally with the blocking Mesh
calls (`new_completion().execute()`). This is the second pillar of the decision: the pairing
"sync nodes + native Mesh calls" is what actually works on the instance, where the async LangChain
adapter would have hit the `get_stream_writer` bug.

### Sub-agent invocation

From the orchestrator, calling a sub-agent is NOT a special case: a sub-agent is a DSS agent
exposed in the Mesh, called like a model via `project.get_llm(agent_id).new_completion()` then
`execute_streamed()` (method `_consume_subagent`). The orchestrator consumes the sub-agent's stream, relays
its phase events (relabeled `SUB_AGENT_*`) and retrieves its trace footer, from which Evidence will extract
the generated SQL. This whole mechanism relies on native Mesh streaming; the LangChain adapter would give
neither the trace footer nor the fine-grained timeline events.

### DSS tool invocation

Managed DSS tools are called via `get_agent_tool(tool_id).run({...})`. On the sub-agent side, the only real
runtime tool in v3 is the Semantic Model Query tool `revenue_semantic_query` (`v4oqA6R`,
`SEMANTIC_TOOL_ID`), invoked by `tool.run({sem_key: semantic_question})`: it is the one that WRITES AND
EXECUTES the analytical SQL. Reading the SQL and the rows from the RETURN value of `run()` is what makes
Evidence capture deterministic (rather than guessing keys in a trace). The grounding of terms,
however, is not a tool: it is read-only inline SQL on the value index (see
[ADR-0010](0010-grounding-et-semantic-model.md)).

> IN FLUX: the attribute lookup tool `attribute_lookup` (`tools/attribute_lookup_tool.py`) was
> wired on 2026-06-18 as a built-in tool of the ORCHESTRATOR (board decision), also called natively
> via `get_agent_tool(...).run(...)` and dispatched inline in `node_tools` like `show_table` /
> `current_date`. Its predecessor, the managed tool `dataset_lookup` (`9FEzVZk`) and the `lookup` intent,
> were REMOVED from the code. The reference research pack still describes `attribute_lookup` as "built but
> not wired": the repository code (edited live, `dataiku-agents/CLAUDE.md`) indicates the opposite. To
> be confirmed on the instance, and the native Mesh call pattern remains true in all cases.

## Rationale

Three reasons underpin this choice.

1. **Preserve reasoning AND tool-calling.** This is the central argument: `as_langchain_chat_model` loses
   these two capabilities; native Mesh calls keep them. Without reasoning, the orchestrator routes poorly;
   without tool-calling, it can neither delegate to the sub-agents nor request a chart/table rendering.

2. **Reasoning is configured on the model, not in the code.** With the native API, the reasoning effort is
   configured on the LLM Mesh connection side (for example reasoning=high on the model) and the code merely
   requests the completion. The LangChain adapter would add a translation layer that masks those
   settings. Important corollary: we NEVER force `with_json_output` on the orchestrator, because in DSS
   14 that silently DISABLES the reasoning of the call (see
   [ADR-0007](0007-json-output-force-sur-understand.md), where this same `with_json_output` is, on the
   contrary, FORCED on the sub-agent's UNDERSTAND extraction, which does not need to reason).

3. **Sync streaming works, async does not.** `get_stream_writer()` is reliable in a synchronous node under
   3.11. The "blocking Mesh call in a sync node + custom writer" pattern is the one that has been proven
   on the instance; it does not force the use of the asynchronicity that the ChatModel adapter would encourage.

## Consequences

### Positive

- DSS validation: the execution log proves that LangGraph runs on the Python 3.11 Code Agent with these
  native calls, which lifted the review uncertainties (L055). Reasoning and tool-calling are preserved
  end to end.
- The strict `tool_call -> tool_output` pairing is under direct control of the code (via `with_tool_calls`
  / `with_tool_output`), which avoids the Mesh 400s on Claude / Vertex.
- Evidence capture is deterministic: SQL and rows are read from the return value of
  `get_agent_tool(...).run()`, not guessed in a trace.
- The agent files remain self-contained: only `stdlib`, `dataiku` and `langgraph` are imported, never
  a LangChain adaptation layer for the models. No import of the plugin.

### Negative

- Two distinct processes coexist: the Code Agents (3.11 env) and the Flask python-lib backend (env
  3.9.23). A config set in one does not reach the other without explicitly making it TRAVEL (the case of
  the Evidence source URL, which transits through the SQL items). See
  [05-agents/07-deploying-and-editing-agents.md](../05-agents/07-deploying-and-editing-agents.md).
- The two Code Agents must be RE-PASTED by hand into DSS after every repository change (the
  repository is the source of truth). This is a permanent process, not an automated build.
- This pattern depends on the Python 3.11 runtime for the agents (env distinct from the 3.9 backend). This is the subject
  of [ADR-0005](0005-langgraph-code-agents-python-311.md).

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| `as_langchain_chat_model()` (LangChain ChatModel adapter) | Loses the Mesh's native reasoning AND tool-calling; normalizes the exchange and masks the connection-side settings. Unacceptable for an orchestrator that routes and drives tools. |
| DSS visual agents (black box) | No fine-grained control over the loop, the event streaming, the tool_call/output pairing or Evidence capture; not auditable at the required level. |
| Everything in Python 3.9 in the Flask backend | LangChain / LangGraph are not available on the 3.9 env; the 3.9 / 3.11 dual path exists precisely to host the agents in 3.11 (L054). |
| Force `with_json_output` on the orchestrator to make its outputs reliable | In DSS 14, that disables the reasoning of the call. The forced JSON is reserved for the sub-agent's UNDERSTAND extraction (ADR-0007), not for the orchestrator that must reason. |

## See also

- [05-agents/06-models-prompts-and-llm-mesh.md](../05-agents/06-models-prompts-and-llm-mesh.md) - the
  detail of the Mesh calls, the per-mode models and the control tokens (reference document).
- [0005-langgraph-code-agents-python-311.md](0005-langgraph-code-agents-python-311.md) - the LangGraph
  choice and the Python 3.11 runtime that makes these sync calls possible.
- [0007-json-output-force-sur-understand.md](0007-json-output-force-sur-understand.md) - the counterpart:
  `with_json_output` forced on UNDERSTAND, never on the orchestrator (otherwise loss of reasoning).
- [0009-modeles-par-mode.md](0009-modeles-par-mode.md) - which model drives the loop depending on the mode
  (eco / medium / high), with no escalation.
- [0010-grounding-et-semantic-model.md](0010-grounding-et-semantic-model.md) - the inline grounding
  (not a tool) and the Semantic Model that owns the SQL, called via `get_agent_tool(...).run()`.
- [05-agents/07-deploying-and-editing-agents.md](../05-agents/07-deploying-and-editing-agents.md) -
  re-paste the two Code Agents (3.11 env) and verify the ids after every change.
- [README.md](README.md) - ADR index.
