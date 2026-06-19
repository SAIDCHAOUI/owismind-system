# Deploying and editing agents

> Audience: agent engineer. Last updated: 2026-06-19. Summary: how to edit the two Code
> Agents in the repository (source of truth), re-paste them into a Python 3.11 env in DSS, verify the config
> ids, and never break the frozen contracts the webapp depends on.

The two OWIsMind Code Agents (`OWIsMind_orchestrator` and `SalesDrive_revenue_expert`,
`agent:bHrWLyOL`) live in `dataiku-agents/agents/`. The repository is the **source of truth**: you edit
here, then **re-paste** the code into the corresponding DSS Code Agent. Any edit made directly in the DSS
editor is overwritten at the next paste. This document describes the deployment procedure, the config
ids to verify, the frozen contracts that must never be renamed, and the redeployment regimes
depending on what changed (agent only, Flow recipes, plugin backend).

> IN FLUX: the `dataiku-agents/` layer is being edited live by another engineer. The names and ids
> cited here were verified in the code on 2026-06-18. The `attribute_lookup` wiring is present in the
> orchestrator source; it goes live on the next re-paste (see the dedicated section). Always check the
> actual state of the file before relying on it.

## 1. The mental model: one repository, two Code Agents, one 3.11 env

The agents **never go through the plugin zip**. The zip ships the built frontend plus the Flask
backend `python-lib` (Python 3.9.23); the agents are a **third deployment path**, fully
separate. They are **standalone** files: they import only the stdlib, `dataiku` and
`langchain`/`langgraph`, and **no plugin module**. This autonomy is what makes it possible to paste them
as-is into a Code Agent.

The dual Python path is structural: the Flask backend runs on **Python 3.9.23** (without langchain),
while the Code Agents run on **Python 3.11** because LangGraph / LangChain v1 require at least
Python 3.10. You therefore cannot host the agents inside the backend; they must be pasted into a
distinct 3.11 code env. This is what justifies deployment by copy-paste rather than by the zip.

| Element | Repo file | DSS Code Agent | Python env |
|---|---|---|---|
| Orchestrator | `agents/OWIsMind_orchestrator.py` | OWIsMind_orchestrator | 3.11 |
| Revenue sub-agent | `agents/SalesDrive_revenue_expert.py` | SalesDrive_revenue_expert (`agent:bHrWLyOL`) | 3.11 |

The rationale for the 3.11 env and the copy-paste decision are formalized in
[ADR-0005](../08-decisions/0005-langgraph-code-agents-python-311.md). The rationale for the Flask backend
3.9 plus native LLM Mesh calls is in [ADR-0006](../08-decisions/0006-appels-natifs-llm-mesh.md).

## 2. The deployment procedure (re-paste the agents)

The canonical procedure lives in `dataiku-agents/README.md` (section "Deploy / update procedure") and
`dataiku-agents/CLAUDE.md`. In five steps:

1. **Edit** the file(s) in `dataiku-agents/agents/`, then run the pure-logic tests
   (no DSS, no install):
   ```bash
   python3 -m unittest discover -s dataiku-agents/tests
   ```
2. **Re-paste BOTH Code Agents** as soon as one changes, into the **Python 3.11** env:
   `agents/OWIsMind_orchestrator.py` -> Code Agent **OWIsMind_orchestrator**, and
   `agents/SalesDrive_revenue_expert.py` -> Code Agent **SalesDrive_revenue_expert**.
3. **Verify the config ids** against the instance (section 3).
4. **Optional**: set `source_url` on the `revenue_expert` capability of the orchestrator registry
   (the Dataiku URL of the `DRIVE_Revenues` dataset) -> Evidence then renders the source as clickable.
5. **If the plugin backend (`python-lib`) also changed**: rebuild plus upload the zip plus **restart the
   webapp backend**. An **agent-only** change requires **NO zip upload**: the webapp
   resolves the orchestrator by id through the server whitelist, without going through the embedded code agent.

### 2.1 Why re-paste BOTH agents together

The orchestrator resolves the sub-agent **by id** (`agent:bHrWLyOL`), and the collaboration contract between
the two lives on both sides: the orchestrator **labels** the sub-agent's internal blocks and tools
(timeline), and the sub-agent **emits** those same blocks/tools. Some fixes therefore touch both
files at once. Pasting only one of the two can produce a contract drift (a label that no longer
matches, a renamed span). The rule is firm: if one changes, you re-paste both.

