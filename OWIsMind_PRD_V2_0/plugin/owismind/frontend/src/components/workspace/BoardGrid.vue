<script setup>
// Dashboard tab - every widget the agent published, KPI cards in their own row, then
// the other widgets in a responsive grid (one column on a narrow panel, two beyond
// 900px, via a container query on the panel width, not the viewport).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { boardLayout } from '../../composables/workspaceModel.js'
import WidgetCard from './WidgetCard.vue'

const props = defineProps({
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
})
const { t } = useI18n()
const layout = computed(() => boardLayout(props.state))
const empty = computed(() => !props.state.widgets.length)
</script>

<template>
  <div class="board">
    <div v-if="empty" class="empty">
      <div class="empty-t">{{ t('ws.board.empty_t') }}</div>
      <p class="empty-b">{{ t('ws.board.empty_b') }}</p>
    </div>
    <template v-else>
      <div v-if="layout.kpis.length" class="kpi-row">
        <WidgetCard v-for="w in layout.kpis" :key="w.id" :widget="w" :state="state" :running="running" />
      </div>
      <div v-if="layout.others.length" class="grid">
        <WidgetCard
          v-for="w in layout.others"
          :key="w.id"
          :widget="w"
          :state="state"
          :running="running"
          :class="{ wide: w.kind === 'table' }"
        />
      </div>
    </template>
  </div>
</template>

<style scoped>
.board {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.kpi-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: var(--s-3);
}
.grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr);
  gap: var(--s-4);
}
@container (min-width: 900px) {
  .grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  /* A table needs the width: it spans the whole row. */
  .grid > .wide { grid-column: 1 / -1; }
}
.empty { max-width: 440px; padding: var(--s-6) 0; }
.empty-t { font-size: var(--fs-base); font-weight: var(--fw-bold); padding-bottom: 8px; }
.empty-b { margin: 0; font-size: var(--fs-sm); color: var(--text-2); line-height: var(--lh-text); }
</style>
