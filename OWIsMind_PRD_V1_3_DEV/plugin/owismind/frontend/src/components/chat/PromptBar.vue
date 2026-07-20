<script setup>
// Prompt bar - auto-growing textarea, agent picker (left), voice button (left,
// placeholder: no STT backend), send (right). Enter sends; Shift+Enter inserts a
// newline.
import { ref, computed, nextTick, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useChatStore } from '../../stores/chat.js'
import { useSessionStore } from '../../stores/session.js'
import { usePromptContextStore } from '../../stores/promptContext.js'
import { useScreenContextStore } from '../../stores/screenContext.js'
import { useToasts } from '../../composables/useToasts.js'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { contextKey } from '../../composables/promptContextModel.js'
import { Icon } from '../ui'
import AgentPicker from './AgentPicker.vue'
import ModelModePicker from './ModelModePicker.vue'
import ScreenContextDetail from './ScreenContextDetail.vue'

const { t, locale } = useI18n()
const chat = useChatStore()
const session = useSessionStore()
const promptContext = usePromptContextStore()
const screenCtx = useScreenContextStore()
const { push } = useToasts()

// Dataset label shown by the accepted-context chip ('' when no snapshot is live).
const screenDataset = computed(() => (screenCtx.offer ? screenCtx.offer.dataset : ''))

// Full transparency: clicking the accepted chip toggles a popover previewing the EXACT
// LIVE snapshot (screenCtx.offer) that will be attached on the next send. Anchored inside
// the prompt card, closed on outside click / Escape. Reset when the chip disappears.
const ctxPopoverOpen = ref(false)
const ctxChipRef = ref(null)
useClickOutside(ctxChipRef, () => { ctxPopoverOpen.value = false })
watch(() => screenCtx.chipVisible, (visible) => {
  if (!visible) ctxPopoverOpen.value = false
})

// Fire the `offered` analytics ONCE per signature, at banner DISPLAY time (the store
// guards duplicates via lastOfferedSig). The banner shows when it is eligible AND the
// draft is non-empty; re-fire on a signature change while it stays displayed.
watch(
  [() => screenCtx.bannerEligible, () => chat.draft.trim() !== '', () => screenCtx.liveSig],
  () => {
    if (screenCtx.bannerEligible && chat.draft.trim() && screenCtx.liveSig != null) {
      screenCtx.markOffered(screenCtx.liveSig)
    }
  },
)

// Chip identity + hover title for the picked data-context values.
function ctxKey(it) {
  return contextKey(it)
}
function ctxTitle(it) {
  return it.column + ' = ' + it.value + (it.source ? ' (' + it.source + ')' : '')
}

