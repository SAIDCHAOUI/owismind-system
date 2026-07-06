<script setup>
// User filter chips for the Source Data Explorer - every chip is a =/IN filter the
// user built through the distinct-values picker, editable and removable, plus an
// "add filter" chip over any column and a "clear all" reset. Mirrors the Evidence
// chips internals (pickerSeq stale-guard, caps, useClickOutside) but simpler: there
// are no agent-locked chips or advanced fragment - all chips are the user's own.
//
// The "add filter" popover is a two-step flow (searchable column list -> value
// picker); the value picker is searchable client-side over the loaded window and,
// when the server list is truncated, escalates to a server-side search on Enter.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import {
  SOURCE_Q_MIN,
  foldSearchTerm as fold,
  isTemporalColType,
  monthRangeToBetween,
  monthRangeToBetweenSmart,
  betweenValuesToMonthRange,
  looksLikeIsoDateValues,
  yearOfValue,
} from '../../composables/sourceModel.js'
import RangePopoverFields from './RangePopoverFields.vue'
import { Icon } from '../ui'

const { t } = useI18n()
const sources = useSourcesStore()

// Autofocus a freshly mounted search input (the popover mounts on open, so a
// plain `autofocus` attribute would not re-fire on the next open).
const vFocus = { mounted: (el) => el.focus() }

// Max distinct values shown in the picker - mirrors the backend distinct cap.
const PICKER_LIMIT = 100
// Max values one filter may carry - mirrors the backend per-filter cap.
const MAX_FILTER_VALUES = 50
// Max user filters per request - mirrors the backend filter cap.
const MAX_FILTERS = 20

const zone = ref(null)
// One popover at a time: { kind: 'chip', key } | { kind: 'add' } | null
const pop = ref(null)
// Add flow sub-step: 'column' (search + pick a column) | 'value' (pick values).
const addStep = ref('column')
const pickerLoading = ref(false)
const pickerValues = ref([])
const pickerTruncated = ref(false)
// A distinct request failed for the CURRENT popover: shown instead of a misleading
// "no value" state (cleared on the next load attempt).
const pickerError = ref(false)
const pickerSelected = ref([])
// The column whose values are being picked (add step 2 OR an edited chip).
const pickerColumn = ref('')
// The key of the chip currently being EDITED (null in the add flow): forwarded to the
// cascading distinct picker so the edited chip is dropped from the scope and its own
// values stay offered.
const editedChipKey = ref(null)
// Live search text: colSearch filters the column list, valSearch filters the
// loaded value window (both client-side, accent/case-insensitive).
const colSearch = ref('')
const valSearch = ref('')
// Whether the CURRENT window came from a non-empty server-side search: once a
// search narrowed the window (truncated may then be false), Enter must still be
// able to broaden it or restore the unfiltered top-N on an empty term.
const serverFiltered = ref(false)
// Stale-response guard: a late distinct response from a previous popover (or a
// previous server search) must never overwrite the values (or spinner) of the
// one currently open.
let pickerSeq = 0

// RANGE mode (a date filter picked in 1-2 clicks): two 'YYYY-MM' month fields (From / To)
// + a one-click full-year fill, rendered by the shared RangePopoverFields. Used instead of
// the distinct-values list when the picker column is temporal OR its values sniff as ISO
// date strings (a STRING column that actually stores dates). `rangeLexical` selects the
// BETWEEN bounds: calendar-precise for a true temporal column, shape-mimicking (built from
// the loaded distinct values) for a sniffed string column. Distinct values still load in the
// background (full-year options, the shape sample, + the "pick exact values" list toggle).
const rangeMode = ref(false)
const rangeLexical = ref(false)
const rangeFrom = ref('') // 'YYYY-MM'
const rangeTo = ref('') // 'YYYY-MM'

// Iframe-safe dismissal: also close on window blur (DSS chrome clicks never reach us),
// guarded so opening a native month calendar does not self-close. A full-viewport backdrop
// (template) + Escape are the other two layers.
useClickOutside(zone, () => { pop.value = null }, { closeOnWindowBlur: true })

const columns = computed(() => sources.columns || [])
const canAddFilter = computed(() => sources.chips.length < MAX_FILTERS)
const tooManyValues = computed(() => pickerSelected.value.length > MAX_FILTER_VALUES)

