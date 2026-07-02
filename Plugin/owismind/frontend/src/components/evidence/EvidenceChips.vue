<script setup>
// Filter chips - the agent's WHERE decomposed into chips. EVERY value chip is
// editable through the distinct-values picker (editing a comparison chip like
// `period >= '2025-01'` converts it to =/IN of the picked values) and every
// chip is removable; the advanced fragment is one chip removable as a whole.
// Plus an "add filter" chip over any column and an "agent version" reset.
// Visual grammar (charter, no-green rule): value chips = solid border,
// advanced/add = dashed border, modified state = dashed ORANGE badge.
//
// The "add filter" popover is a two-step flow (searchable column list -> value
// picker); the value picker is searchable client-side over the loaded window and,
// when the server list is truncated, escalates to a server-side search on Enter.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { SOURCE_Q_MIN, foldSearchTerm as fold } from '../../composables/sourceModel.js'
import { Icon } from '../ui'

const { t } = useI18n()
const evidence = useEvidenceStore()

// Autofocus a freshly mounted search input (the popover mounts on open, so a
// plain `autofocus` attribute would not re-fire on the next open).
const vFocus = { mounted: (el) => el.focus() }

// Max distinct values shown in the picker - mirrors backend service.DISTINCT_LIMIT.
const PICKER_LIMIT = 100
// Max values one filter may carry - mirrors backend MAX_EVIDENCE_IN_VALUES
// (security/validation.py): a bigger selection would 400 on every rows call.
const MAX_FILTER_VALUES = 50
// Max client filters per request - mirrors backend MAX_EVIDENCE_FILTERS.
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
// The column whose values are being picked (add step 2 OR an edited chip) and the
// server id whose predicate must NOT scope its own picker (edited agent chip only).
const pickerColumn = ref('')
const pickerExcludeId = ref(null)
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

useClickOutside(zone, () => { pop.value = null })

