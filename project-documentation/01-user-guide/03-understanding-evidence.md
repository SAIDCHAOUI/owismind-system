# Understanding Results (Evidence Studio)

> Audience: business user. Last updated: 2026-06-18. Summary: this guide explains the Evidence Studio
> panel (trust badge, sources, calculation, captured result, drill, exploration, collapsed SQL,
> Chart/Table/KPI tabs) and why every figure shown comes from a real SQL result, never from a fabrication.

## What Evidence Studio is for

When you ask a question, the agent does not simply hand you a figure: OWIsMind opens an evidence panel
called Evidence Studio to the right of the chat. This panel answers a single question: "can I trust this
result, and how was it obtained?".

The key point to remember: **every figure shown comes from a real SQL query run against the data**,
never from an estimate produced by the language model. The panel rebuilds the explanation from that real
query, fully automatically and **deterministically** (the same result will always yield the same
explanation). No language model is involved at evidence time: it therefore cannot "embellish" what
actually happened.

The panel opens on its own at the end of a response that produced at least one successful query. You can
also open it manually from the "Evidence" button below a response, and close it with the cross in the
top right corner. Opening Evidence narrows the chat column: this is expected.

> Good to know: Evidence Studio re-reads the data **right now**, at the moment you look at it. Only the
> "Result used by the agent" block (described further down) shows what the agent actually saw when it
> answered. For a question about the security and confidentiality of these re-reads, see
> [Security Model](../02-architecture/04-security-model.md).

## The panel tabs

Depending on the response, the panel may show several tabs at the top. The **Evidence** tab is always
present; the others appear only if the agent requested a visual display.

| Tab (label) | Internal key | What you see there |
|---|---|---|
| Evidence | `evidence` | The heart of the panel: badge, sources, filters, calculation, result, exploration, SQL. Always present. |
| Chart | `chart` | A chart (line, bars or pie) built from the captured result. |
| Table | `table` | The exact result received by the agent, presented as a table. |
| KPI | `kpi` | A key figure highlighted (with an optional variation, green arrow if up, red if down). |

Switching tabs does not affect the conversation thread: you can go look at the chart and then come back
to the evidence without losing anything. Charts, tables and KPIs are built **server-side** from the real
result: the agent only states which field goes on the x-axis or y-axis, and the server does the rest. If
the data does not lend itself to a plot (column not found, non-numeric values), the tab shows an honest
message ("Unable to plot this data.") rather than a false chart.

> The panel is designed to never "break": if a piece of information is missing, the corresponding section
> hides itself or shows an explanatory line, but the rest of the panel remains usable.

## The trust badge: the first thing to read

At the very top of the Evidence tab, a **pill** summarizes the verification level of the response,
accompanied by a plain-language sentence. The color rule is deliberate and **never includes green**
(green would give a false impression of total guarantee):

- **solid orange border** = certified scope;
- **dashed orange border** = partial evidence;
- **muted gray** = a plain statement from the agent, unverified.

Here are the possible levels, from the strongest to the most cautious. The labels and sentences are those
shown in the application (i18n keys `ev.proof.level.*`):

| Label | Pill tone | What it means |
|---|---|---|
| Certified result | solid orange | The calculation is broken down step by step AND the exact result used by the agent was kept. This is the highest level. |
| Certified source | solid orange | The exact source and scope of the query are identified. The rows shown are re-read now, not at response time. |
| Partial evidence | dashed orange | Only part of the scope could be reproduced. The elements that were not reproduced are **listed**, never hidden. |
| Stated by the agent | gray | A statement from the agent: this query could not be verified automatically. |

When verification is partial, a discreet note indicates how many conditions could not be reproduced
("N element(s) not reproduced"). This is an honesty choice: what could not be verified is **counted and
shown**, never concealed.

> How these levels are computed (for the curious reader): the backend derives the level mechanically by
> analyzing the real query (identified source, reproduced filter conditions, understood calculation). One
> technical detail: the "Result used by the agent" pill may be absent even when the scope is certified,
> because result capture is best-effort on this instance. The full detail of the scale (`declared` ->
> `source_identified` -> `scope_partial` -> `scope_exact` -> `calc_decomposed`) lives in
> [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md).

## Data source

Below the badge, the **Data source** section indicates where the figures come from, in plain language:
the name of the queried dataset. If the response ran several queries, an honest note adds "+N more
query/queries run".

When a link to Dataiku has been configured on the agent, the dataset name becomes **clickable** (tooltip
"Open the dataset in Dataiku") and opens the source in a new tab. If no link is configured, the name is
shown as plain text.

## The filters applied by the agent

