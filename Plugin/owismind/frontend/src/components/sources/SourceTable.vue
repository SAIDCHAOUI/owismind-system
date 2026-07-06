<script setup>
// Source rows table - live rows of the active source dataset under the current
// search + user filters. Sticky header, click-to-sort, BOTH vertical and horizontal
// scroll, and LAZY / INFINITE loading: the store loads page 0, then appends the next
// page when the bottom sentinel scrolls into view (never the whole table at once).
// Mirrors the Evidence rows table mechanics on the sources store.
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { usePromptContextStore } from '../../stores/promptContext.js'
import { useToasts } from '../../composables/useToasts.js'
import { MAX_CONTEXT_VALUES, MAX_CONTEXT_VALUE_CHARS } from '../../composables/promptContextModel.js'
import { isNumericColType, formatStatNumber, chipOp } from '../../composables/sourceModel.js'
import { track } from '../../services/track.js'
import CellActionPopover from './CellActionPopover.vue'
import ColumnMenu from './ColumnMenu.vue'
import { DataLoader, Icon } from '../ui'

// Column windowing (client-side only): render the first COLS_INITIAL columns, then
// reveal COLS_MORE more each time the horizontal sentinel scrolls into view. The
// server keeps returning ALL columns; search still spans every column server-side.
const COLS_INITIAL = 30
const COLS_MORE = 20

// Mirror of the backend per-request filter cap (SourceChips.vue MAX_FILTERS): at the cap
// the add picker cannot render, so the column menu's Filter item disables instead.
const MAX_FILTERS = 20
// Mirror of the filter picker's per-chip value cap (SourceChips.vue MAX_FILTER_VALUES):
// a single equality/membership chip never accumulates more than this many values.
const MAX_FILTER_VALUES = 50

const { t, locale } = useI18n()
const sources = useSourcesStore()
const promptContext = usePromptContextStore()
const { push } = useToasts()

// The DB-computed column statistics strip (sum / avg / min / max of the sigma-expanded
// numeric column, over the FULL filtered set). Each value goes through the locale-aware
// exact formatter; a null (e.g. a fully-null column) shows as '-'.
function fmtStat(v) {
  return formatStatNumber(v, locale.value)
}
const allColumns = computed(() => sources.columns || [])
const colCount = ref(COLS_INITIAL)
const columns = computed(() => allColumns.value.slice(0, colCount.value))
const colsWindowed = computed(() => allColumns.value.length > columns.value.length)

// Reset the visible window whenever the dataset's columns change (new source). A column
// change means a new dataset, so any open header menu (anchored to a stale header) closes.
watch(allColumns, () => { colCount.value = COLS_INITIAL; closeColMenu() })

function sortDir(name) {
  const s = sources.sort
  return s && s.column === name ? s.dir : ''
}
function cell(row, name) {
  const v = row[name]
  return v == null ? '-' : String(v)
}

// Cell selection: click a non-null cell to open a popover offering to queue its value
// as context for the next question. Only one popover at a time; it closes on scroll of
// the table container and whenever the active source changes.
const popover = ref(null) // { x, y, column, value, source, canUse } | null

function closePopover() {
  popover.value = null
}
// A cell is pickable when it holds a REAL value: null and whitespace-only cells
// would normalize to nothing (a silent no-op), so they are not clickable at all.
function pickable(row, name) {
  const raw = row[name]
  return raw != null && String(raw).trim() !== ''
}
function onCellClick(event, row, name) {
  if (!pickable(row, name)) return
  const value = String(row[name])
  popover.value = {
    x: event.clientX,
    y: event.clientY,
    column: name,
    value,
    source: sources.activeSourceLabel,
    canUse: value.length <= MAX_CONTEXT_VALUE_CHARS,
  }
  track('source_cell_clicked', { column: name })
}
function usePopoverValue() {
  const p = popover.value
  if (!p) return
  const status = promptContext.add({ source: p.source, column: p.column, value: p.value })
  if (status === 'added') push(t('src.cell.added'), { tone: 'ok', icon: 'check' })
  else if (status === 'exists') push(t('src.cell.exists'), { icon: 'info' })
  else if (status === 'full') push(t('src.cell.full', [MAX_CONTEXT_VALUES]), { tone: 'warn', icon: 'info' })
  closePopover()
}

