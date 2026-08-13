<script setup>
// Source Data "Analyze" workspace - ONE place, ONE model, for every computation over the
// active dataset. It replaces the two competing systems the previous version showed side
// by side (a Calculate zone AND a pivot): here a single sentence-shaped builder reads
//
//     Measure [Row count] [Sum of Revenues] (+ Add)   for [All filtered rows]
//     Measure [Sum of Revenues]             (+ Add)   by  [Solution]
//
// and the result surface adapts to it: no grouping -> KPI cards (one per measure);
// grouping -> a bar table with one column per measure. The result GROWS with what is
// asked (more measures, more groups) and UNDER it, full width, the very rows those
// figures come from - the analyzed columns pinned first (user ask 2026-08-13: the
// dataset being worked on shows completely at the bottom, no side column).
//
// Everything is DB-computed over the FULL filtered set (the same search + filters as the
// Data view), never over the visible window. The state machine lives in the shared
// aggregate surface (workspace* API); this component only renders it and lays it out.
//
// ONE workspace, TWO hosts (user ask 2026-08-13: a single structure to maintain): the
// standalone Source explorer (default, sources store) and the Evidence "Source data"
// tab (its exchange-scoped store via the `surface` prop). Both stores spread the SAME
// aggregate-surface API and the same preview-window contract, so this component is
// host-agnostic - it replaced the legacy Calculate zone + SourceAnalyze pivot.
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { useSourcesStore } from '../../stores/sources.js'
import { useScrollHints } from '../../composables/useScrollHints.js'
import {
  isTemporalColType,
  bucketOptionsFor,
  formatStatNumber,
  formatBucketKey,
  sortBucketRowsAsc,
  measureKey,
  measureLabelKey,
  barGeometry,
  orderPreviewColumns,
  MAX_WORKSPACE_MEASURES,
} from '../../composables/sourceModel.js'
import MeasurePicker from './MeasurePicker.vue'
import ScrollHints from './ScrollHints.vue'
import SourceTable from './SourceTable.vue'
import { Icon } from '../ui'

const props = defineProps({
  // Host store carrying the shared aggregate-surface workspace API + the preview-window
  // contract (previewRows / previewLoading / previewError / refreshPreviewRows /
  // totalCount). Defaults to the standalone sources store; the Evidence "Source data"
  // tab passes its exchange-scoped evidence store instead.
  surface: { type: Object, default: null },
  // Typed columns override ([{ name, type }]) for hosts whose columns do not live on
  // the surface store itself (Evidence: the exchange meta's columns).
  columns: { type: Array, default: null },
  // Provenance reported for a cell picked in the data table below (prompt context).
  // Null = the host store's own active source label.
  sourceLabel: { type: String, default: null },
})

const { t, locale } = useI18n()
const sources = props.surface || useSourcesStore()

const allColumns = computed(() => props.columns || sources.columns || [])
const measures = computed(() => sources.workspaceMeasures || [])
const atCeiling = computed(() => measures.value.length >= MAX_WORKSPACE_MEASURES)

// --- the builder ---------------------------------------------------------------
function measureLabel(m) {
  const key = measureLabelKey(m)
  if (!key) return ''
  return m.fn === 'count' ? t(key) : t(key, [m.column])
}
const groupColumn = computed(() => sources.workspaceGroup)
const groupType = computed(() => {
  const c = allColumns.value.find((x) => x.name === groupColumn.value)
  return c ? c.type : ''
})
const groupTemporal = computed(() => isTemporalColType(groupType.value))
const bucketOptions = computed(() => bucketOptionsFor(groupType.value))

function onGroupChange(e) {
  sources.setWorkspaceGroup(e.target.value || null)
}
function onBucketChange(e) {
  sources.setWorkspaceBucket(e.target.value)
}
function removeMeasure(i) {
  sources.removeWorkspaceMeasure(i)
}

