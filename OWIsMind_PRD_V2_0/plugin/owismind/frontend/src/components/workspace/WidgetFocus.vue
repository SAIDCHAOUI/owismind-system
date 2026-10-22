<script setup>
// Focus level of a dashboard widget: ONE widget shown alone, large, above the whole
// app (teleported to <body>: the Studio card clips its content). It renders the SAME
// WidgetCard in its `focused` mode (chart redrawn at the dialog size, table paged in
// its own viewport, KPI with its captured rows). Closes on Escape, on the scrim and
// on the card's close control; keyboard focus stays inside the dialog while it is
// open and returns to the control that opened it. Same scrim rules as ui/Modal.vue
// (flat, no blur).
import { computed, ref, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import { useWorkspaceStore } from '../../stores/workspace.js'
import WidgetCard from './WidgetCard.vue'

const ws = useWorkspaceStore()
const dialog = ref(null)
let lastFocused = null

const widget = computed(() => {
  const id = ws.focusWidgetId
  const list = (ws.state && ws.state.widgets) || []
  return id ? list.find((w) => w.id === id) || null : null
})
const running = computed(() => !!(ws.shown && ws.shown.running))

// The focused widget left the board (document re-projected, entry changed): close.
watch(widget, (w) => {
  if (!w && ws.focusWidgetId) ws.closeFocus()
})

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

function focusables() {
  const root = dialog.value
  return root ? Array.from(root.querySelectorAll(FOCUSABLE)).filter((el) => el.offsetParent !== null) : []
}

function onKey(e) {
  if (e.key === 'Escape') {
    e.preventDefault()
    e.stopPropagation()
    ws.closeFocus()
    return
  }
  if (e.key !== 'Tab') return
  // Focus trap: Tab / Shift+Tab cycle through the dialog's own controls.
  const els = focusables()
  if (!els.length) {
    e.preventDefault()
    dialog.value && dialog.value.focus()
    return
  }
  const first = els[0]
  const last = els[els.length - 1]
  const active = document.activeElement
  const inside = dialog.value && dialog.value.contains(active)
  if (e.shiftKey && (active === first || !inside)) {
    e.preventDefault()
    last.focus()
  } else if (!e.shiftKey && (active === last || !inside)) {
    e.preventDefault()
    first.focus()
  }
}

function onScrim(e) {
  // Only the scrim itself (not a press that started inside the card).
  if (e.target === e.currentTarget) ws.closeFocus()
}

onMounted(async () => {
  lastFocused = document.activeElement
  document.addEventListener('keydown', onKey, true)
  await nextTick()
  const els = focusables()
  // Land on the close control (first control of the card header) so Escape / Enter
  // both work at once; the dialog itself when nothing is focusable yet.
  const close = dialog.value && dialog.value.querySelector('.w-close')
  ;(close || els[0] || dialog.value)?.focus()
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey, true)
  if (lastFocused && typeof lastFocused.focus === 'function' && document.contains(lastFocused)) lastFocused.focus()
  lastFocused = null
})
</script>

<template>
  <Teleport to="body">
    <div v-if="widget" class="wf-scrim" @mousedown="onScrim">
      <div
        ref="dialog"
        class="wf-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby="w-focus-title"
        tabindex="-1"
      >
        <WidgetCard :widget="widget" :state="ws.state" :running="running" focused />
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Flat scrim (charter: no blur, no gradient), same values as ui/Modal.vue. */
.wf-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px;
  background: rgba(0, 0, 0, 0.55);
  animation: wf-fade var(--dur) var(--ease-out) both;
}
:global(body[data-theme="dark"] .wf-scrim) { background: rgba(0, 0, 0, 0.65); }
.wf-dialog {
  display: flex;
  flex-direction: column;
  width: 92vw;
  height: 88vh;
  max-width: 1600px;
  min-height: 0;
  outline: none;
  animation: wf-in var(--dur) var(--ease-out) both;
}
/* The card is the dialog surface: same frame as on the board, the floating level. */
.wf-dialog > :deep(.widget) {
  flex: 1 1 auto;
  padding: var(--s-5);
  background: var(--paper);
  box-shadow: var(--float-strong);
}
@keyframes wf-fade { from { opacity: 0; } }
@keyframes wf-in { from { opacity: 0; transform: translateY(8px); } }
@media (prefers-reduced-motion: reduce) {
  .wf-scrim,
  .wf-dialog { animation: none; }
}
</style>
