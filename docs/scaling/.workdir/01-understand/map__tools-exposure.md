Now I have enough to write a precise, grounded analysis.

---

## Tools & Exposure Mechanism: How Artifacts Work Today and Can They Be Shared?

### (1) Exactly HOW does an agent cause a chart/table to appear?

**Answer: (a) - it is a built-in Python tool inside the orchestrator's own loop, not a DSS tool object.**

The mechanism, traced from real code:

1. `build_tool_specs()` in `OWIsMind_orchestrator.py` (line 323-373) registers `show_chart`, `show_table`, and `show_kpi` as **in-process function specs** added to the `LoopChat` completion's `settings["tools"]`. They exist only as JSON schema entries; there is no DSS `get_agent_tool()` call behind them.

2. In `node_tools()` (line 1586-), the dispatcher splits incoming tool calls into `sub_calls` (routed to real DSS sub-agents via `self._tool_to_cap`) and `local_calls` (all others). `show_chart/table/kpi` fall into `local_calls`.

3. For each local call, `_record_artifact(name, args, state)` (line 1467) validates the column names against `state["latest"]` (the last result from a sub-agent) and builds an artifact spec `{kind, title, chart}`. It returns this spec and a short text for the model.

4. If the spec is valid, `writer(_ev("ARTIFACT", {...}))` (line 1669-1673) is called via `get_stream_writer()` - the LangGraph stream writer. This emits an `ARTIFACT` event into the LangGraph custom stream.

5. On the backend side, `streaming.py`'s `_normalized_artifact_event()` (line 142) picks up `ARTIFACT` events and normalizes them into `{type:"artifact", kind, title, chart}` - note the comment at line 147: **"The DATA is NOT here - the frontend reuses the captured generated_sql result via /evidence/meta; only the SPEC travels."**

6. `stream_manager.py` (line 385-398) accumulates the artifact specs and, at end-of-run (line 449-457), persists them via `artifacts_storage.save_artifacts(exchange_id, user_id, artifacts)` into `webapp_artifacts_v1`.

7. The frontend fetches `/evidence/meta`, gets the `artifacts` array, and then `chart_payload.py` on the server constructs the Chart.js `{labels, datasets}` payload by joining the artifact spec (x/y column names) against the captured SQL result rows already in `generated_sql[].result`.

**The key coupling**: `show_chart/show_table` only work because `state["latest"]` (the in-memory LangGraph state dict) holds the result rows from the sub-agent's SQL call, captured earlier in the same `node_tools` pass. The artifact spec and the data live in TWO DIFFERENT places: spec in the stream, data in the captured SQL result. Joining them back happens server-side in `chart_payload.py` at Evidence fetch time.

---

### (2) Is this capability intrinsic to OUR code agent, or callable by a foreign agent?

**Fully intrinsic to our code agent. A foreign visual agent cannot trigger it.**

The coupling is deep and four-layered:

| Layer | Coupling |
|---|---|
| **LangGraph graph state** | `state["latest"]` holds the in-memory result rows. A foreign agent has no access to this state dict; there is no shared memory bus. |
| **Stream writer** | `writer(_ev("ARTIFACT", ...))` calls `get_stream_writer()`, which is the LangGraph `custom` stream channel, only available inside a LangGraph graph node. A visual DSS agent does not run in our graph. |
| **Backend stream interpreter** | `streaming.py` only sees events coming through our polling loop (`/chat/poll`), which wraps OUR orchestrator's invocation in `stream_manager.py`. A foreign agent's events flow through a completely different DSS pathway. |
| **Data join at Evidence time** | `chart_payload.py` joins the artifact spec against the `generated_sql[].result` captured into `webapp_artifacts_v1` by our `stream_manager`. A foreign agent emits no `generated_sql` items in our format and persists nothing into our tables. |

A Dataiku visual/LLM Mesh agent running outside our code has no way to push into our `webapp_artifacts_v1`, no access to our LangGraph state, and no entry point to emit an `ARTIFACT` event our backend would catch.

---

### (3) What does plugin.json currently expose?

`Plugin/owismind/plugin.json` declares **only the plugin metadata**: id `owismind`, version, label, description, author, icon. It exposes **zero functional components**: no recipes, no custom python steps, no agent tools, no code environments, no webapps (those are under `webapps/` and `python-lib/` which DSS discovers by convention from the directory layout, not from entries in `plugin.json`).

The plugin's actual runtime surface is: one WebApp (`webapp-owismind-ai-agents`, under `webapps/`) + one python-lib (`python-lib/owismind/`), discovered by DSS from folder structure. There are NO declared agent tool components in the plugin manifest.