// Filter the table on the clicked cell's exact value, against the ACTIVE host sources
// store (home explorer OR the embedded agent-mode explorer in Evidence). The value is
// used RAW (the same string the popover carries for the context action), never merged
// into a temporal BETWEEN chip:
//   - an existing '=' / 'IN' chip on that column absorbs the value (deduped, capped at
//     MAX_FILTER_VALUES); if already present or at the cap, this is a silent close.
//   - otherwise (only BETWEEN chips, or none) a fresh '=' chip is added.
// The store's setChipValues / addFilter already refetch rows + aggregates and fire the
// existing source_filter_added tracking, so no extra analytics event is emitted here.
// Every outcome is acknowledged with a toast (like the "use for agent" action): a no-op
// (value already present, or the chip at its value cap) must never be a silent close.
function filterPopoverValue() {
  const p = popover.value
  if (!p) return
  const raw = p.value
  const chip = sources.chips.find((c) => c.column === p.column && chipOp(c) !== 'BETWEEN')
  if (chip) {
    const values = chip.values || []
    if (values.some((v) => String(v) === raw)) {
      push(t('src.cell.filterExists'), { icon: 'info' })
    } else if (values.length >= MAX_FILTER_VALUES) {
      push(t('src.cell.filterFull', [MAX_FILTER_VALUES]), { tone: 'warn', icon: 'info' })
    } else {
      sources.setChipValues(chip.key, values.concat([raw]))
      push(t('src.cell.filtered'), { tone: 'ok', icon: 'check' })
    }
  } else {
    sources.addFilter(p.column, [raw])
    push(t('src.cell.filtered'), { tone: 'ok', icon: 'check' })
  }
  closePopover()
}

// Filtered-column indicator + header column menu. `filteredColumns` is the set of column
// names carrying at least one user filter (drives the orange header cue + the menu's
// checkmark). The menu is a fixed-position card anchored to a header's menu trigger.
const filteredColumns = computed(() => {
  const set = new Set()
  for (const c of sources.chips) {
    if (c && c.column) set.add(c.column)
  }
  return set
})
function isFiltered(name) {
  return filteredColumns.value.has(name)
}

const colMenu = ref(null) // { x, y, column } | null
function openColMenu(event, column) {
  const r = event.currentTarget.getBoundingClientRect()
  colMenu.value = { x: r.left, y: r.bottom + 4, column }
}
function closeColMenu() {
  colMenu.value = null
}
const menuSortDir = computed(() => (colMenu.value ? sortDir(colMenu.value.column) || null : null))
const menuFiltered = computed(() => (colMenu.value ? isFiltered(colMenu.value.column) : false))
const menuCanFilter = computed(() => sources.chips.length < MAX_FILTERS)
function onMenuSort(dir) {
  if (colMenu.value) sources.setSort(colMenu.value.column, dir)
  closeColMenu()
}
function onMenuFilter() {
  if (colMenu.value) sources.requestColumnFilter(colMenu.value.column)
  closeColMenu()
}

// Close the popover + header menu when the active source changes (before meta reloads).
watch(() => sources.activeSourceId, () => { closePopover(); closeColMenu() })

// Infinite scroll: an IntersectionObserver watches a sentinel just below the last row
// inside the table's OWN scroll container. Root is the scroll container so it never
// reacts to the outer panel's scroll. `rootMargin` pre-fetches one screen early.
const scrollEl = ref(null)
const sentinelEl = ref(null)
let observer = null

function teardownObserver() {
  if (observer) {
    observer.disconnect()
    observer = null
  }
}
function setupObserver() {
  teardownObserver()
  if (typeof IntersectionObserver !== 'function') return
  if (!scrollEl.value || !sentinelEl.value) return
  observer = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) sources.loadMoreRows()
      }
    },
    { root: scrollEl.value, rootMargin: '200px 0px', threshold: 0 },
  )
  observer.observe(sentinelEl.value)
}

// (Re)bind whenever the sentinel mounts/unmounts (it only exists while there are rows
// AND more to load). watch on the ref handles the v-if churn.
watch(sentinelEl, (el) => {
  if (el) setupObserver()
  else teardownObserver()
})

// Horizontal column sentinel: a thin cell at the right edge of the header inside the
// SAME scroll container. When it enters the viewport (scrolled right) reveal the next
// batch of columns - the horizontal mirror of the vertical rows sentinel.
const colSentinelEl = ref(null)
let colObserver = null

