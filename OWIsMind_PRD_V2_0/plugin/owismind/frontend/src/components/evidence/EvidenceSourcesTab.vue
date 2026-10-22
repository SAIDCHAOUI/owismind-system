<script setup>
// Unified "Source data" tab of the Evidence panel. It merges, in ONE selector row:
//   (a) the exchange's DETECTED source tables (evidence.sources) - browsed through
//       the exchange-scoped evidence store (LEGACY mode: agent chips + drill + the
//       exact SQL scope), plus a full-text search over the whole exchange table;
//   (b) the agent's CONFIGURED source datasets whose dataset is NOT already detected
//       - browsed through the sources store (AGENT mode: the standalone explorer).
// Detected entries come first; the selector hides when there is a single entry.
//
// The agent of the exchange is resolved via the chat store (agentKeyForExchange). If
// it cannot be resolved, or the agent exposes no extra sources, only the detected
// entries are offered - i.e. the v1 behaviour, untouched.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useSourcesStore } from '../../stores/sources.js'
import { useChatStore } from '../../stores/chat.js'
import { useSessionStore } from '../../stores/session.js'
import { Icon } from '../ui'
import DatasetPick from '../sources/DatasetPick.vue'
import EvidenceChips from './EvidenceChips.vue'
import EvidenceTable from './EvidenceTable.vue'
import SourceExplorer from '../sources/SourceExplorer.vue'
import SourceWorkspace from '../sources/SourceWorkspace.vue'

const { t } = useI18n()
const evidence = useEvidenceStore()
const sources = useSourcesStore()
const chat = useChatStore()
const session = useSessionStore()

// The agent that produced the exchange, then its configured source datasets.
const exchangeAgentKey = computed(() => chat.agentKeyForExchange(evidence.exchangeId))
const agentSources = computed(() => {
  const key = exchangeAgentKey.value
  if (!key) return []
  const a = session.agents.find((x) => x.key === key)
  return a && Array.isArray(a.sources) ? a.sources : []
})

// The detected tables the agent's SQL actually reads (evidence.sources = matched
// datasets). These use LEGACY mode. Compared case-insensitively against the agent's
// configured sources so a configured dataset already detected is not offered twice.
const detectedEntries = computed(() =>
  (evidence.sources || []).map((s) => ({
    mode: 'legacy',
    dataset: s.dataset,
    label: s.label || s.dataset,
    key: 'legacy:' + s.dataset,
  })),
)
const detectedDatasets = computed(
  () => new Set(detectedEntries.value.map((e) => String(e.dataset).toLowerCase())),
)
const agentEntries = computed(() => {
  const seen = detectedDatasets.value
  return agentSources.value
    .filter((s) => s.dataset && !seen.has(String(s.dataset).toLowerCase()))
    .map((s) => ({
      mode: 'agent',
      sourceId: s.id,
      dataset: s.dataset,
      label: s.label || '#' + s.id,
      key: 'agent:' + s.id,
    }))
})
// Detected first, then the agent's extra sources.
const entries = computed(() => detectedEntries.value.concat(agentEntries.value))
const showSelector = computed(() => entries.value.length > 1)

// The dataset the LEGACY view currently re-queries (the evidence store's selection,
// or the first detected table by default). Used to keep the selector in sync and to
// decide whether a detected click needs a re-query.
const activeLegacyDataset = computed(
  () => evidence.selectedTable || (evidence.sources[0] && evidence.sources[0].dataset) || null,
)

// Which selector entry is active. Null selection resolves to the first entry (a
// detected/legacy one). An empty list still renders the legacy block (v1 fallback).
// The selection lives in the exchange-scoped evidence store (not a local ref) so an
// agent-mode dataset choice survives a tab round-trip - this component is v-if'd in
// EvidencePanel and remounts. The store resets it to null on every exchange/close.
const selectedKey = computed({
  get: () => evidence.sourceTabKey,
  set: (v) => {
    evidence.sourceTabKey = v
  },
})
const active = computed(() => {
  const list = entries.value
  if (!list.length) return { mode: 'legacy' }
  return list.find((e) => e.key === selectedKey.value) || list[0]
})
const isAgentMode = computed(() => active.value.mode === 'agent')

