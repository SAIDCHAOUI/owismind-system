<script setup>
// Model-mode picker — a compact segmented control (Éco / Medium / High) bound to
// the ui store. It is purely a cost/quality preference sent with each turn: the
// backend defaults unknown values to "medium". Eco = cheap model only; Medium =
// cheap model + conservative auto-escalation to the strong model on hard turns;
// High = strong model. The system is built to be excellent on the cheap model —
// this only lets a user dial quality up when they want it.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore, MODEL_MODES } from '../../stores/ui.js'

const { t } = useI18n()
const ui = useUiStore()

const current = computed(() => ui.modelMode)
const modes = MODEL_MODES // ['eco', 'medium', 'high']

// Roving-tabindex keyboard support (WAI-ARIA radiogroup): only the checked
// option is in the tab order; Left/Right move (and select) the active mode.
function move(offset) {
  const i = modes.indexOf(current.value)
  const next = modes[(i + offset + modes.length) % modes.length]
  ui.setModelMode(next)
}
</script>

<template>
  <div class="mode-picker" role="radiogroup" :aria-label="t('mode.label')">
    <button
      v-for="m in modes"
      :key="m"
      type="button"
      class="mode-seg"
      :class="{ active: current === m }"
      role="radio"
      :aria-checked="current === m"
      :tabindex="current === m ? 0 : -1"
      :title="t('mode.' + m + '_hint')"
      @click="ui.setModelMode(m)"
      @keydown.left.prevent="move(-1)"
      @keydown.right.prevent="move(1)"
    >
      {{ t('mode.' + m) }}
    </button>
  </div>
</template>

<style scoped>
.mode-picker {
  display: inline-flex;
  align-items: center;
  gap: 1px;
  padding: 2px;
  background: var(--surface-2);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
}
.mode-seg {
  font-size: 11px;
  font-weight: 500;
  line-height: 1;
  padding: 4px 9px;
  border-radius: var(--r-pill);
  color: var(--text-3);
  transition: all var(--dur) var(--ease);
  white-space: nowrap;
}
.mode-seg:hover { color: var(--text); }
.mode-seg.active {
  background: var(--bg);
  color: var(--orange-text);
  font-weight: 600;
  box-shadow: var(--shadow-xs, 0 1px 2px rgba(0, 0, 0, 0.08));
}
:global(body[data-theme="dark"] .mode-seg.active) { background: var(--surface-hover); }
</style>