The DSS agent tool objects (`attribute_lookup`, `revenue_semantic_query`) are **project-level objects inside the DSS project `OWISMIND_DEV`**, not plugin-declared components. They are not shipped in the plugin zip.

---

### (4) Can a DSS plugin declare a reusable "Custom Python tool" callable by ANY agent (visual or code)?

**Partially known, partially proven, partially unknown.**

**Proven (from the codebase):** DSS 14 supports "Custom Python tools" as standalone project-level objects, callable via `project.get_agent_tool(id).run(input_dict)`. The orchestrator uses this exact API at line 1293 to call `attribute_lookup`. Both visual and code agents can reference a Custom Python tool in their DSS configuration if the tool exists in the same project.

**From `GUIDE_DATAIKU_DSS_PLUGIN_REFERENCE.md`:** The guide does not mention agent tool components as a plugin-packageable type. It lists: WebApps, recipes, python-lib, resource files, code-env. There is no reference to a `plugin.json` field for declaring a Custom Python tool component.

**What is unknown / not confirmed in this repo:** Whether DSS 14 supports declaring Custom Python tool objects INSIDE a plugin zip (so they deploy with the plugin and appear in LLM Mesh's tool picker for any agent project-wide). The DSS Plugin Reference in `docs/cadrage/` gives no evidence of this capability. The fact that `attribute_lookup` is a standalone project object (not in the plugin zip) is suggestive that it cannot currently be plugin-packaged.

**Conclusion:** The mechanism for a visual agent to call `attribute_lookup` **already works in principle** (project-level Custom Python tool, any agent in the project can select it in DSS config). But packaging it as a distributable plugin component is unproven from this codebase.

---

### (5) The seam problem: exposing render_chart / build_pdf / draft_email as plugin tools callable by foreign agents

**The hard coupling problems:**

**Problem 1 - Data delivery.** Today `show_chart` works because the data (`state["latest"]`) is already in the orchestrator's LangGraph state. A plugin tool (`render_chart`) callable by a foreign agent would need to **receive the data as input** (the rows, columns) in the tool call itself, not rely on shared memory. That means the foreign agent must serialize its result rows into the tool's input payload - potentially large, token-costly, and against DSS stream patterns.

**Problem 2 - No return channel into the webapp stream.** Our ARTIFACT flow is: `writer(ARTIFACT event)` -> our `stream_manager` captures it -> `webapp_artifacts_v1` -> `/evidence/meta`. A Custom Python tool's return value goes back to the CALLING AGENT as a text string (the tool output in the agent's LLM context). There is no mechanism for a Custom Python tool to side-channel events into our webapp's polling stream for a run initiated by a different agent. The seam would require the plugin tool to write directly to `webapp_artifacts_v1` using the run's `exchange_id` - but a foreign agent's run has no `exchange_id` in our schema unless we create one.

**Extension seam that would work (concrete):** A Custom Python tool `render_chart(exchange_id, columns, rows, chart_type, x, y, title)` that:
- Takes row data as JSON input (foreign agent serializes it)
- Receives `exchange_id` as a parameter (the foreign agent's chat session must have been initiated through our webapp, giving it an exchange_id)
- Writes directly to `webapp_artifacts_v1` via `artifacts_storage.save_artifacts(exchange_id, user_id, [spec])`
- Returns a JSON string `{"status":"rendered","kind":"chart","title":"..."}` to the calling agent's LLM context

The hard coupling then reduces to: **the foreign agent must run inside a chat session our webapp initiated** (so an `exchange_id` in our schema exists). This is feasible if the foreign agent is invoked from our webapp's `/chat/start` as an alternative agent entry in the whitelist. But for a truly foreign agent (invoked outside our webapp, in another DSS flow), there is no exchange_id and no stream - the artifact has nowhere to land.

**The `build_pdf` / `draft_email` tools are simpler** - they can return their output as a URL or base64 string to the calling agent's LLM context without needing to write to the webapp's artifact store. The rendering stays in the tool's return value, not in a side panel.

**Summary of the coupling that blocks full generalization:** The chart/table Evidence panel is a webapp-session-scoped side channel, not a general-purpose rendering bus. Any tool wanting to push into it must be aware of the session (exchange_id), must run inside a process that can reach our PostgreSQL connection `SQL_owi`, and must serialize data explicitly. This is doable for agents invoked from our webapp; it is structurally impossible for agents running independently in other DSS contexts.