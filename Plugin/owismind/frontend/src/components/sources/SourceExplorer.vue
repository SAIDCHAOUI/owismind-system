<script setup>
// Source Data Explorer body - store-driven. Renders (top to bottom): a dataset
// selector (one chip per configured source, hidden when there is a single one or the
// explorer is embedded), an Enter/button global search, the user filter chips, and
// the rows table. Used in the standalone SourcePanel (the pre-conversation empty
// screen) and, with `embedded`, inside the Evidence "Source data" tab; it feeds the
// sources store, so the host only has to ensureAgent() first.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { Icon } from '../ui'
import SourceChips from './SourceChips.vue'
import SourceTable from './SourceTable.vue'
import SourceAnalyze from './SourceAnalyze.vue'
import SourceCalc from './SourceCalc.vue'

// `embedded` hides the internal dataset selector: hosted inside the Evidence
// "Source data" tab, the unified selector there drives the dataset choice.
defineProps({ embedded: { type: Boolean, default: false } })

const { t } = useI18n()
const sources = useSourcesStore()

const activeSourceId = computed(() => sources.activeSourceId)
const hasTabs = computed(() => sources.sourceList.length > 1)

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
    <div v-if="hasTabs && !embedded" class="src-datasets">
      <span class="src-datasets-label">{{ t('src.dataset_label') }}</span>
      <button
        v-for="s in sources.sourceList"
        :key="s.id"
        type="button"
        class="src-dataset"
        :class="{ active: s.id === activeSourceId }"
        :disabled="sources.loading"
        @click="sources.setSource(s.id)"
      >
        {{ s.label }}
      </button>
    </div>

    <!-- Top area: the global search + the Data|Analyze switch sit on the LEFT, the
         Calculate zone fills the empty RIGHT side. A flex row that wraps to a stacked
         block on narrow widths (the explorer is also used in a 480px side panel). -->
    <div class="src-top">
      <div class="src-top-main">
        <!-- Global search over the whole dataset - fires on Enter or the search button. -->
        <div class="src-search">
          <Icon name="search" class="src-search-ico" />
          <input
            v-model="term"
            type="text"
            class="src-search-input"
            maxlength="200"
            :placeholder="t('src.search.placeholder')"
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
        <div v-if="oneChar" class="src-search-hint">{{ t('src.search.min') }}</div>

        <!-- Data / Analyze view switch (segmented control). The filter chips are shared
             context and stay visible in BOTH views; only the surface below swaps. Plain
             toggle buttons (aria-pressed), NOT the ARIA tab pattern: tabs would promise
             tabpanel wiring + arrow-key navigation this simple switch does not have. Shown
             only once the dataset is loaded (same gate as the content below). -->
        <div v-if="!sources.loading && !sources.error" class="src-viewseg">
          <button
            type="button"
            class="src-viewseg-btn"
            :class="{ active: !sources.analyzeOpen }"
            :aria-pressed="!sources.analyzeOpen"
            @click="sources.setAnalyzeOpen(false)"
          >{{ t('src.view.data') }}</button>
          <button
            type="button"
            class="src-viewseg-btn"
            :class="{ active: sources.analyzeOpen }"
            :aria-pressed="sources.analyzeOpen"
            @click="sources.setAnalyzeOpen(true)"
          >{{ t('src.view.analyze') }}</button>
        </div>
      </div>
      <!-- Calculate zone (pick a column, see its key figures). Rendered once columns load. -->
      <SourceCalc v-if="!sources.loading && !sources.error" class="src-top-calc" />
    </div>

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
      <SourceChips />
      <SourceTable v-if="!sources.analyzeOpen" />
      <SourceAnalyze v-else />
    </template>
  </div>
</template>

<style scoped>
.src-explorer { display: flex; flex-direction: column; gap: var(--s-4); min-height: 0; }

/* Dataset selector - flat square chips, orange only on the active one. */
.src-datasets { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2); }
.src-datasets-label {
  font-size: 11px; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.src-dataset {
  padding: 3px 10px; border: 1px solid var(--border); border-radius: 0;
  font-size: var(--fs-xs); color: var(--text-2); background: var(--surface);
  transition: all var(--dur) var(--ease);
}
.src-dataset:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.src-dataset:disabled { opacity: 0.5; cursor: not-allowed; }
.src-dataset.active { border-color: var(--orange); color: var(--orange-text); background: var(--orange-soft); }
:global(body[data-theme="dark"] .src-dataset.active) { background: var(--orange-soft-dark); }

/* Top area - the search + view switch on the left, the Calculate zone on the right. A
   flex row that wraps to a stacked block on narrow widths (a 480px side panel). */
.src-top { display: flex; flex-wrap: wrap; align-items: flex-start; gap: var(--s-4) var(--s-5); }
.src-top-main { flex: 1 1 260px; min-width: 0; display: flex; flex-direction: column; gap: var(--s-3); }
.src-top-calc { flex: 1 1 240px; min-width: 0; }

/* Data / Analyze segmented control - a 1px-bordered row; the active segment fills with
   ink (charter recipe). Square, flat, self-sized (does not stretch full width). */
.src-viewseg {
  display: inline-flex; align-self: flex-start;
  border: 1px solid var(--border-strong); border-radius: 0; overflow: hidden;
}
.src-viewseg-btn {
  padding: 5px 16px; font-size: var(--fs-xs); color: var(--text-2);
  background: var(--bg); transition: all var(--dur) var(--ease);
}
.src-viewseg-btn + .src-viewseg-btn { border-left: 1px solid var(--border-strong); }
.src-viewseg-btn:hover:not(.active) { background: var(--surface-hover); color: var(--text); }
.src-viewseg-btn.active { background: var(--text); color: var(--bg); font-weight: var(--fw-medium); }

/* Search box - flat, square, 1px border; the icon and clear button are muted. */
.src-search {
  display: flex; align-items: center; gap: var(--s-2);
  border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--bg); padding: 0 8px;
}
.src-search-ico { color: var(--text-3); flex: none; width: 15px; height: 15px; }
.src-search-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  padding: 8px 4px; color: var(--text); font-size: var(--fs-sm);
}
.src-search-input:focus { outline: none; }
.src-search-clear {
  flex: none; padding: 3px; border-radius: 0; color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.src-search-clear:hover { color: var(--text); }
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
  padding: 2px 10px; border-radius: 0; color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.src-state button:hover { background: var(--surface-hover); color: var(--text); }
</style>
