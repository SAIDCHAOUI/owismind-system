<script setup>
// "Add a measure" picker of the Analyze workspace - a fixed-position card anchored to the
// [+ Add] button (or to the measure chip it swaps). It lists every measure the dataset CAN
// compute, GROUPED BY COLUMN TYPE (user ask 2026-10-20: readable at a glance): the row
// count, then Numbers (sum / average / median / min / max under each column), Dates
// (min / max), then Text and identifiers (distinct values, one line per column). The
// grouping and the search live in the pure measurePickerModel (node:test).
//
// Keyboard: focus lands in the search; ArrowDown / ArrowUp walk the options (skipping the
// ones already measured, wrapping around), Enter adds the highlighted one, Escape and Tab
// close and hand the focus back to the trigger. Combobox + listbox semantics
// (aria-activedescendant): the focus never leaves the search while the list is walked.
//
// A measure already in the builder is shown disabled with the orange tick rather than
// hidden: the answer to "why can I not add it again" must be on screen.
//
// Teleported to body + position: fixed + --z-menu, exactly like ColumnMenu and
// CellActionPopover: the workspace clips its own overflow (result and data panes scroll
// independently), so a popover living inside it would be cut off by an ancestor. This is
// the trap documented in SourceChips.vue, and the reason this is a component and not an
// absolutely-positioned div.
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useClickOutside } from '../../composables/useClickOutside.js'
import { measureKey, measureLabelKey } from '../../composables/sourceModel.js'
import {
  buildMeasureGroups,
  filterMeasureGroups,
  flattenMeasureOptions,
  stepMeasureOption,
  measureShortLabelKey,
} from '../../composables/measurePickerModel.js'
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

const PICKER_W = 320
const MARGIN = 8
// Unique DOM ids per instance (aria-activedescendant / aria-labelledby targets).
const uid = 'mp-' + Math.random().toString(36).slice(2, 9)
const listId = uid + '-list'

const rootEl = ref(null)
const inputEl = ref(null)
const listEl = ref(null)
const term = ref('')
const pos = ref({ left: props.x, top: props.y })

// Full label ("Sum of Revenues", "Row count"): the title, the aria label and the search
// target. The REAL column name is used verbatim (F25: proof surface).
function fullLabel(o) {
  const key = measureLabelKey(o)
  if (!key) return ''
  return o.fn === 'count' ? t(key) : t(key, [o.column])
}
// Short label inside a column block ("Sum"): the column is already named above it.
function shortLabel(o) {
  const key = measureShortLabelKey(o.fn)
  return key ? t(key) : ''
}

const allGroups = computed(() => buildMeasureGroups(props.columns, isIdentifierColumn))
const groups = computed(() => filterMeasureGroups(allGroups.value, term.value, fullLabel))
const flat = computed(() => flattenMeasureOptions(groups.value))
const indexByKey = computed(() => {
  const map = new Map()
  flat.value.forEach((o, i) => map.set(o.key, i))
  return map
})

const activeKeys = computed(() => new Set((props.active || []).map((m) => measureKey(m))))
function isUsed(o) {
  return activeKeys.value.has(o.key)
}

// The highlighted option (index in `flat`, -1 = none). Reset to the first pickable one
// whenever the visible list changes (typing narrows it).
const activeIndex = ref(-1)
watch(flat, () => {
  activeIndex.value = stepMeasureOption(flat.value, -1, 1, isUsed)
}, { immediate: true })
const activeId = computed(() => (activeIndex.value >= 0 ? optionId(activeIndex.value) : null))
function optionId(i) {
  return uid + '-o' + i
}
function idxOf(o) {
  const i = indexByKey.value.get(o.key)
  return i == null ? -1 : i
}
// Keep the highlighted row in sight while the keyboard walks a long list.
watch(activeIndex, (i) => {
  if (i < 0) return
  nextTick(() => {
    const el = listEl.value && listEl.value.querySelector('#' + optionId(i))
    if (el && typeof el.scrollIntoView === 'function') el.scrollIntoView({ block: 'nearest' })
  })
})

function pick(o) {
  if (!o || isUsed(o)) return
  emit('pick', { fn: o.fn, column: o.column })
}
function hover(o) {
  if (isUsed(o)) return
  const i = idxOf(o)
  if (i >= 0) activeIndex.value = i
}

