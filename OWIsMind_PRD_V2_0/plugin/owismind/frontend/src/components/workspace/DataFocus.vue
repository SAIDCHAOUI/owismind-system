<script setup>
// Data tab focused on ONE result (sql_id), opened from a widget or the provenance
// drawer: which widget / step it feeds, the filters read from its SQL, and its rows -
// the FULL result paged from /evidence/result-rows for THAT sql_id (ArtifactTable),
// never the exchange's "latest" query. "All the answer's data" leaves the focus and
// shows the exchange-level Evidence view (chips, source rows, calculation).
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { dataFocus, filterParts } from '../../composables/workspaceModel.js'
import { businessStepArgs } from '../../composables/evidenceProof.js'
import { Icon } from '../ui'
import ArtifactTable from '../evidence/ArtifactTable.vue'

const { t } = useI18n()
const ws = useWorkspaceStore()

const focus = computed(() => dataFocus(ws.state, ws.dataSqlId, ws.dataWidgetId))
const info = computed(() => ws.sqlInfo(ws.dataSqlId))
const filters = computed(() =>
  (info.value ? info.value.filters : [])
    .map((f) => filterParts(f, businessStepArgs))
    .filter(Boolean)
    .map((p) => (p.key ? t(p.key, p.args) : p.text)),
)
const title = computed(() => (focus.value && focus.value.widget ? focus.value.widget.title : t('ws.data.result')))
</script>

<template>
  <div class="focus">
    <header class="f-head">
      <div class="f-titles">
        <span class="f-eyebrow">{{ t('ws.data.focus') }}</span>
        <span class="f-title">{{ title }}</span>
      </div>
      <button type="button" class="f-all" @click="ws.clearDataFocus()">
        <Icon name="database" />{{ t('ws.data.all') }}
      </button>
    </header>

    <section class="f-sec">
      <div class="f-label">{{ t('ws.prov.filters') }}</div>
      <div v-if="filters.length" class="chips">
        <span v-for="(f, i) in filters" :key="i" class="chip">{{ f }}</span>
      </div>
      <p v-else class="f-note">{{ t('ws.prov.no_filter') }}</p>
    </section>

    <section class="f-sec f-rows">
      <div class="f-label">{{ t('ws.prov.result') }}</div>
      <ArtifactTable
        v-if="info && info.result"
        :result="info.result"
        :exchange-id="ws.exchangeId ? String(ws.exchangeId) : ''"
        :sql-id="ws.dataSqlId || ''"
      />
      <p v-else class="f-note">{{ t('ws.data.no_rows') }}</p>
    </section>
  </div>
</template>

<style scoped>
.focus {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--s-5);
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.f-head { display: flex; align-items: flex-start; gap: var(--s-3); }
.f-titles { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.f-eyebrow { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--orange-text); }
.f-title { font-size: var(--fs-base); font-weight: var(--fw-bold); line-height: var(--lh-text); }
.f-meta { font-size: 11px; color: var(--text-3); }
.f-all {
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  color: var(--text-2);
  white-space: nowrap;
}
.f-all:hover { border-color: var(--text); color: var(--text); }
.f-all :deep(.ui-icon) { width: 13px; height: 13px; }
.f-sec { border-top: 1px solid var(--border-strong); padding-top: var(--s-3); }
.f-label { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); padding-bottom: var(--s-2); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; }
.chip {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.f-note { margin: 0; font-size: var(--fs-sm); color: var(--text-3); }
</style>
