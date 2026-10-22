// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/aggregateSurface.test.js
// The SHARED aggregate-surface state machine (composables/aggregateSurface.js) driven with
// injected fake deps - the state transitions the Source explorer AND the Evidence tab rely
// on. NO install: from frontend/ run  node --test test/  (the factory imports vue's `ref`,
// resolvable from node_modules here). Behaviour must stay byte-identical to the machine
// extracted from stores/sources.js.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createAggregateSurface } from '../src/composables/aggregateSurface.js'

// Flush pending microtasks (the calc zone uses a .then().catch().finally() chain).
const flush = () => new Promise((r) => setTimeout(r, 0))

// Build a surface over controllable deps + a call log. `respond(call, i)` returns the
// aggregate response (or throws to simulate a backend error).
function makeSurface(opts = {}) {
  const o = opts
  const calls = []
  let epoch = o.epoch || 0
  let active = o.active !== undefined ? o.active : true
  const columns = o.columns || [
    { name: 'amount', type: 'int' },
    { name: 'country', type: 'string' },
    { name: 'sale_date', type: 'date' },
  ]
  let respond = o.respond || (() => ({ rows: [{ m0: 42 }] }))
  const refreshRowsCalls = []
  const surface = createAggregateSurface({
    getColumns: () => columns,
    isActive: () => active,
    getEpoch: () => epoch,
    fetchAggregate: (group, measures, limit) => {
      const call = { group, measures, limit }
      calls.push(call)
      return Promise.resolve().then(() => respond(call, calls.length - 1))
    },
    refreshRows: () => { refreshRowsCalls.push(1); return Promise.resolve() },
    errorCode: 'source_unavailable',
  })
  return {
    surface, calls, refreshRowsCalls,
    setEpoch: (e) => { epoch = e },
    setActive: (a) => { active = a },
    setRespond: (fn) => { respond = fn },
  }
}

const isCountCall = (c) => c.group === null && c.measures.length === 1 && c.measures[0].fn === 'count'

// --- Calculate zone ------------------------------------------------------------

test('setCalcColumn: a numeric column starts on the default measure subset and maps by position', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 100 }] }) })
  h.surface.setCalcColumn('amount')
  assert.equal(h.surface.calcColumn.value, 'amount')
  // int default subset -> [sum] only (never all five figures at once)
  assert.deepEqual(h.surface.calcFns.value, ['sum'])
  assert.equal(h.calls[0].group, null)
  assert.equal(h.calls[0].limit, 1)
  assert.deepEqual(h.calls[0].measures.map((m) => m.fn), ['sum'])
  assert.equal(h.calls[0].measures[0].column, 'amount')
  await flush()
  assert.deepEqual(h.surface.calcValues.value, { sum: 100 })
  assert.equal(h.surface.calcLoading.value, false)
})

test('setCalcColumn: a temporal column defaults to [min, max]; a text column to [count_distinct]', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 'a', m1: 'z' }] }) })
  h.surface.setCalcColumn('sale_date')
  assert.deepEqual(h.surface.calcFns.value, ['min', 'max'])
  assert.deepEqual(h.calls[0].measures.map((m) => m.fn), ['min', 'max'])
  await flush()
  assert.deepEqual(h.surface.calcValues.value, { min: 'a', max: 'z' })
  h.surface.setCalcColumn('country')
  assert.deepEqual(h.surface.calcFns.value, ['count_distinct'])
})

test('setCalcFns: selecting a subset re-fetches ONLY those measures, mapped by position in spec order', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 20, m1: 1, m2: 99 }] }) })
  h.surface.setCalcColumn('amount')
  await flush()
  const before = h.calls.length
  // Ask for avg + max, out of order + with an unknown fn: sanitized to spec order [avg, max].
  h.surface.setCalcFns(['max', 'bogus', 'avg'])
  assert.deepEqual(h.surface.calcFns.value, ['avg', 'max'])
  const call = h.calls[before]
  assert.deepEqual(call.measures.map((m) => m.fn), ['avg', 'max'])
  await flush()
  // m0 -> avg, m1 -> max, m2 -> min (min not selected, so not present)
  assert.deepEqual(h.surface.calcValues.value, { avg: 20, max: 1 })
})

