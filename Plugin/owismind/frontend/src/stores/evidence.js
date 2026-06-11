// Evidence Studio store — the proof panel's state: which exchange it shows, the
// server meta (columns/chips/sql), the LOCAL editable chip state and the rows
// page. Every request is guarded by sequence numbers so a stale response can
// never overwrite a newer one — `seq` for open/close transitions, `rowsSeq` for
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
} from '../composables/evidenceModel.js'

// Deepest browsable page index — mirrors the backend's MAX_EVIDENCE_PAGE
// (security/validation.py): the server silently clamps anything deeper.
const MAX_PAGE = 20

export const useEvidenceStore = defineStore('evidence', () => {
  const open = ref(false)
  const exchangeId = ref(null)
  const meta = ref(null) // last /evidence/meta response (null while loading)
  const chips = ref([]) // local editable working state (evidenceModel shape)
  const includeAdvanced = ref(false)
  const rows = ref([])
  const page = ref(0)
  const hasMore = ref(false)
  const sort = ref(null) // { column, dir: 'asc' | 'desc' } | null
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

  function _resetData() {
    meta.value = null
    chips.value = []
    includeAdvanced.value = false
    rows.value = []
    page.value = 0
    hasMore.value = false
    sort.value = null
    drill.value = null // close / new exchange = no drill (and nothing to restore)
    error.value = ''
    rowsError.value = ''
    loading.value = false
    rowsLoading.value = false
  }

  // Open the panel for one exchange. `auto` (the end-of-generation reveal) only
  // opens when meta says the interactive view is available — no degraded
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
      open.value = true
      await _loadRows(mySeq)
      return
    }
    // Manual open (per-message button): opens immediately, degraded view included.
    const mySeq = ++seq
    exchangeId.value = id
    _resetData()
    open.value = true
    loading.value = true
    try {
      const m = await fetchEvidenceMeta(id)
      if (mySeq !== seq) return
      meta.value = m
      chips.value = chipsFromMeta(m)
      includeAdvanced.value = !!(m.advanced && m.advanced.present)
      if (m.available) await _loadRows(mySeq)
    } catch (e) {
      if (mySeq !== seq) return
      error.value = (e && e.message) || 'evidence_unavailable'
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  // Tri-state result: true = latest request succeeded, false = latest request
  // FAILED (pagination rolls back on this), null = superseded by a newer
  // request/close (no rollback — something else owns the state now).
  async function _loadRows(mySeq) {
    const myRows = ++rowsSeq
    rowsLoading.value = true
    try {
      const payload = buildRowsPayload(
        exchangeId.value, chips.value, includeAdvanced.value, page.value, sort.value,
        drill.value ? drill.value.labels : null,
      )
      const data = await fetchEvidenceRows(payload)
      if (mySeq !== seq || myRows !== rowsSeq) return null
      rows.value = data.rows || []
      hasMore.value = !!data.has_more
      // Adopt the server-echoed page: the backend silently CLAMPS deep pages
      // (MAX_EVIDENCE_PAGE), and a counter that keeps incrementing past the
      // clamp would page forever over the same rows.
      if (typeof data.page === 'number' && data.page >= 0) page.value = data.page
      return true
    } catch (e) {
      if (mySeq !== seq || myRows !== rowsSeq) return null
      rowsError.value = (e && e.message) || 'evidence_unavailable'
      return false
    } finally {
      if (mySeq === seq && myRows === rowsSeq) rowsLoading.value = false
    }
  }

  function refreshRows() {
    error.value = ''
    rowsError.value = ''
    return _loadRows(seq)
  }

  function close() {
    seq += 1 // invalidate any in-flight request
    open.value = false
    exchangeId.value = null
    _resetData()
  }

  // --- filter editing (picker = / IN + removal + add + reset) -----------------
  function removeChip(key) {
    chips.value = chips.value.filter((c) => c.key !== key)
    page.value = 0
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
    page.value = 0
    refreshRows()
  }
  function addFilter(column, values) {
    if (!column || !values.length) return
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
    page.value = 0
    refreshRows()
  }
  function removeAdvanced() {
    includeAdvanced.value = false
    page.value = 0
    refreshRows()
  }
  function resetToAgent() {
    chips.value = chipsFromMeta(meta.value)
    includeAdvanced.value = !!(meta.value && meta.value.advanced && meta.value.advanced.present)
    page.value = 0
    sort.value = null
    // Back to the agent view = out of any drill. The drill snapshot is NOT
    // restored — the reset target IS the agent scope, not the pre-drill view.
    drill.value = null
    refreshRows()
  }

  // --- drill-down (trust layer v2) ---------------------------------------------
  // Pivot the table to the SOURCE ROWS behind one captured-result row. Only
  // reachable when the server vouched for it (drilldown.available) AND the
  // exact agent result was captured: the labels are built from the CAPTURED
  // row, never from the live table, so the drill proves what the agent used.
  // The pre-drill view (chips/advanced/sort/page) is snapshotted for exitDrill.
  function drillIntoResultRow(rowIndex) {
    const m = meta.value
    if (!m || !m.result || !m.result.captured) return
    if (!m.drilldown || !m.drilldown.available) return
    const cols = m.drilldown.columns
    if (!Array.isArray(cols) || !cols.length) return
    const row = Array.isArray(m.result.rows) ? m.result.rows[rowIndex] : null
    if (!Array.isArray(row)) return
    // Capped at 8 labels (backend mirror); null = unmappable column/value —
    // abort silently rather than drill on a partial (lying) scope.
    const labels = buildDrillLabels(cols, m.result.columns, row)
    if (!labels) return
    // Consecutive drill (chevron clicked while already drilling): keep the
    // ORIGINAL pre-drill snapshot — only the labels change. Re-snapshotting
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
          savedPage: page.value,
        }
    page.value = 0
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
    page.value = d.savedPage
    drill.value = null
    refreshRows()
  }

  // --- table interactions ------------------------------------------------------
  function setSort(column) {
    sort.value =
      sort.value && sort.value.column === column
        ? { column, dir: sort.value.dir === 'asc' ? 'desc' : 'asc' }
        : { column, dir: 'asc' }
    page.value = 0
    refreshRows()
  }
  // Rollback ONLY on a genuine failure of the latest request (ok === false):
  // a superseded request (null) means another action owns `page` now, so a
  // rollback would fight it (e.g. prevPage from page 1 racing a filter reset).
  async function nextPage() {
    if (!hasMore.value || rowsLoading.value) return
    if (page.value >= MAX_PAGE) return // mirrors backend MAX_EVIDENCE_PAGE
    const previous = page.value
    page.value += 1
    const ok = await refreshRows()
    if (ok === false) page.value = previous
  }
  async function prevPage() {
    if (page.value === 0 || rowsLoading.value) return
    const previous = page.value
    page.value -= 1
    const ok = await refreshRows()
    if (ok === false) page.value = previous
  }

  // Distinct values for the picker — returned to the caller (the popover owns
  // its own transient open/loading state), never stored here. NOT staleness-
  // guarded: the popover must drop a result that resolves after the panel
  // moved on (it closes on outside-click anyway). `excludeId` = server id of
  // the chip being edited (its predicate must not scope its own picker).
  function loadDistinct(column, excludeId) {
    if (!exchangeId.value) return Promise.reject(new Error('evidence_unavailable'))
    return fetchEvidenceDistinct(exchangeId.value, column, excludeId)
  }

  return {
    open, exchangeId, meta, chips, includeAdvanced, rows, page, hasMore, sort, drill,
    loading, rowsLoading, error, rowsError, available, modified,
    openForExchange, close, refreshRows,
    removeChip, setChipValues, addFilter, removeAdvanced, resetToAgent,
    drillIntoResultRow, exitDrill,
    setSort, nextPage, prevPage, loadDistinct,
  }
})
