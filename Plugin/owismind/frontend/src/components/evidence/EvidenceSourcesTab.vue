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
import EvidenceChips from './EvidenceChips.vue'
import EvidenceTable from './EvidenceTable.vue'
import SourceExplorer from '../sources/SourceExplorer.vue'
import SourceCalc from '../sources/SourceCalc.vue'
import SourceAnalyze from '../sources/SourceAnalyze.vue'

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

// Entering AGENT mode: lazily point the sources store at this agent + source (both
// calls are idempotent). Never opens the standalone panel (data usage without
// sources.open). Fires for clicks and for a programmatic default/drill change.
watch(active, (a) => {
  if (a && a.mode === 'agent') {
    sources.ensureAgent(exchangeAgentKey.value)
    sources.setSource(a.sourceId)
  }
})

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
const enriched = computed(() => !!(evidence.meta && evidence.meta.verification))
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
// SourceCalc / SourceAnalyze so their type-driven measures + numeric detection match the
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
    <!-- Unified selector: detected tables (legacy) then the agent's extra sources. -->
    <div v-if="showSelector" class="ev-src-selector">
      <span class="ev-src-selector-label">{{ t('ev.table.source') }}</span>
      <button
        v-for="e in entries"
        :key="e.key"
        type="button"
        class="ev-src-chip"
        :class="{ active: e.key === active.key }"
        @click="selectEntry(e)"
      >
        {{ e.label }}
      </button>
    </div>

    <!-- AGENT mode: the standalone explorer, driven by the unified selector. -->
    <SourceExplorer v-if="isAgentMode" embedded />

    <!-- LEGACY mode: the exchange-scoped explorer (chips + drill + search + Data/Analyze
         segmented + Calculate zone + table swap). -->
    <template v-else>
      <EvidenceChips />
      <div v-if="drill" class="ev-drill-band">
        <Icon name="filter" />
        <span class="ev-drill-text">{{ t('ev.proof.drill.banner', [drillLabels]) }}</span>
        <button class="ev-drill-exit" :title="t('ev.proof.drill.exit')" @click="onExitDrill">
          <Icon name="x" />
        </button>
      </div>
      <span v-if="enriched" class="ev-explore">{{ t('ev.proof.explore') }}</span>

      <!-- Top area: search + the Data|Analyze switch on the LEFT, the Calculate zone on the
           RIGHT (wraps to a stacked block when narrow) - mirrors the standalone Source
           explorer, driven by the SHARED SourceCalc on the evidence surface. -->
      <div class="ev-src-top">
        <div class="ev-src-top-main">
          <!-- Full-text search over the WHOLE exchange table - Enter or button only. -->
          <div class="ev-src-search">
            <Icon name="search" class="ev-src-search-ico" />
            <input
              v-model="evSearchTerm"
              type="text"
              class="ev-src-search-input"
              maxlength="200"
              :placeholder="t('src.search.placeholder')"
              @keydown.enter.prevent="submitEvSearch"
            />
            <button v-if="evSearchTerm" type="button" class="ev-src-search-clear" :title="t('x.close')" @click="clearEvSearch">
              <Icon name="x" />
            </button>
            <button type="button" class="ev-src-search-go" :aria-label="t('src.search.go')" :title="t('src.search.go')" @click="submitEvSearch">
              <Icon name="search" />
            </button>
          </div>
          <div v-if="evOneChar" class="ev-src-search-hint">{{ t('src.search.min') }}</div>
          <!-- Data / Analyze view switch. The chips above are shared context in BOTH views;
               only the surface below swaps. Plain toggle buttons (aria-pressed). -->
          <div class="ev-viewseg">
            <button
              type="button"
              class="ev-viewseg-btn"
              :class="{ active: !evidence.analyzeOpen }"
              :aria-pressed="!evidence.analyzeOpen"
              @click="evidence.setAnalyzeOpen(false)"
            >{{ t('src.view.data') }}</button>
            <button
              type="button"
              class="ev-viewseg-btn"
              :class="{ active: evidence.analyzeOpen }"
              :aria-pressed="evidence.analyzeOpen"
              @click="evidence.setAnalyzeOpen(true)"
            >{{ t('src.view.analyze') }}</button>
          </div>
        </div>
        <!-- Calculate zone (pick a column, see its key figures over the current filter). -->
        <SourceCalc class="ev-src-top-calc" :surface="evidence" :columns="evColumns" />
      </div>

      <!-- Data / Analyze swap of the table (chips + search stay above in both). -->
      <EvidenceTable v-if="!evidence.analyzeOpen" />
      <SourceAnalyze v-else :surface="evidence" :columns="evColumns" />
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
.ev-src-tab :deep(.ev-table),
.ev-src-tab :deep(.src-table) { flex: 1; min-height: 0; }
.ev-src-tab :deep(.ev-table-scroll),
.ev-src-tab :deep(.src-table-scroll) { flex: 1 1 auto; max-height: none; }
/* The embedded explorer fills the column too. */
.ev-src-tab :deep(.src-explorer) { flex: 1; min-height: 0; }
/* The Analyze mini-pivot fills the column too (it keeps its own inner scroll cap). */
.ev-src-tab :deep(.src-analyze) { flex: 1; min-height: 0; }