// Measure picker: a teleported fixed card anchored under its trigger, so no ancestor
// overflow (the result / preview panes both scroll) can clip it. TWO triggers share it:
// [+ Add] appends a measure (editIndex null); a MEASURE CHIP swaps its own slot in
// place (user ask 2026-08-13: change a measure without remove + re-add).
const addBtn = ref(null)
const anchorEl = ref(null) // the trigger the open card is anchored to (click-outside)
const picker = ref(null) // { x, y, editIndex } | null
function openPickerAt(el, editIndex) {
  if (!el) return
  const r = el.getBoundingClientRect()
  anchorEl.value = el
  picker.value = { x: r.left, y: r.bottom + 6, editIndex }
}
function togglePicker() {
  if (picker.value && picker.value.editIndex == null) {
    picker.value = null
    return
  }
  openPickerAt(addBtn.value, null)
}
function toggleEdit(i, e) {
  if (picker.value && picker.value.editIndex === i) {
    picker.value = null
    return
  }
  openPickerAt(e.currentTarget, i)
}
function onPick(m) {
  if (picker.value && picker.value.editIndex != null) {
    sources.replaceWorkspaceMeasure(picker.value.editIndex, m.fn, m.column)
  } else {
    sources.addWorkspaceMeasure(m.fn, m.column)
  }
  picker.value = null
}

// --- the result ----------------------------------------------------------------
const grouped = computed(() => !!groupColumn.value)
// Bucketed results come back newest-first (the server cap keeps the MOST RECENT periods);
// re-sort chronologically for reading. A ranked (non-bucketed) list keeps the server's
// order: it is the ranking by the first measure.
const rows = computed(() => {
  const raw = sources.workspaceRows || []
  return groupTemporal.value ? sortBucketRowsAsc(raw) : raw
})
// The ungrouped answer is a single totals row: one KPI card per measure.
const totalsRow = computed(() => (sources.workspaceRows || [])[0] || null)
// An empty filtered selection has no figures to show: say so instead of printing a wall
// of dashes that reads like a broken screen.
const emptySelection = computed(() => sources.totalCount === 0)

// One scale PER measure (never shared): two measures can carry different units, so a bar
// may only be compared with the bars of its own column.
const measureRanges = computed(() =>
  measures.value.map((m, i) => {
    let lo = Infinity
    let hi = -Infinity
    for (const row of rows.value) {
      const v = Number(row['m' + i])
      if (!Number.isFinite(v)) continue
      if (v < lo) lo = v
      if (v > hi) hi = v
    }
    return lo === Infinity ? { min: 0, max: 0 } : { min: lo, max: hi }
  }),
)
function barStyle(row, i) {
  const range = measureRanges.value[i] || { min: 0, max: 0 }
  const g = barGeometry(row['m' + i], range.min, range.max)
  return { left: g.left + '%', width: g.width + '%' }
}
function isNegative(row, i) {
  const v = Number(row['m' + i])
  return Number.isFinite(v) && v < 0
}
function fmtStat(v) {
  return formatStatNumber(v, locale.value)
}
// The group label. A NULL key is a missing value in the data (distinct from an empty
// string, which is a real - if blank - value): both deserve their own honest label.
function groupLabel(row) {
  if (row.key == null) return t('src.ws.null_group')
  if (groupTemporal.value) {
    const label = formatBucketKey(row.key, sources.workspaceBucket)
    return label == null ? t('src.ws.null_group') : label
  }
  return row.key === '' ? t('src.an.empty_group') : String(row.key)
}
// What the 50-group cap actually kept - never an invented total (the API returns no
// group count): the most recent periods for a calendar grouping, the top 50 by the
// ranking measure otherwise.
const truncationNote = computed(() => {
  if (!sources.workspaceTruncated) return ''
  if (groupTemporal.value) return t('src.ws.last_periods')
  return t('src.ws.top', [measureLabel(measures.value[0])])
})

// Scroll affordances on the result table (5+ measures scroll horizontally).
const resultScroll = ref(null)
const resultHints = useScrollHints(resultScroll)

// --- the data preview ----------------------------------------------------------
// The columns the figures are about, pinned first in the preview: the group column, then
// each measure's column (row count has none), deduped in builder order.
const pinnedColumns = computed(() => {
  const names = []
  if (groupColumn.value) names.push(groupColumn.value)
  for (const m of measures.value) {
    if (m.column) names.push(m.column)
  }
  return names
})
const previewColumns = computed(() => orderPreviewColumns(allColumns.value, pinnedColumns.value))
const previewOpen = ref(true)

