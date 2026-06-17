<script setup>
// Prompt bar — auto-growing textarea, agent picker (left), voice button (left,
// placeholder: no STT backend), send (right). Visual spec ported from `.prompt`
// / `.prompt-input` / `.prompt-row` / `.p-icon` / `.send-btn` (components.css).
// Enter sends; Shift+Enter inserts a newline.
import { ref, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useSessionStore } from '../../stores/session.js'
import { useToasts } from '../../composables/useToasts.js'
import { Icon } from '../ui'
import AgentPicker from './AgentPicker.vue'
import ModelModePicker from './ModelModePicker.vue'

const { t } = useI18n()
const chat = useChatStore()
const session = useSessionStore()
const { push } = useToasts()

const ta = ref(null)

function autosize() {
  const el = ta.value
  if (!el) return
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 200) + 'px'
}
watch(() => chat.draft, () => nextTick(autosize))

function submit() {
  const text = chat.draft
  if (!text.trim() || !chat.canSend) return
  chat.draft = ''
  nextTick(autosize)
  chat.send(text)
}
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}
function micClick() {
  // Voice input has no STT backend yet — honest placeholder.
  push(t('prompt.mic') + ' — bientôt', { icon: 'mic' })
}

const placeholder = () =>
  session.needsConfig
    ? t('prompt.placeholder')
    : session.hasAgents
      ? t('prompt.placeholder')
      : t('prompt.choose_agent')
</script>

<template>
  <div class="prompt">
    <textarea
      ref="ta"
      v-model="chat.draft"
      class="prompt-input"
      rows="1"
      :placeholder="placeholder()"
      :disabled="session.needsConfig"
      autocomplete="off"
      @keydown="onKey"
      @input="autosize"
    />
    <div class="prompt-row">
      <div class="prompt-left">
        <AgentPicker />
        <ModelModePicker />
      </div>
      <div class="prompt-right">
        <!-- Mic sits with the send action on the right (voice → send grouping). No STT
             backend yet — honest placeholder. -->
        <button class="p-icon" type="button" :title="t('prompt.mic')" @click="micClick">
          <Icon name="mic" />
        </button>
        <!-- While a run is in flight, the send button becomes a STOP button (cuts the
             generation short; the partial answer is kept). Otherwise it sends. -->
        <button
          v-if="chat.sending"
          class="send-btn stop-btn"
          type="button"
          :title="t('prompt.stop')"
          @click="chat.stopGeneration()"
        >
          <Icon name="stop" />
        </button>
        <button
          v-else
          class="send-btn"
          type="button"
          :title="t('prompt.send')"
          :disabled="!chat.canSend || !chat.draft.trim()"
          @click="submit"
        >
          <Icon name="send" />
        </button>
      </div>
    </div>
  </div>
  <p class="prompt-foot">{{ t('prompt.foot_disclaimer') }}</p>
</template>

<style scoped>
.prompt {
  border: 1px solid var(--border);
  background: var(--bg);
  border-radius: var(--r);
  padding: var(--s-3) var(--s-4) var(--s-2);
  display: flex;
  flex-direction: column;
  transition: border-color var(--dur) var(--ease);
}
.prompt:focus-within { border-color: var(--border-strong); }
.prompt-input {
  width: 100%;
  background: transparent;
  border: none;
  outline: none;
  resize: none;
  font-size: var(--fs-md);
  line-height: 1.5;
  color: var(--text);
  padding: 6px 0 8px;
  min-height: 28px;
  max-height: 200px;
  font-family: inherit;
}
.prompt-input::placeholder { color: var(--text-3); }
.prompt-row { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; }
.prompt-left { display: flex; align-items: center; gap: 2px; }
.prompt-right { display: flex; align-items: center; gap: var(--s-2); }
.p-icon {
  width: 32px;
  height: 32px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  border-radius: 6px;
  transition: all var(--dur) var(--ease);
}
.p-icon:hover { background: var(--surface-hover); color: var(--text); }
.p-icon :deep(.ui-icon) { width: 17px; height: 17px; }
.send-btn {
  width: 32px;
  height: 32px;
  background: var(--orange);
  color: #fff;
  border-radius: 8px;
  display: grid;
  place-items: center;
  transition: all var(--dur) var(--ease);
}
.send-btn:hover:not(:disabled) { background: var(--orange-deep); }
.send-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.send-btn :deep(.ui-icon) { width: 14px; height: 14px; }
.prompt-foot { text-align: center; font-size: var(--fs-xs); color: var(--text-3); padding-top: var(--s-3); }
</style>
