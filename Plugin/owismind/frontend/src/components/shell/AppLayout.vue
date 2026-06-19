<script setup>
// App shell layout - the `.app` grid (sidebar | main) with a draggable sidebar
// resize handle. When the Evidence Studio panel is open (`with-evidence`), the
// grid becomes sidebar | conversation (center, flexible) | evidence (RIGHT,
// fixed draggable width) - the proof panel docks on the right of the chat.
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '../../stores/ui.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useSessionStore } from '../../stores/session.js'
import Sidebar from './Sidebar.vue'
import MainTop from './MainTop.vue'
import EvidencePanel from '../evidence/EvidencePanel.vue'
// BEGIN impersonation (temporary) - top banner shown while an admin views as a user.
// Removable: delete this import + the <ImpersonateBanner> in the template + the
// .shell wrapper, and the features/admin-impersonate folder.
import ImpersonateBanner from '../../features/admin-impersonate/ImpersonateBanner.vue'
// END impersonation (temporary)

const ui = useUiStore()
const evidence = useEvidenceStore()
const session = useSessionStore()
const route = useRoute()
const dragging = ref(false)
const draggingEv = ref(false)

// The proof panel only makes sense NEXT TO a conversation: leaving the chat route
// (Settings, FAQ, Agents…) closes it so the page renders in the main column -
// never squeezed beside a stale panel. Coming back to a conversation re-opens it
// via the chat store's evidence continuity (ensureSession's skip path or
// openSession → _autoOpenEvidence).
//
// Watching `evidence.open` TOO (not just the route) closes the two async leaks:
// an auto-open whose /evidence/meta resolves AFTER the user navigated away, and
// an end-of-run auto-open fired while the user sits on a non-chat page (the poll
// loop lives in the store and survives ChatView's unmount). close() is idempotent
// and bumps the store's seq, which also aborts any still-in-flight auto commit.
// Default pre-flush timing closes the panel before paint - no visual flash.
watch([() => route.name, () => evidence.open], ([name]) => {
  if (name !== 'chat') evidence.close()
})

// Opening Evidence auto-collapses the conversation sidebar to give the panel
// room; the expand toggle stays visible in MainTop (it shows whenever the
// sidebar is collapsed). The user can re-expand at any time - we never force
// the sidebar back open on close, and the automatic collapse is NOT persisted
// (persistChoice=false): only an explicit user toggle may decide what state
// the next session cold-starts with.
watch(() => evidence.open, (open) => {
  if (open) ui.setSidebarCollapsed(true, false)
})

// The evidence width clamp samples window.innerWidth: re-clamp on resize so a
// window shrunk WHILE the panel is open can never leave a stale wide panel
// swallowing the chat column (and pushing the drag handle off-screen).
function onWindowResize() {
  if (evidence.open) ui.setEvidenceWidth(ui.evidenceW)
}
window.addEventListener('resize', onWindowResize)

const appStyle = computed(() => ({
  '--sidebar-w': ui.sidebarCollapsed ? '0px' : ui.sidebarW + 'px',
  '--evidence-w': ui.evidenceW + 'px',
}))

function onMove(e) {
  if (!dragging.value) return
  ui.setSidebarWidth(e.clientX)
}
function onEvMove(e) {
  if (!draggingEv.value) return
  // The evidence panel is the RIGHTMOST column: its width grows leftwards.
  ui.setEvidenceWidth(window.innerWidth - e.clientX)
}
function endResize() {
  if (!dragging.value && !draggingEv.value) return
  dragging.value = false
  draggingEv.value = false
  document.removeEventListener('pointermove', onMove)
  document.removeEventListener('pointermove', onEvMove)
  document.removeEventListener('pointerup', endResize)
  document.body.style.userSelect = ''
  document.body.style.cursor = ''
}
function _grabCursor() {
  document.addEventListener('pointerup', endResize)
  document.body.style.userSelect = 'none'
  document.body.style.cursor = 'col-resize'
}
function startResize(e) {
  if (e.button !== 0 || ui.sidebarCollapsed) return // primary button only
  // Capture the pointer: a release outside the DSS iframe still fires
  // pointerup on the handle (bubbling to the document listener), so the
  // drag can never get stuck.
  e.currentTarget.setPointerCapture(e.pointerId)
  dragging.value = true
  document.addEventListener('pointermove', onMove)
  _grabCursor()
}
function startEvResize(e) {
  if (e.button !== 0) return // primary button only
  e.currentTarget.setPointerCapture(e.pointerId)
  draggingEv.value = true
  document.addEventListener('pointermove', onEvMove)
  _grabCursor()
}
onBeforeUnmount(() => {
  window.removeEventListener('resize', onWindowResize)
  endResize()
})
</script>