onMounted(() => {
  // Declare the workspace visible: the surface computes its first result, and the store
  // starts keeping the preview window in step with the scope.
  sources.setWorkspaceActive(true)
  sources.refreshPreviewRows()
})
onBeforeUnmount(() => {
  sources.setWorkspaceActive(false)
})
</script>

<template>
  <div class="src-ws">
    <!-- THE BUILDER - one line, full width, read as a sentence. Every chip OPENS the
         measure list to swap itself in place (no remove + re-add) and carries its own
         removal; adding is a separate, always-reachable action. -->
    <div class="ws-builder">
      <span class="ws-lead">{{ t('src.ws.lead') }}</span>
      <TransitionGroup name="ws-chip" tag="span" class="ws-chips">
        <span
          v-for="(m, i) in measures"
          :key="measureKey(m)"
          class="ws-chip"
          :class="{ open: !!picker && picker.editIndex === i }"
        >
          <button
            type="button"
            class="ws-chip-btn"
            :title="t('src.ws.change')"
            :aria-label="t('src.ws.change')"
            :aria-expanded="!!picker && picker.editIndex === i"
            @click="toggleEdit(i, $event)"
          >
            <span class="ws-chip-label">{{ measureLabel(m) }}</span>
            <Icon name="chevronDown" class="ws-chip-caret" />
          </button>
          <button
            v-if="measures.length > 1"
            type="button"
            class="ws-chip-x"
            :title="t('src.ws.remove')"
            :aria-label="t('src.ws.remove')"
            @click="removeMeasure(i)"
          ><Icon name="x" /></button>
        </span>
      </TransitionGroup>
      <button
        ref="addBtn"
        type="button"
        class="ws-add"
        :class="{ open: !!picker && picker.editIndex == null }"
        :disabled="atCeiling"
        :title="atCeiling ? t('src.ws.full', [MAX_WORKSPACE_MEASURES]) : t('src.ws.add_title')"
        :aria-label="t('src.ws.add_title')"
        :aria-expanded="!!picker && picker.editIndex == null"
        @click="togglePicker"
      ><Icon name="plus" />{{ t('src.ws.add') }}</button>

      <span class="ws-sep" aria-hidden="true" />

      <!-- The grouping is NEVER empty: with no column it reads "for all filtered rows",
           which is exactly what the KPI cards below then show. -->
      <span class="ws-prep">{{ grouped ? t('src.ws.prep_by') : t('src.ws.prep_all') }}</span>
      <span class="ws-part">
        <Icon name="layers" />
        <select
          class="ws-select"
          :aria-label="t('src.ws.group_label')"
          :value="groupColumn || ''"
          @change="onGroupChange"
        >
          <option value="">{{ t('src.ws.all_rows') }}</option>
          <option v-for="c in allColumns" :key="c.name" :value="c.name">{{ c.name }}</option>
        </select>
      </span>
      <span v-if="groupTemporal" class="ws-part">
        <Icon name="clock" />
        <select
          class="ws-select ws-bucket"
          :aria-label="t('src.ws.bucket_label')"
          :value="sources.workspaceBucket"
          @change="onBucketChange"
        >
          <option v-for="b in bucketOptions" :key="b" :value="b">{{ t('src.ws.bucket.' + b) }}</option>
        </select>
      </span>
    </div>

    <!-- RESULT above, THE DATA below - always stacked, both full width: the result grows
         with the measures, the dataset keeps the rest of the height. -->
    <div class="ws-body">
      <section class="ws-result">
        <div v-if="sources.workspaceLoading && !rows.length" class="ws-skeleton" :aria-label="t('src.loading')">
          <div v-for="n in 5" :key="'sk-' + n" class="ws-sk-row">
            <span class="sk sk-a" />
            <span class="sk sk-b" />
          </div>
        </div>
        <div v-else-if="sources.workspaceError" class="ws-state error">
          <span>{{ t('src.error') }}</span>
          <button type="button" @click="sources.runWorkspace()">{{ t('src.retry') }}</button>
        </div>
        <div v-else-if="emptySelection" class="ws-state">{{ t('src.ws.no_rows') }}</div>

        <!-- No grouping: one KPI card per measure (charte recipe - square card, orange
             top rule, caps label, big heavy figure). -->
        <div v-else-if="!grouped" class="ws-kpis" :class="{ busy: sources.workspaceLoading }">
          <div v-for="(m, i) in measures" :key="measureKey(m)" class="ws-kpi">
            <span class="ws-kpi-label">{{ measureLabel(m) }}</span>
            <span class="ws-kpi-value mono" :title="fmtStat(totalsRow ? totalsRow['m' + i] : null)">
              {{ fmtStat(totalsRow ? totalsRow['m' + i] : null) }}
            </span>
          </div>
        </div>

        <!-- Grouping: the bar table, one column per measure. -->
        <template v-else-if="rows.length">
          <div class="ws-table-wrap" :class="{ 'has-total': !!sources.workspaceTotals }">
            <div ref="resultScroll" class="ws-table-scroll" :class="{ busy: sources.workspaceLoading }">
              <table class="ws-table">
                <thead>
                  <tr>
                    <!-- The first column is named after the ACTUAL grouping (plus its
                         calendar bucket), not a generic "group": the header answers
                         "what are these rows?" before the eye reaches the figures. -->
                    <th class="ws-th-group">
                      {{ groupColumn || t('src.ws.col_group') }}<span v-if="groupTemporal" class="ws-th-bucket"> · {{ t('src.ws.bucket.' + sources.workspaceBucket) }}</span>
                    </th>
                    <th v-for="(m, i) in measures" :key="measureKey(m)" class="ws-th-value">
                      <span class="ws-th-inner">
                        <span class="ws-th-label">{{ measureLabel(m) }}</span>
                        <!-- The FIRST measure ranks the groups (server ORDER BY m0 DESC).
                             A calendar grouping is ordered by period instead. -->
                        <Icon
                          v-if="i === 0 && !groupTemporal"
                          name="chevronDown"
                          class="ws-th-rank"
                          :title="t('src.ws.ranked_by')"
                        />
                      </span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  <tr v-for="(row, r) in rows" :key="r">
                    <td class="ws-group" :title="groupLabel(row)">{{ groupLabel(row) }}</td>
                    <!-- The bar lives in an inset wrapper so it never touches the cell
                         walls: the magnitude reads as a quiet fill BEHIND the figure,
                         not as a painted column. -->
                    <td v-for="(m, i) in measures" :key="measureKey(m)" class="ws-value">
                      <span class="ws-cell">
                        <span
                          class="ws-bar"
                          :class="{ neg: isNegative(row, i) }"
                          :style="barStyle(row, i)"
                          aria-hidden="true"
                        />
                        <span class="ws-val-text mono">{{ fmtStat(row['m' + i]) }}</span>
                      </span>
                    </td>
                  </tr>
                </tbody>
                <!-- The same measures over the WHOLE filtered selection: the reference
                     every group row is read against (the backend returns it with the
                     grouped query, so this costs nothing extra). -->
                <tfoot v-if="sources.workspaceTotals">
                  <tr>
                    <td class="ws-group ws-total-label">{{ t('src.ws.all_rows') }}</td>
                    <!-- Same inset wrapper as the body cells (no bar): the totals line
                         up exactly under the figures they summarize. -->
                    <td v-for="(m, i) in measures" :key="measureKey(m)" class="ws-value ws-total-value">
                      <span class="ws-cell">
                        <span class="ws-val-text mono">{{ fmtStat(sources.workspaceTotals['m' + i]) }}</span>
                      </span>
                    </td>
                  </tr>
                </tfoot>
              </table>
            </div>
            <ScrollHints
              :can-left="resultHints.canLeft.value"
              :can-right="resultHints.canRight.value"
              :can-down="resultHints.canDown.value"
              :hidden-right="resultHints.hiddenRight.value"
              @left="resultHints.stepLeft"
              @right="resultHints.stepRight"
              @down="resultHints.stepDown"
            />
          </div>
          <div v-if="truncationNote" class="ws-note">{{ truncationNote }}</div>
        </template>
        <div v-else class="ws-state">{{ t('src.an.no_rows') }}</div>
      </section>

      <!-- THE DATA - the rows every figure above is computed on, analyzed columns first. -->
      <aside class="ws-preview" :class="{ 'is-collapsed': !previewOpen }">
        <div class="ws-preview-head">
          <span class="ws-preview-label">{{ t('src.ws.preview') }}</span>
          <!-- The counter states what IS on screen: it must stay silent while the window
               failed to load (0 rows shown would read as "the filter selects nothing"). -->
          <span v-if="!sources.previewError && sources.totalCount != null" class="ws-preview-count mono">
            {{ t('src.ws.preview_count', [sources.previewRows.length, fmtStat(sources.totalCount)]) }}
          </span>
          <span class="ws-preview-spacer" />
          <button
            type="button"
            class="ws-preview-toggle"
            :class="{ closed: !previewOpen }"
            :title="previewOpen ? t('src.ws.preview_collapse') : t('src.ws.preview_expand')"
            :aria-label="previewOpen ? t('src.ws.preview_collapse') : t('src.ws.preview_expand')"
            :aria-expanded="previewOpen"
            @click="previewOpen = !previewOpen"
          ><Icon name="chevronDown" /></button>
        </div>
        <!-- A failed window is an ERROR, never an empty table: an empty grid here would
             claim the filtered selection holds no rows. Retry re-fetches the window. -->
        <div v-if="sources.previewError" class="ws-state error">
          <span>{{ t('src.error') }}</span>
          <button type="button" @click="sources.refreshPreviewRows()">{{ t('src.retry') }}</button>
        </div>
        <!-- Its cells act on the SAME host as the figures above (surface): filtering on a
             value here re-computes the analysis, it does not touch another explorer. -->
        <SourceTable
          v-else
          preview
          :rows="sources.previewRows"
          :loading="sources.previewLoading"
          :columns="previewColumns"
          :pinned="pinnedColumns"
          :surface="surface"
          :source-label="sourceLabel"
        />
      </aside>
    </div>

    <MeasurePicker
      v-if="picker"
      :x="picker.x"
      :y="picker.y"
      :anchor="anchorEl"
      :columns="allColumns"
      :active="measures"
      @pick="onPick"
      @close="picker = null"
    />
  </div>
