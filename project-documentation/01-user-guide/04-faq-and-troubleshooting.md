# FAQ and troubleshooting (user)

> Audience: OWI/Orange business user, first-level support team. Last updated:
> 2026-06-19. Summary: practical answers to frequently asked questions and the right course of action when
> facing common situations (an uncovered domain, a long answer, a stopped generation, an empty result, slowness
> in High mode, a budget reached), including the moment when an administrator should be involved.

OWIsMind is a business-oriented agentic chat portal. You ask a question in natural language about
revenue (the `DRIVE_Revenues` dataset), the agent works in front of you (the timeline), and every figure is
grounded in a real SQL result that you can inspect in the Evidence Studio panel on the right. This
page answers everyday questions and explains how to react when something does not go as
expected. To learn how to use the chat, see [Using the chat](02-using-the-chat.md); to read the
Evidence panel, see [Understanding evidence](03-understanding-evidence.md).

## 1. Frequently asked questions

### Which agents can I query today?

By default, your questions are routed to the `OWIsMind_orchestrator` orchestrator, which talks to you and
routes your request to the appropriate specialist. In v3, a single domain is genuinely equipped with an agent:
**revenue** (the `SalesDrive_revenue_expert` revenue expert sub-agent). It knows every
revenue figure in the `DRIVE_Revenues` dataset, across all Phases: `ACTUALS` (the default), `BUDGET`, `FORECAST`,
`Q3F`, `HLF`.

The agent selector only shows the agents enabled by your administrator. The list always comes from the
server: if an agent does not appear there, it is not enabled on your instance. To browse the agents that
are available to you and read what each one can do, open the **Agents** page from the sidebar. Each agent
card shows a tagline, a description, capabilities and tools, all written by an administrator (not
hardcoded in the application). If the profile of an agent has not been filled in yet, its card shows an
honest "This agent's profile has not been filled in by an administrator yet." message rather than
invented text.

> IN FLUX: if only the orchestrator is listed in the selector and no specialist appears, it means no
> specialist agent has been enabled by your administrator yet. The orchestrator will honestly say so if
> you target an uncovered domain (see section 2.1).

### Why trust an answer?

Every numeric answer comes with an **Evidence Studio** panel that re-derives, without any AI, the
way the figure was produced: the data source, the scope and the exact filters,
how the number is computed, the exact result used, and a verification-level badge. The badge
is **never green**: this is a deliberate choice so as not to give a false sense of confidence (solid = certified,
dotted = partial, gray = declared). For details, see [Understanding evidence](03-understanding-evidence.md).

### How do I ask a good question?

The more precise your request, the better the answer. The input bar explicitly invites you to do so
(i18n key `prompt.placeholder`: "Describe your request as precisely as possible") and the home screen
adds a tip (`empty.tip`): specify the terms used, the period and the scope. Examples of
well-scoped requests: "actual revenue of account X in 2025", "top 10 customers by ACTUALS revenue", "2026
budget by solution line".

`Enter` sends your message, `Shift+Enter` inserts a line break. The microphone (voice input) **never** triggers
the send automatically: you re-read, then send it yourself.

### What is the mode selector (Eco / Medium / High) for?

The mode chooses the model that drives the entire answer. A single model leads the run, there is no escalation
along the way.

| Mode | Cost | Speed | When to use it |
|---|---|---|---|
| Eco (default, recommended) | Low | Very fast | The vast majority of everyday questions |
| Medium | Moderate | Fast | More demanding or nuanced requests |
| High | High | More deliberate | Maximum quality on a complex question |

Eco is the recommended default mode (label `mode.recommended`, message `mode.reco_line`). Whatever
the mode, the analytical SQL is always written by the same engine (the Semantic Model Query tool, on a
Sonnet model): switching mode does not degrade the accuracy of the figure, it mainly changes the comfort of the
wording and the cost.

### Is there a monthly budget?

Yes. Every user gets a rolling **monthly credit in US dollars** (default $50) that resets automatically
on the 1st of each month - no reset job is required. Consumption (LLM-Mesh estimated cost, also shown as
tokens and dollar amount under each response) accumulates in the current monthly bucket.

Your current spend, limit, remaining amount and reset date are visible on the **My account** page
(sidebar avatar, then "My account"). A transparency line below the gauge tells you the origin of your
limit: the global default, a temporary global boost an admin applied, or a personal override an admin
set specifically for you.

When your monthly budget is exhausted, the input bar is **blocked**: a banner appears with the exact
amounts (key `chat.quota_banner`) and sending is prevented until the 1st-of-month reset. The blocking
is enforced server-side at `/chat/start` (HTTP 402 `monthly_quota_exceeded`); it fails open by
contract (a backend read error lets the request through rather than blocking you incorrectly). If you
need a higher limit, contact your administrator.

