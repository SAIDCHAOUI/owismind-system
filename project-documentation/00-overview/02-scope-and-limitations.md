# Scope and limitations

> Audience: Product, business, support. Last updated: 2026-06-19. Summary: this document states
> precisely what OWIsMind DOES and DOES NOT do today (a single staffed domain, the declared but
> unequipped domains, the known technical limitations) and gives a snapshot of the roadmap.

OWIsMind is a business-oriented agentic chat portal, packaged as a Dataiku DSS plugin (id `owismind`,
version `0.0.1`). Its promise is not to "answer" but to answer with **evidence**: every figure comes
from a real SQL result, the user watches the agent work live (timeline), and they can inspect the
exact data and SQL that produced the answer (Evidence Studio). This document frames that scope: it
distinguishes what is delivered and validated in DSS, what is deliberately out of scope, and what is
still being wired up. For the product "why", see
[Product overview](01-product-overview.md).

---

## 1. What the system DOES today

The delivered core (v3) is a natural-language question-and-answer assistant on **OWI / Orange client
revenues**, grounded on the `DRIVE_Revenues` source dataset.

| Capability | What the user gets |
|---|---|
| Multi-turn agentic chat | Ask a question in French or English; the orchestrator dialogues, routes to the right specialist, and writes the analysis in the language of the last message. History and context (ancestor chain, name and date) assembled on the backend side. |
| Grounded NL-to-SQL | The terms typed by the user (client names, offer terms) are grounded on exact cell values via grounding (read-only inline SQL on the value index), then the analytical SQL is written and executed by the Semantic Model Query tool `revenue_semantic_query` (`v4oqA6R`). |
| All revenue Phases | The sub-agent `SalesDrive_revenue_expert` (`agent:bHrWLyOL`) owns the figures for all Phases: `ACTUALS` (default), `BUDGET`, `FORECAST`, `Q3F`, `HLF`. Totals, breakdowns, rankings, share of total, scenario or period comparisons, trends, distinct values, "what does this data contain". |
| Live Execution Timeline | A live timeline of the agent's steps, with human-readable labels by default (debug mode shows the technical names). |
| Evidence Studio v1 | An "evidence" panel to the right of the chat that replays the agent's SELECT in read-only mode, shows the source table with the WHERE filters as editable chips, the captured result, the calculation in business language, a deterministic verification badge and the collapsed SQL. Opens automatically at the end of generation. |
| Artifacts (chart / table / KPI) | The orchestrator calls `show_chart` / `show_table` / `show_kpi`: the data is rendered in the panel (interactive Chart.js charts) instead of being copied into the answer bubble. |
| Token and cost tracking | A `tokens in / out + estimated cost` line under each answer. |
| Feedback, branches, stop | Per-message feedback, conversation editing and branches (tree via `parent_exchange_id`), persistent agent per conversation, generation stop. |
| Admin-authored agent profiles | An admin writes each agent's tagline, description, capabilities, tools, icon and badge in the Administration panel (no hardcoded copy); validated and sanitized server-side by `validate_agent_meta` (pure, never raises); stored inside `enabled_agents` in `webapp_settings_v1`; served via `GET /agents` without leaking `agent_id` or project. An agent without a profile shows a "profile to complete" card. |
| Monthly per-user budget | A configurable rolling monthly credit in USD (default $50); spend is `estimatedCost` from LLM Mesh, accumulated in `webapp_usage_monthly_v1` per calendar month. Enforcement: `/chat/start` returns HTTP 402 `monthly_quota_exceeded` when spent >= limit and enforcement is enabled; fails open (a read error lets the answer through). Admins set a global default, time-boxed global boost, or per-user overrides. Coded; not yet validated on DSS. |
| Multilingual and theme | FR and EN; English is the default locale (FR kept). Every UI label translatable. Light and dark theme via `body[data-theme]` + semantic tokens. |
| Orange charter UI | Sober Orange design system: white/black + rare `#FF7900` accent; square geometry (`border-radius: 0`, avatars round); flat fills, 1px rules, heavy titles; collapsed sidebar is a RAIL (logo + icon shortcuts). Spec: `docs/cadrage/CHARTE_ORANGE_UI.md`. |

