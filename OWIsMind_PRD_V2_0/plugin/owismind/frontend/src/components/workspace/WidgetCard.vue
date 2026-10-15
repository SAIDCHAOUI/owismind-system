<script setup>
// One dashboard widget: a common frame (kind, step, title, the agent's comment, the
// provenance button) around the V1.3 renderers reused as they are (ArtifactChart /
// ArtifactTable / ArtifactKpi in their `bare` mode) or a markdown text block. Every
// data widget is bound to ITS OWN sql_id: an orphan binding shows an honest empty
// state, never the rows of another query.
import { computed, defineAsyncComponent } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { chartSpecForArtifact, stepFor } from '../../composables/workspaceModel.js'
import { Icon } from '../ui'
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
const info = computed(() => (props.widget.sql_id ? ws.sqlInfo(props.widget.sql_id) : null))
const step = computed(() => (props.widget.step_id ? stepFor(props.state, props.widget.step_id) : null))
const stepRemoved = computed(() => !!props.widget.step_id && !step.value)
const isData = computed(() => props.widget.kind !== 'text')
// Rows for this sql_id not available yet while the run is live or its stored
// document is loading: a waiting state (not an empty state - the figures are on their
// way). The card fills as soon as rows reach the store from any source.
const waiting = computed(() => isData.value && !render.value.orphan && !render.value.result && !render.value.data && render.value.pending)
const chartSpec = computed(() => chartSpecForArtifact(props.widget.chart))
const provLine = computed(() => {
  const p = info.value && info.value.provenance
  const parts = []
  if (p && p.agent_key) parts.push(String(p.agent_key).replace(/_/g, ' '))
  const rc = info.value && info.value.rowCount
  if (typeof rc === 'number') parts.push(t('ws.prov.rows') + ' ' + rc)
  return parts.join(' · ')
})
</script>

<template>
  <article class="widget" :class="['k-' + widget.kind, { orphan: render.orphan }]">
    <header class="w-head">
      <div class="w-meta">
        <span class="w-kind mono">{{ t('ws.kind.' + widget.kind) }}</span>
        <span v-if="step" class="w-step">{{ t('ws.step.label', [step.index]) }}</span>
        <span v-else-if="stepRemoved" class="w-step">{{ t('ws.widget.removed_step') }}</span>
      </div>
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

    <footer v-if="isData && widget.sql_id && !render.orphan" class="w-foot">
      <button
        type="button"
        class="w-prov"
        :class="{ active: ws.drawerSqlId === widget.sql_id && ws.drawerWidgetId === widget.id }"
        :title="t('ws.widget.provenance_of', [widget.title])"
        @click="ws.openProvenance(widget.sql_id, widget.id)"
      >
        <Icon name="shield" />
        <span>{{ t('ws.widget.provenance') }}</span>
        <span v-if="provLine" class="w-prov-meta">{{ provLine }}</span>
        <span class="w-prov-id mono">{{ widget.sql_id }}</span>
      </button>
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
.w-meta { display: flex; align-items: center; gap: 8px; }
.w-kind { font-size: 11px; color: var(--text-3); }
.w-step {
  font-size: 11px;
  color: var(--text-2);
  padding: 1px 6px;
  border: 1px solid var(--border);
  border-radius: var(--r-xs);
}
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
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: 100%;
  font-size: var(--fs-xs);
  color: var(--text-2);
  transition: color var(--dur) var(--ease);
}
.w-prov:hover, .w-prov.active { color: var(--text); }
.w-prov.active span:first-of-type { color: var(--orange-text); font-weight: var(--fw-bold); }
.w-prov :deep(.ui-icon) { width: 14px; height: 14px; flex: 0 0 14px; }
.w-prov-meta {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--text-3);
}
.w-prov-id { margin-left: auto; font-size: 11px; color: var(--text-3); }
</style>
