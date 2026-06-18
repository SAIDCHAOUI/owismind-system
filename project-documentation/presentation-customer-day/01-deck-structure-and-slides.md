# OWIsMind - Dataiku Customer Day deck (structure and slides)

> Brief for slide generation. Audience of THIS document: the script writers (FR and EN) and
> whoever generates the final slides. Last updated: 2026-06-18. Everything here is grounded in the
> real OWIsMind project documentation: no invented metric, no invented customer. The only business
> domain is Orange / OWI telecom revenue analytics on `DRIVE_Revenues`.

---

## 1. The pitch at a glance

| Item | Value |
|---|---|
| Event | Dataiku Customer Day (a customer experience-sharing event) |
| Audience | Dataiku people, technical profiles: data scientists, ML / data engineers, solution designers |
| Speaker | The project owner (founder voice) |
| Total time | About 15 minutes |
| Format | Title slide + 5 core slides + closing slide (7 frames, 1 big diagram per slide max) |
| Tone | Entrepreneur / founder pitch: accessible, lively, storytelling energy, still professional and credible. Almost a SaaS product, built entirely on Dataiku. Goes technical in ONE deep-dive section, but stays a story, never a lecture. |

**Logline (one line, say it on slide 0 and again at the close):**

> OWIsMind is a self-serve AI revenue analyst, built end to end on Dataiku, that answers a business
> question in plain language and shows the receipt behind every euro, because trust is wired into
> the architecture, not promised in a prompt.

**The central message (non-negotiable, it is the spine of the whole talk):**

> OWIsMind is NEITHER just a webapp NOR just an agent. It is a SYSTEM that composes four Dataiku
> primitives: a Vue 3 webapp served by DSS, an agent layer (orchestrator + sub-agent) on the LLM
> Mesh, design-time Flow recipes that fabricate the expertise, and direct SQL storage. The whole is
> greater than the parts. The talk tells the STORY of that system.

**How the three source arcs are blended (so the owner can defend the choices):**

- Founder framing carries slides 0 to 2 (the pain, the counter-intuitive insight, the product).
- The system-composition thesis is the spine across ALL slides (every slide shows a layer and the
  contract that snaps it to the next). It owns slides 0, 1, 5 and the close.
- The engineering story is the gold for the single technical deep-dive (slide 4): four hard problems,
  each solved by a DIFFERENT layer cooperating.

---

## 2. The narrative arc in one paragraph

We open on the founder pain (a business user waits days for one revenue number they dare not trust),
then reveal the counter-intuitive insight that reframes the whole AI-analyst category: the hard part
is not generating the answer, it is making it trustworthy, so trust must be a STRUCTURAL property of
the architecture, not a promise in a prompt. From there we reveal the product (a near-SaaS self-serve
analyst with its differentiating trio of Conversation + live Timeline + Evidence Studio) and name the
thesis out loud: this is a SYSTEM of four Dataiku primitives, not a feature. We earn the technical
room's respect with ONE honest deep-dive into the four-layer machinery (the honesty firewall, grounding
that is NOT a tool, the Semantic Model owns the SQL, streaming-by-polling because the DSS proxy buffers
SSE, signal versus data in Evidence), then we land on proof (validated in DSS on the revenue domain) and
the founder kicker that turns a single-domain v3 into a platform: to staff the next domain we add one
entry to a registry, no rewrite. Close on the thesis: a system, built on Dataiku, where the whole is
greater than the parts.

---

## 3. Slide-by-slide detail

> For each slide: TITLE, a one-line objective, the EXACT on-slide content (slide-ready short lines, not
> paragraphs), a VISUAL / DIAGRAM direction, a time budget, and the 3 to 4 talking points that anchor
> the FR and EN scripts. Keep the slide text spare: the speaker carries the story, the slide carries
> the spine.

### Slide 0 (title) - "OWIsMind: the self-serve AI analyst that shows its receipts"

- Objective: set the founder tone in one breath and plant the SYSTEM thesis before a single detail.
- Time budget: 1 min.

On-slide content:
- OWIsMind - the self-serve AI revenue analyst that shows its receipts.
- Tagline: the number AND the receipt.
- A business AI-agent chat portal, packaged as a Dataiku DSS plugin (id `owismind`, v0.0.1).
- Built end to end on Dataiku: Vue 3 webapp, Flask backend, two LangGraph Code Agents on LLM Mesh,
  direct SQL on PostgreSQL.
