# My account and budget

> Audience: business user (analyst, sales representative, OWI/Orange manager). Last updated:
> 2026-06-19. Summary: how to view and change your theme and language, understand your profile,
> read the monthly budget gauge (spent / limit / remaining / reset date), and what happens when
> the budget is exhausted.

The **My account** page (i18n key `set.title`: "My account") is reached from the sidebar: click your
avatar (initials in a circle) at the bottom left, or click the "My account" entry in the menu. It is
the page formerly labelled "Settings" - the rename to "My account" was introduced in the Orange UI
redesign. It groups everything that belongs to you: appearance preferences, your identity, your
monthly budget and your usage history.

## Appearance: theme and language

At the top right of the page, two controls let you adjust the look of the interface immediately:

- **Theme:** a flat segmented control switches between **Light** and **Dark** mode. The change takes
  effect at once and is remembered across sessions.
- **Language:** a selector switches the interface between French and English. The default is English.
  The change takes effect at once; conversation history and agent responses already in the thread are
  not re-translated.

These two controls are also accessible from the header bar on every page, so you never have to visit
My account just to change them.

## Your profile

The profile card shows:

- your **display name**, derived automatically from your Dataiku login (for example `said.chaoui`
  becomes "Said");
- a **Dataiku identifier pill** with a lock icon and your login id in monospace;
- your **groups**, if any, listed as chips with an orange accent border.

The "Edit profile" button is currently disabled ("Soon" badge): there is no route yet to let you set
your own display name or title. Your identity is always derived from your Dataiku session and cannot
be changed from within OWIsMind for now.

## The monthly budget gauge

OWIsMind assigns every user a rolling monthly credit in US dollars. The budget card on My account
shows the current state of this credit in real time (loaded from `/usage` via the session store,
refreshed on page entry):

```
$12.34  /  $50.00                                     25%
[=====================================               ]
$37.66 remaining               Resets on Jul 1, 2026
Monthly limit: $50.00 (default).
```

| Element | What it means |
|---|---|
| Big monospace amount on the left | Cumulative spend this calendar month (in dollars), driven by the LLM-Mesh `estimatedCost` of each exchange. |
| `/ $50.00` | Your current monthly limit. |
| Percentage (right) | Spend as a percentage of the limit. |
| Flat bar | Visual gauge, capped at 100% visually even if spending went fractionally over the cap before the block took effect. Turns red when you are blocked or over. |
| "remaining" | How much credit is left this month. |
| "Resets on ..." | The first day of the next calendar month: the budget resets automatically, with no action required from anyone. |
| Transparency line | Explains why your limit is what it is (see below). |

### Limit source transparency

The line below the gauge tells you exactly **why your limit is what it is** (i18n keys
`set.budget.src_*`):

| Message | What it means |
|---|---|
| "Monthly limit: $X (default)." | Your limit is the global default set by the administrator. |
| "Monthly limit: $X (temporary boost until [date])." | A global temporary boost is active for all users; it expires on the shown date and then reverts to the default. |
| "Monthly limit: $X (granted by an administrator)." | An administrator assigned you a permanent personal override. |
| "Monthly limit: $X (temporary boost until [date])." (personal) | An administrator assigned you a time-limited personal override. |

### What "off" looks like

If the administrator has **not enabled enforcement** (tracking on but no blocking), the gauge shows
a "wallet" icon with: "Usage tracking is on. No monthly limit is currently enforced."
(`set.budget.off`). In this mode, your spend is tracked and displayed but no request is ever blocked.

### Severity levels

The gauge and percentage change color based on how much of the budget is consumed:

| State | Color | When |
|---|---|---|
| Normal | Default (neutral) | Below 80% |
| Warning | Orange | 80% or more |
| Over / blocked | Red | At or past 100%, or explicitly blocked |

## Mini-grid: requests and tokens

Below the gauge, a small two-column grid shows two counters for the current month:

- **Requests** (`set.budget.requests`): the number of exchanges sent this month.
- **Tokens this month** (`set.usage.tokens_month`): the total number of tokens (input + output) used
  in this calendar month.

## Usage history

Further down, a four-tile stat grid (`set.usage`) shows lifetime and current-month statistics:

| Tile | What it shows |
|---|---|
| Tokens this month | Total tokens (with a sub-line: input tokens in green / output tokens in gray). |
| Spend this month | Dollar amount + request count. |
| Lifetime spend | Cumulative cost since your account was created. |
| Last activity | Date of your most recent exchange. |

## When the budget is exhausted

When `spent >= limit` and enforcement is on, the budget card shows a red alert flag:
"Monthly budget reached. New requests resume on [date] (monthly reset)." (`set.budget.blocked`).

Simultaneously, in the chat, the input bar becomes **greyed out** and a transparent banner appears
above it:

> "Monthly budget reached: $50.00 used of $50.00. New requests resume on Jul 1, 2026."

(`chat.quota_banner`, with exact spent / limit / reset date). You cannot send new requests.

The block is enforced **server-side** at `/chat/start`, which returns HTTP 402 `monthly_quota_exceeded`
before the run starts. The enforcement fails open by contract: if the budget status cannot be read due
to a backend error, the request is allowed through and the spend is still recorded - this keeps a
transient failure from locking you out incorrectly.

The block is lifted automatically when the calendar month rolls over to the 1st. No reset job or admin
action is needed.

> IN FLUX: the budget enforcement is coded and validated at the code level but has not yet been
> confirmed live on the DSS instance. If you do not see a budget gauge on your My account page, the
> budget feature may not yet be deployed on your instance. Contact your administrator.

### What to do when blocked

- **Wait** for the automatic 1st-of-month reset.
- **Ask your administrator** to raise your limit. They can grant you a permanent or temporary personal
  override from the Administration console (Quotas & budgets tab). See
  [Agents and administration](06-agents-and-administration.md) for what the admin can do.

## Agent-context window preference

At the bottom of the page, a preference card lets you set how many **recent messages** OWIsMind sends
to the agent as context for each new exchange. The default is 20; the minimum is 10; the maximum is 50; the step is 10.

Lowering this value makes each exchange cheaper (fewer tokens in context) and faster. Raising it lets
the agent refer to earlier parts of a long conversation. The change applies immediately to the next
exchange you send.

## See also
- [Getting started](01-getting-started.md) - opening the application, the sidebar rail and navigation.
- [Using the chat](02-using-the-chat.md) - modes, the cost line under each response.
- [Agents and administration](06-agents-and-administration.md) - admin management of budgets and quotas.
- [FAQ and troubleshooting](04-faq-and-troubleshooting.md) - what to do when blocked, how to ask for a limit increase.