test('setCalcFns: an empty (or all-unknown) selection is ignored - the current subset is kept', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 5 }] }) })
  h.surface.setCalcColumn('amount')
  await flush()
  const n = h.calls.length
  h.surface.setCalcFns([]) // empty -> no-op
  h.surface.setCalcFns(['unknown_fn']) // nothing survives sanitize -> no-op
  assert.deepEqual(h.surface.calcFns.value, ['sum'])
  assert.equal(h.calls.length, n, 'no re-fetch fired')
})

test('setCalcColumn: re-picking the same column or an empty pick toggles the zone off', async () => {
  const h = makeSurface()
  h.surface.setCalcColumn('amount')
  await flush()
  h.surface.setCalcColumn('amount') // same column -> clear
  assert.equal(h.surface.calcColumn.value, null)
  assert.equal(h.surface.calcValues.value, null)
  h.surface.setCalcColumn('country')
  await flush()
  assert.equal(h.surface.calcColumn.value, 'country')
  h.surface.setCalcColumn('') // empty pick -> clear
  assert.equal(h.surface.calcColumn.value, null)
})

test('setCalcColumn: a NULL value in the aggregate maps to null (rendered as a dash)', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: null, m1: 0 }] }) })
  h.surface.setCalcColumn('amount')
  h.surface.setCalcFns(['sum', 'avg']) // request two so both positions are covered
  await flush()
  assert.equal(h.surface.calcValues.value.sum, null)
  assert.equal(h.surface.calcValues.value.avg, 0) // a real 0 is preserved
})

test('reloadCalc after an error retries; a failing calc surfaces the error code', async () => {
  let fail = true
  const h = makeSurface({ respond: () => { if (fail) throw new Error('boom'); return { rows: [{ m0: 5 }] } } })
  h.surface.setCalcColumn('amount')
  await flush()
  assert.equal(h.surface.calcError.value, 'boom')
  assert.equal(h.surface.calcValues.value, null)
  fail = false
  h.surface.reloadCalc()
  await flush()
  assert.equal(h.surface.calcError.value, '')
  assert.equal(h.surface.calcValues.value.sum, 5)
})

// --- afterScopeChange (count + calc follow the filters) ------------------------

test('afterScopeChange: a NEW scope fires the row count and reloads the Calculate zone', async () => {
  const h = makeSurface({
    respond: (c) => (isCountCall(c) ? { rows: [{ m0: 7 }] } : { rows: [{ m0: 100 }] }),
  })
  h.surface.setCalcColumn('amount')
  await flush()
  const before = h.calls.length
  h.surface.afterScopeChange('sigA')
  await flush()
  const added = h.calls.slice(before)
  assert.ok(added.some(isCountCall), 'a count call fired')
  assert.ok(
    added.some((c) => !isCountCall(c) && c.measures[0] && c.measures[0].column === 'amount'),
    'the calc zone reloaded',
  )
  assert.equal(h.surface.totalCount.value, 7)
})

test('afterScopeChange: same sig with a present count is a no-op; a null count is healed', async () => {
  let failCount = true
  const h = makeSurface({
    respond: (c) => {
      if (isCountCall(c) && failCount) throw new Error('boom')
      return { rows: [{ m0: 5 }] }
    },
  })
  h.surface.afterScopeChange('sigA') // new sig -> count fails -> null
  await flush()
  assert.equal(h.surface.totalCount.value, null)
  const n1 = h.calls.length
  failCount = false
  h.surface.afterScopeChange('sigA') // same sig + null count -> heal
  await flush()
  assert.ok(h.calls.length > n1)
  assert.equal(h.surface.totalCount.value, 5)
  const n2 = h.calls.length
  h.surface.afterScopeChange('sigA') // same sig + present count -> nothing
  await flush()
  assert.equal(h.calls.length, n2)
})

