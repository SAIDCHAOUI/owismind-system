<script setup>
// One dashboard widget: a common frame (title, the agent's comment, ONE plain
// "where does this data come from?" link) around the V1.3 renderers reused as they
// are (ArtifactChart / ArtifactTable / ArtifactKpi in their `bare` mode) or a
// markdown text block. No identifier, step number or kind label is shown. Every
// data widget is bound to ITS OWN sql_id: an orphan binding shows an honest empty
// state, never the rows of another query.
//
// Every widget carries a small toolbar: "expand" toggles the card between its compact
// width and the wide one (BoardGrid repacks the rows; default from layoutBoard, the
// user's choice is kept), and data widgets add "focus", the card alone, large, in the
// WidgetFocus overlay. A text widget is not a data card: it reads as a section of the
// analysis (no frame, a heading, filling its cell, its toolbar shown on hover
// or keyboard focus only) and has a provenance link only when it cites a sql_id. In that overlay (`focused`) the toolbar
// holds the close control only, and a KPI also lists its captured rows.
//
// On the board (`movable`) a grip handle leads the toolbar: pressing it arms the
// card for a native HTML5 drag (BoardGrid owns the drop logic and the indicator), and
// with the keyboard the arrow keys move the card one place earlier / later, Home / End
// to the first / last place (emitted as `move` with a delta, BoardGrid applies it).
import { computed, defineAsyncComponent, ref, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useWorkspaceStore } from '../../stores/workspace.js'
import { chartSpecForArtifact } from '../../composables/workspaceModel.js'
import ArtifactTable from '../evidence/ArtifactTable.vue'
import ArtifactKpi from '../evidence/ArtifactKpi.vue'
import WidgetText from './WidgetText.vue'
import { Icon } from '../ui'
// Lazy on purpose: chart.js is the heaviest dependency (same split as EvidencePanel).
const ArtifactChart = defineAsyncComponent(() => import('../evidence/ArtifactChart.vue'))

const props = defineProps({
  widget: { type: Object, required: true },
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
  // Rendered inside the focus overlay (WidgetFocus).
  focused: { type: Boolean, default: false },
  // The board lets the user rearrange this card (more than one card in its group).
  movable: { type: Boolean, default: false },
})
const emit = defineEmits(['move'])
const { t } = useI18n()
const ws = useWorkspaceStore()

const render = computed(() => ws.widgetData(props.widget))
// The exchange that owns this widget's query (its origin when carried from an earlier
// answer): the full rows are paged from THAT exchange, never by sql_id alone.
const ref_ = computed(() => ws.resultRef(props.widget))
const rowsExchangeId = computed(() => (ref_.value && ref_.value.exchangeId) || '')
const isData = computed(() => props.widget.kind !== 'text')
// Rows for this sql_id not available yet while the run is live or its stored
// document is loading: a waiting state (not an empty state - the figures are on their
// way). The card fills as soon as rows reach the store from any source.
const waiting = computed(() => isData.value && !render.value.orphan && !render.value.result && !render.value.data && render.value.pending)
const chartSpec = computed(() => chartSpecForArtifact(props.widget.chart))

// Toolbar: the focus level for data widgets with figures; the width toggle for every
// widget (hidden on a one-column board, where it would change nothing).
const tools = computed(() => isData.value && !render.value.orphan)
const canExpand = computed(() => !props.focused)
const expanded = computed(() => ws.isExpanded(props.widget.id))
const canMove = computed(() => props.movable && !props.focused)

// Drag arming: the card is draggable ONLY while the grip is pressed, so text
// selection, chart hovering and table scrolling inside the card keep working.
const armed = ref(false)
function disarm() {
  armed.value = false
  window.removeEventListener('pointerup', disarm)
}
function arm(e) {
  if (e.button !== undefined && e.button !== 0) return
  armed.value = true
  window.addEventListener('pointerup', disarm)
}
onBeforeUnmount(() => window.removeEventListener('pointerup', disarm))

const MOVE_KEYS = { ArrowLeft: -1, ArrowUp: -1, ArrowRight: 1, ArrowDown: 1, Home: -Infinity, End: Infinity }
function onMoveKey(e) {
  const delta = MOVE_KEYS[e.key]
  if (delta === undefined || e.altKey || e.ctrlKey || e.metaKey) return
  e.preventDefault()
  emit('move', delta)
}
// The provenance drawer lives in the Studio, under the overlay: leave the focus first.
function openProvenance() {
  if (props.focused) ws.closeFocus()
  ws.openProvenance(props.widget.sql_id, props.widget.id, props.widget.origin || null)
}
</script>

