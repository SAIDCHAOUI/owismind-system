<script setup>
// Evidence rows table — live rows of the matched source table under the agent's
// (or user-modified) filters. Sticky header, click-to-sort, BOTH vertical and
// horizontal scroll, and LAZY / INFINITE loading: the store loads page 0, then
// appends the next page when the bottom sentinel scrolls into view (never the
// whole table at once). When the agent's SQL reads several distinct source
// datasets, a small table selector is shown above the table.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'

const { t } = useI18n()
const evidence = useEvidenceStore()
const columns = computed(() => (evidence.meta && evidence.meta.columns) || [])

// The dataset name the live rows currently re-query: the explicit selection, or
// (default) the first matched source. Drives the selector's active chip.
const activeTable = computed(
  () => evidence.selectedTable || (evidence.sources[0] && evidence.sources[0].dataset) || null,
)

function sortDir(name) {
  const s = evidence.sort
  return s && s.column === name ? s.dir : ''
}
function cell(row, name) {
  const v = row[name]
  return v == null ? '—' : String(v)
}

// ── Infinite scroll ───────────────────────────────────────────────────────────
// An IntersectionObserver watches a sentinel just below the last row inside the
// table's OWN scroll container. When it enters the viewport the store appends
// the next page (bounded by hasMore + MAX_ROWS). The observer's root is the
// scroll container, so it never reacts to the outer panel's scroll.
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
        if (entry.isIntersecting) {
          evidence.loadMoreRows()
        }
      }
    },
    // `rootMargin` pre-fetches one viewport early so the next page is loading
    // before the user reaches the very bottom (smoother infinite scroll).
    { root: scrollEl.value, rootMargin: '200px 0px', threshold: 0 },
  )
  observer.observe(sentinelEl.value)
}

// (Re)bind the observer whenever the sentinel mounts/unmounts (it only exists
// while there are rows AND more to load). watch on the ref handles v-if churn.
watch(sentinelEl, (el) => {
  if (el) setupObserver()
  else teardownObserver()
})
onBeforeUnmount(teardownObserver)
</script>

<template>
  <!-- `busy` (55% dim) only applies to refreshes with REAL rows on screen: the
       first-load skeleton must keep full opacity or its shimmer washes out. -->
  <div class="ev-table" :class="{ busy: evidence.rowsLoading && evidence.rows.length > 0 }">
    <!-- Source-table selector — shown ONLY when the SQL reads several distinct
         datasets. Single-source keeps the v1 layout (no selector). -->
    <div v-if="evidence.hasMultipleSources" class="ev-table-sources">
      <span class="src-label">{{ t('ev.table.source') }}</span>
      <button
        v-for="s in evidence.sources"
        :key="s.dataset"
        type="button"
        class="src-chip"
        :class="{ active: s.dataset === activeTable }"
        :disabled="evidence.rowsLoading"
        @click="evidence.setTable(s.dataset)"
      >
        {{ s.label || s.dataset }}
      </button>
    </div>
    <div ref="scrollEl" class="ev-table-scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.name" :class="{ sorted: sortDir(c.name) }">
              <button type="button" class="th-btn" @click="evidence.setSort(c.name)">
                <span class="th-label">{{ c.name }}</span>
                <span v-if="sortDir(c.name)" class="th-sort">
                  <Icon :name="sortDir(c.name) === 'asc' ? 'chevronUp' : 'chevronDown'" />
                </span>
              </button>
            </th>
          </tr>
        </thead>
        <!-- First load (no rows yet): shimmer skeleton rows instead of a blank area.
             Refreshes with rows on screen keep the lighter `.busy` opacity dim. -->
        <tbody v-if="evidence.rowsLoading && !evidence.rows.length" aria-hidden="true">
          <tr v-for="n in 12" :key="'sk-' + n" class="sk-row">
            <td v-for="c in columns" :key="c.name"><span class="sk-cell" /></td>
          </tr>
        </tbody>
        <tbody v-else>
          <!-- Stable key on the accumulated index: rows only ever APPEND, so an
               index key never re-keys an already-rendered row. -->
          <tr v-for="(row, i) in evidence.rows" :key="i">
            <td v-for="c in columns" :key="c.name">{{ cell(row, c.name) }}</td>
          </tr>
        </tbody>
      </table>
      <!-- Infinite-scroll sentinel: when it enters the scroll viewport the store
           appends the next page. Only present while there ARE rows and the
           server still has more (and the client cap is not hit). -->
      <div
        v-if="evidence.rows.length && evidence.hasMore"
        ref="sentinelEl"
        class="ev-table-sentinel"
        aria-hidden="true"
      >
        <span v-if="evidence.rowsLoading" class="ev-more-spin">{{ t('ev.table.loadingMore') }}</span>
      </div>
      <div v-if="!evidence.rows.length && !evidence.rowsLoading" class="ev-table-empty">
        {{ t('ev.table.empty') }}
      </div>
    </div>
    <!-- Recoverable rows-level error: the chips above stay mounted and usable. -->
    <div v-if="evidence.rowsError" class="ev-table-error">
      <span>{{ t('ev.error') }}</span>
      <button @click="evidence.refreshRows()">{{ t('ev.retry') }}</button>
    </div>
    <!-- Footer: how many rows are loaded, and whether more remain (lazy). -->
    <div class="ev-table-foot">
      <span class="mono page">{{ t('ev.table.loaded', [evidence.rows.length]) }}</span>
      <span v-if="evidence.hasMore" class="more-hint">{{ t('ev.table.more') }}</span>
    </div>
  </div>
