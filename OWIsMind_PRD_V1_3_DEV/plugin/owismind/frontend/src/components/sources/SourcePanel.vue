<script setup>
// Standalone Source Data Explorer panel - the RIGHT column shown BEFORE a conversation
// starts (opened from the empty-screen CTA). A thin host: a header (title + agent
// label + close) wrapping the store-driven SourceExplorer. Mutual exclusion with the
// Evidence panel lives in AppLayout; this component only renders the sources surface.
import { computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { useSessionStore } from '../../stores/session.js'
import { Icon } from '../ui'
import SourceExplorer from './SourceExplorer.vue'

const { t } = useI18n()
const sources = useSourcesStore()
const session = useSessionStore()

const agentLabel = computed(() => {
  const a = session.agents.find((x) => x.key === sources.agentKey)
  return (a && a.label) || ''
})

// The selected agent can change while the panel is open (the user picks another agent
// in the prompt bar): follow it. If the new agent exposes NO sources, close the panel
// instead of ensuring a dataset-less explorer (which would render a dead empty state
// and could fire a source:null rows request).
watch(() => session.selectedAgentKey, (key) => {
  if (!sources.open) return
  if (!key) return
  const a = session.agents.find((x) => x.key === key)
  const hasSources = !!(a && Array.isArray(a.sources) && a.sources.length)
  if (!hasSources) {
    sources.closePanel()
    return
  }
  sources.ensureAgent(key)
})
</script>

<template>
  <aside class="src-panel">
    <header class="src-head">
      <div class="src-title">
        <Icon name="database" />
        <span class="src-title-label">{{ t('src.panel.title') }}</span>
        <span v-if="agentLabel" class="src-agent">{{ agentLabel }}</span>
      </div>
      <div class="src-actions">
        <!-- Two-state dock toggle: ambient third <-> expanded two thirds. -->
        <button
          class="src-btn"
          :title="sources.wide ? t('src.panel.shrink') : t('src.panel.expand')"
          @click="sources.toggleWide()"
        >
          <Icon :name="sources.wide ? 'chevronsRight' : 'chevronsLeft'" />
        </button>
        <!-- The X is a sticky opt-out: the auto-dock stops for this app session. -->
        <button class="src-btn" :title="t('x.close')" @click="sources.dismissPanel()">
          <Icon name="x" />
        </button>
      </div>
    </header>
    <div class="src-panel-body">
      <SourceExplorer />
    </div>
  </aside>
</template>

<style scoped>
/* Ambient surface: the docked data view sits on a soft gray so the WHITE chat column
   (and its ink-framed prompt) reads as the foreground. The data table inside is
   forced back to white below - the content pops, the chrome recedes. */
.src-panel {
  display: flex; flex-direction: column; min-width: 0; overflow: hidden;
  background: var(--surface);
  border-left: 1px solid var(--border-strong);
  /* Remap the explorer's host tokens: on this ambient --surface, chips/cards go
     back to --bg with a VISIBLE 1px filet (charte) - content pops, chrome recedes.
     The Evidence "Source data" tab (default --bg host) keeps its fallbacks. */
  --src-chip-bg: var(--bg);
  --src-chip-border: var(--border-strong);
  /* Discreet dock-in (charte motion): a short fade + slide from the right edge. */
  animation: src-dock-in var(--dur-slow) var(--ease-out) both;
}
@keyframes src-dock-in {
  from { opacity: 0; transform: translateX(12px); }
}
@media (prefers-reduced-motion: reduce) {
  .src-panel { animation: none; }
}
.src-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--s-4) var(--s-5); border-bottom: 1px solid var(--border-strong);
}
.src-title { display: flex; align-items: center; gap: 8px; min-width: 0; }
/* Ink icon: a permanently visible dock earns NO orange (charte: orange is for
   active states / title-bars / primary actions, never ambient chrome). */
.src-title :deep(.ui-icon) { width: 16px; height: 16px; color: var(--text-2); flex: none; }
/* Micro-label recipe (charte): quiet caps - the panel is ambient, not a headline. */
.src-title-label {
  font-size: 11px; font-weight: var(--fw-heavy); text-transform: uppercase;
  letter-spacing: 0.1em; color: var(--text-2);
}
.src-agent {
  font-size: 11px; color: var(--text-2); font-weight: 400;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.src-actions { display: flex; align-items: center; gap: 2px; }
.src-btn { padding: 4px; border-radius: 0; color: var(--text-2); transition: all var(--dur) var(--ease); }
.src-btn:hover { background: var(--surface-hover); color: var(--text); }
.src-btn :deep(.ui-icon) { width: 16px; height: 16px; }
/* Full-height body: a flex column that does NOT scroll itself - the rows table
   fills the remaining height and owns the only scroll (no double scrollbar). */
.src-panel-body {
  flex: 1; min-height: 0; overflow: hidden; padding: var(--s-5);
  display: flex; flex-direction: column;
}
.src-panel-body :deep(.src-explorer) { flex: 1; min-height: 0; }
.src-panel-body :deep(.src-table) {
  flex: 1; min-height: 0; background: var(--bg);
  /* A --bg block on the ambient --surface is a CARD: visible 1px filet (charte). */
  border-color: var(--border-strong);
}
.src-panel-body :deep(.src-table-scroll) { flex: 1 1 auto; max-height: none; }
</style>