Target usage: a desktop workstation, from 12 inches to ultra-wide.

### The honesty firewall (what builds trust)

A central structural invariant distinguishes OWIsMind from a chatbot: **the orchestrator never holds
a business figure**. Every figure comes from a sub-agent that executes SQL, so the orchestrator
structurally cannot invent a number. Its PERSONA enforces an honesty firewall (defined in
`OWIsMind_orchestrator.py`, section "YOUR HONESTY"):

- it never states an unsourced business fact, never invents a figure, a source or a
  capability;
- it never tells the user that a metric, a scenario or a figure is "missing, null or
  unavailable": only a specialist can say so, after looking;
- the only allowed "no" is a **capability gap** ("no AGENT yet for this domain"), never "the
  data does not exist";
- it never does arithmetic in its head; exact sums, deltas, ratios and rankings are the
  specialist's work.

This stance explains why some questions receive a "capability gap" rather than a
false answer (see section 3).

---

## 2. A single staffed domain: revenues

In v3, **only one business domain actually has an agent**: the `revenue` domain. The orchestrator's
`CAPABILITIES` registry declares only one active capability
(`revenue_expert`, `enabled: true`), which routes to `SalesDrive_revenue_expert`.

This is a deliberate stance, not a gap: adding a domain is an act of **configuration**, not
a rebuild. The webapp contains no agent business logic. Concretely, staffing a new
domain consists of wiring the same Flow recipes onto the new dataset, duplicating the sub-agent Code
Agent (changing two dataset names), and adding **one entry** in `CAPABILITIES`.

> Invariant to know: **one single active capability per domain that owns the figures**. A
> second revenue agent would have to switch the first to `enabled: false`. This is what guarantees that
> a figure always has a single owner.

---

## 3. Declared but unstaffed domains (the honest "no")

The orchestrator knows a list of business domains (`BUSINESS_DOMAINS`) broader than what is
staffed. A domain is considered "staffed" only when an enabled agent declares it. For the
others, the orchestrator answers with an honest capability gap instead of denying the existence of the data.

| Domain (`BUSINESS_DOMAINS`) | Staffed in v3? | Current behavior |
|---|---|---|
| `revenue` (revenues, invoicing, budget, forecasts) | Yes (`revenue_expert`) | Answered by the revenue sub-agent. |
| `tickets` (tickets and incidents) | No | "No agent yet for this domain" (capability gap). |
| `satisfaction` (client satisfaction) | No | Honest capability gap. |
| `opportunities` (sales opportunities) | No | Honest capability gap. |
| `delivery` (delivery and deployment) | No | Honest capability gap. |
| `billing` (detailed invoicing) | No | Honest capability gap. |

For support: if a user reports that the assistant "refuses to answer" on tickets or
satisfaction, this is not a bug. It is the expected behavior as long as the domain is not
staffed. The message stays honest (an agent is missing), it never claims the data is absent.
The capability gap message closes by itself as soon as an agent is added for the domain.

> The real list of activatable agents always comes from the backend (`GET /agents`). The frontend file
> `agentMeta.js` (which carried hardcoded showcase descriptions like "Cooper, Revenues") was DELETED
> (2026-06-18): agent descriptions are now written by an admin via the Administration panel. Only
> `revenue_expert` is actually deployed; all other entries are configuration placeholders, not
> delivered capabilities.

---

## 4. What the system DOES NOT do (known limitations)

Several limitations are architecture or V1 scope choices, not oversights.

### 4.1 No cross-dataset JOIN in a single query

The sub-agent works on one table, never a JOIN. An analysis that would span several datasets
(for example revenues AND tickets for the same client) is not done in one query: it goes through
the orchestrator, **one agent per dataset**. This multi-agent "360" analysis is waiting for a second staffed
domain to become genuinely useful.

### 4.2 No SSE streaming: a polling-based transport

