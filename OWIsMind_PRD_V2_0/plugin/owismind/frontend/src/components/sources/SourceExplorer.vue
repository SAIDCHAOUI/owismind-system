<script setup>
// Source Data Explorer body - store-driven. Renders (top to bottom): ONE top line
// holding the dataset dropdown (hidden when there is a single source or the explorer
// is embedded), the Enter/button global search naming the dataset it searches and the
// user filter chips (they wrap under it once the search reaches its floor), then the
// surface itself. Used in the standalone SourcePanel
// (the pre-conversation empty screen; the Data|Analyze switch lives in ITS header to
// save a body row) and, with `embedded`, inside the Evidence "Source data" tab (which
// has no such header, so the switch renders inline there); it feeds the sources store,
// so the host only has to ensureAgent() first.
//
// Two clean surfaces, one job each: DATA browses rows (search, filters, sort, cells),
// ANALYZE computes (measures, result, and the same rows table under them).
// Everything that computes lives in SourceWorkspace - the Data view carries no figures.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { Icon } from '../ui'
import DatasetPick from './DatasetPick.vue'
import SourceChips from './SourceChips.vue'
import SourceTable from './SourceTable.vue'
import SourceWorkspace from './SourceWorkspace.vue'

// `embedded` hides the internal dataset selector: hosted inside the Evidence
// "Source data" tab, the unified selector there drives the dataset choice.
defineProps({ embedded: { type: Boolean, default: false } })

const { t } = useI18n()
const sources = useSourcesStore()

const activeSourceId = computed(() => sources.activeSourceId)
const hasTabs = computed(() => sources.sourceList.length > 1)
// The dataset choice is a DROPDOWN (shared DatasetPick), not one pill per source: an
// agent may expose ten datasets, and a pill row would eat the panel (user ask
// 2026-08-13). String-keyed so the select round-trips the EXACT id.
const activeKey = computed(() => (activeSourceId.value == null ? '' : String(activeSourceId.value)))
const datasetOptions = computed(() =>
  sources.sourceList.map((s) => ({ key: String(s.id), label: s.label })),
)
function onDatasetChange(key) {
  const s = sources.sourceList.find((x) => String(x.id) === key)
  if (s) sources.setSource(s.id)
}
// The search names WHAT it searches: "Search in DRIVE Revenues..." beats a generic
// placeholder (the user must never wonder whether this searches the chat or the data).
const activeLabel = computed(() => {
  const s = sources.sourceList.find((x) => x.id === activeSourceId.value)
  return (s && s.label) || ''
})
const searchPlaceholder = computed(() =>
  activeLabel.value ? t('src.search.in', [activeLabel.value]) : t('src.search.placeholder'),
)

// Search fires ONLY on Enter or the explicit search button (no debounce): the input
// binds to a LOCAL term so typing stays instant; the store (and its refetch) is
// touched only on submit. The clear (X) resets and refetches immediately.
const term = ref(sources.q || '')
const oneChar = computed(() => term.value.trim().length === 1)

function submitQuery() {
  sources.setQuery(term.value)
}
function clearQuery() {
  term.value = ''
  sources.setQuery('')
}
// Switching dataset resets the store's search: mirror it into the local term.
watch(() => sources.activeSourceId, () => {
  term.value = sources.q || ''
})
// The store's `q` can also change AFTER init - a view-memory restore sets it
// asynchronously once meta has loaded, long after `term` was seeded with ''. Mirror
// `sources.q` back into the local box so a restored search term is visible (and its
// clear (X) reachable). Guarded on inequality so a normal keystroke -> setQuery
// round-trip (which lands `q === term`) never fights typing or the debounce.
watch(() => sources.q, (q) => {
  const next = q || ''
  if (next !== term.value) term.value = next
})
</script>

