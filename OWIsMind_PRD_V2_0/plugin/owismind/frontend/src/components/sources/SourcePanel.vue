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
      <!-- Data | Analyze - hoisted into the header (user ask 2026-08-13): the body keeps
           its rows for the data. Same store flag the explorer surfaces read. -->
      <div v-if="!sources.loading && !sources.error" class="src-viewseg">
        <button
          type="button"
          class="src-viewseg-btn"
          :class="{ active: !sources.analyzeOpen }"
          :aria-pressed="!sources.analyzeOpen"
          :title="t('src.view.hint.data')"
          @click="sources.setAnalyzeOpen(false)"
        ><Icon name="grid" />{{ t('src.view.data') }}</button>
        <button
          type="button"
          class="src-viewseg-btn"
          :class="{ active: sources.analyzeOpen }"
          :aria-pressed="sources.analyzeOpen"
          :title="t('src.view.hint.analyze')"
          @click="sources.setAnalyzeOpen(true)"
        ><Icon name="chart" />{{ t('src.view.analyze') }}</button>
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
    <div class="src-panel-body" :class="{ 'is-teaser': sources.teaser }">
      <!-- `inert` (not just pointer-events) while teasing: the veil must also stop the
           KEYBOARD, or Tab would land in a search field the user cannot see. -->
      <div class="src-explorer-host" :inert="sources.teaser">
        <SourceExplorer />
      </div>
      <!-- Teaser veil (auto-docked state): the data is deliberately blurred - "I
           exist, click me to work on me". One click lifts the blur and expands the
           dock to its working width. Hover already eases the blur, inviting in. -->
      <button
        v-if="sources.teaser"
        type="button"
        class="src-teaser-veil"
        @click="sources.engage()"
      >
        <span class="src-teaser-card">
          <Icon name="database" />
          <span class="src-teaser-title">{{ t('src.teaser.title') }}</span>
          <span class="src-teaser-hint">{{ t('src.teaser.hint') }}</span>
        </span>
      </button>
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
  display: flex; align-items: center; gap: var(--s-3);
  /* Same fixed height as the chat topbar (.main-top: 56px) so the two bottom
     hairlines meet as ONE continuous line across the whole app (user ask). */
  height: 56px; flex-shrink: 0;
  padding: 0 var(--s-5); border-bottom: 1px solid var(--border);
}
/* Title truncates FIRST (min-width 0): the view switch and the actions never do. */
.src-title { display: flex; align-items: center; gap: 8px; min-width: 0; flex: 0 1 auto; }
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
/* Data / Analyze segmented control (hoisted from the explorer body) - compact header
   fit of the same charte recipe: 1px filet, pill, active segment filled with ink. */
.src-viewseg {
  display: inline-flex; flex: none;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill); overflow: hidden;
}
.src-viewseg-btn {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 12px; font-size: var(--fs-xs); color: var(--text-2);
  background: var(--bg); transition: all var(--dur) var(--ease);
}
.src-viewseg-btn :deep(.ui-icon) { width: 12px; height: 12px; transition: transform var(--dur) var(--ease); }
.src-viewseg-btn + .src-viewseg-btn { border-left: 1px solid var(--border-strong); }
.src-viewseg-btn:hover:not(.active) { background: var(--surface-hover); color: var(--text); }
.src-viewseg-btn:hover:not(.active) :deep(.ui-icon) { transform: scale(1.1); }
.src-viewseg-btn.active { background: var(--text); color: var(--bg); font-weight: var(--fw-medium); }
@media (prefers-reduced-motion: reduce) {
  .src-viewseg-btn, .src-viewseg-btn :deep(.ui-icon) { transition: none; }
  .src-viewseg-btn:hover:not(.active) :deep(.ui-icon) { transform: none; }
}
.src-actions { display: flex; align-items: center; gap: 2px; margin-left: auto; }
/* Rounded icon buttons (premium 2026-08-13): the hover patch reads as a soft target,
   not a hard square dropped on the header rule. */
.src-btn {
  display: inline-flex; padding: 6px; border-radius: var(--r-pill);
  color: var(--text-2); transition: all var(--dur) var(--ease);
}
.src-btn:hover { background: var(--surface-hover); color: var(--text); }
.src-btn :deep(.ui-icon) { width: 16px; height: 16px; }
/* Full-height body: a flex column that does NOT scroll itself - the rows table
   fills the remaining height and owns the only scroll (no double scrollbar). */
.src-panel-body {
  flex: 1; min-height: 0; overflow: hidden; padding: var(--s-5);
  display: flex; flex-direction: column;
}
/* The inert host is a pure layout pass-through: the explorer keeps filling the body. */
.src-explorer-host { flex: 1; min-height: 0; display: flex; flex-direction: column; }
.src-panel-body :deep(.src-explorer) {
  flex: 1; min-height: 0;
  transition: filter var(--dur-slow) var(--ease), opacity var(--dur-slow) var(--ease);
}
/* Teaser (auto-docked): the explorer is present but deliberately NOT yet usable -
   blurred, inert, behind a floating invite. Hovering eases the blur (curiosity
   rewarded); clicking anywhere engages (blur lifts + dock expands). */
.src-panel-body.is-teaser { position: relative; cursor: pointer; }
.src-panel-body.is-teaser :deep(.src-explorer) {
  filter: blur(3px) saturate(0.85);
  opacity: 0.75;
  pointer-events: none;
  user-select: none;
}
.src-panel-body.is-teaser:hover :deep(.src-explorer) {
  filter: blur(1.8px) saturate(0.95);
  opacity: 0.9;
}
.src-teaser-veil {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: transparent;
  cursor: pointer;
}
.src-teaser-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: var(--s-2);
  max-width: 260px;
  padding: var(--s-5) var(--s-6);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--elev-2);
  text-align: center;
  transition: transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.src-teaser-veil:hover .src-teaser-card { transform: translateY(-2px) scale(1.02); }
.src-teaser-card :deep(.ui-icon) { width: 22px; height: 22px; color: var(--orange); }
.src-teaser-title { font-size: var(--fs-md); font-weight: var(--fw-bold); color: var(--text); }
.src-teaser-hint { font-size: var(--fs-xs); color: var(--text-2); line-height: 1.5; }
@media (prefers-reduced-motion: reduce) {
  .src-panel-body :deep(.src-explorer) { transition: none; }
  .src-teaser-card { transition: none; }
  .src-teaser-veil:hover .src-teaser-card { transform: none; }
}
/* The BROWSING table fills the dock; the Analyze view's read-only preview
   (`.is-preview`) keeps its own compact height instead. */
.src-panel-body :deep(.src-table:not(.is-preview)) {
  flex: 1; min-height: 0; background: var(--bg);
  /* A --bg block on the ambient --surface is a CARD: visible 1px filet (charte). */
  border-color: var(--border-strong);
}
.src-panel-body :deep(.src-table:not(.is-preview) .src-table-view) { flex: 1 1 auto; min-height: 0; }
.src-panel-body :deep(.src-table:not(.is-preview) .src-table-scroll) { flex: 1 1 auto; max-height: none; }
/* The preview is a --bg card on the ambient --surface too (same filet grammar). */
.src-panel-body :deep(.src-table.is-preview) { background: var(--bg); border-color: var(--border-strong); }
</style>
