<script setup>
// User filter chips for the Source Data Explorer - every chip is a =/IN filter the
// user built through the distinct-values picker, editable and removable, plus an
// "add filter" chip over any column and a "clear all" reset. Mirrors the Evidence
// chips internals (pickerSeq stale-guard, caps, useClickOutside) but simpler: there
// are no agent-locked chips or advanced fragment - all chips are the user's own.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { Icon } from '../ui'

const { t } = useI18n()
const sources = useSourcesStore()

// Max distinct values shown in the picker - mirrors the backend distinct cap.
const PICKER_LIMIT = 100
// Max values one filter may carry - mirrors the backend per-filter cap.
const MAX_FILTER_VALUES = 50
// Max user filters per request - mirrors the backend filter cap.
const MAX_FILTERS = 20

const zone = ref(null)
// One popover at a time: { kind: 'chip', key } | { kind: 'add' } | null
const pop = ref(null)
const pickerLoading = ref(false)
const pickerValues = ref([])
const pickerTruncated = ref(false)
const pickerSelected = ref([])
const addColumn = ref('')
// Stale-response guard: a late distinct response from a previous popover must never
// overwrite the values (or spinner) of the one currently open.
let pickerSeq = 0

useClickOutside(zone, () => { pop.value = null })

const columns = computed(() => sources.columns || [])
const canAddFilter = computed(() => sources.chips.length < MAX_FILTERS)
const tooManyValues = computed(() => pickerSelected.value.length > MAX_FILTER_VALUES)

function displayValues(chip) {
  return chip.values.map((v) => String(v)).join(', ')
}

async function _loadPicker(column, current) {
  const my = ++pickerSeq
  pickerLoading.value = true
  pickerValues.value = []
  pickerTruncated.value = false
  pickerSelected.value = current.slice()
  try {
    const data = await sources.loadDistinct(column)
    if (my !== pickerSeq) return
    const values = data.values || []
    // Keep the current values selectable even outside the top-N. Compare on String():
    // chip values and live distinct values may differ in type (42 vs "42").
    const seen = new Set(values.map((v) => String(v)))
    const missing = current.filter((v) => !seen.has(String(v)))
    pickerValues.value = missing.concat(values)
    pickerTruncated.value = !!data.truncated
  } catch (e) {
    if (my !== pickerSeq) return
    pickerValues.value = current.slice()
  } finally {
    if (my === pickerSeq) pickerLoading.value = false
  }
}

function openChipPicker(chip) {
  pop.value = { kind: 'chip', key: chip.key }
  _loadPicker(chip.column, chip.values)
}
function openAdd() {
  pickerSeq += 1 // kill any in-flight load (and its spinner) from a previous popover
  pickerLoading.value = false
  pop.value = { kind: 'add' }
  addColumn.value = ''
  pickerValues.value = []
  pickerSelected.value = []
  pickerTruncated.value = false
}
function onAddColumn() {
  if (addColumn.value) _loadPicker(addColumn.value, [])
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
  else if (addColumn.value) sources.addFilter(addColumn.value, pickerSelected.value)
  pop.value = null
}
</script>

<template>
  <div ref="zone" class="src-chips" @keydown.escape="pop = null">
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
          <span class="op mono">{{ chip.op }}</span>
          <span class="val">{{ displayValues(chip) }}</span>
          <Icon name="chevronDown" />
        </button>
        <button class="chip-x" :title="t('src.filters.remove')" @click="onRemoveChip(chip)">
          <Icon name="x" />
        </button>

        <!-- Distinct-values picker (edit an existing filter) -->
        <div v-if="pop && pop.kind === 'chip' && pop.key === chip.key" class="src-pop">
          <div v-if="pickerLoading" class="pop-state">{{ t('src.loading') }}</div>
          <template v-else>
            <div v-if="pickerTruncated" class="pop-note">{{ t('src.picker.truncated', [PICKER_LIMIT]) }}</div>
            <div class="pop-list">
              <label v-for="v in pickerValues" :key="typeof v + ':' + String(v)" class="pop-item">
                <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                <span>{{ String(v) }}</span>
              </label>
              <div v-if="!pickerValues.length" class="pop-state">{{ t('src.picker.empty') }}</div>
            </div>
            <div v-if="tooManyValues" class="pop-note">{{ t('src.picker.max', [MAX_FILTER_VALUES]) }}</div>
            <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
              {{ t('src.picker.apply') }}
            </button>
          </template>
        </div>
      </span>

      <!-- Add a filter on any column (hidden at the backend filter cap) -->
      <span v-if="canAddFilter" class="src-chip add">
        <button class="chip-main" @click="openAdd">
          <Icon name="plus" /><span>{{ t('src.filters.add') }}</span>
        </button>
        <div v-if="pop && pop.kind === 'add'" class="src-pop">
          <select v-model="addColumn" class="pop-select" @change="onAddColumn">
            <option value="" disabled>{{ t('src.column') }}</option>
            <option v-for="c in columns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
          <div v-if="pickerLoading" class="pop-state">{{ t('src.loading') }}</div>
          <template v-else-if="addColumn">
            <div v-if="pickerTruncated" class="pop-note">{{ t('src.picker.truncated', [PICKER_LIMIT]) }}</div>
            <div class="pop-list">
              <label v-for="v in pickerValues" :key="typeof v + ':' + String(v)" class="pop-item">
                <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                <span>{{ String(v) }}</span>
              </label>
              <div v-if="!pickerValues.length" class="pop-state">{{ t('src.picker.empty') }}</div>
            </div>
            <div v-if="tooManyValues" class="pop-note">{{ t('src.picker.max', [MAX_FILTER_VALUES]) }}</div>
            <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
              {{ t('src.picker.apply') }}
            </button>
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

.src-pop {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: var(--z-menu);
  min-width: 220px; max-width: 320px; padding: var(--s-2);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: 0; box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: var(--s-2);
}
.pop-list { max-height: 240px; overflow-y: auto; display: flex; flex-direction: column; }
.pop-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 8px;
  border-radius: 0; font-size: var(--fs-sm); cursor: pointer;
}
.pop-item:hover { background: var(--surface-hover); }
.pop-item input { accent-color: var(--orange); }
.pop-state { padding: var(--s-2); color: var(--text-3); font-size: var(--fs-xs); }
.pop-note { padding: 0 8px; color: var(--text-3); font-size: 11px; }
.pop-select {
  width: 100%; padding: 6px 8px; border: 1px solid var(--border);
  border-radius: 0; background: var(--bg); color: var(--text); font-size: var(--fs-sm);
}
.pop-apply {
  align-self: flex-end; padding: 4px 12px; border-radius: 0;
  background: var(--orange); color: #fff; font-size: var(--fs-xs); font-weight: 500;
}
.pop-apply:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
