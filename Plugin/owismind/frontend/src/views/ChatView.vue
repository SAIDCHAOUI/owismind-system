<script setup>
// Chat page — wires the validated transport (chat store → useChatStream → polling)
// to the maquette UI. Empty state centers title + prompt; an active conversation
// shows the scrollable thread with the prompt pinned below. The route's optional
// :sessionId selects a conversation (lazily fetched on open); no param = a new one.
import { watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../stores/chat.js'
import { useSessionStore } from '../stores/session.js'
import ChatThread from '../components/chat/ChatThread.vue'
import ChatEmpty from '../components/chat/ChatEmpty.vue'
import PromptBar from '../components/chat/PromptBar.vue'

const route = useRoute()
const router = useRouter()
const { t } = useI18n()
const chat = useChatStore()
const session = useSessionStore()

// Route → conversation. ensureSession fetches lazily (deep-link hydrates on its
// own) but skips the refetch when the param already matches the in-memory thread
// (the URL stamp below, or coming back from Settings — where it still re-runs the
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
// actually changes the route — pushing `/chat` while already on param-less `/chat`
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
</script>

<template>
  <div class="chat">
    <!-- Storage not configured: an admin must set the SQL connection -->
    <div v-if="session.needsConfig" class="chat-config">
      <div class="chat-config__card">
        <p class="chat-config__title">⚙️ Stockage non configuré</p>
        <p class="muted">
          Un administrateur doit définir la <b>connexion SQL</b> dans les réglages de la webapp
          (onglet Settings), puis redémarrer le backend.
        </p>
      </div>
    </div>

    <template v-else-if="chat.hasMessages">
      <ChatThread :turns="chat.turns" />
      <div class="prompt-wrap">
        <!-- A failed switch keeps the PREVIOUS thread on screen — the error must be
             visible here too (sends are blocked by canSend until a clean reload). -->
        <p v-if="chat.threadError" class="chat-error">{{ t('chat.loadThreadError') }}</p>
        <p v-else-if="chat.errorMsg" class="chat-error">{{ chat.errorMsg }}</p>
        <PromptBar />
      </div>
    </template>

    <div v-else class="empty-stage">
      <ChatEmpty />
      <div class="prompt-wrap in-empty">
        <p v-if="chat.threadError" class="chat-error">{{ t('chat.loadThreadError') }}</p>
        <p v-else-if="chat.errorMsg" class="chat-error">{{ chat.errorMsg }}</p>
        <PromptBar />
      </div>
    </div>

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

.empty-stage {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: stretch;
  justify-content: center;
  gap: var(--s-7);
  min-height: 0;
  overflow-y: auto;
}

.prompt-wrap {
  width: var(--chat-col);
  max-width: var(--chat-col-max);
  margin: 0 auto;
  padding: 0 var(--s-7) var(--s-7);
  flex-shrink: 0;
}
/* On the empty / new-chat screen the prompt bar is the only element, so the full
   90% measure looks oversized — keep it comfortably narrow and centered (the title
   and tip above it sit in the same ~760px band). */
.prompt-wrap.in-empty { padding-bottom: var(--s-7); max-width: 760px; }

.chat-error {
  text-align: center;
  font-size: var(--fs-sm);
  color: var(--danger);
  margin: 0 0 var(--s-3);
}
/* Conversation-switch loading overlay (centered spinner over the whole .chat area). */
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

.chat-config { flex: 1; display: grid; place-items: center; padding: var(--s-7); }
.chat-config__card {
  max-width: 460px;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--surface);
  padding: var(--s-6);
  text-align: center;
}
.chat-config__title { font-weight: 600; color: var(--text); margin: 0 0 var(--s-3); }
</style>
