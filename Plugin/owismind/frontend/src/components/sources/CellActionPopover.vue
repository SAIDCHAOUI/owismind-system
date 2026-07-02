<script setup>
// Cell action popover - a small fixed-position card anchored to a clicked Source Data
// cell. Shows the column, the full value, and a primary "use this value" action (or a
// note when the value is too long to send). Closes on outside-click or Escape. Its
// coordinates are clamped so it never overflows the viewport edges.
import { nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClickOutside } from '../../composables/useClickOutside.js'

const props = defineProps({
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  column: { type: String, default: '' },
  value: { type: String, default: '' },
  source: { type: String, default: '' },
  canUse: { type: Boolean, default: true },
})
const emit = defineEmits(['use', 'close'])

const { t } = useI18n()

// Fixed width (matches the CSS below) drives right-edge clamping; height is measured
// from the mounted element so the bottom-edge clamp accounts for the real card size.
const POPOVER_W = 280
const MARGIN = 8

const rootEl = ref(null)
const pos = ref({ left: props.x, top: props.y })

function clampToViewport() {
  const vw = window.innerWidth || 0
  const vh = window.innerHeight || 0
  const h = rootEl.value ? rootEl.value.offsetHeight : 160
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
// A window resize moves the anchor cell under the fixed card: the stored click
// coordinates go stale, so close instead of drifting off the cell (mirrors the
// close-on-scroll behavior of the host tables).
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
  <div
    ref="rootEl"
    class="cell-pop"
    role="dialog"
    :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
  >
    <div class="cell-pop-col">{{ column }}</div>
    <div class="cell-pop-val mono">{{ value }}</div>
    <button
      v-if="canUse"
      type="button"
      class="cell-pop-use"
      @click="emit('use')"
    >
      {{ t('src.cell.use') }}
    </button>
    <p v-else class="cell-pop-note">{{ t('src.cell.tooLong') }}</p>
  </div>
</template>

<style scoped>
/* Square, flat card on a 1px border with the minimal 1px shadow (charte Orange:
   no blur, no gradient, no glow). Fixed so it anchors to the click coordinates. */
.cell-pop {
  position: fixed;
  z-index: var(--z-menu);
  width: 280px;
  max-width: calc(100vw - 16px);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 0;
  box-shadow: var(--shadow);
  padding: var(--s-3);
  display: flex;
  flex-direction: column;
  gap: var(--s-2);
}
.cell-pop-col {
  font-size: var(--fs-xs);
  text-transform: uppercase;
  letter-spacing: 0.08em;
  font-weight: var(--fw-bold);
  color: var(--text-2);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cell-pop-val {
  max-height: 120px;
  overflow: auto;
  word-break: break-word;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--surface);
  border: 1px solid var(--border);
  padding: 6px 8px;
}
/* Default ghost button (charte): 1px ink border, inverts on hover. */
.cell-pop-use {
  padding: 6px 10px;
  border: 1px solid var(--text);
  border-radius: 0;
  background: transparent;
  color: var(--text);
  font-size: var(--fs-sm);
  font-weight: var(--fw-medium);
  cursor: pointer;
  transition: all var(--dur) var(--ease);
}
.cell-pop-use:hover {
  background: var(--text);
  color: var(--bg);
}
.cell-pop-note {
  font-size: var(--fs-xs);
  color: var(--text-3);
  margin: 0;
}
</style>
