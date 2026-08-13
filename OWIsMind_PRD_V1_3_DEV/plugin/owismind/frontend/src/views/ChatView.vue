<script setup>
// Chat page - wires the validated transport (chat store → useChatStream → polling)
// to the maquette UI. Empty state centers title + prompt; an active conversation
// shows the scrollable thread with the prompt pinned below. The route's optional
// :sessionId selects a conversation (lazily fetched on open); no param = a new one.
import { watch, computed, ref, nextTick, onBeforeUnmount } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../stores/chat.js'
import { useSessionStore } from '../stores/session.js'
import { formatMoney, formatShortDate } from '../composables/budgetModel.js'
import ChatThread from '../components/chat/ChatThread.vue'
import ChatEmpty from '../components/chat/ChatEmpty.vue'
import PromptBar from '../components/chat/PromptBar.vue'
import { Icon } from '../components/ui'
import { captureFirstSend, playFirstSend, playStageExit } from '../composables/useFirstSendMorph.js'

const route = useRoute()
const router = useRouter()
const { t, locale } = useI18n()
const chat = useChatStore()
const session = useSessionStore()

// Monthly-budget banner (transparent): shown above the prompt when the user has hit
// their credit and enforcement is on. The server-side gate is authoritative; this just
// explains WHY sending is paused and WHEN it resumes (the reset date).
const budgetBlocked = computed(() => session.budgetBlocked)
const budgetMsg = computed(() => {
  const u = session.usage
  if (!u) return ''
  return t('chat.quota_banner', [
    formatMoney(u.spent_usd, locale.value),
    formatMoney(u.limit_usd, locale.value),
    formatShortDate(u.next_reset, locale.value),
  ])
})

// BEGIN impersonation (temporary) - read-only note while an admin views as a user.
// The label is the EFFECTIVE (impersonated) user from the session. Sending is also
// disabled via chat.canSend; this just explains why. Removable: delete this computed
// + the .imp-note block in the prompt-wrap + its styles.
const impersonateNote = computed(() => {
  if (!session.impersonating) return ''
  const u = session.user
  const label = (u && (u.display_name || u.user_id)) || '-'
  return t('impersonate.readonly_note', [label])
})
// END impersonation (temporary)

// Map the few send errors that benefit from a human message (the monthly-quota race in
// particular); anything else shows its raw stable code (unchanged behaviour).
const friendlyError = computed(() => {
  const code = chat.errorMsg
  if (!code) return ''
  if (code === 'monthly_quota_exceeded') return budgetMsg.value || t('chat.quota_short')
  return code
})

// Route → conversation. ensureSession fetches lazily (deep-link hydrates on its
// own) but skips the refetch when the param already matches the in-memory thread
// (the URL stamp below, or coming back from Settings - where it still re-runs the
// evidence continuity). New conversation when there's no :sessionId.
watch(
  () => route.params.sessionId,
  (sid) => {
    if (sid) chat.ensureSession(sid)
    else chat.newConversation()
  },
  { immediate: true },
)

// Store → route sync. A conversation STARTED on bare `/chat` keeps its session id
// only in the store: stamp it into the URL once its first exchange exists, so the
// sidebar highlights it and the New-conversation button (`router.push('/chat')`)
// actually changes the route - pushing `/chat` while already on param-less `/chat`
// is a no-op the param watcher never sees (the "dead button" bug). The watcher
// above ignores the stamp (param === activeSessionId with the thread in memory).
watch(
  () => chat.exchanges.length,
  (n) => {
    if (n > 0 && route.name === 'chat' && route.params.sessionId !== chat.activeSessionId) {
      router.replace('/chat/' + encodeURIComponent(chat.activeSessionId))
    }
  },
)

/* --- First-send morph ("the hand-off") ------------------------------------
 * The arrival screen becomes a working thread in one patch: the heading leaves,
 * the sentence moves into its bubble, the prompt card settles at the foot. All of
 * it is decoration played AFTER the send has already left (see
 * composables/useFirstSendMorph.js). It runs on the first message of a
 * conversation only; from turn two the existing message entry is the right answer.
 */
const promptBar = ref(null)
let cancelMorph = null
/* The heading's geometry BEFORE the patch. By the time Vue calls the leave hook the
 * thread is already inserted and the block has been pushed down, so measuring it
 * there freezes it in the wrong place. */
let stageRect = null

function stopMorph() {
  if (cancelMorph) cancelMorph()
  cancelMorph = null
}
/* The first user bubble of the thread. Read from the DOM on purpose: the thread is
 * mounted in the same patch, and a registration channel through two components
 * would buy nothing for a node that is, by definition, the first of its kind. */
