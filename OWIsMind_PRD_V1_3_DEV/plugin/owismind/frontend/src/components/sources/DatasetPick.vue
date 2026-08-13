<script setup>
// Shared dataset dropdown - the "DATASET [db icon] <select>" pill of the explorer top
// row, extracted so the standalone Source panel and the Evidence "Source data" tab
// render the EXACT same control (one structure to maintain, user ask 2026-08-13).
// Purely presentational: string-keyed options in, the picked key out; each host maps
// its own entries (source ids / detected tables) to and from the keys.
//
// Native select in a pill (the workspace grouping idiom): a native list can never be
// clipped by a scrolling pane, reads with the OS the user knows, and scales to any
// number of datasets. Neutral ink: the control always SHOWS the active dataset, so a
// permanent orange would break the rare-accent rule.
import { useI18n } from 'vue-i18n'
import { Icon } from '../ui'

defineProps({
  // [{ key: string, label: string }] - the datasets on offer, in display order.
  options: { type: Array, default: () => [] },
  // Key of the active option ('' when none).
  value: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
})
const emit = defineEmits(['change'])
const { t } = useI18n()

function onChange(e) {
  emit('change', e.target.value)
}
</script>

<template>
  <label class="ds-pick" :title="t('src.dataset_label')">
    <span class="ds-pick-label">{{ t('src.dataset_label') }}</span>
    <Icon name="database" />
    <select
      class="ds-pick-select"
      :aria-label="t('src.dataset_label')"
      :value="value"
      :disabled="disabled"
      @change="onChange"
    >
      <option v-for="o in options" :key="o.key" :value="o.key">{{ o.label }}</option>
    </select>
  </label>
</template>

<style scoped>
/* Same 40px height as the search box and the view switch: the whole top row reads as
   ONE aligned line of controls (user ask 2026-08-13). */
.ds-pick {
  display: inline-flex; align-items: center; gap: 8px; flex: none; min-width: 0;
  height: 40px; box-sizing: border-box; padding: 0 8px 0 12px;
  border: 1px solid var(--src-chip-border, var(--border)); border-radius: var(--r-pill);
  background: var(--src-chip-bg, var(--surface));
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ds-pick:hover, .ds-pick:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }
.ds-pick :deep(.ui-icon) { width: 13px; height: 13px; color: var(--text-3); flex: none; }
/* Micro-label recipe (charte): caps, 11px, heavy, wide tracking, --text-2. */
.ds-pick-label {
  font-size: 11px; color: var(--text-2); font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow); flex: none;
}
.ds-pick-select {
  min-width: 0; max-width: 240px; padding: 6px 2px; cursor: pointer;
  border: none; background: transparent; color: var(--text); font-size: var(--fs-sm);
}
.ds-pick-select:focus { outline: none; }
.ds-pick-select:disabled { opacity: 0.5; cursor: not-allowed; }
@media (prefers-reduced-motion: reduce) { .ds-pick { transition: none; } }
</style>
