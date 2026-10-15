<script setup>
// User message bubble - the active version's prompt for one turn. Asymmetric
// rounded bubble, right-aligned. Text is rendered via interpolation ({{ }}) -
// never v-html - so user input is always safe.
//
// Hover reveals two actions: Copy (clipboard) and Edit. Editing opens an inline textarea;
// submitting calls chat.editTurn(turn, text), which creates a NEW SIBLING branch from this
// turn's parent (nothing is deleted - the old version stays reachable via the answer's
// version arrows). Reads useChatStore() directly (no prop-drilling - just the `turn`).
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useToasts } from '../../composables/useToasts.js'
import { Icon } from '../ui'
import ScreenContextDetail from './ScreenContextDetail.vue'

const props = defineProps({
  turn: { type: Object, required: true },
})

const { t } = useI18n()
const chat = useChatStore()
const { push } = useToasts()

const text = computed(() => props.turn.exchange.userText)
const editing = ref(false)
const draft = ref('')

// Full transparency: the on-screen SOURCE-DATA context the user consented to share with
// THIS message (stamped on the answer version at send, rebuilt from the row on reload).
// Null when nothing was attached - the line then does not render at all.
const screenCtx = computed(() => props.turn.exchange.version && props.turn.exchange.version.screenCtx)
const screenDataset = computed(() => (screenCtx.value && screenCtx.value.dataset) || '')
const ctxOpen = ref(false)

function startEdit() {
  draft.value = text.value
  editing.value = true
}
function cancel() {
  editing.value = false
}
function submit() {
  const v = draft.value.trim()
  if (!v) return
  editing.value = false
  chat.editTurn(props.turn, v) // new sibling branch
}
async function copy() {
  try {
    await navigator.clipboard.writeText(text.value)
    push(t('msg.copied'), { icon: 'check', tone: 'ok' })
  } catch (e) {
    push(t('msg.copy_failed'), { icon: 'alert', tone: 'warn' })
  }
}
</script>

<template>
  <div class="msg user u-no-shrink">
    <div v-if="!editing" class="bubble-wrap">
      <div class="bubble">{{ text }}</div>
      <!-- On-screen context shared with this message: an elegant, discreet line that
           expands the FULL detail inline (nothing hidden). Renders only when a context
           was actually attached. -->
      <div v-if="screenCtx" class="sc-line">
        <button
          type="button"
          class="sc-toggle"
          :aria-expanded="ctxOpen"
          @click="ctxOpen = !ctxOpen"
        >
          <Icon name="database" class="sc-ic" />
          <span class="sc-sent">{{ t('prompt.screen.sent') }}</span>
          <span v-if="screenDataset" class="sc-ds">{{ screenDataset }}</span>
          <Icon :name="ctxOpen ? 'chevronUp' : 'chevronDown'" class="sc-chev" />
        </button>
        <ScreenContextDetail v-if="ctxOpen" :snap="screenCtx" class="sc-inline" />
      </div>
      <div class="u-actions">
        <button :title="t('msg.copy')" @click="copy"><Icon name="copy" /></button>
        <button :title="t('msg.edit')" :disabled="!chat.canSend" @click="startEdit"><Icon name="edit" /></button>
      </div>
    </div>
    <div v-else class="edit-box">
      <textarea
        v-model="draft"
        class="edit-area"
        rows="3"
        :placeholder="t('msg.edit_placeholder')"
        @keydown.esc="cancel"
      />
      <div class="edit-actions">
        <button class="ghost" @click="cancel">{{ t('msg.cancel') }}</button>
        <button class="primary" :disabled="!draft.trim() || !chat.canSend" @click="submit">{{ t('msg.send') }}</button>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* Arrival: fade + rise together (the shared slide-up keyframe only translates, so a
   message used to appear at full opacity mid-slide). */
.msg { animation: msg-in var(--dur-slow) var(--ease-out) both; }
@keyframes msg-in {
  from { opacity: 0; transform: translateY(6px); }
  to { opacity: 1; transform: translateY(0); }
}
.msg.user { display: flex; justify-content: flex-end; }