function firstBubbleEl() {
  const inner = document.querySelector('.conv-inner')
  return inner ? inner.querySelector('.msg.user .bubble') : null
}

// PRE-flush: the DOM is still the arrival screen, which is what we must measure.
watch(
  () => chat.hasMessages,
  (now, before) => {
    // Falling BACK to the arrival screen (the optimistic exchange is dropped when
    // the monthly quota rejects the run) must take the flying sentence with it.
    if (!now) {
      stopMorph()
      return
    }
    if (before) return
    const bar = promptBar.value
    if (!bar) return
    const stage = document.querySelector('.empty-stage')
    stageRect = stage ? stage.getBoundingClientRect() : null
    const first = captureFirstSend({ card: bar.cardEl, input: bar.taEl })
    if (!first) return
    stopMorph()
    nextTick(() => {
      const b = promptBar.value
      if (!b || !b.cardEl) return
      cancelMorph = playFirstSend(first, { card: b.cardEl, findBubble: firstBubbleEl })
    })
  },
  { flush: 'pre' },
)
// A conversation switch or leaving the view must never strand a flying sentence.
watch(() => chat.activeSessionId, stopMorph)
onBeforeUnmount(stopMorph)

/* Leave hook of the arrival heading: freeze it where it sits and take it OUT of the
 * flow, so the prompt card measures its REAL final position on the same frame. */
function onStageLeave(el, done) {
  const parent = el.parentElement
  if (parent) {
    const r = stageRect || el.getBoundingClientRect()
    const p = parent.getBoundingClientRect()
    el.style.position = 'absolute'
    el.style.left = r.left - p.left + 'px'
    el.style.top = r.top - p.top + 'px'
    el.style.width = r.width + 'px'
    el.style.height = r.height + 'px'
    el.style.pointerEvents = 'none'
  }
  playStageExit(el, done)
}
</script>

<template>
  <div class="chat">
    <!-- Storage not configured: an admin must set the SQL connection -->
    <div v-if="session.needsConfig" class="chat-config">
      <div class="chat-config__card">
        <p class="chat-config__title">Stockage non configuré</p>
        <p class="muted">
          Un administrateur doit définir la <b>connexion SQL</b> dans les réglages de la webapp
          (onglet Settings), puis redémarrer le backend.
        </p>
      </div>
    </div>

    <!-- ONE prompt bar for both stages. It used to be duplicated in the two branches
         (arrival / thread), which destroyed and rebuilt the component on the first send:
         the focus was lost and no morph was possible. Hoisted here, the SAME node
         travels from the centre of the arrival screen to the foot of the thread, which
         is what the send transition animates (FLIP, see morphSend below). -->
    <template v-else>
      <ChatThread v-if="chat.hasMessages" :turns="chat.turns" />
      <!-- The heading does not cut: it is pulled out of the flow and animated away
           by its leave hook, which is also what lets the card measure its landing. -->
      <Transition :css="false" @leave="onStageLeave">
        <div v-if="!chat.hasMessages" class="empty-stage">
          <ChatEmpty />
        </div>
      </Transition>

      <div class="prompt-wrap" :class="{ 'in-empty': !chat.hasMessages }">
        <!-- BEGIN impersonation (temporary) - read-only note (admin viewing as user). -->
        <div v-if="impersonateNote" class="imp-note">
          <Icon name="users" />
          <span>{{ impersonateNote }}</span>
        </div>
        <!-- END impersonation -->
        <!-- Monthly budget exhausted: a clear, transparent banner (sends are paused). -->
        <div v-if="budgetBlocked" class="budget-banner">
          <Icon name="wallet" />
          <span>{{ budgetMsg }}</span>
        </div>
        <!-- A failed switch keeps the PREVIOUS thread on screen - the error must be
             visible here too (sends are blocked by canSend until a clean reload). -->
        <p v-if="chat.threadError" class="chat-error">{{ t('chat.loadThreadError') }}</p>
        <p v-else-if="chat.errorMsg" class="chat-error">{{ friendlyError }}</p>
        <PromptBar ref="promptBar" />
      </div>

      <!-- Arrival only: the lower half of the stage. With `.empty-stage` filling the
           upper half (content flushed to its bottom edge), the heading + prompt group
           lands optically centred, exactly where it sat before the hoist. -->
      <div v-if="!chat.hasMessages" class="empty-tail" aria-hidden="true"></div>
    </template>

    <!-- Centered loading overlay during a conversation switch: it sits OVER both the
         current thread and the empty stage, so the screen never flashes "new
         conversation" before the target rows arrive (Feature 3). -->
    <div v-if="chat.threadLoading" class="thread-loading" aria-live="polite">
      <span class="thread-spinner" />
      <span class="thread-loading__label">{{ t('chat.loadingThread') }}</span>
    </div>
  </div>