> IN FLUX: this enforcement is coded and validated in code but has not yet been confirmed on the
> live DSS instance. If you do not see a budget gauge on your My account page, the budget feature
> may not yet be deployed on your instance.

Admins are subject to the same budget rules as regular users. They can adjust the global limit and
per-user limits from the Administration console. For details, see
[Agents and administration](06-agents-and-administration.md).

### Are my conversations private?

You only see **your** conversations and the agents authorized for you. Identity is resolved on the
server side from your browser session, never from the content you send.

## 2. Common problems and how to react

### 2.1 The agent says it does not yet have an agent for this domain

This is **intended** behavior, not a failure. The orchestrator applies an honesty firewall: it
never invents a figure and never claims that data "does not exist". The only form of "no" it
allows itself is: "I do not yet have an **agent** for this domain" (a capability gap). The source text of the
persona is unambiguous (`OWIsMind_orchestrator.py`): "You MAY say you don't yet have an AGENT for a
domain (a capability gap). You may NEVER say the DATA does not exist."

In practice: if you ask about tickets, customer satisfaction or another domain not yet
equipped, the orchestrator will tell you that it does not have the corresponding specialist. This is not a
lack of data, but a lack of agent. What to do:

- Reformulate toward the covered domain (revenue) if your question can be reduced to it.
- If you genuinely need that domain, report it to your administrator: adding an agent is a
  configuration action on the agent side (see the runbook
  [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md)).

Conversely, if the orchestrator claims that a figure "does not exist" or "is zero" without having consulted the
specialist, that is abnormal: report it to support (it violates the honesty firewall).

### 2.2 The answer takes a while to arrive, or drops in one block at the end

The text of the answer does not arrive word by word: it often drops **in one block at the end**. This is normal and tied to
the architecture (SSE streaming is buffered by DSS, so a polling transport is used). What
is truly "live" is the **timeline**: it shows you the current step (the agent understands, grounds
the values, queries the model, drafts). As long as the timeline advances, the agent is working.

A request may also take time because it chains several steps (understanding, grounding the
terms onto exact values, writing and executing the SQL, formatting). Be patient and follow the
timeline rather than the text area.

### 2.3 I stopped the generation, but "Stopping..." stays displayed for a moment

The stop button asks the server to interrupt the run, but this stop is **cooperative**: the model's stream
has no immediate cancellation API, so the run can only be cut **between two chunks**. If a
model call or a SQL query is in progress, this may take a few seconds.

Meanwhile, the interface shows a clear "Stopping..." indicator (key `chat.stopping`,
spinner + blinking label), and keeps monitoring the run until the terminal event. This is expected.
The server keeps the partial answer already produced and frees the worker. You have nothing else to do
but wait for the indicator to end.

### 2.4 The answer is empty, or no figure is displayed

Several cases, to be distinguished:

