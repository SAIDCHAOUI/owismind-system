<script setup>
// "Add a measure" picker of the Analyze workspace - a fixed-position card anchored to the
// [+ Add] button. It lists every measure the dataset CAN compute, one row per (function,
// column) pair chosen by measureSpecForColumn (numeric -> sum/average/median/min/max,
// temporal -> min/max, an IDENTIFIER or anything else -> distinct values), plus the row
// count, which needs no column. A pair already in the builder is shown disabled rather than
// hidden: the answer to "why can I not add it again" must be on screen.
//
// Teleported to body + position: fixed + --z-menu, exactly like ColumnMenu and
// CellActionPopover: the workspace clips its own overflow (result and preview panes scroll
// independently), so a popover living inside it would be cut off by an ancestor. This is
// the trap documented in SourceChips.vue, and the reason this is a component and not an
// absolutely-positioned div.
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { measureSpecForColumn, measureKey, measureLabelKey } from '../../composables/sourceModel.js'
import { isIdentifierColumn } from '../../composables/cellFormat.js'
import { Icon } from '../ui'

const props = defineProps({
  x: { type: Number, required: true },
  y: { type: Number, required: true },
  // The dataset columns ([{ name, type }]) the measures are built from.
  columns: { type: Array, default: () => [] },
  // The measures already in the builder ([{ fn, column }]) - offered but disabled.
  active: { type: Array, default: () => [] },
  // The trigger element the card is anchored to ([+ Add]). Treated as INSIDE by the
  // click-outside guard: the card is teleported to body, so without this a click on the
  // trigger would close the card on mousedown and its own click handler would reopen it -
  // the picker could never be dismissed from the button that opened it.
  anchor: { type: Object, default: null },
})
const emit = defineEmits(['pick', 'close'])

const { t } = useI18n()

const PICKER_W = 280
const MARGIN = 8

const rootEl = ref(null)
const term = ref('')
const pos = ref({ left: props.x, top: props.y })

// Every offerable measure, in reading order: the row count first (it needs no column and
// is the most asked figure), then each column's type-driven functions. The REAL column
// name is used verbatim (F25: this is a proof surface, not a prettified label).
const offers = computed(() => {
  const list = [{ fn: 'count', column: null, label: t('src.an.fn.count') }]
  for (const col of props.columns || []) {
    if (!col || !col.name) continue
    for (const spec of measureSpecForColumn(col.name, col.type, isIdentifierColumn(col.name))) {
      const key = measureLabelKey({ fn: spec.fn, column: col.name })
      if (!key) continue
      list.push({ fn: spec.fn, column: col.name, label: t(key, [col.name]) })
    }
  }
  return list
})

// The search filters on the COLUMN name and on the rendered label, so both "revenue" and
// "sum" find "Sum of Revenues".
const visible = computed(() => {
  const needle = term.value.trim().toLowerCase()
  if (!needle) return offers.value
  return offers.value.filter(
    (o) => o.label.toLowerCase().includes(needle)
      || String(o.column || '').toLowerCase().includes(needle),
  )
})

const activeKeys = computed(() => new Set((props.active || []).map((m) => measureKey(m))))
function isUsed(offer) {
  return activeKeys.value.has(measureKey(offer))
}

function clampToViewport() {
  const vw = window.innerWidth || 0
  const vh = window.innerHeight || 0
  const h = rootEl.value ? rootEl.value.offsetHeight : 320
  let left = props.x
  let top = props.y
  if (left + PICKER_W + MARGIN > vw) left = vw - PICKER_W - MARGIN
  if (left < MARGIN) left = MARGIN
  if (top + h + MARGIN > vh) top = vh - h - MARGIN
  if (top < MARGIN) top = MARGIN
  pos.value = { left, top }
}

// The composable unrefs each target, so the anchor travels as a computed ref.
const anchorEl = computed(() => props.anchor)
useClickOutside([rootEl, anchorEl], () => emit('close'))