- Not just a webapp. Not just an agent. A SYSTEM.
- Domain today: Orange / OWI telecom revenue (`DRIVE_Revenues`).

Visual / diagram:
- Full-bleed dark slide, light Orange accent. Product name large, tagline beneath.
- Four small glowing tiles (Webapp, Agents, Flow recipes, SQL) drifting at the top, snapping into one
  solid block labeled SYSTEM at the bottom. This is the seed of the layered diagram reused on slides 1,
  4 and the close.

Talking points (anchor the scripts):
1. Introduce yourself and the one-line promise: ask in plain language, get a figure in euros, see the
   receipt behind every number.
2. State the thesis immediately: this is a system, not a webapp and not an agent, and it runs entirely
   on Dataiku.
3. Set expectations: a short story in five beats - the problem, the idea, the product, one deep
   technical dive, and where this goes next.

### Slide 1 (core 1) - "The Friday ping: a number you wait for, and dare not trust"

- Objective: make the room feel the problem before any solution. Two obstacles, one stake.
- Time budget: 2 min.

On-slide content:
- A salesperson pings you on a Friday: "what did this account actually bill this year?"
- The figure lives in `DRIVE_Revenues` (about 175,000 rows, 20 columns, 5 scenarios in `Phase`).
- Obstacle 1: writing SQL is a rare skill on the business side, so people wait days for an analyst.
- Obstacle 2: even when an AI answers, you cannot put a possibly-invented number in a board deck.
- Real traps in the data: never SUM across scenarios, never default to the lowest offer level
  `sirano_product` (BUDGET rows lack it, so a total silently drops to zero).
- The reframe: the hard part is not generating the answer. The hard part is TRUST.

Visual / diagram:
- Split screen. Left: a Slack-style bubble "what did this account actually bill this year?" with a
  ticking clock. Right: a wall of raw SQL with a red "is this number real?" stamp. A diagonal slash
  separates wait-time from trust.

Talking points:
1. Tell the Friday-ping story as a lived scene: the number exists, it is just locked behind SQL the
   business side cannot write, so they wait.
2. Name the second, harder obstacle: speed without trust is useless, because a hallucinated euro in a
   board deck is a career risk.
3. Use one concrete data trap (never SUM across `Phase`; never default to `sirano_product`, where
   BUDGET rows have no value and a total collapses to zero) to prove the domain is genuinely hard.
4. Land the reframe: the real problem is not generation, it is trust.

### Slide 2 (core 2) - "The insight: don't promise trust, build it into the structure"

- Objective: the aha moment, the hinge of the talk. Turn the pain into a principle the technical room
  will nod at.
- Time budget: 2.5 min.

On-slide content:
- Most AI tools chase trust with a better prompt, hoping the model behaves. That is a promise, not a
  guarantee.
- OWIsMind's bet: make trust a STRUCTURAL property.
- The orchestrator holds NO business figure, ever, so it structurally cannot invent a number.
- Every figure comes from a sub-agent that pulled it from a real SQL result: answer and evidence are
  born together.
- The honesty firewall (in the persona): never "the data does not exist", only an honest "no AGENT yet
  for this domain" (a capability gap); no mental arithmetic; tool results treated as untrusted input.
- The product tell: the Evidence badge is NEVER green (solid = certified, dotted = partial, gray =
  declared). The UI itself refuses false assurance.

Visual / diagram:
- One bold diagram: a locked gate labeled "Honesty firewall" between the orchestrator (a no-data icon)
  and the figures, with the ONLY allowed path going through an "SQL-grounded sub-agent". A crossed-out
  green checkmark in the corner, caption "never green".

Talking points:
1. Contrast the industry default (trust as a prompt wish) with the OWIsMind bet (trust as a structural
   constraint).
2. Explain the firewall plainly: the orchestrator literally never holds the data, so inventing a number
   is not forbidden by a rule it might break, it is impossible by construction.
3. Name the honest "no": a capability gap ("no agent yet for tickets") is allowed; denying the data
   exists is forbidden. Only a specialist, after looking, can say a figure is missing.
4. Land the never-green badge as proof the discipline reaches all the way into the UI.

### Slide 3 (core 3) - "The product: a near-SaaS analyst, and the differentiating trio"

