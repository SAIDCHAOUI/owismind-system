<script setup>
// Result section - the rows the agent's SQL returned: a sober bounded table + the row
// count, with a per-row drill chevron when (and only when) the backend certified the
// drill-down reliable. The agents keep only a short excerpt of each result, so when
// that excerpt may hide rows the FULL result is paged in from the backend
// (useResultRows: 100 rows, then more on scroll) and the count says "N of T rows" -
// a user must never take an excerpt for the whole answer. When nothing was captured,
// ONE honest line says so (no re-execution is shown as "what the agent saw").
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { inferNumericColumns, formatCell } from '../../composables/cellFormat.js'
import { formatStatNumber } from '../../composables/sourceModel.js'
import { resultCountLabel } from '../../composables/resultRows.js'
import { useResultRows } from '../../composables/useResultRows.js'
import { Icon } from '../ui'

const { t, locale } = useI18n()
const evidence = useEvidenceStore()

const meta = computed(() => evidence.meta)
const result = computed(() => (meta.value && meta.value.result) || null)
const captured = computed(() => !!(result.value && result.value.captured))
// Gate on the NEW contract fields only: a v1 meta (neither result nor queries)
// renders nothing, keeping the panel identical to today.
const show = computed(
  () => !!(result.value || (meta.value && Array.isArray(meta.value.queries))),
)

const { rows, columns, total, live, hasMore, loading, partial, loadMore } = useResultRows(() => ({
  exchangeId: evidence.exchangeId ? String(evidence.exchangeId) : '',
  sqlId: '',
  result: result.value,
}))

// Per-row drill is offered ONLY when the backend certified it available and every
// drill column maps onto a column on screen (drill keys carry SOURCE column names - a
// CTE rename makes them unmappable here, so the affordance is honestly withheld). The
// drill reads the clicked row ITSELF (captured or full-result window), never an index.
const drillable = computed(() => {
  const d = meta.value && meta.value.drilldown
  if (!(captured.value && d && d.available && Array.isArray(d.columns) && d.columns.length)) {
    return false
  }
  const shown = columns.value.map((c) => String(c).toLowerCase())
  return d.columns.every((c) => shown.includes(String(c).toLowerCase()))
})

// Count line: never a total we do not know (resultRows.resultCountLabel).
const countLine = computed(() => {
  const rc = result.value && result.value.row_count
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

// Not-captured case: the CONTRACT field first - result.row_count is the ACTIVE
// item's count, set by the backend (the item this panel proves). The queries[]
// scan stays only as a fallback for a meta without a result block; it would
// otherwise diverge from the active item (CONTRACT-02: a trailing failed query
// could lend its count to the proof section).
const missingRowCount = computed(() => {
  const rc = result.value && result.value.row_count
  if (typeof rc === 'number' && Number.isFinite(rc) && rc >= 0) return rc
  if (result.value) return null // a result block exists: never second-guess it
  const qs = meta.value && meta.value.queries
  if (!Array.isArray(qs)) return null
  for (let i = qs.length - 1; i >= 0; i--) {
    const q = qs[i]
    if (q && q.matched && typeof q.row_count === 'number' && q.row_count >= 0) return q.row_count
  }
  return null
})

// Per-column numeric-ness (inferred from the shown values): numeric columns
// right-align and locale-format.
const numericCols = computed(() => inferNumericColumns(columns.value, rows.value))

function cell(v, j) {
  return formatCell(v, numericCols.value[j], locale.value)
}

// Trust layer: the EXACT DB value stays reachable on hover of a formatted cell
// (this is a proof surface - the display rounds to 2 decimals, the title never).
function rawTitle(v, j) {
  return numericCols.value[j] && v != null ? String(v) : null
}

function drillRow(row) {
  if (!drillable.value) return
  const fn = evidence.drillIntoResultRow
  if (typeof fn === 'function') fn(row, columns.value)
}

// Infinite scroll (same pattern as the Source Data table): a sentinel below the last
// row, observed inside the section's OWN scroll box, asks for the next window.
const scrollEl = ref(null)
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
    { root: scrollEl.value, rootMargin: '120px 0px', threshold: 0 },
  )
  observer.observe(el)
})
onBeforeUnmount(teardownObserver)
</script>