function onKey(e) {
  if (e.key === 'Escape') emit('close')
}
// A resize moves the anchor button under the fixed card: close instead of drifting
// (same rule as ColumnMenu / CellActionPopover).
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
watch(() => [props.x, props.y], () => nextTick(clampToViewport))
// The list shrinks as the user types: re-clamp so a short card never floats off-screen.
watch(visible, () => nextTick(clampToViewport))
</script>

<template>
  <Teleport to="body">
    <div ref="rootEl" class="mp-card" role="dialog" :aria-label="t('src.ws.add_title')" :style="{ left: pos.left + 'px', top: pos.top + 'px' }">
      <div class="mp-head">{{ t('src.ws.picker.title') }}</div>
      <div class="mp-search">
        <Icon name="search" />
        <input
          v-model="term"
          type="text"
          class="mp-input"
          maxlength="80"
          :placeholder="t('src.picker.searchCols')"
          :aria-label="t('src.picker.searchCols')"
        />
      </div>
      <div class="mp-list" role="listbox">
        <button
          v-for="o in visible"
          :key="o.fn + ':' + (o.column || '')"
          type="button"
          class="mp-item"
          :class="{ used: isUsed(o) }"
          :disabled="isUsed(o)"
          :title="isUsed(o) ? t('src.ws.picker.used') : o.label"
          @click="emit('pick', { fn: o.fn, column: o.column })"
        >
          <span class="mp-label">{{ o.label }}</span>
          <span v-if="isUsed(o)" class="mp-tick"><Icon name="check" /></span>
        </button>
        <div v-if="!visible.length" class="mp-none">{{ t('src.picker.noColMatch') }}</div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Floating card (premium 2026-08-13): rounded --r-lg, layered --elev-2, flat inside.
   Fixed + teleported so no ancestor overflow or transform can clip or offset it. */
.mp-card {
  position: fixed;
  z-index: var(--z-menu);
  width: 280px;
  max-width: calc(100vw - 16px);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--elev-2);
  padding: var(--s-2) 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
  transform-origin: top left;
  animation: mp-in var(--dur) var(--ease-out) both;
}
@keyframes mp-in {
  from { opacity: 0; transform: translateY(-4px) scale(0.98); }
}
@media (prefers-reduced-motion: reduce) { .mp-card { animation: none; } }

.mp-head {
  padding: 4px 14px 8px;
  font-size: 11px; font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--text-2);
  border-bottom: 1px solid var(--border);
}
.mp-search {
  display: flex; align-items: center; gap: 6px;
  margin: var(--s-2) var(--s-2) 0;
  padding: 4px 8px;
  border: 1px solid var(--border); border-radius: var(--r-pill);
  background: var(--surface);
}
.mp-search :deep(.ui-icon) { width: 13px; height: 13px; color: var(--text-3); flex: none; }
.mp-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  color: var(--text); font-size: var(--fs-sm); padding: 3px 0;
}
.mp-input:focus { outline: none; }
.mp-search:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }

.mp-list { display: flex; flex-direction: column; max-height: 320px; overflow-y: auto; padding: var(--s-2) 0; }
.mp-item {
  display: flex; align-items: center; gap: 8px;
  width: calc(100% - 2 * var(--s-2));
  margin: 0 var(--s-2); padding: 7px 10px;
  background: transparent; border: 0; border-radius: var(--r-sm);
  color: var(--text); font-size: var(--fs-sm); text-align: left; cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.mp-item:hover:not(:disabled) { background: var(--surface-hover); }
.mp-item:disabled { cursor: default; color: var(--text-3); }
@media (prefers-reduced-motion: reduce) { .mp-item { transition: none; } }
.mp-label { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* The single rare orange accent: what is already measured (charte, orange text only). */
.mp-tick { flex: none; display: inline-flex; color: var(--orange-text); }
.mp-tick :deep(.ui-icon) { width: 14px; height: 14px; }
.mp-none { padding: 8px 14px; font-size: var(--fs-xs); color: var(--text-3); }
</style>