// Values picked for one conversation must not bleed into another: navigating to a
// different conversation (or starting a new one) drops the queue. On the PRE-
// conversation screen an agent-picker switch drops it too (the values were picked
// from the previous agent's datasets); mid-conversation the picker is left alone -
// the chips stay visible and removable either way.
watch(() => chat.activeSessionId, () => promptContext.clear())
watch(() => session.selectedAgentKey, () => {
  if (!chat.exchanges.length) promptContext.clear()
})

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
  // Append the picked data-context values as a readable block, then clear the queue.
  const block = promptContext.block(locale.value)
  chat.draft = ''
  nextTick(autosize)
  if (block) {
    chat.send(text + '\n\n' + block)
    promptContext.clear()
  } else {
    chat.send(text)
  }
}
function onKey(e) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    submit()
  }
}
function micClick() {
  // Voice input has no STT backend yet - honest placeholder.
  push(t('prompt.mic') + ' - bientôt', { icon: 'mic' })
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
    <!-- Consent banner: offers to attach the filtered SOURCE-DATA VIEW the user shaped
         (filters / search / DB-computed figures) as context for the agent. Shows only once
         the user starts typing; a decision is sticky per view signature (no nagging). -->
    <div v-if="screenCtx.bannerEligible && chat.draft.trim()" class="prompt-screen-banner" role="status" aria-live="polite">
      <span class="prompt-screen-msg">{{ t('prompt.screen.detected') }}</span>
      <span class="prompt-screen-actions">
        <button type="button" class="prompt-screen-btn" @click="screenCtx.accept()">
          {{ t('prompt.screen.include') }}
        </button>
        <button type="button" class="prompt-screen-btn prompt-screen-btn--quiet" @click="screenCtx.decline()">
          {{ t('prompt.screen.dismiss') }}
        </button>
      </span>
    </div>
    <!-- Accepted-context chip: the view is attached to every send while its signature is
         unchanged. Removable (x -> decline) so the user is always in control. -->
    <div v-if="screenCtx.chipVisible" class="prompt-screen">
      <span ref="ctxChipRef" class="prompt-ctx-chip prompt-ctx-chip--live" @keydown.escape="ctxPopoverOpen = false">
        <button
          type="button"
          class="prompt-ctx-open"
          :title="t('prompt.screen.view')"
          :aria-expanded="ctxPopoverOpen"
          @click="ctxPopoverOpen = !ctxPopoverOpen"
        >
          <span class="prompt-ctx-chip-text">{{ t('prompt.screen.chip', [screenDataset]) }}</span>
        </button>
        <button
          type="button"
          class="prompt-ctx-x"
          :title="t('prompt.screen.chip_remove')"
          @click="screenCtx.decline()"
        >
          <Icon name="x" />
        </button>
        <!-- Live preview: EXACTLY what rides on the next send (nothing hidden). -->
        <div v-if="ctxPopoverOpen && screenCtx.offer" class="prompt-ctx-pop" role="dialog">
          <ScreenContextDetail :snap="screenCtx.offer" />
        </div>
      </span>
    </div>
    <!-- Picked data-context values (from Source Data cells): shown above the input,
         appended to the message as a readable block at send time. -->
    <div v-if="promptContext.hasItems" class="prompt-ctx">
      <span class="prompt-ctx-title">{{ t('prompt.ctx.title') }}</span>
      <span class="prompt-ctx-list">
        <span
          v-for="it in promptContext.items"
          :key="ctxKey(it)"
          class="prompt-ctx-chip"
          :title="ctxTitle(it)"
        >
          <span class="prompt-ctx-chip-text">{{ it.column }} = {{ it.value }}</span>
          <button
            type="button"
            class="prompt-ctx-x"
            :title="t('prompt.ctx.remove')"
            @click="promptContext.remove(ctxKey(it))"
          >
            <Icon name="x" />
          </button>
        </span>
      </span>
      <button type="button" class="prompt-ctx-clear" @click="promptContext.clear()">
        {{ t('prompt.ctx.clear') }}
      </button>
    </div>
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
        <!-- Response-mode dial: shown ONLY for agents whose admin profile opted into
             modes (the OWIsMind orchestrator). A plain agent that cannot act on the
             mode never shows it. -->
        <ModelModePicker v-if="session.selectedAgentSupportsModes" />
      </div>
      <div class="prompt-right">
        <!-- Mic sits with the send action on the right (voice → send grouping). No STT
             backend yet - honest placeholder. -->
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
/* Screen-context consent banner: flat, square, sober. A single 4px orange left rail is
   the only accent (charte); no fill, no glow. Sits at the very top of the prompt card. */
.prompt-screen-banner {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-2);
  padding: var(--s-2) var(--s-3);
  margin-bottom: var(--s-2);
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-left: 4px solid var(--orange);
  border-radius: 0;
}
.prompt-screen-msg {
  flex: 1 1 auto;
  min-width: 0;
  font-size: var(--fs-xs);
  color: var(--text);
}
.prompt-screen-actions { display: flex; align-items: center; gap: var(--s-3); flex: 0 0 auto; }
.prompt-screen-btn {
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--orange-text);
  border-radius: 0;
  transition: color var(--dur) var(--ease);
}
.prompt-screen-btn:hover { color: var(--orange-deep); }
.prompt-screen-btn--quiet { color: var(--text-2); font-weight: var(--fw-regular); }
.prompt-screen-btn--quiet:hover { color: var(--text); }
/* Accepted-context chip row: same recipe as .prompt-ctx (below). */
.prompt-screen {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-2);
  padding-bottom: var(--s-2);
  margin-bottom: var(--s-1);
  border-bottom: 1px solid var(--border);
}
/* Data-context chip row: compact, square, sober. Sits above the textarea inside the
   prompt card. Orange stays rare - chips are ink-on-surface with a 1px border. */
.prompt-ctx {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-2);
  padding-bottom: var(--s-2);
  margin-bottom: var(--s-1);
  border-bottom: 1px solid var(--border);
}
.prompt-ctx-title {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: var(--fw-bold);
  color: var(--text-2);
}
.prompt-ctx-list { display: flex; align-items: center; flex-wrap: wrap; gap: var(--s-2); }
.prompt-ctx-chip {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  max-width: 220px;
  padding: 2px 4px 2px 8px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
  font-size: var(--fs-xs);
  color: var(--text);
}
.prompt-ctx-chip-text {
  max-width: 160px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
/* The accepted-context chip is clickable to preview the live snapshot: anchor the popover
   and let the label read as an interactive control. */
.prompt-ctx-chip--live { position: relative; }
.prompt-ctx-open {
  display: inline-flex;
  align-items: center;
  min-width: 0;
  color: inherit;
  cursor: pointer;
}
.prompt-ctx-pop {
  position: absolute;
  top: calc(100% + 6px);
  left: 0;
  z-index: var(--z-menu);
}
.prompt-ctx-x {
  display: grid;
  place-items: center;
  width: 16px;
  height: 16px;
  color: var(--text-3);
  border-radius: 0;
  transition: color var(--dur) var(--ease);
}
.prompt-ctx-x:hover { color: var(--text); }
.prompt-ctx-x :deep(.ui-icon) { width: 11px; height: 11px; }
.prompt-ctx-clear {
  margin-left: auto;
  font-size: var(--fs-xs);
  color: var(--text-2);
  transition: color var(--dur) var(--ease);
}
.prompt-ctx-clear:hover { color: var(--text); }
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