/* Bubble + hover actions, right-aligned column. */
.bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  max-width: 78%;
}
/* The user's turn: a soft-cornered card, one step below the prompt card's --r-xl so
   the hierarchy reads (the prompt is where you write, this is what you wrote). */
.bubble {
  background: var(--surface);
  border: 1px solid var(--border-strong);
  padding: 10px 14px;
  border-radius: var(--r-lg);
  font-size: var(--fs-md);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  transition: border-color var(--dur) var(--ease);
}
/* Hovering the turn firms the frame - it signals the actions below belong to it. */
.bubble-wrap:hover .bubble { border-color: var(--text-3); }

/* On-screen context line: discreet, right-aligned under the bubble, with a 1px top
   separator. Ink-on-nothing, orange stays absent here (charte: rare). */
.sc-line {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 6px;
  width: 100%;
  padding-top: 6px;
  border-top: 1px solid var(--border);
}
/* Negative right margin keeps the label flush with the bubble edge while the row
   still gets a real hover surface to sit on. */
.sc-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  padding: 2px 6px;
  margin-right: -6px;
  border-radius: var(--r-sm);
  font-size: var(--fs-xs);
  color: var(--text-3);
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.sc-toggle:hover { color: var(--text-2); background: var(--surface-hover); }
.sc-toggle .sc-ic :deep(.ui-icon) { width: 12px; height: 12px; }
.sc-ds {
  font-family: var(--font-mono);
  color: var(--text-2);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sc-chev :deep(.ui-icon) { width: 12px; height: 12px; }
.sc-inline { align-self: stretch; }

/* Hidden by default, revealed on hover (or focus-within for keyboard users): they
   fade in AND rise the last 3px, so they read as belonging to the bubble above. */
.u-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  visibility: hidden;
  transform: translateY(-3px);
  transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease-out);
}
.bubble-wrap:hover .u-actions,
.bubble-wrap:focus-within .u-actions {
  opacity: 1;
  visibility: visible;
  transform: translateY(0);
}
.u-actions button {
  display: inline-flex;
  align-items: center;
  padding: 5px;
  border-radius: var(--r-pill);
  color: var(--text-3);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}
.u-actions button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.u-actions button:active:not(:disabled) { transform: scale(0.9); }
.u-actions button:disabled { opacity: 0.4; cursor: not-allowed; }
.u-actions button :deep(.ui-icon) { width: 14px; height: 14px; }

/* Inline edit box - styled like the prompt input. */
.edit-box {
  width: 78%;
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.edit-area {
  width: 100%;
  resize: vertical;
  min-height: 64px;
  padding: 10px 14px;
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-md);
  font-family: inherit;
  line-height: 1.6;
  caret-color: var(--orange);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.edit-area:focus { outline: none; border-color: var(--text-3); box-shadow: var(--elev-1); }
.edit-actions { display: flex; justify-content: flex-end; gap: var(--s-2); }
.edit-actions button {
  padding: 6px 14px;
  border-radius: var(--r-pill);
  font-size: var(--fs-sm);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}
.edit-actions button:active:not(:disabled) { transform: scale(0.97); }
.edit-actions button.ghost { color: var(--text-2); }
.edit-actions button.ghost:hover { background: var(--surface-hover); color: var(--text); }
.edit-actions button.primary { background: var(--orange); color: #fff; font-weight: 500; }
/* --orange-deep, NOT --orange-soft-dark: that token resolves to the pale
   #fff5ec tint in light theme, which turned the hovered Send into white-on-white. */
.edit-actions button.primary:hover:not(:disabled) { background: var(--orange-deep); }
.edit-actions button.primary:disabled { opacity: 0.4; cursor: not-allowed; }

@media (prefers-reduced-motion: reduce) {
  .msg { animation: none; }
  .u-actions { transition: opacity var(--dur) var(--ease); transform: none; }
  .bubble-wrap:hover .u-actions,
  .bubble-wrap:focus-within .u-actions { transform: none; }
  .u-actions button:active:not(:disabled),
  .edit-actions button:active:not(:disabled) { transform: none; }
}
/* Narrow chat column: the bubble may use more of the measure. */
@container chat (max-width: 560px) {
  .bubble-wrap { max-width: 90%; }
  .bubble { padding: 8px 12px; }
}
</style>
