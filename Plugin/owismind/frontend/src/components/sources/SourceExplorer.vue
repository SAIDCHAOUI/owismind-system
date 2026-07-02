<script setup>
// Source Data Explorer body - store-driven. Renders (top to bottom): a dataset
// selector (one chip per configured source, hidden when there is a single one), a
// debounced global search, the user filter chips, and the rows table. Used inside the
// standalone SourcePanel (the pre-conversation empty-screen surface); it feeds the
// sources store, so the host only has to ensureAgent() first.
import { computed, ref, watch, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { Icon } from '../ui'
import SourceChips from './SourceChips.vue'
import SourceTable from './SourceTable.vue'

const { t } = useI18n()
const sources = useSourcesStore()

const activeSourceId = computed(() => sources.activeSourceId)
const hasTabs = computed(() => sources.sourceList.length > 1)

// Debounced search: the input binds to a LOCAL term so typing is instant; the store
// (and its refetch) is only touched after a short idle or on Enter.
const term = ref(sources.q || '')
const oneChar = computed(() => term.value.trim().length === 1)
let timer = null

function scheduleQuery() {
  if (timer) clearTimeout(timer)
  timer = setTimeout(() => {
    timer = null
    sources.setQuery(term.value)
  }, 350)
}
function flushQuery() {
  if (timer) { clearTimeout(timer); timer = null }
  sources.setQuery(term.value)
}
function clearQuery() {
  if (timer) { clearTimeout(timer); timer = null }
  term.value = ''
  sources.setQuery('')
}
// Switching dataset resets the store's search: mirror it into the local term.
watch(() => sources.activeSourceId, () => {
  if (timer) { clearTimeout(timer); timer = null }
  term.value = sources.q || ''
})
onBeforeUnmount(() => { if (timer) clearTimeout(timer) })
</script>

<template>
  <div class="src-explorer">
    <!-- Dataset selector - only when the agent exposes more than one source. -->
    <div v-if="hasTabs" class="src-datasets">
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

    <!-- Global search over the whole dataset. -->
    <div class="src-search">
      <Icon name="search" class="src-search-ico" />
      <input
        v-model="term"
        type="text"
        class="src-search-input"
        maxlength="200"
        :placeholder="t('src.search.placeholder')"
        :disabled="sources.loading || !!sources.error || sources.activeSourceId == null"
        @input="scheduleQuery"
        @keydown.enter.prevent="flushQuery"
      />
      <button v-if="term" type="button" class="src-search-clear" :title="t('x.close')" @click="clearQuery">
        <Icon name="x" />
      </button>
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
      <SourceChips />
      <SourceTable />
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
