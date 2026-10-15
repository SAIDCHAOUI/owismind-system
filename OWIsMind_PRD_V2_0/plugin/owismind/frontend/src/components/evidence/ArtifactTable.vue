<script setup>
// ArtifactTable.vue - the agent's result table for the Evidence Studio Table tab.
// Shows the result the agent's SQL returned. The agents only keep a short excerpt of it,
// so when that excerpt may hide rows the FULL result is paged in from the backend
// (useResultRows): a first window of 100 rows, then more on scroll, with an honest
// "Showing N of T rows" count. A complete small result is shown as captured (no request).
// Cell styling deliberately mirrors EvidenceResult.vue's conventions.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { inferNumericColumns, formatCell } from '../../composables/cellFormat.js'
import { formatStatNumber } from '../../composables/sourceModel.js'
import { resultCountLabel } from '../../composables/resultRows.js'
import { useResultRows } from '../../composables/useResultRows.js'
import { useScrollHints } from '../../composables/useScrollHints.js'
import ScrollHints from '../sources/ScrollHints.vue'

const { t, locale } = useI18n()

const props = defineProps({
  // meta.result: { captured, columns, rows, row_count, truncated }
  result: { type: Object, default: null },
  // Exchange + optional artifact sql_id: which stored query the full result re-reads.
  exchangeId: { type: String, default: '' },
  sqlId: { type: String, default: '' },
  // Agent-provided title (what the table IS), shown as the header line.
  title: { type: String, default: '' },
  // Agent-provided one-sentence caption (what the table shows), above it.
  description: { type: String, default: '' },
})

const captured = computed(() => !!(props.result && props.result.captured))
const { rows, columns, total, live, hasMore, loading, partial, loadMore } = useResultRows(() => ({
  exchangeId: props.exchangeId,
  sqlId: props.sqlId,
  result: props.result,
}))

// Count line: never a total we do not know (resultRows.resultCountLabel).
const countLine = computed(() => {
  const rc = props.result && props.result.row_count
  const known = live.value ? total.value : (typeof rc === 'number' ? rc : null)
  const label = resultCountLabel({
    shown: rows.value.length,
    total: known,
    live: live.value,
    hasMore: hasMore.value,
    partial: partial.value,
  })
  return t(label.key, label.args.map((n) => formatStatNumber(n, locale.value)))
})

// Per-column numeric-ness (inferred from the shown values): numeric columns are
// right-aligned with tabular digits and locale-formatted for human reading.
const numericCols = computed(() => inferNumericColumns(columns.value, rows.value))

function cell(row, j) {
  const v = Array.isArray(row) ? row[j] : undefined
  return formatCell(v, numericCols.value[j], locale.value)
}

// Trust layer: the EXACT DB value stays reachable on hover of a formatted cell
// (this is a proof surface - the display rounds to 2 decimals, the title never).
function rawTitle(row, j) {
  const v = Array.isArray(row) ? row[j] : undefined
  return numericCols.value[j] && v != null ? String(v) : null
}

// Scroll affordances: a captured result is often wider and longer than its viewport, and
// nothing else on this proof surface says so.
const scrollEl = ref(null)
const { canLeft, canRight, canDown, hiddenRight, stepLeft, stepRight, stepDown } =
  useScrollHints(scrollEl)

// Infinite scroll (same pattern as the Source Data table): a sentinel below the last row,
// observed inside the table's OWN scroll box, asks for the next window.
const sentinelEl = ref(null)
let observer = null
function teardownObserver() {
  if (observer) {
    observer.disconnect()
    observer = null
  }
}
watch(sentinelEl, (el) => {
  teardownObserver()
  if (!el || !scrollEl.value || typeof IntersectionObserver !== 'function') return
  observer = new IntersectionObserver(
    (entries) => {
      if (entries.some((e) => e.isIntersecting)) loadMore()
    },
    { root: scrollEl.value, rootMargin: '200px 0px', threshold: 0 },
  )
  observer.observe(el)
})
onBeforeUnmount(teardownObserver)
</script>

