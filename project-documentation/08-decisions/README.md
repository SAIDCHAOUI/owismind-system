# Architecture Decision Records (ADR) - index

> Audience: developer, architect. Last updated: 2026-06-18. Summary: this document explains what an ADR
> is, the format adopted in OWIsMind, and indexes the 14 structuring decisions of the project with their
> status and a link to the detailed record.

## What this section is for

An ADR (Architecture Decision Record) is a short record that captures a structuring decision: the context
that made it necessary, the decision taken, the reasons, the consequences (good and bad), and the
alternatives that were ruled out. The goal is not to re-explain the code (the technical sections do that)
but to answer the question that every newcomer or future maintainer asks: "why is this done THIS WAY, and
not otherwise?".

In OWIsMind, several choices may look counter-intuitive at first glance: streaming goes through polling
rather than SSE, the runtime uses no Dataiku Flow, the frontend routes in hash mode, and the agents run in
a Python environment different from the backend. Each of these decisions has a concrete cause (often a
failure observed in DSS) and a safety constraint behind it. The ADRs capture this memory to prevent a
future "simplification" from reintroducing a bug that has already been paid for.

The ADRs are the hardened projection of the project's living memory (`memory/LESSONS.md` and
`memory/PROJECT_STATE.md`), which remain the source of truth in case of divergence with an older guide.

## The ADR format used

Each ADR record in this section follows the same structure, in this order:

| Section | What it contains |
|---|---|
| **Status** | The state of the decision: `Accepted`, `Accepted (in flux)`, `Roadmap` or `Superseded by ADR-xx`. A decision validated in DSS production is noted as such. |
| **Context** | The problem or constraint that forced the decision (often a behavior observed in DSS, an instance-safety requirement, or a platform limitation). |
| **Decision** | What was decided, in a clear statement, with the real code identifiers (file, constant, tool id). |
| **Reasons** | The rationale: why this option rather than another, what evidence supports it. |
| **Consequences (+/-)** | The positive effects AND the assumed costs. A good decision always has a cost; naming it avoids unpleasant surprises. |
| **Rejected alternatives** | The options ruled out and the reason for their rejection, so they are not naively re-proposed. |

Status convention used in the index table:

- **Accepted**: decision in force, most often validated in DSS production.
- **Accepted (in flux)**: decision settled, but part of the wiring or DSS validation remains to be
  confirmed; these points are flagged with a `> IN FLUX: ...` blockquote in the relevant record.
- **Roadmap**: orientation decision whose implementation is NOT yet wired in v3.

## ADR table

| # | Title | Status | Record |
|---|---|---|---|
| 0001 | Vue SPA served by DSS as static assets (hash router) | Accepted (DSS) | [0001](0001-vue-spa-servie-par-dss.md) |
| 0002 | Streaming by polling (no SSE, DSS proxy) | Accepted (DSS) | [0002](0002-streaming-par-polling.md) |
| 0003 | Direct SQL, no Flow at runtime (safety posture) | Accepted (DSS) | [0003](0003-sql-direct-sans-flow.md) |
| 0004 | Server-side agent whitelist (opaque logical key) | Accepted (DSS) | [0004](0004-whitelist-agents-serveur.md) |
| 0005 | LangGraph Code Agents in Python 3.11 (3.9/3.11 dual path) | Accepted (DSS) | [0005](0005-langgraph-code-agents-python-311.md) |
| 0006 | Native LLM Mesh calls in the nodes (no `as_langchain_chat_model`) | Accepted (DSS) | [0006](0006-appels-natifs-llm-mesh.md) |
| 0007 | `with_json_output` forced on UNDERSTAND (reasoning reserved for routing/prose) | Accepted (DSS) | [0007](0007-json-output-force-sur-understand.md) |
| 0008 | Evidence trust layer and artifacts (separate signal from data) | Accepted (DSS) | [0008](0008-evidence-trust-layer-et-artifacts.md) |
| 0009 | Per-mode model and mode propagation (model-agnostic architecture) | Accepted (in flux) | [0009](0009-modeles-par-mode.md) |
| 0010 | Grounding via value_index, the Semantic Model owns the SQL (hybrid engine) | Accepted (in flux) | [0010](0010-grounding-et-semantic-model.md) |
| 0011 | Assistive sub-agent (does not impose a column for an ambiguous term) | Accepted (in flux) | [0011](0011-sous-agent-assistif.md) |
| 0012 | Typographic rule: no em dash | Accepted | [0012](0012-regle-typographique-sans-tiret-cadratin.md) |

> Numbering: the index table follows the file numbering `0001` to `0012`. The research material
> (`.workdir/research/decisions-history.md`) numbers from `ADR-01` to `ADR-14` because it groups some
> neighboring decisions under two records (for example the hybrid data engine and the grounding, or the
> orchestrator "route, do not deny"). The content is the same; only the split into delivered files
> differs. See the correspondence below.

### Correspondence with the research material

