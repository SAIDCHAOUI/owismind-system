// Plugin/owismind/frontend/test/aggregateSurface.test.js
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

test('setCalcColumn: a numeric column fetches type-driven measures and maps values by position', async () => {
  const h = makeSurface({ respond: () => ({ rows: [{ m0: 100, m1: 20, m2: 15, m3: 1, m4: 99 }] }) })
  h.surface.setCalcColumn('amount')
  assert.equal(h.surface.calcColumn.value, 'amount')
  assert.equal(h.calls[0].group, null)
  assert.equal(h.calls[0].limit, 1)
  // int -> sum, avg, median, min, max (statsSpecFor)
  assert.deepEqual(h.calls[0].measures.map((m) => m.fn), ['sum', 'avg', 'median', 'min', 'max'])
  await flush()
  assert.deepEqual(h.surface.calcValues.value, { sum: 100, avg: 20, median: 15, min: 1, max: 99 })
  assert.equal(h.surface.calcLoading.value, false)
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
  const h = makeSurface({ respond: () => ({ rows: [{ m0: null, m1: 0, m2: null, m3: 0, m4: 0 }] }) })
  h.surface.setCalcColumn('amount')
  await flush()
  assert.equal(h.surface.calcValues.value.sum, null)
  assert.equal(h.surface.calcValues.value.avg, 0) // a real 0 is preserved
})

test('reloadCalc after an error retries; a failing calc surfaces the error code', async () => {
  let fail = true
  const h = makeSurface({ respond: () => { if (fail) throw new Error('boom'); return { rows: [{ m0: 5, m1: 5, m2: 5, m3: 5, m4: 5 }] } } })
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
    respond: (c) => (isCountCall(c) ? { rows: [{ m0: 7 }] } : { rows: [{ m0: 100, m1: 20, m2: 15, m3: 1, m4: 99 }] }),
  })
  h.surface.setCalcColumn('amount')
  await flush()
  const before = h.calls.length
  h.surface.afterScopeChange('sigA')
  await flush()
  const added = h.calls.slice(before)
  assert.ok(added.some(isCountCall), 'a count call fired')
  assert.ok(added.some((c) => c.measures.length === 5), 'the calc zone reloaded')
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

// --- reset / staleness guards --------------------------------------------------

test('resetDerived clears the calc + analyze + count state and the defaults', async () => {
  const h = makeSurface()
  h.surface.setCalcColumn('amount')
  h.surface.setAnalyzeGroup('country')
  h.surface.setAnalyzeOpen(true)
  await flush()
  h.surface.resetDerived()
  assert.equal(h.surface.calcColumn.value, null)
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
