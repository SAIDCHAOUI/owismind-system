<script setup>
// Workspace summary card, under an answer that built a workspace: the mission, the
// plan progress, the widget list and the "Open the workspace" button that restores
// the right column exactly as generated. A stored answer whose document is not in
// memory yet (conversation reloaded: only `has_workspace` is known) shows the compact
// form - the button fetches the document on demand, never N documents up front.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { planProgress, hasWorkspaceContent } from '../../composables/workspaceModel.js'
import { Icon } from '../ui'

const props = defineProps({
  exchange: { type: Object, required: true },
})
const { t } = useI18n()
const ws = useWorkspaceStore()
const evidence = useEvidenceStore()

const entry = computed(() => ws.entryFor(props.exchange.id, props.exchange.uid))
const state = computed(() => (entry.value && hasWorkspaceContent(entry.value.state) ? entry.value.state : null))
const progress = computed(() => planProgress(state.value))
const running = computed(() => !!(entry.value && entry.value.running))
const shown = computed(() => ws.open && !!entry.value && ws.shown === entry.value)
const MAX_THUMBS = 4
const thumbs = computed(() => (state.value ? state.value.widgets.slice(0, MAX_THUMBS) : []))
const moreThumbs = computed(() => (state.value ? Math.max(0, state.value.widgets.length - MAX_THUMBS) : 0))
const KIND_ICON = { chart: 'chart', table: 'grid', kpi: 'trendUp', text: 'document' }

async function openWorkspace(tab) {
  const id = props.exchange.id
  if (!id) return
  const ok = await ws.openForExchange(id, { uid: props.exchange.uid, tab })
  // No stored workspace after all (V1.3 answer): the proof panel is the fallback.
  if (!ok && !ws.open) evidence.openForExchange(id)
}
</script>

<template>
  <section class="ws-card" :class="{ shown, live: running }">
    <div class="ws-card-head">
      <span class="ws-card-mark" aria-hidden="true"><Icon name="layers" /></span>
      <span class="ws-card-title">{{ t('ws.title') }}</span>
      <span v-if="running" class="ws-card-status"><span class="dot" aria-hidden="true" />{{ t('ws.status.running') }}</span>
    </div>

    <template v-if="state">
      <p v-if="state.plan && state.plan.mission" class="ws-card-mission">{{ state.plan.mission }}</p>
      <div class="ws-card-stats mono">
        <span v-if="progress.total">{{ t('ws.summary.steps', [progress.done, progress.total]) }}</span>
        <span v-if="state.widgets.length">{{ t('ws.summary.widgets', [state.widgets.length]) }}</span>
        <span v-if="state.notes.length">{{ t('ws.summary.notes', [state.notes.length]) }}</span>
      </div>
      <ul v-if="thumbs.length" class="ws-card-thumbs">
        <li v-for="w in thumbs" :key="w.id">
          <button type="button" class="thumb" :disabled="!exchange.id" @click="openWorkspace('board')">
            <Icon :name="KIND_ICON[w.kind] || 'chart'" />
            <span class="thumb-title">{{ w.title }}</span>
          </button>
        </li>
        <li v-if="moreThumbs" class="thumb-more mono">+{{ moreThumbs }}</li>
      </ul>
    </template>
    <p v-else class="ws-card-mission muted">{{ t('ws.summary.stored') }}</p>

    <div class="ws-card-foot">
      <button
        type="button"
        class="ws-open"
        :class="{ on: shown }"
        :disabled="!exchange.id"
        @click="openWorkspace()"
      >
        <Icon :name="shown ? 'check' : 'layers'" />{{ shown ? t('ws.summary.shown') : t('ws.summary.open') }}
      </button>
    </div>
  </section>
</template>

<style scoped>
.ws-card {
  margin-top: var(--s-3);
  padding: var(--s-4);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  background: var(--bg);
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  max-width: 640px;
}
/* The card whose workspace is on screen takes the orange selection signal. */
.ws-card.shown { border-color: var(--orange); }
.ws-card-head { display: flex; align-items: center; gap: 8px; }
.ws-card-mark { display: grid; place-items: center; color: var(--text-2); }
.ws-card-mark :deep(.ui-icon) { width: 15px; height: 15px; }
.ws-card-title { font-size: var(--fs-sm); font-weight: var(--fw-bold); }
.ws-card-status {
  margin-left: auto;
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  color: var(--orange-text);
  font-weight: var(--fw-bold);
}
.dot {
  width: 7px;
  height: 7px;
  background: var(--orange);
  animation: card-pulse 1.15s ease-in-out infinite;
}
@keyframes card-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .dot { animation: none; } }
.ws-card-mission {
  margin: 0;
  font-size: var(--fs-sm);
  line-height: var(--lh-text);
  color: var(--text);
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.ws-card-mission.muted { color: var(--text-2); }
.ws-card-stats {
  display: flex;
  flex-wrap: wrap;
  gap: var(--s-4);
  font-size: 11px;
  color: var(--text-2);
}
.ws-card-thumbs {
  margin: 0;
  padding: 0;
  list-style: none;
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
  gap: 6px;
}
.thumb {
  width: 100%;
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--surface);
  font-size: var(--fs-xs);
  color: var(--text);
  text-align: left;
  transition: border-color var(--dur) var(--ease);
}
.thumb:hover:not(:disabled) { border-color: var(--text); }
.thumb :deep(.ui-icon) { width: 14px; height: 14px; flex: 0 0 14px; color: var(--text-3); }
.thumb-title { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.thumb-more { display: flex; align-items: center; font-size: 11px; color: var(--text-3); padding: 0 6px; }
.ws-card-foot { display: flex; }
/* Primary action of the card = orange fill, black ink; once shown it settles to an
   outlined "shown on the right" state. */
.ws-open {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 14px;
  border-radius: var(--r-btn);
  background: var(--orange);
  color: var(--on-orange);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  transition: background var(--dur) var(--ease);
}
.ws-open:hover:not(:disabled) { background: var(--orange-deep); }
.ws-open:disabled { opacity: 0.5; cursor: default; }
.ws-open.on {
  background: transparent;
  color: var(--text);
  border: 1px solid var(--orange);
}
.ws-open :deep(.ui-icon) { width: 15px; height: 15px; }
</style>
