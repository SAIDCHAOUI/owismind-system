// Evidence Studio store - the proof panel's state: which exchange it shows, the
// server meta (columns/chips/sql), the LOCAL editable chip state and the rows
// page. Every request is guarded by sequence numbers so a stale response can
// never overwrite a newer one - `seq` for open/close transitions, `rowsSeq` for
// out-of-order rows responses (same idiom as chat.js's cancel token).
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import {
  fetchEvidenceMeta,
  fetchEvidenceRows,
  fetchEvidenceDistinct,
} from '../services/backend.js'
import {
  chipsFromMeta,
  buildRowsPayload,
  buildDrillLabels,
  isModified,
  normalizeEditableOp,
  effectiveEvidenceQuery,
} from '../composables/evidenceModel.js'
import { track } from '../services/track.js'

// Limit/offset pagination (v2): the first load pulls a big window, then each
// "load more" appends a small one. INITIAL_LIMIT + n x MORE_LIMIT never exceeds
// MAX_ROWS (100 + 20 x 20 = 500), so the offset never passes the backend's cap.
const INITIAL_LIMIT = 100
const MORE_LIMIT = 20
// Defensive client-side cap on the ACCUMULATED (lazily appended) rows: infinite
// scroll appends window after window, so a huge source table must never grow the
// in-memory array without bound. Past MAX_ROWS the "load more" sentinel stops
// fetching (the user filters to narrow).
const MAX_ROWS = 500

