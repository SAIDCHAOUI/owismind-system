<script setup>
// Source Data "Calculate" zone - the business-user surface. Pick ONE column, then pick
// WHICH of its type-driven measures to display, shown as BIG KPI cards computed by the
// DATABASE over the FULL filtered set (the same search + filters as the table), never the
// visible window. The measures a column CAN show depend on its TYPE (statsSpecFor):
// numeric -> sum/average/median/min/max, temporal -> min/max, anything else -> distinct
// count (never a hardcoded column name). The user chooses a subset (default = the sensible
// starting set) so a column never shows all five figures at once, and a long value is
// shown in full (wrapped, never CSS-clipped) with the exact figure in its tooltip.
// PERSISTENT: it lives in the empty top-right area while the table stays visible, and it
// follows the current filters (re-computes on every scope change).
//
// One code, two hosts: the `surface` prop is the aggregate surface (the Source explorer
// store by DEFAULT, the Evidence store when mounted in the Evidence "Source data" tab).
// Both expose the SAME aggregate API (calcColumn / calcFns / calcValues / setCalcColumn /
// setCalcFns / ...). The `columns` prop supplies the active [{ name, type }] list (the
// Source store carries its own `columns`; the Evidence host passes meta.columns).
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { statsSpecFor, formatStatNumber } from '../../composables/sourceModel.js'
import { Icon } from '../ui'

const props = defineProps({
  surface: { type: Object, default: null },
  columns: { type: Array, default: null },
})

const { t, locale } = useI18n()
// Default to the Source explorer store (creating it fires NO query); the Evidence host
// passes its own store as `surface`, so useSourcesStore() is skipped entirely there.
const surface = props.surface || useSourcesStore()

const allColumns = computed(() => props.columns || surface.columns || [])
// The type of the chosen column, then its ordered key-figure spec (everything the column
// CAN show; empty when no column).
const calcType = computed(() => {
  const c = allColumns.value.find((x) => x.name === surface.calcColumn)
  return c ? c.type : ''
})
const spec = computed(() => (surface.calcColumn ? statsSpecFor(calcType.value) : []))
// The measures actually selected for display, kept in spec order (calcFns is already a
// sanitized, spec-ordered subset - filtering the spec preserves each measure's labelKey).
const selectedFns = computed(() => surface.calcFns || [])
const selectedSpec = computed(() => spec.value.filter((s) => selectedFns.value.includes(s.fn)))

// The measures dropdown is offered only when the column can show MORE THAN ONE figure
// (a text column offers just distinct count - nothing to pick).
const hasChoice = computed(() => spec.value.length > 1)

// --- measures dropdown ---------------------------------------------------------
const measZone = ref(null)
const measOpen = ref(false)
useClickOutside(measZone, () => { measOpen.value = false })

function isSelected(fn) {
  return selectedFns.value.includes(fn)
}
// Toggle one measure. setCalcFns sanitizes + IGNORES an empty result, so unchecking the
// last selected measure is a no-op (at least one figure always stays shown).
function toggleFn(fn) {
  const cur = selectedFns.value
  const next = cur.includes(fn) ? cur.filter((f) => f !== fn) : cur.concat(fn)
  surface.setCalcFns(next)
}

