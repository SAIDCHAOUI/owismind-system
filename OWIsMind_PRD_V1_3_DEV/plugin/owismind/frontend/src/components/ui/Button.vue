<script setup>
// Mutualized button - ONE implementation shared across the app.
// Visual spec: docs/cadrage/CHARTE_ORANGE_UI.md.
// Variants: primary | ghost | danger | link | icon.
import Icon from './Icon.vue'

defineProps({
  variant: {
    type: String,
    default: 'ghost',
    validator: (v) => ['primary', 'ghost', 'danger', 'link', 'icon'].includes(v),
  },
  // Optional leading icon name (from the icon registry).
  icon: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  // Native button type; 'button' avoids accidental form submits.
  type: { type: String, default: 'button' },
  // Full-width within its container.
  block: { type: Boolean, default: false },
})
</script>

<template>
  <button
    :type="type"
    :disabled="disabled"
    :class="['ui-btn', `ui-btn--${variant}`, { 'ui-btn--block': block, 'ui-btn--icon-only': variant === 'icon' && !$slots.default }]"
  >
    <Icon v-if="icon" :name="icon" class="ui-btn__icon" />
    <span v-if="$slots.default" class="ui-btn__label"><slot /></span>
  </button>
</template>

<style scoped>
/* Base: capsule geometry (premium direction - the charter allows --r-pill on the
   primary action and icon buttons; a footer row mixing a pill and a square would
   read as two different systems, so every solid/outlined variant is a capsule).
   Micro-feedback: a 1px lift on hover, a press-down on click. */
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  padding: 10px 18px;
  font-size: 13px;
  font-weight: 700;
  font-family: inherit;
  border-radius: var(--r-pill);
  border: 2px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease),
    color var(--dur) var(--ease), transform var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}
.ui-btn--block { width: 100%; }
.ui-btn__icon { width: 14px; height: 14px; }
.ui-btn:not(:disabled):not(.ui-btn--link):not(.ui-btn--icon):hover { transform: translateY(-1px); }
.ui-btn:not(:disabled):active { transform: translateY(0) scale(0.98); }

/* Ghost (default): 2px near-black border, transparent bg; hover inverts. */
.ui-btn--ghost {
  background: var(--bg);
  color: var(--text);
  border-color: var(--text);
}
.ui-btn--ghost:hover:not(:disabled) {
  background: var(--text);
  color: var(--bg);
}

/* Primary: solid orange fill; hover deepens the fill and lifts it off the card. */
.ui-btn--primary {
  background: var(--orange);
  color: #fff;
  border-color: var(--orange);
}
.ui-btn--primary:hover:not(:disabled) {
  background: var(--orange-deep);
  border-color: var(--orange-deep);
  box-shadow: var(--elev-1);
}

/* Danger: solid red, destructive confirm - square. */
.ui-btn--danger {
  background: var(--danger);
  color: #fff;
  border-color: var(--danger);
}
.ui-btn--danger:hover:not(:disabled) {
  filter: brightness(0.9);
}

/* Link: text-only inline action, hover goes orange. */
.ui-btn--link {
  background: transparent;
  border-color: transparent;
  color: var(--text-2);
  padding: 7px 8px;
  font-weight: 600;
}
.ui-btn--link:hover:not(:disabled) { color: var(--orange-text); }

/* Icon: round target, subtle, for icon-only affordances (mic, close, more...). */
.ui-btn--icon {
  background: transparent;
  border-color: transparent;
  color: var(--text-3);
  padding: 7px;
  border-radius: var(--r-pill);
}
.ui-btn--icon:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.ui-btn--icon-only { padding: 7px; }
.ui-btn--icon .ui-btn__icon { width: 16px; height: 16px; }

.ui-btn:disabled { opacity: 0.4; cursor: not-allowed; }
/* Prevent ghost from inverting when disabled. */
.ui-btn--ghost:disabled:hover { background: var(--bg); color: var(--text); }

@media (prefers-reduced-motion: reduce) {
  .ui-btn {
    transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease),
      color var(--dur) var(--ease);
  }
  .ui-btn:not(:disabled):not(.ui-btn--link):not(.ui-btn--icon):hover,
  .ui-btn:not(:disabled):active { transform: none; }
}
</style>
