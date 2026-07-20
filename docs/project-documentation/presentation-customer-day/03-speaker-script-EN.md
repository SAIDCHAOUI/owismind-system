# OWIsMind - Dataiku Customer Day - Speaker Script (EN)

> Spoken script, to deliver on stage. About 15 minutes, 7 frames (title + 5 core + close).
> Read it out loud, do not read it from the screen. The slide carries the spine, you carry the story.
> Timing cues are per slide. Total budget lands near 15 minutes.
> Typography rule respected throughout: no em dash, no en dash, anywhere.
>
> Delivery notes:
> - [PAUSE] = breathe, let it land. [CLICK] = advance the slide.
> - Bracketed asides like (look at the room) are stage directions, do not say them.
> - When you say a number, slow down. Numbers are the whole point of this product.

---

## Slide 0 - Title: "OWIsMind, the self-serve AI analyst that shows its receipts" (~1 min)

(walk on, let the title sit for a second, then start calm and warm)

Good morning, everyone. Thank you for having me.

I want to start with a promise, because the whole product is built around one. The promise is this: you ask a business question in plain language, you get a figure in euros, and you see the receipt behind every single number. The figure, and the proof. [PAUSE]

That product is called OWIsMind. It is a chat portal for business users, packaged as a Dataiku DSS plugin. Under the hood it is a Vue 3 webapp, a Flask backend, two LangGraph agents on the LLM Mesh, and direct SQL on PostgreSQL. All of it built end to end on Dataiku.

But here is the line I really want you to leave with today, and I am putting it up front so it colors everything else. [CLICK]

OWIsMind is not just a webapp. It is not just an agent. It is a system. [PAUSE] Four ordinary Dataiku primitives, snapped together, that become something none of them could be alone.

(point at the four tiles assembling into one block)

Today it answers one domain: Orange telecom revenue, on a dataset called DRIVE_Revenues. And in the next fifteen minutes I am going to tell you the story of that system in five beats: the problem, the idea, the product, one honest technical deep dive for this room, and where it goes next.

Let's start with the problem.

---

## Slide 1 - The Friday ping: a number you wait for, and dare not trust (~2 min)

[CLICK]

Picture a Friday afternoon. A salesperson pings you: "what did this account actually bill this year?" Simple question. They need it for Monday. [PAUSE]

And here is the frustrating part. The answer exists. It is sitting right there in DRIVE_Revenues: about 175,000 rows, 20 columns, five different scenarios in a single column called Phase. The number is in the data. It is just locked behind SQL.

And on the business side, writing SQL is a rare skill. So what happens? They wait. They open a ticket, they queue behind an analyst, and a one-line question turns into a two-day wait. That is obstacle number one: speed. (beat)

Now, you might think, fine, that is exactly what an AI assistant is for. Plug an LLM on the warehouse and let it answer. And that brings us to obstacle number two, which is the hard one. [PAUSE]

You cannot put a possibly-invented number in a board deck. A hallucinated euro is not a cute mistake. It is a career risk for the person who presented it. Speed without trust is worthless here.

And this domain punishes you for getting it wrong. Two quick traps. (hold up one finger) You must never sum across scenarios: actuals plus budget plus forecast in one total is nonsense. (second finger) And you must never default to the lowest offer level, sirano_product, because the budget rows simply do not have it, so a total silently collapses to zero. Zero. And it looks perfectly confident while it does it.

So here is the reframe, and it is the hinge of this whole talk. [PAUSE] The hard part is not generating the answer. The hard part is trust.

---

## Slide 2 - The insight: don't promise trust, build it into the structure (~2.5 min)

[CLICK]

So how does the industry usually chase trust? With a better prompt. You write "please be accurate, do not make things up, cite your sources," and you hope the model behaves. [PAUSE]

That is a promise. It is not a guarantee. And on a board number, the difference between a promise and a guarantee is the whole game.

OWIsMind makes a different bet. The bet is: do not promise trust, build it into the structure. Make trust a structural property of the architecture, not a request in a prompt. (let that land)

Let me make that concrete, because this is the heart of the design. [CLICK]

The orchestrator, the agent that talks to the user, holds no business figure. Ever. It physically does not have the revenue data. So inventing a number is not something it is forbidden to do, it is something it is structurally incapable of doing. There is nothing to hallucinate from. [PAUSE]

Every figure you ever see comes from a sub-agent that pulled it out of a real SQL result. The answer and the evidence are born together, in the same breath. You cannot have one without the other.

