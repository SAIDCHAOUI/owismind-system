# ADR-0005 - LangGraph Code Agents on Python 3.11

> Audience: Agent engineer. Last updated: 2026-06-18. Summary: why OWIsMind's orchestrator and revenue
> sub-agent are LangGraph Code Agents running on a Python 3.11 code env, separate from the Flask backend on
> 3.9.23, and why the alternatives (visual agent, all-in-3.9) were rejected.

## Status

Accepted and validated in DSS. The execution log proves that LangGraph runs on the 3.11 Code Agent (see L055 in
`memory/LESSONS.md`), which cleared the two UNVERIFIED items from the initial review. The decision is
structural: it is the foundation of the entire agent layer.

> IN FLUX: the `dataiku-agents/` agent layer is being edited live. Class names, model ids and the tool list
> may shift from one session to the next. The names cited here were verified against the code as of
> 2026-06-18; in case of divergence, the code prevails.

## Context

OWIsMind needs two robust agents capable of both reasoning AND calling tools:

- an orchestrator (`OWIsMind_orchestrator`) that converses with the user, routes to a specialist sub-agent,
  renders artifacts (chart, table, kpi) and writes the analysis, while never holding a single business
  figure;
- a revenue expert sub-agent (`SalesDrive_revenue_expert`, `agent:bHrWLyOL`) that runs an
  UNDERSTAND -> RESOLVE -> QUERY -> RENDER pipeline and owns all the figures.

Two platform constraints drive the decision.

First, the **dual Python path**. The Dataiku instance has two code environments: Python 3.9 AND
Python 3.11 (confirmed by the user on 2026-06-14). However, the **Flask backend of the webapp runs on
3.9.23** (observed). Yet LangChain and LangGraph v1 require Python >= 3.10. Both facts are true
simultaneously: one cannot conclude that "everything is 3.9, therefore never any langchain", nor the
reverse. The trap would be to assume the backend is representative of the whole platform.

Second, **agent quality**. A DSS visual agent (box-to-box in the editor) is quick to assemble but
opaque: you control neither the loop, nor the deterministic capture of evidence, nor the propagation of the
mode to the sub-agent, nor the frozen contracts on which Evidence Studio depends. The project needs full
control over the loop code, the event transport and the signal/data separation.

## Decision

Both agents are **Code Agents implemented in LangGraph**, running on a **Python 3.11 code env**.

### 1. LangGraph Code Agents, not visual agents

Each agent is a self-contained Python file (`agents/OWIsMind_orchestrator.py` and
`agents/SalesDrive_revenue_expert.py`) re-pasted by hand into a DSS Code Agent. The repository is the **source
of truth**: you edit the file in the repository, then re-paste into DSS on every change (direct edits in DSS
are overwritten on the next paste). The DSS entry point is a `MyLLM(BaseLLM)` class (inheriting from
`dataiku.llm.python.BaseLLM`) whose runtime calls `process` / `process_stream`. The files are strictly
self-contained: they import only the stdlib, `dataiku` and `langgraph`; no import from the plugin.

The loop is a LangGraph `StateGraph` compiled **per request** (closures bind the `project`, the `trace` and
the chat context of the current call). The orchestrator wires three nodes, `agent` -> `tools` ->
`agent`, with a `finish` exit, in the "sub-agents-as-tools" pattern:

```
user turn -> [agent] --(tool calls?)--> [tools] --> [agent] --> ... --> [finish]
                ^                                       |
                +---------------------loop---------------+
```

The full graph (orchestrator loop and sub-agent pipeline) is described and drawn in its canonical home, the
agent-system overview: see
[Agent system - overview](../05-agents/01-agent-system-overview.md). This ADR does not redraw it.

### 2. Python 3.11 code env required

Because the files import `langgraph` (`from langgraph.graph import StateGraph, START, END` and
`from langgraph.config import get_stream_writer`), they MUST run on a code env >= 3.11. The header of the
orchestrator file enshrines it as a non-negotiable rule: "This file imports langchain/langgraph -> it MUST run
on a Python >= 3.11 code env. Assign the 3.11 code env to this Code Agent in DSS Settings." The sub-agent
carries the same constraint ("Runs on the Python 3.11 code env, LangGraph needs >= 3.10").

The Flask backend, for its part, stays on **3.9.23**: it never does an `import langchain`. It talks to the
agents through LLM Mesh natively (`get_agent_tool(id).run()`), like the rest of the backend. The version
boundary is therefore clean: all agentic code is isolated in the two 3.11 Code Agents, while the backend stays
stdlib + `dataiku` on 3.9.

| Component | Runtime | Imports langchain/langgraph? | LLM Mesh calls |
|---|---|---|---|
| Flask backend (`python-lib/owismind`) | Python 3.9.23 | No (forbidden) | Native (`get_agent_tool(id).run()`) |
| Orchestrator Code Agent (`OWIsMind_orchestrator`) | Python 3.11 code env | Yes (LangGraph) | Native (`new_completion()`, `execute_streamed()`, `get_agent_tool(id).run()`) |
| Sub-agent Code Agent (`SalesDrive_revenue_expert`) | Python 3.11 code env | Yes (LangGraph) | Native (same) |

### 3. Native LLM Mesh calls in synchronous nodes

