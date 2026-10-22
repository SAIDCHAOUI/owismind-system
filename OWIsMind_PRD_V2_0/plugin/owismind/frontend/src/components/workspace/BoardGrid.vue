<script setup>
// Dashboard tab - every widget the agent published (but the analysis scope, shown in
// the Studio header), in ONE grid that reads like the answer, top to bottom (text
// sections, charts, tables and KPI cards interleaved in the user's order). The grid
// has 4 tracks on a wide board, 2 on a medium one and 1 on a narrow one (boardTracks,
// from the board width measured here) and every card gets the span computed by
// layoutBoard (composables/boardOrder.js): a section text sits beside the figure it
// explains (or on a full row above a wide one), KPI cards share a row and never
// stretch, and the last text / chart / table of a row fills what is left, so the
// board never shows a hole. Every widget has a width toggle; the user's choice is
// kept per answer and the packing still applies.
//
// The user arranges the board: each card's grip starts a native HTML5 drag (no
// library), an orange insertion bar shows where it lands (before / after the card
// under the pointer, on the axis the cards are laid out on), and with the keyboard
// the grip's arrow keys move the card one place (WidgetCard emits `move`). Moves are
// announced to screen readers. The order lives in the workspace store (per answer,
// remembered by the browser); the grid never uses `dense` packing, so the user's
// order is exactly the visual order.
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { boardTracks } from '../../composables/boardOrder.js'
import { useWorkspaceStore } from '../../stores/workspace.js'
import WidgetCard from './WidgetCard.vue'

const props = defineProps({
  state: { type: Object, required: true },
  running: { type: Boolean, default: false },
})
const { t } = useI18n()
const ws = useWorkspaceStore()
const widgets = computed(() => ws.boardList)
const ids = computed(() => widgets.value.map((w) => w.id))
const empty = computed(() => !widgets.value.length)
const tracks = computed(() => ws.boardTracks)

// A standalone section text spanning a wide board flows in two columns when long
// enough (no right-hand void beside a short line column).
const FLOW_MIN_CHARS = 280

const root = ref(null)
// The store lays the board out for the live track count (layoutBoard).
let ro = null
onMounted(() => {
  if (!root.value || typeof ResizeObserver !== 'function') return
  ro = new ResizeObserver((entries) => {
    const w = entries[0] && entries[0].contentRect ? entries[0].contentRect.width : 0
    if (w > 0) ws.setBoardTracks(boardTracks(w))
  })
  ro.observe(root.value)
})
onBeforeUnmount(() => {
  if (ro) ro.disconnect()
  ro = null
})

// Screen-reader announcement of the last move (polite live region).
const announce = ref('')
function say(text) {
  // Re-announce an identical sentence: clear first, set on the next tick.
  announce.value = ''
  nextTick(() => { announce.value = text })
}
function titleOf(id) {
  const w = widgets.value.find((x) => x.id === id)
  return (w && w.title) || ''
}

// --- keyboard ---------------------------------------------------------------------------

function keyMove(widget, delta) {
  const r = ws.moveWidgetBy(widget.id, ids.value, delta)
  if (r.index < 0) return
  if (r.moved) say(t('ws.board.moved', [widget.title, r.index + 1, r.count]))
  else say(t(r.index === 0 ? 'ws.board.move_first' : 'ws.board.move_last', [widget.title]))
  // The keyed list moved the card's DOM node: give the focus back to its grip.
  if (r.moved) {
    nextTick(() => {
      const card = root.value && root.value.querySelector('[data-widget-id="' + CSS.escape(widget.id) + '"] .w-move')
      if (card) card.focus()
    })
  }
}

// --- drag and drop (native HTML5) -------------------------------------------------------

const dragId = ref(null)
// The insertion point under the pointer: { id, after, axis } (null = none).
const drop = ref(null)

function onDragStart(e, widget) {
  // Only the card itself (armed by its grip) starts a move; a link or an image
  // dragged from inside a card is not a board move.
  if (e.target !== e.currentTarget) return
  dragId.value = widget.id
  drop.value = null
  if (e.dataTransfer) {
    e.dataTransfer.effectAllowed = 'move'
    // Firefox only starts a drag that carries data.
    try { e.dataTransfer.setData('text/plain', widget.title || widget.id) } catch (err) { /* ignore */ }
  }
}

function onDragOver(e, widget) {
  const from = dragId.value
  if (!from) return
  e.preventDefault()
  if (e.dataTransfer) e.dataTransfer.dropEffect = 'move'
  if (widget.id === from) {
    drop.value = null
    return
  }
  const rect = e.currentTarget.getBoundingClientRect()
  const host = e.currentTarget.parentElement
  const hostW = host ? host.getBoundingClientRect().width : rect.width
  // A card spanning its row (expanded, a table, a one-column board) is laid out
  // vertically: before / after = upper / lower half. Otherwise left / right half.
  const axis = rect.width > hostW * 0.75 ? 'y' : 'x'
  const after = axis === 'y' ? e.clientY > rect.top + rect.height / 2 : e.clientX > rect.left + rect.width / 2
  const cur = drop.value
  if (!cur || cur.id !== widget.id || cur.after !== after || cur.axis !== axis) drop.value = { id: widget.id, after, axis }
}