function teardownColObserver() {
  if (colObserver) {
    colObserver.disconnect()
    colObserver = null
  }
}
function setupColObserver() {
  teardownColObserver()
  if (typeof IntersectionObserver !== 'function') return
  if (!scrollEl.value || !colSentinelEl.value) return
  colObserver = new IntersectionObserver(
    (entries) => {
      for (const entry of entries) {
        if (entry.isIntersecting) {
          colCount.value = Math.min(allColumns.value.length, colCount.value + COLS_MORE)
        }
      }
    },
    { root: scrollEl.value, rootMargin: '0px 200px', threshold: 0 },
  )
  colObserver.observe(colSentinelEl.value)
}
watch(colSentinelEl, (el) => {
  if (el) setupColObserver()
  else teardownColObserver()
})

// Close the popover + header menu when the table scrolls (anchor coordinates go stale).
function onScroll() {
  if (popover.value) closePopover()
  if (colMenu.value) closeColMenu()
}
watch(scrollEl, (el, old) => {
  if (old) old.removeEventListener('scroll', onScroll)
  if (el) el.addEventListener('scroll', onScroll, { passive: true })
})

onBeforeUnmount(() => {
  teardownObserver()
  teardownColObserver()
  if (scrollEl.value) scrollEl.value.removeEventListener('scroll', onScroll)
})
</script>

<template>
  <!-- `busy` (55% dim) only applies to refreshes with REAL rows on screen: the
       first-load skeleton must keep full opacity or its shimmer washes out. The
       DataLoader overlay rides the same condition (delayed fade-in inside it keeps
       fast refreshes flicker-free). -->
  <div class="src-table" :class="{ busy: sources.rowsLoading && sources.rows.length > 0 }">
    <DataLoader v-if="sources.rowsLoading && sources.rows.length > 0" :label="t('src.crunch')" />
    <div ref="scrollEl" class="src-table-scroll">
      <table>
        <thead>
          <tr>
            <th v-for="c in columns" :key="c.name" :class="{ sorted: sortDir(c.name), filtered: isFiltered(c.name) }">
              <div class="th-inner">
                <button type="button" class="th-btn" @click="sources.setSort(c.name)">
                  <span class="th-label">{{ c.name }}</span>
                  <span v-if="sortDir(c.name)" class="th-sort">
                    <Icon :name="sortDir(c.name) === 'asc' ? 'chevronUp' : 'chevronDown'" />
                  </span>
                </button>
                <!-- Sigma: send this numeric column to the Calculate zone (its key
                     figures over the current filter). Same toggle semantics as before. -->
                <button
                  v-if="isNumericColType(c.type)"
                  type="button"
                  class="th-sigma"
                  :class="{ active: sources.calcColumn === c.name }"
                  :title="t('src.stats.toggle')"
                  :aria-label="t('src.stats.toggle')"
                  :aria-pressed="sources.calcColumn === c.name"
                  @click.stop="sources.setCalcColumn(c.name)"
                >&#931;</button>
                <!-- Column menu trigger: 3-state sort + "Filter values...". Revealed on
                     hover/focus, and pinned visible when the column is sorted or filtered. -->
                <button
                  type="button"
                  class="th-menu"
                  :class="{ pinned: sortDir(c.name) || isFiltered(c.name) }"
                  :title="t('src.col.menu')"
                  :aria-label="t('src.col.menu')"
                  @click.stop="openColMenu($event, c.name)"
                >
                  <Icon name="chevronDown" />
                </button>
              </div>
            </th>
            <!-- Horizontal column sentinel: reveals the next batch of columns when
                 scrolled into view (client-side column windowing). -->
            <th v-if="colsWindowed" ref="colSentinelEl" class="col-sentinel" aria-hidden="true"></th>
          </tr>
        </thead>
        <!-- First load (no rows yet): pulse skeleton rows instead of a blank area.
             Refreshes with rows on screen keep the lighter `.busy` opacity dim. -->
        <tbody v-if="sources.rowsLoading && !sources.rows.length" aria-hidden="true">
          <tr v-for="n in 12" :key="'sk-' + n" class="sk-row">
            <td v-for="c in columns" :key="c.name"><span class="sk-cell" /></td>
          </tr>
        </tbody>
        <tbody v-else>
          <!-- Stable key on the accumulated index: rows only ever APPEND, so an
               index key never re-keys an already-rendered row. -->
          <tr v-for="(row, i) in sources.rows" :key="i">
            <td
              v-for="c in columns"
              :key="c.name"
              :class="{ 'cell-click': pickable(row, c.name) }"
              @click="onCellClick($event, row, c.name)"
            >{{ cell(row, c.name) }}</td>
          </tr>
        </tbody>
      </table>
      <!-- Infinite-scroll sentinel: present only while there ARE rows and the server
           still has more (and the client cap is not hit). -->
      <div
        v-if="sources.rows.length && sources.hasMore"
        ref="sentinelEl"
        class="src-table-sentinel"
        aria-hidden="true"
      >
        <span v-if="sources.rowsLoading" class="src-more-spin">{{ t('src.loadingMore') }}</span>
      </div>
      <div v-if="!sources.rows.length && !sources.rowsLoading" class="src-table-empty">
        {{ t('src.empty') }}
      </div>
    </div>
    <!-- Recoverable rows-level error: the search + filters above stay usable. -->
    <div v-if="sources.rowsError" class="src-table-error">
      <span>{{ t('src.error') }}</span>
      <button @click="sources.refreshRows()">{{ t('src.retry') }}</button>
    </div>
    <!-- Footer: how many rows are loaded, how many columns are shown, and whether
         more rows remain (lazy). -->
    <div class="src-table-foot">
      <span class="mono page">{{ t('src.loaded', [sources.rows.length]) }}</span>
      <span class="foot-spacer" />
      <span v-if="colsWindowed" class="cols-hint">{{ t('src.cols', [columns.length, allColumns.length]) }}</span>
      <span v-if="sources.hasMore" class="more-hint">{{ t('src.more') }}</span>
    </div>
    <!-- Totals bar (Excel-like status strip): the DB-EXACT row count over the current
         filter. The per-column key figures now live in the Calculate zone at the top. -->
    <div class="src-totals">
      <span class="src-totals-rows mono">
        <template v-if="sources.totalLoading && sources.totalCount == null">
          <span class="dots" aria-hidden="true"><i /><i /><i /></span>
        </template>
        <template v-else-if="sources.totalCount != null">
          {{ t('src.stats.rows', [fmtStat(sources.totalCount)]) }}
        </template>
      </span>
    </div>
  </div>
  <CellActionPopover
    v-if="popover"
    :x="popover.x"
    :y="popover.y"
    :column="popover.column"
    :value="popover.value"
    :source="popover.source"
    :can-use="popover.canUse"
    @use="usePopoverValue"
    @filter="filterPopoverValue"
    @close="closePopover"
  />
  <ColumnMenu
    v-if="colMenu"
    :x="colMenu.x"
    :y="colMenu.y"
    :column="colMenu.column"
    :sort-dir="menuSortDir"
    :filtered="menuFiltered"
    :can-filter="menuCanFilter"
    @sort="onMenuSort"
    @filter="onMenuFilter"
    @close="closeColMenu"
  />
