Now I have everything I need. Let me compile the analysis.

---

## DSS Plugin & Agent-Tool Capabilities: Technical Analysis

### 1. Plugin component types documented and used

**VERIFIED from `plugin.json` and the webapp + repo structure:**

- **WebApp (STANDARD)**: the sole declared component type. `plugin.json` contains no `components` array beyond the webapp. The webapp `webapp-owismind-ai-agents/webapp.json` declares `"baseType": "STANDARD"`, `"hasBackend": "true"` (string, not boolean - DSS requirement), and `"standardWebAppLibraries": ["jquery","dataiku"]`. One webapp per plugin, one logical entrypoint.
- **python-lib**: `Plugin/owismind/python-lib/owismind/` is a first-class DSS plugin component (placed on the import path by DSS at runtime). It carries the full Flask application: `api/routes.py` (20+ routes), `agents/`, `evidence/`, `storage/`, `security/`.
- **Custom Python Agent Tool**: `dataiku-agents/tools/attribute_lookup_tool.py` extends `BaseAgentTool` (imported from `dataiku.llm.agent_tools`). The class is `MyAgentTool(BaseAgentTool)` with two contract methods: `get_descriptor(self, tool)` returning a JSON Schema `inputSchema` + description, and `invoke(self, input, trace)` returning `{"output": ..., "sources": [...]}`. This tool exists as a live DSS object - it is **not** in the plugin zip; it is a standalone agent tool object created directly in the DSS UI and stored on the instance.
- **Code Agent (Python 3.11 env)**: `OWIsMind_orchestrator.py` and `SalesDrive_revenue_expert.py` in `dataiku-agents/agents/` are LangGraph agents pasted into DSS Code Agents under a Python 3.11 code environment. They are NOT plugin components - they live as DSS project objects, not in the zip.
- **No code-env folder** in the plugin: VERIFIED. The plugin ships no `code-env/python/` subfolder. The webapp backend runs under the instance default env (Python 3.9.23, confirmed by `/ping`). UNVERIFIED whether a plugin-declared code-env would correctly isolate the webapp backend to 3.11.
- **No recipes, parameter sets, custom dataset formats**: none exist in the plugin. `plugin.json` declares no `components` array at all, only top-level metadata.

---

### 2. Can a DSS plugin ship a reusable Agent Tool for visual AND code agents via LLM Mesh?

**The evidence is mixed:**

- **VERIFIED (tool contract)**: `attribute_lookup_tool.py` uses `from dataiku.llm.agent_tools import BaseAgentTool` and implements `get_descriptor()` + `invoke()`. The orchestrator calls `project.get_agent_tool(tool_id)` then `tool.get_agent_tool().run()` (seen in `SalesDrive_revenue_expert.py`). The DSS Python API `project.get_agent_tool(id)` and `project.list_agent_tools()` are used in `OWIsMind_orchestrator.py` (lines 1293-1303). This is the live, validated contract.
- **VERIFIED (Code Agent can call a Custom Python Tool)**: the orchestrator's `_get_tool` / `_run_lookup` pattern (lines 1284-1341) calls the tool object from within a Code Agent. The sub-agent also calls `project.get_agent_tool(id).run()` for the Semantic Model Query tool (`v4oqA6R`).
- **UNVERIFIED (visual agent reuse)**: the guide documents, skill, and repo code show tools being called from Code Agents only. Whether a Dataiku **visual agent** (the drag-drop builder in DSS 14.4) can pick up the same Custom Python tool is plausible from Dataiku's documented architecture but is NOT demonstrated by any code in this repo. Must be confirmed on the instance.
- **UNVERIFIED (plugin-packaged tool)**: `attribute_lookup_tool.py` is **not** inside the plugin zip - it is manually created in the DSS UI by pasting the Python. DSS does support declaring agent tools inside a plugin's `agent-tools/` subfolder (official docs §8), but **this repo has never done it** and the guide does not document this path. Declaring a tool via the plugin would make it available to any project that installs the plugin; this is an untested extension point.

**Descriptor / contract (VERIFIED from `attribute_lookup_tool.py`)**:

```python
class MyAgentTool(BaseAgentTool):
    def get_descriptor(self, tool):
        return {
            "description": "...",
            "inputSchema": {
                "$id": "...", "type": "object",
                "properties": {"entity": {...}, "attributes": {...}, "dataset": {...}},
                "required": ["entity"],
            }
        }
    def invoke(self, input, trace):
        args = input.get("input", {})
        ...
        return {"output": payload, "sources": [{"id": dataset, "type": "dataset", "name": "..."}]}
```

Tool resolves its own dataset via `dataiku.Dataset(name).get_location_info()` and runs SQL through `dataiku.SQLExecutor2(dataset=...)`. No project key is passed by the caller - it is resolved from the DSS execution context.

---

### 3. Webapp runtime: Flask on Python 3.9.23

**VERIFIED:**

