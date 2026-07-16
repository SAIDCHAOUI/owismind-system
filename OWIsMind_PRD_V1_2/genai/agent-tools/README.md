# tools/ - the DSS agent tools

> The tools the OWIsMind agents call inside the production project
> **OWISMIND_PRD_V1_2**. Only one tool has custom Python to mirror
> (`attribute_lookup_tool.py`, in this folder); the others are DSS configuration
> objects with no code to store here.

## The four tools

| Tool | id | Type | Status | Called by | Code |
|---|---|---|---|---|---|
| `attribute_lookup_tool` | `UUoynaL` | InlinePython | LIVE | the **orchestrator** (`OWIsMind_orchestrator`, `038G7mlF`), both domains | [`attribute_lookup_tool.py`](attribute_lookup_tool.py) (this folder) |
| `Drive_Revenues_resolve_filter_value` | `aNxeOc4` | InlinePython | LEGACY, wired to nothing | nobody | not mirrored |
| `revenue_semantic_query` | `v4oqA6R` | Custom_agent_tool (semantic-models-lab plugin) | LIVE | the **revenue sub-agent** (`SalesDrive_revenue_expert`, `bHrWLyOL`) | config only (points at model `AHUh9hb`) |
| `tickets_semantic_query` | `nEirlso` | Custom_agent_tool (semantic-models-lab plugin) | LIVE (tool object present; model repoint pending) | the **tickets sub-agent** (`CSSO_Trouble_Tickets_Expert`, `NcE9LD2i`) | config only (points at model `dM4jA4G`) |

## Details

### `attribute_lookup_tool` (`UUoynaL`, InlinePython, LIVE)

The orchestrator's fast value-read built-in: one read-only `ILIKE` over the source
text columns (revenue or tickets), with the `*_Value_Catalog` / `*_value_catalogue`
alias fallback for "did you mean" suggestions. Its code is mirrored verbatim as
[`attribute_lookup_tool.py`](attribute_lookup_tool.py); edit there, then paste back
into the DSS tool.

### `Drive_Revenues_resolve_filter_value` (`aNxeOc4`, InlinePython, LEGACY)

The former revenue grounding tool. **Superseded by `attribute_lookup_tool`**: it is
wired to nothing (called by no agent), still present in the DSS tool listing as of
2026-07-09, and **pending manual deletion in DSS**. Its code is intentionally NOT
mirrored here (dead code). The names `resolve_filter_value` / `dataset_sql_query`
also survive only as frozen timeline-event labels in the sub-agent
(`KNOWN_TOOL_NAMES`), not as live tool calls.

### `revenue_semantic_query` (`v4oqA6R`) and `tickets_semantic_query` (`nEirlso`)

Instances of the **semantic-models-lab plugin** tool type (`Custom_agent_tool`):
configuration objects that point a Semantic Model Query at a model, with **no
custom Python to mirror**. They bind:

- `revenue_semantic_query` -> model `Drive_Revenues_Semantic_Model` (`AHUh9hb`)
- `tickets_semantic_query` -> model `TroubleTickets_Semantic_Model` (`dM4jA4G`)

Each runs **Agent mode OFF** (linear SQL pipeline), LLM `vertex_ai/claude-sonnet-4-6`,
embedding `vertex_ai/text-embedding-005`, access datasets as the calling user. Their
LLM-facing "Description for LLM" text (the rules pasted into the DSS tool settings)
lives in [`../semantic-models/TOOL_DESCRIPTIONS.md`](../semantic-models/TOOL_DESCRIPTIONS.md).
The models themselves are documented in [`../semantic-models/`](../semantic-models/README.md).