<template>
  <div class="src-explorer">
    <!-- Dataset selector - only when the agent exposes more than one source AND the
         explorer is not embedded (the unified Evidence selector drives it there). -->
    <!-- ONE top line (user ask 2026-10-20): the dataset dropdown, the search, then the
         filter chips. The search fills what the chips leave and shrinks as they arrive,
         down to its floor; past it the chips block wraps to the next line. The
         `dataset` slot lets an EMBEDDED host (Evidence) put ITS OWN selector in the
         exact same spot, so both hosts keep an identical layout. -->
    <div class="src-topbar">
      <slot name="dataset">
        <DatasetPick
          v-if="hasTabs && !embedded"
          :options="datasetOptions"
          :value="activeKey"
          :disabled="sources.loading"
          @change="onDatasetChange"
        />
      </slot>

      <!-- Global search over the whole dataset - fires on Enter or the search button.
           The placeholder NAMES the dataset it searches. -->
      <div class="src-search">
        <Icon name="search" class="src-search-ico" />
        <input
          v-model="term"
          type="text"
          class="src-search-input"
          maxlength="200"
          :placeholder="searchPlaceholder"
          :disabled="sources.loading || !!sources.error || sources.activeSourceId == null"
          @keydown.enter.prevent="submitQuery"
        />
        <button v-if="term" type="button" class="src-search-clear" :title="t('x.close')" @click="clearQuery">
          <Icon name="x" />
        </button>
        <button
          type="button"
          class="src-search-go"
          :aria-label="t('src.search.go')"
          :title="t('src.search.go')"
          :disabled="sources.loading || !!sources.error || sources.activeSourceId == null"
          @click="submitQuery"
        >
          <Icon name="search" />
        </button>
      </div>

      <!-- View switch - EMBEDDED host only, riding the SAME top row (the Evidence
           "Source data" tab has no panel header to carry it; the docked SourcePanel
           hoists the switch into its own header instead). Plain toggle buttons
           (aria-pressed) whose titles carry the one-line view hints. -->
      <div v-if="embedded && !sources.loading && !sources.error" class="src-viewseg">
        <button
          type="button"
          class="src-viewseg-btn"
          :class="{ active: !sources.analyzeOpen }"
          :aria-pressed="!sources.analyzeOpen"
          :title="t('src.view.hint.data')"
          @click="sources.setAnalyzeOpen(false)"
        ><Icon name="grid" />{{ t('src.view.data') }}</button>
        <button
          type="button"
          class="src-viewseg-btn"
          :class="{ active: sources.analyzeOpen }"
          :aria-pressed="sources.analyzeOpen"
          :title="t('src.view.hint.analyze')"
          @click="sources.setAnalyzeOpen(true)"
        ><Icon name="chart" />{{ t('src.view.analyze') }}</button>
      </div>

      <!-- The filters, shared context of BOTH views, on the same line (no label: the
           [+ Add a filter] control names itself). Outside the loading / error states,
           like the surfaces below. -->
      <SourceChips v-if="!sources.loading && !sources.error" />
    </div>
    <div v-if="oneChar" class="src-search-hint">{{ t('src.search.min') }}</div>

    <!-- States: meta loading / meta error / content. -->
    <div v-if="sources.loading" class="src-skeleton" :aria-label="t('src.loading')">
      <span class="sk sk-band" />
      <div class="sk sk-table" />
    </div>
    <div v-else-if="sources.error" class="src-state error">
      <span>{{ t('src.error') }}</span>
      <button type="button" @click="sources.reload()">{{ t('src.retry') }}</button>
    </div>
    <template v-else>
      <SourceTable v-if="!sources.analyzeOpen" />
      <!-- The Analyze workspace: measures + optional grouping, its result, and the rows
           behind it. Both explorer hosts drive the SOURCES store; the Evidence
           "Source data" legacy surface hosts the SAME workspace on its own store. -->
      <SourceWorkspace v-else />
    </template>
  </div>
</template>

<style scoped>
.src-explorer { display: flex; flex-direction: column; gap: var(--s-4); min-height: 0; }

/* Top line: dataset dropdown (shared DatasetPick) + search + filter chips. Wrapping is
   decided on the search's FLOOR (its basis), so the chips stay beside it until the
   search would drop under 220px, then wrap below as one block (SourceChips). */
