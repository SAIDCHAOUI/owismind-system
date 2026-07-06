<script setup>
// Source Data "Analyze" view - a one-group-by + one-measure mini-pivot over the active
// dataset. Every number is computed by the DATABASE over the FULL filtered set (the
// same search + filters as the Data table), never the visible window.
//
// One code, two hosts: the `surface` prop is the aggregate surface (the Source explorer
// store by DEFAULT, the Evidence store in the Evidence "Source data" tab); both expose the
// SAME analyze API (analyzeGroup / analyzeFn / setAnalyze* / runAnalyze / ...) plus `q` and
// `chips` for the scope recap. The `columns` prop supplies the active [{ name, type }] list.
// This component only renders the form + result table. Charter: square, flat, 1px borders;
// the Excel-like data bar is a NEUTRAL span (no orange).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import {
  isNumericColType,
  isTemporalColType,
  bucketOptionsFor,
  shareOfTotal,
  formatStatNumber,
  formatBucketKey,
  effectiveSourceQuery,
  chipOp,
  betweenValuesToMonthRange,
  sortBucketRowsAsc,
} from '../../composables/sourceModel.js'

const props = defineProps({
  surface: { type: Object, default: null },
  columns: { type: Array, default: null },
})

const { t, locale } = useI18n()
// Default to the Source explorer store (creating it fires NO query); the Evidence host
// passes its own store as `surface`, so useSourcesStore() is skipped entirely there.
const surface = props.surface || useSourcesStore()

const allColumns = computed(() => props.columns || surface.columns || [])
const numericColumns = computed(() => allColumns.value.filter((c) => isNumericColType(c.type)))

// Group-by column + its temporal bucket options (empty for a non-temporal column).
const groupType = computed(() => {
  const c = allColumns.value.find((x) => x.name === surface.analyzeGroup)
  return c ? c.type : ''
})
const groupTemporal = computed(() => isTemporalColType(groupType.value))
const bucketOptions = computed(() => bucketOptionsFor(groupType.value))

// Measure select value encodes fn (+ column): 'count' | 'sum:<col>' | 'avg:<col>'.
const measureValue = computed(() =>
  surface.analyzeFn === 'count' ? 'count' : surface.analyzeFn + ':' + surface.analyzeMeasureColumn,
)
// The % of total column only makes sense for additive measures (count / sum).
const showShare = computed(() => surface.analyzeFn === 'count' || surface.analyzeFn === 'sum')

// Honest recap of the active scope (search + filter chips) so the user always knows the
// pivot is computed on the filtered selection, not the whole dataset. Reads the host's own
// `q` + `chips` (both hosts expose them); a locked agent chip reads via its raw op.
const scopeSummary = computed(() => {
  const parts = []
  const eq = effectiveSourceQuery(surface.q)
  if (eq) parts.push('"' + eq + '"')
  for (const c of surface.chips) {
    // A temporal range chip reads as its month span (same wording as the chip itself),
    // never as the raw internal bounds (the end-of-month microsecond bound is an
    // implementation detail, not something a business user should decode).
    const range = chipOp(c) === 'BETWEEN' ? betweenValuesToMonthRange(c.values) : null
    if (range) parts.push(c.column + ' : ' + t('src.range.chip', [range.from, range.to]))
    else parts.push(c.column + ' ' + c.op + ' ' + c.values.join(', '))
  }
  return parts.join(' · ')
})
const hasScope = computed(() => scopeSummary.value.length > 0)

// The selection is complete once a group is picked and the measure is valid.
const complete = computed(
  () => !!surface.analyzeGroup && (surface.analyzeFn === 'count' || !!surface.analyzeMeasureColumn),
)

