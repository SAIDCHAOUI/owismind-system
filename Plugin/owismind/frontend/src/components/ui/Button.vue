<script setup>
// Mutualized button - replaces the maquette's 5 re-implementations
// (.modal-btn / .edit-btn / .fb-btn / .es-btn / .admin-btn × primary/ghost).
// Visual spec ported from `.modal-btn` (v4-extras.css) + `.es-btn.link`
// (workspace.css). Variants: primary | ghost | danger | link | icon.
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
.ui-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  padding: 10px 18px;
  font-size: 13.5px;
  font-weight: 600;
  font-family: inherit;
  border-radius: var(--r);
  border: 1px solid transparent;
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--dur) var(--ease), border var(--dur) var(--ease),
    color var(--dur) var(--ease), filter var(--dur) var(--ease);
}
.ui-btn--block { width: 100%; }
.ui-btn__icon { width: 15px; height: 15px; }

/* Ghost (default) - neutral outlined */
.ui-btn--ghost {
  background: transparent;
  color: var(--text-2);
  border-color: var(--border-strong);
}
.ui-btn--ghost:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }

/* Primary - solid orange */
.ui-btn--primary {
  background: var(--orange);
  color: #fff;
  border-color: var(--orange);
}
.ui-btn--primary:hover:not(:disabled) { filter: brightness(1.05); }

/* Danger - solid red (destructive confirm) */
.ui-btn--danger {
  background: #ef4444;
  color: #fff;
  border-color: #ef4444;
}
.ui-btn--danger:hover:not(:disabled) { background: #dc2626; border-color: #dc2626; }

/* Link - text-only inline action */
.ui-btn--link {
  background: transparent;
  border-color: transparent;
  color: var(--text-2);
  padding: 7px 8px;
  font-weight: 500;
}
.ui-btn--link:hover:not(:disabled) { color: var(--orange); }

/* Icon - square, subtle, for icon-only affordances (mic, close, more…) */
.ui-btn--icon {
  background: transparent;
  border-color: transparent;
  color: var(--text-3);
  padding: 7px;
  border-radius: var(--r-sm);
}
.ui-btn--icon:hover:not(:disabled) { background: var(--surface-hover); color: var(--text); }
.ui-btn--icon-only { padding: 7px; }
.ui-btn--icon .ui-btn__icon { width: 16px; height: 16px; }

.ui-btn:disabled { opacity: 0.45; cursor: not-allowed; }
</style>