The live steps are not SSE streaming. A first SSE attempt showed that the internal proxy of
DSS buffers the response, which then arrived in a single block at the end. The chosen solution is a
**polling-via-thread**: the agent runs in a worker thread on the backend side, and the frontend polls
`/chat/poll` every ~500 ms until the run finishes.

Visible consequence for the user: the **text answer often lands in one block at the end**. The
usable "live" view is not text being written word by word, it is the **timeline** of steps. See
[Streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) for the complete
mechanics and [ADR-0002 - Polling-based streaming](../08-decisions/0002-streaming-par-polling.md) for the
decision.

### 4.3 Budget cap: coded, not yet validated on DSS

> IN FLUX: the monthly budget enforcement IS now coded. The `/chat/start` route calls
> `budget.has_budget(user_id)` before starting a run; if the user has spent >= their effective limit
> and enforcement is enabled, it returns HTTP 402 with `monthly_quota_exceeded`. Enforcement fails
> OPEN by contract: a read error (DB unavailable, timeout) lets the answer through, and the spend is
> still recorded so the next request is gated once the read recovers.
>
> Token and cost tracking were already in place (`webapp_usage_monthly_v1`). The new module
> `storage/budget.py` adds: resolution of the effective limit (per-user override > global temp boost
> > global default), the `webapp_user_quota_v1` table for per-user overrides (created lazily),
> admin routes (`GET/POST /admin/budget`, `POST /admin/budget/users`), and a 30-second in-process
> config cache to avoid a second DB round-trip per chat send.
>
> The blocking behavior has not yet been validated on the DSS instance. If a user asks why the
> chat is refused, it is because they reached their monthly budget (HTTP 402). Admins can raise the
> limit or grant a temporary boost via the Administration panel (Quotas tab).

### 4.4 Mobile out of V1 priority

The target experience is desktop-first (responsive from 12 inches to ultra-wide). Mobile is
explicitly out of priority for V1.

### 4.5 No generic SQL route, no Flow at runtime

The frontend never chooses the table, the connection or the query: no generic SQL route is
exposed. At runtime, there is no Flow orchestration, with the sole exception of the execution
trace, appended write-only to an optional Flow dataset. See
[ADR-0003 - Direct SQL, no Flow at runtime](../08-decisions/0003-sql-direct-sans-flow.md).

### 4.6 Evidence Studio v1: to be refined

> IN FLUX: Evidence Studio v1 works (the agent's SELECT is replayed read-only on the
> source dataset), but the user has indicated that "it works well, but not yet the way he wants".
> The precise adjustments (labels, badge, layout, drill) have not yet been gathered and
> are to be clarified before any evolution. The full panel with six tabs (Evidence, Dataset, Chart,
> SQL, Trace, Cost) is deferred (see section 6).

### 4.7 Attribute lookup: in transition

> IN FLUX: attribute lookups (for example "who is the account manager of account X?") are
> being rewired. The old managed tool `dataset_lookup` (`9FEzVZk`) and its `lookup` intent have
> been entirely REMOVED from the code (they no longer appear in the sub-agent). Its replacement,
> `attribute_lookup` (`tools/attribute_lookup_tool.py`), is built and tested: it is a standalone Custom
> Python tool that filters in read-only SQL across all text columns of the dataset (case-insensitive
> and accent-insensitive search, nothing loaded in memory). The Custom Python tool object already
> EXISTS in DSS.
>
> On the orchestrator side, `attribute_lookup` is wired as a built-in tool (dispatched inline in
> `node_tools`), but the built-in becomes operational only after the orchestrator is re-pasted into
> DSS. `LOOKUP_TOOL_ID = ""` means the tool is resolved by name on each run (no direct id bind
> needed). As long as the orchestrator has not been re-pasted, the call is never reached and the
> orchestrator falls back to the specialist (the answer still succeeds, via the slower semantic path).
> Since the repo is being edited live, this status can change; check the state of `LOOKUP_TOOL_ID`
> and whether the orchestrator has been re-pasted at the time of testing.

### 4.8 Single-process assumption

