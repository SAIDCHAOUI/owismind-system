Now I have enough to write a comprehensive, dense research response.

---

## Dataiku DSS - LLM Mesh Agents, Plugin Tools, and MCP: State-of-the-Art Findings

---

### 1. Visual Agents vs Code Agents: Capabilities and Tool Access

**Two agent paradigms exist in DSS 13.x/14.x:**

- **Simple Visual Agents** ([doc](https://doc.dataiku.com/dss/latest/generative-ai/agents/visual-agents.html), DSS 13+): no-code, purely autonomous. The builder declares which managed tools the agent may use and optional instructions. The agent selects and calls tools on its own. No Python required.
- **Structured Visual Agents** ([release notes 14.4.0](https://doc.dataiku.com/dss/latest/release_notes/14.html)): block-based, deterministic orchestration (routing blocks, mandatory tool call blocks, Python blocks). Introduced in 14.4.0. Artifacts from earlier blocks flow into later blocks. Python blocks in structured agents support project libraries as of 14.6.0.
- **Code Agents** ([doc](https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html), DSS 13+): full Python control. Require **Python 3.10+** code environment. Can use LangChain/LangGraph and native Mesh calls. Access managed tools via `project.get_agent_tool(id).run(input)` or `.as_langchain_structured_tool()`.

**Critical constraint for OWIsMind:** The backend is Python 3.9 (observed). Code agents and their code envs require Python 3.10+. This is a hard DSS constraint - code agents cannot run in 3.9.

---

### 2. Plugin-Provided Custom Agent Tools: The Full Contract

**This is the decisive finding.** Dataiku does support plugin-shipped custom agent tools that appear as managed tools in the platform catalog - selectable by both visual and code agents.

**Plugin structure** ([developer guide](https://developer.dataiku.com/latest/tutorials/plugins/custom-tools/generality/index.html)):

```
toolbox/
  plugin.json
  code-env/python/spec/requirements.txt
  python-agent-tools/
    my-tool/
      tool.json          # component descriptor
      tool.py            # implementation
```

**`tool.json` (component descriptor):**
```json
{
  "id": "my-tool",
  "meta": {
    "label": "My Tool",
    "description": "One-line purpose"
  },
  "params": []
}
```
The `params` array can define admin-configurable parameters (connection names, dataset names, etc.) that become available as `config` in `set_config`.

**`tool.py` (Python contract):**
```python
from dataiku.llm.agent_tools import BaseAgentTool

class MyTool(BaseAgentTool):
    def set_config(self, config, plugin_config):
        self.config = config

    def get_descriptor(self, tool):
        return {
            "description": "Description the LLM sees to decide when to call this tool",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "param1": {"type": "string", "description": "..."}
                }
            }
        }

    def invoke(self, input, trace):
        args = input["input"]
        # ... logic ...
        return {"output": "string result"}
```

**Registration flow:** Once the plugin is installed, admin goes to `GenAI > Agent Tools > New agent tool`, selects the plugin tool from the list, gives it a project-scoped name and description. The tool then appears in the managed tools catalog and is **selectable by both visual agents and code agents** - confirmed by the developer guide ([source](https://developer.dataiku.com/latest/tutorials/plugins/custom-tools/generality/index.html)): "Custom tools automatically appear in the Dataiku agent tools interface as managed, selectable components."

**Code env for plugin tools:** Dependencies declared in `code-env/python/spec/requirements.txt`. The guide does not specify a minimum Python version for plugin tools themselves (unlike code agents which require 3.10+). This is unconfirmed for 3.9 - worth testing, but plugin code envs are independent of the agent code env.

---

### 3. How Tool Output Surfaces to Agents and Webapps

**Output contract:** `invoke` returns `{"output": "<string>"}`. For dataset lookup tools, the documented pattern is `output['output']['rows']` - suggesting dict outputs with nested structure are supported, not only flat strings. However, the official tutorials only show string returns. Returning a serialized JSON string (then parsed by the agent) is the safest pattern.

**How the calling agent sees the result:**

- Code agent: `tool.run(input_dict)` returns the dict directly. `tool.as_langchain_structured_tool()` makes it a LangChain `BaseTool`. ([using-tools doc](https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html))
- Visual agent: the tool output is injected as context into the LLM's next turn automatically - the agent synthesizes it into the response.
- The `trace` parameter in `invoke` is for execution metadata/monitoring, not content.

**Webapp consumption:** A webapp (Flask/DSS backend) can call any managed tool via the Python API: `dataiku.api_client().get_default_project().get_agent_tool("tool-id").run(payload)`. This is the same API a code agent uses - no agent runtime needed. This is directly applicable to OWIsMind's Flask backend calling chart/table tools on demand.

---

### 4. MCP Support in DSS (DSS as Client and Server)

**DSS as MCP client** ([local MCP doc](https://doc.dataiku.com/dss/latest/agents/tools/local-mcp.html), [remote MCP doc](https://doc.dataiku.com/dss/latest/agents/tools/remote-mcp.html)):

- **Local MCP tool** (DSS 14.x): runs an MCP server process locally (stdio transport); tools selectively exposed to agents. Requires `fastmcp >= 2.0`, Python 3.10+.
- **Remote MCP tool** (DSS 14.x): connects to a remote MCP server (HTTP/SSE). Used to consume external MCP servers. Added multi-type field support in 14.6.2.
- Both appear as managed tools usable by visual and code agents.

**DSS as MCP server** ([developer guide](https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/my-mcp/index.html)):

- Requires DSS 14.0+ and Python 3.10+.
- An agent is wrapped as an Agent Tool (LLM Mesh Query type), then exposed via the `mcp` Python SDK as a Code Studio headless webapp.
- Accessible at `https://<HOST>/webapps/<PROJECT>/<WEBAPP_ID>/mcp` with bearer token auth.
- This enables ANY external MCP client (Claude Code, other agents) to call Dataiku agents as tools.

**Relevance to OWIsMind:** MCP is viable for future cross-agent reuse but requires DSS 14 and Python 3.10+ - neither is confirmed for the current OWIsMind instance. The plugin tool path is lower-friction for internal reuse.

---

### 5. Key Constraints and Version Flags

| Capability | Minimum DSS | Python req | Confirmed? |
|---|---|---|---|
| Plugin custom agent tools | 13.x (likely) | unspecified (plugin env) | Docs confirmed |
| Code Agents | 13.x | **3.10+** (hard) | Docs confirmed |
| Simple/Structured Visual Agents | 13.x / 14.4 | none (no-code) | Docs confirmed |
| Local MCP tool | 14.x | 3.10+ + fastmcp 2.0 | Docs confirmed |
| Remote MCP tool | 14.x | 3.10+ | Docs confirmed |
| DSS as MCP server | **14.0+** | 3.10+ | Docs confirmed |
| Plugin tool usable by visual agent | unspecified | - | Implied by docs, **not explicit** |

---

### Concrete Recommendations for OWIsMind

1. **Package chart/table tools as plugin agent tools now.** The `python-agent-tools/` component in a plugin is the correct abstraction. Each tool gets a `tool.json` + `BaseAgentTool` subclass. Once installed, it appears in the managed tool catalog - usable by any visual agent or code agent without reimplementing the tool logic.

2. **The return value must be a string today.** Return a JSON-serialized string for rich payloads (e.g. chart spec). The calling agent (or OWIsMind's Flask backend via `tool.run()`) parses it. Do not rely on dict nesting in `output` - that pattern is only documented for dataset lookup, not guaranteed in all tool types.

3. **Do not target visual agents for chart/table tools yet without testing.** The docs imply plugin tools are selectable in visual agents but do not explicitly confirm it. Validate on the instance before betting the architecture on it.

4. **Keep OWIsMind's Flask backend as the primary tool caller** (`project.get_agent_tool(id).run(payload)`) - no agent runtime required, compatible with Python 3.9, and gives full control over the event stream.

5. **MCP is the path for multi-tenant/cross-project reuse but needs DSS 14 + Python 3.10.** Not yet applicable unless the instance is confirmed at 14.x.

6. **Structured Visual Agents (DSS 14.4+)** are the right abstraction for deterministic multi-step orchestration if/when a visual, no-code builder experience is wanted. The Python block in structured agents supports project libraries (14.6.0), meaning OWIsMind's `python-lib/owismind/` could be imported directly.

---

Sources:
- [Introduction to Agents in Dataiku DSS 14](https://doc.dataiku.com/dss/latest/agents/introduction.html)
- [Simple Visual Agents](https://doc.dataiku.com/dss/latest/generative-ai/agents/visual-agents.html)
- [Code Agents](https://doc.dataiku.com/dss/latest/generative-ai/agents/code-agents.html)
- [Managed tools catalog](https://doc.dataiku.com/dss/latest/agents/tools/index.html)
- [Using tools (agent API)](https://doc.dataiku.com/dss/latest/agents/tools/using-tools.html)
- [Creating a custom plugin tool (developer guide)](https://developer.dataiku.com/latest/tutorials/plugins/custom-tools/generality/index.html)
- [Creating a Custom Python Tool (tutorial)](https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/custom-python-tool/index.html)
- [Local MCP tool](https://doc.dataiku.com/dss/latest/agents/tools/local-mcp.html)
- [Remote MCP tool](https://doc.dataiku.com/dss/latest/agents/tools/remote-mcp.html)
- [Building a Dataiku MCP Server](https://developer.dataiku.com/latest/tutorials/genai/agents-and-tools/mcp/my-mcp/index.html)
- [DSS 14 Release Notes](https://doc.dataiku.com/dss/latest/release_notes/14.html)