<template>
  <!-- BEGIN impersonation (temporary) - the shell wrapper stacks the read-only
       banner above the app grid while an admin views as a user. When not
       impersonating, the wrapper just holds the grid (no visual change). -->
  <div class="shell">
    <ImpersonateBanner v-if="session.impersonating" />
    <!-- END impersonation (temporary) -->
    <div
      class="app"
      :class="{
        'sidebar-collapsed': ui.sidebarCollapsed,
        'with-evidence': evidence.open,
        resizing: dragging || draggingEv,
      }"
      :style="appStyle"
    >
      <Sidebar />
      <div
        class="resize-handle left"
        :class="{ active: dragging }"
        @pointerdown.prevent="startResize"
      />
      <main class="main">
        <MainTop />
        <RouterView />
      </main>
      <div
        v-if="evidence.open"
        class="resize-handle ev"
        :class="{ active: draggingEv }"
        @pointerdown.prevent="startEvResize"
      />
      <EvidencePanel v-if="evidence.open" />
    </div>
  </div>
</template>

<style scoped>
/* BEGIN impersonation (temporary) - the shell wrapper stacks the read-only banner
   above the app grid. Without a banner it is a plain full-height column holding the
   grid, so the layout is byte-identical to before. With the banner, the grid fills
   the remaining height (min-height: 0 lets the grid's own overflow work). */
.shell {
  display: flex;
  flex-direction: column;
  height: 100vh;
}
.shell > .app { flex: 1; min-height: 0; height: auto; }
/* END impersonation (temporary) */
.app {
  --sidebar-w: 260px;
  display: grid;
  grid-template-columns: var(--sidebar-w) 1fr;
  grid-template-rows: 1fr;
  height: 100vh;
  position: relative;
  /* Smooth same-track-count column changes (sidebar collapse/expand). Track-count
     changes (evidence open/close) are not interpolable and snap - the panel's own
     slide-in carries the perceived motion there. */
  transition: grid-template-columns var(--dur-slow) var(--ease);
}
/* Live drags must track the pointer 1:1 - a transition would rubber-band them. */
.app.resizing { transition: none; }
@media (prefers-reduced-motion: reduce) {
  .app { transition: none; }
}
/* Collapsed = a thin icon RAIL (not fully hidden): keeps New conversation, nav,
   help and the account avatar one click away while freeing the canvas. */
.app.sidebar-collapsed {
  grid-template-columns: var(--rail-w) 1fr;
}

.resize-handle {
  position: absolute;
  top: 0;
  bottom: 0;
  width: 10px;
  margin-left: -5px;
  cursor: col-resize;
  z-index: var(--z-menu);
  background: transparent;
  user-select: none;
  touch-action: none;
}
.resize-handle::after {
  content: "";
  position: absolute;
  top: 0;
  bottom: 0;
  left: 4px;
  width: 2px;
  background: transparent;
  transition: background var(--dur) var(--ease);
  pointer-events: none;
}
.resize-handle:hover::after,
.resize-handle.active::after { background: var(--orange); }
.resize-handle.left { left: var(--sidebar-w); }
.app.sidebar-collapsed .resize-handle.left { display: none; }

.main {
  display: flex;
  flex-direction: column;
  overflow: hidden;
  min-width: 0;
  position: relative;
}

/* Evidence open: sidebar | conversation (center, flexible) | evidence (right). */
.app.with-evidence {
  grid-template-columns: var(--sidebar-w) 1fr var(--evidence-w);
}
.app.sidebar-collapsed.with-evidence {
  grid-template-columns: var(--rail-w) 1fr var(--evidence-w);
}
.app.with-evidence .main {
  border-right: 1px solid var(--border);
}
.resize-handle.ev {
  left: auto;
  right: var(--evidence-w);
  margin-left: 0;
  margin-right: -5px;
}
</style>
