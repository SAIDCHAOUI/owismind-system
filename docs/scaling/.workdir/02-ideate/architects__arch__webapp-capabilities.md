Confirmed: the `Chart` instance lives in `ArtifactChart.vue` (line 149) but `toBase64Image()` is never called, and `MessageAgent.vue` only has copy-to-clipboard. The artifact spec/data split and routes match my context exactly. I have enough verified grounding to write the roadmap.

---

# OWIsMind Webapp Capability Roadmap (Mission 1: breadth)

Senior-architect recommendation for the technical CEO. Opinionated, sequenced, YAGNI-ruthless. Every seam below is a real file/contract verified this session.

## Guiding thesis
The webapp already nails the hard 80%: orchestration, grounding, Evidence, artifacts (chart/table/KPI), budget enforcement. The breadth that moves the needle for the 4 personas is **getting the answer OUT of the app** (download/share/report) and **keeping the conversation moving** (follow-ups, comparisons, decomposition). Most of that ships with **zero install** by reusing the captured `generated_sql[].result` and the existing Chart.js instance. The expensive, install-gated items (PDF, email, voice) come later and behind HITL. Drop anything that duplicates Evidence or invents a second source of truth.

---

## PHASE 1 - Quick wins, ZERO install, high persona value

### 1. Chart PNG download
- **What:** A download button on every chart that exports exactly what the user sees as a PNG.
- **Persona value:** Account manager pastes the revenue chart into a client QBR deck; marketing director drops it in a campaign review; executive screenshots-free for a board slide. This is the single most-requested "get it out" action.
- **Technical approach:** The `Chart` instance already exists in `ArtifactChart.vue` (line 149, `instance = new Chart(...)`). Expose `instance.toBase64Image('image/png', 1)`, build an `<a download>` and `.click()`. Wire the unused `download` icon in the chart toolbar inside `EvidencePanel.vue`. Pure client-side; nothing touches the backend. Add i18n `ev.chart.download` to `extra.js` (fr+en).
- **Effort / install:** S, no install.
- **Risk / charter:** None to the instance (no server call). Charter: square download button, single orange accent only on hover, no emoji. Filename derived from conversation title + chart label.
- **Dependencies / phase:** None. Ship first.