function selectEntry(entry) {
  if (!entry) return
  selectedKey.value = entry.key
  // Legacy: re-query only when picking a DIFFERENT detected table. The currently
  // active one keeps the evidence store's state (agent chips, drill) intact - the
  // agent-mode sources store is separate, so switching back needs no reset.
  if (entry.mode === 'legacy' && entry.dataset !== activeLegacyDataset.value) {
    evidence.setTable(entry.dataset)
  }
}

// Selector as the SHARED dataset dropdown (DatasetPick), exactly where the standalone
// panel puts it: first thing on the top row, before the search.
const datasetOptions = computed(() => entries.value.map((e) => ({ key: e.key, label: e.label })))
function onDatasetChange(key) {
  selectEntry(entries.value.find((e) => e.key === key))
}
// The search names WHAT it searches (mirror of the standalone explorer).
const evSearchPlaceholder = computed(() =>
  active.value && active.value.label
    ? t('src.search.in', [active.value.label])
    : t('src.search.placeholder'),
)

// Entering AGENT mode: lazily point the sources store at this agent + source (both
// calls are idempotent). Never opens the standalone panel (data usage without
// sources.open). IMMEDIATE: on a SQL-less exchange there are no detected entries, so
// the FIRST active entry is already agent-mode - without immediate the explorer would
// mount on a never-initialized store and show an empty table.
watch(active, (a) => {
  if (a && a.mode === 'agent') {
    sources.ensureAgent(exchangeAgentKey.value)
    sources.setSource(a.sourceId)
  }
}, { immediate: true })

// A new exchange resets the selection so `active` recomputes to the first entry.
watch(() => evidence.exchangeId, () => {
  selectedKey.value = null
  evSearchTerm.value = evidence.q || ''
})

// Drilling a result row lands on this tab (evidence.drillIntoResultRow sets the tab):
// force the selection back to the LEGACY entry of the drilled table so the drilled
// rows are actually visible (never a stale agent-mode view).
watch(() => evidence.drill, (d) => {
  if (!d) return
  const dataset = activeLegacyDataset.value
  const entry =
    entries.value.find((e) => e.mode === 'legacy' && e.dataset === dataset) ||
    entries.value.find((e) => e.mode === 'legacy')
  if (entry) selectedKey.value = entry.key
})

// ── Legacy-mode extras (moved here from EvidencePanel) ──────────────────────────
const drill = computed(() => evidence.drill || null)
const drillLabels = computed(() => {
  const labels = drill.value && Array.isArray(drill.value.labels) ? drill.value.labels : []
  return labels
    .map((l) => l.column + ' = ' + (l.value == null ? '-' : String(l.value)))
    .join(', ')
})
function onExitDrill() {
  const fn = evidence.exitDrill
  if (typeof fn === 'function') fn()
}

// The active exchange table's typed columns ([{ name, type }]), passed to the shared
// SourceWorkspace so its type-driven measures + numeric detection match the
// legacy table. Empty until meta loads.
// KNOWN LIMITATION (same convention as the rows-table headers): meta.columns are the
// DEFAULT (first matched) table's live columns, captured once at open; switching to
// another matched table (multi-source SQL) re-queries rows/aggregates against the
// SELECTED table but does NOT refetch meta, so the pickers may list columns the
// selected table lacks (the server then answers a clean 400, shown as the zone's
// error state). Accepted trade-off: multi-table joins are rare and headers already
// share it; a per-table meta refetch is the future fix.
const evColumns = computed(() => (evidence.meta && evidence.meta.columns) || [])

// ── Exchange-table search (legacy mode) - Enter/button only, no debounce ────────
const evSearchTerm = ref(evidence.q || '')
const evOneChar = computed(() => evSearchTerm.value.trim().length === 1)
function submitEvSearch() {
  evidence.setQuery(evSearchTerm.value)
}
function clearEvSearch() {
  evSearchTerm.value = ''
  evidence.setQuery('')
}
</script>