// Type of one column of the active source ('' when unknown).
function colType(name) {
  const c = columns.value.find((x) => x.name === name)
  return c ? c.type : ''
}
// True when the popover's current column is a true temporal type (calendar-precise range).
const isTemporalCol = computed(() => isTemporalColType(colType(pickerColumn.value)))
// Whether a range toggle is meaningful in LIST mode: the column is truly temporal, or its
// loaded values sniff as ISO date strings (a string column that stores dates).
const rangeAvailable = computed(
  () => isTemporalCol.value || looksLikeIsoDateValues(pickerValues.value),
)
// The years present in the loaded distinct values of the temporal column, ascending. When
// empty (not derivable / not loaded yet) the full-year control degrades to a 4-digit input.
const rangeYearOptions = computed(() => {
  const years = new Set()
  for (const v of pickerValues.value) {
    const y = yearOfValue(v)
    if (y) years.add(y)
  }
  return Array.from(years).sort()
})
// Apply stays enabled only when both months are set and parse to a valid range. Both
// builders share the same parse/swap guards, so validity is identical - branch anyway so
// the enabling predicate exactly mirrors the builder applyRange runs. In LEXICAL mode the
// template additionally disables Apply while the distinct window is loading: the smart
// bounds mimic the SAMPLE values' shape, so applying against a not-yet-loaded (empty)
// window would silently fall back to calendar bounds that can miss rows on a bare
// 'YYYY-MM' text column.
const rangeReady = computed(() => !!(rangeLexical.value
  ? monthRangeToBetweenSmart(rangeFrom.value, rangeTo.value, pickerValues.value)
  : monthRangeToBetween(rangeFrom.value, rangeTo.value)))

// Toggle between the month RANGE fields and the exact-values list (a quiet text link).
// Entering range mode picks the bound style from the column type (lexical for a sniffed
// string column, calendar-precise for a temporal one) and keeps any From / To already set.
function enterRangeMode() {
  rangeLexical.value = !isTemporalCol.value
  rangeMode.value = true
}
function exitRangeMode() {
  rangeMode.value = false
}

// Client-side matching folds through the SAME accent map as the server (imported
// `fold`), so a term behaves identically before and after a server-side escalation.
const filteredColumns = computed(() => {
  const needle = fold(colSearch.value.trim())
  if (!needle) return columns.value
  return columns.value.filter((c) => fold(c.name).includes(needle))
})
const filteredValues = computed(() => {
  const needle = fold(valSearch.value.trim())
  if (!needle) return pickerValues.value
  return pickerValues.value.filter((v) => fold(String(v)).includes(needle))
})

function displayValues(chip) {
  return chip.values.map((v) => String(v)).join(', ')
}

// Load one window of distinct values for `column`. `current` values are kept
// selectable even outside the top-N (concatenated when missing). `serverQ` (when
// non-empty) narrows the window server-side over ALL values, not just the top-N. The
// cascade exclude key is read from `editedChipKey` so the edited chip's own values stay
// offered (the add flow leaves it null -> every active chip scopes the picker).
// `sniffPrefill` (an array, or undefined to skip): after a successful load of a
// NON-temporal column, if the window sniffs as ISO date strings, auto-enter TEXT-safe
// range mode prefilled from these values (the chip's, or [] when adding).
// Resolves true on success, false on failure, null when superseded - so a caller
// (the server search) can gate its own state on the request that actually landed.
async function _loadPicker(column, current, serverQ, sniffPrefill) {
  const my = ++pickerSeq
  pickerLoading.value = true
  pickerError.value = false
  pickerValues.value = []
  pickerTruncated.value = false
  pickerSelected.value = current.slice()
  try {
    const data = await sources.loadDistinct(column, serverQ, editedChipKey.value)
    if (my !== pickerSeq) return null
    const values = data.values || []
    // Keep the current values selectable even outside the top-N. Compare on String():
    // chip values and live distinct values may differ in type (42 vs "42").
    const seen = new Set(values.map((v) => String(v)))
    const missing = current.filter((v) => !seen.has(String(v)))
    pickerValues.value = missing.concat(values)
    pickerTruncated.value = !!data.truncated
    // A string column that actually stores dates: offer the 1-2 click range instead of a
    // month-by-month tick. Only on the primary list load (sniffPrefill defined) and never
    // over-riding an already-open range mode.
    if (sniffPrefill !== undefined && !rangeMode.value && looksLikeIsoDateValues(pickerValues.value)) {
      rangeLexical.value = true
      _openRange(sniffPrefill)
      rangeMode.value = true
    }
    return true
  } catch (e) {
    if (my !== pickerSeq) return null
    pickerValues.value = current.slice()
    pickerError.value = true
    return false
  } finally {
    if (my === pickerSeq) pickerLoading.value = false
  }
}

