# Models, prompts and LLM Mesh

> Audience: agent engineer. Last updated: 2026-06-18. Summary: how the two Code Agents
> select an LLM Mesh model per mode, call it NATIVELY (never `as_langchain_chat_model`),
> reserve reasoning for routing and contract-bound extraction (`with_json_output`), and how
> control tokens drive mode and language end to end.

OWIsMind is **model-agnostic by design**: a single model drives an entire conversation turn, chosen
by the user mode (`eco` / `medium` / `high`). There is no escalation and no mid-turn model switch. This
document is the single reference for model ids, LLM Mesh calling conventions, reasoning tuning, and
prompt design (act-first, live narration, persona). The three foundational decisions are formalized in
ADR-0006, ADR-0007 and ADR-0009.

## 1. The per-mode models

The mode is a LOGICAL key chosen by the user in the webapp. The backend appends it to the current turn
as a control token (see section 4), and each Code Agent resolves it to an LLM Mesh id. The same three
ids are declared VERBATIM at the top of
`dataiku-agents/agents/OWIsMind_orchestrator.py` AND of
`dataiku-agents/agents/SalesDrive_revenue_expert.py`, on the same Mesh connection.

| Mode | Constant (id) | Model | Default | Live narration |
|---|---|---|---|---|
| `eco` | `GEMINI_FLASH_LITE_ID` = `"openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite"` | Gemini 3.1 Flash-Lite | yes (`DEFAULT_MODE = "eco"`) | OFF |
| `medium` | `GEMINI_FLASH_ID` = `"openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash"` | Gemini 3.5 Flash | no | ON |
| `high` | `SONNET_ID` = `"openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6"` | Claude Sonnet 4.6 | no | ON |

The format of an id is `<connection-prefix>:<provider>/<model>`: it MUST match exactly an
id exposed by the instance's LLM Mesh connection. On the orchestrator side, the table
`LOOP_LLM_BY_MODE = {"eco": GEMINI_FLASH_LITE_ID, "medium": GEMINI_FLASH_ID, "high": SONNET_ID}` and the
`pick_loop_llm(mode)` helper return the single model that drives routing, tool calls and the final
response, end to end. On the sub-agent side, this is `LLM_BY_MODE` (same values) and `pick_subagent_llm(mode)`.

> IN FLUX: these ids are best-effort against the observed format. A wrong id is not visible at
> compile time: the corresponding mode simply does not respond in DSS (and since `eco` is the default,
> it is the first one to break). Verify it in the Mesh connection after every re-paste of the Code
> Agents, see [Deploying and editing the agents](07-deploying-and-editing-agents.md).

### Propagating the mode to the sub-agent

The mode does not stay in the orchestrator: it is PROPAGATED so the whole stack remains on the same
tier (in `high`, Sonnet everywhere). In `node_tools`, when the orchestrator delegates to the sub-agent via
`ask_revenue_expert`, it prefixes the `context_msg` (injected in the system role) with a `MODE: <mode>`
line followed by `USER LANGUAGE: <lang>`. The sub-agent reads this token with `forced_mode(context)` (regex
`\bMODE:\s*(eco|medium|high)\b`), threads `pick_subagent_llm(mode)` into the `llm_id` field of its
`ExpertState`, and all of its LLM calls (UNDERSTAND, SQLGEN of the direct fallback, optional headline)
use this model.

One major exception: the **Semantic Model Query tool** (`revenue_semantic_query`, id `v4oqA6R`) which
actually writes and executes the analytical SQL runs on ITS own strong model (Sonnet), configured
in DSS, in ALL modes. Offer and column resolution therefore remains strong whatever the orchestration
tier. Details in
[Agent tools and Semantic Model](04-tools-and-semantic-model.md).

For the details of this decision (removal of escalation, one model per turn, propagation), see
[ADR-0009 - Per-mode models](../08-decisions/0009-modeles-par-mode.md).

## 2. NATIVE LLM Mesh calls (never `as_langchain_chat_model`)

The two files import `langchain`/`langgraph` and therefore run on a Python 3.11 code env (see
[ADR-0005](../08-decisions/0005-langgraph-code-agents-python-311.md)). But INSIDE the LangGraph nodes
(synchronous), the model calls go through the NATIVE LLM Mesh API, never through the
`as_langchain_chat_model` adapter. This is non-negotiable: the adapter loses native reasoning and
tool-calling, whereas the native API preserves them.

The native API used:

- `project.get_llm(llm_id).new_completion()` opens a fresh completion on the mode's model.
- `completion.with_message(content, role=...)` stacks system / user / assistant messages.
- `completion.settings["tools"] = tool_specs` injects the function schemas (orchestrator only).
- `completion.with_tool_calls(...)` / `completion.with_tool_output(..., tool_call_id=...)` replay
  the exact tool_call -> tool_output pairing.
- `completion.execute()` returns a response carrying `.text`, `.tool_calls` and `.trace`.