<template>
  <div class="art-table">
    <!-- Not captured: honest empty state (we never pretend to have data we don't). -->
    <div v-if="!captured" class="art-empty">
      <span>{{ t('art.table.empty') }}</span>
    </div>

    <template v-else>
      <!-- Header: what the table is + what it shows, BEFORE the data (context first). -->
      <div v-if="title || description" class="art-table-head">
        <span v-if="title" class="art-table-title">{{ title }}</span>
        <p v-if="description" class="art-desc">{{ description }}</p>
      </div>
      <div class="art-table-box">
        <div ref="scrollEl" class="art-table-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="(col, j) in columns" :key="j" :class="{ num: numericCols[j] }">{{ col }}</th>
              </tr>
            </thead>
            <tbody>
              <!-- Cells indexed by column so a short row never shifts the grid -->
              <tr v-for="(row, i) in rows" :key="i">
                <td v-for="(col, j) in columns" :key="j" :class="{ num: numericCols[j] }" :title="rawTitle(row, j)">{{ cell(row, j) }}</td>
              </tr>
              <!-- Empty rows guard -->
              <tr v-if="rows.length === 0">
                <td :colspan="columns.length || 1" class="art-table-none">{{ t('art.table.empty') }}</td>
              </tr>
            </tbody>
          </table>
          <!-- Infinite-scroll sentinel: present only while the full result has more. -->
          <div v-if="live && hasMore" ref="sentinelEl" class="art-sentinel" aria-hidden="true">
            <span v-if="loading">{{ t('ev.table.loadingMore') }}</span>
          </div>
        </div>
        <ScrollHints
          :can-left="canLeft"
          :can-right="canRight"
          :can-down="canDown"
          :hidden-right="hiddenRight"
          @left="stepLeft"
          @right="stepRight"
          @down="stepDown"
        />
      </div>

      <!-- Context line: how many rows are on screen OUT OF how many the answer has
           (rows AND columns), plus the scroll hint while more rows remain. -->
      <div class="art-table-info">
        <span v-if="loading && !live">{{ t('ev.table.loadingMore') }}</span>
        <span v-else :class="{ 'art-trunc': partial }">{{ countLine }}</span>
        <span aria-hidden="true">·</span>
        <span>{{ t('art.table.cols', [columns.length]) }}</span>
        <span v-if="live && hasMore">{{ t('ev.table.more') }}</span>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* No z-index ≥ 5: chips popover (z-index 5, L043) must stay above. */
.art-table {
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
  min-height: 0;
}
/* Header block above the data: title first (level-2 emphasis), caption under. */
.art-table-head {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.art-table-title {
  font-size: var(--fs-md);
  font-weight: var(--fw-bold);
  color: var(--text);
  line-height: 1.35;
}
/* Agent-provided caption: what the table shows (scope, period, scenario). */
.art-desc {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
}

/* Scrollable viewport - taller than EvidenceResult's mini-table since this IS
   the data browser tab, not a secondary proof section. Square, visible frame. */
/* position: relative anchors the scroll-affordance overlay on the data viewport. */
.art-table-box {
  position: relative;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  overflow: hidden;
}
.art-table-scroll {
  max-height: 480px;
  overflow-y: auto;
  overflow-x: auto;
}

/* Replicates EvidenceResult.vue cell styling exactly */
table {
  width: 100%;
  border-collapse: separate;
  border-spacing: 0;
  font-size: var(--fs-sm);
}
/* Charte table header: uppercase micro-labels over a VISIBLE rule - the header
   reads as a scannable band, clearly distinct from the data rows. */
thead th {
  position: sticky;
  top: 0;
  z-index: 1;
  background: var(--surface);
  padding: 8px 12px;
  text-align: left;
  box-shadow: inset 0 -1px 0 var(--border-strong);
  color: var(--text-2);
  font-size: 11px;
  font-weight: var(--fw-heavy);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  white-space: nowrap;
  user-select: none;
}
tbody td {
  padding: 5px 12px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  max-width: 320px;
}
tbody tr:last-child td { border-bottom: none; }
/* Row hover: scanning the captured result, the whole line lights up so the eye keeps
   its place across a wide table. */
tbody td { transition: background var(--dur) var(--ease); }
tbody tr:hover td { background: var(--surface-hover); }
@media (prefers-reduced-motion: reduce) { tbody td { transition: none; } }
/* Numeric columns: right-aligned, tabular digits - magnitudes line up and read
   at a glance (the values themselves are locale-formatted by formatCell). */
th.num { text-align: right; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }

.art-table-none {
  color: var(--text-3);
  text-align: center;
  padding: var(--s-5) !important;
}

/* Infinite-scroll sentinel: a thin band below the rows (Source Data pattern). */
.art-sentinel {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 24px;
  padding: 4px;
  font-size: 11px;
  color: var(--text-3);
}

.art-table-info {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  font-size: var(--fs-xs);
  color: var(--text-3);
}
/* Truncation = caveat on proof - orange text (AA token) matching EvidenceResult.vue */
.art-trunc { color: var(--orange-text); }

/* Empty state when result was not captured */
.art-empty {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--s-8) var(--s-4);
  font-size: var(--fs-sm);
  color: var(--text-3);
  border: 1px dashed var(--border);
  border-radius: 0;
  text-align: center;
}
</style>
