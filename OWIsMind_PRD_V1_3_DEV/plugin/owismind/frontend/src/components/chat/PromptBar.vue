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

// Keyboard-affordance hint ("Enter to send"): recognition over recall - shown
// only while the input is focused AND carries text (never as ambient noise).
const inputFocused = ref(false)
const enterHintVisible = computed(
  () => inputFocused.value && !!chat.draft.trim() && !chat.sending && chat.canSend,
)

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
    <!-- On-screen context chip: the SOURCE-DATA VIEW the user shaped (filters / search /
         DB-computed figures) is attached to every send BY DEFAULT - the agent sees what
         the user sees. Removable (x -> opt-out, sticky for this exact view) so the user
         stays in control; any view change re-includes automatically. -->
    <div v-if="screenCtx.chipVisible" class="prompt-screen" role="status" aria-live="polite">
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
    <!-- Opted-out view still on screen: one quiet line + a re-include action, so
         excluding the context is reversible without re-shaping the view. -->
    <div v-if="screenCtx.excludedVisible" class="prompt-screen prompt-screen--off">
      <span class="prompt-screen-off-text">{{ t('prompt.screen.off') }}</span>
      <button type="button" class="prompt-screen-btn" @click="screenCtx.accept()">
        {{ t('prompt.screen.include') }}
      </button>
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
      @focus="inputFocused = true"
      @blur="inputFocused = false"
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
        <!-- Keyboard hint: appears once the draft is ready to go (focused + text),
             so the fastest path (Enter) is learned by seeing, not by guessing. -->
        <span v-if="enterHintVisible" class="send-hint" aria-hidden="true">
          <kbd class="send-kbd">&#8629;</kbd>{{ t('prompt.enter_hint') }}
        </span>
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
/* The prompt is the PRIMARY control of the page: a soft ELEVATED card (premium
   direction, user decision 2026-08-13) - generous radius, hairline border, layered
   shadow that deepens on hover/focus. The chrome recedes; the typing area leads. */
.prompt {
  position: relative;
  border: 1px solid var(--border-strong);
  background: var(--bg);
  border-radius: var(--r-xl);
  padding: var(--s-4) var(--s-5) var(--s-3);
  display: flex;
  flex-direction: column;
  box-shadow: var(--elev-1);
  transition: box-shadow var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.prompt:hover { box-shadow: var(--elev-2); }
/* Focused = the hero moment (user ask 2026-08-13, "effet luxe"): the frame turns
   orange and a WHISPER of tinted air spreads around the card (a 4px --orange-soft
   veil under the soft elevation - no glow, no gradient, just the brand breathing
   on the sides). Sanctioned per-component accent, NOT a global focus ring. */
.prompt:focus-within {
  border-color: var(--orange);
  box-shadow: 0 0 0 4px var(--orange-soft), var(--elev-2);
}
:global(body[data-theme="dark"] .prompt:focus-within) {
  border-color: var(--orange);
  box-shadow: 0 0 0 4px var(--orange-soft-dark), var(--elev-2);
}
/* Dark canvas: the card sits one surface step ABOVE the page (a same-color card
   would disappear; the border alone is too faint at this size). */
:global(body[data-theme="dark"] .prompt) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
/* Re-include action (opted-out row): plain orange-text button, flat and square.
   Hover keeps the AA-safe --orange-text in BOTH themes (--orange-deep fails AA on
   light and darkens the dark theme) and signals with an underline instead. */
.prompt-screen-btn {
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  color: var(--orange-text);
  border-radius: 0;
}
.prompt-screen-btn:hover { text-decoration: underline; }
/* On-screen context chip row (auto-included): same recipe as .prompt-ctx (below). */
.prompt-screen {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--s-2);
  padding-bottom: var(--s-2);
  margin-bottom: var(--s-1);
  border-bottom: 1px solid var(--border);
}
/* Opted-out row: one quiet line + the re-include action, no border theatrics
   (the modifier drops the chip row's bottom rule). --text-2 keeps the state
   line AA-readable in both themes (it carries functional information). */
.prompt-screen--off { border-bottom: none; }
.prompt-screen-off-text { font-size: var(--fs-xs); color: var(--text-2); }
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
  padding: 3px 6px 3px 10px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-pill);
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
  border-radius: var(--r-pill);
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
  font-size: 16px;
  line-height: 1.55;
  color: var(--text);
  caret-color: var(--orange);
  padding: 8px 0 10px;
  min-height: 30px;
  max-height: 200px;
  font-family: inherit;
}
.prompt-input::placeholder { color: var(--text-3); }
.prompt-row { display: flex; align-items: center; justify-content: space-between; padding-top: 6px; }
.prompt-left { display: flex; align-items: center; gap: 2px; }
.prompt-right { display: flex; align-items: center; gap: var(--s-2); }
.p-icon {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  color: var(--text-2);
  border-radius: var(--r-pill);
  transition: all var(--dur) var(--ease);
}
.p-icon:hover { background: var(--surface-hover); color: var(--text); }
.p-icon:active { background: var(--surface-2); }
.p-icon:focus-visible { outline: 2px solid var(--orange); outline-offset: 1px; }
.p-icon :deep(.ui-icon) { width: 17px; height: 17px; }
/* Keyboard hint: quiet mono line + square kbd cap, visible only when the draft is
   ready (focused + text). Enters with the shared rise so it never pops harshly. */
.send-hint {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
  white-space: nowrap;
  animation: owi-rise var(--dur) var(--ease-out) both;
}
.send-kbd {
  font-family: var(--font-mono);
  font-size: 11px;
  line-height: 1;
  padding: 2px 5px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-xs);
  color: var(--text-2);
  background: var(--surface);
}
/* Send = the page's primary action: solid orange, PILL (premium direction), one
   size up. Micro-feedback: the glyph nudges forward on hover ("this will go"),
   the button presses down on click - state talks back at every step. */
.send-btn {
  width: 38px;
  height: 38px;
  background: var(--orange);
  color: #fff;
  border-radius: var(--r-pill);
  display: grid;
  place-items: center;
  transition: background var(--dur) var(--ease), opacity var(--dur) var(--ease),
    transform var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.send-btn:hover:not(:disabled) { background: var(--orange-deep); box-shadow: var(--elev-2); }
.send-btn:active:not(:disabled) { transform: scale(0.94); }
/* Ink ring, not orange: an orange ring around a solid-orange button would read
   as a same-hue halo, not a focus state. */
.send-btn:focus-visible { outline: 2px solid var(--text); outline-offset: 2px; }
.send-btn :deep(.ui-icon) {
  width: 15px;
  height: 15px;
  transition: transform var(--dur) var(--ease);
}
.send-btn:hover:not(:disabled) :deep(.ui-icon) { transform: translateX(2px); }
/* The stop variant keeps its glyph still (stopping is not "sending forward"). */
.send-btn.stop-btn:hover :deep(.ui-icon) { transform: none; }
@media (prefers-reduced-motion: reduce) {
  .send-btn, .send-btn :deep(.ui-icon) { transition: background var(--dur) var(--ease), opacity var(--dur) var(--ease); }
  .send-btn:active:not(:disabled) { transform: none; }
  .send-btn:hover:not(:disabled) :deep(.ui-icon) { transform: none; }
  .send-hint { animation: none; }
}
.send-btn:disabled { opacity: 0.35; cursor: not-allowed; }
.prompt-foot { text-align: center; font-size: var(--fs-xs); color: var(--text-3); padding-top: var(--s-3); }
</style>
