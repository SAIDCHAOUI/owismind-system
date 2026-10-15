<script setup>
// Agent picker - repopulated from GET /agents (opaque logical keys), NOT the
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
    <template #trigger="{ toggle, open }">
      <button
        class="agent-pick"
        :class="{ 'is-empty': !session.hasAgents, open }"
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
/* Capsule trigger inside the prompt card: it keeps its fill while the menu is open,
   so the panel above visibly belongs to this control. */
.agent-pick {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  height: 32px;
  padding: 0 12px;
  border-radius: var(--r-pill);
  color: var(--text-2);
  font-size: var(--fs-sm);
  font-weight: 500;
  max-width: 320px;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.agent-pick:hover:not(:disabled),
.agent-pick.open { background: var(--surface-hover); color: var(--text); }
.agent-pick:disabled { opacity: 0.6; cursor: not-allowed; }
.agent-pick__label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.agent-pick__lead :deep(svg), .agent-pick__lead { width: 16px; height: 16px; color: var(--orange); flex-shrink: 0; }
.agent-pick__caret {
  width: 14px;
  height: 14px;
  color: var(--text-3);
  flex-shrink: 0;
  transition: color var(--dur) var(--ease);
}
.agent-pick:hover:not(:disabled) .agent-pick__caret,
.agent-pick.open .agent-pick__caret { color: var(--text-2); }

@media (prefers-reduced-motion: reduce) {
  .agent-pick, .agent-pick__caret { transition: none; }
}
</style>
