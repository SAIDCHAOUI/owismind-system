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
.msg { animation: slide-up var(--dur) var(--ease); }
.msg.user { display: flex; justify-content: flex-end; }

/* Bubble + hover actions, right-aligned column. */
.bubble-wrap {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 4px;
  max-width: 78%;
}
.bubble {
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 10px 14px;
  border-radius: 14px 14px 4px 14px;
  font-size: var(--fs-md);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

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
.sc-toggle {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  max-width: 100%;
  font-size: var(--fs-xs);
  color: var(--text-3);
  transition: color var(--dur) var(--ease);
}
.sc-toggle:hover { color: var(--text-2); }
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

/* Hidden by default, revealed on hover (or focus-within for keyboard users). */
.u-actions {
  display: flex;
  gap: 2px;
  opacity: 0;
  visibility: hidden;
  transition: opacity var(--dur) var(--ease);
}
.bubble-wrap:hover .u-actions,
.bubble-wrap:focus-within .u-actions {
  opacity: 1;
  visibility: visible;
}
.u-actions button {
  display: inline-flex;
  align-items: center;
  padding: 4px;
  border-radius: var(--r-sm);
  color: var(--text-3);
  transition: all var(--dur) var(--ease);
}
.u-actions button:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
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
  border-radius: var(--r);
  background: var(--surface);
  color: var(--text);
  font-size: var(--fs-md);
  font-family: inherit;
  line-height: 1.6;
}
.edit-area:focus { outline: none; border-color: var(--orange); }
.edit-actions { display: flex; justify-content: flex-end; gap: var(--s-2); }
.edit-actions button {
  padding: 6px 14px;
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  transition: all var(--dur) var(--ease);
}
.edit-actions button.ghost { color: var(--text-2); }
.edit-actions button.ghost:hover { background: var(--surface-hover); color: var(--text); }
.edit-actions button.primary { background: var(--orange); color: #fff; font-weight: 500; }
.edit-actions button.primary:hover:not(:disabled) { background: var(--orange-soft-dark); }
.edit-actions button.primary:disabled { opacity: 0.4; cursor: not-allowed; }
</style>