// --- Analyze (mini-pivot) ------------------------------------------------------

test('analyze: count is complete without a column; sum needs a numeric column', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ key: 'DZ', m0: 3 }], totals: { m0: 10 }, truncated: false }) })
  h.surface.setAnalyzeGroup('country') // count is the default measure -> complete -> runs
  await flush()
  assert.equal(h.calls.length, 1)
  assert.equal(h.calls[0].measures[0].fn, 'count')
  assert.deepEqual(h.surface.analyzeRows.value, [{ key: 'DZ', m0: 3 }])
  assert.deepEqual(h.surface.analyzeTotals.value, { m0: 10 })
  const n = h.calls.length
  h.surface.setAnalyzeMeasure('sum', null) // sum without a column -> clears, no run
  await flush()
  assert.equal(h.calls.length, n)
  assert.deepEqual(h.surface.analyzeRows.value, [])
  h.surface.setAnalyzeMeasure('sum', 'amount') // sum with a column -> runs
  await flush()
  assert.equal(h.calls.length, n + 1)
  assert.equal(h.calls[n].measures[0].fn, 'sum')
  assert.equal(h.calls[n].measures[0].column, 'amount')
  assert.equal(h.calls[n].limit, 50)
})

test('analyze: a temporal group carries the month bucket', async () => {
  const h = makeSurface({ respond: () => ({ rows: [], totals: null }) })
  h.surface.setAnalyzeGroup('sale_date') // temporal -> bucket defaults to month, count runs
  await flush()
  assert.deepEqual(h.calls[0].group, { column: 'sale_date', bucket: 'month' })
})

test('setAnalyzeOpen: closing after a stale scope change re-fetches the host rows', async () => {
  const h = makeSurface({ respond: () => ({ rows: [], totals: null }) })
  h.surface.setAnalyzeOpen(true)
  h.surface.markRowsStale() // scope changed while analyzing (host skipped the rows window)
  h.surface.setAnalyzeOpen(false)
  assert.equal(h.refreshRowsCalls.length, 1)
  // Closing again with no stale change does NOT re-fetch.
  h.surface.setAnalyzeOpen(true)
  h.surface.setAnalyzeOpen(false)
  assert.equal(h.refreshRowsCalls.length, 1)
})

test('rowsShown: the rows window is on screen in the Data view AND in the mounted workspace', () => {
  const h = makeSurface({ respond: () => ({ rows: [], totals: null }) })
  assert.equal(h.surface.rowsShown(), true) // Data view
  h.surface.setAnalyzeOpen(true)
  assert.equal(h.surface.rowsShown(), false) // Analyze open, workspace not mounted yet
  h.surface.setWorkspaceActive(true)
  assert.equal(h.surface.rowsShown(), true) // the workspace data pane browses the same window
  h.surface.setWorkspaceActive(false)
  assert.equal(h.surface.rowsShown(), false)
})

test('ensureFreshRows: a mounting workspace catches up a skipped window exactly once', () => {
  const h = makeSurface({ respond: () => ({ rows: [], totals: null }) })
  h.surface.ensureFreshRows() // current window: no request
  assert.equal(h.refreshRowsCalls.length, 0)
  h.surface.setAnalyzeOpen(true)
  h.surface.markRowsStale() // scope changed before the workspace mounted
  h.surface.setWorkspaceActive(true)
  h.surface.ensureFreshRows()
  assert.equal(h.refreshRowsCalls.length, 1)
  h.surface.ensureFreshRows() // stale flag consumed
  assert.equal(h.refreshRowsCalls.length, 1)
  // Back to the Data view: nothing stale left, no second fetch.
  h.surface.setAnalyzeOpen(false)
  assert.equal(h.refreshRowsCalls.length, 1)
})

// --- reset / staleness guards --------------------------------------------------

