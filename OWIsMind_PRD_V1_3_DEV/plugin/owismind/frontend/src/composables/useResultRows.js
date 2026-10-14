// useResultRows - the rows an agent-result table shows, with the FULL result paged in
// when the agent's captured excerpt may hide rows (composables/resultRows.js decides).
//
// `source` is a getter returning { exchangeId, sqlId, result } (result = meta.result
// shape). When the capture is complete, the table shows it as-is and NO request fires
// (instance safety: most answers are small). Otherwise the first window of the full
// result is fetched once per (exchange, sql id), then `loadMore()` appends windows on
// scroll. Any failure falls back to the captured excerpt, flagged `partial` so the count
// line says honestly that rows are missing. Stale responses are dropped by a sequence.
import { computed, ref, watch } from 'vue'
import { fetchEvidenceResultRows } from '../services/backend.js'
import {
  needsFullResult,
  nextResultWindow,
  RESULT_INITIAL_LIMIT,
} from './resultRows.js'

export function useResultRows(source) {
  const liveRows = ref([])
  const liveColumns = ref([])
  const total = ref(null) // exact total of the full result (null = unknown)
  const live = ref(false) // true once a full-result window is on screen
  const hasMore = ref(false)
  const loading = ref(false)
  const failed = ref(false) // the full result was needed but could not be read
  let seq = 0

  const result = computed(() => {
    const s = source() || {}
    return s.result || null
  })
  const capturedRows = computed(() =>
    result.value && Array.isArray(result.value.rows)
      ? result.value.rows.filter((r) => Array.isArray(r))
      : [],
  )
  const capturedColumns = computed(() =>
    result.value && Array.isArray(result.value.columns) ? result.value.columns.map(String) : [],
  )

  const rows = computed(() => (live.value ? liveRows.value : capturedRows.value))
  const columns = computed(() => (live.value ? liveColumns.value : capturedColumns.value))
  // The capture is (possibly) an excerpt and the full result is not on screen.
  const partial = computed(() => !live.value && needsFullResult(result.value))

  function reset() {
    seq++
    liveRows.value = []
    liveColumns.value = []
    total.value = null
    live.value = false
    hasMore.value = false
    loading.value = false
    failed.value = false
  }

  function request(offset, limit) {
    const s = source() || {}
    if (!s.exchangeId) return Promise.resolve(null)
    const my = ++seq
    loading.value = true
    return fetchEvidenceResultRows({
      exchange_id: s.exchangeId,
      sql_id: s.sqlId || undefined,
      limit,
      offset,
    })
      .then((data) => {
        if (my !== seq) return
        const page = Array.isArray(data && data.rows) ? data.rows : []
        if (offset === 0) {
          liveColumns.value = Array.isArray(data.columns) ? data.columns.map(String) : []
          liveRows.value = page
          total.value = typeof data.total === 'number' ? data.total : null
          live.value = true
        } else {
          liveRows.value = liveRows.value.concat(page)
        }
        hasMore.value = !!data.has_more
      })
      .catch(() => {
        if (my !== seq) return
        // First window failed: keep the captured excerpt (flagged partial). A failed
        // append keeps what is loaded and simply stops paging.
        if (offset === 0) failed.value = true
        hasMore.value = false
      })
      .finally(() => {
        if (my === seq) loading.value = false
      })
  }

  function loadMore() {
    if (!live.value || loading.value) return
    const w = nextResultWindow(liveRows.value.length, hasMore.value)
    if (w) request(w.offset, w.limit)
  }

  // One full-result read per (exchange, sql id, capture): re-keyed when the shown
  // result changes (exchange switch, other artifact), never on unrelated re-renders.
  watch(
    () => {
      const s = source() || {}
      return [s.exchangeId || null, s.sqlId || null, result.value]
    },
    ([exchangeId, , res]) => {
      reset()
      if (exchangeId && needsFullResult(res)) request(0, RESULT_INITIAL_LIMIT)
    },
    { immediate: true },
  )

  return { rows, columns, total, live, hasMore, loading, failed, partial, loadMore }
}
