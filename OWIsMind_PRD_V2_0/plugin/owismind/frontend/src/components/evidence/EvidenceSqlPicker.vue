<script setup>
// Multi-SQL selector (V2.0): one answer can rely on several results. Each one is
// named in plain words (the chart / table it feeds, else its plan step) with its row
// count - never an identifier or a query number. Picking one switches the WHOLE Data
// view to that result. Shown only when the answer holds two results or more.
import { useI18n } from 'vue-i18n'
import { resultLabel } from '../../composables/workspaceModel.js'

defineProps({
  // sqlChoices() output.
  choices: { type: Array, required: true },
  busy: { type: Boolean, default: false },
})
const emit = defineEmits(['select'])
const { t } = useI18n()
</script>

<template>
  <section class="sqlp" :aria-label="t('ev.sqlpick.title')">
    <div class="sqlp-head">{{ t('ev.sqlpick.title') }}</div>
    <div class="sqlp-list" role="listbox">
      <button
        v-for="c in choices"
        :key="c.sqlId"
        type="button"
        role="option"
        class="sqlp-item"
        :class="{ active: c.active, failed: !c.success }"
        :aria-selected="c.active"
        :disabled="busy"
        @click="!c.active && emit('select', c.sqlId)"
      >
        <span class="sqlp-name">{{ resultLabel(c) || t('ev.sqlpick.result', [c.n]) }}</span>
        <span class="sqlp-meta">
          <template v-if="!c.success">{{ t('ws.prov.failed') }}</template>
          <template v-else-if="c.rowCount != null">{{ t('ev.sqlpick.rows', [c.rowCount]) }}</template>
        </span>
      </button>
    </div>
  </section>
</template>

<style scoped>
.sqlp {
  flex: none;
  padding: var(--s-3) var(--s-5);
  border-bottom: 1px solid var(--border);
}
.sqlp-head { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); padding-bottom: var(--s-2); }
.sqlp-list { display: flex; gap: 6px; overflow-x: auto; padding-bottom: 2px; }
.sqlp-item {
  flex: 0 0 auto;
  max-width: 260px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  padding: 8px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg);
  text-align: left;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.sqlp-item:hover:not(:disabled) { border-color: var(--text); }
/* Selection = the orange signal: orange frame + faint orange fill. */
.sqlp-item.active { border-color: var(--orange); background: var(--orange-soft-dark); }
.sqlp-item:disabled { cursor: progress; }
.sqlp-name {
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sqlp-meta { font-size: var(--fs-xs); color: var(--text-2); white-space: nowrap; }
.sqlp-item.failed .sqlp-meta { color: var(--danger); }
</style>
