<script setup>
// Accessible modal - ONE implementation replacing the maquette's per-screen
// modals. Visual spec ported from `.modal-scrim` / `.modal-card` / `.modal-*`
// (v4-extras.css). Teleported to <body>, closes on Escape and scrim click,
// moves focus into the card on open and restores it on close.
//
// v-model carries the open state. Slots: #header (or `title` prop), default
// (body), #footer (actions row, e.g. <Button> primitives).
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'
import { useI18n } from 'vue-i18n'
import { useReducedMotion } from '../../composables/useReducedMotion.js'
import Icon from './Icon.vue'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  title: { type: String, default: '' },
  // Optional header icon name; `danger` tints it red (destructive confirms).
  icon: { type: String, default: '' },
  danger: { type: Boolean, default: false },
  // Allow Escape / scrim-click / close button to dismiss.
  closable: { type: Boolean, default: true },
  maxWidth: { type: String, default: '440px' },
})
const emit = defineEmits(['update:modelValue', 'close'])

const { t } = useI18n()
const reduced = useReducedMotion()
const card = ref(null)
let lastFocused = null

function close() {
  if (!props.closable) return
  emit('update:modelValue', false)
  emit('close')
}
function onScrim(e) {
  // Only when the scrim itself (not the card) is clicked.
  if (e.target === e.currentTarget) close()
}
function onKey(e) {
  if (e.key === 'Escape') close()
}

watch(
  () => props.modelValue,
  async (open) => {
    if (open) {
      lastFocused = document.activeElement
      document.addEventListener('keydown', onKey)
      await nextTick()
      card.value && card.value.focus()
    } else {
      document.removeEventListener('keydown', onKey)
      lastFocused && lastFocused.focus && lastFocused.focus()
      lastFocused = null
    }
  },
)
onBeforeUnmount(() => document.removeEventListener('keydown', onKey))
</script>

<template>
  <Teleport to="body">
    <Transition name="ui-modal">
      <div v-if="modelValue" class="ui-modal-scrim" @mousedown="onScrim">
        <div
          ref="card"
          class="ui-modal-card"
          :class="{ 'is-static': reduced }"
          :style="{ maxWidth }"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
          tabindex="-1"
        >
          <button
            v-if="closable"
            type="button"
            class="ui-modal-close"
            :aria-label="t('x.close')"
            @click="close"
          >
            <Icon name="x" />
          </button>

          <div v-if="title || $slots.header || icon" class="ui-modal-head">
            <span v-if="icon" class="ui-modal-icon" :class="{ danger }">
              <Icon :name="icon" />
            </span>
            <slot name="header">
              <h2 class="ui-modal-title">{{ title }}</h2>
            </slot>
          </div>

          <div class="ui-modal-body"><slot /></div>

          <div v-if="$slots.footer" class="ui-modal-actions"><slot name="footer" /></div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.ui-modal-scrim {
  position: fixed;
  inset: 0;
  z-index: var(--z-overlay);
  background: rgba(10, 10, 12, 0.48);
  backdrop-filter: blur(2px);
  -webkit-backdrop-filter: blur(2px);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}
:global(body[data-theme="dark"] .ui-modal-scrim) { background: rgba(0, 0, 0, 0.58); }

.ui-modal-card {
  position: relative;
  width: 100%;
  max-height: calc(100vh - 48px);
  overflow-y: auto;
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 16px;
  padding: 26px 26px 22px;
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.22), 0 2px 6px rgba(0, 0, 0, 0.08);
  outline: none;
  animation: ui-modalCardIn 200ms var(--ease) forwards;
}
.ui-modal-card.is-static { animation: none; }
:global(body[data-theme="dark"] .ui-modal-card) {
  background: var(--surface);
  box-shadow: 0 24px 60px rgba(0, 0, 0, 0.55), 0 2px 6px rgba(0, 0, 0, 0.4);
}
@keyframes ui-modalCardIn {
  from { transform: translateY(8px) scale(0.985); }
  to { transform: translateY(0) scale(1); }
}

.ui-modal-close {
  position: absolute;
  top: 12px;
  right: 12px;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.ui-modal-close:hover { background: var(--surface-hover); color: var(--text); }
.ui-modal-close :deep(.ui-icon) { width: 16px; height: 16px; }

.ui-modal-head {
  display: flex;
  align-items: center;
  gap: 12px;
  padding-right: 30px;
}
.ui-modal-icon {
  width: 38px;
  height: 38px;
  border-radius: 10px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  background: var(--surface-2);
  color: var(--text-2);
}
.ui-modal-icon.danger { background: rgba(239, 68, 68, 0.12); color: #ef4444; }
.ui-modal-icon :deep(.ui-icon) { width: 20px; height: 20px; }
.ui-modal-title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
  line-height: 1.3;
}

.ui-modal-body { margin-top: 18px; }
.ui-modal-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 22px;
}

/* Scrim fade (gracefully degraded if reduced-motion via shortened duration) */
.ui-modal-enter-active,
.ui-modal-leave-active { transition: opacity var(--dur) var(--ease); }
.ui-modal-enter-from,
.ui-modal-leave-to { opacity: 0; }
</style>
