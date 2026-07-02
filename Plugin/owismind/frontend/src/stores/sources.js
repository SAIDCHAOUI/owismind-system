// Source Data Explorer store - a user-facing browser over the datasets an admin has
// wired to an agent (the agent's `sources` list from /agents). It powers the standalone
// right-panel shown pre-conversation (`open`, from the empty-screen CTA). Patterned on
// evidence.js: every request is guarded by sequence numbers so a stale response can never
// overwrite a newer one (`seq` for source/meta transitions, `rowsSeq` for out-of-order
// rows). The per-exchange Evidence panel is exchange-scoped and does NOT use this store.
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
} from '../services/backend.js'
import {
  buildSourceRowsPayload,
  makeSourceChip,
  normalizeSourceOp,
  effectiveSourceQuery,
} from '../composables/sourceModel.js'

// Limit/offset pagination (v2): the first load pulls a big window, then each
// "load more" appends a small one. INITIAL_LIMIT + n x MORE_LIMIT never exceeds
// MAX_ROWS (100 + 20 x 20 = 500), so the offset never passes the backend's cap.
const INITIAL_LIMIT = 100
const MORE_LIMIT = 20
// Client-side cap on the ACCUMULATED (lazily appended) rows: infinite scroll
// appends window after window, so a huge dataset must never grow the in-memory
// array without bound. Past MAX_ROWS the sentinel stops (the user filters to narrow).
const MAX_ROWS = 500

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

  let seq = 0 // stale-response guard for source/meta transitions
  let rowsSeq = 0 // per-rows-request guard: last REQUEST wins, not last response
  let userChipSeq = 0 // keys for user-added chips
  // The source id whose meta is currently loaded/loading; gates ensureAgent so a
  // re-activation of an already-loaded source does NOT refetch.
  let loadedSourceId = null

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
  }

  // Ensure the store is populated for `key`, fetching the active source's meta+rows
  // LAZILY (only the first time that source is seen). Idempotent: re-calling it for an
  // already-loaded source is a no-op. Called when a surface becomes visible.
  function ensureAgent(key) {
    if (!key) return
    if (key !== agentKey.value) {
      // A different agent: drop everything and adopt its source list.
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
    ensureAgent(key)
  }
  function closePanel() {
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
      }
      offset.value = echoed
      hasMore.value = !!data.has_more && rows.value.length < MAX_ROWS
      return true
    } catch (e) {
      if (mySeq !== seq || myRows !== rowsSeq) return null
      rowsError.value = (e && e.message) || 'source_unavailable'
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
    offset.value = 0
    refreshRows()
  }

  // --- user filters (add / edit / remove / clear) ------------------------------
  function addFilter(column, values) {
    if (!column || !values || !values.length) return
    userChipSeq += 1
    chips.value.push(makeSourceChip(column, values, userChipSeq))
    offset.value = 0
    refreshRows()
  }
  function setChipValues(key, values) {
    const chip = chips.value.find((c) => c.key === key)
    if (!chip || !values.length) return
    chip.values = values.slice()
    chip.op = normalizeSourceOp(values)
    offset.value = 0
    refreshRows()
  }
  function removeChip(key) {
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
  function setSort(column) {
    sort.value =
      sort.value && sort.value.column === column
        ? { column, dir: sort.value.dir === 'asc' ? 'desc' : 'asc' }
        : { column, dir: 'asc' }
    offset.value = 0
    refreshRows()
  }

  // Distinct values for the add/edit picker - returned to the caller (the popover owns
  // its own transient open/loading state), never stored here. `q` (optional) narrows
  // the window server-side over ALL values; empty/absent keeps the default top-N.
  function loadDistinct(column, q) {
    if (activeSourceId.value == null || !agentKey.value) {
      return Promise.reject(new Error('source_unavailable'))
    }
    return fetchSourceDistinct(agentKey.value, activeSourceId.value, column, q)
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
    activeSourceLabel,
    ensureAgent, openPanel, closePanel, setSource, reload, setQuery,
    addFilter, setChipValues, removeChip, clearFilters, setSort,
    refreshRows, loadMoreRows, loadDistinct,
  }
})
