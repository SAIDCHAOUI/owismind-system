# Orchestrator "Expert Authority" — foundation design (FROZEN CONTRACT)

> 2026-06-11. Foundation layer of the "collaborative agentic system" rework. Freezes the
> behavioural contract that stops the orchestrator from answering / denying business questions
> by itself and makes it a generic, registry-driven dispatcher for N expert sub-agents.
> Grounded in real user transcripts (`docs/questions_asked.md`): ~10 furious complaints about the
> SAME root cause ("you answered without querying the agent / you invented the data / you said 0").
> Scope chosen by the user: **Foundation only** (Levels 2 "refusals→offers" and 3 "guided
> exploration" are explicitly deferred — see §9).

## 0. Goal

Make the orchestrator **structurally incapable of asserting a business fact it did not get from a
sub-agent**, and turn it into a dispatcher that works with as many experts as we register —
add an agent = one registry entry `{key, agent_id, label, description, domain}`, the orchestrator
does the routing, collection and final formatting.

The triggering bug: a user asks "budget 2026 for Roaming Hub…", the orchestrator answers
*"I don't have access to budget data"* — **without ever calling the revenue agent**, which DOES
read the `Phase` column (`ACTUALS / BUDGET / FORECAST / Q3F / HLF`). The orchestrator denied a
capability it has, on behalf of an expert it never consulted. The transcripts show this is the
*central* defect, not an isolated case (`l.148, 149, 186, 187, 512, 765, 770, 780, 784, 812`).

Non-negotiables (inherited): no new dependency (pure Python 3.9, standalone Code Agent files),
**LLM calls kept to the minimum** (`1 plan + (0|1) synthesis` — unchanged vs today; the fix is in
the *decision*, not in added calls), no Flow at runtime, server-side agent whitelist, frozen event
kinds, no hardcoded business value in agent logic (rule P3). Streaming, Evidence trust layer,
sub-agent internals, usage tracking, sources block: **untouched**.

## 1. The honesty guarantee — three rules (the whole point)

- **R1 — Zero business fact authored by the orchestrator.** No figure, no value, no "0", no
  "this data does not exist". *Every* business fact comes from a sub-agent — relayed verbatim
  (single-agent path) or synthesized **strictly from agent returns** (multi-agent path).
- **R2 — The only "no" the orchestrator may author: "I have no agent for that".** It knows its own
  roster (legitimate self-knowledge). It NEVER says "the data does not exist / there is none" —
  only the expert, which actually queried the catalog, may say that (`out_of_scope` / `no_data`).
  The budget bug = conflating *"I lack the capability"* (false — it has the revenue agent) with
  *"the data doesn't exist"* (not the orchestrator's call).
- **R3 — When in doubt, route — do not rule.** Routing is the default action. Refusing is the
  exception, reserved for *clearly non-OWI* questions or *known domains with no agent wired*.

## 2. Intent model + the structural firewall

The leak is here: when the planner classifies a business question as `CLARIFY` / `OUT_OF_SCOPE`,
it then writes **free text** that hallucinates a business assertion. Fix: **the only text the
orchestrator authors is text that cannot, by construction, contain a business fact.**

Intent enum (ADD `CAPABILITY_GAP` and `CONCEPT`; keep the others — values travel in `PLAN_READY`
eventData, so we ADD rather than rename to avoid touching the frozen event surface):

| intent | who writes the text | guarantee |
|---|---|---|
| `BUSINESS` | the sub-agents | default for anything touching a domain that HAS an agent |
| `CAPABILITY_GAP` *(new)* | **deterministic template** from the registry | "I don't have an agent for *[tickets]* yet" + what I can do — never a figure |
| `OUT_OF_SCOPE` | **deterministic template** | polite redirect (weather, trivia) — no business assertion |
| `CONCEPT` *(new)* | LLM, bounded | general telco notion, **explicitly labelled "general knowledge"**, zero OWI-specific figure/definition |
| `GREETING` | LLM, bounded | social / personal (name, date) from session context — no business fact |
| `CLARIFY` | LLM, **hard-bounded** | ask ONE question; **never assert a value or a data limitation**; reserved for genuinely contentless input |

Key consequences:
- `CAPABILITY_GAP` and `OUT_OF_SCOPE` become **code-generated deterministic templates** — removing
  the free-text surface where the hallucination happened. The planner only *classifies* and (for
  a gap) names the matched `domain`; the message itself is rendered by code from the registry.
- `CLARIFY` remains the only business-adjacent free-text path; it is prompt-locked to
  *interrogative-only* ("ask, never assert"). The planner is told to **prefer `BUSINESS` (route to
  the expert, whose clarification is catalog-grounded) over `CLARIFY`** whenever a plausible expert
  exists — the expert already emits `need_clarification` with real candidate values.

New / changed planner prompt rules (the humility clauses), added to `build_planner_prompt`:
- "You do NOT know what the data contains. You NEVER tell the user that a metric, a scenario
  (budget/forecast/actuals/…), a figure or a record is unavailable, missing, or zero."
- "If a question concerns a business domain that HAS an agent, choose `BUSINESS` and route it —
  even if you are unsure the specific data exists. ONLY the agent can confirm or deny existence."
- "You MAY state that you lack an *agent* for a domain → `CAPABILITY_GAP` (name the domain). You
  may NEVER state that *data* does not exist."
- "Reserve `OUT_OF_SCOPE` for questions clearly unrelated to OWI business data."

## 3. Registry = manifest (extensibility + anti-drift)

### 3.1 Add an agent = one entry
Each capability entry gains a `domain` key and an accurate, broad `description` (the manifest):
```
"salesdrive_v2": {
    "kind": "agent", "agent_id": "<real id>", "domain": "revenue",
    "label_fr": "…", "label_en": "…",
    "planner_description": "<the full-truth manifest, see 3.2>",
    "enabled": True,
    # …existing keys (labels, dataset refs) unchanged…
}
```
Adding tickets/CX/opps later = one entry with its `agent_id` + `domain`. No code change.

### 3.2 Revenue manifest rewritten to the full truth (kills the budget bug at the source)
Replace the current `planner_description` ("Revenue … Data source: DRIVE_Revenues.") with a manifest
that states ALL real coverage:
> "Revenue / billing on OWI customers across **all scenarios/phases — actuals, budget, forecast,
> Q3F, HLF** — broken down by customer, product, solution, solution line, sirano product, partner,
> distribution type, sales entity, sales zone, parent group, month or year; totals, top-N rankings,
> period comparisons, **actuals-vs-budget deltas/variance**, trends, YTD. Data source: DRIVE_Revenues."

This is applied to BOTH `salesdrive` and `salesdrive_v2` entries (same underlying agent), so whichever
is live carries the truthful manifest.

### 3.3 Anti-drift guard (respects rule P3 — no business value in logic, just a test)
A repo test imports both modules (tests run in the repo, where both are importable — the *runtime*
standalone constraint does not apply to tests) and asserts the live revenue manifest still mentions
the expert's real capabilities:
```python
from salesdrive import salesdrive_agent as sd
from orchestrator import orchestrator_agent as orch

def test_revenue_manifest_covers_phases_and_axes():
    desc = orch.CAPABILITIES["salesdrive_v2"]["planner_description"].lower()
    for phase in sd.KNOWN_PHASES:            # ACTUALS, BUDGET, FORECAST, Q3F, HLF
        assert phase.lower() in desc
    # a representative sample of the real group-by axes must be advertised
    for axis in ("customer", "product", "solution", "month", "year"):
        assert axis in desc
```
If anyone shrinks the description back to "revenue only" → CI fails. The phases/axes themselves are
**sourced from the sub-agent's own constants**, never re-hardcoded in orchestrator logic.

### 3.4 Domain map (gap vs out-of-scope discrimination)
A new constant lists the business domains the product knows about, with display labels:
```
BUSINESS_DOMAINS = {
  "revenue":       {"label_fr": "revenus / CA / budget / forecast", "label_en": "revenue / billing / budget / forecast"},
  "tickets":       {"label_fr": "tickets d'incidents",              "label_en": "incident tickets"},
  "satisfaction":  {"label_fr": "satisfaction / expérience client", "label_en": "customer satisfaction / experience"},
  "opportunities": {"label_fr": "opportunités / pipeline",          "label_en": "opportunities / pipeline"},
  "delivery":      {"label_fr": "livraison (LD / SOF / déconnexions)","label_en": "delivery (LD / SOF / disconnections)"},
  "billing":       {"label_fr": "facturation",                      "label_en": "billing"},
}
```
- A question matching a domain **with** a wired agent → `BUSINESS`.
- A question matching a domain **without** a wired agent → `CAPABILITY_GAP` (deterministic message
  built from the domain label + the list of domains that DO have agents).
- A question matching **no** domain → `OUT_OF_SCOPE`.

The planner receives the domain map AND the list of domains currently staffed by an agent (derived
from the registry at runtime). Wiring an agent later auto-closes its gap with zero prompt edits.

## 4. Dispatch + synthesis (sequential now, parallel-ready) — constant LLM cost

- Execution is **unchanged**: the existing `process_stream` loop already runs N steps and synthesizes.
  Single agent → relay verbatim (**0 synthesis call**). Several sources → **1** synthesis call from
  the step returns. Net: `1 plan + (0|1) synthesis` — same as today.
- **Parallelism is deferred** (user decision): the foundation keeps sequential live-streaming
  (validated UX, minimal risk). A future Level-2 change can run `_execute_agent_step` concurrently;
  nothing in this foundation blocks that.
- **Synthesis hardened**: it writes ONLY from agent returns; if a step returned `no_data` /
  `out_of_scope` / a gap, it states that honestly for that part — never papers over with an invented
  figure. The existing `AGENT_RESULT` status (`ready | need_clarification | out_of_scope | no_data |
  error`) already carries this; the synthesis prompt and the per-step result blocks must surface it.

## 5. Concept / methodology questions (user decision: route to the expert if possible)

Frequent in the corpus: "how do you calculate the forecast" (l.284), "what are the original
datasets" (l.500), "définition d'un client perdu" (l.324), "différence SS7 vs LTE" (l.783),
"c'est quoi un whale" (l.14).

- **OWI-specific methodology / definitions** (how OWI computes a figure, what an OWI-specific term
  means in the data) → `BUSINESS`, routed to the owning agent. The expert owns its own methodology;
  the orchestrator must not improvise it.
- **General telco concepts** with no OWI specificity → `CONCEPT`: a short bounded answer **explicitly
  labelled as general knowledge**, never asserting an OWI figure or an OWI-specific definition, then
  an offer to pull the real data. One bounded LLM call (reuses the planner's `direct_answer`
  channel; no extra round-trip).
- When unsure which of the two → prefer `BUSINESS` (route). Same R3 bias.

## 6. What does NOT change (preserve the validated surface)

Streaming polling + `/chat/start`→`/chat/poll`; the frozen event-kind contract; the Evidence trust
layer (sql_explain / capture / drill); the sub-agent files' internals; the deterministic
`_sources_block`; usage/cost tracking; the relay-verbatim single-agent path. Blast radius is
confined to: `build_planner_prompt`, `PLANNER_JSON_SCHEMA`, `_validate_plan`, the non-business branch
of `process_stream`, the registry entries + new `BUSINESS_DOMAINS` constant, a few fr/en template
texts, and new tests.

## 7. Tests (proof, grounded in `questions_asked.md`)

Pure unit tests (no DSS), driven by real transcript lines:
1. **Routing — no false denial**: "Give me the budget 2026 for the Roaming Hub, …" → intent
   `BUSINESS`, one revenue step; assert NO `direct_answer` and NO digit/"budget unavailable" text.
2. **Capability gap, not invention**: "combien de tickets d'incidents on a fait avec 1&1 en 2025 ?"
   with only the revenue agent wired → intent `CAPABILITY_GAP`, domain `tickets`; message is the
   deterministic template; assert it contains NO "0" and NO figure.
3. **Out of scope**: "météo à Paris ?" → `OUT_OF_SCOPE`, deterministic redirect.
4. **Ellipsis routing**: history `[budget Roaming 2026]` then "and for Virtual Network" → `BUSINESS`
   with a self-contained instruction naming Virtual Network + budget 2026.
5. **Concept routing**: "how do you calculate the forecast" → `BUSINESS` (revenue). "différence SS7
   vs LTE" → `CONCEPT`, labelled general, no OWI figure.
6. **Anti-drift** (§3.3): manifest covers `KNOWN_PHASES` + sample axes.
7. **Firewall**: for every non-`BUSINESS` intent, the rendered orchestrator text passes a guard that
   it contains no standalone monetary/figure token presented as data (templates trivially pass; the
   `CLARIFY`/`CONCEPT`/`GREETING` prompts are asserted to forbid it).

Existing orchestrator + salesdrive unit suites must stay green.

## 8. Deployment reconciliation (one input needed from the user)

Repo registry currently has `salesdrive` (visual `rNTZ781a`, `enabled: True`) and `salesdrive_v2`
(`agent_id: FILL_ME`, `enabled: False`), but the user runs the **code agent v2** in DSS. Before/at
implementation: set `salesdrive_v2.agent_id` to the real DSS id, `enabled: True`, and disable the
visual entry — so the repo matches the live reality and the anti-drift test targets the live entry.
(The orchestrator file is re-pasted into its DSS Code Agent after the change; the sub-agent file is
unchanged by this foundation.)

## 9. Explicitly deferred (Levels 2 & 3 — NOT in this spec)

- **Level 2 — refusals → honest offers**: when an expert cannot answer exactly, return what it CAN
  do (available phases/axes/near values) and have the orchestrator turn the refusal into an offer.
- **Level 3 — guided exploration**: proactively surface answerable dimensions, propose relevant
  follow-ups, build across turns.
- **Parallel multi-agent dispatch** (faster 360s) — see §4.
- Wiring the tickets / satisfaction / opportunities / delivery / billing agents (no DSS ids yet).

These layers sit ON TOP of this foundation without reworking it.
