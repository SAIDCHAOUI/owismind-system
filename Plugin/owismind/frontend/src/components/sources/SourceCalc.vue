<script setup>
// Source Data "Calculate" zone - the business-user surface. Pick ONE column and see its
// key figures as small KPI cards, computed by the DATABASE over the FULL filtered set
// (the same search + filters as the table), never the visible window. The measures shown
// depend on the column TYPE (statsSpecFor): numeric -> sum/average/median/min/max,
// temporal -> min/max, anything else -> distinct count (never a hardcoded column name).
// PERSISTENT: it lives in the empty top-right area while the table stays visible, and it
// follows the current filters (re-computes on every scope change).
//
// One code, two hosts: the `surface` prop is the aggregate surface (the Source explorer
// store by DEFAULT, the Evidence store when mounted in the Evidence "Source data" tab).
// Both expose the SAME aggregate API (calcColumn / calcValues / setCalcColumn / ...). The
// `columns` prop supplies the active [{ name, type }] list (the Source store carries its
// own `columns`; the Evidence host passes meta.columns).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { statsSpecFor, formatStatNumber } from '../../composables/sourceModel.js'

const props = defineProps({
  surface: { type: Object, default: null },
  columns: { type: Array, default: null },
})

const { t, locale } = useI18n()
// Default to the Source explorer store (creating it fires NO query); the Evidence host
// passes its own store as `surface`, so useSourcesStore() is skipped entirely there.
const surface = props.surface || useSourcesStore()

const allColumns = computed(() => props.columns || surface.columns || [])
// The type of the chosen column, then its ordered key-figure spec (empty when no column).
const calcType = computed(() => {
  const c = allColumns.value.find((x) => x.name === surface.calcColumn)
  return c ? c.type : ''
})
const spec = computed(() => (surface.calcColumn ? statsSpecFor(calcType.value) : []))

function fmt(v) {
  return formatStatNumber(v, locale.value)
}
// The DB-computed value for one measure fn ('-' via the formatter when null / absent).
function valueOf(fn) {
  const v = surface.calcValues
  return v && Object.prototype.hasOwnProperty.call(v, fn) ? v[fn] : null
}
function onColumnChange(e) {
  surface.setCalcColumn(e.target.value || null)
}
</script>

<template>
  <div class="src-calc">
    <div class="src-calc-head">
      <span class="src-calc-eyebrow">{{ t('src.calc.title') }}</span>
      <select
        class="src-calc-select"
        :class="{ chosen: !!surface.calcColumn }"
        :aria-label="t('src.calc.title')"
        :value="surface.calcColumn || ''"
        @change="onColumnChange"
      >
        <option value="">{{ t('src.calc.choose') }}</option>
        <option v-for="c in allColumns" :key="c.name" :value="c.name">{{ c.name }}</option>
      </select>
    </div>

    <!-- Figures for the chosen column: KPI cards (skeleton on first load, dimmed on a
         scope refetch, error state reusing the src.error idiom). -->
    <template v-if="surface.calcColumn">
      <div v-if="surface.calcError" class="src-calc-error">
        <span>{{ t('src.error') }}</span>
        <button type="button" @click="surface.reloadCalc()">{{ t('src.retry') }}</button>
      </div>
      <div
        v-else
        class="src-calc-cards"
        :class="{ busy: surface.calcLoading && surface.calcValues }"
      >
        <!-- First load (no values yet): discrete skeleton cards matching the spec. -->
        <template v-if="surface.calcLoading && !surface.calcValues">
          <div v-for="s in spec" :key="'sk-' + s.fn" class="calc-card" aria-hidden="true">
            <span class="calc-card-label">{{ t(s.labelKey) }}</span>
            <span class="calc-card-val sk-val" />
          </div>
        </template>
        <template v-else>
          <div v-for="s in spec" :key="s.fn" class="calc-card">
            <span class="calc-card-label">{{ t(s.labelKey) }}</span>
            <span class="calc-card-val mono">{{ fmt(valueOf(s.fn)) }}</span>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* The Calculate zone - a compact, flat, square block that fills the empty top-right
   area. Header (eyebrow + column select) above a wrapping row of small KPI cards. */
.src-calc { display: flex; flex-direction: column; gap: var(--s-2); min-width: 0; }
.src-calc-head { display: flex; align-items: center; gap: var(--s-2); flex-wrap: wrap; }
.src-calc-eyebrow {
  font-size: 11px; color: var(--text-2); text-transform: uppercase;
  letter-spacing: 0.1em; font-weight: var(--fw-heavy); flex: none;
}
/* Column select - flat square, 1px border, orange border on focus (charter). The active
   column name reads in orange text (the single rare accent, as the old totals bar did). */
.src-calc-select {
  flex: 1; min-width: 160px; max-width: 260px;
  padding: 6px 10px; border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--bg); color: var(--text-2); font-size: var(--fs-sm);
}
.src-calc-select:focus { outline: none; border-color: var(--orange); }
.src-calc-select.chosen { color: var(--orange-text); font-weight: var(--fw-medium); }

/* KPI cards - one small flat square card per measure; they wrap onto the next line and,
   in the 480px side panel, stack cleanly. Dimmed while a scope change refetches. */
.src-calc-cards { display: flex; flex-wrap: wrap; gap: var(--s-2); transition: opacity var(--dur) var(--ease); }
.src-calc-cards.busy { opacity: 0.55; }
.calc-card {
  display: flex; flex-direction: column; gap: 3px;
  min-width: 96px; flex: 1 1 96px; padding: 6px 10px;
  border: 1px solid var(--border); border-radius: 0; background: var(--surface);
}
.calc-card-label {
  font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.calc-card-val {
  font-size: var(--fs-sm); font-weight: var(--fw-semibold); color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Skeleton value - a flat surface block with an opacity pulse (no gradient, charter). */
.sk-val { height: 14px; width: 70%; background: var(--surface-2); animation: calc-pulse 1.4s ease-in-out infinite; }
@keyframes calc-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .sk-val { animation: none; } }

/* Error - honest, quiet, reusing the src.error idiom with a retry. */
.src-calc-error { display: flex; align-items: center; gap: var(--s-3); color: var(--danger); font-size: var(--fs-xs); }
.src-calc-error button {
  padding: 2px 10px; border-radius: 0; color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.src-calc-error button:hover { background: var(--surface-hover); color: var(--text); }
</style>
