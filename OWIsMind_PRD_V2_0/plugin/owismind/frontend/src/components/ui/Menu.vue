<script setup>
// Self-contained dropdown menu - ONE shared implementation. Visual spec:
// docs/cadrage/CHARTE_ORANGE_UI.md. Owns its open state, positions the panel
// relative to the trigger, closes on Escape, outside-click, or item select.
//
// Usage:
//   <Menu :items="items" align="right" @select="onSelect">
//     <template #trigger="{ toggle, open }">
//       <Button variant="icon" icon="dots" @click="toggle" />
//     </template>
//   </Menu>
// `items`: [{ key, label, icon?, danger?, sep? }]. A `sep:true` entry renders a divider.
import { ref } from 'vue'
import { useClickOutside } from '../../composables/useClickOutside.js'
import Icon from './Icon.vue'

const props = defineProps({
  items: { type: Array, default: () => [] },
  align: { type: String, default: 'right', validator: (v) => ['left', 'right'].includes(v) },
  // 'bottom' opens below the trigger, 'top' opens above (e.g. sidebar-foot menus).
  placement: { type: String, default: 'bottom', validator: (v) => ['top', 'bottom'].includes(v) },
})
const emit = defineEmits(['select', 'open', 'close'])

const wrap = ref(null)
const open = ref(false)

function toggle() {
  open.value ? close() : show()
}
function show() {
  open.value = true
  emit('open')
}
function close() {
  if (!open.value) return
  open.value = false
  emit('close')
}
function onItem(item) {
  if (item.sep || item.disabled) return
  emit('select', item.key, item)
  close()
}
function onKey(e) {
  if (e.key === 'Escape') close()
}

useClickOutside(wrap, close)
</script>

<template>
  <div ref="wrap" class="ui-menu-wrap" @keydown="onKey">
    <slot name="trigger" :toggle="toggle" :open="open" />
    <Transition name="ui-menu">
      <div v-if="open" class="ui-menu" :class="[`align-${align}`, `place-${placement}`]" role="menu">
        <template v-for="(item, i) in items" :key="item.key ?? i">
          <div v-if="item.sep" class="ui-menu-sep" />
          <button
            v-else
            type="button"
            role="menuitem"
            class="ui-menu-item"
            :class="{ danger: item.danger, 'has-sub': item.hasSub }"
            :disabled="item.disabled"
            @click="onItem(item)"
          >
            <span class="ic"><Icon v-if="item.icon" :name="item.icon" /></span>
            <span class="lbl">{{ item.label }}</span>
            <span v-if="item.hasSub" class="arr"><Icon name="chevronRight" /></span>
          </button>
        </template>
      </div>
    </Transition>
  </div>
</template>

<style scoped>
.ui-menu-wrap { position: relative; display: inline-flex; }

.ui-menu {
  position: absolute;
  min-width: 220px;
  background: var(--bg);
  /* Floating layer (premium direction): rounded card + soft layered elevation, the
     1px frame keeps it readable on a same-tone surface. */
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--elev-2);
  padding: 6px;
  z-index: var(--z-menu);
  font-family: var(--font-sans);
}
.ui-menu.align-right { right: 4px; }
.ui-menu.align-left { left: 4px; }
.ui-menu.place-bottom { top: calc(100% + 6px); }
.ui-menu.place-top { bottom: calc(100% + 6px); }
/* Dark canvas: a floating panel takes one surface step above the page, otherwise a
   --bg card on a --bg page reads as a hole. No shadow override: --elev-2 carries
   its own dark variant (tokens.css). */
:global(body[data-theme="dark"] .ui-menu) { background: var(--surface-2); }

.ui-menu-item {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 7px 10px;
  border-radius: var(--r-sm);
  font-size: 12.5px;
  color: var(--text);
  background: transparent;
  text-align: left;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
  font-family: inherit;
}
.ui-menu-item:hover:not(:disabled) { background: var(--surface-hover); }
.ui-menu-item:disabled { opacity: 0.5; cursor: default; }
.ui-menu-item .ic {
  width: 14px;
  height: 14px;
  color: var(--text-3);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: color var(--dur) var(--ease);
}
/* The whole row answers the pointer, glyph included (a grey icon under a hovered
   row reads as disabled). */
.ui-menu-item:hover:not(:disabled) .ic { color: var(--text-2); }
.ui-menu-item .ic :deep(.ui-icon) { width: 14px; height: 14px; }
.ui-menu-item .lbl { line-height: 1.3; }
.ui-menu-item .arr {
  width: 12px;
  height: 12px;
  color: var(--text-3);
  display: inline-flex;
}
.ui-menu-item .arr :deep(.ui-icon) { width: 12px; height: 12px; }
.ui-menu-item.has-sub:hover .arr { color: var(--text); }
/* Destructive row: the status token already carries its own light/dark value, so a
   theme override would only re-state it (no hardcoded hex here). The :hover rules
   are declared at hover specificity so the neutral row-hover cannot grey them. */
.ui-menu-item.danger,
.ui-menu-item.danger:hover:not(:disabled) { color: var(--danger); }
.ui-menu-item.danger .ic,
.ui-menu-item.danger:hover:not(:disabled) .ic { color: var(--danger); }
.ui-menu-item.danger:hover:not(:disabled) { background: var(--danger-soft); }
.ui-menu-sep { height: 1px; background: var(--border); margin: 4px 6px; }

/* Open/close: a short fade plus a small rise and settle from 0.98, anchored on the
   trigger edge so the panel visibly grows OUT of the button it belongs to. */
.ui-menu-enter-active {
  transition: opacity var(--dur) var(--ease-out), transform var(--dur) var(--ease-out);
}
.ui-menu-leave-active {
  transition: opacity var(--dur-fast) var(--ease-in), transform var(--dur-fast) var(--ease-in);
}
.ui-menu-enter-from,
.ui-menu-leave-to { opacity: 0; }
.ui-menu.place-bottom { transform-origin: top center; }
.ui-menu.place-top { transform-origin: bottom center; }
.ui-menu-enter-from.place-bottom,
.ui-menu-leave-to.place-bottom { transform: translateY(-6px) scale(0.98); }
.ui-menu-enter-from.place-top,
.ui-menu-leave-to.place-top { transform: translateY(6px) scale(0.98); }

@media (prefers-reduced-motion: reduce) {
  .ui-menu-item { transition: none; }
  .ui-menu-enter-active,
  .ui-menu-leave-active { transition: opacity 90ms linear; }
  .ui-menu-enter-from.place-bottom,
  .ui-menu-leave-to.place-bottom,
  .ui-menu-enter-from.place-top,
  .ui-menu-leave-to.place-top { transform: none; }
}
</style>
