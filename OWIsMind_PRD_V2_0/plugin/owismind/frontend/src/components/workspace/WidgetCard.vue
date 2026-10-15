<script setup>
// One dashboard widget: a common frame (title, the agent's comment, ONE plain
// "where does this data come from?" link) around the V1.3 renderers reused as they
// are (ArtifactChart / ArtifactTable / ArtifactKpi in their `bare` mode) or a
// markdown text block. No identifier, step number or kind label is shown. Every
// data widget is bound to ITS OWN sql_id: an orphan binding shows an honest empty
// state, never the rows of another query.
import { computed, defineAsyncComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { chartSpecForArtifact } from '../../composables/workspaceModel.js'
import ArtifactTable from '../evidence/ArtifactTable.vue'
import ArtifactKpi from '../evidence/ArtifactKpi.vue'
import WidgetText from './WidgetText.vue'
// Lazy on purpose: chart.js is the heaviest dependency (same split as EvidencePanel).
const ArtifactChart = defineAsyncComponent(() => import('../evidence/ArtifactChart.vue'))

const props = defineProps({
  widget: { type: Object, required: true },
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
})
const { t } = useI18n()
const ws = useWorkspaceStore()

const render = computed(() => ws.widgetData(props.widget))
const isData = computed(() => props.widget.kind !== 'text')
// Rows for this sql_id not available yet while the run is live or its stored
// document is loading: a waiting state (not an empty state - the figures are on their
// way). The card fills as soon as rows reach the store from any source.
const waiting = computed(() => isData.value && !render.value.orphan && !render.value.result && !render.value.data && render.value.pending)
const chartSpec = computed(() => chartSpecForArtifact(props.widget.chart))
</script>

<template>
  <article class="widget" :class="['k-' + widget.kind, { orphan: render.orphan }]">
    <header class="w-head">
      <h3 class="w-title">{{ widget.title }}</h3>
      <p v-if="widget.comment" class="w-comment">{{ widget.comment }}</p>
    </header>

    <div class="w-body">
      <p v-if="render.orphan" class="w-orphan">{{ t('ws.widget.orphan') }}</p>
      <div v-else-if="waiting" class="w-wait">
        <span class="w-wait-dot" aria-hidden="true" />{{ t('ws.widget.waiting') }}
      </div>
      <ArtifactChart
        v-else-if="widget.kind === 'chart'"
        :chart="chartSpec"
        :data="render.data"
        :title="widget.title"
        bare
      />
      <ArtifactKpi
        v-else-if="widget.kind === 'kpi'"
        :data="render.data"
        :title="widget.title"
        :unit="(widget.kpi && widget.kpi.unit) || ''"
        bare
      />
      <ArtifactTable
        v-else-if="widget.kind === 'table'"
        :result="render.result"
        :exchange-id="ws.exchangeId ? String(ws.exchangeId) : ''"
        :sql-id="widget.sql_id || ''"
      />
      <WidgetText v-else :text="widget.text || ''" />
    </div>

    <!-- ONE plain link: where the figures come from (technical details stay inside). -->
    <footer v-if="isData && widget.sql_id && !render.orphan" class="w-foot">
      <button
        type="button"
        class="w-prov"
        :class="{ active: ws.drawerSqlId === widget.sql_id && ws.drawerWidgetId === widget.id }"
        @click="ws.openProvenance(widget.sql_id, widget.id)"
      >{{ t('ws.prov.where') }}</button>
    </footer>
  </article>
</template>

<style scoped>
.widget {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-width: 0;
  padding: var(--s-4);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  background: var(--bg);
  animation: w-in var(--dur) var(--ease-out) both;
}
@keyframes w-in { from { opacity: 0; transform: translateY(6px); } }
@media (prefers-reduced-motion: reduce) { .widget { animation: none; } }
.w-head { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
.w-title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.w-comment {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.w-body { min-width: 0; }
.w-orphan {
  margin: 0;
  padding: var(--s-4);
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: var(--lh-text);
}
.w-wait {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 80px;
  font-size: var(--fs-sm);
  color: var(--text-3);
}
.w-wait-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  background: var(--orange);
  animation: w-pulse 1.15s ease-in-out infinite;
}
@keyframes w-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .w-wait-dot { animation: none; } }
.w-foot { border-top: 1px solid var(--border); padding-top: var(--s-3); }
.w-prov {
  font-size: var(--fs-sm);
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 3px;
  transition: color var(--dur) var(--ease);
}
.w-prov:hover { color: var(--text); text-decoration-color: var(--text); }
.w-prov.active { color: var(--orange-text); text-decoration-color: var(--orange); }
</style>