On the orchestrator side, this contract lives in the `LoopChat` class: the whole transcript is mirrored into
a list of ops (`("msg"|"calls"|"out")`) and replayed on a fresh completion (`_fresh`). This guarantees
that on each turn, every tool_call receives its tool_output: a broken pairing is rejected by LLM Mesh
with a **hard 400** (Claude/Vertex), so `node_tools` is the sole writer of outputs and pairs every
orphaned call with `"[no output produced]"`.

The sub-agent calls its DSS tools (the Semantic Model Query tool) via
`project.get_agent_tool(tool_id).run({...})`, which is the native equivalent on the tools side. This point is
detailed in [Agent tools and Semantic Model](04-tools-and-semantic-model.md).

For the decision and its rationale (3.9/3.11 dual path, why native), see
[ADR-0006 - Native LLM Mesh calls](../08-decisions/0006-appels-natifs-llm-mesh.md).

## 3. Reasoning: where it lives, where it is explicitly turned off

The `reasoning effort` is NOT controllable from code: it is set manually ON the model in the
LLM Mesh connection (for example `high` on Sonnet). The role of the code is NOT to break it where it
serves a purpose, and to turn it off where it hurts.

### The orchestrator NEVER forces `with_json_output`

The orchestrator always calls the model with a plain native completion (tool-calling + free text),
never with `with_json_output`. The reason is documented verbatim at the top of the file: in **DSS 14**,
forcing a native JSON output on the orchestrator **silently disables reasoning**. Yet
the orchestrator needs reasoning to route well (pick the right sub-agent, formulate a
self-contained task, decide chart/table/kpi). So it is left to emit function calls and free
text, with reasoning active.

> Absolute rule: never add `with_json_output` on the orchestrator. It is a reasoning trap
> in DSS 14.

### The sub-agent forces `with_json_output` on UNDERSTAND only

By contrast, the sub-agent's UNDERSTAND step (turning the question into a JSON intent / scope /
terms object) is a deterministic EXTRACTION, not a reasoning task. It is called via
`_call_json_llm`, which forces `with_json_output(schema=...)` on attempt 1. The code comment says so
unambiguously: forcing JSON disables reasoning FOR THAT CALL, which is exactly what is wanted, a
clean and fast parse rather than a long "thinking" pass the parser cannot read. The JSON schema
(`build_understand_schema`) anchors its enums on the business profile (`DRIVE_Revenues_profile`).

The fallback mechanism is two attempts:

| Attempt | Mode | Model | Goal |
|---|---|---|---|
| 1 | `with_json_output` active | mode's model (`state["llm_id"]`, eco/medium/high) | reliable native JSON parse |
| 2 | prompt-only (no json mode) | same model | backup if the connection rejects json mode |

