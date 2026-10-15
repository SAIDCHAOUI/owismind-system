<script setup>
// Single mount point for transient toasts (mounted once in App.vue). Teleports to
// <body> and renders the shared `toasts` queue bottom-centre. Visual spec:
// docs/cadrage/CHARTE_ORANGE_UI.md - inverted pill, soft shadow, top z-index.
import { useToasts } from '../../composables/useToasts.js'
import Icon from './Icon.vue'

const { toasts } = useToasts()
</script>

<template>
  <Teleport to="body">
    <TransitionGroup name="ui-toast" tag="div" class="ui-toast-stack">
      <div v-for="t in toasts" :key="t.id" :class="['ui-toast', `ui-toast--${t.tone}`]">
        <span v-if="t.icon" class="ico"><Icon :name="t.icon" /></span>
        <span class="tx">{{ t.message }}</span>
      </div>
    </TransitionGroup>
  </Teleport>
</template>

<style scoped>
.ui-toast-stack {
  position: fixed;
  left: 50%;
  bottom: 28px;
  transform: translateX(-50%);
  display: flex;
  flex-direction: column-reverse;
  align-items: center;
  gap: 8px;
  z-index: var(--z-toast);
  pointer-events: none;
}
.ui-toast {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  /* Floating layer: rounded + soft layered elevation, over an inverted-ink fill so
     it reads instantly against either theme. */
  border-radius: var(--r-lg);
  background: var(--text);
  color: var(--bg);
  font-size: var(--fs-sm);
  font-weight: 500;
  box-shadow: var(--elev-2);
}
.ui-toast .ico { display: inline-flex; }
.ui-toast .ico :deep(.ui-icon) { width: 14px; height: 14px; }
/* Tone accents on the leading icon (the pill itself stays inverted, matching the maquette) */
.ui-toast--ok .ico { color: var(--success); }
.ui-toast--warn .ico { color: var(--warn); }
.ui-toast--danger .ico { color: var(--danger); }

/* Rises from below and settles from 0.96; leaving drops back the same way. `move`
   keeps the stack from jumping when an older toast is dismissed under a newer one. */
.ui-toast-enter-active { transition: opacity var(--dur) var(--ease-out), transform var(--dur) var(--ease-out); }
.ui-toast-leave-active { transition: opacity var(--dur-fast) var(--ease-in), transform var(--dur-fast) var(--ease-in); }
.ui-toast-enter-from,
.ui-toast-leave-to { opacity: 0; transform: translateY(10px) scale(0.96); }
.ui-toast-move { transition: transform var(--dur) var(--ease); }

@media (prefers-reduced-motion: reduce) {
  .ui-toast-enter-active,
  .ui-toast-leave-active { transition: opacity 90ms linear; }
  .ui-toast-enter-from,
  .ui-toast-leave-to { transform: none; }
  .ui-toast-move { transition: none; }
}
</style>
