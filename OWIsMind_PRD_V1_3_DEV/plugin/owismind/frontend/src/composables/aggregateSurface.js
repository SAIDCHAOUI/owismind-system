// Shared aggregate-surface state machine for the Source Data explorer AND the Evidence
// "Source data" tab. Both hosts expose the SAME DB-computed tools over their current
// filtered scope: a live row COUNT (the bottom bar), a persistent "Calculate" zone
// (pick one column, see its key figures chosen by column TYPE), and an "Analyze"
// one-group-by + one-measure mini-pivot. This factory owns ALL that state plus its
// request sequencing; each host injects how to read its columns, whether an aggregate
// is meaningful right now, its meta epoch (stale-response guard) and how to run ONE
// aggregate request (the host builds its own payload + calls its own backend fn).
//
// Extracted VERBATIM from stores/sources.js so that store, re-expressed on this factory,
// behaves byte-identically. Kept Vue-reactive (ref) but Pinia-free, so it is testable
// under node:test with injected fake deps (F11).
//
// deps:
//   getColumns():  [{ name, type }]  - the active columns (type drives the measures)
//   isActive():    bool              - whether an aggregate is meaningful right now
//   getEpoch():    number            - the host's meta seq (stale-response epoch guard)
//   fetchAggregate(group, measures, limit): Promise - the host builds the payload and
//                  calls its backend; resolves { rows, totals?, truncated? }
//   refreshRows(): void|Promise      - re-fetch the host's Data-table window (used when
//                  leaving Analyze after a scope change had skipped it)
//   errorCode:     string            - the host's default error code (e.g. 'source_unavailable')
import { ref } from 'vue'
import {
  statsSpecFor,
  isTemporalColType,
  defaultCalcFnsFor,
  addMeasure,
  removeMeasureAt,
  replaceMeasureAt,
  defaultWorkspaceMeasures,
  measureKey,
  MAX_WORKSPACE_MEASURES,
} from './sourceModel.js'
import { isIdentifierColumn } from './cellFormat.js'