If `with_json_output` is unavailable on the model/connection, the exception is caught, annotated
in the span (`json_mode_unavailable`) and logged: it degrades to a prompt-only parse instead of
failing silently. Absent an injected mode (batch / stand-alone path), `_call_json_llm`
falls back to `UNDERSTAND_LLM_ID` (= the default mode's model, so Gemini Flash-Lite).

> Note: the original bug was the opposite, UNDERSTAND ran with reasoning and without `with_json_output`,
> produced ~15 s of "thinking" then text the parser could not read, and failed before any
> SQL. The fix is this rule: `with_json_output` for any output consumed by code, reasoning
> reserved for real decisions.

Where reasoning stays active on the sub-agent side: the implicit routing and, if enabled, the verified
headline. By default `SUBAGENT_LLM_HEADLINE = False` (the orchestrator writes the user-facing analysis, so
no redundant LLM headline); when it is enabled, the headline is verified figure by figure
(`verify_headline`) and rejected at the slightest unsourceable number.

For the decision and its rationale, see
[ADR-0007 - `with_json_output` forced on UNDERSTAND](../08-decisions/0007-json-output-force-sur-understand.md).

The contrast can be summarized as follows:

| Call | `with_json_output` | Reasoning | Why |
|---|---|---|---|
| Orchestrator (routing + text) | never | active | in DSS 14, json mode breaks reasoning; routing needs it |
| Sub-agent UNDERSTAND | forced (attempt 1) | turned off for this call | deterministic extraction, reliable and fast parse |
| Semantic Model Query tool | configured in DSS | strong (Sonnet) | writes the analytical SQL, in all modes |

## 4. Control tokens: mode and language end to end

The mode and language travel from the frontend down to the two agents as machine-only tokens,
appended by the backend at the END of the current turn (highest-recency slot). The format is built
in `Plugin/owismind/python-lib/owismind/agents/context.py` (`build_user_suffix`):

```
[Context - User: <name> · Today: <date> · Web app language: <label>] ⟦owi:mode=<mode>⟧⟦owi:lang=<lang>⟧
```

The `[Context - …]` block is HUMAN and remains visible to the model (it carries the imperative language
rule). The `⟦owi:mode=…⟧` / `⟦owi:lang=…⟧` tokens are MACHINE-ONLY: each agent parses them then
STRIPS them from every replayed message, so they never reach the model as text.

On the orchestrator side:

- `parse_mode(text)` reads the LAST valid `⟦owi:mode=…⟧` token (default `eco`) then removes ALL the
  `⟦owi:…⟧` tokens. Reading the LAST one is a safety measure: the backend appends its authoritative
  token at the end of the message, so a user who typed a fake `⟦owi:mode=high⟧` earlier in their
  message cannot force a more expensive model.
- `parse_lang(text)` likewise reads the LAST `⟦owi:lang=…⟧` token (`fr`/`en`), or `None` (batch/eval
  path), in which case the code falls back to `_detect_lang`.
- `_strip_context_block` removes the human `[Context -…]` block only for our DERIVED uses
  (sub-agent continuity, fallback detection); the MODEL always sees the block via the replayed
  history.

On the sub-agent side, the `MODE:` and `USER LANGUAGE:` injected into the `context_msg` are read by
`forced_mode(context)` and `forced_language(context)`. The authoritative language is always the one resolved
by the backend (it knows the real language of the user message, whereas the sub-agent only sees a
self-contained task often written in English).

## 5. Prompt design: act-first, conditional narration, persona

The system prompts are generated per request. Three traits structure their design.

### Act-first

The core of the orchestrator prompt (`PERSONA` + `build_system_prompt`, HOW TO WORK section) requires
ACTING, not promising: a question that needs business data must trigger a tool call
THIS turn; a turn that promises without calling a tool is a FAILURE, not a response. This is what avoids
the "narrate-and-stop" of small models (the model writes an introductory sentence then stops without
calling the tool). A dedicated guardrail (`_looks_like_premature_stop`) conservatively detects a
concrete promise without a tool call and re-injects a nudge (at most once per run) asking it to call
the tool NOW.

### Conditional live narration

The "# NARRATE AS YOU GO" section of the orchestrator prompt is added only if `narrate=True`, that is
`narration_enabled(mode)` which returns `mode != "eco"`. When present, it asks the
model to write ONE short natural sentence in the user's language just before the tool call,
on the SAME turn as the call (never the sentence alone). This sentence (the `preamble`) is streamed as
REAL response text, not as a transient ticker: it appears as a bubble before the
tool runs, and the final response continues in the same message.

In `eco` (Gemini Flash-Lite, the smallest tier), narration is deliberately OFF: otherwise the model
would get stuck in narrate-and-stop. The wait is then covered by the deterministic ticker of
the timeline (transient `NARRATION` events on the backend side), not by the model.

### Persona and honesty firewall

The system prompt also carries the persona and the honesty firewall (the orchestrator never emits a
business fact, never says that a piece of data does not exist, routes when in doubt), the output rule (data
in the Evidence panel, never a markdown table in the text), the money rule (`€` + separators,
presentation of the `[Scope]`/`[Perimetre]`), and the screen awareness. These aspects pertain to the
behavior of the orchestrator and are detailed in [The orchestrator](02-orchestrator.md). For the pipeline of
the sub-agent and its prompts (UNDERSTAND, COMPOSE of the semantic question), see
[The revenue expert sub-agent](03-revenue-expert-subagent.md).

The language rule is re-stated LAST in the system prompt (recency slot) AND at the end of the
user message (the `[Context -…]`): a double anchor so that a small model honors it.

## 6. Robustness: naming the model that failed

All the orchestrator loop calls are wrapped in a `try`. On failure,
`process_stream` logs `Orchestrator failure (model=%s)` with `loop_llm`, emits an `ERROR` event
`{"stage": "orchestrator", "message": "internal_error", "model": loop_llm}`, serves a fallback FR user
message, then `DONE`. Naming the model prevents a misconfigured LLM Mesh id from surfacing as an opaque crash
mid-loop: if `eco` does not respond, the ERROR carries the id `GEMINI_FLASH_LITE_ID` and points
directly to the cause (id that does not match the Mesh connection).

## See also
- [Agent system - overview](01-agent-system-overview.md) - the orchestrator and the sub-agent, the frozen contracts.
- [The orchestrator](02-orchestrator.md) - the LangGraph loop, the registry, the honesty firewall, the modes.
- [The revenue expert sub-agent](03-revenue-expert-subagent.md) - the UNDERSTAND/RESOLVE/QUERY/RENDER pipeline and UNDERSTAND in JSON.
- [Agent tools and Semantic Model](04-tools-and-semantic-model.md) - `revenue_semantic_query` (`v4oqA6R`) on Sonnet in all modes.
- [Deploying and editing the agents](07-deploying-and-editing-agents.md) - re-paste the 2 Code Agents in env 3.11, verify the ids.
- [ADR-0006 - Native LLM Mesh calls](../08-decisions/0006-appels-natifs-llm-mesh.md) - why not `as_langchain_chat_model`.
- [ADR-0007 - `with_json_output` forced on UNDERSTAND](../08-decisions/0007-json-output-force-sur-understand.md) - reasoning reserved for routing/prose.
- [ADR-0009 - Per-mode models](../08-decisions/0009-modeles-par-mode.md) - model-agnostic architecture, mode propagation.