export const useEvidenceStore = defineStore('evidence', () => {
  const open = ref(false)
  const exchangeId = ref(null)
  const meta = ref(null) // last /evidence/meta response (null while loading)
  // Active tab in the Evidence Studio panel: 'evidence' | 'chart' | 'table'.
  // Computed from the artifacts on each exchange load; switching tabs MUST NOT
  // toggle `open` (the ChatThread scroll gate gates only on `open`, not this ref).
  const activeTab = ref('evidence')
  const chips = ref([]) // local editable working state (evidenceModel shape)
  const includeAdvanced = ref(false)
  // Lazily ACCUMULATED rows: page 0 resets this array, every "load more" appends
  // the next page (infinite scroll). Bounded by MAX_ROWS so a huge table can
  // never blow memory. `page` is the index of the LAST loaded page.
  const rows = ref([])
  const offset = ref(0) // running count of already-loaded rows (= next window start)
  const hasMore = ref(false)
  const sort = ref(null) // { column, dir: 'asc' | 'desc' } | null
  // Full-text search over ALL columns of the active exchange table. Raw text; the
  // payload carries the effective (>= 2 chars, folded) form. Reset on exchange/close.
  const q = ref('')
  // Source-table selector (multi-table SQL): the dataset name the live rows
  // table is currently re-querying. null = the backend's default (first matched
  // table). Reset on every exchange/close; a selector is shown only when the
  // meta carries more than one matched source.
  const selectedTable = ref(null)
  // Which entry the unified "Source data" selector has active (its `key`, e.g.
  // 'legacy:<dataset>' or 'agent:<id>'). Exchange-scoped so an agent-mode dataset
  // choice survives a tab round-trip (the tab component is v-if'd and remounts).
  // null = the selector's default (the first detected/legacy entry). Reset on
  // every exchange/close.
  const sourceTabKey = ref(null)
  // Drill-down into ONE captured-result row (trust layer v2): non-null while
  // the table shows the source rows behind a result row. Carries the labels
  // sent with /evidence/rows plus a snapshot of the pre-drill view (restored
  // on exit): { labels: [{column, value}], savedChips, savedIncludeAdvanced,
  // savedSort, savedPage } | null.
  const drill = ref(null)
  const loading = ref(false) // meta fetch
  const rowsLoading = ref(false)
  const error = ref('') // META-level error code ('' = none): blanks the whole panel
  // ROWS-level error ('' = none): the chips stay mounted and interactive so the
  // user can recover (retry / change a filter) without losing the panel.
  const rowsError = ref('')

  let seq = 0 // stale-response guard for open/close transitions
  let rowsSeq = 0 // per-rows-request guard: last REQUEST wins, not last response
  let userChipSeq = 0 // keys for user-added chips

  const available = computed(() => !!(meta.value && meta.value.available))
  const modified = computed(
    () => available.value && isModified(meta.value, chips.value, includeAdvanced.value),
  )
  // The DISTINCT matched source tables the agent's SQL reads (backend meta.sources).
  // A selector is offered only when there is more than one (single-table = no UI).
  const sources = computed(() => {
    const s = meta.value && Array.isArray(meta.value.sources) ? meta.value.sources : []
    return s
  })
  const hasMultipleSources = computed(() => sources.value.length > 1)

  // Compute the default tab key for a given meta object: 'evidence' unless
  // there are artifacts, in which case the first artifact's kind wins.
  // 'evidence' is always valid (the base panel).
  function _defaultTab(m) {
    const arts = m && Array.isArray(m.artifacts) ? m.artifacts : []
    const first = arts[0]
    if (first && (first.kind === 'chart' || first.kind === 'table')) return first.kind
    return 'evidence'
  }

  function _resetData() {
    meta.value = null
    chips.value = []
    includeAdvanced.value = false
    rows.value = []
    offset.value = 0
    q.value = '' // close / new exchange = no active search
    hasMore.value = false
    sort.value = null
    selectedTable.value = null // close / new exchange = default (first matched) table
    sourceTabKey.value = null // close / new exchange = default (first detected) selector entry
    drill.value = null // close / new exchange = no drill (and nothing to restore)
    error.value = ''
    rowsError.value = ''
    loading.value = false
    rowsLoading.value = false
    activeTab.value = 'evidence' // reset to base tab; will be re-computed after meta loads
  }

  // Open the panel for one exchange. `auto` (the end-of-generation reveal) only
  // opens when meta says the interactive view is available - no degraded
  // auto-open (user decision). Manual open (the per-message button) opens
  // immediately, degraded view included.
  async function openForExchange(id, opts) {
    if (!id) return
    const auto = !!(opts && opts.auto)
    if (auto) {
      // Staged auto-reveal: fetch meta WITHOUT touching the current panel
      // state; commit only when the interactive view is confirmed available
      // and no user-initiated open/close happened meanwhile. A degraded or
      // failed auto reveal must never wipe or close what the user is viewing.
      const seqAtStart = seq
      let m
      try {
        m = await fetchEvidenceMeta(id)
      } catch (e) {
        return
      }
      if (seq !== seqAtStart || !m.available) return
      const mySeq = ++seq
      exchangeId.value = id
      _resetData()
      meta.value = m
      chips.value = chipsFromMeta(m)
      includeAdvanced.value = !!(m.advanced && m.advanced.present)
      activeTab.value = _defaultTab(m)
      open.value = true
      track('evidence_panel_opened', { auto: true })
      await _loadRows(mySeq)
      return
    }
    // Manual open (per-message button): opens immediately, degraded view included.
    const mySeq = ++seq
    exchangeId.value = id
    _resetData()
    open.value = true
    track('evidence_panel_opened', { auto: false })
    loading.value = true
    try {
      const m = await fetchEvidenceMeta(id)
      if (mySeq !== seq) return
      meta.value = m
      chips.value = chipsFromMeta(m)
      includeAdvanced.value = !!(m.advanced && m.advanced.present)
      activeTab.value = _defaultTab(m)
      if (m.available) await _loadRows(mySeq)
    } catch (e) {
      if (mySeq !== seq) return
      error.value = (e && e.message) || 'evidence_unavailable'
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  // Lazily load ONE window of rows. `append` selects the mode:
  //   - false (default): a FRESH first window (offset 0) - replaces the
  //     accumulated rows (used on open / search / filter / sort / drill / table).
  //   - true: load the NEXT window (offset = rows.length) and APPEND to the
  //     accumulated rows (the infinite-scroll sentinel). The accumulated array is
  //     capped at MAX_ROWS so a huge source table can never grow it without bound.
  // Tri-state result: true = latest request succeeded, false = latest request
  // FAILED (no append/reset committed), null = superseded by a newer
  // request/close (no rollback - something else owns the state now).
  async function _loadRows(mySeq, opts) {
    const append = !!(opts && opts.append)
    const targetOffset = append ? rows.value.length : 0
    const targetLimit = append ? MORE_LIMIT : INITIAL_LIMIT
    const myRows = ++rowsSeq
    rowsLoading.value = true
    try {
      const payload = buildRowsPayload(
        exchangeId.value, chips.value, includeAdvanced.value, targetLimit, targetOffset, sort.value,
        drill.value ? drill.value.labels : null, selectedTable.value, q.value,
      )
      const data = await fetchEvidenceRows(payload)
      if (mySeq !== seq || myRows !== rowsSeq) return null
      const newRows = data.rows || []
      // Adopt the server-echoed offset: the backend silently CLAMPS an out-of-range
      // offset; appending a clamped window would duplicate rows, so we only append
      // when the server honoured the exact offset we asked for (= current tail).
      const echoed = typeof data.offset === 'number' && data.offset >= 0 ? data.offset : targetOffset
      if (append) {
        if (echoed === rows.value.length) {
          rows.value = rows.value.concat(newRows).slice(0, MAX_ROWS)
        }
      } else {
        rows.value = newRows.slice(0, MAX_ROWS)
      }
      offset.value = echoed
      // Stop paging once the server has no more rows OR the client cap is hit.
      hasMore.value = !!data.has_more && rows.value.length < MAX_ROWS
      return true
    } catch (e) {
      if (mySeq !== seq || myRows !== rowsSeq) return null
      rowsError.value = (e && e.message) || 'evidence_unavailable'
      return false
    } finally {
      if (mySeq === seq && myRows === rowsSeq) rowsLoading.value = false
    }
  }

  // Fresh reload (page 0): used by every filter / sort / drill / table change.
  function refreshRows() {
    error.value = ''
    rowsError.value = ''
    return _loadRows(seq)
  }

  // Infinite-scroll: append the next window when the sentinel scrolls into view.
  // Bounded by hasMore (server) and MAX_ROWS (client); never fetches everything.
  function loadMoreRows() {
    if (!hasMore.value || rowsLoading.value) return Promise.resolve(null)
    if (rows.value.length >= MAX_ROWS) return Promise.resolve(null)
    return _loadRows(seq, { append: true })
  }

  // Search the WHOLE active exchange table (all columns). The caller fires this on
  // Enter / an explicit search button only (no debounce). Stores the raw text but
  // skips a pointless refetch when the EFFECTIVE term is unchanged (e.g. a 1st char
  // still below the 2-char threshold). A fresh reload starts at offset 0.
  function setQuery(value) {
    const next = value == null ? '' : String(value)
    if (next === q.value) return
    const before = effectiveEvidenceQuery(q.value)
    q.value = next
    if (effectiveEvidenceQuery(next) === before) return
    // Record only the length (never the search text itself - it can carry PII).
    track('evidence_searched', { len: next.length })
    offset.value = 0
    refreshRows()
  }

  function close() {
    // Only a real open->closed transition is a user action worth recording (close() is
    // also called idempotently on new-exchange / open-session, when nothing was open).
    if (open.value) track('evidence_panel_closed', {})
    seq += 1 // invalidate any in-flight request
    open.value = false
    exchangeId.value = null
    _resetData()
  }

  // --- filter editing (picker = / IN + removal + add + reset) -----------------
  function removeChip(key) {
    const chip = chips.value.find((c) => c.key === key)
    track('evidence_filter_removed', { column: chip ? chip.column : null })
    chips.value = chips.value.filter((c) => c.key !== key)
    offset.value = 0
    refreshRows()
  }
  function setChipValues(key, values) {
    const chip = chips.value.find((c) => c.key === key)
    if (!chip || !values.length) return
    chip.values = values.slice()
    chip.op = normalizeEditableOp(values)
    // Editing a comparison chip (>=, BETWEEN, LIKE…) converts it to =/IN of the
    // picked values: it now travels as a structured client filter instead of a
    // server-side kept id (see evidenceModel.buildRowsPayload).
    chip.editable = true
    offset.value = 0
    refreshRows()
  }
  function addFilter(column, values) {
    if (!column || !values.length) return
    track('evidence_filter_added', { column })
    userChipSeq += 1
    chips.value.push({
      key: 'u' + userChipSeq,
      id: null,
      column,
      op: normalizeEditableOp(values),
      values: values.slice(),
      editable: true,
      source: 'user',
    })
    offset.value = 0
    refreshRows()
  }
  function removeAdvanced() {
    includeAdvanced.value = false
    offset.value = 0
    refreshRows()
  }
  function resetToAgent() {
    chips.value = chipsFromMeta(meta.value)
    includeAdvanced.value = !!(meta.value && meta.value.advanced && meta.value.advanced.present)
    offset.value = 0
    sort.value = null
    // Back to the agent view = out of any drill. The drill snapshot is NOT
    // restored - the reset target IS the agent scope, not the pre-drill view.
    drill.value = null
    refreshRows()
  }

  // --- drill-down (trust layer v2) ---------------------------------------------
  // Pivot the table to the SOURCE ROWS behind one captured-result row. Only
  // reachable when the server vouched for it (drilldown.available) AND the
  // exact agent result was captured: the labels are built from the CAPTURED
  // row, never from the live table, so the drill proves what the agent used.
  // The pre-drill view (chips/advanced/sort) is snapshotted for exitDrill; exit
  // does a fresh reload at offset 0, so no scroll offset needs saving.
  function drillIntoResultRow(rowIndex) {
    const m = meta.value
    if (!m || !m.result || !m.result.captured) return
    if (!m.drilldown || !m.drilldown.available) return
    const cols = m.drilldown.columns
    if (!Array.isArray(cols) || !cols.length) return
    const row = Array.isArray(m.result.rows) ? m.result.rows[rowIndex] : null
    if (!Array.isArray(row)) return
    // Capped at 8 labels (backend mirror); null = unmappable column/value -
    // abort silently rather than drill on a partial (lying) scope.
    const labels = buildDrillLabels(cols, m.result.columns, row)
    if (!labels) return
    track('evidence_row_drilled', {})
    // Consecutive drill (chevron clicked while already drilling): keep the
    // ORIGINAL pre-drill snapshot - only the labels change. Re-snapshotting
    // here would capture the in-drill view, and exitDrill would then restore
    // the drill instead of the user's pre-drill context (FRONT-UX-02).
    const prev = drill.value
    drill.value = prev
      ? { ...prev, labels }
      : {
          labels,
          // Plain deep-enough copies: a chip only holds primitives + a values array.
          savedChips: chips.value.map((c) => ({ ...c, values: c.values.slice() })),
          savedIncludeAdvanced: includeAdvanced.value,
          savedSort: sort.value ? { ...sort.value } : null,
        }
    offset.value = 0
    // The rows table lives in the Sources tab; the drill chevron sits on the
    // Evidence tab. Land the user on the tab that renders the drilled rows so the
    // click has a visible surface (setActiveTab never touches `open`, F13).
    activeTab.value = 'sources'
    refreshRows()
  }

  function exitDrill() {
    const d = drill.value
    if (!d) return
    // Restore the exact pre-drill view (the snapshot copies are detached, so
    // handing them back to the refs cannot alias the dropped drill object).
    chips.value = d.savedChips
    includeAdvanced.value = d.savedIncludeAdvanced
    sort.value = d.savedSort
    offset.value = 0 // restore = fresh reload from the top with the saved filters
    drill.value = null
    refreshRows()
  }

  // --- table interactions ------------------------------------------------------
  function setSort(column) {
    sort.value =
      sort.value && sort.value.column === column
        ? { column, dir: sort.value.dir === 'asc' ? 'desc' : 'asc' }
        : { column, dir: 'asc' }
    offset.value = 0
    refreshRows()
  }
  // Switch the live rows table to another matched source dataset (multi-table
  // SQL). Resets the lazy state and re-queries page 0 of THAT table. A drill is
  // dropped (its group keys are scoped to the previous table). No-op when the
  // name is the current one or not among the matched sources.
  function setTable(name) {
    if (name === selectedTable.value) return
    if (name != null && !sources.value.some((s) => s.dataset === name)) return
    selectedTable.value = name || null
    // A different table = a different schema: the agent's filters no longer
    // resolve there, so drop them back to the table's own scope (page 0, no
    // drill). Chips for the new table are NOT in this meta, so show all rows.
    chips.value = []
    includeAdvanced.value = false
    sort.value = null
    drill.value = null
    offset.value = 0
    refreshRows()
  }

  // Distinct values for the picker - returned to the caller (the popover owns
  // its own transient open/loading state), never stored here. NOT staleness-
  // guarded: the popover must drop a result that resolves after the panel
  // moved on (it closes on outside-click anyway). `excludeId` = server id of
  // the chip being edited (its predicate must not scope its own picker). `q`
  // (optional) narrows the window server-side over ALL values; empty/absent
  // keeps the default top-N.
  function loadDistinct(column, excludeId, q) {
    if (!exchangeId.value) return Promise.reject(new Error('evidence_unavailable'))
    return fetchEvidenceDistinct(exchangeId.value, column, excludeId, q)
  }

  // Map each real tab key to a FIRST-CLASS analytics event, so dashboards read
  // feature usage directly (which tab users open) instead of one generic event
  // with a `tab` prop. Any future/unknown key falls back to evidence_tab_viewed
  // carrying the raw key. The keys mirror EvidencePanel.tabItems.
  const _TAB_EVENT_BY_KEY = {
    evidence: 'evidence_proof_viewed',
    sources: 'source_data_viewed',
    chart: 'chart_viewed',
    table: 'table_viewed',
    kpi: 'kpi_viewed',
  }

  // Switch the active tab. Switching MUST NOT touch `open` (the ChatThread scroll
  // gate is gated on `evidence.open`, not on `activeTab` - F13 rule).
  function setActiveTab(key) {
    activeTab.value = key
    const name = _TAB_EVENT_BY_KEY[key]
    if (name) track(name, {})
    else track('evidence_tab_viewed', { tab: key })
  }

  return {
    open, exchangeId, meta, chips, includeAdvanced, rows, offset, hasMore, sort, drill, q,
    loading, rowsLoading, error, rowsError, available, modified,
    sources, hasMultipleSources, selectedTable, sourceTabKey,
    activeTab, setActiveTab, setQuery,
    openForExchange, close, refreshRows, loadMoreRows,
    removeChip, setChipValues, addFilter, removeAdvanced, resetToAgent,
    drillIntoResultRow, exitDrill,
    setSort, setTable, loadDistinct,
  }
})