- Objective: the product reveal. Show what the user gets, why it feels like finished SaaS, and pay off
  the "system, not a feature" thesis with the three pillars working together.
- Time budget: 2.5 min.

On-slide content:
- You land straight in a chat, ask a question, the orchestrator writes the analysis in your language,
  in euros, with the scope spelled out (scenario, period, entity).
- The differentiating trio:
  - Conversation: the figure plus a written analysis.
  - Live Execution Timeline: you watch the agent work, with human-readable step labels.
  - Evidence Studio: the receipt panel that opens automatically.
- Evidence Studio re-derives, with ZERO LLM, how the answer was produced: badge, sources, filters as
  editable chips, the exact captured result, the collapsed SQL, interactive Chart.js charts.
- Already behaves like a product: FR / EN, light and dark theme, per-message feedback, conversation
  branches, stop-generation, a tokens-in / out / estimated-cost line under every answer.
- Cost modes the user picks (eco / medium / high) drive the model; eco is the default, so it stays
  cheap by default.

Visual / diagram:
- A realistic three-pane product screenshot (or high-fidelity mock): conversation sidebar on the left,
  the euro-formatted answer with its scope line in the center, Evidence Studio open on the right with a
  never-green badge, editable filter chips, and a bar chart. Annotate the three panes as the trio.
- Reuse the differentiating-trio flow (Question -> Conversation / Timeline / Evidence) if a second small
  diagram is wanted, but keep ONE big visual.

Talking points:
1. Walk one real turn: land in the chat, ask, get an answer in euros with its scope line spelled out
   (scenario, period, entity).
2. Present the trio as one experience: the analysis you read, the agent you watch work live, and the
   receipt that opens by itself.
3. Stress that Evidence re-derives everything deterministically, with zero extra LLM call: the proof is
   not the model's word, it is the stored SQL replayed.
4. Note the SaaS finish (FR/EN, themes, feedback, branches, stop, per-answer cost) and that eco is the
   cheap default.

### Slide 4 (core 4, THE DEEP DIVE) - "Under the hood: the four-layer system that earns the trust"

- Objective: the one slide that goes deep for this crowd. Earn the engineers' respect with the real
  machinery and the honest hard choices, then surface back to the story. This is the engineering-story
  arc, distilled to four cracked problems, one per layer.
- Time budget: 4 min (the longest beat; this is where the technical audience leans in).
- `is_deep_dive: true`

On-slide content:
- Four layers, narrow contracts: Vue 3 SPA + Flask backend (Python 3.9), two LangGraph Code Agents on
  LLM Mesh (Python 3.11), direct SQL on PostgreSQL. No Flow at runtime (except a write-only trace).
- Grounding is the trick, and it is NOT a tool: user terms are anchored to EXACT cell values via
  read-only inline SQL on `DRIVE_Revenues_value_index` (about 3.6k values) - exact match, then fuzzy
  LIKE, then a difflib last chance. The expertise itself is fabricated design-time by Flow recipes (a
  profile and a value index), human-reviewable, never hard-coded.
- The Semantic Model owns the SQL: the only real runtime tool, `revenue_semantic_query` (`v4oqA6R`),
  WRITES and RUNS the analytical SQL on a Sonnet model in every mode. The sub-agent assists with hints,
  it never dictates the column.
- Streaming is polling, on purpose: DSS puts an nginx in front of the backend that buffers SSE, so the
  agent runs in a bounded worker thread and the frontend polls a process dict every ~500 ms. The
  genuinely live view is the timeline, not word-by-word text.
- Evidence = signal vs data: an artifact event carries only a spec `{kind, title, chart}`, never the
  rows. The Chart.js payload is rebuilt server-side in trusted Python from the captured result, so a
  mistyped column degrades to an honest empty state, never a fake chart.
- Instance-safety bounds everywhere: max 8 concurrent runs, a 300s deadline, read-only +
  statement_timeout.

Visual / diagram:
- THE canonical four-layer architecture diagram (reuse the system-context diagram from the docs): user
  -> Vue SPA -> Flask, Flask over native LLM Mesh -> orchestrator -> revenue sub-agent, sub-agent doing
  inline-SQL grounding on the value index then the Semantic Model tool writing analytical SQL on
  `DRIVE_Revenues`, Flask persisting to PostgreSQL. Flow recipes drawn dotted as design-time only.
