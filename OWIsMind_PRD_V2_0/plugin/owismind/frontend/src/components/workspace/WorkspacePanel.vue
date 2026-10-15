<script setup>
// Studio (V2) - the floating right-hand card of an answer that built a workspace:
// header (name + run status), TWO tabs (Dashboard, always first, and Data) and the
// "where does this data come from" drawer. The plan lives above the prompt
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
import EvidencePanel from '../evidence/EvidencePanel.vue'

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

const tabs = computed(() => {
  const s = state.value
  return [
    { key: 'board', label: t('ws.tab.board'), count: s && s.widgets.length ? s.widgets.length : null },
    { key: 'data', label: t('ws.tab.data'), count: null },
  ]
})

// The Data tab shows the Evidence panel of THIS exchange: (re)load it when the tab is
// entered or when the shown workspace changes while the tab is active. A live run has
// no exchange id until /chat/start answers, and nothing is stored before the run ends.
// With a sql_id focus (a widget's "See the data"), the Evidence view is scoped to
// THAT query (multi-SQL Evidence, /evidence/meta?sql_id=).
function syncEvidence() {
  if (ws.activeTab !== 'data' || !ws.open) return
  const id = ws.exchangeId
  if (!id || running.value) return
  const want = ws.dataSqlId || null
  if (evidence.open && evidence.exchangeId === id && (!want || evidence.requestedSqlId === want)) return
  evidence.openForExchange(id, want ? { sqlId: want } : undefined)
}
watch(() => [ws.activeTab, ws.exchangeId, ws.open, running.value, ws.dataSqlId], syncEvidence, { immediate: true })
// Leaving the focus ("all the answer's data") returns to the default view.
watch(() => ws.dataSqlId, (now, before) => {
  if (!now && before && evidence.open && evidence.exchangeId === ws.exchangeId && evidence.requestedSqlId) {
    evidence.openForExchange(ws.exchangeId)
  }
})
// The selector inside the Data tab moves the focus along (no reload loop: the store
// already holds the picked query).
watch(() => evidence.requestedSqlId, (sid) => {
  if (sid && ws.dataSqlId && sid !== ws.dataSqlId && evidence.exchangeId === ws.exchangeId) ws.openData(sid)
})
// The server did not scope the view to the focused query (older backend: no
// meta.sql_id): the exact rows of THAT query are shown instead (never another one's).
const unscopedFocus = computed(() =>
  !!ws.dataSqlId && !!evidence.meta && !evidence.loading && evidence.activeSqlId !== ws.dataSqlId,
)

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
        <div class="ws-titles">
          <span class="ws-title">{{ t('ws.title') }}</span>
          <span class="ws-sub">
            <span v-if="running" class="ws-live" aria-hidden="true" />
            {{ statusLabel }}
          </span>
        </div>
        <button type="button" class="ws-icon-btn" :title="t('ws.close')" :aria-label="t('ws.close')" @click="ws.close()">
          <Icon name="x" />
        </button>
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
    </header>

    <div class="ws-body" :class="{ 'ws-body--data': ws.activeTab === 'data' }" role="tabpanel">
      <div v-if="entry && entry.loading" class="ws-skeleton" :aria-label="t('ws.loading')">
        <span class="sk sk-line" />
        <span class="sk sk-line short" />
        <span class="sk sk-block" />
      </div>
      <div v-else-if="entry && entry.error" class="ws-state">{{ t('ws.error') }}</div>
      <template v-else-if="state">
        <BoardGrid v-if="ws.activeTab === 'board'" :state="state" :running="running" />
        <!-- Data tab: ONE result when opened from a widget (sql_id focus), else the
             exchange-level Evidence view. -->
        <DataFocus v-else-if="ws.activeTab === 'data' && unscopedFocus" />
        <EvidencePanel v-else-if="ws.activeTab === 'data'" embedded />
      </template>
    </div>

    <ProvenanceDrawer v-if="ws.drawerSqlId" />
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
}
/* Same height as the chat top bar (56px) so both hairlines meet as one line. */
.ws-head-row {
  height: 56px;
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: 0 var(--s-3) 0 var(--s-5);
}
.ws-titles {
  display: flex;
  flex-direction: column;
  gap: 3px;
  flex: 1 1 auto;
  min-width: 0;
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
  padding: 10px var(--s-4);
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
