<script setup>
// Agent picker — repopulated from GET /agents (opaque logical keys), NOT the
// maquette's hard-coded list (a literal port would send invalid keys → 404
// agent_not_enabled). Reuses the <Menu> primitive; opens upward
// (it lives in the bottom prompt bar). Binds session.selectedAgentKey.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSessionStore } from '../../stores/session.js'
import { Icon, Menu } from '../ui'

const { t } = useI18n()
const session = useSessionStore()

const items = computed(() => session.agents.map((a) => ({ key: a.key, label: a.label })))
const selectedLabel = computed(() => {
  const a = session.agents.find((x) => x.key === session.selectedAgentKey)
  return a ? a.label : t('prompt.choose_agent')
})

function onSelect(key) {
  session.selectAgent(key)
}
</script>

<template>
  <Menu align="left" placement="top" :items="items" @select="onSelect">
    <template #trigger="{ toggle }">
      <button
        class="agent-pick"
        :class="{ 'is-empty': !session.hasAgents }"
        :disabled="!session.hasAgents"
        :title="session.hasAgents ? t('prompt.choose_agent') : t('prompt.choose_agent')"
        @click="toggle"
      >
        <Icon name="robot" class="agent-pick__lead" />
        <span class="agent-pick__label">{{ session.hasAgents ? selectedLabel : t('prompt.choose_agent') }}</span>
        <Icon name="chevronsUpDown" class="agent-pick__caret" />
      </button>
    </template>
  </Menu>
</template>

<style scoped>
.agent-pick {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 0 10px;
  border-radius: var(--r-sm);
  color: var(--text-2);
  font-size: var(--fs-sm);
  font-weight: 500;
  max-width: 240px;
  transition: all var(--dur) var(--ease);
}
.agent-pick:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.agent-pick:disabled { opacity: 0.6; cursor: not-allowed; }
.agent-pick__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-pick__lead :deep(svg), .agent-pick__lead { width: 16px; height: 16px; color: var(--orange); flex-shrink: 0; }
.agent-pick__caret { width: 14px; height: 14px; color: var(--text-3); flex-shrink: 0; }
</style>
