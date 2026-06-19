Now I have enough context to write the full analysis. Let me compile the findings.

---

## Frontend Capabilities & UX Surface

### 1. What a User Can DO Today

**Chat surface (`ChatView.vue`, `PromptBar.vue`, `ChatThread.vue`)**
- Type a message in a growing textarea (max 200px), submit with Enter or the Send button (`PromptBar.submit()`).
- Stop generation mid-run: the Send button becomes a Stop button while `chat.sending` is true; `chat.stopGeneration()` posts `POST /owismind-api/chat/stop` and shows a pulsing "Stopping..." banner until the terminal `stopped` event lands.
- Choose the **agent** via `AgentPicker.vue`: a `<Menu>` populated from `session.agents` (server-resolved opaque `key` + `label`; raw `agent_id` never travels to the front). Only enabled + admin-authored agents appear.
- Choose the **model mode** via `ModelModePicker.vue`: a two-pane modal (list + detail panel) with three options - Eco (Gemini 3.1 Flash-Lite, green, recommended), Medium (Gemini 3.5 Flash, orange), High (Claude Sonnet, red). Cost/speed are 5-dot meters. The choice is confirmed with a Valider/Annuler footer (click-to-select, no hover preview). The active mode is stored in `useUiStore.modelMode`.
- **Regenerate** an answer (new exchange sibling from the same parent). **Version navigation** (prev/next arrows) walks siblings when a prompt was edited or regenerated.
- **Copy** the answer text to clipboard via `navigator.clipboard.writeText(answerText(v))` (`copy()` in `MessageAgent.vue`).
- **Feedback** per message: thumbs-up / thumbs-down persisted immediately via `POST /owismind-api/chat/feedback`; a modal collects reasons + comment (dislike). The `...` menu can also open detailed-feedback for any rating.
- Browse **conversation history** from the sidebar (`conversationList.js`, keyset-paginated); opening a conversation lazy-loads messages via `GET /owismind-api/conversation`.
- Control the **agent context window** (10-50 messages) from Settings (slider, stored in `prefs.js`).
- Switch **language** (FR/EN) and **theme** (light/dark) from Settings, persisted in localStorage.

**Evidence Studio right panel (`EvidencePanel.vue`)**
- Open manually from the "Open Evidence" button in `MessageAgent.vue`'s footer (gated on `v.sql.length && v.exchangeId`), or auto-opens post-run when evidence is available.
- **Filter chips** (`EvidenceChips.vue`): all chips are editable; picker loads bounded distinct values; `=`/`IN` pre-selects the picker; reset/remove closes the popover.
- **Drill-down** (`evidence.drill`): clicking a captured-result row scopes the source table to that row's key values; an orange dashed band signals drill mode; an X button exits.
- **Source click-through** (`EvidenceSources.vue`): when the agent's registry has a `source_url`, the dataset name is a `<a target="_blank">` link to Dataiku.
- **Infinite scroll** on the source data table (up to 500 rows, 10 pages of 50, capped by `MAX_ROWS`).
- **Agent library** (`AgentsView.vue`): searchable grid of enabled agents with admin-authored taglines/descriptions/capabilities; selecting a card navigates to `/chat` with that agent pre-selected.
- **Admin console** (`AdminView.vue`): tabs for storage info, users + admin-flag toggling, agents whitelist + inline profile editor (tagline/description/capabilities/tools/icon/badge, server-validated), and budget configuration (global default + temp boost + per-user overrides with expiry dates).
- **Settings** (`SettingsView.vue`): profile (read-only from `/me`), theme, language, context window, real budget card (spend/limit/remaining/reset date with transparency line about the limit source), real usage card (tokens + lifetime).

### 2. Artifact / Output Types That Render Today - Right-Panel Tab Population

`EvidencePanel.vue` derives `tabItems` from `meta.artifacts` (returned by `GET /owismind-api/evidence/meta`). A tab is added once per distinct `kind`. Currently supported kinds:

