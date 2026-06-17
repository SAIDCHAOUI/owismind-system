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
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import MessageUser from './MessageUser.vue'
import MessageAgent from './MessageAgent.vue'
import { timelineSignature } from '../../composables/timelineModel.js'
import { useChatStore } from '../../stores/chat.js'
import { useEvidenceStore } from '../../stores/evidence.js'

const props = defineProps({
  turns: { type: Array, required: true },
})

const chat = useChatStore()
const evidence = useEvidenceStore()

const scroller = ref(null)
// How close to the bottom (px) still counts as "following" the stream.
const NEAR_BOTTOM_PX = 120
let stick = true

const signature = computed(() => {
  const arr = props.turns
  let s = String(arr.length)
  const last = arr[arr.length - 1]
  if (last) {
    s += `|${timelineSignature(last.exchange.version)}|${last.versionIdx}`
  }
  return s
})

function onScroll() {
  const el = scroller.value
  if (!el) return
  stick = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_BOTTOM_PX
}
async function toBottom() {
  await nextTick()
  const el = scroller.value
  if (el && stick) el.scrollTop = el.scrollHeight
}
function repin() {
  stick = true
  toBottom()
}
// Streaming growth of the live turn: follow ONLY while a run is active (and near bottom).
// Gating on `sending` is what stops a VERSION-NAVIGATION recompute - which also changes the
// signature (the last turn differs) and the turn count - from yanking the view to the bottom.
// That auto-scroll would bury the branch-point version arrows when navigating to a longer
// (older) branch, making the "back to latest" arrow look like it disappeared.
watch(signature, () => { if (chat.sending) toBottom() }, { flush: 'post' })
// A new exchange was created (send / edit / regenerate): its answer lands at the bottom -
// pin to it. Pure version navigation does NOT change exchanges.length, so it won't repin.
watch(() => chat.exchanges.length, repin)
// Conversation switch (openSession / newConversation): open the thread at its bottom.
watch(() => chat.activeSessionId, repin)
// Evidence panel open/close adds/removes the fixed-width right column, so the chat
// (always the flexible center column) narrows or widens: every message rewraps,
// scrollHeight changes and the bottom pin is silently lost (the signature watcher
// is sending-gated, nothing else fires).
// Re-run the STICK-GATED toBottom() once the new layout is applied - F13-safe: it
// does not watch `turns`, and a user who scrolled up is never yanked (stick=false).
watch(() => evidence.open, () => toBottom(), { flush: 'post' })
onMounted(() => {
  stick = true
  toBottom()
})
</script>

<template>
  <div ref="scroller" class="conv" @scroll.passive="onScroll">
    <div class="conv-inner">
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
</style>
