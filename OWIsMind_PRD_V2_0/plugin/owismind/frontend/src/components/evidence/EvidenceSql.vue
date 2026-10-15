<script setup>
// "Technical details" disclosure at the foot of the Data tab: closed by default, it
// holds everything a business user never needs (the result identifier and the agent's
// exact query, pretty-printed with a copy button). Same wording and pattern as the
// provenance drawer, so nothing technical is visible until the user asks for it.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useToasts } from '../../composables/useToasts.js'
import { highlightSqlLines } from '../../composables/sqlPretty.js'
import { Icon } from '../ui'

const props = defineProps({
  sql: { type: String, required: true },
  sqlId: { type: String, default: '' },
})
const { t } = useI18n()
const { push } = useToasts()

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
  <details class="ev-tech">
    <summary>{{ t('ws.prov.tech') }}</summary>
    <dl v-if="sqlId" class="ev-tech-facts">
      <dt>{{ t('ws.prov.id') }}</dt>
      <dd class="mono">{{ sqlId }}</dd>
    </dl>
    <div class="ev-tech-row">
      <span class="ev-tech-label">{{ t('ws.prov.sql') }}</span>
      <button type="button" class="ev-tech-copy" @click="copySql">
        <Icon name="copy" />{{ t('ws.prov.copy') }}
      </button>
    </div>
    <pre class="ev-tech-sql mono"><code><template v-for="(line, li) in lines" :key="li"><span v-for="(tok, ti) in line" :key="ti" :class="'sqltok-' + tok.kind">{{ tok.text }}</span>{{ '\n' }}</template></code></pre>
  </details>
</template>

<style scoped>
/* Mirrors the provenance drawer's .d-tech block (flat, 1px rule, muted summary). */
.ev-tech {
  flex: none;
  border-top: 1px solid var(--border);
  padding: var(--s-3) var(--s-5);
  background: var(--bg);
}
.ev-tech summary { cursor: pointer; font-size: var(--fs-xs); color: var(--text-3); }
.ev-tech summary:hover { color: var(--text); }
.ev-tech[open] summary { margin-bottom: var(--s-3); }
.ev-tech-facts { margin: 0 0 var(--s-3); }
.ev-tech-facts dt { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); padding-bottom: 3px; }
.ev-tech-facts dd { margin: 0; font-size: var(--fs-sm); color: var(--text); overflow-wrap: anywhere; }
.ev-tech-row { display: flex; align-items: center; justify-content: space-between; gap: var(--s-3); }
.ev-tech-label { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); }
.ev-tech-copy {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  color: var(--text-2);
}
.ev-tech-copy:hover { border-color: var(--text); color: var(--text); }
.ev-tech-copy :deep(.ui-icon) { width: 13px; height: 13px; }
.ev-tech-sql {
  margin: var(--s-2) 0 0;
  padding: var(--s-3) var(--s-4);
  max-height: 240px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
  white-space: pre;
  tab-size: 2;
}
/* Text-only token spans (escaped): keywords take the orange text tone, literals the
   series hues, exactly like the provenance drawer. */
.sqltok-kw { color: var(--orange-text); font-weight: var(--fw-bold); }
.sqltok-str { color: var(--series-2); }
.sqltok-num { color: var(--series-1); }
</style>
