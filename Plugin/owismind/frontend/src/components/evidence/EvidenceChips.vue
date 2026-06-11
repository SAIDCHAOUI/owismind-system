<script setup>
// Filter chips — the agent's WHERE decomposed into chips. EVERY value chip is
// editable through the distinct-values picker (editing a comparison chip like
// `period >= '2025-01'` converts it to =/IN of the picked values) and every
// chip is removable; the advanced fragment is one chip removable as a whole.
// Plus an "add filter" chip over any column and an "agent version" reset.
// Visual grammar (maquette, no-green rule): value chips = solid border,
// advanced/add = dashed border, modified state = dashed ORANGE badge.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { Icon } from '../ui'

const { t } = useI18n()
const evidence = useEvidenceStore()

// Max distinct values shown in the picker — mirrors backend service.DISTINCT_LIMIT.
const PICKER_LIMIT = 100
// Max values one filter may carry — mirrors backend MAX_EVIDENCE_IN_VALUES
// (security/validation.py): a bigger selection would 400 on every rows call.
const MAX_FILTER_VALUES = 50
// Max client filters per request — mirrors backend MAX_EVIDENCE_FILTERS.
const MAX_FILTERS = 20

const zone = ref(null)
// One popover at a time: { kind: 'chip', key } | { kind: 'add' } | null
const pop = ref(null)
const pickerLoading = ref(false)
const pickerValues = ref([])
const pickerTruncated = ref(false)
const pickerSelected = ref([])
const addColumn = ref('')
// Stale-response guard: a late distinct response from a previous popover must
// never overwrite the values (or spinner) of the one currently open.
let pickerSeq = 0

useClickOutside(zone, () => { pop.value = null })

const columns = computed(() => (evidence.meta && evidence.meta.columns) || [])
const advanced = computed(() => evidence.meta && evidence.meta.advanced)
// Backend rejects requests with more than MAX_FILTERS structured filters:
// stop offering "add" once the editable+user chips reach the cap.
const canAddFilter = computed(
  () => evidence.chips.filter((c) => c.editable || c.source === 'user').length < MAX_FILTERS,
)
const tooManyValues = computed(() => pickerSelected.value.length > MAX_FILTER_VALUES)

function displayValues(chip) {
  return chip.values.map((v) => String(v)).join(', ')
}

async function _loadPicker(column, current, excludeId) {
  const my = ++pickerSeq
  pickerLoading.value = true
  pickerValues.value = []
  pickerTruncated.value = false
  pickerSelected.value = current.slice()
  try {
    const data = await evidence.loadDistinct(column, excludeId)
    if (my !== pickerSeq) return
    const values = data.values || []
    // Keep the agent's original values selectable even outside the top-N.
    // Compare on String(): chip values parsed from SQL text may be strings
    // while live distinct values are typed (42 vs "42") — dedupe on display form.
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
  // Pre-select the current values only for =/IN chips: for any other op
  // (!=, NOT IN, >=, BETWEEN, LIKE…) the stored values are NOT a selection —
  // pre-checking them and applying would silently INVERT or distort the
  // agent's filter. The user picks the values they want explicitly.
  const preselect = chip.op === '=' || chip.op === 'IN' ? chip.values : []
  // The chip's own server-side predicate must not scope its own picker.
  const excludeId = chip.source === 'agent' && chip.id != null ? chip.id : null
  _loadPicker(chip.column, preselect, excludeId)
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
  if (addColumn.value) _loadPicker(addColumn.value, [], null)
}
// Store actions that rebuild/remove chips must close an open picker first:
// the recreated chips keep their keys, so a surviving popover would re-apply
// its PRE-action selection on the next Apply click.
function onReset() {
  pop.value = null
  evidence.resetToAgent()
}
function onRemoveChip(chip) {
  if (pop.value && pop.value.kind === 'chip' && pop.value.key === chip.key) pop.value = null
  evidence.removeChip(chip.key)
}
// Selection compares on String(v), consistent with the picker's dedupe: chip
// values parsed from SQL text may be strings while live distinct values carry
// the column's real type ('2024' vs 2024) — display form is the identity here.
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
  if (pop.value.kind === 'chip') evidence.setChipValues(pop.value.key, pickerSelected.value)
  else if (addColumn.value) evidence.addFilter(addColumn.value, pickerSelected.value)
  pop.value = null
}
</script>

