<script setup>
// App shell layout - the `.app` grid (sidebar | main) with a draggable sidebar
// resize handle. When the Evidence Studio panel is open (`with-evidence`), the
// grid becomes sidebar | conversation (center, flexible) | evidence (RIGHT,
// fixed draggable width) - the proof panel docks on the right of the chat.
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useUiStore } from '../../stores/ui.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useSourcesStore } from '../../stores/sources.js'
import { useSessionStore } from '../../stores/session.js'
import { useChatStore } from '../../stores/chat.js'
import { shouldAutoDock } from '../../composables/sourceModel.js'
import Sidebar from './Sidebar.vue'
import MainTop from './MainTop.vue'
import EvidencePanel from '../evidence/EvidencePanel.vue'
import SourcePanel from '../sources/SourcePanel.vue'
import WorkspacePanel from '../workspace/WorkspacePanel.vue'
import { useWorkspaceStore } from '../../stores/workspace.js'
// BEGIN impersonation (temporary) - top banner shown while an admin views as a user.
// Removable: delete this import + the <ImpersonateBanner> in the template + the
// .shell wrapper, and the features/admin-impersonate folder.
import ImpersonateBanner from '../../features/admin-impersonate/ImpersonateBanner.vue'
// END impersonation (temporary)

const ui = useUiStore()
const evidence = useEvidenceStore()
const sources = useSourcesStore()
const session = useSessionStore()
const chat = useChatStore()
const workspace = useWorkspaceStore()
const route = useRoute()

// V2: the right column hosts ONE of three panels. The workspace (plan / journal /
// dashboard / data) has priority: its Data tab embeds the Evidence panel of the SAME
// exchange (evidence.open may then be true underneath it). The standalone Evidence
// panel remains for answers without a workspace (V1.3 history), Source Data last.
const wsOpen = computed(() => workspace.open)
const evStandalone = computed(() => evidence.open && !workspace.open)
const proofColumn = computed(() => wsOpen.value || evStandalone.value)
const dragging = ref(false)
const draggingEv = ref(false)
const draggingSrc = ref(false)

// Either the Evidence proof panel OR the standalone Source Data Explorer occupies the
// right column - they are mutually exclusive (see the watches below). The two panels
// size differently: Evidence keeps its pixel width + drag handle, Source Data uses
// the fraction-based docked layout (compact third / expanded two-thirds) with no drag.

// Arrival-screen auto-dock: the Source Data view is ON SCREEN by default - the user
// never has to discover a CTA and click it. Docked whenever the chat route shows an
// EMPTY conversation and the selected agent exposes sources, unless the user
// explicitly dismissed it (sticky per app session) or Evidence owns the column.
// Once a conversation starts the panel simply stays until Evidence takes over; it
// re-docks on the next new conversation.
//
// The bare-route guard (no :sessionId param) closes a boot race: deep-linking into
// an EXISTING conversation fetches /agents and /conversation concurrently, and if
// the agent list wins, `exchanges` is still empty - without the guard the dock
// would flash open (and fire meta+rows fetches) over a conversation being loaded.
// A conversation STARTED here gets its id stamped into the URL at the first
// exchange (ChatView), by which point exchanges > 0 blocks the dock anyway.
const autoDockKey = computed(() => {
  const a = session.selectedAgent
  return a && Array.isArray(a.sources) && a.sources.length ? a.key : ''
})
watch(
  [
    () => route.name,
    () => route.params.sessionId,
    autoDockKey,
    () => chat.exchanges.length,
    () => evidence.open,
    () => sources.dismissed,
    () => workspace.open,
  ],
  ([name, sid, key, exchanges, evOpen, dismissed, wsIsOpen]) => {
    const dock = shouldAutoDock({
      routeName: name,
      sessionParam: sid,
      agentKey: key,
      exchangeCount: exchanges,
      evidenceOpen: evOpen || wsIsOpen,
      dismissed,
      open: sources.open,
    })
    if (dock) sources.openPanel(key, { auto: true })
  },
  { immediate: true },
)

// The X opt-out only holds for the CURRENT empty screen (user decision 2026-08-13,
// "always show the teased data"): once a conversation starts or the user leaves the
// chat, clear it - the NEXT arrival screen auto-docks (and teases) again. Clearing
// only on these transitions is what prevents an X -> instant re-dock loop.
watch([() => chat.exchanges.length, () => route.name], ([exchangeCount, name]) => {
  if (exchangeCount > 0 || name !== 'chat') sources.undismissPanel()
})

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
watch([() => route.name, () => evidence.open, () => sources.open, () => workspace.open], ([name]) => {
  if (name !== 'chat') {
    workspace.close()
    evidence.close()
    sources.closePanel()
  }
})