<template>
  <div class="ev-src-tab">
    <!-- AGENT mode: the standalone explorer; the unified selector rides ITS top row
         (dataset slot), exactly where the standalone panel puts its own dropdown. -->
    <SourceExplorer v-if="isAgentMode" embedded>
      <template #dataset>
        <DatasetPick
          v-if="showSelector"
          :options="datasetOptions"
          :value="active.key"
          @change="onDatasetChange"
        />
      </template>
    </SourceExplorer>

    <!-- LEGACY mode: the exchange-scoped explorer - the SAME layout as the standalone
         Source panel (user ask 2026-08-13, one structure to maintain): dataset dropdown
         + search + the Data|Analyze switch on ONE top row, the filters on one line
         below, then the surface (the raw table, or the shared Analyze workspace over
         the evidence store). -->
    <template v-else>
      <!-- ONE top row: dropdown, then the search taking every remaining pixel, then
           the view switch (mirrors the standalone panel's topbar economy). -->
      <div class="ev-src-top">
        <DatasetPick
          v-if="showSelector"
          :options="datasetOptions"
          :value="active.key"
          @change="onDatasetChange"
        />
        <!-- Full-text search over the WHOLE exchange table - Enter or button only. -->
        <div class="ev-src-search">
          <Icon name="search" class="ev-src-search-ico" />
          <input
            v-model="evSearchTerm"
            type="text"
            class="ev-src-search-input"
            maxlength="200"
            :placeholder="evSearchPlaceholder"
            @keydown.enter.prevent="submitEvSearch"
          />
          <button v-if="evSearchTerm" type="button" class="ev-src-search-clear" :title="t('x.close')" @click="clearEvSearch">
            <Icon name="x" />
          </button>
          <button type="button" class="ev-src-search-go" :aria-label="t('src.search.go')" :title="t('src.search.go')" @click="submitEvSearch">
            <Icon name="search" />
          </button>
        </div>
        <!-- Data / Analyze view switch. The chips below are shared context in BOTH views;
             only the surface below swaps. Plain toggle buttons (aria-pressed). -->
        <div class="ev-viewseg">
          <button
            type="button"
            class="ev-viewseg-btn"
            :class="{ active: !evidence.analyzeOpen }"
            :aria-pressed="!evidence.analyzeOpen"
            :title="t('src.view.hint.data')"
            @click="evidence.setAnalyzeOpen(false)"
          >{{ t('src.view.data') }}</button>
          <button
            type="button"
            class="ev-viewseg-btn"
            :class="{ active: evidence.analyzeOpen }"
            :aria-pressed="evidence.analyzeOpen"
            :title="t('src.view.hint.analyze')"
            @click="evidence.setAnalyzeOpen(true)"
          >{{ t('src.view.analyze') }}</button>
        </div>
      </div>
      <div v-if="evOneChar" class="ev-src-search-hint">{{ t('src.search.min') }}</div>

      <!-- Filters on ONE line (mirror of the panel), locked agent chips included. -->
      <EvidenceChips />
      <div v-if="drill" class="ev-drill-band">
        <Icon name="filter" />
        <span class="ev-drill-text">{{ t('ev.proof.drill.banner', [drillLabels]) }}</span>
        <button class="ev-drill-exit" :title="t('ev.proof.drill.exit')" @click="onExitDrill">
          <Icon name="x" />
        </button>
      </div>

      <!-- Data / Analyze swap of the table (topbar + chips stay above in both). The
           Analyze view is the SHARED workspace, hosted on the evidence store. -->
      <EvidenceTable v-if="!evidence.analyzeOpen" />
      <!-- The workspace's data table picks cells against THIS exchange's scope, and names
           its provenance with the browsed table (same label the legacy table reports). -->
      <SourceWorkspace
        v-else
        :surface="evidence"
        :columns="evColumns"
        :source-label="activeLegacyDataset"
      />
    </template>
  </div>
</template>

<style scoped>
/* Full-height flex column: the selector / chips / search sit on top (flex:none) and
   the table fills the rest and scrolls (see the :deep overrides below). */
.ev-src-tab {
  display: flex; flex-direction: column; gap: var(--s-4);
  flex: 1; min-height: 0;
}
/* Let the rows table fill the remaining panel height instead of a capped block:
   flex:1 on the table, an uncapped scroll container (keeps the ~220px floor). */
/* Every rows table fills the panel: the Data view AND the Analyze workspace's data pane
   (the same SourceTable since 2026-10-20). */
.ev-src-tab :deep(.ev-table),
.ev-src-tab :deep(.src-table) { flex: 1; min-height: 0; }
.ev-src-tab :deep(.ev-table-view),
.ev-src-tab :deep(.src-table .src-table-view) { flex: 1 1 auto; min-height: 0; }
.ev-src-tab :deep(.ev-table-scroll),
.ev-src-tab :deep(.src-table .src-table-scroll) { flex: 1 1 auto; max-height: none; }
/* The embedded explorer fills the column too. */
.ev-src-tab :deep(.src-explorer) { flex: 1; min-height: 0; }
/* The shared Analyze workspace fills the column (its result, then the data pane). */
.ev-src-tab :deep(.src-ws) { flex: 1; min-height: 0; }

/* ONE top row - the search takes every remaining pixel, the Data|Analyze switch rides
   its right end; wraps only when the Evidence panel is squeezed very narrow. */
.ev-src-top { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2) var(--s-3); flex: none; }

