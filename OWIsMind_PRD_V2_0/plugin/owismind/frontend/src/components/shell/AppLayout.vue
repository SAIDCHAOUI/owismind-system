<script setup>
// App shell layout - the `.app` grid (sidebar | main) with a draggable sidebar
// resize handle. When the Evidence Studio panel is open (`with-evidence`), the
// grid becomes sidebar | conversation (center, flexible) | evidence (RIGHT,
// fixed draggable width) - the proof panel docks on the right of the chat.
import { ref, computed, watch, onBeforeUnmount } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../../stores/ui.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useSourcesStore } from '../../stores/sources.js'
import { useSessionStore } from '../../stores/session.js'
import { useChatStore } from '../../stores/chat.js'
import { teaserState, isNarrow, studioWidth } from '../../composables/teaserModel.js'
import Sidebar from './Sidebar.vue'
import MainTop from './MainTop.vue'
import EvidencePanel from '../evidence/EvidencePanel.vue'
import SourcePanel from '../sources/SourcePanel.vue'
import WorkspacePanel from '../workspace/WorkspacePanel.vue'
import WorkspaceTeaser from '../workspace/WorkspaceTeaser.vue'
import { useWorkspaceStore } from '../../stores/workspace.js'
// BEGIN impersonation (temporary) - top banner shown while an admin views as a user.
// Removable: delete this import + the <ImpersonateBanner> in the template + the
// .shell wrapper, and the features/admin-impersonate folder.
import ImpersonateBanner from '../../features/admin-impersonate/ImpersonateBanner.vue'
// END impersonation (temporary)

const { t } = useI18n()
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

// V2 (user feedback 2026-10-15, design "beacon"): the arrival screen no longer
// auto-docks the Source Data panel. The right column shows a small clickable TEASER
// instead (composables/teaserModel.js): it opens the agent's data, or the last
// answer's workspace, on click. A workspace still opens on its own when a run
// builds its plan (design behavior); the teaser signals one built while closed.
const viewportW = ref(window.innerWidth || 1280)
const narrow = computed(() => isNarrow(viewportW.value))
const rightOpen = computed(() => proofColumn.value || sources.open)
const agentSources = computed(() => {
  const a = session.selectedAgent
  return a && Array.isArray(a.sources) ? a.sources : []
})
// The last answer of the active branch, when it built a workspace.
const lastWsExchange = computed(() => {
  const turns = chat.turns
  const last = turns.length ? turns[turns.length - 1].exchange : null
  if (!last) return null
  return last.hasWorkspace || workspace.hasContent(last.id, last.uid) ? last : null
})
const lastWsEntry = computed(() => {
  const ex = lastWsExchange.value
  return ex ? workspace.entryFor(ex.id, ex.uid) : null
})
const teaser = computed(() =>
  teaserState({
    routeName: route.name,
    rightPanelOpen: rightOpen.value,
    agentHasSources: agentSources.value.length > 0,
    workspaceReady: !!lastWsExchange.value,
    running: !!(lastWsEntry.value && lastWsEntry.value.running),
    unseen: !!lastWsExchange.value && lastWsExchange.value.id != null && workspace.unseenExchangeId === lastWsExchange.value.id,
    viewportWidth: viewportW.value,
  }),
)
const teaserColumn = computed(() => teaser.value.visible && !teaser.value.compact && !narrow.value)
const teaserAgentKey = computed(() => (session.selectedAgent ? session.selectedAgent.key : ''))
function openFromTeaser() {
  const ex = lastWsExchange.value
  if (teaser.value.mode === 'workspace' && ex) {
    if (ex.id) {
      Promise.resolve(workspace.openForExchange(ex.id, { uid: ex.uid })).catch(() => {})
    }
    return
  }
  const a = session.selectedAgent
  if (a) {
    openAtStudioShare(ui.setSourcesWidth)
    sources.openPanel(a.key)
  }
}
// The Studio opens at 70% of the width beside the collapsed rail and the chat keeps
// the other 30% (hard minimum): on its own when the agent starts a dashboard, from the
// beacon or from "Open the Studio". The rail is collapsed FIRST so the 70/30 clamp
// measures the final layout. The resize handle can only narrow it afterwards.
function openAtStudioShare(setWidth) {
  ui.setSidebarCollapsed(true, false)
  setWidth(studioWidth(viewportW.value, RAIL_PX))
}
const RAIL_PX = 60
watch(() => workspace.open, (open) => {
  if (open && !narrow.value) openAtStudioShare(ui.setEvidenceWidth)
})
// Bottom sheet (narrow screens): one tap outside closes the open right panel. When
// that panel is the Studio it is an explicit user close: sticky for a live run (no
// automatic Studio re-open); closing another panel leaves the run untouched.
function closeRight() {
  workspace.close(workspace.open ? { byUser: true } : undefined)
  evidence.close()
  sources.closePanel()
}

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
    if (evidence.open && !workspace.hostsEvidence(evidence.exchangeId)) evidence.close()
  } else if (evidence.open && workspace.hostsEvidence(evidence.exchangeId)) {
    evidence.close()
  }
})
// The Studio's Data tab may host the Evidence of a carried widget's ORIGIN answer
// (continued Studio): that one belongs to the Studio too (workspace.hostsEvidence).
watch(() => [evidence.open, evidence.exchangeId], ([open, id]) => {
  if (open && workspace.open && !workspace.hostsEvidence(id)) workspace.close()
})
// The Studio's auto-open never pre-empts a right panel the USER opened (Source Data
// past its auto-dock teaser, a standalone Evidence panel) and never opens off the chat
// route: the store defers it until the chat shows with no such panel. A deferred open
// never crosses conversations: chat.openSession / newConversation drop it, and the
// store also skips a deferred run of another conversation than `sessionId`.
watch(() => chat.activeSessionId, () => workspace.clearDeferred())
watch(
  () => [(sources.open && !sources.teaser) || evStandalone.value, route.name === 'chat', chat.activeSessionId],
  ([otherPanel, onChat, sessionId]) => workspace.setPanelContext({ otherPanel, onChat, sessionId }),
  { immediate: true },
)

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
  [proofColumn, srcHungry, narrow],
  ([proofOpen, hungrySrc, isNarrowNow]) => {
    if (proofOpen || hungrySrc || isNarrowNow) ui.setSidebarCollapsed(true, false)
  },
  { immediate: true },
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
  viewportW.value = window.innerWidth || viewportW.value
  if (proofColumn.value) ui.setEvidenceWidth(ui.evidenceW)
  if (sources.open) ui.setSourcesWidth(ui.sourcesW)
}
window.addEventListener('resize', onWindowResize)
// Expanding / resizing the left sidebar eats into the same width: re-clamp the right
// panel so the chat never drops under its 30% share.
watch([() => ui.sidebarCollapsed, () => ui.sidebarW], () => {
  if (proofColumn.value) ui.setEvidenceWidth(ui.evidenceW)
  if (sources.open) ui.setSourcesWidth(ui.sourcesW)
})

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
        'with-evidence': !narrow && proofColumn,
        'with-sources': !narrow && !proofColumn && sources.open,
        'with-teaser': teaserColumn,
        narrow,
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
        v-if="proofColumn && !narrow"
        class="resize-handle ev"
        :class="{ active: draggingEv }"
        @pointerdown.prevent="startEvResize"
      />
      <div
        v-if="!proofColumn && sources.open && !narrow"
        class="resize-handle ev src"
        :class="{ active: draggingSrc }"
        @pointerdown.prevent="startSrcResize"
      />
      <!-- Right column (wide) or bottom sheet (narrow): ONE panel at a time. -->
      <div v-if="narrow && rightOpen" class="sheet-backdrop" :aria-label="t('ws.sheet.close')" @click="closeRight" />
      <div v-if="rightOpen" class="right-host" :class="{ sheet: narrow }">
        <WorkspacePanel v-if="wsOpen" />
        <EvidencePanel v-else-if="evStandalone" />
        <SourcePanel v-else-if="sources.open" />
      </div>
      <WorkspaceTeaser
        v-else-if="teaser.visible"
        :teaser="{ ...teaser, compact: teaser.compact || narrow }"
        :agent-key="teaserAgentKey"
        :sources="agentSources"
        @open="openFromTeaser"
      />
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
  /* V2 Studio: ONE gray canvas behind sidebar, header and chat; the Studio, the
     beacon and the prompt float on it as cards. */
  background: var(--canvas);
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
/* The sidebar is a distinct PAPER column with a 1px right edge against the canvas
   (light: white on grey; dark: the paper step above the black canvas), so users find
   their conversations at a glance. The chat column keeps the canvas; the prompt card
   goes back to paper. */