- Three callouts pinned on the diagram: "grounding is NOT a tool", "the model owns the SQL", "polling,
  not SSE". Optionally a fourth: "signal vs data".

Talking points:
1. Frame the four layers as four narrow contracts, then make the headline point: each hard problem is
   solved by a DIFFERENT layer cooperating, which is exactly why the whole beats the parts.
2. Grounding: user words are anchored to exact cell values by read-only inline SQL on the value index
   (exact, then fuzzy, then difflib) - it is not a tool, and the expertise was fabricated design-time by
   Flow recipes, reviewable by a human, never hard-coded.
3. The Semantic Model owns the SQL (`revenue_semantic_query`, `v4oqA6R`, Sonnet in all modes); tell the
   real EVPL budget-equals-zero bug to show why the sub-agent assists rather than dictates.
4. The war story every Dataiku engineer recognizes: SSE was buffered by the DSS proxy, so streaming is
   polling-via-thread, bounded (8 runs, 300s); and signal-vs-data means a mistyped column degrades to an
   honest empty chart, never a fake one. Then surface back to the story.

### Slide 5 (core 5) - "Proof and the kicker: validated in DSS, a platform not a one-off"

- Objective: traction and vision. Show it is real and running, then deliver the SaaS-on-Dataiku
  punchline that turns a single domain into a platform.
- Time budget: 2.5 min.

On-slide content:
- Real and validated in DSS on the revenue domain: full chat turn, live timeline, Evidence replay and
  Chart.js artifacts run end to end on the instance.
- Repo is the source of truth: the two Code Agents are pasted by hand into DSS (3.11 env), so the
  engineering, tests and review live in version control.
- Honest scope, on purpose: one staffed domain today (revenue). Other domains (tickets, satisfaction,
  opportunities, delivery, billing) answer with a capability gap, never a fake answer. The budget cap
  has its storage ready; enforcement is a deliberate next step.
- The platform kicker: staffing a new domain = wire the same Flow recipes onto a new dataset, duplicate
  the sub-agent (change two dataset names), add ONE entry to the `CAPABILITIES` registry. No rewrite.
- The vision: that one-line extensibility unlocks the multi-agent "360" analysis - one question,
  several specialists in parallel, one conversation, one Evidence space per agent.

Visual / diagram:
- Left: a "Live in DSS" badge over a small montage of the running app.
- Right: a before / after of the `CAPABILITIES` registry where adding "tickets" is literally one new
  line, with an arrow to a future 360 view showing two agents fanning out from one question. The rest of
  the stack (webapp, recipes, storage) shown UNTOUCHED.
- Bottom band repeats the closing line: "A system. Built on Dataiku."

Talking points:
1. Establish traction honestly: it runs end to end in DSS on the revenue domain, and the repo (not
   scattered UI edits) is the source of truth.
2. Own the scope with confidence: one staffed domain, and the unstaffed ones answer with an honest
   capability gap rather than a fake answer - that honesty IS the product.
3. Deliver the kicker: a new domain is one registry entry plus the same recipes on a new dataset, no
   rewrite, which is the SaaS-on-Dataiku promise.
4. Point at the vision: that one-line extensibility is what unlocks the parallel multi-agent 360.

### Slide 6 (closing) - "The whole is greater than the parts"

- Objective: re-assemble the system thesis with founder conviction, return to the opening promise, and
  leave the room with the founder line.
- Time budget: 1 min.

On-slide content:
- Recap in one breath: a webapp served by DSS, agents on the LLM Mesh, recipes that fabricate the
  expertise, direct SQL - wired by narrow contracts into one trustworthy product.
- Each primitive was ordinary on its own. The composition is what makes a number provable.
- Not a webapp, not an agent, not a recipe. The SYSTEM you get when you stop building features and start
  composing primitives.
- On Dataiku, the primitives were already in your hands.
- Closing founder line: we did not make AI talk about revenue, we made it accountable for every euro it
  shows.

Visual / diagram:
- Callback to the title slide: the four primitive tiles (Webapp, Agents, Recipes, SQL) snap together one
  last time into the solid OWIsMind block, with "THE WHOLE > THE PARTS" centered. The four-layer diagram
  fully lit. End card with the plugin id and a thank-you line.