export function createAggregateSurface(deps) {
  // --- DB-computed row count + the "Calculate" zone (persistent) -----------------
  const totalCount = ref(null) // number | null (DB row count over the filter)
  const totalLoading = ref(false)
  const calcColumn = ref(null) // string | null (the column being summarized)
  // The ORDERED subset of measures the user chose to display (always a non-empty subset
  // of statsSpecFor(calcColumn's type), kept in spec order). The user picks which figures
  // to see so a column never shows all five numeric measures at once, and _reloadCalc
  // only ever requests these.
  const calcFns = ref([]) // string[] (selected fn keys, spec order)
  const calcValues = ref(null) // { <fn>: value|null } | null (mapped m0..mN by position)
  const calcLoading = ref(false)
  const calcError = ref('') // '' = none

  // --- Analyze (one-group-by + one-measure mini-pivot) --------------------------
  const analyzeOpen = ref(false) // Data view vs Analyze view (chips stay in both)
  const analyzeGroup = ref(null) // group-by column name | null
  const analyzeBucket = ref('month') // temporal bucket ('month'|'quarter'|'year')
  const analyzeFn = ref('count') // measure function ('count'|'sum'|'avg')
  const analyzeMeasureColumn = ref(null) // measured numeric column | null (count = none)
  const analyzeRows = ref([]) // [{ key, m0 }] ordered by the backend
  const analyzeTotals = ref(null) // { m0 } over the same filter | null (for shares)
  const analyzeTruncated = ref(false) // true when the 50-group cap bit
  const analyzeLoading = ref(false)
  const analyzeError = ref('') // '' = none

  // --- Unified Analyze workspace (the standalone Source explorer) ---------------
  // ONE model instead of two: a list of MEASURES (1..8) over an OPTIONAL grouping.
  //   no group -> a single totals row, rendered as KPI cards
  //   group    -> up to 50 group rows ranked by the FIRST measure (or the 50 most recent
  //               calendar buckets), rendered as a bar table with one column per measure.
  // ADDITIVE: the calc* / analyze* state above is untouched and still drives the Evidence
  // hosts. This state stays inert until a host declares itself active, so a host that does
  // not display the workspace never issues a request for it.
  const workspaceActive = ref(false)
  // There is ALWAYS at least one measure, so the workspace can never show an empty result
  // waiting for the user to configure something. The list starts on the row count only
  // because the columns are not known yet; as soon as they are, an UNTOUCHED list is
  // re-defaulted to the sum of the first numeric quantity column (see _applyDefaultMeasures).
  const workspaceMeasures = ref([{ fn: 'count', column: null }])
  // True while the measure list is still the automatic default: the moment the user adds,
  // removes or swaps a measure it turns false and the defaulting never fires again for
  // this scope (their choice must survive every refresh). A scope reset arms it back.
  let measuresPristine = true
  const workspaceGroup = ref(null) // group-by column name | null (= all filtered rows)
  const workspaceBucket = ref('month') // calendar bucket for a temporal group
  const workspaceRows = ref([]) // [{ key?, m0..mN }] as returned by the backend
  const workspaceTotals = ref(null) // { m0..mN } over the same filter | null (ungrouped)
  const workspaceTruncated = ref(false) // true when the 50-group cap bit
  const workspaceLoading = ref(false)
  const workspaceError = ref('') // '' = none

  let workspaceSeq = 0 // per-workspace-request guard
  let countSeq = 0 // per-count-request guard (the totals bar row count)
  let calcSeq = 0 // per-calculate-zone-request guard
  let analyzeSeq = 0 // per-analyze-request guard
  // Signature of the aggregation SCOPE at the last FRESH load (host-computed): a change
  // re-fires the count, re-computes Calculate, and re-runs Analyze if open + complete.
  let lastViewSig = null
  // True when filters/search changed while the Analyze view was open (the table window
  // is skipped there); the Data view re-fetches its rows lazily on return.
  let rowsStale = false

  // Type of one column of the active scope ('' when unknown).
  function _colType(name) {
    const c = (deps.getColumns() || []).find((x) => x.name === name)
    return c ? c.type : ''
  }
  function _err(e) {
    return (e && e.message) || deps.errorCode
  }

  // Reset the DB-computed row count + the Calculate zone + the Analyze view. Called on
  // every scope reset (source/table/exchange switch, panel close) so a stale count /
  // figures / pivot from the previous scope never lingers. In-flight aggregate requests
  // are dropped by their epoch guard (the host bumps its meta seq on every transition);
  // hosts whose epoch does NOT change on the reset call invalidate() as well.
  function resetDerived() {
    totalCount.value = null
    totalLoading.value = false
    calcColumn.value = null
    calcFns.value = []
    calcValues.value = null
    calcLoading.value = false
    calcError.value = ''
    analyzeOpen.value = false
    analyzeGroup.value = null
    analyzeBucket.value = 'month'
    analyzeFn.value = 'count'
    analyzeMeasureColumn.value = null
    analyzeRows.value = []
    analyzeTotals.value = null
    analyzeTruncated.value = false
    analyzeLoading.value = false
    analyzeError.value = ''
    // The workspace returns to its automatic default, re-armed for the NEW scope (the
    // columns of the dataset being switched to are not known yet, so the real default is
    // computed by _applyDefaultMeasures once they are). Its ACTIVE flag is host lifecycle,
    // not scope, so it survives the reset.
    workspaceMeasures.value = [{ fn: 'count', column: null }]
    measuresPristine = true
    workspaceGroup.value = null
    workspaceBucket.value = 'month'
    workspaceRows.value = []
    workspaceTotals.value = null
    workspaceTruncated.value = false
    workspaceLoading.value = false
    workspaceError.value = ''
    lastViewSig = null
    rowsStale = false
  }

  // Drop every in-flight aggregate response (count / calculate / analyze) without
  // touching the epoch. Hosts whose meta seq does NOT bump on a scope reset (e.g. the
  // Evidence table selector) call this so a late response from the previous scope can
  // never land. The Source explorer never needs it (its meta seq bumps on every switch).
  function invalidate() {
    countSeq += 1
    calcSeq += 1
    analyzeSeq += 1
    workspaceSeq += 1
  }

  // DB row count over the current search + filters (the totals bar). One COUNT(*) per
  // scope change (guarded by countSeq + the meta epoch). Best-effort: a failure clears
  // the count rather than showing a wrong one.
  async function refreshTotals() {
    if (!deps.isActive()) return
    const my = ++countSeq
    const epoch = deps.getEpoch()
    totalLoading.value = true
    try {
      const data = await deps.fetchAggregate(null, [{ fn: 'count', column: null }], 1)
      if (my !== countSeq || epoch !== deps.getEpoch()) return
      const first = (data.rows || [])[0] || {}
      totalCount.value = first.m0 == null ? null : Number(first.m0)
    } catch (e) {
      if (my !== countSeq || epoch !== deps.getEpoch()) return
      totalCount.value = null
    } finally {
      if (my === countSeq && epoch === deps.getEpoch()) totalLoading.value = false
    }
  }

  // Clear the Calculate zone (used on a scope reset and on toggle-off). Bumps calcSeq so
  // any in-flight figures response is dropped.
  function _clearCalc() {
    calcSeq += 1
    calcColumn.value = null
    calcFns.value = []
    calcValues.value = null
    calcError.value = ''
    calcLoading.value = false
  }

  // Sanitize a requested measure list against a column's offering: keep only fns that
  // statsSpecFor(type) actually lists, in SPEC order (never the caller's order), so the
  // KPI cards render in a stable, type-driven sequence. Returns [] when nothing survives
  // (callers treat an empty result as "keep the current selection").
  function _sanitizeCalcFns(column, fns) {
    const wanted = new Set(fns || [])
    return statsSpecFor(_colType(column)).map((s) => s.fn).filter((fn) => wanted.has(fn))
  }

  // Fetch the current calcColumn's key figures over the current filtered set. Only the
  // SELECTED measures (calcFns, a type-driven subset the user chose) are requested; the
  // single group-null aggregate is mapped back to { <fn>: value } by position (m0..mN)
  // over that selected list. Guarded by calcSeq + the meta epoch. Returns the request
  // promise so callers/tests can await it.
  function _reloadCalc() {
    const column = calcColumn.value
    const fns = calcFns.value
    if (!deps.isActive() || !column || !fns.length) return Promise.resolve()
    const measures = fns.map((fn) => ({ fn, column }))
    const my = ++calcSeq
    const epoch = deps.getEpoch()
    calcValues.value = null
    calcError.value = ''
    calcLoading.value = true
    return deps.fetchAggregate(null, measures, 1)
      .then((data) => {
        if (my !== calcSeq || epoch !== deps.getEpoch()) return
        const first = (data.rows || [])[0] || {}
        const values = {}
        fns.forEach((fn, i) => { values[fn] = first['m' + i] == null ? null : first['m' + i] })
        calcValues.value = values
      })
      .catch((e) => {
        if (my !== calcSeq || epoch !== deps.getEpoch()) return
        calcError.value = _err(e)
        calcValues.value = null
      })
      .finally(() => {
        if (my === calcSeq && epoch === deps.getEpoch()) calcLoading.value = false
      })
  }

  // Pick the column summarized by the Calculate zone. An empty pick or re-picking the
  // active column toggles the zone off; any other column fetches its figures over the
  // SAME filtered set. The row count is left untouched.
  function setCalcColumn(column) {
    if (!deps.isActive()) return
    if (!column || calcColumn.value === column) {
      _clearCalc()
      return
    }
    calcColumn.value = column
    // A NEW column starts on its type's default measure subset (not all figures at once).
    calcFns.value = defaultCalcFnsFor(_colType(column))
    _reloadCalc()
  }

  // Change which measures the Calculate zone displays for the current column. The list is
  // sanitized against the column's offering (spec order, unknown fns dropped); an empty
  // result is IGNORED so at least one measure always stays selected. A real change
  // re-fetches only the new subset.
  function setCalcFns(fns) {
    if (!calcColumn.value) return
    const next = _sanitizeCalcFns(calcColumn.value, fns)
    if (!next.length) return
    calcFns.value = next
    _reloadCalc()
  }

  // Retry the Calculate zone after a failed fetch (the error-state retry). No-op when no
  // column is chosen; re-picking would toggle the zone off instead of retrying.
  function reloadCalc() {
    if (calcColumn.value) _reloadCalc()
  }

  // --- Analyze (one-group-by + one-measure mini-pivot) --------------------------
  // The selection is complete once a group column is chosen AND the measure is valid
  // (count needs no column; sum/avg need a numeric column).
  function _analyzeComplete() {
    if (!deps.isActive() || !analyzeGroup.value) return false
    return analyzeFn.value === 'count' ? true : !!analyzeMeasureColumn.value
  }
  function _clearAnalyzeResult() {
    analyzeRows.value = []
    analyzeTotals.value = null
    analyzeTruncated.value = false
    analyzeError.value = ''
  }

  // Run the pivot: measures ([count] or [fn(column)]) + group {column, bucket} (bucket
  // only for a temporal column), limit 50 group rows. Guarded by analyzeSeq + the meta
  // epoch, so a superseded run can never overwrite a newer one.
  async function runAnalyze() {
    if (!_analyzeComplete()) return
    const my = ++analyzeSeq
    const epoch = deps.getEpoch()
    analyzeLoading.value = true
    analyzeError.value = ''
    try {
      const measures = analyzeFn.value === 'count'
        ? [{ fn: 'count', column: null }]
        : [{ fn: analyzeFn.value, column: analyzeMeasureColumn.value }]
      const temporal = isTemporalColType(_colType(analyzeGroup.value))
      const group = { column: analyzeGroup.value, bucket: temporal ? analyzeBucket.value : null }
      const data = await deps.fetchAggregate(group, measures, 50)
      if (my !== analyzeSeq || epoch !== deps.getEpoch()) return
      analyzeRows.value = Array.isArray(data.rows) ? data.rows : []
      analyzeTotals.value = data.totals || null
      analyzeTruncated.value = !!data.truncated
    } catch (e) {
      if (my !== analyzeSeq || epoch !== deps.getEpoch()) return
      analyzeError.value = _err(e)
      analyzeRows.value = []
      analyzeTotals.value = null
      analyzeTruncated.value = false
    } finally {
      if (my === analyzeSeq && epoch === deps.getEpoch()) analyzeLoading.value = false
    }
  }

  // Switch between the Data table and the Analyze view (chips stay shared in both).
  // Entering Analyze with a complete selection refreshes its result; leaving it after a
  // scope change (rowsStale) re-fetches the table window the change had skipped.
  function setAnalyzeOpen(value) {
    analyzeOpen.value = !!value
    if (analyzeOpen.value) {
      if (_analyzeComplete()) runAnalyze()
      // The unified workspace host (standalone explorer) always has a valid selection.
      if (workspaceActive.value) runWorkspace()
    } else if (rowsStale) {
      rowsStale = false
      deps.refreshRows()
    }
  }
  // Pick the group-by column. Default the bucket to 'month' for a temporal column so a
  // date group is immediately usable. Runs when complete, clears the result otherwise.
  function setAnalyzeGroup(column) {
    analyzeGroup.value = column || null
    if (analyzeGroup.value && isTemporalColType(_colType(analyzeGroup.value))) {
      analyzeBucket.value = 'month'
    }
    if (_analyzeComplete()) runAnalyze()
    else _clearAnalyzeResult()
  }
  function setAnalyzeBucket(bucket) {
    analyzeBucket.value = bucket
    if (_analyzeComplete() && isTemporalColType(_colType(analyzeGroup.value))) runAnalyze()
  }
  // Pick the measure (row count, or sum/avg of a numeric column). `column` is ignored
  // for count. Runs when complete, clears the result otherwise.
  function setAnalyzeMeasure(fn, column) {
    analyzeFn.value = fn
    analyzeMeasureColumn.value = fn === 'count' ? null : (column || null)
    if (_analyzeComplete()) runAnalyze()
    else _clearAnalyzeResult()
  }

  // --- Unified Analyze workspace actions ---------------------------------------
  // Re-default the measure list from the columns, as long as the user has not touched it.
  // The list is created before the columns are known (a store is built empty), so the
  // real default can only be computed later: this runs at every gate that may follow a
  // column change (host mount, scope change, and every request). Idempotent - an unchanged
  // list is left alone, so nothing re-renders and no extra request fires.
  function _applyDefaultMeasures() {
    if (!measuresPristine) return
    const next = defaultWorkspaceMeasures(deps.getColumns(), isIdentifierColumn)
    const current = workspaceMeasures.value || []
    const unchanged = current.length === next.length
      && current.every((m, i) => measureKey(m) === measureKey(next[i]))
    if (unchanged) return
    workspaceMeasures.value = next
  }

  // Run the workspace aggregate: 1..8 measures over the optional grouping, capped at 50
  // group rows. Guarded by workspaceSeq + the meta epoch, exactly like the pivot above.
  async function runWorkspace() {
    if (!workspaceActive.value || !deps.isActive()) return
    _applyDefaultMeasures()
    const measures = (workspaceMeasures.value || []).slice(0, MAX_WORKSPACE_MEASURES)
    if (!measures.length) return
    const my = ++workspaceSeq
    const epoch = deps.getEpoch()
    workspaceLoading.value = true
    workspaceError.value = ''
    try {
      const column = workspaceGroup.value
      const temporal = column ? isTemporalColType(_colType(column)) : false
      const group = column ? { column, bucket: temporal ? workspaceBucket.value : null } : null
      const data = await deps.fetchAggregate(group, measures, 50)
      if (my !== workspaceSeq || epoch !== deps.getEpoch()) return
      workspaceRows.value = Array.isArray(data.rows) ? data.rows : []
      workspaceTotals.value = data.totals || null
      workspaceTruncated.value = !!data.truncated
    } catch (e) {
      if (my !== workspaceSeq || epoch !== deps.getEpoch()) return
      workspaceError.value = _err(e)
      workspaceRows.value = []
      workspaceTotals.value = null
      workspaceTruncated.value = false
    } finally {
      if (my === workspaceSeq && epoch === deps.getEpoch()) workspaceLoading.value = false
    }
  }

  // A host declares that it DISPLAYS the workspace (mount) or stops (unmount). Activating
  // it while the Analyze view is open computes the first result immediately: the workspace
  // is never an empty shell waiting for input.
  function setWorkspaceActive(value) {
    workspaceActive.value = !!value
    // Default from the columns straight away, so the builder READS right on mount even
    // when no request can run yet (inactive host): the sentence must never show a measure
    // the first result will not be about.
    if (workspaceActive.value) _applyDefaultMeasures()
    if (workspaceActive.value && analyzeOpen.value) runWorkspace()
  }
  // Add one measure. A duplicate (same fn + column) or the 8-measure ceiling is a no-op,
  // so no request fires for a list that did not change. A real change is the user taking
  // the list over: the automatic default never overwrites it afterwards.
  function addWorkspaceMeasure(fn, column) {
    const next = addMeasure(workspaceMeasures.value, { fn, column })
    if (next === workspaceMeasures.value) return
    workspaceMeasures.value = next
    measuresPristine = false
    runWorkspace()
  }
  // Remove one measure. Removing the LAST one is refused (there is always a result).
  function removeWorkspaceMeasure(index) {
    const next = removeMeasureAt(workspaceMeasures.value, index)
    if (next === workspaceMeasures.value) return
    workspaceMeasures.value = next
    measuresPristine = false
    runWorkspace()
  }
  // Change one measure in place (chip click -> pick another): the slot keeps its rank,
  // so swapping the first measure keeps it the ranking measure. No-ops fire no request.
  function replaceWorkspaceMeasure(index, fn, column) {
    const next = replaceMeasureAt(workspaceMeasures.value, index, { fn, column })
    if (next === workspaceMeasures.value) return
    workspaceMeasures.value = next
    measuresPristine = false
    runWorkspace()
  }
  // Pick the grouping ('' / null = all filtered rows). A temporal column starts on the
  // month bucket so a date grouping is immediately usable.
  function setWorkspaceGroup(column) {
    workspaceGroup.value = column || null
    if (workspaceGroup.value && isTemporalColType(_colType(workspaceGroup.value))) {
      workspaceBucket.value = 'month'
    }
    runWorkspace()
  }
  function setWorkspaceBucket(bucket) {
    workspaceBucket.value = bucket
    if (workspaceGroup.value && isTemporalColType(_colType(workspaceGroup.value))) runWorkspace()
  }

  // React to a scope change the host detected on a fresh load. `sig` is the host-computed
  // scope signature. Same scope -> nothing to recompute, EXCEPT a row count that failed
  // transiently (it would otherwise stay blank forever). New scope -> re-compute the
  // Calculate zone (persistent, follows the filters), re-fire the count, and re-run
  // Analyze if it is open with a complete selection.
  function afterScopeChange(sig) {
    if (sig === lastViewSig) {
      if (totalCount.value == null && !totalLoading.value) refreshTotals()
      return
    }
    lastViewSig = sig
    if (calcColumn.value) _reloadCalc()
    refreshTotals()
    if (analyzeOpen.value && _analyzeComplete()) runAnalyze()
    // A new scope may be a new DATASET: re-default the untouched measure list here, not
    // only on the request below, so the builder already reads right when the user opens
    // the Analyze view (no count -> sum flash on arrival).
    if (workspaceActive.value) _applyDefaultMeasures()
    if (workspaceActive.value && analyzeOpen.value) runWorkspace()
  }

  // rowsStale bookkeeping the hosts drive from their rows-load spots:
  //   - a FRESH Data-view load that succeeded matched the current scope -> clearRowsStale
  //   - a scope change while Analyze is open skipped the Data window     -> markRowsStale
  function markRowsStale() { rowsStale = true }
  function clearRowsStale() { rowsStale = false }

  return {
    // DB-computed row count + the Calculate zone
    totalCount, totalLoading, calcColumn, calcFns, calcValues, calcLoading, calcError,
    setCalcColumn, setCalcFns, reloadCalc,
    // Analyze (mini-pivot)
    analyzeOpen, analyzeGroup, analyzeBucket, analyzeFn, analyzeMeasureColumn,
    analyzeRows, analyzeTotals, analyzeTruncated, analyzeLoading, analyzeError,
    setAnalyzeOpen, setAnalyzeGroup, setAnalyzeBucket, setAnalyzeMeasure, runAnalyze,
    // Unified Analyze workspace (measures + optional grouping, standalone explorer)
    workspaceActive, workspaceMeasures, workspaceGroup, workspaceBucket,
    workspaceRows, workspaceTotals, workspaceTruncated, workspaceLoading, workspaceError,
    setWorkspaceActive, addWorkspaceMeasure, removeWorkspaceMeasure, replaceWorkspaceMeasure,
    setWorkspaceGroup, setWorkspaceBucket, runWorkspace,
    // host orchestration hooks
    refreshTotals, afterScopeChange, resetDerived, invalidate,
    markRowsStale, clearRowsStale,
  }
}