We wrap that in what we call an honesty firewall, and it lives in the agent's persona. Three rules. (count them) One: it never says "the data does not exist." The only "no" it is allowed to give is an honest "I do not have an agent for that domain yet." A capability gap, not a denial of reality. Two: no mental arithmetic, ever. It does not add two numbers in its head, it asks a tool. Three: it treats every tool result as untrusted input, to be checked, not assumed.

And the discipline goes all the way into the pixels. (point at the badge) In the Evidence panel, the verification badge is never green. Solid means certified, dotted means partial, gray means declared. There is no green "trust me" state, because the interface itself refuses to give you false assurance. [PAUSE]

That is the idea. Now let me show you what it actually feels like.

---

## Slide 3 - The product: a near-SaaS analyst, and the differentiating trio (~2.5 min)

[CLICK]

You open OWIsMind and you land straight in a chat. You ask your question. The orchestrator writes back a real analysis, in your language, in euros, with the scope spelled out: which scenario, which period, which entity. No "here is a number," it tells you exactly what it measured. [PAUSE]

And then there is the part I am proud of, which I call the differentiating trio. Three things working as one experience. (point to the three panes)

First, the Conversation: the figure plus a written analysis you can actually read and paste into a deck.

Second, the live Execution Timeline. You watch the agent work in real time, with human-readable step labels. It is not a spinner that says "thinking." You see it ground the terms, write the query, run it. The work is visible.

Third, and this is the one, Evidence Studio. The receipt panel. It opens by itself, and it re-derives, with zero LLM, exactly how the answer was produced. [PAUSE] The badge, the sources, the filters as editable chips, the exact captured result, the SQL folded away for the curious, and interactive charts. (beat) And I want to be precise about that "zero LLM." The proof is not the model telling you a second time that it was right. It is the stored SQL, replayed deterministically. The receipt is real because it is not generated, it is recomputed.

And around all of that, this already behaves like a finished SaaS. French and English. Light and dark theme. Per-message feedback. Conversation branches. Stop-generation mid-run. And a small line under every answer showing tokens in, tokens out, and the estimated cost. [PAUSE]

One more thing on cost, because this matters for a real deployment. The user picks a mode: eco, medium, or high. That choice drives which model runs. Eco is the default. So out of the box, it stays cheap. You pay for the big model only when you ask for it.

So that is the product. Now, this is a room full of engineers, so let me earn it. Let me open the hood.

---

## Slide 4 - The deep dive: the four-layer system that earns the trust (~4 min)

[CLICK]

(slightly different gear here, a touch slower, more precise, this is your home turf)

This is the most technical slide, and I am going to stay on it the longest, because this is where the "system, not a feature" claim gets proven. [PAUSE]

Four layers, and the trick is that each one has a narrow contract. A Vue 3 single-page app and a Flask backend, on Python 3.9. Two LangGraph Code Agents on the LLM Mesh, on Python 3.11. And direct SQL on PostgreSQL. No Flow at runtime, except one write-only trace. (beat) And here is the headline: each hard problem is solved by a different layer, cooperating. That is exactly why the whole beats the parts. Let me give you four of those problems.

(one)

Grounding. When a user types a client name or an offer term, we have to anchor that word to an exact cell value in the data, or every downstream filter is garbage. And here is the part engineers always ask about: grounding is not a tool. [PAUSE] It is read-only inline SQL, on a value index we built called DRIVE_Revenues_value_index, about 3,600 distinct values. Three passes: exact match first, then a fuzzy LIKE, then a difflib last chance for typos. And crucially, that expertise, the profile and the value index, is fabricated at design time, by Flow recipes. It is human-reviewable. It is never hard-coded in the agent. The Flow builds the knowledge, the agent consumes it.

(two)

The Semantic Model owns the SQL. The analytical query, the real one, is written and run by the only genuine runtime tool: revenue_semantic_query, on a Sonnet-class model, in every mode. [PAUSE] And there is a lesson baked into that decision. Early on, the sub-agent tried to dictate the column itself, and on one query for an EVPL budget it pinned the wrong level and the budget came back as zero. A confident, wrong zero. So we changed the contract: the sub-agent assists with hints, it never dictates. The strong model owns the SQL. The little agent helps, it does not overrule.

(three)