// Pre-fill the range fields from a BETWEEN chip's stored [start, end] (empty when adding
// fresh). The full-year control's own typed-year state resets on remount.
function _openRange(values) {
  const r = betweenValuesToMonthRange(values)
  rangeFrom.value = r ? r.from : ''
  rangeTo.value = r ? r.to : ''
}
function openChipPicker(chip) {
  pop.value = { kind: 'chip', key: chip.key }
  pickerColumn.value = chip.column
  editedChipKey.value = chip.key
  valSearch.value = ''
  serverFiltered.value = false
  rangeMode.value = false
  rangeLexical.value = false
  const temporal = isTemporalColType(colType(chip.column))
  const between = chip.op === 'BETWEEN' && Array.isArray(chip.values) && chip.values.length === 2
  if (temporal) {
    // Temporal column: calendar-precise range. Pre-fill From / To from the chip; load
    // distinct in the background for the full-year options and the "pick exact values" list.
    rangeMode.value = true
    _openRange(chip.values)
    _loadPicker(chip.column, [], '', undefined)
  } else if (between) {
    // Editing an existing lexical range on a STRING column: TEXT-safe range. Same background
    // load (year options + the list toggle).
    rangeMode.value = true
    rangeLexical.value = true
    _openRange(chip.values)
    _loadPicker(chip.column, [], '', undefined)
  } else {
    // Non-temporal, non-range chip: load the distinct list; if it sniffs as ISO dates,
    // auto-enter TEXT-safe range mode prefilled from the chip.
    _loadPicker(chip.column, chip.values, '', chip.values)
  }
}
function openAdd() {
  pickerSeq += 1 // kill any in-flight load (and its spinner) from a previous popover
  pickerLoading.value = false
  pop.value = { kind: 'add' }
  addStep.value = 'column'
  pickerColumn.value = ''
  editedChipKey.value = null
  colSearch.value = ''
  valSearch.value = ''
  serverFiltered.value = false
  pickerValues.value = []
  pickerSelected.value = []
  pickerTruncated.value = false
  rangeMode.value = false
  rangeLexical.value = false
  _openRange([])
}
// Add step 1 -> step 2: a column was chosen. A temporal column enters range mode (and
// loads distinct only to derive year options + the list toggle); any other loads its
// first value window and sniffs it for ISO date strings.
function pickColumn(name) {
  if (!name) return
  addStep.value = 'value'
  pickerColumn.value = name
  valSearch.value = ''
  serverFiltered.value = false
  rangeMode.value = false
  rangeLexical.value = false
  if (isTemporalColType(colType(name))) {
    rangeMode.value = true
    _openRange([])
    _loadPicker(name, [], '', undefined)
  } else {
    _loadPicker(name, [], '', [])
  }
}
// Add step 2 -> step 1: drop the in-flight value load, the picked values and the range.
function backToColumns() {
  pickerSeq += 1
  pickerLoading.value = false
  addStep.value = 'column'
  pickerColumn.value = ''
  valSearch.value = ''
  serverFiltered.value = false
  pickerValues.value = []
  pickerSelected.value = []
  pickerTruncated.value = false
  rangeMode.value = false
  rangeLexical.value = false
  _openRange([])
}
// Enter in the value search. With a term: re-load the window narrowed server-side,
// meaningful when the window is incomplete (truncated top-N) OR already narrowed by
// a previous search (then truncated may be false, but broadening needs a re-query).
// Empty term: restore the unfiltered top-N after a server search. The in-progress
// selection is kept (missing values are concatenated back). `serverFiltered` is only
// committed once the request LANDS (a failed or superseded search must not relabel
// the window); a term below the server's minimum needle is not escalated at all
// (the backend would silently ignore it and re-run the unfiltered top-N).
async function onValueSearchEnter() {
  if (!pickerColumn.value || pickerLoading.value) return
  const qText = valSearch.value.trim()
  if (qText) {
    if (fold(qText).length < SOURCE_Q_MIN) return
    if (!pickerTruncated.value && !serverFiltered.value) return
    const ok = await _loadPicker(pickerColumn.value, pickerSelected.value, qText)
    if (ok === true) serverFiltered.value = true
  } else {
    if (!serverFiltered.value) return
    const ok = await _loadPicker(pickerColumn.value, pickerSelected.value, '')
    if (ok === true) serverFiltered.value = false
  }
}
function onClear() {
  pop.value = null
  sources.clearFilters()
}
function onRemoveChip(chip) {
  if (pop.value && pop.value.kind === 'chip' && pop.value.key === chip.key) pop.value = null
  sources.removeChip(chip.key)
}
function isSelected(v) {
  const s = String(v)
  return pickerSelected.value.some((x) => String(x) === s)
}
function toggleValue(v) {
  const s = String(v)
  const i = pickerSelected.value.findIndex((x) => String(x) === s)
  if (i >= 0) pickerSelected.value.splice(i, 1)
  else pickerSelected.value.push(v)
}
function applyPicker() {
  if (!pop.value || !pickerSelected.value.length || tooManyValues.value) return
  if (pop.value.kind === 'chip') sources.setChipValues(pop.value.key, pickerSelected.value)
  else if (pickerColumn.value) sources.addFilter(pickerColumn.value, pickerSelected.value)
  pop.value = null
}
function cancelPicker() {
  pop.value = null
}