.app :deep(.sidebar) {
  --bg: var(--paper);
  background: var(--paper);
  border-right-color: var(--border);
}
.main { --bg: var(--canvas); background: var(--canvas); }
.main :deep(.main-top) { border-bottom-color: transparent; }
.main :deep(.prompt) { --bg: var(--paper); }

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

/* Teaser column (no right panel open, wide screens): a narrow beacon on the right. */
.app.with-teaser {
  grid-template-columns: var(--sidebar-w) 1fr var(--teaser-w, 320px);
}
.app.sidebar-collapsed.with-teaser {
  grid-template-columns: var(--rail-w) 1fr var(--teaser-w, 320px);
}
/* The right panel host fills its grid cell; the panel inside owns the layout. */
.right-host {
  display: flex;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  /* The Studio floats: a paper card inset 12px from the viewport edges. */
  margin: 12px 12px 12px 0;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--paper);
  box-shadow: var(--float-strong);
  --bg: var(--paper);
}
.right-host > * { flex: 1 1 auto; min-width: 0; }
.right-host > :deep(.src-panel) { background: var(--paper); border-left: 0; }
/* Narrow screens: no right column at all (no horizontal scroll); the open panel
   becomes a bottom sheet over the chat, closed by tapping outside. */
.app.narrow,
.app.narrow.sidebar-collapsed {
  grid-template-columns: var(--rail-w) minmax(0, 1fr);
}
.right-host.sheet {
  /* Narrow screens: the Studio covers the whole screen (its header closes it). */
  position: fixed;
  inset: 0;
  margin: 0;
  z-index: var(--z-overlay);
  border: 0;
  border-radius: 0;
  box-shadow: none;
  animation: sheet-in var(--dur-slow) var(--ease-out) both;
}
@keyframes sheet-in { from { transform: translateY(24px); opacity: 0; } }
.sheet-backdrop {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: var(--veil);
}
@media (prefers-reduced-motion: reduce) {
  .right-host.sheet { animation: none; }
}
</style>