test('resetDerived clears the calc + analyze + count state and the defaults', async () => {
  const h = makeSurface()
  h.surface.setCalcColumn('amount')
  h.surface.setAnalyzeGroup('country')
  h.surface.setAnalyzeOpen(true)
  await flush()
  h.surface.resetDerived()
  assert.equal(h.surface.calcColumn.value, null)
  assert.deepEqual(h.surface.calcFns.value, [])
  assert.equal(h.surface.calcValues.value, null)
  assert.equal(h.surface.analyzeGroup.value, null)
  assert.equal(h.surface.analyzeOpen.value, false)
  assert.equal(h.surface.analyzeBucket.value, 'month')
  assert.equal(h.surface.analyzeFn.value, 'count')
  assert.equal(h.surface.totalCount.value, null)
})

test('epoch guard: a calc response that lands after the epoch changed is dropped', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 111, m1: 1, m2: 1, m3: 1, m4: 1 }] }) })
  h.surface.setCalcColumn('amount')
  h.setEpoch(9) // the exchange/source moved on before the response applied
  await flush()
  assert.equal(h.surface.calcValues.value, null)
})

test('invalidate: drops an in-flight aggregate response without touching the epoch', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 1, m1: 2, m2: 3, m3: 4, m4: 5 }] }) })
  h.surface.setCalcColumn('amount')
  h.surface.invalidate()
  await flush()
  assert.equal(h.surface.calcValues.value, null)
})

test('inactive host: setCalcColumn / refreshTotals / runAnalyze issue no request', async () => {
  const h = makeSurface({ active: false })
  h.surface.setCalcColumn('amount')
  assert.equal(h.surface.calcColumn.value, null)
  await h.surface.refreshTotals()
  h.surface.setAnalyzeGroup('country')
  await h.surface.runAnalyze()
  assert.equal(h.calls.length, 0)
})

// --- Unified Analyze workspace (measures + optional grouping) ---------------------
// The standalone Source explorer drives this state; the Evidence hosts never activate it.

test('workspace: inert until a host activates it, then it computes immediately', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 640 }], totals: null, truncated: false }) })
  h.surface.setAnalyzeOpen(true)
  await flush()
  assert.equal(h.calls.length, 0, 'a host that does not display the workspace requests nothing')

  h.surface.setWorkspaceActive(true)
  await flush()
  assert.equal(h.calls.length, 1)
  // The default figure is the SUM of the first numeric quantity column, never the row
  // count (which the scope bar already states), and no grouping.
  assert.deepEqual(h.calls[0].measures, [{ fn: 'sum', column: 'amount' }])
  assert.equal(h.calls[0].group, null)
  assert.deepEqual(h.surface.workspaceRows.value, [{ m0: 640 }])
})

test('workspace: adding a measure re-runs with both, a duplicate does nothing', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 1, m1: 2 }] }) })
  h.surface.setWorkspaceActive(true)
  h.surface.setAnalyzeOpen(true)
  await flush()
  const before = h.calls.length

  h.surface.addWorkspaceMeasure('count', null)
  await flush()
  assert.equal(h.calls.length, before + 1)
  assert.deepEqual(h.calls[h.calls.length - 1].measures, [
    { fn: 'sum', column: 'amount' },
    { fn: 'count', column: null },
  ])

  h.surface.addWorkspaceMeasure('count', null) // exact duplicate
  await flush()
  assert.equal(h.calls.length, before + 1, 'no request for a list that did not change')
})

test('workspace: the last measure cannot be removed', async () => {
  const h = makeSurface()
  h.surface.setWorkspaceActive(true)
  await flush()
  h.surface.removeWorkspaceMeasure(0)
  await flush()
  assert.deepEqual(h.surface.workspaceMeasures.value, [{ fn: 'sum', column: 'amount' }])
})

// --- The default measure (user ask 2026-08-13: never open on a row count) ----------

