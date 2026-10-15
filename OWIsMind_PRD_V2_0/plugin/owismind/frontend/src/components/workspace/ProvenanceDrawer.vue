<script setup>
// Provenance drawer - where ONE result (sql_id) comes from: the expert sub-agent and
// tool that produced it, the task it was given, duration and status, the filters
// read from its SQL (read-only chips), the SQL itself pretty-printed (sqlPretty, the
// copy button copies the exact executed query) and an honest row count. "Open in
// Data" moves to the Data tab (the Evidence panel of this exchange).
import { computed, ref, onMounted, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { stepFor } from '../../composables/workspaceModel.js'
import { highlightSqlLines } from '../../composables/sqlPretty.js'
import { resultCountLabel, needsFullResult } from '../../composables/resultRows.js'
import { formatStatNumber } from '../../composables/sourceModel.js'
import { calcStepArgs } from '../../composables/evidenceProof.js'
import { useToasts } from '../../composables/useToasts.js'
import { Icon } from '../ui'

const { t, locale } = useI18n()
const ws = useWorkspaceStore()
const { push } = useToasts()
const closeBtn = ref(null)

const sqlId = computed(() => ws.drawerSqlId)
const info = computed(() => ws.sqlInfo(sqlId.value))
const prov = computed(() => (info.value && info.value.provenance) || null)
const widget = computed(() => {
  const id = ws.drawerWidgetId
  return id && ws.state ? ws.state.widgets.find((w) => w.id === id) || null : null
})
const step = computed(() => {
  const sid = (prov.value && prov.value.step_id) || (widget.value && widget.value.step_id)
  return sid ? stepFor(ws.state, sid) : null
})
const lines = computed(() => (info.value && info.value.sql ? highlightSqlLines(info.value.sql) : []))

const toolLabel = computed(() => {
  const tool = prov.value && prov.value.tool
  return tool ? t('ws.tool.' + tool.replace(/-/g, '_')) : ''
})
const duration = computed(() => {
  const ms = prov.value && prov.value.duration_ms
  if (typeof ms !== 'number') return ''
  return t('ws.prov.seconds', [(ms / 1000).toLocaleString(locale.value, { maximumFractionDigits: 1 })])
})

// One read-only chip per filter. /workspace sends the filter_* steps of the SQL
// explainer ({kind, params}, rendered with the shared ev.exp.* labels); the chip
// shape {column, op, values} and plain strings are still accepted.
function filterLabel(f) {
  if (typeof f === 'string') return f
  if (!f || typeof f !== 'object') return ''
  if (typeof f.kind === 'string' && f.kind.startsWith('filter_')) {
    // Same wording as the Evidence calculation steps; an unknown kind -> opaque label.
    const s = calcStepArgs(f)
    return t(s.key, s.args)
  }
  const values = Array.isArray(f.values) ? f.values : f.value != null ? [f.value] : []
  const op = f.op && f.op !== '=' && f.op !== 'IN' ? ' ' + f.op + ' ' : ' : '
  return String(f.column || '') + op + values.map(String).join(', ')
}
const filters = computed(() => (info.value ? info.value.filters.map(filterLabel).filter(Boolean) : []))

const countLine = computed(() => {
  const r = info.value && info.value.result
  if (!r || !Array.isArray(r.rows)) {
    const rc = info.value && info.value.rowCount
    return typeof rc === 'number' ? t('res.count.full', [formatStatNumber(rc, locale.value)]) : ''
  }
  const label = resultCountLabel({
    shown: r.rows.length,
    total: info.value.rowCount,
    live: false,
    hasMore: false,
    partial: needsFullResult(r),
  })
  return t(label.key, label.args.map((n) => formatStatNumber(n, locale.value)))
})

async function copySql() {
  try {
    await navigator.clipboard.writeText(info.value.sql)
    push(t('ws.prov.copied'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    push(t('msg.copy_failed'), { icon: 'alert', tone: 'warn' })
  }
}
function openData() {
  ws.closeProvenance()
  ws.setTab('data')
}
function onKey(e) {
  if (e.key === 'Escape') ws.closeProvenance()
}
onMounted(() => {
  document.addEventListener('keydown', onKey)
  if (closeBtn.value) closeBtn.value.focus()
})
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <div class="drawer" role="dialog" :aria-label="t('ws.prov.title')">
    <header class="d-head">
      <div class="d-titles">
        <span class="d-title">{{ t('ws.prov.title') }}</span>
        <span class="d-sub mono">{{ widget ? widget.title + ' · ' : '' }}{{ sqlId }}</span>
      </div>
      <button ref="closeBtn" type="button" class="d-close" :title="t('ws.prov.close')" :aria-label="t('ws.prov.close')" @click="ws.closeProvenance()">
        <Icon name="x" />
      </button>
    </header>

    <div class="d-body">
      <p v-if="!prov" class="d-note">{{ t('ws.prov.unknown') }}</p>
      <dl v-else class="facts">
        <div class="fact">
          <dt>{{ t('ws.prov.agent') }}</dt>
          <dd>{{ String(prov.agent_key).replace(/_/g, ' ') }}</dd>
        </div>
        <div class="fact">
          <dt>{{ t('ws.prov.tool') }}</dt>
          <dd>{{ toolLabel }}</dd>
        </div>
        <div v-if="step" class="fact">
          <dt>{{ t('ws.tab.plan') }}</dt>
          <dd>{{ t('ws.step.label', [step.index]) }} : {{ step.label }}</dd>
        </div>
        <div v-if="duration" class="fact">
          <dt>{{ t('ws.prov.duration') }}</dt>
          <dd class="mono">{{ duration }}</dd>
        </div>
        <div class="fact">
          <dt>{{ t('ws.prov.status') }}</dt>
          <dd :class="prov.success ? 'ok' : 'ko'">{{ prov.success ? t('ws.prov.ok') : t('ws.prov.failed') }}</dd>
        </div>
        <div v-if="prov.task" class="fact block">
          <dt>{{ t('ws.prov.task') }}</dt>
          <dd class="task">{{ prov.task }}</dd>
        </div>
      </dl>

      <section class="d-sec">
        <div class="d-label">{{ t('ws.prov.filters') }}</div>
        <div v-if="filters.length" class="chips">
          <span v-for="(f, i) in filters" :key="i" class="chip">{{ f }}</span>
        </div>
        <p v-else class="d-note">{{ t('ws.prov.no_filter') }}</p>
      </section>

      <section v-if="countLine" class="d-sec">
        <div class="d-label">{{ t('ws.prov.result') }}</div>
        <p class="d-count">{{ countLine }}</p>
      </section>

      <section class="d-sec">
        <div class="d-label-row">
          <span class="d-label">{{ t('ws.prov.sql') }}</span>
          <button v-if="info && info.sql" type="button" class="d-copy" @click="copySql">
            <Icon name="copy" />{{ t('ws.prov.copy') }}
          </button>
        </div>
        <pre v-if="lines.length" class="sql mono"><code><template v-for="(line, li) in lines" :key="li"><span v-for="(tok, ti) in line" :key="ti" :class="'sqltok-' + tok.kind">{{ tok.text }}</span>{{ '\n' }}</template></code></pre>
        <p v-else class="d-note">{{ t('ws.prov.no_sql') }}</p>
      </section>
    </div>

    <footer class="d-foot">
      <button type="button" class="d-primary" @click="openData">
        <Icon name="database" />{{ t('ws.prov.open_data') }}
      </button>
      <a v-if="info && info.sourceUrl" class="d-link" :href="info.sourceUrl" target="_blank" rel="noopener noreferrer">{{ t('ws.prov.open_source') }}</a>
    </footer>
  </div>
</template>

<style scoped>
/* Drawer over the panel body (the panel is position:relative). z-index stays under 5
   (chips popovers, F21). */
.drawer {
  position: absolute;
  top: 0;
  right: 0;
  bottom: 0;
  width: min(440px, 94%);
  z-index: 4;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  border-left: 1px solid var(--border-strong);
  box-shadow: var(--float-strong);
  animation: d-in var(--dur-slow) var(--ease-out) both;
}
@keyframes d-in { from { transform: translateX(24px); opacity: 0; } }
@media (prefers-reduced-motion: reduce) { .drawer { animation: none; } }
.d-head {
  flex: 0 0 auto;
  height: 56px;
  display: flex;
  align-items: center;
  gap: var(--s-3);
  padding: 0 var(--s-3) 0 var(--s-5);
  border-bottom: 1px solid var(--border);
}
.d-titles { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
.d-title { font-size: var(--fs-sm); font-weight: var(--fw-bold); }
.d-sub {
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.d-close {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-2);
}
.d-close:hover { background: var(--surface-hover); color: var(--text); }
.d-close :deep(.ui-icon) { width: 16px; height: 16px; }
.d-body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--s-4) var(--s-5) var(--s-5);
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
.facts { margin: 0; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: var(--s-3) var(--s-4); }
.fact { min-width: 0; }
.fact.block { grid-column: 1 / -1; }
.fact dt { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); padding-bottom: 3px; }
.fact dd { margin: 0; font-size: var(--fs-sm); color: var(--text); overflow-wrap: anywhere; }
.fact dd.ok { color: var(--success); }
.fact dd.ko { color: var(--danger); }
.task {
  padding: var(--s-2) var(--s-3);
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  line-height: var(--lh-text);
  white-space: pre-line;
}
.d-sec { border-top: 1px solid var(--border-strong); padding-top: var(--s-3); }
.d-label { font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text-2); }
.d-label-row { display: flex; align-items: center; justify-content: space-between; gap: var(--s-3); }
.chips { display: flex; flex-wrap: wrap; gap: 6px; padding-top: var(--s-2); }
.chip {
  display: inline-flex;
  align-items: center;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg);
  font-size: var(--fs-xs);
  white-space: nowrap;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
}
.d-note { margin: var(--s-2) 0 0; font-size: var(--fs-sm); color: var(--text-3); }
.d-count { margin: var(--s-2) 0 0; font-size: var(--fs-sm); }
.d-copy {
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
.d-copy:hover { border-color: var(--text); color: var(--text); }
.d-copy :deep(.ui-icon) { width: 13px; height: 13px; }
.sql {
  margin: var(--s-2) 0 0;
  padding: var(--s-3) var(--s-4);
  max-height: 320px;
  overflow: auto;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.65;
  color: var(--text-2);
  white-space: pre;
}
/* Text-only token spans (escaped): keywords take the orange text tone, literals the
   series hues (secondary palette = categories, here token kinds). */
.sqltok-kw { color: var(--orange-text); font-weight: var(--fw-bold); }
.sqltok-str { color: var(--series-2); }
.sqltok-num { color: var(--series-1); }
.d-foot {
  flex: 0 0 auto;
  display: flex;
  align-items: center;
  gap: var(--s-4);
  padding: var(--s-3) var(--s-5);
  border-top: 1px solid var(--border);
}
/* Primary action = orange fill, black ink (V2 charter). */
.d-primary {
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
}
.d-primary:hover { background: var(--orange-deep); }
.d-primary :deep(.ui-icon) { width: 15px; height: 15px; }
.d-link {
  font-size: var(--fs-sm);
  color: var(--orange-text);
  text-decoration: underline;
  text-underline-offset: 2px;
}
</style>