- `webapp.json`: `"hasBackend": "true"` (string), `"baseType": "STANDARD"`.
- `webapps/webapp-owismind-ai-agents/backend.py`: bootstrap pattern confirmed by the guide - `from owismind.api.routes import register_routes; register_routes(app)`. DSS injects the `app` Flask object.
- `python-lib/owismind/api/routes.py`: `Blueprint("owismind_api", __name__, url_prefix="/owismind-api")`, 22 routes including `/ping`, `/chat/start`, `/chat/poll`, `/chat/stop`, `/agents`, `/evidence/meta`, `/evidence/rows`, `/evidence/distinct`, `/usage`, `/admin/*`.
- Python version: 3.9.23 confirmed at `/ping` (`sys.version`). FastAPI / 3.11 backend are **UNVERIFIED** and the guide explicitly warns not to assert them.
- `paramsPythonSetup: "compute_available_connections.py"`: DSS calls this Python script to populate the `sql_connection` SELECT dropdown in webapp settings - a DSS-specific extension point for dynamic param choices.

---

### 4. Constraints shaping any plugin-tool plan

**Code env split (VERIFIED):**
The webapp backend must stay on Python 3.9.23 (no langchain, no langgraph). LangGraph agents run in a separate Python 3.11 Code Agent env. A Custom Python agent tool runs in the Code Agent's env (3.11 when called from Code Agents), NOT in the Flask backend's env. This is the hard seam: **the webapp backend and the agent tools live in different runtimes**.

**Dataset / project handle inside a tool (VERIFIED):**
`MyAgentTool._get_table()` calls `dataiku.Dataset(dataset_name).get_location_info()`. The DSS execution context (project scope) is inherited from the Code Agent environment - the tool does not receive an explicit project key. `dataiku.SQLExecutor2(dataset=dataiku.Dataset(name))` binds to the agent's project context. Accessing a dataset from another project requires `dataiku.Dataset(name, project_key=...)` explicitly.

**Structured output from a tool (VERIFIED):**
The `invoke()` return dict `{"output": dict|str, "sources": [...]}` is the contract. The orchestrator reads `tool_output` as a JSON string and passes it back to the LLM as a tool result. Rich structured data (tables, charts) is passed via DSS artifact events (`ARTIFACT` event kind) written by the orchestrator's `show_chart` / `show_table` nodes - NOT by the tool's `invoke()` return value.

**Streaming limits (VERIFIED):**
There is no streaming inside `invoke()`. A tool call is a blocking synchronous call. The DSS proxy buffers HTTP long-streams, so SSE is abandoned (L019, validated in DSS). Live UX comes from **timeline events** emitted by the Code Agent's LangGraph nodes, not from tool internals. Tool output reaches the model when `invoke()` returns.

**Scaling bottleneck**: `MyAgentTool.__init__` holds `self._cache` and `self._tables` as instance state. If DSS re-instantiates the tool class per call (likely), these per-instance caches offer no cross-call benefit. UNVERIFIED whether DSS keeps a single tool instance alive between calls.

---

### 5. Concrete recommendation skeleton: expose webapp capabilities as plugin agent tools

**What is safe to assert (VERIFIED seams):**

A new capability callable by a Code Agent follows this pattern, validated in the repo:

```
dataiku-agents/tools/<new_capability>_tool.py
  class MyAgentTool(BaseAgentTool):
      def get_descriptor(self, tool): -> {"description": ..., "inputSchema": ...}
      def invoke(self, input, trace): -> {"output": ..., "sources": [...]}
```

The tool accesses Dataiku APIs (`dataiku.Dataset`, `SQLExecutor2`, `dataiku.api_client()`) directly in the 3.11 env. Add the tool as a `lookup_domains` entry in the orchestrator registry (lines 224+ of `OWIsMind_orchestrator.py`) and wire it as a built-in tool in `build_tool_specs()` (line 285) or as a new CAPABILITY entry. The existing `_get_tool` / `_run_lookup` pattern is the clean extension seam.

**What must be validated on the instance first (UNVERIFIED):**

1. **Plugin-packaged tool discovery**: whether adding an `agent-tools/` subfolder to the plugin zip makes the tool automatically available to visual and Code Agents in any project. Not tested here; requires an `agent-tools/<name>/` folder with a `tool.json` descriptor and a `tool.py` - this is the official Dataiku plugin contract but NOT used in this repo.
2. **Visual agent compatibility**: confirm a visual LLM Mesh agent can call a Custom Python tool from this plugin (vs. a tool created ad-hoc in the project).
3. **Cross-project tool visibility**: whether `project.get_agent_tool()` can resolve a plugin-packaged tool from a project other than where the plugin is installed.
4. **Instance reuse of `MyAgentTool`**: whether DSS keeps a single instance alive (making `self._cache` useful across calls) or re-instantiates per call.

**The safest, already-proven path**: create the tool as a Python file in `dataiku-agents/tools/`, paste into a DSS Custom Python Tool object in the target project, reference by id in `LOOKUP_TOOL_ID` (or by name via `LOOKUP_TOOL_NAME`). This is the `attribute_lookup` pattern and is the only path with live DSS evidence in this repo.