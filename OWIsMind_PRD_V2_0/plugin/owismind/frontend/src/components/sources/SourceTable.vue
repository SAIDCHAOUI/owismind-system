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
import { isNumericColType, formatStatNumber, pickCellFilterChip } from '../../composables/sourceModel.js'
import { isIdentifierColumn, formatCell } from '../../composables/cellFormat.js'
import { useScrollHints } from '../../composables/useScrollHints.js'
import { track } from '../../services/track.js'
import CellActionPopover from './CellActionPopover.vue'
import ColumnMenu from './ColumnMenu.vue'
import ScrollHints from './ScrollHints.vue'
import { DataLoader, Icon } from '../ui'

// `preview` = the compact copy the Analyze workspace shows under its figures, so the user
// always sees the rows those figures are computed on: capped height, static headers, no
// lazy append - those would fire a query from a surface meant to answer one question only
// ("what am I analyzing?"). Its CELLS, however, are as live as the browsing table's (user
// ask 2026-08-13): clicking a value offers the same two actions - queue it as context for
// the next question, or filter the whole scope on it - because the analysis and the rows
// under it share one filter state, so a cell filter re-computes the figures above too.
// The workspace feeds it its OWN bounded window (`rows`, refetched on every scope change
// by the store) and its own column ORDER (`columns`, analyzed columns first) with `pinned`
// marking them; left null, everything comes from the store exactly as the browsing table
// has always read it.
const props = defineProps({
  preview: { type: Boolean, default: false },
  rows: { type: Array, default: null },
  columns: { type: Array, default: null },
  pinned: { type: Array, default: null },
  loading: { type: Boolean, default: false },
  // Host store owning the FILTER state these cells act on (chips / addFilter /
  // setChipValues). Null = the standalone sources store, which is also the only host of
  // the browsing table; the Analyze workspace passes its own host, so a cell clicked in
  // the Evidence "Source data" tab filters the EXCHANGE scope, never the explorer's.
  surface: { type: Object, default: null },
  // Provenance reported to the prompt context for a picked cell. Null = the host's own
  // active source label (the standalone explorer knows it; the Evidence host names its
  // exchange table instead).
  sourceLabel: { type: String, default: null },
})

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

// The store the FILTER surface of this table belongs to. Everything that reads or writes
// filter chips goes through it; the browsing-only machinery (row window, sort, lazy
// append, the Analyze sigma) stays on the sources store, which is the only host that has
// it - the preview never renders those controls.
const host = computed(() => props.surface || sources)

// The DB-computed column statistics strip (sum / avg / min / max of the sigma-expanded
// numeric column, over the FULL filtered set). Each value goes through the locale-aware
// exact formatter; a null (e.g. a fully-null column) shows as '-'.
function fmtStat(v) {
  return formatStatNumber(v, locale.value)
}
// Column set + ORDER: the host's when it provides one (the workspace preview pins the
// analyzed columns first), the store's otherwise.
const allColumns = computed(() => props.columns || sources.columns || [])
const colCount = ref(COLS_INITIAL)
const columns = computed(() => allColumns.value.slice(0, colCount.value))
const colsWindowed = computed(() => allColumns.value.length > columns.value.length)
// Row window + busy flag: the host's bounded preview window, or the store's accumulating
// browsing window.
const tableRows = computed(() => (props.rows ? props.rows : sources.rows))
const tableBusy = computed(() => (props.preview ? props.loading : sources.rowsLoading))
// The analyzed columns, marked (display only - no reordering happens here, the host
// already ordered them).
const pinnedSet = computed(() => new Set(props.pinned || []))

// The columns the Analyze workspace currently measures: the sigma in a numeric header
// lights up for them, so the browsing table shows what is already being computed.
const measuredColumns = computed(() => {
  const set = new Set()
  for (const m of sources.workspaceMeasures || []) {
    if (m && m.column) set.add(m.column)
  }
  return set
})
// Sigma click: measure this column (its SUM, the most asked figure) and switch to the
// Analyze workspace, where the result appears. A column already measured is left alone -
// addWorkspaceMeasure refuses the duplicate - and the view still switches, so the click
// always lands somewhere visible.
function measureColumn(name) {
  sources.addWorkspaceMeasure('sum', name)
  sources.setAnalyzeOpen(true)
}

