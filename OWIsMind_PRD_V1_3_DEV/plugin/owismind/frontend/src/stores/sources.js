// Source Data Explorer store - a user-facing browser over the datasets an admin has
// wired to an agent (the agent's `sources` list from /agents). It powers the standalone
// right-panel shown pre-conversation (`open`, from the empty-screen CTA). Patterned on
// evidence.js: every request is guarded by sequence numbers so a stale response can never
// overwrite a newer one (`seq` for source/meta transitions, `rowsSeq` for out-of-order
// rows). The per-exchange Evidence panel is exchange-scoped and does NOT use this store.
//
// The DB-computed aggregate surface (row count + Calculate zone + Analyze mini-pivot)
// lives in the SHARED composables/aggregateSurface.js factory, so the Evidence "Source
// data" tab offers the exact same tools from one code base. This store wires the factory
// to its own columns / epoch / backend and re-exposes its state under the same names.
//
// SAFETY: NO query fires on store creation or on a hidden mount. The first fetch only
// happens when a surface becomes visible and calls ensureAgent()/openPanel().
import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { useSessionStore } from './session.js'
import {
  fetchSourceMeta,
  fetchSourceRows,
  fetchSourceDistinct,
  fetchSourceAggregate,
} from '../services/backend.js'
import {
  buildSourceRowsPayload,
  buildSourceAggregatePayload,
  makeSourceChip,
  normalizeSourceOp,
  chipOp,
  chipsToFilters,
  effectiveSourceQuery,
  nextSortDir,
} from '../composables/sourceModel.js'
import { createAggregateSurface } from '../composables/aggregateSurface.js'
import {
  createViewMemory,
  sanitizeRestoredChips,
  sanitizeRestoredSort,
  sanitizeRestoredCalc,
} from '../composables/sourceViewMemory.js'
import { track } from '../services/track.js'

// Limit/offset pagination (v2): the first load pulls a big window, then each
// "load more" appends a small one. INITIAL_LIMIT + n x MORE_LIMIT never exceeds
// MAX_ROWS (100 + 20 x 20 = 500), so the offset never passes the backend's cap.
const INITIAL_LIMIT = 100
const MORE_LIMIT = 20
// Client-side cap on the ACCUMULATED (lazily appended) rows: infinite scroll
// appends window after window, so a huge dataset must never grow the in-memory
// array without bound. Past MAX_ROWS the sentinel stops (the user filters to narrow).
const MAX_ROWS = 500

// Per-(agent, dataset) view memory, one per app session (the store is a singleton). It
// remembers a user's filters / search / sort / Calculate selection so they survive a panel
// close/reopen and agent switches back and forth. Session-only (no localStorage).
const viewMemory = createViewMemory()