Talking points:
1. Recap the four layers and the one job each, fast, as a single system.
2. Land the thesis: ordinary primitives, extraordinary composition - that is what makes every euro
   provable.
3. Hand the audience ownership: you already own these bricks on Dataiku; the only question is what system
   you snap them into next.
4. End on the founder line, then thank them.

---

## 4. Visual and design note

- One big diagram or one big screenshot per slide, never two. The slide carries the spine, the speaker
  carries the story.
- Clean, technical, premium. Dark canvas, light Orange brand accent used sparingly (one accent color, not
  a rainbow). Generous whitespace, large type, short lines.
- Reuse two recurring visuals so the deck feels like one system assembling itself:
  - the four-primitive tiles that snap into one block (slides 0 and 6),
  - the four-layer system-context diagram (slides 1 background hint, 4 full, 6 fully lit).
- The Evidence "never green" badge is a motif: show the three-state badge (solid / dotted / gray) wherever
  trust is discussed (slides 2 and 3).
- Slide-ready text only: 4 to 6 short lines per slide, no paragraphs on the slide itself.
- Accessibility: high contrast, no reliance on color alone (pair the badge states with labels).
- TYPOGRAPHY RULE (non-negotiable): never use an em dash (U+2014) or an en dash (U+2013), anywhere - in
  slide text, captions, notes, or the generation prompt. Use a hyphen "-", a colon ":", a comma ",", or
  parentheses.

---

## 5. Prompt to paste into claude.ai

> Copy everything in the block below into claude.ai to generate the actual slide deck.

