<script setup>
// Self-contained dropdown menu - ONE implementation replacing the maquette's
// context/agent/user/help menus. Visual spec ported from `.ctx-menu` /
// `.ctx-menu-item` / `.ctx-menu-sep` (v4-extras.css). Owns its open state,
// positions the panel relative to the trigger, closes on Escape, outside-click,
// or item select.
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
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.12), 0 2px 6px rgba(0, 0, 0, 0.06);
  padding: 4px;
  z-index: var(--z-menu);
  font-family: var(--font-sans);
}
.ui-menu.align-right { right: 4px; }
.ui-menu.align-left { left: 4px; }
.ui-menu.place-bottom { top: calc(100% + 4px); }
.ui-menu.place-top { bottom: calc(100% + 4px); }
:global(body[data-theme="dark"] .ui-menu) {
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.5), 0 2px 6px rgba(0, 0, 0, 0.3);
}

.ui-menu-item {
  display: grid;
  grid-template-columns: 18px 1fr auto;
  gap: 10px;
  align-items: center;
  width: 100%;
  padding: 7px 10px;
  border-radius: 4px;
  font-size: 12.5px;
  color: var(--text);
  background: transparent;
  text-align: left;
  transition: background var(--dur) var(--ease);
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
}
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
.ui-menu-item.danger { color: #dc2626; }
.ui-menu-item.danger .ic { color: #dc2626; }
.ui-menu-item.danger:hover { background: rgba(220, 38, 38, 0.08); }
:global(body[data-theme="dark"] .ui-menu-item.danger),
:global(body[data-theme="dark"] .ui-menu-item.danger .ic) { color: #f87171; }
.ui-menu-sep { height: 1px; background: var(--border); margin: 4px 6px; }

.ui-menu-enter-active,
.ui-menu-leave-active { transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease); }
.ui-menu-enter-from,
.ui-menu-leave-to { opacity: 0; transform: translateY(-4px); }
</style>