> NOTE: these are **complete, standalone Python files**. "Pasting" means replacing
> the entire code of the Code Agent with the content of the repo file, not patching a few lines.

### 2.2 When to restart the backend (or not)

The backend restart depends solely on what changed, not on whether agents moved:

| Change | Re-paste the agents | Upload zip | Restart backend |
|---|:--:|:--:|:--:|
| Code agent only (orchestrator and/or sub-agent) | yes | no | no |
| `python-lib/owismind/**` or `backend.py` | (if agents touched) | yes | **yes** |
| Flow recipes (`recipes/`) | no | no | no (scenario refresh) |

An **agent-only** change therefore requires only a copy-paste: the webapp does not embed the agents'
code, it calls them via LLM Mesh. The backend restart is required only for a change to
`python-lib` or `backend.py`. The full "what to rebuild when" matrix is in
[06-operations/02-build-package-deploy.md](../06-operations/02-build-package-deploy.md).

## 3. The config ids to verify (verbatim)

After each paste, verify that the config constants match the instance. A wrong LLM Mesh id does not
break the paste: it makes **the relevant mode fail silently at runtime** (the mode does not respond,
or the orchestrator emits an `ERROR` event naming the misconfigured `loop_llm`). This is the most
common trap after a re-paste.

### 3.1 Per-mode model ids

Defined identically in the orchestrator and the sub-agent (same constants, same LLM Mesh connection):

| Constant | Value (verbatim) | Mode |
|---|---|---|
| `GEMINI_FLASH_LITE_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.1-flash-lite` | `eco` (default) |
| `GEMINI_FLASH_ID` | `openai:LLM-7064-revforecast:vertex_ai/gemini-3.5-flash` | `medium` |
| `SONNET_ID` | `openai:LLM-7064-revforecast:vertex_ai/claude-sonnet-4-6` | `high` |

The orchestrator maps them via `LOOP_LLM_BY_MODE`; the sub-agent via `LLM_BY_MODE`. The mode chosen by
the user is propagated to the sub-agent, so in `high` the whole stack runs on Sonnet. The detail of the
modes and the propagation is in
[06-models-prompts-and-llm-mesh.md](06-models-prompts-and-llm-mesh.md) and
[ADR-0009](../08-decisions/0009-modeles-par-mode.md).

> IN FLUX: these ids must match an id actually exposed by the instance's LLM Mesh connection
> (form `<connection-prefix>:<provider>/<model>`). They migrated to `gemini-3.1` / `gemini-3.5` /
> `claude-sonnet-4-6`. To re-verify on the instance: an obsolete id means the corresponding mode does not
> respond.

### 3.2 Tool and agent ids

| Constant / field | Value (verbatim) | Where | Role |
|---|---|---|---|
| `SEMANTIC_TOOL_ID` | `v4oqA6R` | sub-agent | Semantic Model Query tool (`revenue_semantic_query`), the only real DSS tool called at runtime; writes and executes the analytical SQL on Sonnet in all modes. |
| `agent_id` (capability `revenue_expert`) | `agent:bHrWLyOL` | orchestrator | resolution of the sub-agent by id (never exposed to the model). |
| `LOOKUP_TOOL_ID` | `""` (empty) | orchestrator | id of the Custom Python tool `attribute_lookup`. Tool object EXISTS in DSS; filling this is optional (name-based fallback resolves `attribute_lookup`). See section 6. |

`SEMANTIC_TOOL_ID_BY_MODE` is constant across the three modes (the tool has its own DSS model, Sonnet).
The detail of the Semantic Model Query tool is in
[04-tools-and-semantic-model.md](04-tools-and-semantic-model.md).

## 4. The frozen contracts: never rename, only add

The webapp (timeline) and Evidence Studio depend on stable names. Renaming them breaks the display without
an explicit error. These contracts are marked "FROZEN" in the file headers. You may **add**
a new kind or label, never **rename** an existing one.

### 4.1 The orchestrator's event kinds

The orchestrator emits a timeline of events whose kinds the frontend knows. Frozen list (header
of `OWIsMind_orchestrator.py`):

`START, PLANNING, CALLING_AGENT, AGENT_DONE, RUNNING_TOOL, TOOL_DONE, ARTIFACT, WRITING_ANSWER, DONE,
ERROR, SUB_AGENT_*` (plus `NARRATION`, transient, live-only, never persisted).

The `SUB_AGENT_*` events are relabelings of the sub-agent's internal blocks (a technical block
without a label is hidden). The structure of the loop that emits these events is detailed in
[02-orchestrator.md](02-orchestrator.md).