Inside the (synchronous) nodes, calls to the model, the sub-agents and the tools are made **natively through
Mesh**: `self._project.get_llm(self._llm_id).new_completion()` then `completion.execute_streamed()` for the
model, `project.get_agent_tool(id).run()` for a tool or a sub-agent. We NEVER wrap the model via
`as_langchain_chat_model`, because that loses the native reasoning and tool-calling. This is the dedicated
subject of [ADR-0006 - Native LLM Mesh calls](0006-appels-natifs-llm-mesh.md).

The streaming of timeline events goes through LangGraph's `get_stream_writer()`, called from **synchronous**
nodes. `process_stream` drives `graph.stream(initial, stream_mode="custom", ...)` and re-yields each
chunk emitted by the writer. This is a subtle point: the known caveat "`get_stream_writer` is broken" only
applies to the **async** path below 3.11; in SYNC on 3.11, it works (proven by the DSS log, L055). This is one
more reason to stay on the 3.11 code env and keep the nodes synchronous.

## Rationale

- `as_langchain_chat_model` would have cost the reasoning and the tool-calling, exactly what the orchestrator
  needs to route. Native Mesh calls preserve them (see ADR-0006).
- The dual 3.9/3.11 path is the platform reality: isolating the agentic code on 3.11 lets us use LangGraph
  without imposing langchain on the Flask backend, which stays lightweight and stdlib-only on 3.9.
- Code (vs a visual agent) gives control of the loop, of the frozen contracts (event kinds, the
  `semantic-model-query` span, `AGENT_RESULT`) on which Evidence Studio depends, of the deterministic capture
  of evidence, and of the propagation of the mode to the sub-agent. None of this can be expressed cleanly in a
  box-to-box visual assembly.
- LangGraph brings exactly what is needed: an explicit `StateGraph` loop, a typed state
  (`TypedDict` annotated), and a custom stream writer for the timeline. The rest (model calls, SQL,
  grounding) stays code that we control.

## Consequences

Positive:

- Validated in DSS: the log proves that LangGraph runs on the 3.11 Code Agent (L055).
- The `reasoning effort=high` is set by hand on the model in the LLM Mesh connection (it cannot be driven by
  code), and stays honored by the native calls.
- The loop, the contracts and the evidence capture are entirely under control: that is what makes a
  deterministic Evidence Studio and the propagation of the mode (a single model per turn) possible.
- Extensible architecture: adding a specialist sub-agent = a new 3.11 Code Agent plus a registry entry on the
  orchestrator side.

Negative (accepted costs):

- **Two separate processes**: the Code Agents (3.11) and the Flask backend (`python-lib`, 3.9) are separate
  processes. A config set in one does not reach the other without being made to travel explicitly (real
  case: the Evidence source URL configured in the orchestrator registry does not arrive on its own at
  `/evidence/meta`, it had to be routed through the SQL items, L082).
- **Manual re-pasting**: on every change to the repository, you must re-paste BOTH Code Agents into DSS (env
  3.11) and re-check the config ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`, `SONNET_ID`,
  `SEMANTIC_TOOL_ID=v4oqA6R`, `agent_id=agent:bHrWLyOL`). This is a permanent process, detailed in
  [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

  > IN FLUX: the `attribute_lookup` tool (`tools/attribute_lookup_tool.py`) was wired as a built-in of the
  > ORCHESTRATOR on 2026-06-18 (review decision), which changes the corresponding deployment procedure:
  > create the Custom Python tool in DSS, set `LOOKUP_TOOL_ID` (or rely on the name-based fallback)
  > and re-paste the orchestrator ONLY. The sub-agent stays unchanged. To be confirmed on the DSS side.

- A change to the agent code alone does NOT require a new zip or a backend restart;
  only a change to `python-lib` requires uploading the zip + restarting the backend.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| All in Python 3.9 in the backend | LangChain/LangGraph require >= 3.10; unavailable on 3.9. The backend stays stdlib + `dataiku`. |
| `as_langchain_chat_model` to wrap the Mesh model | Loss of native reasoning and tool-calling. Native Mesh calls instead (ADR-0006). |
| DSS visual agents (box-to-box) | Black box: no control of the loop, the frozen contracts, the deterministic evidence capture, or the propagation of the mode. |
| Asynchronous LangGraph nodes | `get_stream_writer()` is broken in async < 3.11; we stay on synchronous nodes on 3.11 (proven OK, L055). |

## See also

- [Agent system - overview](../05-agents/01-agent-system-overview.md) - the full LangGraph loop (home of the diagram) and the central invariant.
- [The orchestrator (`OWIsMind_orchestrator`)](../05-agents/02-orchestrator.md) - the agent/tools/finish loop, the registry and the modes.
- [The revenue expert sub-agent (`SalesDrive_revenue_expert`)](../05-agents/03-revenue-expert-subagent.md) - the UNDERSTAND/RESOLVE/QUERY/RENDER pipeline.
- [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md) - re-paste the 2 Code Agents (env 3.11), check the ids.
- [ADR-0006 - Native LLM Mesh calls in the nodes](0006-appels-natifs-llm-mesh.md) - why not `as_langchain_chat_model`.
- [ADR-0007 - `with_json_output` forced on UNDERSTAND](0007-json-output-force-sur-understand.md) - reasoning reserved for routing/prose.
- [Technology stack and dependencies](../02-architecture/05-technology-stack.md) - the dual Python 3.9/3.11 path in the global stack.
- [Architecture decisions (ADR) - index](README.md) - back to the ADR index.