/* Top area - the search + Data|Analyze switch on the left, the Calculate zone on the
   right. A flex row that wraps to a stacked block on narrow widths (the Evidence panel
   is often a ~480px column). Mirrors the standalone Source explorer's top area. */
.ev-src-top { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--s-4) var(--s-5); flex: none; }
.ev-src-top-main { flex: 1 1 220px; min-width: 0; display: flex; flex-direction: column; gap: var(--s-3); }
.ev-src-top-calc { flex: 1 1 240px; min-width: 0; }

/* Data / Analyze segmented control - a 1px-bordered row; the active segment fills with
   ink (charter recipe). Square, flat, self-sized (does not stretch full width). */
.ev-viewseg {
  display: inline-flex; align-self: flex-start;
  border: 1px solid var(--border-strong); border-radius: 0; overflow: hidden;
}
.ev-viewseg-btn {
  padding: 5px 16px; font-size: var(--fs-xs); color: var(--text-2);
  background: var(--bg); transition: all var(--dur) var(--ease);
}
.ev-viewseg-btn + .ev-viewseg-btn { border-left: 1px solid var(--border-strong); }
.ev-viewseg-btn:hover:not(.active) { background: var(--surface-hover); color: var(--text); }
.ev-viewseg-btn.active { background: var(--text); color: var(--bg); font-weight: var(--fw-medium); }

/* Unified selector - small square chips, orange only on the active one. */
.ev-src-selector {
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2);
  flex: none;
}
.ev-src-selector-label {
  font-size: 11px; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.ev-src-chip {
  padding: 3px 10px; border: 1px solid var(--border); border-radius: 0;
  font-size: var(--fs-xs); color: var(--text-2); background: var(--surface);
  transition: all var(--dur) var(--ease);
}
.ev-src-chip:hover { background: var(--surface-hover); color: var(--text); }
.ev-src-chip.active { border-color: var(--orange); color: var(--orange-text); background: var(--orange-soft); }
:global(body[data-theme="dark"] .ev-src-chip.active) { background: var(--orange-soft-dark); }

/* Drill banner - discreet dashed-orange band (moved from EvidencePanel). */
.ev-drill-band {
  display: flex; align-items: center; gap: var(--s-2); flex: none;
  padding: 4px 10px; border: 1px dashed var(--orange); border-radius: var(--r-sm);
  background: var(--orange-soft);
}
.ev-drill-band :deep(.ui-icon) { flex: none; width: 12px; height: 12px; color: var(--orange-text); }
.ev-drill-text {
  flex: 1; min-width: 0; font-size: var(--fs-xs); color: var(--orange-text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ev-drill-exit {
  flex: none; padding: 2px; border-radius: var(--r-sm); color: var(--orange-text);
  transition: all var(--dur) var(--ease);
}
.ev-drill-exit:hover { background: var(--surface-hover); color: var(--text); }
.ev-drill-exit :deep(.ui-icon) { width: 12px; height: 12px; }
:global(body[data-theme="dark"] .ev-drill-band) { background: var(--orange-soft-dark); }

/* "Explore source data" label over the table (only for the enriched contract). */
.ev-explore {
  flex: none;
  font-size: var(--fs-xs); color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
  margin-bottom: calc(-1 * var(--s-2));
}

/* Exchange-table search box - flat, square, 1px border (mirrors the source search). */
.ev-src-search {
  display: flex; align-items: center; gap: var(--s-2); flex: none;
  border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--bg); padding: 0 8px;
}
.ev-src-search-ico { color: var(--text-3); flex: none; width: 15px; height: 15px; }
.ev-src-search-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  padding: 8px 4px; color: var(--text); font-size: var(--fs-sm);
}
.ev-src-search-input:focus { outline: none; }
.ev-src-search-clear {
  flex: none; padding: 3px; border-radius: 0; color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.ev-src-search-clear:hover { color: var(--text); }
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