</template>

<style scoped>
/* The workspace IS the scrollport (user ask 2026-08-13): builder, result and the data
   table flow at their natural heights and the WHOLE surface scrolls vertically - scroll
   down to read the full dataset, scroll back up and the analysis is exactly where it
   was. Each big table still caps its own height with an inner scroll, so neither can
   turn the page into an endless tunnel. */
.src-ws { display: flex; flex-direction: column; gap: var(--s-4); flex: 1 1 auto; min-height: 0; overflow-y: auto; overflow-x: hidden; }

/* --- THE BUILDER ------------------------------------------------------------- */
/* One wrapping line, full width: the sentence stays readable before anything else
   competes for the eye. */
.ws-builder {
  display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-2);
  flex: none;
  animation: ws-rise var(--dur-slow) var(--ease-out) both;
}
@keyframes ws-rise {
  from { opacity: 0; transform: translateY(8px); }
}
@media (prefers-reduced-motion: reduce) { .ws-builder { animation: none; } }
/* Micro-label recipe (charte) for the two words that carry the grammar. */
.ws-lead, .ws-prep {
  font-size: 11px; font-weight: var(--fw-heavy); color: var(--text-2);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  flex: none;
}
.ws-chips { display: contents; }

/* A measure chip: rounded, flat, 1px filet. The BODY is a button opening the measure
   list to swap this slot in place (the caret says so); the x is its own removal. */