// --- range apply ---------------------------------------------------------------
// Build ONE BETWEEN chip from the two month fields. A true temporal column uses
// calendar-precise bounds; a string column sniffed as dates uses bounds that mimic the
// loaded distinct-values shape (parseable on either a text OR a lying date/timestamp column).
// Both builders swap a reversed From > To and return null when a month is missing / malformed
// (apply is disabled then). The chip keeps its explicit op so it is never re-normalized.
function applyRange() {
  if (!pop.value) return
  const range = rangeLexical.value
    ? monthRangeToBetweenSmart(rangeFrom.value, rangeTo.value, pickerValues.value)
    : monthRangeToBetween(rangeFrom.value, rangeTo.value)
  if (!range) return
  const values = [range.start, range.end]
  if (pop.value.kind === 'chip') sources.setChipValues(pop.value.key, values, 'BETWEEN')
  else if (pickerColumn.value) sources.addFilter(pickerColumn.value, values, 'BETWEEN')
  pop.value = null
}

// --- chip display --------------------------------------------------------------
// A BETWEEN chip (a 2-value temporal range) reads as its month span; anything else lists
// its values. The column name is always shown separately (chip.column).
function isBetween(chip) {
  return chip.op === 'BETWEEN' && Array.isArray(chip.values) && chip.values.length === 2
}
function rangeText(chip) {
  const r = betweenValuesToMonthRange(chip.values)
  return r ? t('src.range.chip', [r.from, r.to]) : displayValues(chip)
}
</script>