The backend assumes a single process (an in-memory runs dictionary, bootstrap of the first admin).
This is an operational condition, not a feature. Guardrails bound the load:
a maximum of 8 concurrent runs (beyond that, the backend answers "busy"), eviction of orphan runs by TTL,
and a run is queryable only by its owner.

---

## 5. What is a matter of configuration (and its side effects)

Some visible behaviors depend on the webapp configuration in the DSS Settings.

| Parameter (`webapp.json`) | Effect |
|---|---|
| `sql_connection` | PostgreSQL SQL storage connection. As long as it is not chosen, the app displays "storage not configured" and does not work. |
| `table_prefix` | Optional prefix (16 characters max) inserted after the project key. A prefix that is too long or invalid is ignored. |
| `traces_dataset` | Optional Flow dataset where the final trace of each run is appended. A missing or incompatible dataset never breaks the chat: the trace is simply skipped. |
| `log_level` | Verbosity of the backend logs (DEBUG / INFO / WARNING, default INFO). |

> IN FLUX: the per-mode LLM Mesh model ids (`GEMINI_FLASH_LITE_ID`, `GEMINI_FLASH_ID`,
> `SONNET_ID`) must match the instance's LLM Mesh connection. A wrong id breaks the corresponding
> mode (for example, if the Flash-Lite id is wrong, eco mode, which is the default, no longer answers).
> To be verified in DSS. See [Per-mode models](../08-decisions/0009-modeles-par-mode.md).

For the detail of the parameters and the first commissioning, see
[Installation and configuration](../06-operations/01-installation-and-configuration.md).

---

## 6. Roadmap (decided, deferred)

This snapshot lists what is framed but not yet delivered. The order is not a date commitment.

- **Wire `attribute_lookup` fully**: re-paste the orchestrator into DSS so the built-in dispatch
  becomes live (the Custom Python tool already exists in DSS; `LOOKUP_TOOL_ID = ""` means name
  resolution is used by default, no id update required).
- **Validate the budget cap on DSS**: the enforcement is coded (HTTP 402, `storage/budget.py`,
  `webapp_user_quota_v1`); a smoke-test on the live instance is still needed.
- **Tickets agent**: add two recipes, a Code Agent and a registry entry; this unblocks
  the parallel multi-agent 360 analysis.
- **Full Evidence Studio (six tabs)**: Evidence, Dataset explorer (lazy loading,
  sample warning), Chart (line / bar / grouped / stacked / KPI / donut), collapsed SQL,
  Trace (user view and debug view), Cost (tokens, estimated cost, per agent).
- **Multi-agent 360 analysis**: single conversation, global timeline, one Evidence space per agent,
  the active agent loaded lazily.
- **Export and report**: Markdown, PDF, PowerPoint, 360 client sheet, email; new artifacts
  (image, map, slide, Excel); Admin registry page; agent evaluation (golden questions,
  benchmark).
- **Continuous alignment of the Semantic Model**: keep the model aligned (Phase `ACTUALS`, offer
  hierarchy, golden queries) via `tools/semantic_model/`.

The `DRIVE_Revenues_Value_Catalog` (richer alias catalog) and the Python resolver
`Drive_Revenues_resolve_filter_value` are part of the roadmap: they are NOT wired in v3.

---

## See also
- [Product overview](01-product-overview.md) - the problem solved and the value proposition.
- [Glossary](03-glossary.md) - the canonical terminology (orchestrator, sub-agent, grounding,
  Evidence, mode, Phase, capability gap).
- [Architecture overview](../02-architecture/01-system-overview.md) - the four layers and
  the system context.
- [Streaming and run lifecycle](../04-backend/03-streaming-and-runs.md) - why the transport
  is polling-based and not SSE.
- [Agent system - overview](../05-agents/01-agent-system-overview.md) - orchestrator,
  sub-agent and the central invariant.
- [ADR-0002 - Polling-based streaming](../08-decisions/0002-streaming-par-polling.md) - the
  transport decision.
- [Installation and configuration](../06-operations/01-installation-and-configuration.md) - the
  parameters that condition what the system does.
