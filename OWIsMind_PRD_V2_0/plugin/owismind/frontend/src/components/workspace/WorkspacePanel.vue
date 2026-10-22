<script setup>
// Studio (V2) - the floating right-hand card of an answer that built a workspace:
// ONE header row with two zones: on the left, the name + run status with the TWO tabs
// right under them (Dashboard, always first, and Data); on the right, the analysis
// scope the agent published (WorkspaceScope) taking the remaining width, then the
// close button. Then the body and the "where does this data come from" drawer.
// While the run works and no board widget is published yet, the body shows the
// waiting composition (StudioWaiting) instead of an empty board. The plan lives above the prompt
// (PlanCard). All state lives in the workspace store; the Data tab hosts the V1.3
// Evidence panel in its embedded mode and loads it for THIS exchange on first visit.
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'
import BoardGrid from './BoardGrid.vue'
import ProvenanceDrawer from './ProvenanceDrawer.vue'
import DataFocus from './DataFocus.vue'
import WidgetFocus from './WidgetFocus.vue'
import WorkspaceScope from './WorkspaceScope.vue'
import StudioWaiting from './StudioWaiting.vue'
import EvidencePanel from '../evidence/EvidencePanel.vue'
import { dataTabView, resultHasRows } from '../../composables/workspaceModel.js'

const { t } = useI18n()
const ws = useWorkspaceStore()
const evidence = useEvidenceStore()

const entry = computed(() => ws.shown)
const state = computed(() => ws.state)
const running = computed(() => !!(entry.value && entry.value.running))

const statusLabel = computed(() => {
  if (running.value) return t('ws.status.running')
  const s = state.value && state.value.status
  return t('ws.status.' + (s === 'stopped' || s === 'error' ? s : 'done'))
})

// Waiting composition: a live run on the Dashboard tab with no board widget yet (or
// the shown answer still loading during a run). The first widget replaces it; a run
// that ends with nothing falls back to the board's empty state.
const waiting = computed(() => {
  const e = entry.value
  if (!running.value || !e || e.error || ws.activeTab !== 'board') return false
  return !!e.loading || !ws.boardList.length
})
// The plan step running now, read by the waiting line (null: none known).
const liveStep = computed(() => {
  const steps = (state.value && state.value.plan && state.value.plan.steps) || []
  const s = steps.find((x) => x && x.status === 'running' && x.label)
  return s ? String(s.label) : null
})

// The board counts its own widgets (the scope lives in the header).
const tabs = computed(() => {
  const n = ws.boardList.length
  return [
    { key: 'board', label: t('ws.tab.board'), count: n || null },
    { key: 'data', label: t('ws.tab.data'), count: null },
  ]
})

// The Data tab shows the Evidence panel of THIS exchange: (re)load it when the tab is
// entered or when the shown workspace changes while the tab is active. A live run has
// no exchange id until /chat/start answers, and nothing is stored before the run ends.
// With a sql_id focus (a widget's "See the data"), the Evidence view is scoped to
// THAT query (multi-SQL Evidence, /evidence/meta?sql_id=).
// A result carried from an earlier answer (continued Studio) is read on ITS answer:
// the Evidence view then loads for the widget's origin exchange (ws.dataExchangeId),
// which is sealed, so it opens even while this run is live.
function syncEvidence() {
  if (ws.activeTab !== 'data' || !ws.open) return
  const id = ws.dataExchangeId
  if (!id || (running.value && !ws.dataOrigin)) return
  const want = ws.dataSqlId || null
  if (evidence.open && evidence.exchangeId === id && (!want || evidence.requestedSqlId === want)) return
  evidence.openForExchange(id, want ? { sqlId: want } : undefined)
}
watch(() => [ws.activeTab, ws.exchangeId, ws.open, running.value, ws.dataSqlId, ws.dataOrigin], syncEvidence, { immediate: true })
// Leaving the focus ("all the answer's data") returns to the default view of the
// shown answer (also when the focus was a carried result of another answer).
watch(() => [ws.dataSqlId, ws.dataOrigin, ws.exchangeId], ([now, , id], [before, beforeOrigin, idBefore]) => {
  if (now || !before || id !== idBefore || !evidence.open) return
  if (evidence.exchangeId !== (beforeOrigin || id)) return
  // From a carried result: syncEvidence reloads the shown answer's view (sealed run);
  // a live run has no Evidence yet, so the origin's view is simply closed.
  if (beforeOrigin) {
    if (running.value) evidence.close()
  } else if (evidence.requestedSqlId) {
    evidence.openForExchange(id)
  }
})
// The selector inside the Data tab moves the focus along (no reload loop: the store
// already holds the picked query), on the exchange it shows.
watch(() => evidence.requestedSqlId, (sid) => {
  if (sid && ws.dataSqlId && sid !== ws.dataSqlId && evidence.exchangeId === ws.dataExchangeId) ws.openData(sid, null, ws.dataOrigin)
})
// What the Data tab shows (dataTabView): the Studio's own rows of ONE result when the
// server did not scope the Evidence view to the focused query (older backend: no
// meta.sql_id), or when the Evidence view is degraded (e.g. no_matching_dataset) while
// the Studio holds the rows captured during the run; otherwise the Evidence panel.
// A degraded meta only counts when it belongs to THIS exchange.
const dataView = computed(() => {
  const sameExchange = !!ws.dataExchangeId && evidence.exchangeId === ws.dataExchangeId
  const meta = evidence.meta && (sameExchange || evidence.meta.available !== false) ? evidence.meta : null
  // Fallback candidates (no focus) are the shown answer's own results only: a carried
  // widget's sql_id names a query of another exchange.
  const widgets = ((state.value && state.value.widgets) || []).filter((w) => !w.origin)
  return dataTabView({
    focusSqlId: ws.dataSqlId,
    meta,
    loading: evidence.loading,
    activeSqlId: evidence.activeSqlId,
    candidates: widgets.map((w) => w.sql_id).filter(Boolean),
    hasRows: (sid) => {
      const info = ws.sqlInfo(sid, sid === ws.dataSqlId ? ws.dataOrigin : null)
      return !!info && resultHasRows(info.result)
    },
  })
})