| Decision (research material) | Delivered record(s) |
|---|---|
| ADR-01 Vue SPA + hash | 0001 |
| ADR-02 polling vs SSE | 0002 |
| ADR-03 direct SQL without Flow + ADR-04 `_vN` naming | 0003 |
| ADR-05 opaque agent whitelist | 0004 |
| ADR-06 LangGraph Code Agents 3.11 | 0005, 0006 |
| ADR-07 `with_json_output` on UNDERSTAND | 0007 |
| ADR-08 hybrid engine + ADR-09 inline grounding | 0010 |
| ADR-10 assistive sub-agent | 0011 |
| ADR-11 orchestrator "route, do not deny" | 0002 (security model) / 0009 (modes) cover it in prose; see `05-agents/02-orchestrator.md` |
| ADR-12 per-mode model | 0009 |
| ADR-13 Evidence trust layer + artifacts | 0008 |
| ADR-14 typographic rule | 0012 |

## In-flux points (to confirm in DSS)

The agent layer (`dataiku-agents/`) is being edited live. Three ADRs carry elements not yet validated on
the instance; each record frames them explicitly. In summary:

> IN FLUX (ADR-0009, per-mode model): the LLM Mesh ids `GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID` and
> `SONNET_ID` declared in `dataiku-agents/agents/OWIsMind_orchestrator.py` (constants `LOOP_LLM_BY_MODE`,
> `DEFAULT_MODE = "eco"`, function `pick_loop_llm`) must match the instance's LLM Mesh connection. A wrong
> id breaks the corresponding mode. The live behavior of the models is not validated in DSS.

> IN FLUX (ADR-0010, grounding and Semantic Model): the `attribute_lookup` tool
> (`dataiku-agents/tools/attribute_lookup_tool.py`) replaces the former managed tool `dataset_lookup`
> (`9FEzVZk`) and its `lookup` intent, both REMOVED on 2026-06-18. The tool is built and unit-tested; it is
> wired as a BUILT-IN tool of the ORCHESTRATOR (constant `LOOKUP_TOOL_ID`, empty as long as the Custom
> Python tool has not been created in DSS), with the SUB-AGENT remaining unchanged. To be confirmed on the
> instance (creation of the tool + value of `LOOKUP_TOOL_ID`). The `DRIVE_Revenues_Value_Catalog` and the
> Python resolver `Drive_Revenues_resolve_filter_value` remain ROADMAP, not wired.

> IN FLUX (ADR-0011, assistive sub-agent): the case "YTD EVPL revenue, actuals vs budget" (offer term
> ambiguous across multiple columns, deferred to the Sonnet model) still needs to be re-tested via the
> orchestrator in DSS.

Other non-blocking elements are in flux and documented in the technical sections: the monthly budget quota
(50 EUR/user/month) whose STORAGE is ready (`webapp_usage_monthly_v1`) but whose BLOCKING is not
implemented, and the capture of the Evidence `result` which remains best-effort.

## Adding an ADR

Any future structuring decision deserves an ADR. A decision is structuring if it is durable, costly to
reverse, or surprising (it runs counter to a reasonable expectation). Typically concerned are: a change of
transport (polling, websocket), a new `_vN` table or a change to the data model, the addition of a new
agent or a new DSS tool, a change of safety posture, the choice of an LLM model or a mode, an evolution of
the Evidence proof contract.

Procedure:

1. Create a file `08-decisions/00NN-short-title-in-kebab-case.md` with the next available number.
2. Follow the template (H1 header + audience/date/summary blockquote; sections Status, Context, Decision,
   Reasons, Consequences +/-, Rejected alternatives; final `## See also` section).
3. Do NOT duplicate a major diagram: an ADR illustrates a DECISION, it points to the relevant flow
   (for example ADR-0002 points to the polling diagram in `04-backend/03-streaming-and-runs.md`) rather
   than redrawing it.
4. Add the corresponding line to the ADR table above (number, title, status, link).
5. If the decision corrects or supersedes an earlier decision, mark the old ADR `Superseded by ADR-NN`
   instead of deleting it (the memory of past choices remains useful).

A fundamental rule never to bypass: an ADR records WHY, not a how-to. The how lives in the
`02-architecture`, `04-backend` and `05-agents` sections. An ADR that starts copying code or duplicating
an operations guide has left its role.

## See also

- [Security model (architecture)](../02-architecture/04-security-model.md) - frames the safety decisions
  (ADR-0003, ADR-0004).
- [Backend - security and validation](../04-backend/06-security-and-validation.md) - details the
  implementation of the guardrails referenced by ADR-0003 and ADR-0004.
- [Backend - streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - the home of the
  polling diagram referenced by ADR-0002.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - goes deeper into
  decision ADR-0008 (trust layer, artifacts, capture).
- [Agent system - overview](../05-agents/01-agent-system-overview.md) - context for decisions ADR-0005 to
  ADR-0011.
- [Flow recipes and expertise building](../05-agents/05-flow-recipes-and-grounding.md) - details the
  grounding and the hybrid engine of ADR-0010.
- [Contributing - conventions and rules](../09-maintenance/01-contributing-and-conventions.md) - the
  project's non-negotiable rules, including the typographic rule of ADR-0012.
- [Known gotchas and lessons](../09-maintenance/03-known-gotchas-and-lessons.md) - the cross-cutting
  gotchas that fed several of these decisions.
- [Documentation portal](../README.md) - back to the general table of contents.