// Reset the visible window whenever the dataset's columns change (new source). A column
// change means a new dataset, so any open header menu (anchored to a stale header) closes.
watch(allColumns, () => { colCount.value = COLS_INITIAL; closeColMenu() })

function sortDir(name) {
  const s = sources.sort
  return s && s.column === name ? s.dir : ''
}
// Numeric QUANTITY columns by name (DSS storage type says numeric, name does not
// mark an identifier): their cells are locale-formatted and right-aligned. The
// popover / filter flows keep reading the RAW row value - display only.
const numericByName = computed(() => {
  const map = {}
  for (const c of allColumns.value) {
    if (c && c.name) map[c.name] = isNumericColType(c.type) && !isIdentifierColumn(c.name)
  }
  return map
})
function cell(row, name) {
  return formatCell(row[name], numericByName.value[name], locale.value)
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
    source: props.sourceLabel || host.value.activeSourceLabel || '',
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

// Filter on the clicked cell's exact value, against the HOST's filter state (the home
// explorer, the embedded agent-mode explorer in Evidence, or - from the Analyze preview -
// whichever store hosts the workspace). The value is used RAW (the same string the popover
// carries for the context action), never merged into a temporal BETWEEN chip; which chip
// it may join is the shared rule pickCellFilterChip (a locked agent chip is never touched):
//   - that chip absorbs the value (deduped, capped at MAX_FILTER_VALUES);
//   - no eligible chip -> a fresh '=' chip is added.
// The store's setChipValues / addFilter already refetch rows + aggregates and fire the
// existing source_filter_added tracking, so no extra analytics event is emitted here.
// Every outcome is acknowledged with a toast (like the "use for agent" action): a no-op
// (value already present, or the chip at its value cap) must never be a silent close.
function filterPopoverValue() {
  const p = popover.value
  if (!p) return
  const raw = p.value
  const chip = pickCellFilterChip(host.value.chips, p.column)
  if (chip) {
    const values = chip.values || []
    if (values.some((v) => String(v) === raw)) {
      push(t('src.cell.filterExists'), { icon: 'info' })
    } else if (values.length >= MAX_FILTER_VALUES) {
      push(t('src.cell.filterFull', [MAX_FILTER_VALUES]), { tone: 'warn', icon: 'info' })
    } else {
      host.value.setChipValues(chip.key, values.concat([raw]))
      push(t('src.cell.filtered'), { tone: 'ok', icon: 'check' })
    }
  } else {
    host.value.addFilter(p.column, [raw])
    push(t('src.cell.filtered'), { tone: 'ok', icon: 'check' })
  }
  closePopover()
}

// Filtered-column indicator + header column menu. `filteredColumns` is the set of column
// names carrying at least one user filter (drives the orange header cue + the menu's
// checkmark). The menu is a fixed-position card anchored to a header's menu trigger.
const filteredColumns = computed(() => {
  const set = new Set()
  for (const c of host.value.chips) {
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
const menuCanFilter = computed(() => host.value.chips.length < MAX_FILTERS)
function onMenuSort(dir) {
  if (colMenu.value) sources.setSort(colMenu.value.column, dir)
  closeColMenu()
}
function onMenuFilter() {
  if (colMenu.value) sources.requestColumnFilter(colMenu.value.column)
  closeColMenu()
}

// Close the popover + header menu when the host's active scope changes (before meta
// reloads): the anchored coordinates and the picked value both belong to the old scope.
// An exchange-scoped host carries no activeSourceId, so the watch simply never fires there
// (its own table swap re-mounts this component).
watch(() => host.value.activeSourceId, () => { closePopover(); closeColMenu() })

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

// The cards are FIXED and teleported to body, so a scroll of ANY ancestor moves the cell
// out from under them (the Analyze workspace is itself one scrollport, and its preview
// table rides inside it). A capture-phase document listener sees every scroll in the page
// wherever it happens; it is bound only while a card is actually open, so the common case
// costs nothing.
let docScrollBound = false
function bindDocScroll(wanted) {
  if (wanted === docScrollBound) return
  docScrollBound = wanted
  if (wanted) document.addEventListener('scroll', onScroll, { capture: true, passive: true })
  else document.removeEventListener('scroll', onScroll, { capture: true })
}
watch([popover, colMenu], ([p, m]) => bindDocScroll(!!(p || m)))

onBeforeUnmount(() => {
  teardownObserver()
  teardownColObserver()
  bindDocScroll(false)
  if (scrollEl.value) scrollEl.value.removeEventListener('scroll', onScroll)
})

// Scroll affordances: how much of the table is still out of sight (columns left/right,
// rows below) and the scroll steps the pills trigger. The column sentinel is excluded
// from the count - it is a 1px observer target, not a column.
const { canLeft, canRight, canDown, hiddenRight, stepLeft, stepRight, stepDown } =
  useScrollHints(scrollEl, { headerSelector: 'thead th:not(.col-sentinel)' })
</script>

<template>
  <!-- `busy` (55% dim) only applies to refreshes with REAL rows on screen: the
       first-load skeleton must keep full opacity or its shimmer washes out. The
       DataLoader overlay rides the same condition (delayed fade-in inside it keeps
       fast refreshes flicker-free). -->
  <div class="src-table" :class="{ busy: tableBusy && tableRows.length > 0, 'is-preview': preview }">
    <DataLoader v-if="tableBusy && tableRows.length > 0" :label="t('src.crunch')" />
    <!-- The scroll viewport and its affordance overlay share ONE positioning context, so
         the pills sit on the data edges and not on the footer bars below. -->
    <div class="src-table-view">
    <div ref="scrollEl" class="src-table-scroll">
      <table>
        <thead>
          <tr>
            <th
              v-for="c in columns"
              :key="c.name"
              :class="{ sorted: !preview && sortDir(c.name), filtered: isFiltered(c.name), num: numericByName[c.name], pinned: pinnedSet.has(c.name) }"
              :title="pinnedSet.has(c.name) ? t('src.ws.pinned') : null"
            >
              <div class="th-inner">
                <!-- Preview: a static label. Sorting would ask the server for a window
                     the Analyze view deliberately does not re-fetch. -->
                <span v-if="preview" class="th-btn th-static">
                  <span class="th-label">{{ c.name }}</span>
                </span>
                <template v-else>
                <button type="button" class="th-btn" @click="sources.setSort(c.name)">
                  <span class="th-label">{{ c.name }}</span>
                  <span v-if="sortDir(c.name)" class="th-sort">
                    <Icon :name="sortDir(c.name) === 'asc' ? 'chevronUp' : 'chevronDown'" />
                  </span>
                </button>
                <!-- Sigma: MEASURE this numeric column in the Analyze workspace (its
                     sum over the current filter) and go there. Active while the column
                     is one of the measures on screen. -->
                <button
                  v-if="numericByName[c.name]"
                  type="button"
                  class="th-sigma"
                  :class="{ active: measuredColumns.has(c.name) }"
                  :title="t('src.ws.measure_col')"
                  :aria-label="t('src.ws.measure_col')"
                  :aria-pressed="measuredColumns.has(c.name)"
                  @click.stop="measureColumn(c.name)"
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
                </template>
              </div>
            </th>
            <!-- Horizontal column sentinel: reveals the next batch of columns when
                 scrolled into view (client-side column windowing). -->
            <th v-if="colsWindowed" ref="colSentinelEl" class="col-sentinel" aria-hidden="true"></th>
          </tr>
        </thead>
        <!-- First load (no rows yet): pulse skeleton rows instead of a blank area.
             Refreshes with rows on screen keep the lighter `.busy` opacity dim. -->
        <tbody v-if="tableBusy && !tableRows.length" aria-hidden="true">
          <tr v-for="n in 12" :key="'sk-' + n" class="sk-row">
            <td v-for="c in columns" :key="c.name"><span class="sk-cell" /></td>
          </tr>
        </tbody>
        <tbody v-else>
          <!-- Stable key on the accumulated index: rows only ever APPEND, so an
               index key never re-keys an already-rendered row. -->
          <tr v-for="(row, i) in tableRows" :key="i">
            <td
              v-for="c in columns"
              :key="c.name"
              :class="{ 'cell-click': pickable(row, c.name), num: numericByName[c.name] }"
              @click="onCellClick($event, row, c.name)"
            >{{ cell(row, c.name) }}</td>
          </tr>
        </tbody>
      </table>
      <!-- Infinite-scroll sentinel: present only while there ARE rows and the server
           still has more (and the client cap is not hit). Never in the preview: it
           shows the window already loaded, it does not go asking for more. -->
      <div
        v-if="!preview && tableRows.length && sources.hasMore"
        ref="sentinelEl"
        class="src-table-sentinel"
        aria-hidden="true"
      >
        <span v-if="tableBusy" class="src-more-spin">{{ t('src.loadingMore') }}</span>
      </div>
      <div v-if="!tableRows.length && !tableBusy" class="src-table-empty">
        {{ t('src.empty') }}
      </div>
    </div>
      <ScrollHints
        :can-left="canLeft"
        :can-right="canRight"
        :can-down="canDown"
        :hidden-right="hiddenRight"
        @left="stepLeft"
        @right="stepRight"
        @down="stepDown"
      />
    </div>
    <!-- Recoverable rows-level error of the BROWSING window: the search + filters above
         stay usable. The preview has its own window (and its own error state): a browsing
         failure must not surface under rows the preview loaded fine. -->
    <div v-if="!preview && sources.rowsError" class="src-table-error">
      <span>{{ t('src.error') }}</span>
      <button @click="sources.refreshRows()">{{ t('src.retry') }}</button>
    </div>
    <!-- Footer: how many rows are loaded, how many columns are shown, and whether
         more rows remain (lazy). The preview drops it: its own header already states
         how many rows are shown out of how many the filter selects. -->
    <div v-if="!preview" class="src-table-foot">
      <span class="mono page">{{ t('src.loaded', [tableRows.length]) }}</span>
      <span class="foot-spacer" />
      <span v-if="colsWindowed" class="cols-hint">{{ t('src.cols', [columns.length, allColumns.length]) }}</span>
      <span v-if="!preview && sources.hasMore" class="more-hint">{{ t('src.more') }}</span>
    </div>
    <!-- Totals bar (Excel-like status strip): the DB-EXACT row count over the current
         filter. The per-column key figures now live in the Calculate zone at the top.
         The preview drops it: the Analyze view already states that count above it. -->
    <div v-if="!preview" class="src-totals">
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
/* Scroll viewport + its affordance overlay: ONE positioning context, hugging the data
   only (the footer bars sit outside it, so the pills stay centered on the rows). */
.src-table-view { position: relative; display: flex; flex-direction: column; min-height: 0; }
/* BOTH axes scroll: vertical for rows (~20 rows), horizontal for ALL columns. */
.src-table-scroll {
  overflow: auto;
  max-height: min(60vh, 480px);
  min-height: 220px;
}
/* Preview (Analyze view): a compact strip of the very rows being analyzed - tall enough
   to read a handful of lines, short enough to stay a companion to the pivot above. */
.src-table.is-preview .src-table-scroll { max-height: 220px; min-height: 0; }
/* A static header still reads as a header (uppercase-free real casing, F25), it just
   makes no promise of sorting. */
.th-static { cursor: default; }
/* separate + spacing 0: with `collapse`, the th border scrolls away from a sticky
   header - paint the line as an inset shadow so it sticks with it. */
table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
thead th {
  position: sticky; top: 0; z-index: 1; background: var(--surface);
  text-align: left; box-shadow: inset 0 -1px 0 var(--border);
  color: var(--text-2); font-weight: 500; white-space: nowrap; user-select: none;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
/* Sortable affordance: the whole header cell lights up under the pointer, so the
   click target reads before the menu / sigma controls fade in. */
thead th:hover { color: var(--text); background: var(--surface-hover); }
/* Preview: nothing in the header is clickable, so nothing in it lights up. */
.src-table.is-preview thead th:hover { color: var(--text-2); background: var(--surface); }
/* An ANALYZED column (the grouping, a measured column): ink label over a 2px orange
   cap - the same "this is what the figures are about" cue as a KPI card's top rule,
   discreet enough to leave the other columns readable. */
thead th.pinned { color: var(--text); box-shadow: inset 0 2px 0 var(--orange), inset 0 -1px 0 var(--border); }
.src-table.is-preview thead th.pinned:hover { color: var(--text); }
/* Sorted column: same AA-safe orange-text token as .filtered (small text). */
thead th.sorted { color: var(--orange-text); }
/* Filtered column: orange text cue (charte: orange text only, no background fill). */
thead th.filtered { color: var(--orange-text); }
.th-inner { display: flex; align-items: center; }
/* Numeric columns: header hugs the right edge, matching its right-aligned cells
   (the th content is a flex row, so text-align alone would not move it). */
thead th.num .th-inner { justify-content: flex-end; }
thead th.num .th-btn { flex: 0 1 auto; text-align: right; }
.th-btn {
  display: flex; align-items: center; gap: 4px; flex: 1; min-width: 0;
  padding: 8px 12px; color: inherit; text-align: left; cursor: pointer;
}
.th-sort :deep(.ui-icon) { width: 12px; height: 12px; vertical-align: -2px; }
/* Sigma affordance in NUMERIC headers only: opens the column's DB stats in the totals
   bar. Subtle by default, orange text when active. Rounded icon button (premium
   2026-08-13), no layout shift. */
.th-sigma {
  flex: none; padding: 4px 8px; margin-right: 2px; border-radius: var(--r-pill);
  font-size: 13px; line-height: 1; color: var(--text-3);
  transition: color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.th-sigma:hover { color: var(--text); background: var(--surface-2); }
.th-sigma.active { color: var(--orange-text); }
/* Column-menu trigger: hidden until the header is hovered/focused, pinned visible when
   the column is sorted or filtered. Rounded icon button, no layout shift. */
.th-menu {
  flex: none; padding: 4px 6px; margin-right: 2px; border-radius: var(--r-pill);
  color: var(--text-3); opacity: 0;
  transition: color var(--dur) var(--ease), opacity var(--dur) var(--ease),
    background var(--dur) var(--ease);
}
.th-menu:hover { background: var(--surface-2); }
.th-menu :deep(.ui-icon) { width: 14px; height: 14px; display: block; }
.th-menu:hover { color: var(--text); }
thead th:hover .th-menu, thead th:focus-within .th-menu, .th-menu.pinned { opacity: 1; }
/* Filtered column: the trigger is orange too (mirrors the header text cue). */
thead th.filtered .th-menu { color: var(--orange-text); opacity: 1; }
tbody td {
  padding: 7px 12px; border-bottom: 1px solid var(--border);
  color: var(--text); white-space: nowrap; overflow: hidden;
  text-overflow: ellipsis; max-width: 260px;
  transition: background var(--dur) var(--ease);
}
tbody tr:last-child td { border-bottom: none; }
/* Row-level hover: scanning a wide table, the whole line lights up so the eye keeps
   its place across the horizontal scroll. Two levels - the row on --surface, the
   hovered CELL one step further, since that is what a click actually picks. */
tbody tr:hover td { background: var(--surface); }
/* Non-null cells are pickable: subtle hover cue, no layout shift. */
tbody td.cell-click { cursor: pointer; }
tbody tr:hover td.cell-click:hover, tbody td.cell-click:hover { background: var(--surface-hover); }
@media (prefers-reduced-motion: reduce) {
  tbody td { transition: none; }
}
/* Numeric columns: right-aligned, tabular digits (values locale-formatted). */
tbody td.num { text-align: right; font-variant-numeric: tabular-nums; }
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
  padding: 2px 10px; border-radius: var(--r-pill); color: var(--text-2);
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