<template>
  <div ref="zone" class="ev-chips" @keydown.escape="pop = null">
    <div class="ev-chips-head">
      <span class="ev-chips-title">{{ t('ev.filters') }}</span>
      <span v-if="evidence.modified" class="ev-modified">{{ t('ev.modified') }}</span>
      <button v-if="evidence.modified" class="ev-reset" @click="onReset">
        <Icon name="refresh" /><span>{{ t('ev.filters.reset') }}</span>
      </button>
    </div>

    <div class="ev-chips-row">
      <span v-for="chip in evidence.chips" :key="chip.key" class="ev-chip"
            :class="{ user: chip.source === 'user' }">
        <button class="chip-main" @click="openChipPicker(chip)">
          <span class="col">{{ chip.column }}</span>
          <span class="op mono">{{ chip.op }}</span>
          <span class="val">{{ displayValues(chip) }}</span>
          <Icon name="chevronDown" />
        </button>
        <button class="chip-x" :title="t('ev.filters.remove')" @click="onRemoveChip(chip)">
          <Icon name="x" />
        </button>

        <!-- Distinct-values picker -->
        <div v-if="pop && pop.kind === 'chip' && pop.key === chip.key" class="ev-pop">
          <div v-if="pickerLoading" class="pop-state">{{ t('ev.loading') }}</div>
          <template v-else>
            <div v-if="pickerTruncated" class="pop-note">{{ t('ev.picker.truncated', [PICKER_LIMIT]) }}</div>
            <div class="pop-list">
              <label v-for="v in pickerValues" :key="typeof v + ':' + String(v)" class="pop-item">
                <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                <span>{{ String(v) }}</span>
              </label>
              <div v-if="!pickerValues.length" class="pop-state">{{ t('ev.picker.empty') }}</div>
            </div>
            <div v-if="tooManyValues" class="pop-note">{{ t('ev.picker.max', [MAX_FILTER_VALUES]) }}</div>
            <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
              {{ t('ev.picker.apply') }}
            </button>
          </template>
        </div>
      </span>

      <!-- Advanced (non-decomposable) fragment: removable as a whole -->
      <span v-if="advanced && advanced.present && evidence.includeAdvanced" class="ev-chip advanced">
        <span class="chip-main static" :title="advanced.display">
          <span class="col">{{ t('ev.filters.advanced') }}</span>
          <span class="val mono">{{ advanced.display }}</span>
        </span>
        <button class="chip-x" :title="t('ev.filters.remove')" @click="evidence.removeAdvanced()">
          <Icon name="x" />
        </button>
      </span>

      <!-- Add a filter on any column (hidden at the backend filter cap) -->
      <span v-if="canAddFilter" class="ev-chip add">
        <button class="chip-main" @click="openAdd">
          <Icon name="plus" /><span>{{ t('ev.filters.add') }}</span>
        </button>
        <div v-if="pop && pop.kind === 'add'" class="ev-pop">
          <select v-model="addColumn" class="pop-select" @change="onAddColumn">
            <option value="" disabled>{{ t('ev.column') }}</option>
            <option v-for="c in columns" :key="c.name" :value="c.name">{{ c.name }}</option>
          </select>
          <div v-if="pickerLoading" class="pop-state">{{ t('ev.loading') }}</div>
          <template v-else-if="addColumn">
            <div class="pop-list">
              <label v-for="v in pickerValues" :key="typeof v + ':' + String(v)" class="pop-item">
                <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                <span>{{ String(v) }}</span>
              </label>
              <div v-if="!pickerValues.length" class="pop-state">{{ t('ev.picker.empty') }}</div>
            </div>
            <div v-if="tooManyValues" class="pop-note">{{ t('ev.picker.max', [MAX_FILTER_VALUES]) }}</div>
            <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
              {{ t('ev.picker.apply') }}
            </button>
          </template>
        </div>
      </span>
    </div>
  </div>