<template>
  <article
    class="widget"
    :class="['k-' + widget.kind, { orphan: render.orphan, focused }]"
    :data-widget-id="widget.id"
    :draggable="armed ? 'true' : undefined"
    @dragend="disarm"
  >
    <header class="w-head">
      <div class="w-titles">
        <component :is="focused ? 'h2' : 'h3'" :id="focused ? 'w-focus-title' : undefined" class="w-title">{{ widget.title }}</component>
        <p v-if="widget.comment" class="w-comment">{{ widget.comment }}</p>
      </div>
      <div v-if="tools || canMove || canExpand" class="w-tools">
        <!-- A span, not a <button>: Firefox never starts a drag from inside a button. -->
        <span
          v-if="canMove"
          role="button"
          tabindex="0"
          class="w-tool w-move"
          :title="t('ws.widget.move_hint')"
          :aria-label="t('ws.widget.move', [widget.title])"
          :aria-description="t('ws.widget.move_hint')"
          aria-keyshortcuts="ArrowLeft ArrowRight ArrowUp ArrowDown Home End"
          @pointerdown="arm"
          @keydown="onMoveKey"
        >
          <Icon name="grip" />
        </span>
        <template v-if="!focused">
          <button
            v-if="canExpand"
            type="button"
            class="w-tool w-expand"
            :aria-pressed="expanded"
            :title="t(expanded ? 'ws.widget.collapse' : 'ws.widget.expand')"
            :aria-label="t(expanded ? 'ws.widget.collapse' : 'ws.widget.expand')"
            @click="ws.toggleExpand(widget.id)"
          >
            <Icon :name="expanded ? 'narrow' : 'widen'" />
          </button>
          <button
            v-if="tools"
            type="button"
            class="w-tool"
            :title="t('ws.widget.focus')"
            :aria-label="t('ws.widget.focus')"
            @click="ws.focusWidget(widget.id)"
          >
            <Icon name="maximize" />
          </button>
        </template>
        <button
          v-else-if="focused"
          type="button"
          class="w-tool w-close"
          :title="t('ws.widget.close_focus')"
          :aria-label="t('ws.widget.close_focus')"
          @click="ws.closeFocus()"
        >
          <Icon name="x" />
        </button>
      </div>
    </header>

    <div class="w-body">
      <p v-if="render.orphan" class="w-orphan">{{ t('ws.widget.orphan') }}</p>
      <div v-else-if="waiting" class="w-wait">
        <span class="w-wait-dot" aria-hidden="true" />{{ t('ws.widget.waiting') }}
      </div>
      <ArtifactChart
        v-else-if="widget.kind === 'chart'"
        :chart="chartSpec"
        :data="render.data"
        :title="widget.title"
        bare
      />
      <ArtifactKpi
        v-else-if="widget.kind === 'kpi'"
        :data="render.data"
        :title="widget.title"
        :unit="(widget.kpi && widget.kpi.unit) || ''"
        bare
      />
      <ArtifactTable
        v-else-if="widget.kind === 'table'"
        :result="render.result"
        :exchange-id="rowsExchangeId"
        :sql-id="widget.sql_id || ''"
      />
      <WidgetText v-else :text="widget.text || ''" />
      <!-- Focus level: a KPI also shows the rows it was computed from, when captured. -->
      <ArtifactTable
        v-if="focused && widget.kind === 'kpi' && !waiting && render.result"
        class="w-kpi-rows"
        :result="render.result"
        :exchange-id="rowsExchangeId"
        :sql-id="widget.sql_id || ''"
      />
    </div>

    <!-- ONE plain link: where the figures come from (technical details stay inside). -->
    <footer v-if="widget.sql_id && !render.orphan" class="w-foot">
      <button
        type="button"
        class="w-prov"
        :class="{ active: ws.drawerWidgetId === widget.id && ws.drawerSqlId === widget.sql_id }"
        @click="openProvenance"
      >{{ t('ws.prov.where') }}</button>
    </footer>
  </article>
</template>

<style scoped>
.widget {
  display: flex;
  flex-direction: column;
  gap: var(--s-3);
  min-width: 0;
  padding: var(--s-4);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  background: var(--bg);
  animation: w-in var(--dur) var(--ease-out) both;
}
@keyframes w-in { from { opacity: 0; transform: translateY(6px); } }
@media (prefers-reduced-motion: reduce) { .widget { animation: none; } }
.w-head { display: flex; align-items: flex-start; gap: var(--s-3); min-width: 0; }
.w-titles { flex: 1 1 auto; display: flex; flex-direction: column; gap: 4px; min-width: 0; }
/* Toolbar: quiet ghost icon buttons, ink on hover; the keyboard focus ring is the
   global one (base.css). No orange here: enlarging is not a signal. */