### 2. CSV export of the captured result
- **What:** "Export CSV" on any table/result, serving the exact `generated_sql[].result` the agent used.
- **Persona value:** Account manager pulls the per-account revenue rows into Excel for an ad-hoc client list; product owner feeds rows into their own pivot. Removes the "can you send me the raw numbers" email.
- **Technical approach:** Two viable paths; prefer **client-side** for Phase 1: the result rows are already in the `evidence` store (delivered by `/evidence/meta`), so serialize to CSV in JS (no lib, just join/escape) and download. If we later want server authority, add `GET /evidence/export?fmt=csv&exchange_id=...` in `routes.py` using stdlib `csv` + `io.StringIO`, reading from `chat_v5` captured result (never re-running SQL). Add `ArtifactTable.vue` toolbar button + `ev.table.export_csv` i18n.
- **Effort / install:** S, no install.
- **Risk / charter:** Client-side path = zero instance load. If server path: it is a READ of stored JSON, no SQL execution, owner-scoped like `/evidence/rows`. Never expose a generic export-any-table route (NON-NEGOTIABLE #3).
- **Dependencies / phase:** None.

### 3. Follow-up suggestion chips
- **What:** 2-3 clickable follow-up questions under each answer.
- **Persona value:** The biggest engagement lever. Marketing director who does not know the data model is handed the next good question ("vs last quarter?", "top 5 accounts?", "by product line?"). Turns a one-shot tool into a conversation. Executives explore without learning syntax.
- **Technical approach:** The orchestrator already produces a structured `AGENT_RESULT {intent, resolvedFilters, ...}`. Generate 2-3 follow-ups **deterministically from that** (intent + resolved dimensions + the `Profile.groupable axes`), NOT a second LLM call (cost + latency). Emit them as a new frozen event kind appended to the existing whitelist in `agents/streaming.py` (e.g. `SUGGESTIONS`), carried through `stream_manager` to `/chat/poll`, rendered by `MessageAgent.vue` as charter chips that call `chat.send()` on click. i18n shells in `extra.js`. If determinism feels thin, gate an optional tiny eco-model call behind a flag, but ship deterministic first.
- **Effort / install:** M, no install.
- **Risk / charter:** Suggestions must never assert facts (only questions) -> no hallucination surface. Charter: square chips, hover orange.
- **Dependencies / phase:** Reuses the artifact-event plumbing pattern. Phase 1.

### 4. AI-generated conversation title (replace the SQL-regex derivation)
- **What:** A real 3-5 word title instead of the current `CONV_TITLE_MAXLEN=56` regex-trim of the first message.
- **Persona value:** Every persona scanning a long sidebar history. Low glamour, high daily friction relief.
- **Technical approach:** This is the **one place a cheap LLM call is justified** because it is one-shot and cached. On first exchange completion, fire a single eco-model (Flash-Lite) summarization in the `start_run` thread, store in `webapp_chat_v5` (the conversation already has rows; add a derived title field via the no-ALTER `_vN` pattern or a small `webapp_conv_meta_v1` table - DO NOT ALTER). `build_conversation_list_query` in `sql_builders.py` reads it, falling back to the existing regex when absent (rollback-safe, retroactive). Backend python-lib change -> redeploy required.
- **Effort / install:** M, no install. Needs backend restart on deploy.
- **Risk / charter:** One extra cheap call per conversation (not per message); bounded. Title is display-only, never grounds analysis.
- **Dependencies / phase:** Phase 1 (independent).

### 5. Soft quota banner at 80%
- **What:** A non-blocking warning banner before the existing 402 at 100%.
- **Persona value:** Every user. Avoids the jarring hard-stop mid-analysis; gives executives/AMs runway to finish a session.
- **Technical approach:** `storage/budget.py` already computes spent/limit; `/usage` already returns it. Add a `pct_used` field, render a charter banner in the chat shell at >=80% (reuse the existing exhausted-banner component pattern). Frontend-only if `/usage` already returns enough; otherwise one-field backend add.
- **Effort / install:** S, no install.
- **Risk / charter:** Read-only. Charter: flat banner, orange rule, dismissible.
- **Dependencies / phase:** Phase 1.

---

## PHASE 2 - Differentiators (mostly zero install, one trust-critical)

### 6. Comparison / vs-prior-period intent
- **What:** First-class "vs last quarter / vs budget / YoY" so the answer comes back as a delta + a combo/waterfall chart.
- **Persona value:** This is the question executives and AMs actually ask. Revenue vs budget, this period vs last - the core of every business review. Today it half-works; making it a named intent makes it reliable.
- **Technical approach:** Add `comparison` to the sub-agent intent set in `SalesDrive_revenue_expert.py` UNDERSTAND (the prompt is generated from `Profile` - add the scenario/period axes as comparison candidates). The semantic tool already understands ACTUALS/BUDGET phases. RENDER emits a `show_chart` spec of a new combo/waterfall kind (see #11). FROZEN contract: extend `KNOWN_*` via the anti-drift test, never rename. Requires recoll of both Code Agents (env 3.11).
- **Effort / install:** M, no install. Agent recoll.
- **Risk / charter:** The "never sum across phases" calibration is exactly the intrinsic-human part - reuse the existing scenario semantics, do not re-derive. Reconciliation (#8) guards the deltas.
- **Dependencies / phase:** Pairs with #11 (chart types) and #8 (reconciliation). Phase 2.

### 7. "Explain this number" decomposition
- **What:** Click any number in the narrative -> a breakdown of how it was computed (filters, scope, the rows behind it).
- **Persona value:** Trust. The product owner / executive who will NOT act on a number they cannot defend. This is the moat against "AI made it up."
- **Technical approach:** Mostly already built - `evidence/sql_explain.py` (pure, never-raises) + `evidence/capture.py` (exact captured result) + the `EvidenceCalc.vue` / `EvidenceResult.vue` components + `/evidence/rows` drill. The new work is the **interaction**: detect numbers in `MessageAgent.vue` rendered markdown, link them to the Evidence drill (open the panel scoped to that result row). No new SQL - re-derived from stored `generated_sql`. This is a frontend wiring job over an existing backend.
- **Effort / install:** M, no install.
- **Risk / charter:** Drill already re-validated server-side (refuses >8 keys). No new attack surface.
- **Dependencies / phase:** Phase 2.

### 8. Claim-vs-result reconciliation + confidence badge (P0 trust, do not skip)
- **What:** Every number in the narrative is checked to appear in the captured SQL result; a low/medium/high confidence badge is shown; unverified numbers flagged.
- **Persona value:** **The single most important feature for executive adoption.** One hallucinated revenue number and the AM/executive disengages permanently. This is the governance backbone for the whole product.
- **Technical approach:** Pure Python 3.9 regex pass in a new `evidence/reconcile.py`, run server-side at answer finalization (in `start_run` after the agent completes, before persisting to `webapp_chat_v5`). Compare narrative numbers against `generated_sql[].result` cells (with formatting tolerance from `format_number`). Emit a `confidence` field on the message; render via the existing `EvidenceTrust.vue` badge pattern (charter: never green, plain/dashed/grey). Abstention > hallucination.
- **Effort / install:** M, no install. Backend restart.
- **Risk / charter:** Read-only, deterministic, never-raises (mirror `sql_explain.py`). Charter badge already defined.
- **Dependencies / phase:** Phase 2, but arguably the highest ROI line in this whole document. Sequence it early in Phase 2.

### 9. XLSX export
- **What:** Formatted Excel export of a result (headers, number formats).
- **Persona value:** AMs and product owners live in Excel; CSV loses formatting/types.
- **Technical approach:** `openpyxl` server-side from the captured result, via `/evidence/export?fmt=xlsx`. **CHECK if openpyxl is in the 3.9 backend env first** - if absent, this **requires a user install** (NON-NEGOTIABLE #1: the plan must say so explicitly). If install is unwelcome, stay with CSV (#2) and drop XLSX.
- **Effort / install:** S-M, **may require user install** (openpyxl).
- **Risk / charter:** Read of stored JSON, no SQL. Same export-route discipline as #2.
- **Dependencies / phase:** Phase 2, only if openpyxl present or user approves install.

### 10. Evidence Dataset / Trace / Cost tabs
- **What:** Add three tabs to the Evidence panel: the raw source dataset, the agent trace timeline, the cost of this answer.
- **Persona value:** Product owner (trace/debug), executive (cost transparency), analyst-leaning AM (source data).
- **Technical approach:** `EvidencePanel.vue` already uses `Tabs.vue`. The data exists: source rows via the existing dataset preview path, trace from the timeline events already streamed, cost from `webapp_chat_v5` usage columns. This is composition of existing data into new tabs - low risk. Charter square tabs.
- **Effort / install:** M, no install.
- **Risk / charter:** PII masking in the Dataset tab drill is a governance must (mask before render).
- **Dependencies / phase:** Phase 2.

---

## PHASE 3 - Heavier / install-gated / behind HITL

### 11. New chart types (waterfall / combo / scatter)
- **What:** Extend the chart vocabulary beyond bar/line.
- **Persona value:** Waterfall = actuals-to-budget bridge (executive gold); combo = volume+rate; scatter = segment analysis (marketing).
- **Technical approach:** `chart_payload.py` `build_chart_payload` (line 86) builds the Chart.js `{labels,datasets}` server-side - extend it with new `type` branches; `ArtifactChart.vue` already renders whatever config it gets. Waterfall is a stacked-bar trick (no plugin needed). Add the `show_chart` style options in the agent. **No install** if we stick to core Chart.js; a dedicated waterfall plugin WOULD be an install - avoid it.
- **Effort / install:** M, no install (core Chart.js only).
- **Risk / charter:** Charter palette in chart colors (resolve from tokens, as today).
- **Dependencies / phase:** Enables #6. Phase 2-3 boundary; do the combo for #6, scatter later.

### 12. PDF report via template-fill
- **What:** A one-click branded PDF of the answer (narrative + chart PNG + table), structure fixed, model fills only text/number slots.
- **Persona value:** AM sends a client a polished one-pager; executive gets a shareable artifact. This is a marquee feature for the "more output types" mission.
- **Technical approach:** **Template discipline is the safety property** - a fixed versioned template, model fills slots only, never generates structure. ReportLab (pure Python, no system libs) is the safe choice and **requires a user pip install** (state it explicitly). WeasyPrint is nicer but needs system pango/cairo - confirm with admin, otherwise reject. Chart embedded as the PNG from #1 (matplotlib Agg only if a server-side render is needed). New `/report` endpoint, HITL preview before generation.
- **Effort / install:** L, **requires user install** (ReportLab).
- **Risk / charter:** Generate off the request thread or bounded; never on a hot path. Charter-styled template.
- **Dependencies / phase:** Depends on #1 (PNG). Phase 3.

### 13. Proactive KPI digest (scheduled push to email)
- **What:** A scheduled summary ("your accounts this week") pushed to email/Teams.
- **Persona value:** AM/executive who will not open the app daily - the product comes to them. Strategic for retention.
- **Technical approach:** Runs as a **DSS scheduled scenario off-peak** (instance-safety: never a webapp cron), reusing the agent to produce a digest, template-filled email (fixed structure, model fills slots), `smtplib` stdlib for send. **Teams = webhook only** (no new dep). HITL/opt-in per user. This is the biggest blast-radius feature - everything behind explicit confirmation and a versioned template.
- **Effort / install:** L, no hard install (smtplib stdlib) but needs SMTP config + admin sign-off.
- **Risk / charter:** Email is `requires_confirmation` HITL territory. Instance-safety: scheduled, not webapp-triggered. Sequence LAST.
- **Dependencies / phase:** Depends on #12 template discipline. Phase 3.

### 14. Semantic result cache
- **What:** Cache `(question+filters) -> (result+narrative)` with a 24h TTL.
- **Persona value:** Indirect (cost + latency) - executives get instant repeat answers; cuts the bill 40-70%.
- **Technical approach:** A small keyed table or in-process cache keyed on normalized question + resolved filters, checked in `/chat/start` before `start_run`. Must invalidate on data refresh. **YAGNI caution:** only build when real cost data shows repeat questions; the model cascade already routes 85-90% cheap.
- **Effort / install:** M, no install.
- **Risk / charter:** Staleness risk - 24h TTL + explicit "from cache" disclosure. Phase 3, only if metrics justify.

---

## DROP (YAGNI)
- **Evidence multi-agent mode** (one panel per agent): no multi-agent answers in practice yet; the single panel handles it. Revisit only after a second domain ships.
- **Pin-to-dashboard / saved views:** a second persistence model + a dashboard surface = large scope for unproven demand. The conversation history IS the saved view today. Drop until users ask.
- **Voice input:** the mic placeholder can stay a "soon" label; STT is an install + accuracy + privacy rabbit hole for a B2B analytics tool. Drop.
- **Edit profile (PUT /me):** trivial but no demonstrated need; skip until a real settings requirement appears.
- **Budget dashboard (admin):** the Admin Quotas tab + soft banner (#5) already cover this. A full dashboard is gold-plating. Keep alerts (#5), drop the dashboard.

---

## Sequencing summary
- **Phase 1 (ZERO install, ship now):** Chart PNG (#1), CSV (#2), follow-up chips (#3), AI title (#4), soft quota banner (#5).
- **Phase 2 (differentiators):** Reconciliation+confidence (#8, do first), comparison intent (#6), explain-this-number (#7), Evidence tabs (#10), XLSX (#9, install-check), combo chart for #6 (#11).
- **Phase 3 (heavy/HITL/install):** remaining chart types (#11), PDF report (#12, install), KPI digest email (#13, HITL+SMTP), semantic cache (#14, metrics-gated).

**Files/relevant paths:** `frontend/src/components/evidence/ArtifactChart.vue` (PNG, line 149 Chart instance), `frontend/src/components/chat/MessageAgent.vue` (chips/explain wiring), `frontend/src/components/evidence/EvidencePanel.vue` + `ui/Tabs.vue` (Evidence tabs), `python-lib/owismind/evidence/chart_payload.py:86` (chart types), `python-lib/owismind/evidence/sql_explain.py` + `capture.py` (explain), new `evidence/reconcile.py` (confidence), `python-lib/owismind/api/routes.py` (export/report endpoints), `python-lib/owismind/agents/streaming.py` (new SUGGESTIONS/confidence event kinds), `python-lib/owismind/storage/sql_builders.py` + `chat_v5.py` (title), `frontend/src/i18n/extra.js` (all new keys). **Install-gated and must be flagged to the user:** XLSX (openpyxl), PDF (ReportLab), email digest (SMTP config).