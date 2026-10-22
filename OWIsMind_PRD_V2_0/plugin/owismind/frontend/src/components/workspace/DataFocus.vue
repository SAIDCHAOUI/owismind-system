<script setup>
// Data tab focused on ONE result (sql_id), opened from a widget or the provenance
// drawer: which widget / step it feeds, the filters read from its SQL, and its rows -
// the FULL result paged from /evidence/result-rows for THAT sql_id (ArtifactTable),
// never the exchange's "latest" query. "All the answer's data" leaves the focus and
// shows the exchange-level Evidence view (chips, source rows, calculation).
//
// `unverified`: the Evidence view of this answer is degraded (its tables match no
// browsable project dataset) but the Studio holds the rows captured during the run.
// Those rows are shown with a one-line note, the technical details stay one click
// away (provenance drawer), and the other captured results of the answer are listed.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { dataFocus, filterParts, resultHasRows } from '../../composables/workspaceModel.js'
import { businessStepArgs } from '../../composables/evidenceProof.js'
import { Icon } from '../ui'
import ArtifactTable from '../evidence/ArtifactTable.vue'

const props = defineProps({
  // The result shown (defaults to the Data tab focus).
  sqlId: { type: String, default: null },
  unverified: { type: Boolean, default: false },
})
const { t } = useI18n()
const ws = useWorkspaceStore()

const sid = computed(() => props.sqlId || ws.dataSqlId)
const widgetId = computed(() => (sid.value === ws.dataSqlId ? ws.dataWidgetId : null))
// The exchange owning the focused result: the origin of a carried widget, else the
// shown answer (a fallback sql_id without focus is always the shown answer's).
const origin = computed(() => (sid.value === ws.dataSqlId ? ws.dataOrigin : null))
const focus = computed(() => dataFocus(ws.state, sid.value, widgetId.value, origin.value))
const info = computed(() => ws.sqlInfo(sid.value, origin.value))
const filters = computed(() =>
  (info.value ? info.value.filters : [])
    .map((f) => filterParts(f, businessStepArgs))
    .filter(Boolean)
    .map((p) => (p.key ? t(p.key, p.args) : p.text)),
)
const title = computed(() => (focus.value && focus.value.widget ? focus.value.widget.title : t('ws.data.result')))
// Unverified view: the answer's OTHER results whose rows the Studio holds (one entry
// per result, named after the first widget showing it).
const others = computed(() => {
  if (!props.unverified) return []
  const self = ws.resultRef({ sql_id: sid.value, origin: origin.value })
  const seen = new Set(self ? [self.key] : [])
  const out = []
  for (const w of (ws.state && ws.state.widgets) || []) {
    const r = ws.resultRef(w)
    if (!r || seen.has(r.key)) continue
    seen.add(r.key)
    const other = ws.sqlInfo(r.sqlId, r.origin)
    if (other && resultHasRows(other.result)) out.push({ key: r.key, sqlId: r.sqlId, origin: r.origin, widgetId: w.id, label: w.title })
  }
  return out
})
</script>

<template>
  <div class="focus">
    <header class="f-head">
      <div class="f-titles">
        <span class="f-eyebrow">{{ t('ws.data.focus') }}</span>
        <span class="f-title">{{ title }}</span>
      </div>
      <button v-if="ws.dataSqlId" type="button" class="f-all" @click="ws.clearDataFocus()">
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
        :exchange-id="info.exchangeId || ''"
        :sql-id="sid || ''"
      />
      <p v-else class="f-note">{{ t('ws.data.no_rows') }}</p>
      <p v-if="unverified" class="f-unverified">
        {{ t('ws.data.unverified') }}
        <button type="button" class="f-link" @click="ws.openProvenance(sid, widgetId || (focus && focus.widget && focus.widget.id), origin)">{{ t('ws.prov.tech') }}</button>
      </p>
    </section>

    <section v-if="others.length" class="f-sec">
      <div class="f-label">{{ t('ws.data.others') }}</div>
      <div class="chips">
        <button v-for="o in others" :key="o.key" type="button" class="chip chip-btn" @click="ws.openData(o.sqlId, o.widgetId, o.origin)">{{ o.label }}</button>
      </div>
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
.chip-btn { color: var(--text-2); transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease); }
.chip-btn:hover { border-color: var(--text); color: var(--text); }
/* Unverified rows: one quiet line under the table, the technical details as a link. */
.f-unverified {
  margin: var(--s-3) 0 0;
  font-size: var(--fs-xs);
  color: var(--text-2);
  line-height: var(--lh-text);
}
.f-link {
  margin-left: 4px;
  font-size: inherit;
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 3px;
}
.f-link:hover { color: var(--text); text-decoration-color: var(--text); }
</style>
