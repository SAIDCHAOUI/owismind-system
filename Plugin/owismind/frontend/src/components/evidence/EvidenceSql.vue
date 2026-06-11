<script setup>
// Collapsible raw-SQL footer of the Evidence panel: the agent's exact query +
// a copy button — full transparency under the visual proof.
import { ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToasts } from '../../composables/useToasts.js'
import { Icon } from '../ui'

const props = defineProps({ sql: { type: String, required: true } })
const { t } = useI18n()
const { push } = useToasts()
const show = ref(false)

async function copySql() {
  try {
    await navigator.clipboard.writeText(props.sql)
    push(t('ev.sql.copied'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    push(t('msg.copy_failed'), { icon: 'alert', tone: 'warn' })
  }
}
</script>

<template>
  <div class="ev-sql">
    <div class="ev-sql-bar">
      <button type="button" class="ev-sql-toggle" @click="show = !show">
        <Icon :name="show ? 'chevronDown' : 'chevronRight'" />
        <span>{{ t('ev.sql.title') }}</span>
      </button>
      <button v-if="show" type="button" class="ev-sql-copy" :title="t('ev.sql.copy')" @click="copySql">
        <Icon name="copy" />
      </button>
    </div>
    <pre v-if="show" class="ev-sql-code mono">{{ sql }}</pre>
  </div>
</template>

<style scoped>
.ev-sql { border-top: 1px solid var(--border); background: var(--surface); }
.ev-sql-bar { display: flex; align-items: center; }
.ev-sql-toggle {
  flex: 1; display: flex; align-items: center; gap: 6px; padding: 8px 12px;
  font-size: var(--fs-sm); color: var(--text-2);
  transition: color var(--dur) var(--ease);
}
.ev-sql-toggle:hover { color: var(--text); }
.ev-sql-toggle :deep(.ui-icon) { width: 14px; height: 14px; }
.ev-sql-copy { padding: 8px 12px; color: var(--text-3); }
.ev-sql-copy:hover { color: var(--text); }
.ev-sql-copy :deep(.ui-icon) { width: 14px; height: 14px; }
.ev-sql-code {
  margin: 0; padding: var(--s-3) var(--s-4); max-height: 200px; overflow: auto;
  background: var(--surface-2); font-size: 12px; line-height: 1.6;
  color: var(--text); white-space: pre;
}
</style>