| Tab key | Component | How populated |
|---|---|---|
| `evidence` (always) | `EvidenceTrust`, `EvidenceSources`, `EvidenceChips`, `EvidenceCalc`, `EvidenceResult`, `EvidenceTable`, `EvidenceSql` | Full proof surface: trust badge (solid/dashed/muted - NEVER green), sources, filter chips, calculation steps, captured result, live source table, raw SQL (collapsible, also shown in `MessageAgent.vue` inline) |
| `chart` | `ArtifactChart.vue` | Chart.js canvas; payload (`{ labels, datasets }`) built server-side by `evidence/chart_payload.py` and delivered inside `artifacts[].data`. Types: `line`, `bar`, `bar horizontal`, `bar stacked`, `pie`, `doughnut`; styles: `smooth`, `stepped`, `area`. Re-renders on theme change via `MutationObserver`. |
| `table` | `ArtifactTable.vue` | Captured agent result rows (from `meta.result`). |
| `kpi` | `ArtifactKpi.vue` | Big headline figure with optional delta + delta% (up/down arrow, green/red badge). Server-built by `chart_payload.build_kpi_payload`. Compact number formatting (M, k). |

**Collapsible SQL** in `MessageAgent.vue` (inline, in the answer column): shows `v.sql[]` - each entry has `{ sql, success, row_count }` formatted as `<pre class="sql-code">`. This is separate from the Evidence tab.

**Trust badge** levels: `certified` (solid orange pill), `partial` (dashed orange pill), `declared` (muted grey pill). Determined deterministically by `trustLevel()` in `composables/evidenceProof.js` - no LLM involved.

**Per-message token/cost line** (`MessageAgent.vue` L181-232): `↑ in · ↓ out tokens · ~$cost` in monospace, shown on every terminal exchange that carries usage data.

**Timeline steps** (`MessageAgent.vue`): live bounded ticker (last 5 lines with fade-out mask) during run; collapses to one expandable header line post-run. Sub-agent steps are indented with a left border (`.sub-step`). Step durations use backend emission stamps when available.

### 3. Export / Download Today

**No export or download capability exists.** There is no `download`, `toBlob`, `toBase64`, `saveAs`, `FileSaver`, CSV/XLSX/PDF generation, or image export anywhere in `frontend/src/`. The `download` SVG icon exists in `icons.js` (L67) but it is not wired to any action. The only "export" is **copy to clipboard** (`navigator.clipboard.writeText`) of the plain markdown answer text. Chart.js `instance` is kept in a module-level `let` in `ArtifactChart.vue` but `instance.toBase64Image()` is never called.

### 4. i18n Mechanism

Two-layer system:
- **`messages.json`** (pristine): the 1:1 port of the original maquette's `window.OWI_I18N` extraction. Never edited directly.
- **`extra.js`**: flat dotted keys per locale, merged at boot via `i18n.global.mergeLocaleMessage('fr', extraMessages.fr)` and `mergeLocaleMessage('en', ...)`. Also merged: `timelineMessages` from `registries/timelineSteps.js` (event-kind labels).

To add new strings: add `'my.key': 'value'` in **both** `extra.js` locale objects (`fr` and `en`). Interpolation is positional: `t('key', [arg0, arg1])` matches `{0}`, `{1}` placeholders. Locale switching via `setLocale(id)` from `i18n/index.js`, persisted to `localStorage('owismind.lang')`. Adding a third language: add its id to `langs.json` + a locale block to `messages.json` + a block to `extra.js`.

### 5. Extension Points for New Output Types

These are the cleanest seams, named by exact file:

**A. New artifact tab (e.g. a map, a PDF preview, a "dashboard" embed):**
1. Agent calls `show_<type>` tool -> backend stores the artifact in `webapp_artifacts_v1` with `kind='map'` (or whatever).
2. `evidence/chart_payload.py` adds a `build_map_payload()` function.
3. `/owismind-api/evidence/meta` includes the artifact in `meta.artifacts[]`.
4. `EvidencePanel.vue` `tabItems` computed already handles unknown kinds - add the `kind` to the `seen.has()` guard.
5. Create `ArtifactMap.vue` (or similar) and add a `<template v-else-if="activeTab === 'map'">` block in `EvidencePanel.vue` (following the existing chart/table/kpi pattern at L150-169).
6. Add i18n key `'art.tab.map'` in `extra.js`.

