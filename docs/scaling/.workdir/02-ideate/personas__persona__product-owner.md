**OWIsMind - Product Owner Perspective: Telco Connectivity/Roaming at OWI**

---

**1. Top 7 Moments of Value**

**1.1 - The Silent Revenue Drop I Did Not Know About**
A roaming solution's revenue drops 18% over 3 weeks. No alert fires. I discover it during the monthly review, scrambling to explain it to the VP. The moment I need: OWIsMind surfaces this unprompted, with the affected solution, the magnitude, the time window, and a first-cut hypothesis (single carrier? single account? all actuals vs budget?). I want to be told, not have to ask.

**1.2 - Monday Morning Stakeholder Prep in 3 Minutes**
Every Monday I spend 30-45 minutes pulling numbers for the weekly revenue update: YTD actuals vs budget per solution, top accounts, biggest movers. I want to ask "prepare my Monday update" and get a structured narrative + ready numbers I can paste or export. The narrative must be in my voice, concise, with every number traceable.

**1.3 - Pre-Meeting Briefing on an Account**
30 minutes before a call with a large account I ask: "What is the revenue situation for [Account X] this year, actuals vs budget, and what moved in the last 3 months?" I get a clean brief covering their top products, trend, and any anomaly. Right now I either pull a dashboard or ask a colleague. Both are slow.

**1.4 - "Why Did This Change?" Investigation**
EVPL revenues are up 12% vs last month. Is it one account, one solution line, a price effect, a volume effect, or a contract renewal? I want to drill by axis (account, solution, scenario) in a single conversation without opening multiple dashboards, reformulating SQL, or waiting for a data team.

**1.5 - Budget vs Actual Tracking at Mid-Year**
June close: I need the gap vs budget by solution, by account group (top 20 / mid-tier / tail), YTD and H1 only. The filters are not trivial (exclude internal, only ACTUALS phase, EUR only). Today this is a recurring notebook request. I want to ask it in natural language and get the table + a one-paragraph gap commentary.

**1.6 - New Product Ramp Tracking**
A new connectivity offer launched 6 weeks ago. Is revenue ramping as planned? Which accounts have signed and are billing? Which had commits but show zero actual? I want this on demand without a custom dashboard build.

**1.7 - Cohort / Segment Comparison**
"How does IP revenue compare across the top 5 MVNO accounts vs the top 5 MNO accounts this year?" Segmentation queries like this require either a data engineer or a long pivot session. OWIsMind should handle the comparison in one round-trip and give me a side-by-side table.

---

**2. Outputs I Need**

- **Trend line charts** (monthly actuals, budget line, forecast line on the same axis) - exportable as PNG for a slide.
- **Ranked tables** (top N accounts / solutions by revenue, by gap, by growth rate) - exportable as CSV or Excel.
- **Narrative summaries** - 3-5 sentences, numbers cited exactly, ready to paste into a PowerPoint note or an email. No fluff, no hedging where the number is known.
- **Anomaly callout block** - flagged item, magnitude, time window, affected dimension, one hypothesis. Separate from the main answer so it is visually distinct.
- **Slide-ready export** (or at minimum a PDF with the chart + the narrative + the data table beneath it) for distribution to people who will never use the tool.
- **Email draft** - for the weekly update or an account alert, pre-filled from the answer, with subject line, structured paragraphs, numbers from the query. I review and send; the tool never sends autonomously.

---

**3. Proactive Push Capabilities That Matter Most**

Priority order:

1. **Revenue anomaly detection** - weekly scheduled run, compares this week vs prior 4-week average per solution and per account, surfaces drops or spikes beyond a threshold (say >10% or >50k EUR). Sends a digest email or a notification. This alone would justify the tool for me.
2. **Budget gap alert at mid-month** - if YTD gap vs budget is widening faster than the prior run rate, flag it. Semi-monthly cadence.
3. **Weekly Monday brief** - scheduled narrative generation (top movers, overall YTD, one highlight) delivered Monday 7h. No action needed from me.
4. **New-account zero-billing alert** - accounts with a contract or forecast but zero actual in the rolling 30 days. Catch contract-but-no-billing situations early.

---

**4. Three Features That Would Make This Indispensable**

**4.1 - Proactive anomaly digest (push, not pull).** If I have to remember to ask, the tool is a faster search engine. If it tells me what changed before I ask, it becomes a real analyst. This is the difference between useful and indispensable.

**4.2 - One-click export to slide/PDF/email** from any answer. The last 10 meters of every insight is getting it into a deck or an email. If that step still requires copy-paste and reformatting, adoption stalls at semi-technical users. A "send as email draft" or "export as PDF brief" button on any answer closes the loop.

**4.3 - Claim-vs-data trust indicator per number** (not just per query). I need to see, for each cited figure, that it came from a captured SQL result and not from model memory. One hallucinated revenue number in a stakeholder deck destroys credibility permanently. A small inline badge (verified / sourced) per number, with a click to the underlying rows, is the trust primitive I cannot work without.

---

**5. Trust Requirements**

- Every number in a narrative must be **linked to a source row** - not just "data from SQL_owi" but the actual captured result visible in one click (Evidence panel, current design is on the right track).
- **Scope must be stated explicitly**: which phase (ACTUALS / BUDGET / FORECAST), which time window, which currency, which exclusions. If I cannot see the filter set, I cannot cite the number to a VP.
- **Abstain rather than guess**. If the question is ambiguous or the data is insufficient, say so explicitly. Do not fill a gap with a plausible estimate. Business users disengage permanently after one fabricated figure.
- **Audit trail for scheduled/proactive runs**: when was the anomaly detected, what query, what threshold, what result. I must be able to reproduce the alert for an audit or a challenge.
- **No action without confirmation**: email drafts are drafts - I review before anything leaves the system. Export is pull, not push (except the weekly digest which I configure explicitly).