export const useSourcesStore = defineStore('sources', () => {
  const session = useSessionStore()

  const open = ref(false) // standalone panel visibility (pre-conversation)
  const agentKey = ref('') // logical key of the agent whose sources we browse
  const sourceList = ref([]) // [{ id, label, dataset }] from the session agent (no fetch)
  const activeSourceId = ref(null) // integer id of the dataset currently browsed
  const columns = ref([]) // [{ name, type }] of the active source
  const chips = ref([]) // user filters only (sourceModel chip shape)
  const q = ref('') // raw search text (payload uses the effective, trimmed form)
  const rows = ref([]) // lazily accumulated rows (bounded by MAX_ROWS)
  const offset = ref(0) // running count of already-loaded rows (= next window start)
  const hasMore = ref(false)
  const sort = ref(null) // { column, dir: 'asc' | 'desc' } | null
  const loading = ref(false) // meta fetch (blanks the whole body)
  const rowsLoading = ref(false)
  const error = ref('') // META-level error code ('' = none)
  const rowsError = ref('') // ROWS-level error code ('' = none): filters stay usable
  // A pulse from a header column menu asking the chips component to open the value picker
  // pre-set to a column: { column, n } (n bumped each call so the same column re-fires).
  const columnFilterRequest = ref(null)

  let seq = 0 // stale-response guard for source/meta transitions
  let rowsSeq = 0 // per-rows-request guard: last REQUEST wins, not last response
  let userChipSeq = 0 // keys for user-added chips
  let columnFilterSeq = 0 // monotonic counter behind columnFilterRequest.n
  // The source id whose meta is currently loaded/loading; gates ensureAgent so a
  // re-activation of an already-loaded source does NOT refetch.
  let loadedSourceId = null

  // A stable signature of the aggregation SCOPE (source + search + filters). Sort is
  // deliberately excluded: re-sorting the visible window does not change any total.
  // JSON encoding keeps the boundaries unambiguous whatever a column name / value holds.
  function _viewSignature() {
    const chipSig = (chips.value || []).map((c) => [c.column, chipOp(c), c.values])
    return JSON.stringify([activeSourceId.value, effectiveSourceQuery(q.value), chipSig])
  }

  // The shared aggregate surface. Every number is computed by the DATABASE over the FULL
  // filtered set (not the visible window): the row count, the Calculate zone (persistent,
  // follows the filters) and the Analyze mini-pivot. The store bumps `seq` on every meta
  // transition, so in-flight aggregate requests are dropped by the epoch guard.
  const surface = createAggregateSurface({
    getColumns: () => columns.value,
    isActive: () => activeSourceId.value != null,
    getEpoch: () => seq,
    fetchAggregate: (group, measures, limit) =>
      fetchSourceAggregate(
        buildSourceAggregatePayload(
          agentKey.value, activeSourceId.value, q.value, chips.value, group, measures, limit,
        ),
      ),
    refreshRows: () => refreshRows(),
    errorCode: 'source_unavailable',
  })

  // Read the agent's configured sources from the session store (never a fetch).
  function _agentSources(key) {
    const a = session.agents.find((x) => x.key === key)
    const list = a && Array.isArray(a.sources) ? a.sources : []
    return list.map((s) => ({ id: s.id, label: s.label || '#' + s.id, dataset: s.dataset || '' }))
  }

  function _resetAll() {
    agentKey.value = ''
    sourceList.value = []
    activeSourceId.value = null
    columns.value = []
    chips.value = []
    q.value = ''
    rows.value = []
    offset.value = 0
    hasMore.value = false
    sort.value = null
    error.value = ''
    rowsError.value = ''
    loading.value = false
    rowsLoading.value = false
    loadedSourceId = null
    surface.resetDerived()
  }

  // Reset only the per-source view (chips/search/rows/sort): used when switching to
  // another dataset of the same agent, before its meta loads.
  function _resetView() {
    columns.value = []
    chips.value = []
    q.value = ''
    rows.value = []
    offset.value = 0
    hasMore.value = false
    sort.value = null
    rowsError.value = ''
    surface.resetDerived()
  }

  // Snapshot the LIVE working view (filters / search / sort / Calculate selection) as a
  // plain, deep-copied shape. The Calculate part reads the shared surface refs. Sort is
  // deliberately included (the user's chosen ordering is part of "their view").
  function _snapshotView() {
    return {
      chips: chips.value.map((c) => ({
        key: c.key, column: c.column, op: c.op, values: (c.values || []).slice(),
      })),
      q: q.value,
      sort: sort.value ? { column: sort.value.column, dir: sort.value.dir } : null,
      calcColumn: surface.calcColumn.value,
      calcFns: (surface.calcFns.value || []).slice(),
    }
  }

  // Persist (or forget) the CURRENT (agent, dataset) view before a view-destroying
  // transition. Called with the live agentKey / activeSourceId still in place. Saves only a
  // NON-trivial view (do not fill the memory with empty views); when the live view is
  // trivial it DELETES any stored entry so clearing filters then leaving cannot resurrect
  // stale chips on return.
  function _persistCurrentView() {
    const key = agentKey.value
    const sourceId = activeSourceId.value
    if (!key || sourceId == null) return
    const trivial = !(chips.value.length || q.value || sort.value || surface.calcColumn.value)
    if (trivial) viewMemory.remove(key, sourceId)
    else viewMemory.save(key, sourceId, _snapshotView())
  }

  // Ensure the store is populated for `key`, fetching the active source's meta+rows
  // LAZILY (only the first time that source is seen). Idempotent: re-calling it for an
  // already-loaded source is a no-op. Called when a surface becomes visible.
  function ensureAgent(key) {
    if (!key) return
    if (key !== agentKey.value) {
      // A different agent: remember the outgoing agent's live view, then drop everything
      // and adopt the new agent's source list.
      _persistCurrentView()
      seq += 1 // invalidate any in-flight request from the previous agent
      _resetAll()
      agentKey.value = key
      sourceList.value = _agentSources(key)
      activeSourceId.value = sourceList.value.length ? sourceList.value[0].id : null
    } else if (!sourceList.value.length) {
      // Same agent but the list was empty (agents loaded after the first call).
      sourceList.value = _agentSources(key)
      if (activeSourceId.value == null && sourceList.value.length) {
        activeSourceId.value = sourceList.value[0].id
      }
    }
    if (activeSourceId.value != null && loadedSourceId !== activeSourceId.value) {
      _loadMeta(activeSourceId.value)
    }
  }

  // Standalone panel open/close (the pre-conversation surface).
  function openPanel(key) {
    open.value = true
    track('source_explorer_opened', {}, { agent_key: key || null })
    ensureAgent(key)
  }
  function closePanel() {
    _persistCurrentView() // remember the view so reopening restores it
    seq += 1 // invalidate any in-flight request
    open.value = false
    _resetAll()
  }

  // Load one source's descriptor (columns), then its first page. Resets the per-source
  // view first so the previous dataset's filters/rows never bleed into the new one.
  async function _loadMeta(sourceId) {
    const mySeq = ++seq
    loadedSourceId = sourceId
    _resetView()
    loading.value = true
    error.value = ''
    try {
      const data = await fetchSourceMeta(agentKey.value, sourceId)
      if (mySeq !== seq) return
      columns.value = Array.isArray(data.columns) ? data.columns : []
      // Adopt the server-authored label for the active source if it refined ours.
      if (data.label) {
        const entry = sourceList.value.find((s) => s.id === sourceId)
        if (entry) entry.label = data.label
      }
      // Restore any remembered view for THIS (agent, dataset) within the session, sanitized
      // against the freshly loaded columns (a column may have changed since it was saved).
      // Direct ref assignment (never setCalcColumn/setChipValues/setSort): the subsequent
      // _loadRows -> surface.afterScopeChange(sig) fires EXACTLY ONE calc reload + one count
      // when calcColumn is set, so a wrapper call here would only duplicate requests.
      const saved = viewMemory.restore(agentKey.value, sourceId)
      if (saved) {
        // Re-key restored chips against the LIVE counter so they can never collide with a
        // chip the user adds next (userChipSeq keeps climbing across sessions of the view).
        chips.value = sanitizeRestoredChips(saved.chips, columns.value).map((c) => {
          userChipSeq += 1
          return { key: 'u' + userChipSeq, column: c.column, op: c.op, values: c.values }
        })
        q.value = saved.q || ''
        sort.value = sanitizeRestoredSort(saved.sort, columns.value)
        const cc = sanitizeRestoredCalc(saved.calcColumn, saved.calcFns, columns.value)
        surface.calcColumn.value = cc.column
        surface.calcFns.value = cc.column ? cc.fns : []
      }
      await _loadRows(mySeq)
    } catch (e) {
      if (mySeq !== seq) return
      error.value = (e && e.message) || 'source_unavailable'
    } finally {
      if (mySeq === seq) loading.value = false
    }
  }

  // Load ONE window of rows. `append` selects the mode: false = fresh first window
  // at offset 0 (replaces the accumulated rows), true = next window appended at
  // offset = rows.length (infinite scroll). Tri-state result: true = latest request
  // succeeded, false = it failed, null = superseded.
  async function _loadRows(mySeq, opts) {
    const append = !!(opts && opts.append)
    const targetOffset = append ? rows.value.length : 0
    const targetLimit = append ? MORE_LIMIT : INITIAL_LIMIT
    const myRows = ++rowsSeq
    rowsLoading.value = true
    try {
      const payload = buildSourceRowsPayload(
        agentKey.value, activeSourceId.value, q.value, chips.value, targetLimit, targetOffset, sort.value,
      )
      const data = await fetchSourceRows(payload)
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
        surface.clearRowsStale() // the table window now matches the current scope
        // A FRESH window whose SCOPE changed (new source / search / filters, never a
        // sort or an append): re-fire the DB row count, re-compute the Calculate zone,
        // and re-run Analyze if it is open with a complete selection.
        surface.afterScopeChange(_viewSignature())
      }
      offset.value = echoed
      hasMore.value = !!data.has_more && rows.value.length < MAX_ROWS
      return true
    } catch (e) {
      if (mySeq !== seq || myRows !== rowsSeq) return null
      rowsError.value = (e && e.message) || 'source_unavailable'
      // A FAILED fresh load must still refresh the aggregates: the filters DID change,
      // and keeping the previous scope's DB-exact count / figures on screen would show an
      // authoritative number that no longer matches the active filter set. The count query
      // is independent of the rows query; if it fails too, the count goes honest-null
      // rather than stale.
      if (!append) surface.afterScopeChange(_viewSignature())
      return false
    } finally {
      if (mySeq === seq && myRows === rowsSeq) rowsLoading.value = false
    }
  }

  // Fresh reload (page 0): used by every search / filter / sort change. No-op when no
  // source is active (an agent with zero sources): a rows request with source:null is
  // rejected by the backend (invalid_source -> 400), so never issue one.
  function refreshRows() {
    if (activeSourceId.value == null) return Promise.resolve(null)
    rowsError.value = ''
    if (surface.analyzeOpen.value) {
      // The Data table is hidden behind the Analyze view: skip the (unused) 100-row
      // window and refresh only the DB-computed aggregates (count + pivot). The table
      // is marked stale and re-fetched lazily when the user returns to the Data view.
      surface.markRowsStale()
      surface.afterScopeChange(_viewSignature())
      return Promise.resolve(true)
    }
    return _loadRows(seq)
  }

  // Infinite-scroll: append the next window when the sentinel scrolls into view.
  // Bounded by hasMore (server) and MAX_ROWS (client).
  function loadMoreRows() {
    if (activeSourceId.value == null) return Promise.resolve(null)
    if (!hasMore.value || rowsLoading.value) return Promise.resolve(null)
    if (rows.value.length >= MAX_ROWS) return Promise.resolve(null)
    return _loadRows(seq, { append: true })
  }

  // Switch to another dataset of the same agent. No-op for the current one or an
  // unknown id. Resets the view and re-queries page 0 of the new dataset.
  function setSource(id) {
    if (id == null || id === activeSourceId.value) return
    if (!sourceList.value.some((s) => s.id === id)) return
    _persistCurrentView() // remember the outgoing dataset's view before switching
    track('source_dataset_switched', { source: id }, { agent_key: agentKey.value || null })
    activeSourceId.value = id
    _loadMeta(id)
  }

  // Re-run the active source's meta+rows fetch (the retry after a meta-level error;
  // setSource would no-op on the same id).
  function reload() {
    if (activeSourceId.value != null) _loadMeta(activeSourceId.value)
  }

  // Search: caller debounces. Stores the raw text but skips a pointless refetch when
  // the EFFECTIVE term is unchanged (e.g. a 1st char still below the 2-char threshold).
  // No-op with no active source (zero-source agent): there is nothing to search and a
  // source:null rows request would be rejected by the backend.
  function setQuery(value) {
    if (activeSourceId.value == null) return
    const next = value == null ? '' : String(value)
    if (next === q.value) return
    const before = effectiveSourceQuery(q.value)
    q.value = next
    if (effectiveSourceQuery(next) === before) return
    // Record only the length (never the search text itself - it can carry PII).
    track('source_searched', { len: next.length }, { agent_key: agentKey.value || null })
    offset.value = 0
    refreshRows()
  }

  // --- user filters (add / edit / remove / clear) ------------------------------
  // `op` is optional: pass 'BETWEEN' (with exactly 2 boundary values) for a temporal
  // range chip whose op is preserved; otherwise the op is derived from the value count.
  function addFilter(column, values, op) {
    if (!column || !values || !values.length) return
    track('source_filter_added', { column }, { agent_key: agentKey.value || null })
    userChipSeq += 1
    chips.value.push(makeSourceChip(column, values, userChipSeq, op))
    offset.value = 0
    refreshRows()
  }
  function setChipValues(key, values, op) {
    const chip = chips.value.find((c) => c.key === key)
    if (!chip || !values.length) return
    chip.values = values.slice()
    chip.op = op === 'BETWEEN' && values.length === 2 ? 'BETWEEN' : normalizeSourceOp(values)
    offset.value = 0
    refreshRows()
  }
  function removeChip(key) {
    const chip = chips.value.find((c) => c.key === key)
    track('source_filter_removed', { column: chip ? chip.column : null }, { agent_key: agentKey.value || null })
    chips.value = chips.value.filter((c) => c.key !== key)
    offset.value = 0
    refreshRows()
  }
  function clearFilters() {
    if (!chips.value.length) return
    chips.value = []
    offset.value = 0
    refreshRows()
  }

  // --- table interactions ------------------------------------------------------
  // 3-state sort. `dir` explicit ('asc' | 'desc' | null) sets that direction outright
  // (null clears the sort); omitted, it CYCLES this column through nextSortDir (a header
  // NAME click: none -> asc -> desc -> none). Sorting a DIFFERENT column starts at 'asc'.
  function setSort(column, dir) {
    const current = sort.value && sort.value.column === column ? sort.value.dir : null
    const nextDir = dir === undefined ? nextSortDir(current) : dir
    sort.value = nextDir ? { column, dir: nextDir } : null
    offset.value = 0
    refreshRows()
  }

  // A header column menu asked to open the value picker pre-set to `column`. The chips
  // component watches this ref; `n` is bumped every call so re-requesting the SAME column
  // still re-fires the watcher (the popover reopens on the same column).
  function requestColumnFilter(column) {
    if (!column) return
    columnFilterSeq += 1
    columnFilterRequest.value = { column, n: columnFilterSeq }
  }

  // Distinct values for the add/edit picker - returned to the caller (the popover owns
  // its own transient open/loading state), never stored here. The picker is CASCADING:
  // it only offers values compatible with the OTHER active filters + the table-level
  // search, so it carries that scope. `search` (optional) is the picker's own search on
  // THAT column; empty/absent keeps the default top-N. `excludeChipKey` (optional) is the
  // key of the chip being EDITED: it is dropped from the scope so it never self-scopes its
  // own picker (omit it for the ADD flow, where every chip applies). The table-level
  // search (the store's `q`) travels as scope_q over ALL columns.
  function loadDistinct(column, search, excludeChipKey) {
    if (activeSourceId.value == null || !agentKey.value) {
      return Promise.reject(new Error('source_unavailable'))
    }
    const scopeChips = excludeChipKey == null
      ? chips.value
      : chips.value.filter((c) => c.key !== excludeChipKey)
    const filters = chipsToFilters(scopeChips)
    const scopeQ = effectiveSourceQuery(q.value)
    return fetchSourceDistinct(agentKey.value, activeSourceId.value, column, search, filters, scopeQ)
  }

  // Label of the source currently browsed - what a cell selection reports as its
  // provenance to the prompt context ('' when nothing is active).
  const activeSourceLabel = computed(() => {
    const entry = sourceList.value.find((s) => s.id === activeSourceId.value)
    return entry ? entry.label : ''
  })

  return {
    open, agentKey, sourceList, activeSourceId, columns, chips, q,
    rows, offset, hasMore, sort, loading, rowsLoading, error, rowsError,
    columnFilterRequest, requestColumnFilter,
    activeSourceLabel,
    // DB-computed row count + the Calculate zone (shared aggregate surface)
    totalCount: surface.totalCount,
    totalLoading: surface.totalLoading,
    calcColumn: surface.calcColumn,
    calcFns: surface.calcFns,
    calcValues: surface.calcValues,
    calcLoading: surface.calcLoading,
    calcError: surface.calcError,
    setCalcColumn: surface.setCalcColumn,
    setCalcFns: surface.setCalcFns,
    reloadCalc: surface.reloadCalc,
    // Analyze (mini-pivot)
    analyzeOpen: surface.analyzeOpen,
    analyzeGroup: surface.analyzeGroup,
    analyzeBucket: surface.analyzeBucket,
    analyzeFn: surface.analyzeFn,
    analyzeMeasureColumn: surface.analyzeMeasureColumn,
    analyzeRows: surface.analyzeRows,
    analyzeTotals: surface.analyzeTotals,
    analyzeTruncated: surface.analyzeTruncated,
    analyzeLoading: surface.analyzeLoading,
    analyzeError: surface.analyzeError,
    setAnalyzeOpen: surface.setAnalyzeOpen,
    setAnalyzeGroup: surface.setAnalyzeGroup,
    setAnalyzeBucket: surface.setAnalyzeBucket,
    setAnalyzeMeasure: surface.setAnalyzeMeasure,
    runAnalyze: surface.runAnalyze,
    ensureAgent, openPanel, closePanel, setSource, reload, setQuery,
    addFilter, setChipValues, removeChip, clearFilters, setSort,
    refreshRows, loadMoreRows, loadDistinct,
  }
})