</template>

<style scoped>
/* The table OWNS a bounded height with its own scroll so it can never collapse when
   content stacks above it (flex:none keeps it out of the squeeze). Square geometry.
   position: relative anchors the DataLoader overlay; the busy dim lives on the
   CHILDREN so the overlay itself stays at full opacity. */
.src-table {
  position: relative;
  display: flex; flex-direction: column; flex: none;
  border: 1px solid var(--border); border-radius: 0; overflow: hidden;
}
.src-table-scroll, .src-table-foot { transition: opacity var(--dur) var(--ease); }
.src-table.busy .src-table-scroll, .src-table.busy .src-table-foot { opacity: 0.55; }
.src-table.busy tbody { pointer-events: none; }
/* BOTH axes scroll: vertical for rows (~20 rows), horizontal for ALL columns. */
.src-table-scroll {
  overflow: auto;
  max-height: min(60vh, 480px);
  min-height: 220px;
}
/* separate + spacing 0: with `collapse`, the th border scrolls away from a sticky
   header - paint the line as an inset shadow so it sticks with it. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  text-align: left; box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2); font-weight: 500; white-space: nowrap; user-select: none;
}
thead th:hover { color: var(--text); }
thead th.sorted { color: var(--orange); }
/* Filtered column: orange text cue (charte: orange text only, no background fill). */
thead th.filtered { color: var(--orange-text); }
.th-inner { display: flex; align-items: center; }
.th-btn {
  display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;
  padding: 8px 12px; color: inherit; text-align: left; cursor: pointer;
}
.th-sort :deep(.ui-icon) { width: 12px; height: 12px; vertical-align: -2px; }
/* Sigma affordance in NUMERIC headers only: opens the column's DB stats in the totals
   bar. Subtle by default, orange text when active. Square, no layout shift. */
