<script setup>
// Right-column BEACON (design "Espace de travail v4", aside.ws-beacon): shown whenever
// no right panel is open. A full-height column, sibling of the chat column (the chat
// header is never covered), holding ONE big button: icon, eyebrow, title, subtitle,
// the agent's datasets, a faded preview of real source rows under an "Open the data"
// pill, and the orange call to action at the bottom. Markup and motion follow the
// design (bcnRise stagger, .bcn hover effects). A workspace built while the panel was
// closed (or still running) carries the rare orange signal on the frame. Below the
// narrow breakpoint the design has no beacon: a floating button stands in, under the
// chat header.
import { computed, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { fetchSourceMeta, fetchSourceRows } from '../../services/backend.js'
import { previewTable } from '../../composables/teaserModel.js'
import { Icon } from '../ui'

const props = defineProps({
  // teaserState() output: { visible, mode, signal, running, compact }
  teaser: { type: Object, required: true },
  // The selected agent key + its source datasets [{ id, label, dataset }].
  agentKey: { type: String, default: '' },
  sources: { type: Array, default: () => [] },
})
const emit = defineEmits(['open'])
const { t } = useI18n()

const datasets = computed(() =>
  props.sources.slice(0, 3).map((s, i) => ({
    key: 'ds' + i,
    name: s.label || s.dataset || '',
    meta: s.dataset || '',
  })),
)
const status = computed(() => {
  if (props.teaser.mode !== 'workspace') return ''
  return props.teaser.running ? t('ws.teaser.running') : props.teaser.signal ? t('ws.new') : ''
})

// Faded preview of REAL source rows (first source, 3 columns, 8 rows): one small
// read-only request per agent, cached for the app session, best effort.
const PREVIEW_CACHE = new Map()
const preview = ref({ cols: [], rows: [] })
async function loadPreview() {
  const key = props.agentKey
  const src = props.sources[0]
  if (!key || !src || props.teaser.compact) return
  const cacheKey = key + ':' + (src.id != null ? src.id : 0)
  if (PREVIEW_CACHE.has(cacheKey)) {
    preview.value = PREVIEW_CACHE.get(cacheKey)
    return
  }
  try {
    const sourceId = src.id != null ? src.id : 0
    const meta = await fetchSourceMeta(key, sourceId)
    const page = await fetchSourceRows({ agent: key, source: sourceId, q: '', filters: [], limit: 8, offset: 0, sort: null })
    const table = previewTable(meta, page && page.rows)
    PREVIEW_CACHE.set(cacheKey, table)
    if (props.agentKey === key) preview.value = table
  } catch (e) {
    /* best effort: the beacon simply shows no preview rows */
  }
}
watch(() => [props.agentKey, props.sources.length, props.teaser.compact], loadPreview, { immediate: true })
const gridCols = computed(() => 'repeat(' + Math.max(1, preview.value.cols.length) + ', minmax(0, 1fr))')
</script>

<template>
  <!-- Narrow screens: floating button under the chat header (no beacon in the design). -->
  <button
    v-if="teaser.compact"
    type="button"
    class="bcn-fab"
    :class="{ signal: teaser.signal }"
    :title="t('ws.teaser.cta')"
    @click="emit('open')"
  >
    <Icon name="database" />
    <span>{{ t('ws.teaser.cta') }}</span>
    <span v-if="teaser.signal" class="bcn-dot" :class="{ live: teaser.running }" aria-hidden="true" />
  </button>

  <aside v-else class="ws-beacon">
    <button type="button" class="bcn" :class="{ signal: teaser.signal }" :title="t('ws.teaser.cta')" @click="emit('open')">
      <span class="bcn-top">
        <span class="bcn-ico">
          <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v12c0 1.7 3.6 3 8 3s8-1.3 8-3V6" /><path d="M4 12c0 1.7 3.6 3 8 3s8-1.3 8-3" /></svg>
        </span>
        <span class="bcn-eyebrow">
          <span class="bcn-dot" :class="{ live: teaser.running }" aria-hidden="true" />
          {{ t('ws.teaser.eyebrow') }}<template v-if="status"> · {{ status }}</template>
        </span>
        <span class="bcn-title">{{ t('ws.teaser.title') }}</span>
        <span class="bcn-sub">{{ t('ws.teaser.sub') }}</span>
      </span>

      <span v-if="datasets.length" class="bcn-list">
        <span v-for="d in datasets" :key="d.key" class="bcn-row">
          <span class="bcn-row-main">
            <span class="bcn-row-ico">
              <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" aria-hidden="true"><rect x="3" y="4" width="18" height="16" rx="2" /><line x1="3" y1="9" x2="21" y2="9" /><line x1="9" y1="9" x2="9" y2="20" /></svg>
            </span>
            <span class="bcn-row-name">{{ d.name }}</span>
          </span>
          <span class="bcn-row-meta">{{ d.meta }}</span>
        </span>
      </span>

      <span class="bcn-peek">
        <span class="bcn-tbl" aria-hidden="true">
          <span v-if="preview.cols.length" class="bcn-tbl-head" :style="{ gridTemplateColumns: gridCols }">
            <span v-for="c in preview.cols" :key="c" class="bcn-th">{{ c }}</span>
          </span>
          <span v-for="(r, i) in preview.rows" :key="i" class="bcn-tr" :style="{ gridTemplateColumns: gridCols }">
            <span v-for="(v, j) in r" :key="j" class="bcn-td">{{ v }}</span>
          </span>
        </span>
        <span class="bcn-veil">
          <span class="bcn-pill">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z" /><circle cx="12" cy="12" r="2.6" /></svg>
            {{ t('ws.teaser.peek') }}
          </span>
        </span>
      </span>

      <span class="bcn-cta">
        {{ t('ws.teaser.cta') }}
        <span class="bcn-arrow">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><polyline points="15 6 9 12 15 18" /></svg>
        </span>
      </span>
    </button>
  </aside>
</template>

<style scoped>
/* The column: full height, sibling of the chat column, the card spans top to bottom. */
.ws-beacon {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  /* Same floating inset as the Studio card (12px from the viewport edges). */
  padding: 12px 12px 12px 0;
  background: transparent;
}
.bcn {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--paper, var(--bg));
  box-shadow: var(--float-strong);
  cursor: pointer;
  text-align: left;
  transition: border-color var(--dur) var(--ease-out);
}
.bcn:hover { border-color: var(--text); }
/* Signal (workspace built while closed, or running): the frame takes the orange. */
.bcn.signal { border-color: var(--orange); }
@keyframes bcnRise { from { opacity: 0; transform: translateY(12px); } to { opacity: 1; transform: none; } }
.bcn-top {
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
  padding: var(--s-6) var(--s-5) var(--s-5);
}
.bcn-ico {
  width: 44px;
  height: 44px;
  display: grid;
  place-items: center;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  color: var(--orange);
  animation: bcnRise 0.55s var(--ease-out) both;
  transition: border-color 280ms var(--ease-out), background 280ms var(--ease-out), transform 280ms var(--ease-out);
}
.bcn:hover .bcn-ico { border-color: var(--orange); background: var(--orange-soft-dark); transform: translateY(-2px); }
.bcn-eyebrow {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  letter-spacing: 0;
  color: var(--text-2);
  animation: bcnRise 0.55s var(--ease-out) 0.08s both;
}
.bcn-dot { width: 8px; height: 8px; flex: 0 0 8px; background: var(--orange); }
.bcn-dot.live { animation: bcn-pulse 1.15s ease-in-out infinite; }
@keyframes bcn-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
.bcn-title {
  display: block;
  font-size: var(--fs-lg);
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em;
  line-height: 1.3;
  color: var(--text);
  animation: bcnRise 0.55s var(--ease-out) 0.15s both;
}
.bcn-sub {
  display: block;
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.55;
  animation: bcnRise 0.55s var(--ease-out) 0.22s both;
}
.bcn-list {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  padding: 0 var(--s-5);
  overflow: hidden;
}
.bcn-row {
  display: block;
  padding: 10px 0;
  border-top: 1px solid var(--border);
  animation: bcnRise 0.55s var(--ease-out) 0.3s both;
  transition: padding-left 280ms var(--ease-out);
}
.bcn:hover .bcn-row { padding-left: 4px; }
.bcn-row-main { display: flex; align-items: center; gap: 10px; min-width: 0; }
.bcn-row-ico { color: var(--text-3); display: grid; place-items: center; flex: 0 0 auto; }
.bcn-row-name {
  flex: 1;
  min-width: 0;
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bcn-row-meta {
  display: block;
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--text-3);
  padding: 4px 0 0 24px;
}
.bcn-peek {
  position: relative;
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  margin: var(--s-4) var(--s-5) 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  overflow: hidden;
  animation: bcnRise 0.55s var(--ease-out) 0.4s both;
}
.bcn-tbl {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  pointer-events: none;
  opacity: 0.6;
  transition: opacity 320ms var(--ease-out);
}
.bcn:hover .bcn-tbl { opacity: 1; }
.bcn-tbl-head,
.bcn-tr {
  display: grid;
  gap: 10px;
  padding: 7px 10px;
  border-bottom: 1px solid var(--border);
}
.bcn-tbl-head { background: var(--surface); }
.bcn-th {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: var(--fw-bold);
  color: var(--text-2);
  letter-spacing: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.bcn-td {
  font-size: 11px;
  color: var(--text);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* The design's veil: transparent at the top, the theme veil at the bottom. */
.bcn-veil {
  position: absolute;
  inset: 0;
  display: grid;
  place-items: center;
  background: linear-gradient(180deg, transparent 30%, var(--veil));
  pointer-events: none;
}
.bcn-pill {
  display: flex;
  align-items: center;
  gap: 8px;
  height: 32px;
  padding: 0 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-pill);
  background: var(--bg);
  box-shadow: var(--elev-1);
  font-size: var(--fs-xs);
  font-weight: var(--fw-semibold);
  color: var(--text);
}
.bcn-pill svg { color: var(--orange); }
.bcn-cta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
  margin: var(--s-4) var(--s-5) var(--s-5);
  color: var(--orange-text);
  font-size: var(--fs-base);
  font-weight: var(--fw-bold);
  animation: bcnRise 0.55s var(--ease-out) 0.45s both;
}
.bcn-arrow { display: grid; place-items: center; transition: transform 280ms var(--ease-out); }
.bcn:hover .bcn-arrow { transform: translateX(-4px); }

/* Narrow screens: floating button, BELOW the 56px chat header (never over it). */
.bcn-fab {
  position: fixed;
  top: 68px;
  right: var(--s-4);
  z-index: var(--z-menu);
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 36px;
  padding: 0 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  background: var(--bg);
  box-shadow: var(--float);
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  color: var(--text);
}
.bcn-fab:hover { border-color: var(--text); }
.bcn-fab.signal { border-color: var(--orange); }
.bcn-fab :deep(.ui-icon) { width: 16px; height: 16px; color: var(--orange); }
@media (prefers-reduced-motion: reduce) {
  .bcn-ico, .bcn-eyebrow, .bcn-title, .bcn-sub, .bcn-row, .bcn-peek, .bcn-cta, .bcn-dot.live { animation: none; }
  .bcn-ico, .bcn-tbl, .bcn-row, .bcn-arrow { transition: none; }
}
</style>