// Mutual exclusion: only one right-column panel at a time. Opening one closes the
// other. The close actions bump their store's seq (aborting any in-flight commit) and
// set open=false, so the reciprocal watch fires with `false` and no loop can form.
watch(() => evidence.open, (open) => {
  if (open) sources.closePanel()
})
watch(() => sources.open, (open) => {
  if (open) {
    evidence.close()
    workspace.close()
  }
})
// Workspace <-> Evidence: opening the workspace closes Source Data; the proof panel of
// ANOTHER exchange (a V1.3 answer's Evidence button) replaces the workspace; closing
// the workspace also closes the Evidence panel its Data tab was hosting.
watch(() => workspace.open, (open) => {
  if (open) {
    sources.closePanel()
    if (evidence.open && evidence.exchangeId !== workspace.exchangeId) evidence.close()
  } else if (evidence.open && evidence.exchangeId === workspace.exchangeId) {
    evidence.close()
  }
})
watch(() => [evidence.open, evidence.exchangeId], ([open, id]) => {
  if (open && workspace.open && id !== workspace.exchangeId) workspace.close()
})

// A SPACE-HUNGRY right panel auto-collapses the conversation sidebar to give it
// room: the Evidence panel (pixel width) and a Source Data dock holding a large
// share of the canvas (via the expand toggle OR a manual drag). The compact dock
// coexists with the open sidebar, so the arrival screen keeps the conversation
// list visible. The user can re-expand at any time - we never force the sidebar
// back open on close, and the automatic collapse is NOT persisted
// (persistChoice=false): only an explicit user toggle decides what state the
// next session cold-starts with.
const srcHungry = computed(
  () =>
    sources.open
    && (sources.wide || ui.sourcesW > (window.innerWidth || 1280) * 0.45),
)
watch(
  [proofColumn, srcHungry],
  ([proofOpen, hungrySrc]) => {
    if (proofOpen || hungrySrc) ui.setSidebarCollapsed(true, false)
  },
)

// Expand/compact toggle <-> pixel width: the toggle drives PRESETS of the freely
// resizable width (a drag then fine-tunes from there). Applied only while open.
watch(() => sources.wide, (wideNow) => {
  if (!sources.open) return
  const w = window.innerWidth || 1280
  ui.setSourcesWidth(Math.round(w * (wideNow ? 0.58 : 0.32)))
})

// The panel width clamps sample window.innerWidth: re-clamp on resize so a
// window shrunk WHILE a panel is open can never leave a stale wide panel
// swallowing the chat column (and pushing the drag handle off-screen).
function onWindowResize() {
  if (proofColumn.value) ui.setEvidenceWidth(ui.evidenceW)
  if (sources.open) ui.setSourcesWidth(ui.sourcesW)
}
window.addEventListener('resize', onWindowResize)

const appStyle = computed(() => ({
  '--sidebar-w': ui.sidebarCollapsed ? '0px' : ui.sidebarW + 'px',
  '--evidence-w': ui.evidenceW + 'px',
  '--sources-w': ui.sourcesW + 'px',
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
function onSrcMove(e) {
  if (!draggingSrc.value) return
  // Same geometry as Evidence: the dock is the rightmost column.
  ui.setSourcesWidth(window.innerWidth - e.clientX)
}
function endResize() {
  if (!dragging.value && !draggingEv.value && !draggingSrc.value) return
  dragging.value = false
  draggingEv.value = false
  draggingSrc.value = false
  document.removeEventListener('pointermove', onMove)
  document.removeEventListener('pointermove', onEvMove)
  document.removeEventListener('pointermove', onSrcMove)
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
function startSrcResize(e) {
  if (e.button !== 0) return // primary button only
  e.currentTarget.setPointerCapture(e.pointerId)
  draggingSrc.value = true
  // Grabbing the splitter IS an engagement: lift the teaser blur quietly.
  sources.clearTeaser()
  document.addEventListener('pointermove', onSrcMove)
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
        'with-evidence': proofColumn,
        'with-sources': !proofColumn && sources.open,
        resizing: dragging || draggingEv || draggingSrc,
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
        v-if="proofColumn"
        class="resize-handle ev"
        :class="{ active: draggingEv }"
        @pointerdown.prevent="startEvResize"
      />
      <div
        v-if="!proofColumn && sources.open"
        class="resize-handle ev src"
        :class="{ active: draggingSrc }"
        @pointerdown.prevent="startSrcResize"
      />
      <WorkspacePanel v-if="wsOpen" />
      <EvidencePanel v-else-if="evStandalone" />
      <SourcePanel v-else-if="sources.open" />
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

/* Source Data DOCKED (arrival screen and beyond): a freely resizable pixel column
   (user ask 2026-08-13), same geometry as Evidence. The expand/compact toggle now
   drives PRESETS of this width; the splitter fine-tunes it. The pixel var animates
   through the existing grid-template-columns transition. */
.app.with-sources {
  grid-template-columns: var(--sidebar-w) 1fr var(--sources-w);
}
.app.sidebar-collapsed.with-sources {
  grid-template-columns: var(--rail-w) 1fr var(--sources-w);
}
.resize-handle.ev {
  left: auto;
  right: var(--evidence-w);
  margin-left: 0;
  margin-right: -5px;
}
.resize-handle.src { right: var(--sources-w); }
</style>