function fmt(v) {
  return formatStatNumber(v, locale.value)
}
// The DB-computed value for one measure fn ('-' via the formatter when null / absent).
function valueOf(fn) {
  const v = surface.calcValues
  return v && Object.prototype.hasOwnProperty.call(v, fn) ? v[fn] : null
}
function onColumnChange(e) {
  measOpen.value = false
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

      <!-- Measures picker: which of the column's type-driven figures to show. Hidden for a
           single-measure column (nothing to choose). Square flat popover of checkbox rows. -->
      <div v-if="surface.calcColumn && hasChoice" ref="measZone" class="src-calc-meas" @keydown.escape="measOpen = false">
        <button
          type="button" class="meas-btn" :class="{ open: measOpen }"
          :aria-expanded="measOpen" @click="measOpen = !measOpen"
        >
          <span>{{ t('src.calc.measures') }} ({{ selectedFns.length }})</span>
          <Icon name="chevronDown" />
        </button>
        <div v-if="measOpen" class="meas-pop" role="group" :aria-label="t('src.calc.measures')">
          <label
            v-for="s in spec" :key="s.fn" class="pop-item"
            :class="{ 'is-last': isSelected(s.fn) && selectedFns.length === 1 }"
            :title="isSelected(s.fn) && selectedFns.length === 1 ? t('src.calc.keepOne') : null"
          >
            <input
              type="checkbox" :checked="isSelected(s.fn)"
              :disabled="isSelected(s.fn) && selectedFns.length === 1"
              :aria-description="isSelected(s.fn) && selectedFns.length === 1 ? t('src.calc.keepOne') : null"
              @change="toggleFn(s.fn)"
            />
            <span>{{ t(s.labelKey) }}</span>
          </label>
        </div>
      </div>
    </div>

    <!-- Figures for the chosen column: BIG KPI cards for the SELECTED measures (skeleton on
         first load, dimmed on a scope refetch, error state reusing the src.error idiom). -->
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
        <!-- First load (no values yet): discrete skeleton cards matching the selection. -->
        <template v-if="surface.calcLoading && !surface.calcValues">
          <div v-for="s in selectedSpec" :key="'sk-' + s.fn" class="calc-card" aria-hidden="true">
            <span class="calc-card-label">{{ t(s.labelKey) }}</span>
            <span class="calc-card-val sk-val" />
          </div>
        </template>
        <template v-else>
          <div v-for="s in selectedSpec" :key="s.fn" class="calc-card">
            <span class="calc-card-label">{{ t(s.labelKey) }}</span>
            <span class="calc-card-val mono" :title="fmt(valueOf(s.fn))">{{ fmt(valueOf(s.fn)) }}</span>
          </div>
        </template>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* The Calculate zone - a compact, flat, square block that fills the empty top-right
   area. Header (eyebrow + column select + measures picker) above a wrapping row of BIG
   KPI cards. */
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

/* Measures picker - a flat square trigger + a small square popover of checkbox rows. */
.src-calc-meas { position: relative; flex: none; }
.meas-btn {
  display: inline-flex; align-items: center; gap: 6px; padding: 6px 10px;
  border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--bg); color: var(--text-2); font-size: var(--fs-sm);
  transition: all var(--dur) var(--ease);
}
.meas-btn:hover { color: var(--text); }
.meas-btn.open { border-color: var(--orange); color: var(--text); }
.meas-btn :deep(.ui-icon) { width: 12px; height: 12px; }
.meas-pop {
  position: absolute; top: calc(100% + 6px); right: 0; z-index: var(--z-menu);
  min-width: 180px; padding: var(--s-2);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0; box-shadow: var(--shadow);
  display: flex; flex-direction: column;
}
/* Checkbox rows - same .pop-item idiom as SourceChips (orange accent, square). The last
   selected row is disabled (at least one figure must stay shown) and reads dimmed. */
.pop-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  border-radius: 0; font-size: var(--fs-sm); cursor: pointer; color: var(--text);
}
.pop-item:hover { background: var(--surface-hover); }
.pop-item input { accent-color: var(--orange); flex: none; }
.pop-item.is-last { cursor: default; color: var(--text-2); }
.pop-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

/* KPI cards - one BIG flat square card per SELECTED measure; they grow to fill the row and
   wrap onto the next line. Dimmed while a scope change refetches. */
.src-calc-cards { display: flex; flex-wrap: wrap; gap: var(--s-2); transition: opacity var(--dur) var(--ease); }
.src-calc-cards.busy { opacity: 0.55; }
.calc-card {
  display: flex; flex-direction: column; gap: 4px;
  min-width: 140px; flex: 1 1 140px; padding: 10px 12px;
  border: 1px solid var(--border); border-radius: 0; background: var(--surface);
}
.calc-card-label {
  font-size: 11px; color: var(--text-3); text-transform: uppercase; letter-spacing: 0.06em;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* BIG value - large and heavy, and NEVER clipped: a long total wraps (break anywhere) and
   is fully readable (its exact figure is also in the card's title tooltip). */
.calc-card-val {
  font-size: 20px; line-height: 1.2; font-weight: var(--fw-heavy); color: var(--text);
  white-space: normal; overflow-wrap: anywhere; word-break: break-word;
}
/* Skeleton value - a flat surface block with an opacity pulse (no gradient, charter). */
.sk-val { height: 22px; width: 70%; background: var(--surface-2); animation: calc-pulse 1.4s ease-in-out infinite; }
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