.ws-chip {
  display: inline-flex; align-items: center; gap: 4px; max-width: 100%;
  padding: 5px 6px 5px 12px;
  border: 1px solid var(--border-strong); border-radius: var(--r-pill);
  background: var(--src-chip-bg, var(--bg)); color: var(--text);
  font-size: var(--fs-sm);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ws-chip:hover { border-color: var(--text-3); box-shadow: var(--elev-1); }
/* Its list is open: the same open cue as the [+ Add] trigger. */
.ws-chip.open { border-color: var(--orange); }
.ws-chip-btn { display: inline-flex; align-items: center; gap: 6px; min-width: 0; color: inherit; }
.ws-chip-btn:hover .ws-chip-label { color: var(--orange-text); }
.ws-chip-label { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
/* The caret tips down on hover: the chip opens a picker, not a link (filter-chip cue). */
.ws-chip-caret { width: 11px; height: 11px; flex: none; color: var(--text-3); transition: transform var(--dur) var(--ease); }
.ws-chip-btn:hover .ws-chip-caret { transform: translateY(1px); }
.ws-chip-x {
  flex: none; display: inline-flex; padding: 3px; border-radius: var(--r-pill);
  color: var(--text-3); transition: all var(--dur) var(--ease);
}
.ws-chip-x:hover { background: var(--surface-hover); color: var(--text); }
.ws-chip-x :deep(.ui-icon) { width: 11px; height: 11px; display: block; }
/* A single measure has no removal (there is always a result): the chip keeps its
   padding so the row does not jump when a second measure arrives. */
.ws-chip:only-of-type { padding-right: 12px; }
/* Chips arrive and leave in place (the line re-flows around them). */
.ws-chip-enter-active, .ws-chip-leave-active { transition: opacity var(--dur) var(--ease), transform var(--dur) var(--ease); }
.ws-chip-enter-from, .ws-chip-leave-to { opacity: 0; transform: translateY(-4px); }
.ws-chip-leave-active { position: absolute; }
@media (prefers-reduced-motion: reduce) {
  .ws-chip, .ws-chip-x, .ws-chip-caret { transition: none; }
  .ws-chip-btn:hover .ws-chip-caret { transform: none; }
  .ws-chip-enter-active, .ws-chip-leave-active { transition: none; }
}

/* [+ Add] - separate from the chips, ghost until hovered. */
.ws-add {
  display: inline-flex; align-items: center; gap: 5px; flex: none;
  padding: 5px 12px;
  border: 1px dashed var(--border-strong); border-radius: var(--r-pill);
  background: transparent; color: var(--text-2); font-size: var(--fs-sm);
  transition: all var(--dur) var(--ease);
}
.ws-add:hover:not(:disabled) { border-style: solid; border-color: var(--text); color: var(--text); }
.ws-add.open { border-style: solid; border-color: var(--orange); color: var(--text); }
.ws-add:disabled { opacity: 0.5; cursor: not-allowed; }
.ws-add :deep(.ui-icon) { width: 12px; height: 12px; }
@media (prefers-reduced-motion: reduce) { .ws-add { transition: none; } }

/* A 1px filet between what is measured and what it is measured over. */
.ws-sep { flex: none; width: 1px; height: 18px; background: var(--border); margin: 0 var(--s-1); }

/* The grouping controls - rounded pills holding a native select (a native list can never
   be clipped by a scrolling pane, and reads with the OS the user knows). */
.ws-part {
  display: inline-flex; align-items: center; gap: 6px; min-width: 0; flex: none;
  padding: 2px 8px 2px 10px;
  border: 1px solid var(--border-strong); border-radius: var(--r-lg);
  background: var(--bg);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.ws-part:hover { border-color: var(--text-3); box-shadow: var(--elev-1); }
.ws-part:focus-within { border-color: var(--text-3); box-shadow: var(--elev-1); }
.ws-part :deep(.ui-icon) { width: 14px; height: 14px; color: var(--text-3); flex: none; }
.ws-select {
  min-width: 0; max-width: 240px; padding: 6px 2px;
  border: none; background: transparent; color: var(--text); font-size: var(--fs-sm);
}
.ws-select:focus { outline: none; }
.ws-bucket { max-width: 170px; }
@media (prefers-reduced-motion: reduce) { .ws-part { transition: none; } }

/* --- BODY: result over data --------------------------------------------------- */
/* Natural heights inside the scrolling workspace: nothing fights for the viewport. */
.ws-body { display: flex; flex-direction: column; gap: var(--s-4); flex: none; }
.ws-result { display: flex; flex-direction: column; gap: var(--s-2); flex: none; }
.ws-preview { display: flex; flex-direction: column; gap: var(--s-2); flex: none; }
/* Open: the dataset shows at its BROWSING size (~20 rows, same cap as the Data view)
   and scrolls internally through the whole 50-row window. The `.is-preview` qualifier
   out-ranks SourceTable's own 220px preview cap (same-specificity rules would
   otherwise leave the winner to compile order). */
.ws-preview:not(.is-collapsed) :deep(.src-table.is-preview .src-table-scroll) {
  max-height: min(60vh, 480px);
}

/* --- KPI cards (no grouping) --------------------------------------------------- */
.ws-kpis { display: flex; flex-wrap: wrap; gap: var(--s-3); align-content: flex-start; transition: opacity var(--dur) var(--ease); }
.ws-kpis.busy { opacity: 0.55; }
/* Charte KPI recipe: square card, 1px filet, HIGH 3px orange rule, caps label, big
   heavy figure. The one place the accent is spent on this surface. */
.ws-kpi {
  display: flex; flex-direction: column; gap: 6px;
  flex: 1 1 200px; min-width: 180px; max-width: 100%;
  padding: 14px 16px;
  border: 1px solid var(--border-strong); border-top: 3px solid var(--orange);
  border-radius: 0; background: var(--bg);
  animation: ws-rise var(--dur-slow) var(--ease-out) both;
}
.ws-kpi:nth-child(2) { animation-delay: 45ms; }
.ws-kpi:nth-child(3) { animation-delay: 90ms; }
.ws-kpi:nth-child(n + 4) { animation-delay: 135ms; }
@media (prefers-reduced-motion: reduce) { .ws-kpi, .ws-kpis { animation: none; transition: none; } }
.ws-kpi-label {
  font-size: 11px; font-weight: var(--fw-heavy); color: var(--text-2);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
.ws-kpi-value {
  font-size: 26px; line-height: 1.15; font-weight: var(--fw-heavy); color: var(--text);
  white-space: normal; overflow-wrap: anywhere;
}

/* --- Result table (grouping) --------------------------------------------------- */
.ws-table-wrap {
  position: relative; display: flex; flex-direction: column;
  border: 1px solid var(--border); border-radius: 0; min-height: 0;
}
/* Natural height up to ~half a screen, then an inner scroll (header + totals stay
   pinned): a 50-group result never buries the dataset below it. */
.ws-table-scroll { max-height: min(55vh, 520px); overflow: auto; transition: opacity var(--dur) var(--ease); }
.ws-table-scroll.busy { opacity: 0.55; }
.ws-table { width: 100%; border-collapse: separate; border-spacing: 0; font-size: var(--fs-sm); }
.ws-table thead th {
  position: sticky; top: 0; z-index: 1;
  text-align: left; padding: 9px 18px; background: var(--surface);
  box-shadow: inset 0 -1px 0 var(--border-strong);
  font-size: 11px; text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
  color: var(--text-2); font-weight: var(--fw-heavy); white-space: nowrap;
}
/* The calendar bucket rides the group header quietly (it qualifies, not competes). */
.ws-th-bucket { color: var(--text-3); font-weight: var(--fw-medium); }
/* A measure header may WRAP: French labels ("Nombre de lignes") are long, and a narrow
   dock must lose header height rather than cut the figures underneath. */
.ws-table thead th.ws-th-value { text-align: right; white-space: normal; }
.ws-th-inner { display: inline-flex; align-items: baseline; gap: 4px; text-align: right; }
/* The ranking arrow: the first measure is what ordered the groups. */
.ws-th-rank { width: 12px; height: 12px; color: var(--orange-text); flex: none; }
.ws-table tbody td {
  padding: 0; border-bottom: 1px solid var(--border); color: var(--text);
  transition: background var(--dur) var(--ease);
}
.ws-table tbody tr:last-child td { border-bottom: none; }
.ws-table tbody tr:hover td { background: var(--surface); }
.ws-table tbody tr:hover .ws-bar { background: var(--border); }
/* The group label BREATHES: never glued to the table's left wall (user ask 2026-08-13). */
.ws-group {
  padding: 9px 18px; max-width: 260px; overflow: hidden;
  text-overflow: ellipsis; white-space: nowrap;
}
.ws-value { text-align: right; min-width: 130px; }
/* Inset positioning zone for the bar + figure: the fill starts and stops INSIDE the
   cell (10px off each wall), so adjacent columns keep a visible gutter between fills. */
.ws-cell { position: relative; display: block; margin: 0 10px; }
/* Magnitude bar: a neutral span (never orange), scaled within its OWN measure. A series
   spanning zero draws around the zero line, so a negative reads as negative. */
.ws-bar {
  position: absolute; top: 7px; bottom: 7px;
  background: var(--surface-2); z-index: 0;
  transition: width var(--dur-slow) var(--ease), left var(--dur-slow) var(--ease),
    background var(--dur) var(--ease);
}
/* A negative value keeps the same neutral fill but a 2px ink edge on its zero side, so
   the direction is legible without colour. */
.ws-bar.neg { border-right: 2px solid var(--text-3); }
.ws-val-text { position: relative; z-index: 1; display: block; padding: 9px 8px; font-weight: var(--fw-semibold); }
@media (prefers-reduced-motion: reduce) { .ws-table tbody td, .ws-bar { transition: none; } }
/* Totals row - sticky at the bottom of the scroll, over a strong rule: the reference
   line stays in view while the groups scroll past it. */
.ws-table tfoot td {
  position: sticky; bottom: 0; z-index: 1;
  background: var(--surface); box-shadow: inset 0 1px 0 var(--border-strong);
  padding: 0; color: var(--text);
}
.ws-total-label {
  padding: 9px 18px; font-size: 11px; font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow); color: var(--text-2);
}
.ws-total-value .ws-val-text { font-weight: var(--fw-heavy); }
/* The "more rows below" pill clears the pinned totals row instead of sitting on it. */
.ws-table-wrap.has-total :deep(.sh-down) { bottom: 44px; }

.ws-note { font-size: var(--fs-xs); color: var(--text-3); flex: none; }

/* --- The data preview ---------------------------------------------------------- */
.ws-preview-head { display: flex; align-items: baseline; gap: var(--s-3); flex: none; }
.ws-preview-label {
  font-size: 11px; color: var(--text-2); font-weight: var(--fw-heavy);
  text-transform: uppercase; letter-spacing: var(--tracking-eyebrow);
}
.ws-preview-count { font-size: 11px; color: var(--text-3); }
.ws-preview-spacer { flex: 1; }
.ws-preview-toggle {
  flex: none; display: inline-flex; padding: 3px; border-radius: var(--r-pill);
  color: var(--text-3); align-self: center;
  transition: all var(--dur) var(--ease);
}
.ws-preview-toggle:hover { background: var(--surface-hover); color: var(--text); }
.ws-preview-toggle :deep(.ui-icon) { width: 14px; height: 14px; display: block; transition: transform var(--dur) var(--ease); }
.ws-preview-toggle.closed :deep(.ui-icon) { transform: rotate(-90deg); }
@media (prefers-reduced-motion: reduce) {
  .ws-preview-toggle, .ws-preview-toggle :deep(.ui-icon) { transition: none; }
}
/* Collapsed: the header plus a couple of rows - the data stays present without
   giving it any real height. */
.ws-preview.is-collapsed :deep(.src-table-scroll) { max-height: 96px; }

/* --- States -------------------------------------------------------------------- */
.ws-state { color: var(--text-3); font-size: var(--fs-sm); display: flex; align-items: center; gap: var(--s-3); }
.ws-state.error { color: var(--danger); }
.ws-state button {
  padding: 2px 10px; border-radius: var(--r-pill); color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.ws-state button:hover { background: var(--surface-hover); color: var(--text); }
.ws-skeleton { display: flex; flex-direction: column; gap: 6px; }
.ws-sk-row { display: flex; gap: var(--s-3); }
.sk { display: block; height: 18px; border-radius: 0; background: var(--surface-2); animation: ws-pulse 1.4s ease-in-out infinite; }
.sk-a { flex: 1; }
.sk-b { width: 120px; }
@keyframes ws-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.45; } }
@media (prefers-reduced-motion: reduce) { .sk { animation: none; } }
</style>
