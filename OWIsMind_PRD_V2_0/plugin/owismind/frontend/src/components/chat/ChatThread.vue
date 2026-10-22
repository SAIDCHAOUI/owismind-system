<script setup>
// Conversation thread - renders the ACTIVE PATH (turns) of the conversation tree and
// follows the streaming answer. Each turn is one user bubble (the active version's prompt,
// with hover edit) + one agent message (the active version, with turn-level version arrows
// + regenerate). MessageUser / MessageAgent read useChatStore() directly and call
// chat.editTurn / regenerateTurn / setTurnVersion - no prop-drilling, just the `turn`.
//
// The scroll "signature" includes the last turn's streaming version timeline length + text
// length + status + its versionIdx so we re-evaluate scroll on every poll tick (L020).
//
// Auto-scroll is STICKY-aware: it only pins to the bottom while the user is already near
// the bottom. If the user scrolls up to read earlier output mid-stream, we stop
// auto-scrolling and let them read; sending a new message re-pins to the bottom.
//
// Answer landing: when a run ends and the reader followed it to the bottom, a long final
// answer is scrolled back to its START (steps line just above it kept in view) so the
// reader begins at the top instead of the end. Opening a conversation from history lands
// the same way on its last answer (or at the bottom when it fits). The landing point is
// then ANCHORED: later layout changes (Evidence / Studio column, late renders) re-apply it
// until the user scrolls by hand. Decisions live in composables/chatScrollModel.js.
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount } from 'vue'
import MessageUser from './MessageUser.vue'
import MessageAgent from './MessageAgent.vue'
import { timelineSignature } from '../../composables/timelineModel.js'
import { useReducedMotion } from '../../composables/useReducedMotion.js'
import {
  contentOffset,
  shouldLandOnCompletion,
  answerLandingTop,
  scrollBehavior,
} from '../../composables/chatScrollModel.js'
import { useChatStore } from '../../stores/chat.js'
import { useEvidenceStore } from '../../stores/evidence.js'
import { useSourcesStore } from '../../stores/sources.js'

const props = defineProps({
  turns: { type: Array, required: true },
})

const chat = useChatStore()
const evidence = useEvidenceStore()
const sources = useSourcesStore()
const reduced = useReducedMotion()

const scroller = ref(null)
const inner = ref(null)
// How close to the bottom (px) still counts as "following" the stream.
const NEAR_BOTTOM_PX = 120
let stick = true
// Answer landing anchor: true while the view rests on the last answer's start.
let anchored = false
// Run bookkeeping for the completion landing.
let runUid = null
let runStartedAt = 0
let lastIntentAt = 0
let leftBottomDuringRun = false
let resizeObs = null

const signature = computed(() => {
  const arr = props.turns
  let s = String(arr.length)
  const last = arr[arr.length - 1]
  if (last) {
    s += `|${timelineSignature(last.exchange.version)}|${last.versionIdx}`
  }
  return s
})

const lastUid = () => {
  const last = props.turns[props.turns.length - 1]
  return last ? last.exchange.uid : null
}

function onScroll() {
  const el = scroller.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
  // Only a scroll the USER caused (wheel / touch / key / scrollbar since the run began)
  // counts as leaving the stream; programmatic pins never set this flag.
  if (chat.sending && !stick && lastIntentAt >= runStartedAt) leftBottomDuringRun = true
}
// Any manual scroll intent releases the landing anchor (never fight the user).
function onUserIntent() {
  lastIntentAt = Date.now()
  anchored = false
}

// Measures of the last agent message, in scroll-content coordinates.
function measureLastAnswer(el) {
  const msgs = el.querySelectorAll('[data-agent-msg]')
  const msg = msgs[msgs.length - 1]
  if (!msg) return null
  const base = el.getBoundingClientRect().top
  const st = el.scrollTop
  const off = (node) => (node ? contentOffset(node.getBoundingClientRect().top, base, st) : null)
  const body = msg.querySelector('[data-answer-body]')
  return {
    viewportHeight: el.clientHeight,
    answerTop: body ? off(body) : off(msg),
    answerBottom: contentOffset(msg.getBoundingClientRect().bottom, base, st),
    leadTop: off(msg.querySelector('[data-answer-lead]')),
  }
}
// Scroll to the start of the last answer when it is taller than the viewport.
// Returns false (and does nothing) when it fits.
function landOnLastAnswer(smooth) {
  const el = scroller.value
  if (!el) return false
  const m = measureLastAnswer(el)
  const top = m ? answerLandingTop(m) : null
  if (top == null) return false
  anchored = true
  if (Math.abs(el.scrollTop - top) > 1) {
    if (typeof el.scrollTo === 'function') el.scrollTo({ top, behavior: scrollBehavior(reduced.value, smooth) })
    else el.scrollTop = top
  }
  return true
}