### 4.2 The `semantic-model-query` trace span

The sub-agent's SQL reaches Evidence **through the trace**: the sub-agent creates a subspan named
**`semantic-model-query`** per executed SQL (with `{sql, success, row_count}`, plus `rows`/`columns` on the
successful SQL). The orchestrator appends the sub-agent's trace to its own trace
(`trace.append_trace(sub_trace)`), then `_find_generated_sql` walks the tree and collects all
`semantic-model-query` spans into Evidence items. Renaming this span cuts off Evidence capture and usage
attribution. The `sql_id` format `s{step}q{n}` is also frozen. See
[04-backend/05-evidence-and-artifacts.md](../04-backend/05-evidence-and-artifacts.md).

### 4.3 `AGENT_RESULT`, the sub-agent's machine status

The sub-agent emits **one** final `AGENT_RESULT` event `{status, language, intent, resolvedFilters,
sqlCount, rowCount, attempts}`, with `status` in `ready | need_clarification | out_of_scope | no_data |
error`. This is a machine status consumed by the orchestrator (never displayed as-is to the user).
The sub-agent pipeline is described in [03-revenue-expert-subagent.md](03-revenue-expert-subagent.md).

### 4.4 The sub-agent's `KNOWN_*` <-> the orchestrator registry labels (anti-drift test)

The sub-agent declares two frozen tuples, in `SalesDrive_revenue_expert.py`:

```python
KNOWN_BLOCK_IDS = ("resolve", "run_sql", "format_output", "clarify_user",
                   "out_of_scope_msg", "about_data")
KNOWN_TOOL_NAMES = ("resolve_filter_value", "dataset_sql_query")
```

> Note: `resolve_filter_value` and `dataset_sql_query` are timeline **event labels**, not real tool
> calls. The only real DSS tool called at runtime is `revenue_semantic_query` (`v4oqA6R`).

The orchestrator's `CAPABILITIES` registry (capability `revenue_expert`) must label **exactly**
these ids in its `block_labels` (FR/EN) and `tool_labels` (FR/EN). A missing or extra label is a
**contract drift**. This correspondence is locked by an anti-drift test:

```bash
python3 -m unittest dataiku-agents.tests.test_langgraph_agents
```

> NOTE: a comment in `SalesDrive_revenue_expert.py` cites `test_orchestrator_v3.py` as the file
> for the anti-drift test. That name is obsolete: the test actually lives in
> `dataiku-agents/tests/test_langgraph_agents.py` (it compares `set(block_labels.keys())` to
> `set(KNOWN_BLOCK_IDS)` and the equivalent for the tools). The agent test count (242 `test_` functions
> as of 2026-06-18) is liable to change; run the suite rather than relying on a number.

### 4.5 The registry invariant (one capability per domain)

The `CAPABILITIES` registry is both the **server whitelist** and the **manifest** of the sub-agents.
Adding a sub-agent = one entry here (single extension point). Frozen invariant: **a single
`enabled` capability per business domain that owns the figures**. Activating a second revenue agent
would require switching the first to `enabled=False`. The known domains (staffed or not) live in
`BUSINESS_DOMAINS`; an unstaffed domain feeds the orchestrator's honest capability gap (honesty
firewall). See [02-orchestrator.md](02-orchestrator.md).

## 5. Flow recipe changes = refresh, no re-paste

The Flow's three Python recipes (`recipes/profile_dataset_recipe.py`,
`recipes/build_value_index_recipe.py`, `recipes/build_value_catalog_recipe.py`) are **design-time**:
they transform `DRIVE_Revenues` into expertise artifacts (`DRIVE_Revenues_profile`,
`DRIVE_Revenues_value_index`, and the roadmap `DRIVE_Revenues_Value_Catalog`). They **never** run
at chat runtime.

Consequence for deployment: a recipe change **requires no agent re-paste**. You paste
the recipe code into the Flow's Python recipe, rerun it, and a **refresh scenario** keeps
the profile plus index fresh. The agent always reads the artifacts live; it does not need to be re-pasted
when a recipe reruns. The manufacturing of expertise (profile, value index, grounding) is detailed
in [05-flow-recipes-and-grounding.md](05-flow-recipes-and-grounding.md) and
[ADR-0010](../08-decisions/0010-grounding-et-semantic-model.md).