<template>
  <section v-if="show" class="ev-result">
    <span class="ev-sec-title">{{ t('ev.proof.result') }}</span>

    <template v-if="captured">
      <div class="ev-result-box">
        <div ref="scrollEl" class="ev-result-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="(c, j) in columns" :key="j" :class="{ num: numericCols[j] }">{{ c }}</th>
                <th v-if="drillable" class="th-drill" aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              <!-- Cells indexed by COLUMN so a short row cannot shift the grid. -->
              <tr v-for="(row, i) in rows" :key="i">
                <td v-for="(c, j) in columns" :key="j" :class="{ num: numericCols[j] }" :title="rawTitle(row[j], j)">{{ cell(row[j], j) }}</td>
                <td v-if="drillable" class="td-drill">
                  <button type="button" class="drill-btn" :title="t('ev.proof.result.drill')"
                          @click="drillRow(row)">
                    <Icon name="chevronRight" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
          <!-- Infinite-scroll sentinel: present only while the full result has more. -->
          <div v-if="live && hasMore" ref="sentinelEl" class="ev-result-sentinel" aria-hidden="true">
            <span v-if="loading">{{ t('ev.table.loadingMore') }}</span>
          </div>
        </div>
      </div>
      <div class="ev-result-info">
        <span v-if="loading && !live">{{ t('ev.table.loadingMore') }}</span>
        <span v-else :class="{ trunc: partial }">{{ countLine }}</span>
        <span v-if="live && hasMore">{{ t('ev.table.more') }}</span>
      </div>
    </template>

    <!-- Honest one-liner: nothing was captured, we do not pretend otherwise. -->
    <div v-else class="ev-result-missing">
      <span>{{ t('ev.proof.result.missing') }}</span>
      <span v-if="missingRowCount != null">{{ t('ev.proof.result.rows', [formatStatNumber(missingRowCount, locale)]) }}</span>
    </div>
  </section>
</template>

<style scoped>
/* No z-index ≥ 5 anywhere here: the chips popover (z-index 5, L043) must stay
   above; the sticky header below uses z-index 1 inside its own scroll box. */
.ev-result { display: flex; flex-direction: column; gap: var(--s-2); }
/* Section label - charte micro-label (same pattern as .ev-chips-title). */
.ev-sec-title {
  font-size: 11px; color: var(--text-2); font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: 0.08em;
}
.ev-result-box { border: 1px solid var(--border-strong); border-radius: 0; overflow: hidden; }
/* Bounded viewport: ~240px max, the rows scroll inside (more load on scroll). */
.ev-result-scroll { max-height: 240px; overflow-y: auto; }
/* separate + spacing 0 (same trick as EvidenceTable): with `collapse` the th
   border scrolls away from a sticky header - paint it as an inset shadow. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
/* Charte header band: uppercase micro-labels above a VISIBLE rule. */
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  padding: 7px 12px; text-align: left; box-shadow: inset 0 -1px 0 var(--border-strong);
  color: var(--text-2); font-size: 11px; font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: 0.08em;
  white-space: nowrap; user-select: none;
}
tbody td {
  padding: 5px 12px; border-bottom: 1px solid var(--border);
  color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 260px;
}
tbody tr:last-child td { border-bottom: none; }
/* Row hover: local feedback while scanning the proof rows (guide: every
   interactive surface answers the pointer). */
tbody td { transition: background var(--dur) var(--ease); }
tbody tr:hover td { background: var(--surface-hover); }
/* The drill chevron only exists on the hovered row until then: a per-row action must
   not turn a 10-row proof table into a column of chevrons. It stays visible on focus
   (keyboard) and while the row is hovered. */
tbody .drill-btn { opacity: 0; }
tbody tr:hover .drill-btn, tbody .drill-btn:focus-visible { opacity: 1; }
/* Numeric columns: right-aligned, tabular digits (values locale-formatted). */
th.num { text-align: right; }
td.num { text-align: right; font-variant-numeric: tabular-nums; }
.th-drill, .td-drill { width: 28px; padding: 0 4px; }
.drill-btn {
  display: inline-flex; align-items: center; justify-content: center;
  padding: 4px; border-radius: var(--r-pill); color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.drill-btn:hover { background: var(--surface-2); color: var(--orange); }
.drill-btn :deep(.ui-icon) { width: 13px; height: 13px; transition: transform var(--dur) var(--ease); }
/* The chevron nudges toward the rows it will open. */
.drill-btn:hover :deep(.ui-icon) { transform: translateX(1px); }
@media (prefers-reduced-motion: reduce) {
  tbody td, .drill-btn, .drill-btn :deep(.ui-icon) { transition: none; }
  .drill-btn:hover :deep(.ui-icon) { transform: none; }
}
.ev-result-info { display: flex; align-items: center; gap: var(--s-3); font-size: var(--fs-xs); color: var(--text-3); }
/* Truncation is a caveat on the proof - small orange text (AA token, F2). */
.ev-result-info .trunc { color: var(--orange-text); }
/* Infinite-scroll sentinel: a thin band below the rows (Source Data pattern). */
.ev-result-sentinel {
  display: flex; align-items: center; justify-content: center;
  min-height: 24px; padding: 4px; font-size: 11px; color: var(--text-3);
}
.ev-result-missing {
  display: flex; flex-direction: column; gap: var(--s-1);
  font-size: var(--fs-sm); color: var(--text-3);
}
</style>