// The gaps between cards: dropping there lands at the last insertion point shown.
function onGapOver(e) {
  if (dragId.value) e.preventDefault()
}

function onDrop(e) {
  const from = dragId.value
  const target = drop.value
  if (!from) return
  e.preventDefault()
  if (target && ws.moveWidget(from, target.id, target.after)) {
    say(t('ws.board.moved', [titleOf(from), ids.value.indexOf(from) + 1, ids.value.length]))
  }
  endDrag()
}

function endDrag() {
  dragId.value = null
  drop.value = null
}

function spanOf(w) {
  const it = ws.boardSpans[w.id]
  return Math.min(it ? it.span : 1, tracks.value)
}
function cardClass(w) {
  const d = drop.value
  const it = ws.boardSpans[w.id]
  const span = spanOf(w)
  return {
    // Large on the board (more than half of it): the drawing gains some height.
    expanded: tracks.value > 1 && span > tracks.value / 2,
    paired: !!(it && it.paired),
    flow: w.kind === 'text' && tracks.value >= 4 && span === tracks.value && (w.text || '').length >= FLOW_MIN_CHARS,
    dragging: dragId.value === w.id,
    ['drop-' + (d && d.axis) + '-' + (d && d.after ? 'after' : 'before')]: !!(d && d.id === w.id),
  }
}
function cardEvents(w) {
  return {
    dragstart: (e) => onDragStart(e, w),
    dragover: (e) => onDragOver(e, w),
    drop: onDrop,
    dragend: endDrag,
  }
}
</script>

<template>
  <div ref="root" class="board">
    <div v-if="empty" class="empty">
      <div class="empty-t">{{ t('ws.board.empty_t') }}</div>
      <p class="empty-b">{{ t('ws.board.empty_b') }}</p>
    </div>
    <div v-else class="grid" :style="{ '--tracks': tracks }" @dragover="onGapOver" @drop="onDrop">
      <WidgetCard
        v-for="w in widgets"
        :key="w.id"
        :widget="w"
        :state="state"
        :running="running"
        :movable="widgets.length > 1"
        :class="cardClass(w)"
        :style="{ gridColumn: 'span ' + spanOf(w) }"
        v-on="cardEvents(w)"
        @move="(delta) => keyMove(w, delta)"
      />
    </div>
    <p class="sr-only" aria-live="polite" aria-atomic="true">{{ announce }}</p>
  </div>
</template>

<style scoped>
.board {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  gap: var(--s-4);
}
/* `--tracks` columns (boardTracks of the measured width); each card's span comes from
   layoutBoard. Cards of a row stretch to the row height (a text beside its figure). */
.grid {
  --drop-gap: var(--s-4);
  display: grid;
  grid-template-columns: repeat(var(--tracks, 1), minmax(0, 1fr));
  gap: var(--s-4);
}
/* A KPI card keeps its own height next to a taller chart. */
.grid > .k-kpi { align-self: start; }

/* Drag and drop. The card being moved fades and gets a dashed frame; the insertion
   point is ONE orange bar centred in the gap before / after the card under the
   pointer (orange = a transient signal, never shown at rest). */
.grid > * { position: relative; }
.dragging { opacity: 0.45; border-style: dashed; }
.drop-x-before::after,
.drop-x-after::after,
.drop-y-before::after,
.drop-y-after::after {
  content: '';
  position: absolute;
  background: var(--orange);
  pointer-events: none;
}
.drop-x-before::after,
.drop-x-after::after { top: 0; bottom: 0; width: 3px; }
.drop-x-before::after { left: calc(var(--drop-gap) / -2 - 1.5px); }
.drop-x-after::after { right: calc(var(--drop-gap) / -2 - 1.5px); }
.drop-y-before::after,
.drop-y-after::after { left: 0; right: 0; height: 3px; }
.drop-y-before::after { top: calc(var(--drop-gap) / -2 - 1.5px); }
.drop-y-after::after { bottom: calc(var(--drop-gap) / -2 - 1.5px); }

.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  margin: -1px;
  padding: 0;
  overflow: hidden;
  clip: rect(0 0 0 0);
  white-space: nowrap;
  border: 0;
}
.empty { max-width: 440px; padding: var(--s-6) 0; }
.empty-t { font-size: var(--fs-base); font-weight: var(--fw-bold); padding-bottom: 8px; }
.empty-b { margin: 0; font-size: var(--fs-sm); color: var(--text-2); line-height: var(--lh-text); }
</style>