```
You are a senior presentation designer. Generate a clean, professional, premium slide deck for a
15-minute talk at Dataiku Customer Day (a customer experience-sharing event). The audience is Dataiku
people with technical profiles: data scientists, ML and data engineers, solution designers. The speaker
is the project founder. The tone is an entrepreneur / founder pitch: accessible, lively, storytelling
energy, still professional and credible. The product is almost a SaaS, built entirely on Dataiku. The
talk goes technical in ONE deep-dive slide, but it stays a story, not a lecture.

ABSOLUTE TYPOGRAPHY RULE: never output an em dash (U+2014) or an en dash (U+2013), anywhere. Use a
hyphen "-", a colon ":", a comma ",", or parentheses instead. Re-scan the whole deck before finishing
and remove any em or en dash.

THE PRODUCT: OWIsMind, a self-serve AI revenue analyst packaged as a Dataiku DSS plugin. A business
user asks a question in plain French or English and gets a figure in euros, without writing SQL, and
sees the evidence behind every number. The domain is Orange / OWI telecom revenue analytics on a dataset
called DRIVE_Revenues. Do not invent any metric or customer beyond what is given here.

THE CENTRAL MESSAGE (the spine of the whole deck): OWIsMind is NEITHER just a webapp NOR just an agent.
It is a SYSTEM that composes four Dataiku primitives - a Vue 3 webapp served by DSS, an agent layer
(an orchestrator plus a revenue sub-agent) on the LLM Mesh, design-time Flow recipes that fabricate the
expertise, and direct SQL storage on PostgreSQL. The whole is greater than the parts. Tell the story of
that system.

LOGLINE to place on the title and the close: "OWIsMind is a self-serve AI revenue analyst, built end to
end on Dataiku, that answers a business question in plain language and shows the receipt behind every
euro, because trust is wired into the architecture, not promised in a prompt."

Produce exactly 7 slides (a title slide, 5 core slides, a closing slide). One big diagram or one big
screenshot per slide, never two. Dark canvas, a single light Orange accent used sparingly, generous
whitespace, large type, short lines (4 to 6 short lines per slide, no paragraphs on the slide). Keep a
recurring motif: four primitive tiles (Webapp, Agents, Recipes, SQL) that snap together into one solid
block labeled SYSTEM, and a four-layer architecture diagram. Show a three-state verification badge that
is NEVER green (solid = certified, dotted = partial, gray = declared) wherever trust is discussed.

The 7 slides:

0. Title - "OWIsMind: the self-serve AI analyst that shows its receipts". Tagline "the number AND the
receipt". A business AI-agent chat portal, a Dataiku DSS plugin. Built end to end on Dataiku: Vue 3
webapp, Flask backend, two LangGraph Code Agents on LLM Mesh, direct SQL on PostgreSQL. Not just a
webapp, not just an agent: a SYSTEM. Domain: Orange / OWI telecom revenue (DRIVE_Revenues). Visual: the
four tiles snapping into one SYSTEM block.

1. The problem - "The Friday ping: a number you wait for, and dare not trust". A salesperson pings on a
Friday for one revenue number. It lives in DRIVE_Revenues (about 175,000 rows, 20 columns, 5 scenarios).
Obstacle 1: writing SQL is a rare business skill, so people wait days. Obstacle 2: you cannot put a
possibly-invented number in a board deck. Data traps: never sum across scenarios, never default to the
lowest offer level (some rows lack it, a total drops to zero). Reframe: the hard part is not generating
the answer, it is TRUST. Visual: split screen, a waiting clock on one side, raw SQL with "is this number
real?" on the other.

2. The insight - "Do not promise trust, build it into the structure". Most tools chase trust with a
better prompt (a promise, not a guarantee). OWIsMind makes trust STRUCTURAL: the orchestrator holds NO
business figure, so it structurally cannot invent a number; every figure comes from a sub-agent that
pulled it from a real SQL result. An honesty firewall: never "the data does not exist", only an honest
"no agent yet for this domain"; no mental arithmetic; tool results are untrusted input. The Evidence
badge is NEVER green. Visual: a locked gate "Honesty firewall" between the orchestrator and the figures,
with the only path going through an SQL-grounded sub-agent, and a crossed-out green check.

3. The product - "A near-SaaS analyst, and the differentiating trio". You land in a chat, ask, and get
the analysis in your language, in euros, with the scope spelled out (scenario, period, entity). The trio:
Conversation (figure plus written analysis), live Execution Timeline (watch the agent work, human-readable
labels), Evidence Studio (the receipt panel that opens automatically and re-derives everything with ZERO
extra LLM: badge, sources, editable filter chips, captured result, collapsed SQL, interactive charts). It
already feels like SaaS: FR/EN, light and dark theme, feedback, conversation branches, stop, a tokens and
cost line under each answer. Cost modes eco / medium / high drive the model; eco is the cheap default.
Visual: a three-pane product screenshot (conversation, euro answer with scope line, Evidence panel with a
never-green badge, chips, and a chart), the three panes annotated as the trio.

4. The deep dive (the most technical slide) - "Under the hood: the four-layer system that earns the
trust". Four layers, narrow contracts: Vue 3 SPA plus Flask (Python 3.9), two LangGraph Code Agents on
LLM Mesh (Python 3.11), direct SQL on PostgreSQL, no Flow at runtime except a write-only trace. Grounding
is NOT a tool: user terms are anchored to exact cell values by read-only inline SQL on a value index
(exact, then fuzzy, then a difflib last chance); the expertise is fabricated design-time by Flow recipes,
human-reviewable, never hard-coded. The Semantic Model owns the SQL: the only real runtime tool writes and
runs the analytical SQL on a strong model in every mode; the sub-agent assists with hints, it never
dictates the column. Streaming is polling on purpose: DSS puts an nginx in front of the backend that
buffers SSE, so the agent runs in a bounded worker thread and the frontend polls every about 500 ms; the
live view is the timeline, not word-by-word text. Signal versus data: an artifact carries only a spec,
never the rows, and the chart payload is rebuilt server-side in trusted Python, so a mistyped column
degrades to an honest empty state, never a fake chart. Instance-safety bounds everywhere (max 8 concurrent
runs, a 300s deadline, read-only with a statement timeout). Visual: the four-layer architecture diagram
(user to SPA to Flask, Flask over LLM Mesh to orchestrator to sub-agent, sub-agent grounding on the value
index then the Semantic Model tool writing SQL on DRIVE_Revenues, Flask to PostgreSQL, Flow recipes dotted
as design-time only), with three callouts: "grounding is not a tool", "the model owns the SQL", "polling,
not SSE".

5. Proof and the kicker - "Validated in DSS, a platform not a one-off". It runs end to end in DSS on the
revenue domain (full chat turn, live timeline, Evidence replay, charts). The repo is the source of truth:
the two Code Agents are pasted by hand into DSS. Honest scope: one staffed domain today (revenue); the
others answer with a capability gap, never a fake answer. The platform kicker: staffing a new domain is
wiring the same recipes onto a new dataset, duplicating the sub-agent, and adding ONE entry to a registry,
no rewrite. The vision: that one-line extensibility unlocks a parallel multi-agent "360" (one question,
several specialists, one conversation). Visual: a "Live in DSS" badge over the running app, and a
before / after of a capability registry where adding "tickets" is one new line, the rest of the stack
untouched.

6. Close - "The whole is greater than the parts". Recap: a webapp served by DSS, agents on the LLM Mesh,
recipes that fabricate the expertise, direct SQL, wired by narrow contracts into one trustworthy product.
Each primitive was ordinary; the composition makes a number provable. Not a webapp, not an agent, not a
recipe: the SYSTEM you get when you compose primitives, and on Dataiku the primitives were already in
your hands. Founder line: "we did not make AI talk about revenue, we made it accountable for every euro
it shows." Visual: the four tiles snapping into the OWIsMind block one last time, "THE WHOLE > THE PARTS"
centered, a thank-you end card.

Deliver a clean, presentation-ready deck (one frame per slide), with speaker-ready short text on each
slide and a clear visual direction realized for each. Remember: no em dash and no en dash anywhere.
```

