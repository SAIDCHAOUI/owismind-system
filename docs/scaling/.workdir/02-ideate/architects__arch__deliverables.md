I have everything I need. The seams are verified: `_normalized_artifact_event` (streaming.py:142), `_sanitize`/`save_artifacts`/`read_artifacts` (artifacts.py), `build_chart_payload` (chart_payload.py), Blueprint `api` with `@api.route` decorator, the `request()` fetch helper in backend.js, and the unwired `download` icon. Now I'll write the architecture brief.

---

# DELIVERABLES / EXPORT PIPELINE - Senior Architect Brief

## Thesis (read first)

The system already has a **deliverable** primitive: `webapp_artifacts_v1` stores a tiny SPEC, the row data lives in `generated_sql[].result`, and `/evidence/meta` joins them server-side via `chart_payload.py`. A "deliverable" (PNG, CSV, XLSX, PDF, email) is **the same pattern one notch further**: it is an artifact whose render target is a *file/byte stream* instead of a Chart.js canvas. So do NOT invent a parallel system. Add one artifact kind family (`deliverable`) and one synchronous export route. Everything reuses the captured result, the owner-scoping, and the bounds discipline already proven in `artifacts.py`.

Two hard ground rules from the verified facts: **(1)** the data and spec live in two places and are joined at fetch time (`artifacts.py` line 6, `chart_payload.build_chart_payload`) - so an export endpoint must re-derive bytes from the captured result, never trust client-sent rows; **(2)** the backend is Python 3.9.23 Flask (NON-NEGOTIABLE #8) - ReportLab and openpyxl are pure-Python and run there; WeasyPrint is NOT (needs system pango/cairo, see below).

---

## Phase 0 - PNG + CSV (ZERO install, ship first)

**0a. Chart PNG download (client-side).**
(a) A download button on the Chart tab that saves the exact chart the user sees.
(b) Account manager: drop a revenue trend into a deck in 2 seconds. Marketing director: paste a share-of-revenue pie into a slide. Executive: screenshot-quality figure with no tooling.
(c) `ArtifactChart.vue` already holds a Chart.js instance but never calls `toBase64Image()` (verified: instance held, method never called). Wire the existing unused `download` icon (verified present, `icons.js:67`): `const url = chartRef.toBase64Image('image/png', 1); const a = document.createElement('a'); a.href = url; a.download = slug + '.png'; a.click()`. No backend, no install, no instance load (browser GPU).
(d) **S, no install.**
(e) Charter: the button is a square `Button` (icon-only, on-charter), one per chart, no orange. Security: pure client, no data leaves the browser it didn't already have. Instance-safety: zero (client CPU).
(f) No dependency. Sits first because it is the highest value/effort ratio in the whole mission.

**0b. CSV of the captured result (stdlib, server-side).**
(a) `GET /owismind-api/evidence/export?exchange_id=X&format=csv` streams the captured result table as CSV.
(b) Account manager: hand a client the raw numbers behind the answer. Product owner: pull figures into their own model. Executive: forward to finance.
(c) New route on the `api` Blueprint (`routes.py:75`), beside `/evidence/rows`. Reuse the *exact* identity + storage guard helper already shared by `/evidence/*` (`routes.py:640`). Load the captured result the same way `/evidence/meta` does (the result block `{captured, columns, rows}` that `chart_payload` consumes). Build the file with stdlib `csv.writer` over `io.StringIO`, return `flask.Response(text, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="..."'})`. Owner-scoped read only - the user can only export an exchange they own (mirror `read_artifacts` WHERE `user_id`).
(d) **S, no install.**
(e) Instance-safety: the result is already capped at capture time (it is the bounded `/evidence/meta` payload, not a fresh full-table scan - this is critical: NEVER re-run agent SQL for an export). Apply a hard `MAX_EXPORT_ROWS` cap mirroring the existing artifact caps. Security: no SQL from the front (NON-NEGOTIABLE #3 honored - the route takes only `exchange_id`, never a query). Charter: N/A (no UI beyond a menu item).
(f) Depends only on the shared evidence guard. Pairs with 0a behind one "Export" menu (square `Menu` from `ui/`).

**The export route is the spine.** Format becomes a parameter (`csv` now, `xlsx`/`pdf` later) so Phase 1-2 add a branch, not a new endpoint.

---

## The deliverable artifact model (the unifying design)

A **deliverable** is a new artifact-kind family layered on the verified pipeline. Two flavors:

- **Pull deliverables** (PNG/CSV/XLSX): no spec needed, derived on demand from the captured result via the export route. The frontend just offers buttons. Cheapest, do first.
- **Push deliverables** (PDF report, email draft): the *agent decides* to produce one and emits a spec. These flow through the **already-proven seam**: agent emits an `ARTIFACT`-shaped event -> `streaming._normalized_artifact_event` (verified `streaming.py:142`) -> `stream_manager` accumulates (MAX 8) -> `artifacts.save_artifacts` persists the SPEC (verified `_sanitize` whitelist, `artifacts.py:45`) -> `/evidence/meta` returns it -> a new **Deliverable card** renders a "Download PDF" / "Review email" action that calls the export route to materialize bytes.

To add this: extend `_ARTIFACT_KINDS` in `artifacts.py:31` (currently `("chart","table","kpi")`) with `"deliverable"`, add a `_sanitize` branch that keeps `{kind:"deliverable", subkind:"pdf"|"email", template_id, template_version, slots:{...}, source_exchange_id}` (slots are short strings, bounded exactly like the chart spec strings - `[:128]`, capped count). Mirror the same branch in `streaming._normalized_artifact_event` (the whitelist that drops unknown fields, verified at line 154). **The SPEC stays tiny** (slot values, not rendered bytes) - bytes are generated lazily by the export route at download time. This preserves the system's defining property: artifacts cost a few hundred bytes (`artifacts.py:7`).

---

## TEMPLATE-FILL discipline (the safety property)

**Templates live in the plugin, versioned, never generated by the model.** Create `Plugin/owismind/python-lib/owismind/deliverables/templates/` with one Python module per template id (e.g. `client_one_pager.py`, `exec_summary.py`, `email_draft.py`). Each module exports `VERSION`, `SLOT_SCHEMA` (the named slots + types/lengths), and a pure `render(slots, result, chart_pngs) -> bytes` function. The model **only fills named slots** via `with_json_output` (the verified-reliable path, P0★ in memory: "with_json_output OBLIGATOIRE sur les extractions déterministes"). The model never controls layout, structure, table columns, or any number that isn't echoed from the captured result.

**Exact slot schema - `client_one_pager` (account-manager facing):**
```
{ "client_name": str(<=80), "period_label": str(<=40),
  "headline": str(<=200),            # one-sentence verdict, model-written
  "kpis": [ {"label":str<=40,"value":str<=40} ] (<=4),   # values echoed from result
  "narrative": str(<=1200),          # 2-3 paragraphs, model-written analysis
  "chart_refs": [artifact_index] (<=2),   # which already-rendered charts to embed
  "footnote": str(<=160) }           # scope/disclaimer, e.g. ACTUALS, period
```
**`exec_summary` (executive facing):** `{title, period_label, tldr:str<=300, kpis(<=6), risks:[str<=120](<=3), recommendation:str<=400, chart_refs(<=3)}`.

The render function pulls every KPI **value** from the captured result by column name (reusing `chart_payload._resolve` + `_to_number`, verified pure/never-raises) and rejects any slot value that isn't a string of the bounded length. A **claim-vs-result reconciliation** pass (regex every number in `narrative`/`headline` against the captured result cells) runs before render and flags unverified figures - this is the P0 anti-hallucination guard the governance research calls out, and it is cheap Python 3.9.

---

## Phase 1 - XLSX (needs env check, no agent change)

(a) Add `format=xlsx` to the export route: captured result -> styled workbook.
(b) Product owner / finance-facing: formatted, formula-ready sheet, not raw CSV.
(c) Same route branch; `openpyxl.Workbook()`, write columns + rows from the captured result, one header style, autosize, return as `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` attachment.
(d) **S. INSTALL: confirm `openpyxl` is in the backend code env; if absent, ASK THE USER to install it** (NON-NEGOTIABLE #1 - the agent never installs). It is pure-Python, no system libs.
(e) Instance-safety: same `MAX_EXPORT_ROWS` cap; openpyxl builds in memory, so the row cap also caps RAM. No streaming write needed at our sizes.
(f) Depends on Phase 0 route. Independent of agents/PDF.

---

## Phase 2 - PDF report (the depth the user emphasized)

**Decision: ReportLab, not WeasyPrint.** ReportLab is pure-Python (pip only, **no system libraries**), runs on Python 3.9, and is the safe bet for a managed DSS code env. WeasyPrint renders nicer HTML/CSS but **requires system pango/cairo/gdk-pixbuf** that the agent cannot install and that may not exist on the instance - that violates NON-NEGOTIABLE #1 and risks #2. So: **ReportLab `SimpleDocTemplate` + `Platypus` flowables**, with the template module owning the layout (title bar, KPI grid, narrative paragraphs, embedded chart PNGs, table, footnote) styled to the Orange charter (square rules, `#FF7900` accent on the title bar, Helvetica, no gradients). **Ask the user to install `reportlab`.**

**Chart images for the PDF: matplotlib Agg, server-side.** The browser PNG (0a) isn't available server-side. Add `deliverables/chart_image.py`: `matplotlib.use("Agg")` headless backend, render the *same* `build_chart_payload` output to a PNG `BytesIO` (line/bar/pie). Agg needs no display and is almost certainly already in the DSS env - **verify; if absent, ask to install `matplotlib`.** This keeps charts in the PDF identical-in-data to the on-screen chart (same payload builder, no second source of truth).

- **WHAT** `format=pdf&template=client_one_pager` -> filled, branded PDF from the captured result + slots + server-rendered chart PNGs.
- **VALUE** Account manager: a "complete PDF analysis" to send a client without touching PowerPoint. Executive: a board-ready one-pager. Marketing director: a campaign-impact brief.
- **APPROACH** Export route branch -> load deliverable spec (`read_artifacts`) for slots + load captured result -> `chart_image.py` for embeds -> `templates/<id>.render(slots, result, pngs)` -> ReportLab bytes -> attachment Response.
- **EFFORT L. INSTALL: `reportlab` (required), `matplotlib` (verify first).**
- **RISK** PDF generation is the only CPU-real step. Mitigate: synchronous in the request thread (acceptable - one page, capped rows/charts), hard caps `MAX_PDF_CHARTS=3`, `MAX_EXPORT_ROWS` on any embedded table, a per-user throttle reusing the existing `evidence/throttle` limiter (verified `throttle` module). No background job system needed (YAGNI) - a one-pager renders in well under a second. Owner-scoped. Charter applies fully (this is a branded artifact).
- **DEPENDS** Phase 0 route, the deliverable artifact kind, template modules. After this works, the agent tool (Phase 4) makes it native.

---

## Phase 3 - Email draft (HITL, no auto-send)

(a) The model fills an email template -> a draft card in the chat the user reviews and sends.
(b) Account manager: "email this revenue summary to the client" -> a ready draft, edited then sent. Executive: forward an exec summary.
(c) Deliverable subkind `email`. Slot schema: `{to_hint, subject:str<=160, body_html, body_text, attachment_refs:[deliverable_index]}` - structure FIXED by template, model fills text slots only (`with_json_output`). The card renders subject + body for **review**; a `requires_confirmation: true` flag means **nothing sends without an explicit user click** (HITL preview-before-send is the blast-radius control from governance research).
(d) **M for draft+preview (no install). Sending: see risk.**
(e) **FLAG / instance-safety:** actual SMTP send is the riskiest surface. v1 ships **draft + preview + "copy to clipboard" / `mailto:`** only - **zero install, zero send-from-server, zero new attack surface.** Server-side `smtplib` send is a *separate, later* decision requiring (i) admin-configured SMTP creds in Settings (never hardcoded, mirror `sql_config`), (ii) explicit `requires_confirmation` gate, (iii) rate limiting, (iv) audit log. Do NOT build server send until the user explicitly wants it - YAGNI + blast radius. Charter: square card, plain.
(f) Depends on the deliverable kind + (optionally) PDF for attachments.

---

## Phase 4 - Native agent triggering (`build_report` / `draft_email` tools)

(a) Orchestrator built-in tools so an answer can end with "I've prepared a PDF / a draft email".
(b) Every persona: the deliverable arrives *as part of the answer*, not a manual export - the product feels agentic.
(c) Add `build_report` and `draft_email` to the orchestrator's in-process tool specs **exactly like `show_chart`/`show_table`/`show_kpi`** (verified intrinsic in-process function specs, not DSS tools). The tool's job is tiny: emit a `deliverable` ARTIFACT event with the chosen `template_id` + filled `slots`. It flows the proven seam (`_normalized_artifact_event` -> `save_artifacts`). The tool does **not** render bytes (keeps it cheap, keeps render server-trusted at download time). For FOREIGN/visual agents (mission 1's stretch goal), this stays **out of scope** here: the verified note is that a foreign agent has no shared state/exchange_id, so it cannot write our artifacts table today - flag as NEEDS-DSS-VALIDATION, do not design for it yet.
(d) **M, no install** (Python in the code agent, env 3.11; recoll both Code Agents per the standing process).
(e) Charter N/A (agent code). Safety: the tool only writes a bounded spec; the existing MAX_ARTIFACTS accumulation cap protects against a runaway agent.
(f) **Last** - depends on Phases 2/3 existing so the spec has a renderer.

---

## Sequencing + install summary

1. **Phase 0** PNG (client) + CSV (stdlib) - **zero install**, ship immediately. Export route + Deliverable menu scaffolding.
2. **Phase 1** XLSX - **ask user: `openpyxl`**.
3. **Phase 2** PDF (ReportLab) + matplotlib chart PNGs - **ask user: `reportlab`; verify/ask `matplotlib`**. Add `deliverable` artifact kind + template modules + claim-reconciliation.
4. **Phase 3** Email draft (preview/`mailto` only, **no install**); server SMTP deferred.
5. **Phase 4** `build_report`/`draft_email` agent tools - **no install**, recoll agents.

**Installs to approve (all pip, no system libs):** `reportlab` (required for PDF), `openpyxl` (XLSX - verify presence first), `matplotlib` (PDF chart embeds - very likely present, verify). **Never WeasyPrint** (system libs, violates #1). **Never server-SMTP without an explicit user decision** (blast radius).

**Files to touch (named, verified):** `storage/artifacts.py` (extend `_ARTIFACT_KINDS`/`_sanitize`), `agents/streaming.py` (`_normalized_artifact_event` branch), new `api/routes.py` export route (reuse `routes.py:640` guard + `evidence/throttle`), new `evidence/`-adjacent `deliverables/` package (`templates/*.py`, `chart_image.py`, `reconcile.py`), `evidence/chart_payload.py` (reuse `_resolve`/`_to_number`), frontend `ArtifactChart.vue` (wire `toBase64Image`), `services/backend.js` (add `exportDeliverable`), new `EvidencePanel.vue`/chat Deliverable card, `ui/icons.js` `download` (already present).

**Non-negotiable checkpoints:** no SQL re-run on export (use captured result only, #3); owner-scoped reads (#3); bounded everything (#2); Python 3.9 backend for all server export code (#8); model fills slots only via `with_json_output`, never structure; Orange charter on every new UI surface (#10); the agent installs nothing (#1).