// Clicking the Data tab itself shows the whole answer's data (no sql_id focus).
function onTab(key) {
  if (key === 'data') ws.clearDataFocus()
  ws.setTab(key)
}

function onTabKey(e, i) {
  const keys = tabs.value.map((x) => x.key)
  let next = null
  if (e.key === 'ArrowRight') next = keys[(i + 1) % keys.length]
  else if (e.key === 'ArrowLeft') next = keys[(i - 1 + keys.length) % keys.length]
  if (next) {
    e.preventDefault()
    ws.setTab(next)
    const btn = e.currentTarget.parentElement.querySelectorAll('[role="tab"]')[keys.indexOf(next)]
    if (btn) btn.focus()
  }
}
</script>

<template>
  <aside class="ws-panel" :aria-label="t('ws.title')">
    <header class="ws-head">
      <div class="ws-head-row">
        <div class="ws-left">
          <div class="ws-titles">
            <span class="ws-title">{{ t('ws.title') }}</span>
            <span class="ws-sub">
              <span v-if="running" class="ws-live" aria-hidden="true" />
              {{ statusLabel }}
            </span>
          </div>
          <div class="ws-tabs" role="tablist">
            <button
              v-for="(tab, i) in tabs"
              :key="tab.key"
              type="button"
              role="tab"
              class="ws-tab"
              :class="{ active: ws.activeTab === tab.key }"
              :aria-selected="ws.activeTab === tab.key"
              :tabindex="ws.activeTab === tab.key ? 0 : -1"
              @click="onTab(tab.key)"
              @keydown="onTabKey($event, i)"
            >
              <span class="ws-tab-label">{{ tab.label }}</span>
              <span v-if="tab.count != null" class="ws-tab-count mono">{{ tab.count }}</span>
              <span v-if="ws.fresh[tab.key]" class="ws-tab-new">
                <span class="ws-dot" aria-hidden="true" />{{ t('ws.new') }}
              </span>
            </button>
          </div>
        </div>
        <WorkspaceScope v-if="ws.scope && !(entry && entry.loading)" :key="ws.scope.id" class="ws-scope" :widget="ws.scope" />
        <button type="button" class="ws-icon-btn ws-close" :title="t('ws.close')" :aria-label="t('ws.close')" @click="ws.close({ byUser: true })">
          <Icon name="x" />
        </button>
      </div>
    </header>

    <div class="ws-body" :class="{ 'ws-body--data': ws.activeTab === 'data', 'ws-body--wait': waiting }" role="tabpanel">
      <StudioWaiting v-if="waiting" :step="liveStep" />
      <div v-else-if="entry && entry.loading" class="ws-skeleton" :aria-label="t('ws.loading')">
        <span class="sk sk-line" />
        <span class="sk sk-line short" />
        <span class="sk sk-block" />
      </div>
      <div v-else-if="entry && entry.error" class="ws-state">{{ t('ws.error') }}</div>
      <template v-else-if="state">
        <BoardGrid v-if="ws.activeTab === 'board'" :state="state" :running="running" />
        <!-- Data tab: ONE result when opened from a widget (sql_id focus), else the
             exchange-level Evidence view. -->
        <DataFocus
          v-else-if="ws.activeTab === 'data' && dataView.mode === 'focus'"
          :sql-id="dataView.sqlId"
          :unverified="dataView.unverified"
        />
        <EvidencePanel v-else-if="ws.activeTab === 'data'" embedded />
      </template>
    </div>

    <ProvenanceDrawer v-if="ws.drawerSqlId" />
    <!-- Focus level of one widget (teleported above the whole app). -->
    <WidgetFocus v-if="ws.focusWidgetId && ws.activeTab === 'board'" />
  </aside>