/* Data / Analyze segmented control - a 1px-bordered row; the active segment fills with
   ink (charter recipe). Rounded (premium 2026-08-13), flat, self-sized - the exact twin
   of the standalone explorer's switch. */
.ev-viewseg {
  display: inline-flex; align-items: stretch; align-self: center;
  height: 40px; box-sizing: border-box;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill); overflow: hidden;
}
.ev-viewseg-btn {
  display: inline-flex; align-items: center;
  padding: 0 16px; font-size: var(--fs-xs); color: var(--text-2);
  background: var(--bg); transition: all var(--dur) var(--ease);
}
.ev-viewseg-btn + .ev-viewseg-btn { border-left: 1px solid var(--border-strong); }
.ev-viewseg-btn:hover:not(.active) { background: var(--surface-hover); color: var(--text); }
.ev-viewseg-btn.active { background: var(--text); color: var(--bg); font-weight: var(--fw-medium); }

/* The unified selector is the SHARED DatasetPick dropdown on the top row (its styles
   live in sources/DatasetPick.vue). */

/* Drill banner - discreet dashed-orange band (moved from EvidencePanel). It slides in
   from the row that was drilled: the band explains a narrowing the user just triggered,
   so it must be seen arriving. */
.ev-drill-band {
  display: flex; align-items: center; gap: var(--s-2); flex: none;
  padding: 5px 12px; border: 1px dashed var(--orange); border-radius: var(--r);
  background: var(--orange-soft);
  animation: ev-drill-in var(--dur) var(--ease-out) both;
}
@keyframes ev-drill-in {
  from { opacity: 0; transform: translateY(-6px); }
}
@media (prefers-reduced-motion: reduce) { .ev-drill-band { animation: none; } }
.ev-drill-band :deep(.ui-icon) { flex: none; width: 12px; height: 12px; color: var(--orange-text); }
.ev-drill-text {
  flex: 1; min-width: 0; font-size: var(--fs-xs); color: var(--orange-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ev-drill-exit {
  flex: none; display: inline-flex; padding: 3px; border-radius: var(--r-pill);
  color: var(--orange-text); transition: all var(--dur) var(--ease);
}
.ev-drill-exit:hover { background: var(--surface-hover); color: var(--text); }
.ev-drill-exit :deep(.ui-icon) { width: 12px; height: 12px; }
:global(body[data-theme="dark"] .ev-drill-band) { background: var(--orange-soft-dark); }

/* Exchange-table search box - rounded, quiet border that wakes up on focus, exactly
   like the standalone explorer's search (premium 2026-08-13). */
.ev-src-search {
  display: flex; align-items: center; gap: var(--s-2);
  flex: 1 1 220px; min-width: 0;
  height: 40px; box-sizing: border-box;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill);
  background: var(--bg); padding: 0 10px;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ev-src-search:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }
.ev-src-search-ico { color: var(--text-3); flex: none; width: 15px; height: 15px; }
.ev-src-search-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  padding: 0 4px; color: var(--text); font-size: var(--fs-sm);
}
.ev-src-search-input:focus { outline: none; }
.ev-src-search-clear {
  flex: none; padding: 4px; border-radius: var(--r-pill); color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.ev-src-search-clear:hover { color: var(--text); background: var(--surface-hover); }
.ev-src-search-clear :deep(.ui-icon) { width: 13px; height: 13px; }
.ev-src-search-go {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  padding: 5px 8px; margin-left: 2px; border-left: 1px solid var(--border);
  color: var(--text-2); transition: all var(--dur) var(--ease);
}
.ev-src-search-go:hover { color: var(--orange); background: var(--surface-hover); }
.ev-src-search-go :deep(.ui-icon) { width: 15px; height: 15px; }
.ev-src-search-hint { flex: none; font-size: var(--fs-xs); color: var(--text-3); margin-top: calc(-1 * var(--s-2)); }
</style>