<template>
  <div ref="zone" class="src-chips" @keydown.escape="pop = null">
    <!-- Invisible full-viewport backdrop while a popover is open: makes dismissal
         STRUCTURAL (a first click anywhere closes without activating what is underneath).
         mousedown.prevent blocks focus-steal / text-selection; the popovers paint above it
         (same z-index, later in DOM within this stacking context). -->
    <div
      v-if="pop" class="src-backdrop"
      @mousedown.prevent @click="pop = null"
    ></div>
    <div class="src-chips-head">
      <span class="src-chips-title">{{ t('src.filters.title') }}</span>
      <button v-if="sources.chips.length" class="src-clear" @click="onClear">
        <Icon name="refresh" /><span>{{ t('src.filters.clear') }}</span>
      </button>
    </div>

    <div class="src-chips-row">
      <span v-for="chip in sources.chips" :key="chip.key" class="src-chip">
        <button class="chip-main" @click="openChipPicker(chip)">
          <span class="col">{{ chip.column }}</span>
          <template v-if="isBetween(chip)">
            <span class="val">{{ rangeText(chip) }}</span>
          </template>
          <template v-else>
            <span class="op mono">{{ chip.op }}</span>
            <span class="val">{{ displayValues(chip) }}</span>
          </template>
          <Icon name="chevronDown" />
        </button>
        <button class="chip-x" :title="t('src.filters.remove')" @click="onRemoveChip(chip)">
          <Icon name="x" />
        </button>

        <!-- Edit an existing filter: a month RANGE picker for a temporal column, the
             distinct-values picker otherwise. -->
        <div v-if="pop && pop.kind === 'chip' && pop.key === chip.key" class="src-pop">
          <!-- RANGE mode: From / To months + a one-click full-year fill + a link back to
               the exact-values list. -->
          <div v-if="rangeMode" class="pop-range">
            <RangePopoverFields v-model:from="rangeFrom" v-model:to="rangeTo" :year-options="rangeYearOptions" />
            <button type="button" class="pop-toggle" @click="exitRangeMode">{{ t('src.range.pickList') }}</button>
            <div class="pop-foot">
              <div class="pop-actions">
                <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                <button class="pop-apply" :disabled="!rangeReady || (rangeLexical && pickerLoading)" @click="applyRange">{{ t('src.range.apply') }}</button>
              </div>
            </div>
          </div>
          <!-- Distinct-values picker (non-range column, or list toggled on). -->
          <template v-else>
            <input
              v-model="valSearch" v-focus class="pop-search" type="text"
              :placeholder="t('src.picker.searchVals')"
              @keydown.enter.prevent="onValueSearchEnter"
            />
            <div v-if="pickerLoading" class="pop-state">{{ t('src.loading') }}</div>
            <template v-else>
              <div v-if="pickerError" class="pop-error">{{ t('src.picker.error') }}</div>
              <template v-if="pickerTruncated">
                <div class="pop-note">{{ t('src.picker.truncated', [PICKER_LIMIT]) }}</div>
                <div class="pop-hint">{{ t('src.picker.searchHint') }}</div>
              </template>
              <div v-else-if="serverFiltered" class="pop-hint">{{ t('src.picker.serverFiltered') }}</div>
              <div class="pop-list">
                <label v-for="v in filteredValues" :key="typeof v + ':' + String(v)" class="pop-item">
                  <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                  <span :title="String(v)">{{ String(v) }}</span>
                </label>
                <div v-if="!filteredValues.length" class="pop-state">
                  {{ pickerValues.length ? t('src.picker.noMatch') : t('src.picker.empty') }}
                </div>
              </div>
              <button v-if="rangeAvailable" type="button" class="pop-toggle" @click="enterRangeMode">
                {{ t('src.range.pickRange') }}
              </button>
              <div v-if="tooManyValues" class="pop-note">{{ t('src.picker.max', [MAX_FILTER_VALUES]) }}</div>
              <div class="pop-foot">
                <span v-if="pickerSelected.length" class="pop-count">
                  {{ t('src.picker.selected', [pickerSelected.length]) }}
                </span>
                <div class="pop-actions">
                  <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                  <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
                    {{ t('src.picker.apply') }}
                  </button>
                </div>
              </div>
            </template>
          </template>
        </div>
      </span>

      <!-- Add a filter on any column (hidden at the backend filter cap) -->
      <span v-if="canAddFilter" class="src-chip add">
        <button class="chip-main" @click="openAdd">
          <Icon name="plus" /><span>{{ t('src.filters.add') }}</span>
        </button>
        <div v-if="pop && pop.kind === 'add'" class="src-pop">
          <!-- Step 1: search + pick a column -->
          <template v-if="addStep === 'column'">
            <input
              v-model="colSearch" v-focus class="pop-search" type="text"
              :placeholder="t('src.picker.searchCols')"
            />
            <div class="pop-list">
              <button v-for="c in filteredColumns" :key="c.name" class="pop-col" @click="pickColumn(c.name)">
                <span class="pop-col-name">{{ c.name }}</span>
                <span v-if="c.type" class="pop-col-type mono">{{ c.type }}</span>
              </button>
              <div v-if="!filteredColumns.length" class="pop-state">{{ t('src.picker.noColMatch') }}</div>
            </div>
          </template>
          <!-- Step 2: pick values for the chosen column -->
          <template v-else>
            <div class="pop-head">
              <button class="pop-back" @click="backToColumns">
                <Icon name="chevronLeft" /><span>{{ t('src.picker.back') }}</span>
              </button>
              <span class="pop-head-col">{{ pickerColumn }}</span>
            </div>
            <!-- RANGE mode: From / To months + a one-click full-year fill + a link back to
                 the exact-values list. -->
            <div v-if="rangeMode" class="pop-range">
              <RangePopoverFields v-model:from="rangeFrom" v-model:to="rangeTo" :year-options="rangeYearOptions" />
              <button type="button" class="pop-toggle" @click="exitRangeMode">{{ t('src.range.pickList') }}</button>
              <div class="pop-foot">
                <div class="pop-actions">
                  <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                  <button class="pop-apply" :disabled="!rangeReady || (rangeLexical && pickerLoading)" @click="applyRange">{{ t('src.range.apply') }}</button>
                </div>
              </div>
            </div>
            <!-- Distinct-values picker (non-range column, or list toggled on). -->
            <template v-else>
              <input
                v-model="valSearch" v-focus class="pop-search" type="text"
                :placeholder="t('src.picker.searchVals')"
                @keydown.enter.prevent="onValueSearchEnter"
              />
              <div v-if="pickerLoading" class="pop-state">{{ t('src.loading') }}</div>
              <template v-else>
                <div v-if="pickerError" class="pop-error">{{ t('src.picker.error') }}</div>
                <template v-if="pickerTruncated">
                  <div class="pop-note">{{ t('src.picker.truncated', [PICKER_LIMIT]) }}</div>
                  <div class="pop-hint">{{ t('src.picker.searchHint') }}</div>
                </template>
                <div v-else-if="serverFiltered" class="pop-hint">{{ t('src.picker.serverFiltered') }}</div>
                <div class="pop-list">
                  <label v-for="v in filteredValues" :key="typeof v + ':' + String(v)" class="pop-item">
                    <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                    <span :title="String(v)">{{ String(v) }}</span>
                  </label>
                  <div v-if="!filteredValues.length" class="pop-state">
                    {{ pickerValues.length ? t('src.picker.noMatch') : t('src.picker.empty') }}
                  </div>
                </div>
                <button v-if="rangeAvailable" type="button" class="pop-toggle" @click="enterRangeMode">
                  {{ t('src.range.pickRange') }}
                </button>
                <div v-if="tooManyValues" class="pop-note">{{ t('src.picker.max', [MAX_FILTER_VALUES]) }}</div>
                <div class="pop-foot">
                  <span v-if="pickerSelected.length" class="pop-count">
                    {{ t('src.picker.selected', [pickerSelected.length]) }}
                  </span>
                  <div class="pop-actions">
                    <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                    <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
                      {{ t('src.picker.apply') }}
                    </button>
                  </div>
                </div>
              </template>
            </template>
          </template>
        </div>
      </span>
    </div>
  </div>