---

## 6. Fact-check anchors (for the script writers)

Every claim above traces to the project documentation. Quick references if a script writer needs to
verify a number or a name:

- Plugin id `owismind`, v0.0.1; webapp Vue 3 + Flask; two LangGraph Code Agents (env 3.11); direct SQL on
  PostgreSQL connection `SQL_owi`. (`README.md`, `02-architecture/01-system-overview.md`)
- `DRIVE_Revenues`: about 175,000 rows, 20 columns; measure `amount_eur` in euros; `Phase` has 5 values
  (ACTUALS default, BUDGET, FORECAST, Q3F, HLF); never SUM across scenarios; offer hierarchy Product >
  Solution > SolutionLine > sirano_product, never default to sirano_product (BUDGET rows lack it).
  (`00-overview/01-product-overview.md`)
- Honesty firewall: orchestrator holds no business figure; capability gap allowed, data denial forbidden;
  no mental arithmetic; tool results untrusted. Badge never green (solid / dotted / gray).
  (`05-agents/02-orchestrator.md`, `00-overview/01-product-overview.md`)
- Differentiating trio: Conversation + live Execution Timeline + Evidence Studio; Evidence re-derives with
  zero LLM. (`00-overview/01-product-overview.md`)
- Grounding is NOT a tool: read-only inline SQL on `DRIVE_Revenues_value_index` (about 3.6k values), three
  passes (exact value_norm IN, fuzzy LIKE, difflib last chance). (`05-agents/03-revenue-expert-subagent.md`)
- Semantic Model owns the SQL: `revenue_semantic_query` (`v4oqA6R`), the only real runtime tool, writes
  and runs the SQL on a Sonnet model in all modes; sub-agent assists, does not dictate; EVPL
  budget-equals-zero regression. (`05-agents/02-orchestrator.md`, `05-agents/03-revenue-expert-subagent.md`)
- Streaming by polling: DSS nginx buffers SSE; worker thread plus a `_RUNS` dict, poll every about 500 ms;
  bounds MAX_CONCURRENT_RUNS = 8, MAX_RUN_SECONDS = 300. (`04-backend/03-streaming-and-runs.md`)
- Signal vs data: artifact event carries only a spec, chart payload rebuilt server-side in trusted Python,
  mistyped column degrades to an honest empty state. (`04-backend/05-evidence-and-artifacts.md`)
- Per-mode models: eco = Gemini Flash-Lite (default), medium = Gemini Flash, high = Claude Sonnet; one
  model drives the whole turn, no escalation. (`05-agents/02-orchestrator.md`)
- Extensibility: adding a domain = same Flow recipes on a new dataset + duplicate the sub-agent + one entry
  in `CAPABILITIES`; one staffed domain today (revenue); 360 multi-agent is roadmap.
  (`00-overview/02-scope-and-limitations.md`)
- Repo = source of truth, Code Agents pasted by hand into DSS (3.11 env).
  (`02-architecture/01-system-overview.md`)

> Honesty for the Q&A: if asked, state plainly that v3 staffs a single domain (revenue), that the budget
> cap is stored but not yet enforced, and that the multi-agent 360 is wired but awaits a second domain.
> This honesty is on-brand: it is the same trust posture the product itself takes.