</template>

<style scoped>
.chat { flex: 1; display: flex; flex-direction: column; min-height: 0; overflow: hidden; position: relative; }

/* Upper half of the arrival screen: the heading sits at its BOTTOM edge, right above
   the prompt, and `.empty-tail` balances it below - the pair reads as one centred
   group while the prompt bar stays a sibling (single node, morphable). */
.empty-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  padding-bottom: var(--s-7);
  min-height: 0;
  overflow-y: auto;
}
/* `margin-top: auto` on the CHILD rather than `justify-content: flex-end` on the
   scroll container: on a short viewport the latter pushes overflow past the top
   edge, where it can no longer be scrolled to. */
.empty-stage > * { margin-top: auto; }
.empty-tail { flex: 1; min-height: 0; }

.prompt-wrap {
  width: var(--chat-col);
  max-width: var(--chat-col-max);
  margin: 0 auto;
  padding: 0 var(--s-7) var(--s-7);
  flex-shrink: 0;
  /* Brand AURA on BOTH stages (user decision 2026-08-13): the prompt keeps its
     tinted air after the first send, when it settles at the bottom of the thread.
     PromptBar reads these with a transparent fallback, so the effect is opt-in per
     host and the card never carries a hardcoded colored shadow. */
  --prompt-aura: var(--aura-orange);
  --prompt-aura-strong: var(--aura-orange-strong);
}
/* On the empty / new-chat screen the prompt bar is the only element, so the full
   90% measure looks oversized - keep it comfortably narrow and centered (the title
   above it sits in the same ~760px band). */
.prompt-wrap.in-empty { padding-bottom: var(--s-7); max-width: 760px; }
/* Arrival hero: the prompt is THE element of the page - one size up (roomier card,
   larger input). In-thread it returns to its compact working size. */
.prompt-wrap.in-empty :deep(.prompt) { padding: var(--s-5) var(--s-6) var(--s-4); }
.prompt-wrap.in-empty :deep(.prompt-input) {
  font-size: var(--fs-lg);
  min-height: 56px;
}

.chat-error {
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--danger);
  margin: 0 0 var(--s-3);
}
/* Monthly budget banner (transparent "credit reached" state above the prompt). */
.budget-banner {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 var(--s-3);
  padding: 10px 14px;
  border: 1px solid var(--danger);
  border-radius: 0;
  background: var(--danger-soft);
  color: var(--danger);
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.budget-banner :deep(.ui-icon) { width: 16px; height: 16px; flex-shrink: 0; }
/* BEGIN impersonation (temporary) - read-only note above the prompt (admin view-as).
   Flat, square, a thin orange left accent (charter: orange is a rare accent). */
.imp-note {
  display: flex;
  align-items: center;
  gap: 9px;
  margin: 0 0 var(--s-3);
  padding: 10px 14px;
  border: 1px solid var(--border-strong);
  border-left: 4px solid var(--orange);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-sm);
  line-height: 1.5;
}
.imp-note :deep(.ui-icon) { width: 16px; height: 16px; flex-shrink: 0; color: var(--orange); }
/* END impersonation */
/* Conversation-switch loading overlay (centered spinner over the whole .chat area).
   It fades in rather than snapping over the thread - a fast switch then reads as a
   soft veil instead of a flash. */
.thread-loading {
  position: absolute;
  inset: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--s-3);
  background: rgba(255, 255, 255, 0.55);
  z-index: 5;
  pointer-events: none;
  animation: veil-in var(--dur) var(--ease-out) both;
}
@keyframes veil-in {
  from { opacity: 0; }
  to { opacity: 1; }
}
:global(body[data-theme="dark"] .thread-loading) { background: rgba(13, 13, 13, 0.55); }
.thread-loading__label { font-size: var(--fs-sm); color: var(--text-3); }
.thread-spinner {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  border: 3px solid var(--border);
  border-top-color: var(--orange);
  animation: spin 0.8s linear infinite;
}
@keyframes spin { to { transform: rotate(360deg); } }
@media (prefers-reduced-motion: reduce) {
  .thread-loading { animation: none; }
  /* The spinner is the only "something is happening" signal here, so it keeps
     turning - slower, and without the fade-in that surrounds it. */
  .thread-spinner { animation-duration: 1.8s; }
}

.chat-config { flex: 1; display: grid; place-items: center; padding: var(--s-7); }
.chat-config__card {
  max-width: 460px;
  border: 1px solid var(--border);
  border-radius: 0;
  background: var(--surface);
  padding: var(--s-6);
  text-align: center;
}
.chat-config__title { font-weight: 600; color: var(--text); margin: 0 0 var(--s-3); }
</style>
