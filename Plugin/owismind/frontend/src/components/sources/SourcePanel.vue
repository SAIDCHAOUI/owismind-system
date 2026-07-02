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
        <span>{{ t('src.panel.title') }}</span>
        <span v-if="agentLabel" class="src-agent">{{ agentLabel }}</span>
      </div>
      <button class="src-close" :title="t('x.close')" @click="sources.closePanel()">
        <Icon name="x" />
      </button>
    </header>
    <div class="src-panel-body">
      <SourceExplorer />
    </div>
  </aside>
</template>

<style scoped>
.src-panel {
  display: flex; flex-direction: column; min-width: 0; overflow: hidden;
  background: var(--bg);
}
.src-head {
  display: flex; align-items: center; justify-content: space-between;
  padding: var(--s-4) var(--s-5); border-bottom: 1px solid var(--border);
}
.src-title { display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: var(--fs-md); min-width: 0; }
.src-title :deep(.ui-icon) { width: 16px; height: 16px; color: var(--orange); flex: none; }
.src-agent {
  font-size: 11px; color: var(--text-3); font-weight: 400;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.src-close { padding: 4px; border-radius: 0; color: var(--text-3); transition: all var(--dur) var(--ease); }
.src-close:hover { background: var(--surface-hover); color: var(--text); }
.src-close :deep(.ui-icon) { width: 16px; height: 16px; }
.src-panel-body {
  flex: 1; min-height: 0; overflow-y: auto; padding: var(--s-5);
}
</style>