- **No row matches your scope.** The specialist did search, but the filter returns
  nothing (for example a scenario, a period or an offer term that matches no data). Check the
  scope that the agent presents (the scope line, for example "Over the ACTUALS scope, all periods
  combined..."), and reformulate by broadening or correcting a term. Important reminder: you **never sum**
  across Phases (`ACTUALS`, `BUDGET`, `FORECAST`, `Q3F`, `HLF`); specify the intended Phase.
- **The typed term does not match any exact value.** The agent grounds your terms onto real values
  (grounding). A typo or an approximate label may find nothing. Use the exact name of the
  customer, product or zone.
- **The interactive Evidence view is unavailable.** If the Evidence panel cannot replay the SELECT
  (table not attached to a SQL dataset in the project), it shows an explicit message and still shows you
  the exact query executed by the agent (`ev.degraded`, `ev.degraded.no_dataset`). The chat answer
  remains valid; only the interactive table view is missing.

> IN FLUX: the capture of the exact result in Evidence is best-effort. If the key of the result rows
> cannot be read on the instance, Evidence shows `result_captured: false` (the SQL and the scope
> remain visible, but not the mini-table of the result). This is not a computation error.

### 2.5 Slowness in High mode

High mode uses the most powerful model (Claude Sonnet 4.6): it is deliberately "more deliberate"
(label `mode.high_speed`), so slower and more costly than Eco or Medium. If speed matters more than
wording finesse on your question, switch back to **Eco** (fast, economical, recommended): the
accuracy of the figure does not change, because the SQL is always written by the same engine whatever the mode.

If the slowness persists **in all modes**, it is probably not a model problem but
an instance or backend problem: see section 4.

### 2.6 The send is blocked with a budget banner

When your monthly budget is reached, the input bar greys out and a transparent banner appears above it
(key `chat.quota_banner`) showing what you spent, your limit and the reset date. You cannot send new
requests until the 1st of the following month. What to do:

- Wait for the automatic reset on the 1st of the month.
- If you need to keep using the application before then, contact your administrator: they can raise
  your limit temporarily or permanently from the Administration console.

The "My account" page (sidebar avatar) always shows the current state of your budget (spent,
remaining, reset date).

### 2.7 An agent appears in the list but seems to do nothing useful

If an agent card in the library shows no description - only "This agent's profile has not been filled
in by an administrator yet." - it means the administrator has enabled that agent but has not yet
authored its profile (tagline, description, capabilities, tools). This is expected and honest: no
content is ever invented. Contact your administrator to ask them to complete the profile in the
Administration console.

## 3. Error messages you may encounter

When the send fails on the server side, the interface surfaces a stable error code. Here is how to
interpret them.

| What you see | Internal code | Meaning | What to do |
|---|---|---|---|
| The send is refused, "storage not configured" | `storage_not_configured` (HTTP 409) | The webapp has no chosen SQL connection: it can neither store nor read conversations. | Configuration problem: contact an administrator (see 4). |
| The chosen agent is not available | `agent_not_enabled` (HTTP 404) | The targeted agent is not (or no longer) enabled, or its key is obsolete. | Reselect an agent in the picker; if the right agent is missing, ask an admin to enable it. |
| Monthly budget reached, send blocked | `monthly_quota_exceeded` (HTTP 402) | The user's monthly budget is exhausted. The frontend shows a banner with the amounts and the reset date. | Wait for the 1st-of-month reset, or ask an admin to raise your limit. |
| "Service busy, try again" | `busy` (HTTP 503) | Too many simultaneous generations on the server (concurrency limit reached). | Wait a few seconds and resend your request. |
| The generation interrupts and resumes once | `run_not_found` / `run_lost` | The current run disappeared on the server side (often after a backend restart). | Recoverable, non-blocking case: relaunch your request. |
| "not authenticated" | `unauthenticated` | Your browser session is not recognized. | Reload the page (assets cache); if the problem persists, contact an admin. |

Note: `storage_not_configured` is the most telling error to recognize. It never comes from your
question; it means the webapp has not yet been linked to its database. As long as the SQL connection is
not chosen in the Settings, the application reports "storage not configured" and the chat cannot
work.

## 4. When to contact an administrator

Call an administrator (rather than simply reloading the page) in these cases:

- **"storage not configured" / `storage_not_configured`**: the SQL connection is not chosen. Only an
  admin configures it in the webapp Settings.
- **An agent you need does not appear** in the selector: enabling it is an admin setting.
- **An agent's profile card shows "profile to complete"**: the agent is enabled but its profile has
  not been authored yet - ask the admin to fill it in from Administration > Agents > Edit profile.
- **Your monthly budget is exhausted before the end of the month**: an admin can raise your limit
  temporarily or permanently from Administration > Quotas & budgets.
- **Generalized slowness in all modes**, or repeated `busy` errors: may signal a backend
  to restart or a loaded instance.
- **The orchestrator claims that data "does not exist"** instead of consulting the specialist, or invents
  a figure: this is a deviation from the honesty firewall, to be reported.
- **After an announced update**, if the interface misbehaves (missing assets after a
  new build): a forced browser refresh is often enough; otherwise, the admin checks the
  deployment.

For operational handling, these situations are covered by the incident procedures:
see the operations runbooks. In particular, the backend restart, an unresponsive mode and
the "storage not configured" state are handled there step by step.

## 5. Going further (operator)

If you are an administrator or operator, the following pages detail the course of action and the
configuration:

- The detailed incident procedures (backend to restart, unresponsive mode, storage not
  configured) are in the [Runbooks](../06-operations/04-runbooks.md).
- The installation and the choice of SQL connection are described in
  [Installation and configuration](../06-operations/01-installation-and-configuration.md).
- An unresponsive mode (Eco, Medium or High) often points to an LLM Mesh model id to verify
  on the agent side: see [Deploying and editing the agents](../05-agents/07-deploying-and-editing-agents.md).

## See also

- [Using the chat](02-using-the-chat.md) - prompt, agent selector, mode, timeline, versions, stop.
- [Understanding evidence](03-understanding-evidence.md) - reading the Evidence panel (badge, chips, drill,
  chart) on the user side.
- [My account and budget](05-account-and-budget.md) - the budget gauge, usage history, and what happens when the limit is reached.
- [Agents and administration](06-agents-and-administration.md) - the agents library; for admins: managing agents, profiles and quotas.
- [Getting started](01-getting-started.md) - opening the application and asking a first question.
- [Scope and limitations](../00-overview/02-scope-and-limitations.md) - what the product does and does not do
  (a single staffed domain, enforced budget, no word-by-word streaming).
- [Runbooks](../06-operations/04-runbooks.md) - incident procedures for the operator (backend restart,
  unresponsive mode, storage not configured).
