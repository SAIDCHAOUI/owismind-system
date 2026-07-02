<script setup>
// Source rows table - live rows of the active source dataset under the current
// search + user filters. Sticky header, click-to-sort, BOTH vertical and horizontal
// scroll, and LAZY / INFINITE loading: the store loads page 0, then appends the next
// page when the bottom sentinel scrolls into view (never the whole table at once).
// Mirrors the Evidence rows table mechanics on the sources store.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { Icon } from '../ui'

const { t } = useI18n()
const sources = useSourcesStore()
const columns = computed(() => sources.columns || [])

function sortDir(name) {
  const s = sources.sort
  return s && s.column === name ? s.dir : ''
}
function cell(row, name) {
  const v = row[name]
  return v == null ? '-' : String(v)
}

// Infinite scroll: an IntersectionObserver watches a sentinel just below the last row
// inside the table's OWN scroll container. Root is the scroll container so it never
// reacts to the outer panel's scroll. `rootMargin` pre-fetches one screen early.
const scrollEl = ref(null)
const sentinelEl = ref(null)
let observer = null

function teardownObserver() {
  if (observer) {
    observer.disconnect()
    observer = null
  }
}
function setupObserver() {
  teardownObserver()
  if (typeof IntersectionObserver !== 'function') return
  if (!scrollEl.value || !sentinelEl.value) return
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) sources.loadMoreRows()
      }
    },
    { root: scrollEl.value, rootMargin: '200px 0px', threshold: 0 },
  )
  observer.observe(sentinelEl.value)
}

// (Re)bind whenever the sentinel mounts/unmounts (it only exists while there are rows
// AND more to load). watch on the ref handles the v-if churn.
watch(sentinelEl, (el) => {
  if (el) setupObserver()
  else teardownObserver()
})
onBeforeUnmount(teardownObserver)
</script>

<template>
  <!-- `busy` (55% dim) only applies to refreshes with REAL rows on screen: the
       first-load skeleton must keep full opacity or its shimmer washes out. -->
  <div class="src-table" :class="{ busy: sources.rowsLoading && sources.rows.length > 0 }">
    <div ref="scrollEl" class="src-table-scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.name" :class="{ sorted: sortDir(c.name) }">
              <button type="button" class="th-btn" @click="sources.setSort(c.name)">
                <span class="th-label">{{ c.name }}</span>
                <span v-if="sortDir(c.name)" class="th-sort">
                  <Icon :name="sortDir(c.name) === 'asc' ? 'chevronUp' : 'chevronDown'" />
                </span>
              </button>
            </th>
          </tr>
        </thead>
        <!-- First load (no rows yet): pulse skeleton rows instead of a blank area.
             Refreshes with rows on screen keep the lighter `.busy` opacity dim. -->
        <tbody v-if="sources.rowsLoading && !sources.rows.length" aria-hidden="true">
          <tr v-for="n in 12" :key="'sk-' + n" class="sk-row">
            <td v-for="c in columns" :key="c.name"><span class="sk-cell" /></td>
          </tr>
        </tbody>
        <tbody v-else>
          <!-- Stable key on the accumulated index: rows only ever APPEND, so an
               index key never re-keys an already-rendered row. -->
          <tr v-for="(row, i) in sources.rows" :key="i">
            <td v-for="c in columns" :key="c.name">{{ cell(row, c.name) }}</td>
          </tr>
        </tbody>
      </table>
      <!-- Infinite-scroll sentinel: present only while there ARE rows and the server
           still has more (and the client cap is not hit). -->
      <div
        v-if="sources.rows.length && sources.hasMore"
        ref="sentinelEl"
        class="src-table-sentinel"
        aria-hidden="true"
      >
        <span v-if="sources.rowsLoading" class="src-more-spin">{{ t('src.loadingMore') }}</span>
      </div>
      <div v-if="!sources.rows.length && !sources.rowsLoading" class="src-table-empty">
        {{ t('src.empty') }}
      </div>
    </div>
    <!-- Recoverable rows-level error: the search + filters above stay usable. -->
    <div v-if="sources.rowsError" class="src-table-error">
      <span>{{ t('src.error') }}</span>
      <button @click="sources.refreshRows()">{{ t('src.retry') }}</button>
    </div>
    <!-- Footer: how many rows are loaded, and whether more remain (lazy). -->
    <div class="src-table-foot">
      <span class="mono page">{{ t('src.loaded', [sources.rows.length]) }}</span>
      <span v-if="sources.hasMore" class="more-hint">{{ t('src.more') }}</span>
    </div>
  </div>
</template>

<style scoped>
/* The table OWNS a bounded height with its own scroll so it can never collapse when
   content stacks above it (flex:none keeps it out of the squeeze). Square geometry. */
.src-table {
  display: flex; flex-direction: column; flex: none;
  border: 1px solid var(--border); border-radius: 0; overflow: hidden;
  transition: opacity var(--dur) var(--ease);
}
.src-table.busy { opacity: 0.55; }
.src-table.busy tbody { pointer-events: none; }
/* BOTH axes scroll: vertical for rows (~20 rows), horizontal for ALL columns. */
.src-table-scroll {
  overflow: auto;
  max-height: min(60vh, 480px);
  min-height: 220px;
}
/* separate + spacing 0: with `collapse`, the th border scrolls away from a sticky
   header - paint the line as an inset shadow so it sticks with it. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  text-align: left; box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2); font-weight: 500; white-space: nowrap; user-select: none;
}
thead th:hover { color: var(--text); }
thead th.sorted { color: var(--orange); }
.th-btn {
  display: flex; align-items: center; gap: 4px; width: 100%;
  padding: 8px 12px; color: inherit; text-align: left; cursor: pointer;
}
.th-sort :deep(.ui-icon) { width: 12px; height: 12px; vertical-align: -2px; }
tbody td {
  padding: 7px 12px; border-bottom: 1px solid var(--border);
  color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 260px;
}
tbody tr:last-child td { border-bottom: none; }
/* First-load skeleton rows - flat surface with an opacity pulse (no gradient). */
.sk-cell {
  display: block; height: 12px; width: 70%; border-radius: 0;
  background: var(--surface-2);
  animation: src-pulse 1.4s ease-in-out infinite;
}
.sk-row:nth-child(even) .sk-cell { width: 45%; }
@keyframes src-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) {
  .sk-cell { animation: none; }
}
.src-table-sentinel {
  display: flex; align-items: center; justify-content: center;
  min-height: 24px; padding: 4px;
}
.src-more-spin { font-size: 11px; color: var(--text-3); }
.src-table-empty { padding: var(--s-5); color: var(--text-3); font-size: var(--fs-sm); }
.src-table-error {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 6px 12px; border-top: 1px solid var(--border);
  color: var(--danger); font-size: var(--fs-sm);
}
.src-table-error button {
  padding: 2px 10px; border-radius: 0; color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.src-table-error button:hover { background: var(--surface-hover); color: var(--text); }
.src-table-foot {
  display: flex; align-items: center; gap: var(--s-2);
  padding: 6px 12px; border-top: 1px solid var(--border); background: var(--surface);
}
.src-table-foot .page { font-size: 11px; color: var(--text-3); }
.src-table-foot .more-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }
</style>