**B. Chart PNG download:**
- `ArtifactChart.vue` already holds `let instance` (Chart.js). Add a Download button that calls `instance.toBase64Image()` + `document.createElement('a').click()`. No new dependency needed. One button, one `<a download>` trick. The `download` icon already exists in `icons.js`.

**C. CSV/XLSX download of evidence table or captured result:**
- Extension point: `EvidenceTable.vue` (for the live source rows) or `ArtifactTable.vue` (for captured result). Neither has downloads today.
- No install allowed: a pure CSV serialization (join columns with commas, `\n`) can be done without a library; for XLSX a new dep would need user install.
- The data is already in `evidence.rows` (the store ref holding up to 500 rows). A download button in `EvidenceTable.vue` would iterate `rows.value` and trigger a Blob download.

**D. New output type in the chat column (e.g. email draft, report preview):**
- Add a new `kind` to the timeline reducer (`composables/timelineModel.js`) and `timelineBodyItems` selector.
- Render it in `MessageAgent.vue` inside the `<template v-for="item in bodyItems">` block (L373-378), adding a new `v-else-if="item.kind === 'email_draft'"` branch.
- The backend needs to emit the new event kind in `agents/streaming.py`.

**E. PDF report:**
- No backend PDF route exists. Extension seam: a new `POST /owismind-api/conversation/export` route in `python-lib/owismind/routes.py` that assembles the conversation + evidence into a PDF (Python 3.9, so `fpdf2` or `reportlab` - user must install). Frontend: a button in `MessageAgent.vue` or `EvidencePanel.vue` calling a new `backend.js` function `exportConversation(sessionId, format)`.

**F. New chart type (waterfall, scatter):**
- Only change needed: `ArtifactChart.vue` `buildConfig()` function (extend the `chartType` / `style` switch). The server spec in `chart_payload.py` would add the new `type` string. The Chart.js dep already supports both.

### 6. Envisioned-but-Deferred Product Features (cahier des charges §5, §7)

All of the following are named in the spec as explicitly deferred:

- **Evidence Studio multi-agent mode** (§5 "Multi-agent"): one Evidence panel per agent called, lazy-loaded only for the active agent. States: `not started / running / completed / loaded / not loaded / failed / no evidence / restricted`.
- **Dataset tab in Evidence**: full source-data explorer with search, column filters, sort, keyset pagination, lazy-loading on tab open - with a "sample warning" if the dataset was sampled. (Distinct from the current live-rows table which already lazy-loads.)
- **Trace tab**: two views - user-readable (steps/agents/tools/durations/errors) and debug (raw eventKind/blockId/toolName). The current inline collapsible timeline in `MessageAgent.vue` is the partial implementation.
- **Cost tab**: token breakdown by sub-agent, cost per LLM call, call count, duration. The per-message usage line is the current partial.
- **Export / report** (§7): Markdown, PDF, PowerPoint, "fiche client 360", executive summary, email send. None implemented.
- **New artifact kinds** (§7): image, map, slide, contract, Excel, external dashboard embed.
- **Budget dashboard** (§6): usage history by day/conversation/agent, trends, alerts at 50%/80%/100% thresholds. Currently only the current-month totals are shown in Settings; the admin can set per-user quotas.
- **AI-generated conversation title** (noted in `CONTEXT.md` "colonne `title` en base - toujours différée"): title is currently derived by a SQL regex on the first message, capped at 56 chars.
- **Agent evaluation / benchmarking** (§7): quality score, golden questions, version comparison, success rate. No implementation exists.
- **Voice input** (STT backend): `PromptBar.micClick()` shows a toast "bientôt" - the button is a placeholder.
- **Edit profile** in Settings: the button is disabled with a "soon" comment - no `PUT /me` route exists.
- **Keyset pagination / drill multi-queries** in Evidence (listed in `CONTEXT.md` §0★★ next steps).