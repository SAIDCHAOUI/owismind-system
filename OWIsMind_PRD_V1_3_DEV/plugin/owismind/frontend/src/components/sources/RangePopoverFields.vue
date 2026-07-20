<script setup>
// Shared temporal-range fields for a filter popover - two 'YYYY-MM' month inputs
// (From / To) plus a one-click full-year fill. Used by BOTH the Source Data explorer
// chips (SourceChips) and the Evidence "Source data" chips (EvidenceChips) so the
// range-picking behaviour is ONE code path. The host owns the popover shell (the
// Apply / Cancel foot + the apply -> BETWEEN chip logic); this component only renders
// the fields and emits From / To changes (including the full-year fill, which sets
// From = YYYY-01 and To = YYYY-12). Charter: flat, square, 1px borders, orange focus.
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'

const props = defineProps({
  from: { type: String, default: '' }, // 'YYYY-MM'
  to: { type: String, default: '' }, // 'YYYY-MM'
  // Years present in the column's distinct values (ascending). Empty -> the full-year
  // control degrades to a free 4-digit input.
  yearOptions: { type: Array, default: () => [] },
})
const emit = defineEmits(['update:from', 'update:to'])
const { t } = useI18n()

// Autofocus the From field on open (the popover mounts this component on open, so a
// plain `autofocus` attribute would not re-fire on the next open).
const vFocus = { mounted: (el) => el.focus() }

// Typed 4-digit year fallback (used only when yearOptions is empty).
const typedYear = ref('')

function onFrom(e) {
  emit('update:from', e.target.value)
}
function onTo(e) {
  emit('update:to', e.target.value)
}
// Fill BOTH month fields from a full year in one action (From = YYYY-01, To = YYYY-12).
// The user then confirms with the host's apply button.
function applyFullYear(year) {
  const y = String(year == null ? '' : year).trim()
  if (!/^\d{4}$/.test(y)) return
  emit('update:from', y + '-01')
  emit('update:to', y + '-12')
}
function onYearSelect(e) {
  applyFullYear(e.target.value)
  e.target.value = '' // the select is a one-shot fill, not a persistent choice
}
function onYearInput(e) {
  typedYear.value = e.target.value
  if (/^\d{4}$/.test(typedYear.value.trim())) applyFullYear(typedYear.value)
}
</script>

<template>
  <div class="pop-range-fields">
    <div class="pop-range-months">
      <label class="pop-range-field">
        <span class="pop-range-lbl">{{ t('src.range.from') }}</span>
        <input
          :value="from" v-focus type="month" class="pop-range-input"
          :placeholder="t('src.range.fmt')" pattern="[0-9]{4}-[0-9]{2}" @input="onFrom"
        />
      </label>
      <label class="pop-range-field">
        <span class="pop-range-lbl">{{ t('src.range.to') }}</span>
        <input
          :value="to" type="month" class="pop-range-input"
          :placeholder="t('src.range.fmt')" pattern="[0-9]{4}-[0-9]{2}" @input="onTo"
        />
      </label>
    </div>
    <label class="pop-range-field pop-range-year">
      <span class="pop-range-lbl">{{ t('src.range.year') }}</span>
      <select v-if="yearOptions.length" class="pop-range-input" @change="onYearSelect">
        <option value="">{{ t('src.range.year_choose') }}</option>
        <option v-for="y in yearOptions" :key="y" :value="y">{{ y }}</option>
      </select>
      <input
        v-else :value="typedYear" type="text" inputmode="numeric" maxlength="4"
        class="pop-range-input" :placeholder="t('src.range.year_ph')" @input="onYearInput"
      />
    </label>
  </div>
</template>

<style scoped>
/* From / To month fields + a one-click full-year fill. Flat, square, 1px border,
   orange border on focus (charter). */
.pop-range-fields { display: flex; flex-direction: column; gap: var(--s-3); }
.pop-range-months { display: flex; gap: var(--s-2); }
.pop-range-field { display: flex; flex-direction: column; gap: 4px; min-width: 0; flex: 1; }
.pop-range-lbl {
  font-size: 11px; color: var(--text-2); text-transform: uppercase;
  letter-spacing: 0.06em; font-weight: var(--fw-heavy);
}
.pop-range-input {
  width: 100%; padding: 6px 10px; border: 1px solid var(--border); border-radius: 0;
  background: var(--bg); color: var(--text); font-size: var(--fs-sm);
}
.pop-range-input:focus { outline: none; border-color: var(--orange); }
.pop-range-input::placeholder { color: var(--text-3); }
.pop-range-year { flex: none; }
</style>