function onInputKey(e) {
  if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault()
    activeIndex.value = stepMeasureOption(flat.value, activeIndex.value, e.key === 'ArrowDown' ? 1 : -1, isUsed)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    if (activeIndex.value >= 0) pick(flat.value[activeIndex.value])
  } else if (e.key === 'Tab') {
    // A popup listbox closes on Tab; the focus goes back to its trigger (the card sits at
    // the end of <body>, so the natural Tab order would drop it out of the panel).
    e.preventDefault()
    emit('close')
  }
}

function clampToViewport() {
  const vw = window.innerWidth || 0
  const vh = window.innerHeight || 0
  const h = rootEl.value ? rootEl.value.offsetHeight : 360
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
  nextTick(() => {
    clampToViewport()
    if (inputEl.value) inputEl.value.focus({ preventScroll: true })
  })
})
onBeforeUnmount(() => {
  document.removeEventListener('keydown', onKey, true)
  window.removeEventListener('resize', onResize)
  // Closed from the keyboard (Escape, Tab, Enter): give the focus back to the trigger so
  // the next Tab continues from the builder, not from the end of the page.
  const root = rootEl.value
  if (root && root.contains(document.activeElement) && props.anchor && typeof props.anchor.focus === 'function') {
    props.anchor.focus({ preventScroll: true })
  }
})
watch(() => [props.x, props.y], () => nextTick(clampToViewport))
// The list shrinks as the user types: re-clamp so a short card never floats off-screen.
watch(flat, () => nextTick(clampToViewport))
</script>

<template>
  <Teleport to="body">
    <div
      ref="rootEl"
      class="mp-card"
      role="dialog"
      :aria-label="t('src.ws.add_title')"
      :style="{ left: pos.left + 'px', top: pos.top + 'px' }"
    >
      <div class="mp-head">{{ t('src.ws.picker.title') }}</div>
      <div class="mp-search">
        <Icon name="search" />
        <input
          ref="inputEl"
          v-model="term"
          type="text"
          class="mp-input"
          maxlength="80"
          role="combobox"
          aria-autocomplete="list"
          aria-expanded="true"
          :aria-controls="listId"
          :aria-activedescendant="activeId"
          :placeholder="t('src.picker.searchCols')"
          :aria-label="t('src.picker.searchCols')"
          @keydown="onInputKey"
        />
      </div>
      <div :id="listId" ref="listEl" class="mp-list" role="listbox" :aria-label="t('src.ws.picker.title')">
        <div
          v-for="g in groups"
          :key="g.kind"
          class="mp-group"
          role="group"
          :aria-labelledby="uid + '-g-' + g.kind"
        >
          <div :id="uid + '-g-' + g.kind" class="mp-group-title" role="presentation">{{ t('src.ws.picker.g.' + g.kind) }}</div>
          <template v-for="c in g.columns" :key="c.name == null ? '_rows' : 'c:' + c.name">
            <!-- One function only (row count, distinct values of a text column): ONE line,
                 the column name first and the function as a quiet hint on the right. -->
            <div
              v-if="c.options.length === 1"
              :id="optionId(idxOf(c.options[0]))"
              class="mp-opt"
              :class="{ active: idxOf(c.options[0]) === activeIndex, used: isUsed(c.options[0]) }"
              role="option"
              :aria-selected="idxOf(c.options[0]) === activeIndex"
              :aria-disabled="isUsed(c.options[0])"
              :aria-label="fullLabel(c.options[0])"
              :title="isUsed(c.options[0]) ? t('src.ws.picker.used') : fullLabel(c.options[0])"
              @mousedown.prevent
              @mousemove="hover(c.options[0])"
              @click="pick(c.options[0])"
            >
              <span class="mp-opt-name">{{ c.name == null ? shortLabel(c.options[0]) : c.name }}</span>
              <span v-if="c.name != null" class="mp-opt-fn">{{ shortLabel(c.options[0]) }}</span>
              <span v-if="isUsed(c.options[0])" class="mp-tick"><Icon name="check" /></span>
            </div>
            <!-- Several functions: the column as a sub-heading, its functions beneath. -->
            <template v-else>
              <div class="mp-col" role="presentation" :title="c.name">{{ c.name }}</div>
              <div
                v-for="o in c.options"
                :id="optionId(idxOf(o))"
                :key="o.key"
                class="mp-opt mp-opt-sub"
                :class="{ active: idxOf(o) === activeIndex, used: isUsed(o) }"
                role="option"
                :aria-selected="idxOf(o) === activeIndex"
                :aria-disabled="isUsed(o)"
                :aria-label="fullLabel(o)"
                :title="isUsed(o) ? t('src.ws.picker.used') : fullLabel(o)"
                @mousedown.prevent
                @mousemove="hover(o)"
                @click="pick(o)"
              >
                <span class="mp-opt-name">{{ shortLabel(o) }}</span>
                <span v-if="isUsed(o)" class="mp-tick"><Icon name="check" /></span>
              </div>
            </template>
          </template>
        </div>
        <div v-if="!flat.length" class="mp-none">{{ t('src.picker.noColMatch') }}</div>
      </div>
    </div>
  </Teleport>
