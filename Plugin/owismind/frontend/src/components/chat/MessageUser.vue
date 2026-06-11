<script setup>
// User message bubble — the active version's prompt for one turn. Visual spec ported from
// `.msg.user .bubble` (components.css): asymmetric rounded bubble, right-aligned. Text is
// rendered via interpolation ({{ }}) — never v-html — so user input is always safe.
//
// Hover reveals two actions: Copy (clipboard) and Edit. Editing opens an inline textarea;
// submitting calls chat.editTurn(turn, text), which creates a NEW SIBLING branch from this
// turn's parent (nothing is deleted — the old version stays reachable via the answer's
// version arrows). Reads useChatStore() directly (no prop-drilling — just the `turn`).
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useToasts } from '../../composables/useToasts.js'
import { Icon } from '../ui'

const props = defineProps({
  turn: { type: Object, required: true },
})

const { t } = useI18n()
const chat = useChatStore()
const { push } = useToasts()

const text = computed(() => props.turn.exchange.userText)
const editing = ref(false)
const draft = ref('')

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

/* Inline edit box — styled like the prompt input. */
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
