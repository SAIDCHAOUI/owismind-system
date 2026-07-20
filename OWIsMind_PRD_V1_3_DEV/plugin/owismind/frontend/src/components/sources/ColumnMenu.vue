<script setup>
// Column header menu - a small fixed-position card anchored to a table header's menu
// trigger. Offers the 3-state sort (ascending / descending / clear) with a checkmark on
// the active direction, and a "Filter values..." action that opens the value picker
// pre-set to this column. Closes on outside-click or Escape. Its coordinates are clamped
// so it never overflows the viewport edges. Modeled on CellActionPopover: Teleported to
// body so a transformed Evidence-panel ancestor cannot offset a position:fixed child.
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { Icon } from '../ui'

const props = defineProps({
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  column: { type: String, default: '' },
  // The column's live sort direction: 'asc' | 'desc' | null (not sorted).
  sortDir: { type: String, default: null },
  // Whether the column carries at least one active filter (drives the checkmark/clarity).
  filtered: { type: Boolean, default: false },
  // False when the host is at the backend filter cap (20): the Filter item disables with
  // an explanatory title instead of arming a picker that can never render.
  canFilter: { type: Boolean, default: true },
})
const emit = defineEmits(['sort', 'filter', 'close'])

const { t } = useI18n()

// Fixed width (matches the CSS below) drives right-edge clamping; height is measured
// from the mounted element so the bottom-edge clamp accounts for the real card size.
const POPOVER_W = 220
const MARGIN = 8

const rootEl = ref(null)
const pos = ref({ left: props.x, top: props.y })

function clampToViewport() {
  const vw = window.innerWidth || 0
  const vh = window.innerHeight || 0
  const h = rootEl.value ? rootEl.value.offsetHeight : 180
  let left = props.x
  let top = props.y
  if (left + POPOVER_W + MARGIN > vw) left = vw - POPOVER_W - MARGIN
  if (left < MARGIN) left = MARGIN
  if (top + h + MARGIN > vh) top = vh - h - MARGIN
  if (top < MARGIN) top = MARGIN
  pos.value = { left, top }
}

useClickOutside(rootEl, () => emit('close'))

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
// A window resize moves the anchor header under the fixed card: the stored coordinates go
// stale, so close instead of drifting (mirrors CellActionPopover / the host table scroll).
function onResize() {
  emit('close')
}

onMounted(() => {
  document.addEventListener('keydown', onKey, true)
  window.addEventListener('resize', onResize)
  nextTick(clampToViewport)
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', onResize)
})
// Re-clamp if the anchor moves while mounted (parent reuses the same instance).
watch(() => [props.x, props.y], () => nextTick(clampToViewport))
</script>

<template>
  <!-- Teleported to body (same reasoning as CellActionPopover): inside the Evidence panel
       transformed ancestors would become the containing block of a position:fixed child. -->
  <Teleport to="body">
    <div
      ref="rootEl"
      class="col-menu"
      role="menu"
      :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
    >
      <div class="col-menu-head">{{ column }}</div>
      <button type="button" class="col-menu-item" role="menuitem" @click="emit('sort', 'asc')">
        <span class="col-menu-tick"><Icon v-if="sortDir === 'asc'" name="check" /></span>
        <span>{{ t('src.col.sortAsc') }}</span>
      </button>
      <button type="button" class="col-menu-item" role="menuitem" @click="emit('sort', 'desc')">
        <span class="col-menu-tick"><Icon v-if="sortDir === 'desc'" name="check" /></span>
        <span>{{ t('src.col.sortDesc') }}</span>
      </button>
      <button
        type="button"
        class="col-menu-item"
        role="menuitem"
        :disabled="!sortDir"
        @click="emit('sort', null)"
      >
        <span class="col-menu-tick"></span>
        <span>{{ t('src.col.sortNone') }}</span>
      </button>
      <div class="col-menu-sep" role="separator"></div>
      <button
        type="button"
        class="col-menu-item"
        role="menuitem"
        :disabled="!canFilter"
        :title="canFilter ? null : t('src.col.filterCap')"
        @click="emit('filter')"
      >
        <span class="col-menu-tick"><Icon v-if="filtered" name="check" /></span>
        <span>{{ t('src.col.filterVals') }}</span>
      </button>
    </div>
  </Teleport>
</template>

<style scoped>
/* Square, flat card on a 1px border with the minimal shadow (charte Orange: no blur,
   no gradient, no glow). Fixed so it anchors to the trigger coordinates. */
.col-menu {
  position: fixed;
  z-index: var(--z-menu);
  width: 220px;
  max-width: calc(100vw - 16px);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  box-shadow: var(--shadow);
  padding: var(--s-1) 0;
  display: flex;
  flex-direction: column;
}
.col-menu-head {
  padding: 6px 12px;
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: var(--fw-bold);
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  border-bottom: 1px solid var(--border);
  margin-bottom: var(--s-1);
}
.col-menu-item {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  padding: 7px 12px;
  background: transparent;
  border: 0;
  border-radius: 0;
  color: var(--text);
  font-size: var(--fs-sm);
  text-align: left;
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.col-menu-item:hover:not(:disabled) { background: var(--surface-hover); }
.col-menu-item:disabled { opacity: 0.4; cursor: not-allowed; }
/* Fixed-width tick slot: keeps every label aligned whether or not a checkmark shows.
   The active checkmark is the single rare orange accent (charte: orange text only). */
.col-menu-tick {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 14px;
  height: 14px;
  flex: none;
  color: var(--orange-text);
}
.col-menu-tick :deep(.ui-icon) { width: 14px; height: 14px; }
.col-menu-sep { height: 1px; background: var(--border); margin: var(--s-1) 0; }
</style>