The filters section breaks down the query's `WHERE` condition into **chips** (small labels), one per
filter, in column/value language. Each chip is:

- **editable**: you can change a filter's values via a distinct-values selector;
- **removable**: removing a filter broadens the scope;
- complemented by an "Add a filter" button on any column, and an "Agent version" button to revert to the
  original filters.

These filters drive the exploration table further down (see "Explore the source data"). Changing a filter
never rewrites the agent's response: you simply explore the source data freely, that is all. A dashed
orange border signals that you have changed the filters compared to the agent's version.

> Security: when you change a filter, the application never sends any SQL; it only transmits the column,
> the operator and the chosen values. The server itself rebuilds the query, bounded and read-only. You
> never choose the table or the connection.

## How this result is calculated

The **How this result is calculated** section presents, as a numbered list, the calculation steps in
**business language** (no SQL jargon): the source, the filters, the groupings, the sums, the ratios, and
so on. These steps are derived automatically from the real query. If part of the calculation is not
understood with certainty, it is shown neutrally rather than reformulated incorrectly: a false explanation
would be false evidence. The section disappears entirely if no step could be established.

## Result used by the agent (and the drill)

This is the heart of the evidence: the **Result used by the agent** section shows the **exact rows** the
agent received in order to formulate its response, in a small bounded table (no sorting, no pagination:
this is evidence, not a data explorer), along with the total row count.

Two cases:

- **Captured result**: the table shows the first rows actually used. If the result was truncated, a note
  "Result truncated - first rows only." makes it clear.
- **Result not captured**: an honest line indicates "The exact result used by the agent was not kept for
  this response." (the row count may still be shown). This is an expected case: capture is best-effort and
  not guaranteed on the instance. The panel remains useful for everything else (badge, sources,
  calculation, exploration, SQL).

When the backend has certified the drill as reliable, a **chevron** appears at the end of each result row.
Clicking it "dives" into the **source rows** that make up that result: the exploration table further down
then narrows to that row (a "Source rows: ..." banner appears, with a button to return to the result). The
drill is offered only when it is proven reliable: if a column cannot be tied back with certainty, the
chevron is deliberately hidden rather than risking a drill toward the wrong row.

## Explore the source data

Below the drill banner, the **Explore the source data** section shows the rows of the source table, loaded
as you scroll (lazy loading, by pages). This table reflects the current filters (chips): you can adjust a
filter, add a filter column, and observe the matching rows.

Important: this exploration re-reads **today's** data. If the data has changed since the response, the rows
here may differ from those the agent saw. To know exactly what the agent used, rely on the "Result used by
the agent" section above.

## Technical details (SQL)

At the very bottom, a collapsed "Technical details (SQL)" panel lets you see the **exact query** run by the
agent, formatted and colored for readability. A copy button copies the query as-is. This is the ultimate
level of transparency: the evidence hides nothing, and you can verify the query word for word. This panel
is useful mainly to technical profiles; the rest of the panel is enough for a business reader.

## When the panel is in degraded mode

Sometimes the interactive view is not available (for example, the queried table does not match any SQL
dataset in the project, or the response did not produce a usable query). In that case, the panel shows the
"Stated by the agent" badge followed by a message explaining why, and still offers the raw query when it
exists ("Interactive view unavailable - here is the exact query run by the agent."). Here too, nothing is
made up: you are told honestly what is missing.

## In summary

- Every figure comes from a **real SQL result**, never from a model estimate.
- The **badge** tells you at a glance how thoroughly the response is verified (and is never green, so as
  not to oversell a guarantee).
- The **sources**, the **calculation** and the **captured result** trace the origin of the figure.
- You can **explore** the source data freely and drill down (**drill**) toward the contributing rows.
- The **collapsed SQL** gives you the exact query if you want to verify everything.
- Anything that could not be verified or captured is **shown honestly**, never hidden.

> IN FLUX: capture of the exact result ("Result used by the agent" and the Chart / Table / KPI tabs that
> derive from it) is best-effort and may be absent on the instance. The KPI tab is wired on the interface
> side, but its appearance depends on the agent requesting that type of display. These points are detailed
> on the backend side.

## See also
- [Using the chat](02-using-the-chat.md) - ask a question, choose the agent and the mode, follow the timeline.
- [FAQ and troubleshooting](04-faq-and-troubleshooting.md) - practical answers and common error messages.
- [Backend - Evidence Studio and artifacts](../04-backend/05-evidence-and-artifacts.md) - for the technical reader: capture, verification levels, artifacts pipeline.
- [Security Model](../02-architecture/04-security-model.md) - read-only re-reads, owner-scoping, the frontend never chooses table or connection.