.th-sigma {
  flex: none; padding: 4px 8px; margin-right: 2px; border-radius: 0;
  font-size: 13px; line-height: 1; color: var(--text-3);
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.th-sigma:hover { color: var(--text); background: var(--surface-hover); }
.th-sigma.active { color: var(--orange-text); }
/* Column-menu trigger: hidden until the header is hovered/focused, pinned visible when
   the column is sorted or filtered. Square, no layout shift. */
.th-menu {
  flex: none; padding: 4px 6px; margin-right: 2px; border-radius: 0;
  color: var(--text-3); opacity: 0;
  transition: color var(--dur) var(--ease), opacity var(--dur) var(--ease);
}
.th-menu :deep(.ui-icon) { width: 14px; height: 14px; display: block; }
.th-menu:hover { color: var(--text); }
thead th:hover .th-menu, thead th:focus-within .th-menu, .th-menu.pinned { opacity: 1; }
/* Filtered column: the trigger is orange too (mirrors the header text cue). */
thead th.filtered .th-menu { color: var(--orange-text); opacity: 1; }
tbody td {
  padding: 7px 12px; border-bottom: 1px solid var(--border);
  color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 260px;
}
tbody tr:last-child td { border-bottom: none; }
/* Non-null cells are pickable: subtle hover cue, no layout shift. */
tbody td.cell-click { cursor: pointer; }
tbody td.cell-click:hover { background: var(--surface-hover); }
/* First-load skeleton rows - flat surface with an opacity pulse (no gradient). */
.sk-cell {
  display: block; height: 12px; width: 70%; border-radius: 0;
  background: var(--surface-2);
  animation: src-pulse 1.4s ease-in-out infinite;
}
.sk-row:nth-child(even) .sk-cell { width: 45%; }
@keyframes src-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) {
  .sk-cell { animation: none; }
}
.src-table-sentinel {
  display: flex; align-items: center; justify-content: center;
  min-height: 24px; padding: 4px;
}
.src-more-spin { font-size: 11px; color: var(--text-3); }
.src-table-empty { padding: var(--s-5); color: var(--text-3); font-size: var(--fs-sm); }
.src-table-error {
  display: flex; align-items: center; gap: var(--s-3);
  padding: 6px 12px; border-top: 1px solid var(--border);
  color: var(--danger); font-size: var(--fs-sm);
}
.src-table-error button {
  padding: 2px 10px; border-radius: 0; color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.src-table-error button:hover { background: var(--surface-hover); color: var(--text); }
/* 1px column sentinel: no border, minimal footprint - just an observable target
   at the right edge of the header content. */
.col-sentinel { width: 1px; min-width: 1px; padding: 0; box-shadow: none; background: var(--surface); }
.src-table-foot {
  display: flex; align-items: center; gap: var(--s-2);
  padding: 6px 12px; border-top: 1px solid var(--border); background: var(--surface);
}
.src-table-foot .page { font-size: 11px; color: var(--text-3); }
.src-table-foot .foot-spacer { flex: 1; }
.src-table-foot .cols-hint { font-size: 11px; color: var(--text-3); }
.src-table-foot .more-hint { font-size: 11px; color: var(--text-3); }

/* Totals bar - the DB-exact status strip (row count). Slim, flat, square, 1px top
   border. The per-column key figures now live in the Calculate zone at the top. */
.src-totals {
  display: flex; align-items: center; gap: var(--s-3);
  min-height: 30px; padding: 5px 12px;
  border-top: 1px solid var(--border-strong); background: var(--surface);
}
.src-totals-rows { font-size: var(--fs-xs); color: var(--text); font-weight: var(--fw-semibold); }
/* Loading dots - three flat squares pulsing (no gradient, charter-safe). */
.dots { display: inline-flex; align-items: center; gap: 3px; }
.dots i { width: 4px; height: 4px; background: var(--text-3); border-radius: 0; animation: src-pulse 1.2s ease-in-out infinite; }
.dots i:nth-child(2) { animation-delay: 0.2s; }
.dots i:nth-child(3) { animation-delay: 0.4s; }
</style>