// Bucketed results arrive newest-first (the server cap keeps the most recent
// periods); re-sort chronologically for display. Plain groups keep the server's
// by-measure ranking untouched.
const rows = computed(() => {
  const raw = surface.analyzeRows || []
  return groupTemporal.value ? sortBucketRowsAsc(raw) : raw
})
// Longest bar = the largest MAGNITUDE among the visible groups (handles negatives).
const maxAbs = computed(() =>
  rows.value.reduce((m, r) => Math.max(m, Math.abs(Number(r.m0) || 0)), 0),
)
function barWidth(v) {
  const n = Math.abs(Number(v) || 0)
  return maxAbs.value > 0 ? (n / maxAbs.value) * 100 : 0
}
function fmtStat(v) {
  return formatStatNumber(v, locale.value)
}
// The group label: a temporal bucket formats to YYYY-MM / YYYY-Qn / YYYY; any null key
// (a group with no value) shows the honest "(empty)" label.
function groupLabel(row) {
  if (groupTemporal.value) {
    const label = formatBucketKey(row.key, surface.analyzeBucket)
    return label == null ? t('src.an.empty_group') : label
  }
  return row.key == null || row.key === '' ? t('src.an.empty_group') : String(row.key)
}
function sharePct(v) {
  if (!showShare.value) return null
  const totals = surface.analyzeTotals
  return totals ? shareOfTotal(v, totals.m0) : null
}
function fmtShare(v) {
  const p = sharePct(v)
  return p == null ? '' : formatStatNumber(p, locale.value) + '%'
}

function onGroupChange(e) {
  surface.setAnalyzeGroup(e.target.value || null)
}
function onBucketChange(e) {
  surface.setAnalyzeBucket(e.target.value)
}
function onMeasureChange(e) {
  const val = e.target.value
  if (val === 'count') {
    surface.setAnalyzeMeasure('count', null)
    return
  }
  const idx = val.indexOf(':')
  surface.setAnalyzeMeasure(val.slice(0, idx), val.slice(idx + 1))
}
</script>

<template>
  <div class="src-analyze">
    <!-- Form: group-by (+ bucket for a temporal column), then the measure. -->
    <div class="an-form">
      <div class="an-field">
        <label class="an-label">{{ t('src.an.group_by') }}</label>
        <div class="an-controls">
          <select
            class="an-select"
            :aria-label="t('src.an.group_by')"
            :value="surface.analyzeGroup || ''"
            @change="onGroupChange"
          >
            <option value="">{{ t('src.an.choose') }}</option>
            <option v-for="c in allColumns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
          <select
            v-if="groupTemporal"
            class="an-select an-bucket"
            :aria-label="t('src.an.bucket.label')"
            :value="surface.analyzeBucket"
            @change="onBucketChange"
          >
            <option v-for="b in bucketOptions" :key="b" :value="b">{{ t('src.an.bucket.' + b) }}</option>
          </select>
        </div>
      </div>

      <div class="an-field">
        <label class="an-label">{{ t('src.an.calc') }}</label>
        <select class="an-select" :aria-label="t('src.an.calc')" :value="measureValue" @change="onMeasureChange">
          <option value="count">{{ t('src.an.fn.count') }}</option>
          <template v-for="c in numericColumns" :key="c.name">
            <option :value="'sum:' + c.name">{{ t('src.an.fn.sum', [c.name]) }}</option>
            <option :value="'avg:' + c.name">{{ t('src.an.fn.avg', [c.name]) }}</option>
            <option :value="'median:' + c.name">{{ t('src.an.fn.median', [c.name]) }}</option>
          </template>
        </select>
      </div>
    </div>

    <!-- Honest scope recap: the pivot runs on the filtered selection, not the whole set. -->
    <div v-if="hasScope" class="an-scope">{{ t('src.an.scope', [scopeSummary]) }}</div>

    <!-- States: loading / error / incomplete selection / empty result / result table. -->
    <div v-if="surface.analyzeLoading" class="an-skeleton" :aria-label="t('src.loading')">
      <div v-for="n in 6" :key="'sk-' + n" class="an-sk-row">
        <span class="sk sk-a" />
        <span class="sk sk-b" />
      </div>
    </div>
    <div v-else-if="surface.analyzeError" class="an-state error">
      <span>{{ t('src.error') }}</span>
      <button type="button" @click="surface.runAnalyze()">{{ t('src.retry') }}</button>
    </div>
    <div v-else-if="!complete" class="an-state">{{ t('src.an.prompt') }}</div>
    <div v-else-if="!rows.length" class="an-state">{{ t('src.an.no_rows') }}</div>
    <template v-else>
      <div class="an-result">
        <table class="an-table">
          <thead>
            <tr>
              <th class="an-th-group">{{ t('src.an.col_group') }}</th>
              <th class="an-th-value">{{ t('src.an.col_value') }}</th>
              <th v-if="showShare" class="an-th-share">{{ t('src.an.share') }}</th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="(row, i) in rows" :key="i">
              <td class="an-group" :title="groupLabel(row)">{{ groupLabel(row) }}</td>
              <td class="an-value">
                <span class="an-bar" :style="{ width: barWidth(row.m0) + '%' }" aria-hidden="true" />
                <span class="an-val-text mono">{{ fmtStat(row.m0) }}</span>
              </td>
              <td v-if="showShare" class="an-share mono">{{ fmtShare(row.m0) }}</td>
            </tr>
          </tbody>
        </table>
      </div>
      <div v-if="surface.analyzeTruncated" class="an-note">{{ t('src.an.truncated', [50]) }}</div>
    </template>
  </div>