</template>

<style scoped>
/* The reveal animations on .ev-body children (EvidencePanel's ev-rise, fill
   both) create sibling stacking contexts: without an explicit z-index the
   TABLE block paints over the picker popover. Keep the chips block above. */
.ev-chips { display: flex; flex-direction: column; gap: var(--s-2); position: relative; z-index: 5; }
.ev-chips-head { display: flex; align-items: center; gap: var(--s-3); }
.ev-chips-title { font-size: var(--fs-xs); color: var(--text-3); text-transform: uppercase; letter-spacing: 0.04em; }
.ev-modified {
  font-size: 11px; color: var(--orange); border: 1px dashed var(--orange);
  border-radius: 999px; padding: 1px 8px;
}
.ev-reset {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  font-size: var(--fs-xs); color: var(--text-2); border-radius: var(--r-sm);
  transition: all var(--dur) var(--ease);
}
.ev-reset:hover { background: var(--surface-hover); color: var(--text); }
.ev-reset :deep(.ui-icon) { width: 12px; height: 12px; }

.ev-chips-row { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.ev-chip {
  position: relative; display: inline-flex; align-items: center; gap: 4px;
  max-width: 100%; border: 1px solid var(--border-strong); border-radius: 999px;
  background: var(--surface); padding: 2px 6px 2px 10px; font-size: var(--fs-xs);
}
.ev-chip.advanced { border-style: dashed; color: var(--text-2); }
.ev-chip.user { border-color: var(--orange); }
.chip-main { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: inherit; }
.chip-main:not(.static):hover .val { color: var(--orange); }
.chip-main :deep(.ui-icon) { width: 11px; height: 11px; }
.chip-main .col { color: var(--text-2); }
.chip-main .op { color: var(--text-3); font-size: 10px; }
.chip-main .val {
  color: var(--text); max-width: 220px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.ev-chip.advanced .val { max-width: 280px; }
.chip-x { padding: 2px; border-radius: 50%; color: var(--text-3); }
.chip-x:hover { color: var(--danger); }
.chip-x :deep(.ui-icon) { width: 11px; height: 11px; }
.ev-chip.add { border-style: dashed; }
.ev-chip.add .chip-main { color: var(--text-2); gap: 4px; padding: 2px 4px; }
.ev-chip.add .chip-main:hover { color: var(--orange); }

.ev-pop {
  position: absolute; top: calc(100% + 6px); left: 0; z-index: var(--z-menu);
  min-width: 220px; max-width: 320px; padding: var(--s-2);
  background: var(--surface); border: 1px solid var(--border);
  border-radius: var(--r); box-shadow: var(--shadow);
  display: flex; flex-direction: column; gap: var(--s-2);
}
.pop-list { max-height: 240px; overflow-y: auto; display: flex; flex-direction: column; }
.pop-item {
  display: flex; align-items: center; gap: 8px; padding: 5px 8px;
  border-radius: var(--r-sm); font-size: var(--fs-sm); cursor: pointer;
}
.pop-item:hover { background: var(--surface-hover); }
.pop-item input { accent-color: var(--orange); }
.pop-state { padding: var(--s-2); color: var(--text-3); font-size: var(--fs-xs); }
.pop-note { padding: 0 8px; color: var(--text-3); font-size: 11px; }
.pop-select {
  width: 100%; padding: 6px 8px; border: 1px solid var(--border);
  border-radius: var(--r-sm); background: var(--bg); color: var(--text);
  font-size: var(--fs-sm);
}
.pop-apply {
  align-self: flex-end; padding: 4px 12px; border-radius: var(--r-sm);
  background: var(--orange); color: #fff; font-size: var(--fs-xs); font-weight: 500;
}
.pop-apply:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