const columns = computed(() => (evidence.meta && evidence.meta.columns) || [])
const advanced = computed(() => evidence.meta && evidence.meta.advanced)
// Backend rejects requests with more than MAX_FILTERS structured filters:
// stop offering "add" once the editable+user chips reach the cap.
const canAddFilter = computed(
  () => evidence.chips.filter((c) => c.editable || c.source === 'user').length < MAX_FILTERS,
)
const tooManyValues = computed(() => pickerSelected.value.length > MAX_FILTER_VALUES)

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
// selectable even outside the top-N (concatenated when missing). `excludeId` keeps
// an edited agent chip from scoping its own picker; `serverQ` (when non-empty)
// narrows the window server-side over ALL values, not just the top-N.
// Resolves true on success, false on failure, null when superseded - so a caller
// (the server search) can gate its own state on the request that actually landed.
async function _loadPicker(column, current, excludeId, serverQ) {
  const my = ++pickerSeq
  pickerLoading.value = true
  pickerError.value = false
  pickerValues.value = []
  pickerTruncated.value = false
  pickerSelected.value = current.slice()
  try {
    const data = await evidence.loadDistinct(column, excludeId, serverQ)
    if (my !== pickerSeq) return null
    const values = data.values || []
    // Keep the agent's original values selectable even outside the top-N.
    // Compare on String(): chip values parsed from SQL text may be strings
    // while live distinct values are typed (42 vs "42") - dedupe on display form.
    const seen = new Set(values.map((v) => String(v)))
    const missing = current.filter((v) => !seen.has(String(v)))
    pickerValues.value = missing.concat(values)
    pickerTruncated.value = !!data.truncated
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

function openChipPicker(chip) {
  pop.value = { kind: 'chip', key: chip.key }
  // Pre-select the current values only for =/IN chips: for any other op
  // (!=, NOT IN, >=, BETWEEN, LIKE…) the stored values are NOT a selection -
  // pre-checking them and applying would silently INVERT or distort the
  // agent's filter. The user picks the values they want explicitly.
  const preselect = chip.op === '=' || chip.op === 'IN' ? chip.values : []
  // The chip's own server-side predicate must not scope its own picker.
  const excludeId = chip.source === 'agent' && chip.id != null ? chip.id : null
  pickerColumn.value = chip.column
  pickerExcludeId.value = excludeId
  valSearch.value = ''
  serverFiltered.value = false
  _loadPicker(chip.column, preselect, excludeId, '')
}
function openAdd() {
  pickerSeq += 1 // kill any in-flight load (and its spinner) from a previous popover
  pickerLoading.value = false
  pop.value = { kind: 'add' }
  addStep.value = 'column'
  pickerColumn.value = ''
  pickerExcludeId.value = null
  colSearch.value = ''
  valSearch.value = ''
  serverFiltered.value = false
  pickerValues.value = []
  pickerSelected.value = []
  pickerTruncated.value = false
}
// Add step 1 -> step 2: a column was chosen, load its first value window.
function pickColumn(name) {
  if (!name) return
  addStep.value = 'value'
  pickerColumn.value = name
  pickerExcludeId.value = null
  valSearch.value = ''
  serverFiltered.value = false
  _loadPicker(name, [], null, '')
}
// Add step 2 -> step 1: drop the in-flight value load and the picked values.
function backToColumns() {
  pickerSeq += 1
  pickerLoading.value = false
  addStep.value = 'column'
  pickerColumn.value = ''
  pickerExcludeId.value = null
  valSearch.value = ''
  serverFiltered.value = false
  pickerValues.value = []
  pickerSelected.value = []
  pickerTruncated.value = false
}
// Enter in the value search. With a term: re-load the window narrowed server-side,
// meaningful when the window is incomplete (truncated top-N) OR already narrowed by
// a previous search (then truncated may be false, but broadening needs a re-query).
// Empty term: restore the unfiltered top-N after a server search. The in-progress
// selection is kept (missing values are concatenated back) and the excludeId scope
// is preserved. `serverFiltered` is only committed once the request LANDS (a failed
// or superseded search must not relabel the window); a term below the server's
// minimum needle is not escalated at all (the backend would silently ignore it and
// re-run the unfiltered top-N).
async function onValueSearchEnter() {
  if (!pickerColumn.value || pickerLoading.value) return
  const qText = valSearch.value.trim()
  if (qText) {
    if (fold(qText).length < SOURCE_Q_MIN) return
    if (!pickerTruncated.value && !serverFiltered.value) return
    const ok = await _loadPicker(pickerColumn.value, pickerSelected.value, pickerExcludeId.value, qText)
    if (ok === true) serverFiltered.value = true
  } else {
    if (!serverFiltered.value) return
    const ok = await _loadPicker(pickerColumn.value, pickerSelected.value, pickerExcludeId.value, '')
    if (ok === true) serverFiltered.value = false
  }
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
// the column's real type ('2024' vs 2024) - display form is the identity here.
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
  else if (pickerColumn.value) evidence.addFilter(pickerColumn.value, pickerSelected.value)
  pop.value = null
}
function cancelPicker() {
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

        <!-- Distinct-values picker (edit an existing filter) -->
        <div v-if="pop && pop.kind === 'chip' && pop.key === chip.key" class="ev-pop">
          <input
            v-model="valSearch" v-focus class="pop-search" type="text"
            :placeholder="t('src.picker.searchVals')"
            @keydown.enter.prevent="onValueSearchEnter"
          />
          <div v-if="pickerLoading" class="pop-state">{{ t('ev.loading') }}</div>
          <template v-else>
            <div v-if="pickerError" class="pop-error">{{ t('src.picker.error') }}</div>
            <template v-if="pickerTruncated">
              <div class="pop-note">{{ t('ev.picker.truncated', [PICKER_LIMIT]) }}</div>
              <div class="pop-hint">{{ t('src.picker.searchHint') }}</div>
            </template>
            <div v-else-if="serverFiltered" class="pop-hint">{{ t('src.picker.serverFiltered') }}</div>
            <div class="pop-list">
              <label v-for="v in filteredValues" :key="typeof v + ':' + String(v)" class="pop-item">
                <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                <span :title="String(v)">{{ String(v) }}</span>
              </label>
              <div v-if="!filteredValues.length" class="pop-state">
                {{ pickerValues.length ? t('src.picker.noMatch') : t('ev.picker.empty') }}
              </div>
            </div>
            <div v-if="tooManyValues" class="pop-note">{{ t('ev.picker.max', [MAX_FILTER_VALUES]) }}</div>
            <div class="pop-foot">
              <span v-if="pickerSelected.length" class="pop-count">
                {{ t('src.picker.selected', [pickerSelected.length]) }}
              </span>
              <div class="pop-actions">
                <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
                  {{ t('ev.picker.apply') }}
                </button>
              </div>
            </div>
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
            <input
              v-model="valSearch" v-focus class="pop-search" type="text"
              :placeholder="t('src.picker.searchVals')"
              @keydown.enter.prevent="onValueSearchEnter"
            />
            <div v-if="pickerLoading" class="pop-state">{{ t('ev.loading') }}</div>
            <template v-else>
              <div v-if="pickerError" class="pop-error">{{ t('src.picker.error') }}</div>
              <template v-if="pickerTruncated">
                <div class="pop-note">{{ t('ev.picker.truncated', [PICKER_LIMIT]) }}</div>
                <div class="pop-hint">{{ t('src.picker.searchHint') }}</div>
              </template>
              <div v-else-if="serverFiltered" class="pop-hint">{{ t('src.picker.serverFiltered') }}</div>
              <div class="pop-list">
                <label v-for="v in filteredValues" :key="typeof v + ':' + String(v)" class="pop-item">
                  <input type="checkbox" :checked="isSelected(v)" @change="toggleValue(v)" />
                  <span :title="String(v)">{{ String(v) }}</span>
                </label>
                <div v-if="!filteredValues.length" class="pop-state">
                  {{ pickerValues.length ? t('src.picker.noMatch') : t('ev.picker.empty') }}
                </div>
              </div>
              <div v-if="tooManyValues" class="pop-note">{{ t('ev.picker.max', [MAX_FILTER_VALUES]) }}</div>
              <div class="pop-foot">
                <span v-if="pickerSelected.length" class="pop-count">
                  {{ t('src.picker.selected', [pickerSelected.length]) }}
                </span>
                <div class="pop-actions">
                  <button class="pop-cancel" @click="cancelPicker">{{ t('src.picker.cancel') }}</button>
                  <button class="pop-apply" :disabled="!pickerSelected.length || tooManyValues" @click="applyPicker">
                    {{ t('ev.picker.apply') }}
                  </button>
                </div>
              </div>
            </template>
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
  border-radius: 0; padding: 1px 8px;
}
.ev-reset {
  display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  font-size: var(--fs-xs); color: var(--text-2); border-radius: 0;
  transition: all var(--dur) var(--ease);
}
.ev-reset:hover { background: var(--surface-hover); color: var(--text); }
.ev-reset :deep(.ui-icon) { width: 12px; height: 12px; }

.ev-chips-row { display: flex; flex-wrap: wrap; gap: var(--s-2); }
.ev-chip {
  position: relative; display: inline-flex; align-items: center; gap: 4px;
  max-width: 100%; border: 1px solid var(--border-strong); border-radius: 0;
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
.chip-x { padding: 2px; border-radius: 0; color: var(--text-3); }
.chip-x:hover { color: var(--danger); }
.chip-x :deep(.ui-icon) { width: 11px; height: 11px; }
.ev-chip.add { border-style: dashed; }
.ev-chip.add .chip-main { color: var(--text-2); gap: 4px; padding: 2px 4px; }
.ev-chip.add .chip-main:hover { color: var(--orange); }

/* Popover: aerated, square, token-driven. Wide enough for long values, capped so
   it never dominates the panel; the value/column list scrolls inside. */
.ev-pop {
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