</template>

<style scoped>
.src-analyze { display: flex; flex-direction: column; gap: var(--s-4); min-height: 0; }

/* Form - flat square selects, 1px border, orange border on focus (charter). */
.an-form { display: flex; flex-wrap: wrap; gap: var(--s-5); }
.an-field { display: flex; flex-direction: column; gap: 6px; min-width: 0; }
.an-label {
  font-size: 11px; color: var(--text-2); text-transform: uppercase;
  letter-spacing: 0.1em; font-weight: var(--fw-heavy);
}
.an-controls { display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap; }
.an-select {
  padding: 7px 10px; border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--bg); color: var(--text); font-size: var(--fs-sm);
  min-width: 180px; max-width: 320px;
}
.an-select:focus { outline: none; border-color: var(--orange); }
.an-bucket { min-width: 140px; }

/* Scope recap - discreet, on the filtered selection. */
.an-scope { font-size: var(--fs-xs); color: var(--text-3); }

/* Result table - flat, square. The value cell carries an Excel-like data bar (a neutral
   surface span behind the number, width = value / max of the visible groups). Own scroll
   (the host panels use overflow:hidden and expect internal scrolling). */
.an-result {
  border: 1px solid var(--border); border-radius: 0;
  overflow: auto; max-height: min(60vh, 480px);
}
.an-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
.an-table thead th {
  position: sticky; top: 0; z-index: 1;
  text-align: left; padding: 7px 12px; background: var(--surface);
  box-shadow: inset 0 -1px 0 var(--border-strong);
  font-size: 11px; text-transform: uppercase; letter-spacing: 0.08em;
  color: var(--text-2); font-weight: var(--fw-heavy); white-space: nowrap;
}
.an-th-value, .an-th-share { text-align: right; }
.an-table tbody td { padding: 0; border-bottom: 1px solid var(--border); color: var(--text); }
.an-table tbody tr:last-child td { border-bottom: none; }
.an-group {
  padding: 8px 12px; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
/* The value cell hosts the bar + the number; position:relative anchors the bar. */
.an-value { position: relative; text-align: right; min-width: 120px; }
/* Excel-like data bar: a neutral span growing from the LEFT (magnitude), the exact
   number right-aligned on top. Neutral surface, never orange (charter). */
.an-bar {
  position: absolute; top: 4px; bottom: 4px; left: 0;
  background: var(--surface-2); z-index: 0;
}
.an-val-text { position: relative; z-index: 1; display: block; padding: 8px 12px; font-weight: var(--fw-semibold); }
.an-share { padding: 8px 12px; text-align: right; color: var(--text-2); white-space: nowrap; }

.an-note { font-size: var(--fs-xs); color: var(--text-3); }

/* States - honest, quiet. */
.an-state { color: var(--text-3); font-size: var(--fs-sm); display: flex; align-items: center; gap: var(--s-3); }
.an-state.error { color: var(--danger); }
.an-state button {
  padding: 2px 10px; border-radius: 0; color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.an-state button:hover { background: var(--surface-hover); color: var(--text); }

/* Loading skeleton - flat surface blocks with an opacity pulse (no gradient). */
.an-skeleton { display: flex; flex-direction: column; gap: 6px; }
.an-sk-row { display: flex; gap: var(--s-3); }
.sk { display: block; height: 16px; border-radius: 0; background: var(--surface-2); animation: an-pulse 1.4s ease-in-out infinite; }
.sk-a { flex: 1; }
.sk-b { width: 120px; }
@keyframes an-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