async function toBottom() {
  await nextTick()
  const el = scroller.value
  if (!el) return
  // A landed answer keeps its start in view across layout changes.
  if (anchored) { landOnLastAnswer(false); return }
  if (stick) el.scrollTop = el.scrollHeight
}
function repin() {
  stick = true
  anchored = false
  toBottom()
}
// Opening a conversation: land on its last answer start, or at the bottom when it fits.
async function landOnOpen() {
  await nextTick()
  const el = scroller.value
  if (!el || chat.sending) return
  stick = true
  anchored = false
  if (!landOnLastAnswer(false)) el.scrollTop = el.scrollHeight
}

// Streaming growth of the live turn: follow ONLY while a run is active (and near bottom).
// Gating on `sending` is what stops a VERSION-NAVIGATION recompute - which also changes the
// signature (the last turn differs) and the turn count - from yanking the view to the bottom.
// That auto-scroll would bury the branch-point version arrows when navigating to a longer
// (older) branch, making the "back to latest" arrow look like it disappeared.
watch(signature, () => { if (chat.sending) toBottom() }, { flush: 'post' })
// A new exchange was created (send / edit / regenerate): its answer lands at the bottom -
// pin to it. Pure version navigation does NOT change exchanges.length, so it won't repin.
// Gated on `sending` (set synchronously with the push): a history load also changes the
// length, and that case is owned by the threadLoading watcher below.
watch(() => chat.exchanges.length, () => { if (chat.sending) repin() })
// Conversation switch (openSession / newConversation): open the thread at its bottom
// (the old thread stays on screen under the loading overlay until the rows arrive).
watch(() => chat.activeSessionId, repin)
// History rows arrived (openSession done): land on the last answer.
watch(() => chat.threadLoading, (loading, was) => { if (was && !loading) landOnOpen() }, { flush: 'post' })
// Run lifecycle: arm the bookkeeping on start; on end, land on the long answer start
// when the reader followed the run and it is still the last turn on screen.
watch(() => chat.sending, (now, was) => {
  if (now) {
    anchored = false
    leftBottomDuringRun = false
    runStartedAt = Date.now()
    runUid = lastUid()
    return
  }
  if (!was) return
  const land = shouldLandOnCompletion({
    following: stick,
    leftBottomDuringRun,
    sameSession: runUid != null && runUid === lastUid(),
  })
  runUid = null
  if (land) nextTick(() => landOnLastAnswer(true))
}, { flush: 'post' })
// Evidence panel open/close adds/removes the fixed-width right column, so the chat
// (always the flexible center column) narrows or widens: every message rewraps,
// scrollHeight changes and the bottom pin is silently lost (the signature watcher
// is sending-gated, nothing else fires).
// Re-run the STICK-GATED toBottom() once the new layout is applied - F13-safe: it
// does not watch `turns`, and a user who scrolled up is never yanked (stick=false).
// The standalone Source Data Explorer panel adds/removes the same right column.
watch(() => evidence.open || sources.open, () => toBottom(), { flush: 'post' })
onMounted(() => {
  // Mounted by a send (empty view -> first message): follow the stream from the bottom.
  // Mounted by a history open: land on the last answer.
  if (chat.sending) {
    runStartedAt = Date.now()
    runUid = lastUid()
    repin()
  } else {
    landOnOpen()
  }
  // Any other re-layout (Studio column, late renders) keeps an anchored landing in place.
  if (typeof ResizeObserver === 'function' && inner.value) {
    resizeObs = new ResizeObserver(() => { if (anchored && !chat.sending) landOnLastAnswer(false) })
    resizeObs.observe(inner.value)
  }
})
onBeforeUnmount(() => {
  if (resizeObs) resizeObs.disconnect()
  resizeObs = null
})
</script>

<template>
  <div
    ref="scroller"
    class="conv"
    @scroll.passive="onScroll"
    @wheel.passive="onUserIntent"
    @touchstart.passive="onUserIntent"
    @pointerdown="onUserIntent"
    @keydown="onUserIntent"
  >
    <div ref="inner" class="conv-inner">
      <template v-for="turn in turns" :key="turn.exchange.uid">
        <MessageUser :turn="turn" />
        <MessageAgent :turn="turn" />
      </template>
    </div>
  </div>
</template>

<style scoped>
.conv { flex: 1; overflow-y: auto; min-height: 0; padding-bottom: var(--s-7); }
.conv-inner {
  width: var(--chat-col);
  max-width: var(--chat-col-max);
  margin: 0 auto;
  padding: var(--s-7);
  display: flex;
  flex-direction: column;
  gap: var(--s-7);
}
/* Narrow chat column (Studio open beside it): full-width measure, tighter gutters. */
@container chat (max-width: 560px) {
  .conv-inner { width: 100%; padding: var(--s-5) var(--s-3); gap: var(--s-6); }
}
</style>
