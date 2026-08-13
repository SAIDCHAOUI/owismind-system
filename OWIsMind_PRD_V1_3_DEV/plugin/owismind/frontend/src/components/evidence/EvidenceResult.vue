<script setup>
// Result section - the EXACT rows the agent received (when captured): a sober
// bounded mini-table (no sort, no pagination - this is evidence, not a data
// browser) + the total row count, with a per-row drill chevron when (and only
// when) the backend certified the drill-down reliable. When nothing was
// captured, ONE honest line says so (a re-execution is "now", never "what the
// agent saw" - honesty rules, spec §9).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { resultPreview } from '../../composables/evidenceProof.js'
import { inferNumericColumns, formatCell } from '../../composables/cellFormat.js'
import { formatStatNumber } from '../../composables/sourceModel.js'
import { Icon } from '../ui'

const { t, locale } = useI18n()
const evidence = useEvidenceStore()

const meta = computed(() => evidence.meta)
const result = computed(() => (meta.value && meta.value.result) || null)
const captured = computed(() => !!(result.value && result.value.captured))
const preview = computed(() => resultPreview(result.value))
// Gate on the NEW contract fields only: a v1 meta (neither result nor queries)
// renders nothing, keeping the panel identical to today.
const show = computed(
  () => !!(result.value || (meta.value && Array.isArray(meta.value.queries))),
)

// Per-row drill is offered ONLY when the backend certified it available AND
// the rows on screen are the captured ones (drill indexes meta.result.rows).
// Index-integrity guard: resultPreview drops malformed (non-list) rows, which
// would shift preview indexes off meta.result.rows - in that case the drill
// chevrons are withheld rather than risking a drill into the WRONG row.
const drillable = computed(() => {
  const d = meta.value && meta.value.drilldown
  if (!(captured.value && d && d.available && Array.isArray(d.columns) && d.columns.length)) {
    return false
  }
  // Every drill column must map onto a captured-result column, or the click
  // would silently no-op (drill keys carry SOURCE column names - a CTE rename
  // makes them unmappable here, so the affordance is honestly withheld).
  const resultCols = Array.isArray(result.value.columns)
    ? result.value.columns.map((c) => String(c).toLowerCase())
    : []
  if (!d.columns.every((c) => resultCols.includes(String(c).toLowerCase()))) {
    return false
  }
  const total = Array.isArray(result.value.rows) ? result.value.rows.length : 0
  return preview.value.rows.length + preview.value.more === total
})

// Total rows the agent received - prefer the contract's row_count, fall back
// to what the preview can prove (visible rows + hidden remainder).
const totalRows = computed(() => {
  const rc = result.value && result.value.row_count
  if (typeof rc === 'number' && Number.isFinite(rc) && rc >= 0) return rc
  return preview.value.rows.length + preview.value.more
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

// Per-column numeric-ness (inferred from the previewed values; preview columns map
// 1:1 onto result.columns): numeric columns right-align and locale-format.
const numericCols = computed(() => inferNumericColumns(preview.value.columns, preview.value.rows))

function cell(v, j) {
  return formatCell(v, numericCols.value[j], locale.value)
}

// Trust layer: the EXACT DB value stays reachable on hover of a formatted cell
// (this is a proof surface - the display rounds to 2 decimals, the title never).
function rawTitle(v, j) {
  return numericCols.value[j] && v != null ? String(v) : null
}

// The drill action lands with IMPL-5 (stores/evidence.js): guard so this
// section keeps rendering (chevrons inert) against an older store build.
function drillRow(i) {
  if (!drillable.value) return
  const fn = evidence.drillIntoResultRow
  if (typeof fn === 'function') fn(i)
}
</script>

<template>
  <section v-if="show" class="ev-result">
    <span class="ev-sec-title">{{ t('ev.proof.result') }}</span>

    <template v-if="captured">
      <div class="ev-result-box">
        <div class="ev-result-scroll">
          <table>
            <thead>
              <tr>
                <th v-for="(c, j) in preview.columns" :key="j" :class="{ num: numericCols[j] }">{{ c }}</th>
                <th v-if="drillable" class="th-drill" aria-hidden="true" />
              </tr>
            </thead>
            <tbody>
              <!-- Cells indexed by COLUMN so a short row cannot shift the grid. -->
              <tr v-for="(row, i) in preview.rows" :key="i">
                <td v-for="(c, j) in preview.columns" :key="j" :class="{ num: numericCols[j] }" :title="rawTitle(row[j], j)">{{ cell(row[j], j) }}</td>
                <td v-if="drillable" class="td-drill">
                  <button type="button" class="drill-btn" :title="t('ev.proof.result.drill')"
                          @click="drillRow(i)">
                    <Icon name="chevronRight" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
      <div class="ev-result-info">
        <span>{{ t('ev.proof.result.rows', [formatStatNumber(totalRows, locale)]) }}</span>
        <span v-if="result.truncated" class="trunc">{{ t('ev.proof.result.truncated') }}</span>
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
/* Bounded viewport: ≤ 10 rows rendered, ~240px max before scrolling. */
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
.ev-result-missing {
  display: flex; flex-direction: column; gap: var(--s-1);
  font-size: var(--fs-sm); color: var(--text-3);
}
</style>