</template>

<style scoped>
.ws-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  overflow: hidden;
  background: var(--bg);
  animation: ws-in var(--dur-slow) var(--ease-out) both;
}
@keyframes ws-in {
  from { opacity: 0; transform: translateX(24px); }
  to { opacity: 1; transform: none; }
}
@media (prefers-reduced-motion: reduce) {
  .ws-panel { animation: none; }
}
.ws-head {
  flex: 0 0 auto;
  border-bottom: 1px solid var(--border);
  container-type: inline-size;
}
/* ONE row, two zones. Left: a single column (name + status, the tabs right under
   them, never spreading under the scope). Right: the analysis scope (when published)
   takes the remaining width, centred on the left column, then the close button.
   Without a scope the middle track is simply empty (no extra height). */
.ws-head-row {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr) auto;
  grid-template-areas: 'left scope close';
  align-items: center;
  column-gap: var(--s-5);
  padding: 10px var(--s-3) 10px var(--s-5);
}
.ws-left {
  grid-area: left;
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}
.ws-titles {
  display: flex;
  flex-direction: column;
  gap: 3px;
  min-width: 0;
}
.ws-scope { grid-area: scope; }
.ws-close { grid-area: close; align-self: start; justify-self: end; }
/* Narrow Studio: the scope stacks under the left zone, across the full width. */
@container (max-width: 899px) {
  .ws-head-row {
    grid-template-columns: minmax(0, 1fr) auto;
    grid-template-areas: 'left close' 'scope scope';
    row-gap: var(--s-3);
  }
  .ws-head-row .ws-scope { padding-left: 0; border-left: none; }
}
.ws-title {
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.ws-sub {
  display: flex;
  align-items: center;
  gap: 7px;
  font-size: var(--fs-xs);
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
/* Running state = the one place a pulsing orange square says "work in progress". */
.ws-live {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  background: var(--orange);
  animation: ws-pulse 1.15s ease-in-out infinite;
}
@keyframes ws-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.35; }
}
@media (prefers-reduced-motion: reduce) {
  .ws-live { animation: none; }
}
.ws-icon-btn {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-2);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.ws-icon-btn:hover { background: var(--surface-hover); color: var(--text); }
.ws-icon-btn :deep(.ui-icon) { width: 16px; height: 16px; }
.ws-tabs {
  display: flex;
  gap: 6px;
  overflow-x: auto;
}
.ws-tab {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 30px;
  padding: 0 12px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text-2);
  white-space: nowrap;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.ws-tab:hover { border-color: var(--text); color: var(--text); }
/* Selection = orange signal: orange frame + faint orange fill + ink text. */
.ws-tab.active {
  border-color: var(--orange);
  background: var(--orange-soft-dark);
  color: var(--text);
  font-weight: var(--fw-bold);
}
.ws-tab-count {
  font-size: 11px;
  color: var(--text-3);
  font-weight: var(--fw-regular);
}
.ws-tab-new {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  font-weight: var(--fw-bold);
  color: var(--orange-text);
}
.ws-dot {
  width: 7px;
  height: 7px;
  flex: 0 0 7px;
  background: var(--orange);
}
.ws-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--s-5);
}
/* Waiting composition: a column it fills entirely (StudioWaiting is a size container). */
.ws-body--wait {
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
/* Data tab: the embedded Evidence panel owns its own scroll regions. */
.ws-body--data {
  padding: 0;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.ws-state {
  color: var(--text-2);
  font-size: var(--fs-sm);
}
.ws-skeleton {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
}
.sk {
  display: block;
  background: var(--surface-2);
  border-radius: var(--r-xs);
  animation: ws-sk 1.4s ease-in-out infinite;
}
@keyframes ws-sk { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
.sk-line { height: 14px; width: 70%; }
.sk-line.short { width: 40%; }
.sk-block { height: 220px; }
@media (prefers-reduced-motion: reduce) {
  .sk { animation: none; }
}
</style>