test('workspace: with no numeric quantity column the row count stays the default', async () => {
  const h = makeSurface({ columns: [{ name: 'country', type: 'string' }, { name: 'label', type: 'string' }] })
  h.surface.setAnalyzeOpen(true)
  h.surface.setWorkspaceActive(true)
  await flush()
  assert.deepEqual(h.surface.workspaceMeasures.value, [{ fn: 'count', column: null }])
  assert.deepEqual(h.calls[0].measures, [{ fn: 'count', column: null }])
})

test('workspace: an identifier-shaped numeric column is never the default measure', async () => {
  const h = makeSurface({
    columns: [
      { name: 'customer_id', type: 'bigint' }, // an id is numeric but summing it is nonsense
      { name: 'year', type: 'int' },
      { name: 'revenue', type: 'double' },
    ],
  })
  h.surface.setWorkspaceActive(true)
  await flush()
  assert.deepEqual(h.surface.workspaceMeasures.value, [{ fn: 'sum', column: 'revenue' }])
})

test('workspace: the default is computed when the COLUMNS arrive, not before', async () => {
  // A store is built before its meta loads: the surface starts on the row count and
  // re-defaults itself on the first scope change that carries columns.
  let cols = []
  const calls = []
  const surface = createAggregateSurface({
    getColumns: () => cols,
    isActive: () => true,
    getEpoch: () => 0,
    fetchAggregate: (group, measures, limit) => {
      calls.push({ group, measures, limit })
      return Promise.resolve({ rows: [{ m0: 1 }] })
    },
    refreshRows: () => {},
    errorCode: 'source_unavailable',
  })
  surface.setWorkspaceActive(true)
  surface.setAnalyzeOpen(true)
  await flush()
  assert.deepEqual(surface.workspaceMeasures.value, [{ fn: 'count', column: null }])

  cols = [{ name: 'amount', type: 'int' }]
  surface.afterScopeChange('sig-with-columns')
  await flush()
  assert.deepEqual(surface.workspaceMeasures.value, [{ fn: 'sum', column: 'amount' }])
})

test('workspace: a user choice is never overwritten by the automatic default', async () => {
  let cols = []
  const surface = createAggregateSurface({
    getColumns: () => cols,
    isActive: () => true,
    getEpoch: () => 0,
    fetchAggregate: () => Promise.resolve({ rows: [{ m0: 1 }] }),
    refreshRows: () => {},
    errorCode: 'source_unavailable',
  })
  surface.setWorkspaceActive(true)
  surface.setAnalyzeOpen(true)
  await flush()
  // The user takes the list over BEFORE the columns are known.
  surface.replaceWorkspaceMeasure(0, 'count_distinct', 'country')
  await flush()

  cols = [{ name: 'amount', type: 'int' }, { name: 'country', type: 'string' }]
  surface.afterScopeChange('sig-with-columns')
  await flush()
  assert.deepEqual(
    surface.workspaceMeasures.value,
    [{ fn: 'count_distinct', column: 'country' }],
    'their measure survives every later scope change',
  )
})

test('workspace: resetDerived re-arms the default for the NEXT dataset', async () => {
  const h = makeSurface()
  h.surface.setWorkspaceActive(true)
  h.surface.setAnalyzeOpen(true)
  await flush()
  h.surface.addWorkspaceMeasure('avg', 'amount') // the list is now the user's
  await flush()

  h.surface.resetDerived() // switching dataset
  h.surface.afterScopeChange('sig-next')
  await flush()
  assert.deepEqual(
    h.surface.workspaceMeasures.value,
    [{ fn: 'sum', column: 'amount' }],
    'a new scope opens on its own default again',
  )
})