.src-topbar { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2) var(--s-3); }

/* Data / Analyze segmented control (embedded host, rides the top row) - a 1px-bordered
   row; the active segment fills with ink (charter recipe). Rounded, flat, and the SAME
   40px height as the search beside it (user ask 2026-08-13). */
.src-viewseg {
  display: inline-flex; align-items: stretch; align-self: center; flex: none;
  height: 40px; box-sizing: border-box;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill); overflow: hidden;
}
.src-viewseg-btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 0 16px; font-size: var(--fs-xs); color: var(--text-2);
  background: var(--bg); transition: all var(--dur) var(--ease);
}
.src-viewseg-btn :deep(.ui-icon) { width: 13px; height: 13px; transition: transform var(--dur) var(--ease); }
.src-viewseg-btn + .src-viewseg-btn { border-left: 1px solid var(--border-strong); }
.src-viewseg-btn:hover:not(.active) { background: var(--surface-hover); color: var(--text); }
.src-viewseg-btn:hover:not(.active) :deep(.ui-icon) { transform: scale(1.1); }
.src-viewseg-btn.active { background: var(--text); color: var(--bg); font-weight: var(--fw-medium); }

@media (prefers-reduced-motion: reduce) {
  .src-viewseg-btn, .src-viewseg-btn :deep(.ui-icon) { transition: none; }
  .src-viewseg-btn:hover:not(.active) :deep(.ui-icon) { transform: none; }
}

/* Search box - quiet border that wakes up on focus (premium 2026-08-13). Rides the top
   line and claims the width the chips leave; its basis IS its floor (220px): the line
   breaks before the search would go narrower, the chips wrapping under it instead.
   Same fixed 40px height as every top-row control (user ask 2026-08-13). */
.src-search {
  display: flex; align-items: center; gap: var(--s-2);
  flex: 1 1 220px; min-width: 220px; max-width: 100%;
  height: 40px; box-sizing: border-box;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill);
  background: var(--bg); padding: 0 10px;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.src-search:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }
.src-search-ico { color: var(--text-3); flex: none; width: 15px; height: 15px; }
.src-search-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  padding: 0 4px; color: var(--text); font-size: var(--fs-sm);
}
.src-search-input:focus { outline: none; }
.src-search-clear {
  flex: none; padding: 4px; border-radius: var(--r-pill); color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.src-search-clear:hover { color: var(--text); background: var(--surface-hover); }
.src-search-clear :deep(.ui-icon) { width: 13px; height: 13px; }
/* Explicit search trigger (search fires only on Enter or this button). */
.src-search-go {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  padding: 5px 8px; margin-left: 2px; border-left: 1px solid var(--border);
  color: var(--text-2); transition: all var(--dur) var(--ease);
}
.src-search-go:hover:not(:disabled) { color: var(--orange); background: var(--surface-hover); }
.src-search-go:disabled { opacity: 0.5; cursor: not-allowed; }
.src-search-go :deep(.ui-icon) { width: 15px; height: 15px; }
.src-search-hint { font-size: var(--fs-xs); color: var(--text-3); margin-top: calc(-1 * var(--s-2)); }

/* Meta-loading skeleton - flat surface blocks with an opacity pulse (no gradient). */
.src-skeleton { display: flex; flex-direction: column; gap: var(--s-4); }
.sk { display: block; border-radius: 0; background: var(--surface-2); animation: src-pulse 1.4s ease-in-out infinite; }
.sk-band { width: 55%; height: 26px; }
.sk-table { height: 240px; }
@keyframes src-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }

.src-state { color: var(--text-3); font-size: var(--fs-sm); display: flex; align-items: center; gap: var(--s-3); }
.src-state.error { color: var(--danger); }
.src-state button {
  padding: 2px 10px; border-radius: var(--r-pill); color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.src-state button:hover { background: var(--surface-hover); color: var(--text); }
</style>