</template>

<style scoped>
/* Keep the chips block above the table's stacking context so the picker popover
   is never painted over (mirrors the Evidence chips z-index rule). Square geometry. */
.src-chips { display: flex; flex-direction: column; gap: var(--s-2); position: relative; z-index: 5; }
/* Invisible full-viewport backdrop while a popover is open. Same stacking context as the
   popover (this block has z-index:5); same z-index as .src-pop but EARLIER in the DOM, so
   the popover paints above it. Transparent - it only intercepts the dismiss click. */
.src-backdrop { position: fixed; inset: 0; z-index: var(--z-menu); background: transparent; }
.src-chips-head { display: flex; align-items: center; gap: var(--s-3); }
.src-chips-title { font-size: var(--fs-xs); color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
.src-clear {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  font-size: var(--fs-xs); color: var(--text-2); border-radius: 0;
  transition: all var(--dur) var(--ease);
}
.src-clear:hover { background: var(--surface-hover); color: var(--text); }
.src-clear :deep(.ui-icon) { width: 12px; height: 12px; }

.src-chips-row { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.src-chip {
  position: relative; display: inline-flex; align-items: center; gap: 4px;
  max-width: 100%; border: 1px solid var(--border-strong); border-radius: 0;
  background: var(--surface); padding: 2px 6px 2px 10px; font-size: var(--fs-xs);
}
.chip-main { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: inherit; }
.chip-main:hover .val { color: var(--orange); }
.chip-main :deep(.ui-icon) { width: 11px; height: 11px; }
.chip-main .col { color: var(--text-2); }
.chip-main .op { color: var(--text-3); font-size: 10px; }
.chip-main .val {
  color: var(--text); max-width: 220px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.chip-x { padding: 2px; border-radius: 0; color: var(--text-3); }
.chip-x:hover { color: var(--danger); }
.chip-x :deep(.ui-icon) { width: 11px; height: 11px; }
.src-chip.add { border-style: dashed; }
.src-chip.add .chip-main { color: var(--text-2); gap: 4px; padding: 2px 4px; }
.src-chip.add .chip-main:hover { color: var(--orange); }

/* Popover: aerated, square, token-driven. Wide enough for long values, capped so
   it never dominates the panel; the value/column list scrolls inside. */
.src-pop {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: var(--z-menu);
  min-width: 280px; max-width: 380px; padding: var(--s-3);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0; box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: var(--s-3);
}
.pop-search {
  width: 100%; padding: 6px 10px; border: 1px solid var(--border);
  border-radius: 0; background: var(--bg); color: var(--text); font-size: var(--fs-sm);
}
.pop-search::placeholder { color: var(--text-3); }

/* Temporal range picker wrapper - the From / To fields + full-year control live in the
   shared RangePopoverFields; this only stacks them above the apply / cancel foot. */
.pop-range { display: flex; flex-direction: column; gap: var(--s-3); }
/* Quiet text-link toggle between the range picker and the exact-values list. */
.pop-toggle {
  align-self: flex-start; padding: 2px 0; background: transparent; border: 0;
  color: var(--text-2); font-size: var(--fs-xs); border-radius: 0; cursor: pointer;
}
.pop-toggle:hover { color: var(--text); }
.pop-head { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
.pop-back {
  display: inline-flex; align-items: center; gap: 2px; padding: 2px 6px 2px 2px;
  color: var(--text-2); font-size: var(--fs-xs); border-radius: 0; flex: none;
}
.pop-back:hover { color: var(--text); }
.pop-back :deep(.ui-icon) { width: 13px; height: 13px; }
.pop-head-col {
  font-size: var(--fs-sm); font-weight: var(--fw-heavy); color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.pop-list { max-height: 280px; overflow-y: auto; display: flex; flex-direction: column; }
.pop-col {
  display: flex; align-items: center; justify-content: space-between; gap: var(--s-3);
  width: 100%; padding: 6px 10px; border-radius: 0; color: var(--text);
  font-size: var(--fs-sm); text-align: left;
}
.pop-col:hover { background: var(--surface-hover); }
.pop-col-name { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pop-col-type { color: var(--text-3); font-size: 11px; flex: none; }
.pop-item {
  display: flex; align-items: center; gap: 8px; padding: 6px 10px;
  border-radius: 0; font-size: var(--fs-sm); cursor: pointer;
}
.pop-item:hover { background: var(--surface-hover); }
.pop-item input { accent-color: var(--orange); flex: none; }
.pop-item span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.pop-state { padding: var(--s-2); color: var(--text-3); font-size: var(--fs-xs); }
.pop-note { padding: 0 2px; color: var(--text-3); font-size: 11px; }
.pop-hint { padding: 0 2px; color: var(--text-2); font-size: 11px; }
.pop-error { padding: 0 2px; color: var(--danger); font-size: 11px; }
.pop-foot { display: flex; align-items: center; gap: var(--s-3); }
.pop-count { font-size: var(--fs-xs); color: var(--text-2); }
.pop-actions { display: flex; align-items: center; gap: var(--s-2); margin-left: auto; }
.pop-cancel {
  padding: 4px 12px; border-radius: 0; background: transparent;
  border: 1px solid var(--border); color: var(--text-2); font-size: var(--fs-xs);
}
.pop-cancel:hover { color: var(--text); background: var(--surface-hover); }
.pop-apply {
  padding: 4px 12px; border-radius: 0;
  background: var(--orange); color: #fff; font-size: var(--fs-xs); font-weight: 500;
}
.pop-apply:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