Streaming is polling, on purpose. And every Dataiku engineer in this room is going to recognize this war story. [PAUSE] We wanted server-sent events, token by token. But DSS puts an nginx in front of the backend, and it buffers SSE. So the live stream just sat there and arrived all at once. The fix: the agent runs in a bounded worker thread, and the frontend polls a process dictionary every 500 milliseconds or so. So the genuinely live thing you watch is the timeline, not word-by-word text. We stopped fighting the proxy and made the timeline the live surface instead.

(four)

Signal versus data. When the agent wants to draw a chart, the artifact event it emits carries only a spec: the kind, the title, the chart definition. It never carries the rows. [PAUSE] The actual Chart.js payload is rebuilt server-side, in trusted Python, from the result we already captured. Which means if the agent mistypes a column, the worst case is an honest empty chart, not a beautiful fake one. The model proposes the shape, trusted code supplies the data.

And wrapping all of it, instance-safety bounds, because this runs on a shared Dataiku instance and I am not going to be the person who takes it down. Maximum 8 concurrent runs. A 300-second deadline. Read-only transactions with a statement timeout. [PAUSE]

Four problems, four different layers, one cooperating system. (look up from the diagram) That is the engineering. Let me come back up and show you that it actually works.

---

## Slide 5 - Proof and the kicker: validated in DSS, a platform not a one-off (~2.5 min)

[CLICK]

First, the honest status. This is real, and it is validated in DSS on the revenue domain. The full chat turn, the live timeline, the Evidence replay, the Chart.js artifacts: all of it runs end to end on the instance. Not a mockup. [PAUSE]

And the engineering lives in version control. The repository is the source of truth. The two Code Agents are pasted by hand into DSS, on the 3.11 environment, but the code, the tests, and the reviews live in the repo. This is not a pile of clicks I cannot reproduce.

Now let me be equally honest about the scope, because that honesty is the product. (lean in) Today, one domain is staffed: revenue. If you ask about tickets, or satisfaction, or delivery, or billing, OWIsMind does not invent an answer. It gives you a clean capability gap: "I do not have an agent for that yet." [PAUSE] That is the firewall from slide two, doing its job in production. The budget cap, the 50-euros-a-month guardrail, its storage is ready and enforcement is a deliberate next step. I would rather tell you that than pretend.

And here is the kicker, the part that turns a single-domain demo into a platform. [CLICK]

How do you staff a new domain? You wire the same Flow recipes onto a new dataset. You duplicate the sub-agent and change two dataset names. And you add one entry to a registry called CAPABILITIES. (hold up one finger) One line. No rewrite. The webapp does not change, the storage does not change, the streaming does not change. [PAUSE]

That is the SaaS-on-Dataiku promise. And that one-line extensibility is exactly what unlocks the vision: a parallel multi-agent "360." One question, several specialists answering at once, one conversation, one Evidence space per agent. The plumbing for that is already in place. It is just waiting for the second domain.

---

## Slide 6 - Close: the whole is greater than the parts (~1 min)

[CLICK]

(settle, slow down, this is the landing)

So let me put it back together in one breath. A webapp served by DSS. Agents on the LLM Mesh. Flow recipes that fabricate the expertise at design time. Direct SQL for storage. Four primitives, wired together by narrow contracts, into one product you can actually trust. [PAUSE]

And here is the thing. Each of those primitives, on its own, is ordinary. You all have them. The composition is what makes a number provable.

OWIsMind is not a webapp. It is not an agent. It is not a recipe. It is the system you get when you stop building features, and you start composing primitives. [PAUSE] And the quiet punchline is this: on Dataiku, those primitives were already in your hands.

(look up at the room, deliver this one cleanly)

We did not make AI talk about revenue. We made it accountable for every euro it shows. [PAUSE]

The whole is greater than the parts. Thank you.

(thank-you card up, hold for applause, then take questions)

---

## Q&A honesty notes (not spoken, for the speaker)

Keep the same trust posture in answers. If asked:
- Scope today: v3 staffs a single domain (revenue). The others return an honest capability gap by design.
- Budget cap: stored, not yet enforced. Enforcement is the deliberate next step.
- Multi-agent 360: the plumbing is wired, it awaits a second staffed domain.
- Why polling and not SSE: the DSS nginx buffers SSE, so the live surface is the timeline, by design.
- Why a strong model owns the SQL: a real EVPL budget-equals-zero bug taught us the sub-agent assists, never dictates.

This honesty is on brand. It is the same posture the product itself takes.