.w-tools { flex: 0 0 auto; display: flex; gap: 2px; margin: -4px -6px 0 0; }
.w-tool {
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: var(--r-sm);
  color: var(--text-3);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.w-tool:hover { background: var(--surface-hover); color: var(--text); }
.w-tool[aria-pressed="true"] { color: var(--text); background: var(--surface-press); }
/* Grip: grab cursor, it is the only place a card can be picked up from. */
.w-move { cursor: grab; touch-action: none; }
.w-move:active { cursor: grabbing; }
.w-tool :deep(.ui-icon) { width: 15px; height: 15px; }
/* Where the width toggle changes nothing it is hidden: a one-column board (< 480px,
   BOARD_MEDIUM_MIN). */
@container (max-width: 479px) {
  .widget .w-expand { display: none; }
}
/* Text section: no card frame, a heading and a reading column. Its toolbar stays
   out of the way until the section is hovered or holds the keyboard focus (always
   shown on touch screens, where there is no hover). */
.widget.k-text {
  border-color: transparent;
  background: transparent;
  padding: var(--s-2) 0 var(--s-3);
  gap: var(--s-2);
}
.widget.k-text .w-title { font-size: var(--fs-md); font-weight: var(--fw-bold); letter-spacing: -0.01em; }
/* The section fills its cell (beside its figure, or the full row): a generous reading
   cap only. A long section spanning a wide board flows in two columns instead (BoardGrid
   sets .flow), so no void is left on the right. */
.widget.k-text .w-titles,
.widget.k-text .w-body { max-width: 90ch; }
.widget.k-text.flow .w-titles,
.widget.k-text.flow .w-body { max-width: none; }
/* Lines left alone at a column foot / head read as broken: keep at least 2 together. */
.widget.k-text.flow .w-body { columns: 2 32ch; column-gap: var(--s-6); orphans: 2; widows: 2; }
.widget.k-text.flow .w-body :deep(h1),
.widget.k-text.flow .w-body :deep(h2),
.widget.k-text.flow .w-body :deep(h3),
.widget.k-text.flow .w-body :deep(h4) { break-after: avoid; }
.widget.k-text.flow .w-body :deep(p),
.widget.k-text.flow .w-body :deep(li),
.widget.k-text.flow .w-body :deep(table),
.widget.k-text.flow .w-body :deep(pre),
.widget.k-text.flow .w-body :deep(blockquote) { break-inside: avoid; }
.widget.k-text .w-foot { border-top: none; padding-top: 0; }
@media (hover: hover) {
  .widget.k-text .w-tools { opacity: 0; transition: opacity var(--dur) var(--ease); }
  .widget.k-text:hover .w-tools,
  .widget.k-text:focus-within .w-tools { opacity: 1; }
}
.w-title {
  margin: 0;
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.w-comment {
  margin: 0;
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: var(--lh-text);
  text-wrap: pretty;
}
.w-body { min-width: 0; }
/* Expanded to the full row: the drawing gains some height to keep its proportions. */
.widget.expanded .w-body :deep(.art-fig.bare .art-canvas-wrap) { height: 320px; }
/* Focus overlay: the card fills the dialog, the drawing / rows take the height left. */
.widget.focused { height: 100%; min-height: 0; animation: none; }
.widget.focused .w-title { font-size: var(--fs-md); }
.widget.focused .w-tool { width: 32px; height: 32px; color: var(--text-2); }
.widget.focused .w-tool :deep(.ui-icon) { width: 16px; height: 16px; }
.widget.focused .w-body { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; gap: var(--s-4); overflow: auto; }
.widget.focused .w-body > :deep(.art-chart) { flex: 1 1 auto; min-height: 0; }
.widget.focused .w-body :deep(.art-fig.bare) { flex: 1 1 auto; min-height: 0; }
.widget.focused .w-body :deep(.art-fig.bare .art-canvas-wrap) { flex: 1 1 auto; height: auto; min-height: 320px; }
/* A focused table owns the height: its own viewport scrolls (the infinite-scroll
   observer is rooted on it), so the body itself does not. */
.widget.focused.k-table .w-body { overflow: hidden; }
.widget.focused.k-table .w-body > :deep(.art-table) { flex: 1 1 auto; min-height: 0; }
.widget.focused.k-table .w-body :deep(.art-table-box) { flex: 1 1 auto; min-height: 0; display: flex; flex-direction: column; }
.widget.focused.k-table .w-body :deep(.art-table-scroll) { flex: 1 1 auto; min-height: 0; max-height: none; }
.widget.focused .w-body :deep(.kpi-card.bare .kpi-value) { font-size: var(--fs-3xl); }
.w-orphan {
  margin: 0;
  padding: var(--s-4);
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: var(--lh-text);
}
.w-wait {
  display: flex;
  align-items: center;
  gap: 10px;
  min-height: 80px;
  font-size: var(--fs-sm);
  color: var(--text-3);
}
.w-wait-dot {
  width: 8px;
  height: 8px;
  flex: 0 0 8px;
  background: var(--orange);
  animation: w-pulse 1.15s ease-in-out infinite;
}
@keyframes w-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
@media (prefers-reduced-motion: reduce) { .w-wait-dot { animation: none; } }
.w-foot { border-top: 1px solid var(--border); padding-top: var(--s-3); }
.w-prov {
  font-size: var(--fs-sm);
  color: var(--text-2);
  text-decoration: underline;
  text-decoration-color: var(--border-strong);
  text-underline-offset: 3px;
  transition: color var(--dur) var(--ease);
}
.w-prov:hover { color: var(--text); text-decoration-color: var(--text); }
.w-prov.active { color: var(--orange-text); text-decoration-color: var(--orange); }
</style>