</template>

<style scoped>
/* Floating card: V2 floating radius (--r-lg, like ui/Menu and the filter popover), 1px filet, the floating-layer elevation token, flat
   inside. Fixed + teleported so no ancestor overflow or transform can clip or offset it.
   --paper steps one level above the dark canvas (charte V2 section 4). */
.mp-card {
  position: fixed;
  z-index: var(--z-menu);
  width: 320px;
  max-width: calc(100vw - 16px);
  background: var(--paper);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-lg);
  box-shadow: var(--float);
  display: flex;
  flex-direction: column;
  min-height: 0;
  animation: mp-in var(--dur) var(--ease-out) both;
}
/* Entry: a short fade + 4px drop, never a scale (charte motion). */
@keyframes mp-in {
  from { opacity: 0; transform: translateY(-4px); }
}
@media (prefers-reduced-motion: reduce) { .mp-card { animation: none; } }

/* Micro-label heading (charte recipe) over a soft filet. */
.mp-head {
  padding: 10px 12px 9px;
  font-size: 11px; font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--text-2);
  border-bottom: 1px solid var(--border);
}
/* Search: compact field (--r-pill, like the filter popover search); focus = --text-3 border + elevation (the field recipe). */
.mp-search {
  display: flex; align-items: center; gap: 8px; flex: none;
  margin: var(--s-2);
  height: 36px; box-sizing: border-box; padding: 0 10px;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.mp-search :deep(.ui-icon) { width: 14px; height: 14px; color: var(--text-3); flex: none; }
.mp-input {
  flex: 1; min-width: 0; border: none; background: transparent;
  color: var(--text); font-size: var(--fs-sm); padding: 0;
}
.mp-input:focus { outline: none; }
.mp-input::placeholder { color: var(--text-3); }
.mp-search:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }
@media (prefers-reduced-motion: reduce) { .mp-search { transition: none; } }

.mp-list {
  display: flex; flex-direction: column; min-height: 0;
  max-height: min(380px, 60vh); overflow-y: auto; padding-bottom: var(--s-2);
}
/* A type group: caps micro-label, separated from the previous group by a soft filet. */
.mp-group { display: flex; flex-direction: column; }
.mp-group + .mp-group { border-top: 1px solid var(--border); margin-top: var(--s-1); }
.mp-group-title {
  padding: 10px 12px 4px;
  font-size: 11px; font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--text-2);
}
/* A column inside a multi-function group: its REAL name in ink, functions beneath. */
.mp-col {
  padding: 8px 12px 2px;
  font-size: var(--fs-xs); font-weight: var(--fw-bold); color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* An option: a 36px list row, inset like ui/Menu items (--r-sm). Highlight = one surface
   step (pointer and keyboard share it, so there is never a second, competing highlight). */
.mp-opt {
  display: flex; align-items: center; gap: 8px;
  min-height: 36px; padding: 0 8px; margin: 0 var(--s-1); border-radius: var(--r-sm);
  font-size: var(--fs-sm); color: var(--text);
  cursor: pointer; user-select: none;
  transition: background var(--dur-fast) var(--ease);
}
/* Functions under their column sit one indent in: the column reads as their heading. */
.mp-opt-sub { padding-left: 20px; min-height: 32px; }
.mp-opt.active { background: var(--surface-hover); }
.mp-opt.used { color: var(--text-3); cursor: default; }
@media (prefers-reduced-motion: reduce) { .mp-opt { transition: none; } }
.mp-opt-name { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mp-opt-fn { flex: none; font-size: var(--fs-xs); color: var(--text-3); }
.mp-opt.used .mp-opt-fn { color: var(--text-3); }
/* The single rare orange accent: what is already measured (charte, orange text only). */
.mp-tick { flex: none; display: inline-flex; color: var(--orange-text); }
.mp-tick :deep(.ui-icon) { width: 14px; height: 14px; }
.mp-none { padding: 10px 12px; font-size: var(--fs-xs); color: var(--text-3); }
</style>
