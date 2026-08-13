<script setup>
// Collapsible raw-SQL footer of the Evidence panel: the agent's exact query,
// PRETTY-PRINTED with light syntax highlighting + a copy button (which copies the
// exact executed query verbatim) - full, readable transparency under the proof.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToasts } from '../../composables/useToasts.js'
import { highlightSqlLines } from '../../composables/sqlPretty.js'
import { Icon } from '../ui'

const props = defineProps({ sql: { type: String, required: true } })
const { t } = useI18n()
const { push } = useToasts()
const show = ref(false)

// Formatted + tokenized lines for highlighted display (escaped text, never
// v-html). The copy button still copies the EXACT executed query (props.sql).
const lines = computed(() => highlightSqlLines(props.sql))

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
    <pre v-if="show" class="ev-sql-code mono"><code><template v-for="(line, li) in lines" :key="li"><span v-for="(tok, ti) in line" :key="ti" :class="'sqltok-' + tok.kind">{{ tok.text }}</span>{{ '\n' }}</template></code></pre>
  </div>
</template>

<style scoped>
.ev-sql { border-top: 1px solid var(--border); background: var(--surface); }
.ev-sql-bar { display: flex; align-items: center; }
.ev-sql-toggle {
  flex: 1; display: flex; align-items: center; gap: 6px; padding: 8px 12px;
  font-size: var(--fs-sm); color: var(--text-2);
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.ev-sql-toggle:hover { color: var(--text); background: var(--surface-2); }
.ev-sql-toggle :deep(.ui-icon) { width: 14px; height: 14px; }
.ev-sql-copy {
  display: inline-flex; margin: 4px 8px 4px 0; padding: 6px;
  border-radius: var(--r-pill); color: var(--text-3);
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.ev-sql-copy:hover { color: var(--text); background: var(--surface-hover); }
.ev-sql-copy :deep(.ui-icon) { width: 14px; height: 14px; }
/* The query unrolls (fade + rise) instead of snapping open under the bar. */
.ev-sql-code {
  margin: 0; padding: var(--s-3) var(--s-4); max-height: 240px; overflow: auto;
  background: var(--surface-2); font-size: 12px; line-height: 1.7;
  color: var(--text-2); white-space: pre;
  tab-size: 2;
  animation: ev-sql-open var(--dur) var(--ease-out) both;
}
@keyframes ev-sql-open {
  from { opacity: 0; transform: translateY(-4px); }
}
@media (prefers-reduced-motion: reduce) {
  .ev-sql-toggle, .ev-sql-copy { transition: none; }
  .ev-sql-code { animation: none; }
}
/* Light syntax highlighting - keywords in brand orange, strings/numbers tinted.
   Text-only spans (escaped), so this can never inject markup. */
.sqltok-kw { color: var(--orange-text); font-weight: 600; }
.sqltok-str { color: #2f9e44; }
.sqltok-num { color: #1971c2; }
:global(body[data-theme="dark"] .sqltok-str) { color: #69db7c; }
:global(body[data-theme="dark"] .sqltok-num) { color: #74c0fc; }
</style>