</template>

<style scoped>
/* The table OWNS a bounded height so it can never visually collapse to ~2 rows
   when many proof sections stack above it (the "only 2 rows" bug): inside the
   flex `.ev-body` the previous `flex: 1` height could be squeezed to near-zero.
   A fixed max-height container with its own scroll guarantees ~20 rows visible
   and both axes scroll. flex:none keeps it out of the squeeze. */
.ev-table {
  display: flex; flex-direction: column; flex: none;
  border: 1px solid var(--border); border-radius: var(--r-sm); overflow: hidden;
  transition: opacity var(--dur) var(--ease);
}
.ev-table.busy { opacity: 0.55; }
/* Block stale row interactions while loading; the foot buttons are :disabled-gated. */
.ev-table.busy tbody { pointer-events: none; }
/* BOTH axes scroll: vertical for rows (bounded height ≈ ~20 rows), horizontal
   for ALL columns (no column is hidden / elided away). ~60vh, capped so a tall
   viewport does not make the panel one giant table. */
.ev-table-scroll {
  overflow: auto;
  max-height: min(60vh, 480px);
  min-height: 220px; /* ≈ header + ~7 rows even before the first page lands */
}
/* Source-table selector (multi-table SQL) — small chips above the table. */
.ev-table-sources {
  display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2);
  padding: 6px 10px; border-bottom: 1px solid var(--border); background: var(--surface);
}
.src-label {
  font-size: 11px; color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.src-chip {
  padding: 3px 10px; border: 1px solid var(--border); border-radius: var(--r-pill);
  font-size: var(--fs-xs); color: var(--text-2); background: var(--surface);
  transition: all var(--dur) var(--ease);
}
.src-chip:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.src-chip:disabled { opacity: 0.5; cursor: not-allowed; }
.src-chip.active {
  border-color: var(--orange); color: var(--orange-text); background: var(--orange-soft);
}
/* Dark: translucent orange patch for the active chip (full :global selector, F2/L022). */
:global(body[data-theme="dark"] .src-chip.active) { background: var(--orange-soft-dark); }
/* separate + spacing 0: with `collapse`, the th border scrolls away from a
   sticky header — paint the line as an inset shadow so it sticks with it. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  text-align: left; box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2); font-weight: 500; white-space: nowrap;
  user-select: none;
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
/* First-load skeleton rows — gradient sweep, alternating widths for a natural look. */
.sk-cell {
  display: block; height: 12px; border-radius: 4px; width: 70%;
  background: linear-gradient(90deg, var(--surface-2) 25%, var(--surface-hover) 50%, var(--surface-2) 75%);
  background-size: 200% 100%;
  animation: shimmer-sweep 1.4s linear infinite;
}
.sk-row:nth-child(even) .sk-cell { width: 45%; }
@media (prefers-reduced-motion: reduce) {
  .sk-cell { animation: none; }
}
/* Infinite-scroll sentinel — a thin band below the rows that triggers the next
   page when it scrolls into the container's viewport. */
.ev-table-sentinel {
  display: flex; align-items: center; justify-content: center;
  min-height: 24px; padding: 4px;
}
.ev-more-spin { font-size: 11px; color: var(--text-3); }
.ev-table-empty { padding: var(--s-5); color: var(--text-3); font-size: var(--fs-sm); }
.ev-table-error {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 6px 12px; border-top: 1px solid var(--border);
  color: var(--danger); font-size: var(--fs-sm);
}
.ev-table-error button {
  padding: 2px 10px; border-radius: var(--r-sm); color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.ev-table-error button:hover { background: var(--surface-hover); color: var(--text); }
.ev-table-foot {
  display: flex; align-items: center; gap: var(--s-2);
  padding: 6px 12px; border-top: 1px solid var(--border); background: var(--surface);
}
.ev-table-foot .page { font-size: 11px; color: var(--text-3); }
.ev-table-foot .more-hint { font-size: 11px; color: var(--text-3); margin-left: auto; }
</style>