test('workspace: grouping sends the group, a temporal column starts on the month bucket', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ key: 'FR', m0: 3 }], totals: { m0: 9 }, truncated: true }) })
  h.surface.setWorkspaceActive(true)
  await flush()

  h.surface.setWorkspaceGroup('country')
  await flush()
  let call = h.calls[h.calls.length - 1]
  assert.deepEqual(call.group, { column: 'country', bucket: null }, 'a text column is not bucketed')
  assert.equal(call.limit, 50)
  assert.deepEqual(h.surface.workspaceTotals.value, { m0: 9 })
  assert.equal(h.surface.workspaceTruncated.value, true)

  h.surface.setWorkspaceGroup('sale_date')
  await flush()
  call = h.calls[h.calls.length - 1]
  assert.deepEqual(call.group, { column: 'sale_date', bucket: 'month' })

  h.surface.setWorkspaceBucket('quarter')
  await flush()
  assert.deepEqual(h.calls[h.calls.length - 1].group, { column: 'sale_date', bucket: 'quarter' })

  // Back to "all filtered rows": no group at all.
  h.surface.setWorkspaceGroup(null)
  await flush()
  assert.equal(h.calls[h.calls.length - 1].group, null)
})

test('workspace: a bucket change on a NON temporal group issues no request', async () => {
  const h = makeSurface()
  h.surface.setWorkspaceActive(true)
  h.surface.setWorkspaceGroup('country')
  await flush()
  const before = h.calls.length
  h.surface.setWorkspaceBucket('year')
  await flush()
  assert.equal(h.calls.length, before)
})

test('workspace: a scope change re-runs it only while the Analyze view is open', async () => {
  const h = makeSurface()
  h.surface.setWorkspaceActive(true)
  await flush()
  const before = h.calls.length

  h.surface.afterScopeChange('sig-1') // Data view: count + calc only
  await flush()
  const afterClosed = h.calls.length
  assert.equal(
    h.calls.slice(before, afterClosed).some((c) => c.limit === 50),
    false,
    'the workspace is not recomputed while its view is hidden',
  )

  h.surface.setAnalyzeOpen(true)
  await flush()
  h.surface.afterScopeChange('sig-2')
  await flush()
  assert.equal(h.calls[h.calls.length - 1].limit, 50)
})

test('workspace: a superseded or stale-epoch response never lands', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 1 }] }) })
  h.surface.setWorkspaceActive(true)
  await flush()
  // Superseded: a newer run wins whatever the response order.
  h.setRespond(() => ({ rows: [{ m0: 'old' }] }))
  h.surface.runWorkspace()
  h.setRespond(() => ({ rows: [{ m0: 'new' }] }))
  h.surface.runWorkspace()
  await flush()
  assert.deepEqual(h.surface.workspaceRows.value, [{ m0: 'new' }])

  // Stale epoch: the source moved on while the request was in flight.
  h.setRespond(() => ({ rows: [{ m0: 'ghost' }] }))
  h.surface.runWorkspace()
  h.setEpoch(42)
  await flush()
  assert.deepEqual(h.surface.workspaceRows.value, [{ m0: 'new' }])
})

test('workspace: resetDerived returns it to the honest default', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 1, m1: 2 }] }) })
  h.surface.setWorkspaceActive(true)
  h.surface.addWorkspaceMeasure('sum', 'amount')
  h.surface.setWorkspaceGroup('country')
  await flush()

  h.surface.resetDerived()
  assert.deepEqual(h.surface.workspaceMeasures.value, [{ fn: 'count', column: null }])
  assert.equal(h.surface.workspaceGroup.value, null)
  assert.deepEqual(h.surface.workspaceRows.value, [])
  assert.equal(h.surface.workspaceActive.value, true, 'the host is still mounted')
})

test('workspace: an error surfaces and clears the previous result', async () => {
  const h = makeSurface()
  h.surface.setWorkspaceActive(true)
  await flush()
  h.setRespond(() => { throw new Error('source_unavailable') })
  await h.surface.runWorkspace()
  assert.equal(h.surface.workspaceError.value, 'source_unavailable')
  assert.deepEqual(h.surface.workspaceRows.value, [])
  assert.equal(h.surface.workspaceLoading.value, false)
})