> Note: the sub-agent grounds on `value_index` (inline read-only SQL), NOT on the Value_Catalog.
> `DRIVE_Revenues_Value_Catalog` (recipe `build_value_catalog_recipe.py`) is used only as an alias
> fallback by `attribute_lookup` (orchestrator fast-lookup path), not by the sub-agent.
> `Drive_Revenues_resolve_filter_value` is **being deleted** in DSS (called by nobody; superseded by
> `attribute_lookup`). See [04-tools-and-semantic-model.md](04-tools-and-semantic-model.md).

To add a domain (tickets, satisfaction): wire the same recipes onto the new dataset,
review the profile via an overrides dataset, duplicate the sub-agent Code Agent by changing the two
dataset names in its config, then add **one** entry to `CAPABILITIES`. The domains `tickets`,
`satisfaction`, etc. already exist in `BUSINESS_DOMAINS`, so the capability gap message closes
on its own once the agent is activated.

## 6. In-flux point: activating `attribute_lookup`

> IN FLUX: the managed tool `dataset_lookup` (`9FEzVZk`) and the entire `lookup` intent of the sub-agent
> were **REMOVED on 2026-06-18**. The replacement `attribute_lookup`
> (`tools/attribute_lookup_tool.py`) is built, unit-tested, RUN-TEST validated in DSS, and its **Custom
> Python tool object already exists on the instance** (`dataiku-agents/tools/README.md`, confirmed in
> `dataiku-agents/CLAUDE.md`).

The current state:

- The **wiring is present in the orchestrator**: `attribute_lookup` is declared as a **built-in
  tool** (not a sub-agent capability). It is appended in `build_tool_specs` and dispatched
  inline in `node_tools` (`_run_lookup`), like `show_table` or `current_date`. It touches
  **no frozen `KNOWN_*` contract**, and the **sub-agent is unchanged**.
- `LOOKUP_TOOL_ID = ""` (empty). The name-based fallback (`LOOKUP_TOOL_NAME = "attribute_lookup"`)
  resolves the tool without a code change, so filling `LOOKUP_TOOL_ID` is OPTIONAL (useful for a
  direct bind and slightly faster resolution).
- Activation requires only: **re-paste the ORCHESTRATOR alone** (env 3.11). This is an exception to
  the "re-paste both" rule that applies only because this change does not touch the collaboration contract.

After re-pasting, additionally: (1) update the `revenue_semantic_query` "Description for LLM" in DSS
(drop the stale precondition about `resolve_filter_value`; the corrected text is in
`dataiku-agents/tools/README.md`); (2) delete the `Drive_Revenues_resolve_filter_value` tool object
(called by nobody, loads catalog into pandas RAM).

## 7. Recap of the traps

| Trap | Symptom | Guardrail |
|---|---|---|
| Pasting only one of the two agents | contract drift (label / span) | re-paste BOTH; exception: a change to the `attribute_lookup` built-in only (orchestrator) |
| Wrong Python env | langgraph import fails | assign the **3.11** env to the Code Agent in DSS |
| Obsolete LLM Mesh id | the mode does not respond, `ERROR` event naming `loop_llm` | verify `GEMINI_*_ID` / `SONNET_ID` after each paste |
| Renaming an event kind / the span | timeline or Evidence silent, with no error | frozen contracts: add, never rename |
| Registry labels <-> `KNOWN_*` out of sync | anti-drift test red | make `test_langgraph_agents.py` pass before pasting |
| Forgetting the backend restart | unchanged backend behavior | restart only if `python-lib`/`backend.py` changed |

## See also
- [05-agents/01-agent-system-overview.md](01-agent-system-overview.md) - overview of the agent system and the frozen contracts.
- [05-agents/02-orchestrator.md](02-orchestrator.md) - the LangGraph loop, the registry and the honesty firewall.
- [05-agents/03-revenue-expert-subagent.md](03-revenue-expert-subagent.md) - the sub-agent pipeline and its `KNOWN_*`.
- [05-agents/04-tools-and-semantic-model.md](04-tools-and-semantic-model.md) - `revenue_semantic_query` (`v4oqA6R`) and `attribute_lookup`.
- [05-agents/06-models-prompts-and-llm-mesh.md](06-models-prompts-and-llm-mesh.md) - per-mode models, native LLM Mesh calls, control tokens.
- [06-operations/02-build-package-deploy.md](../06-operations/02-build-package-deploy.md) - what-to-rebuild-when matrix, plugin build and packaging.
- [08-decisions/0005-langgraph-code-agents-python-311.md](../08-decisions/0005-langgraph-code-agents-python-311.md) - ADR: LangGraph Code Agents in Python 3.11.
