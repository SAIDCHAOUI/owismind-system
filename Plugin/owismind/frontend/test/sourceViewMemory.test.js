// Plugin/owismind/frontend/test/sourceViewMemory.test.js
// Pure per-(agent, dataset) view memory + restore sanitizers (composables/
// sourceViewMemory.js). NO install: from frontend/ run  node --test test/
// The Pinia store has no node tests, so ALL the branching that keeps a user's filters /
// search / sort / Calculate selection alive lives in this pure module and is covered here.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  createViewMemory,
  sanitizeRestoredChips,
  sanitizeRestoredSort,
  sanitizeRestoredCalc,
} from '../src/composables/sourceViewMemory.js'

const COLUMNS = [
  { name: 'amount', type: 'int' },
  { name: 'country', type: 'string' },
  { name: 'sale_date', type: 'date' },
]

function sampleView() {
  return {
    chips: [{ key: 'u1', column: 'country', op: '=', values: ['FR'] }],
    q: 'paris',
    sort: { column: 'amount', dir: 'desc' },
    calcColumn: 'amount',
    calcFns: ['sum', 'avg'],
  }
}

// --- createViewMemory: save / restore / evict / deep-copy ----------------------

test('createViewMemory: save then restore returns the view', () => {
  const mem = createViewMemory()
  mem.save('agentA', 1, sampleView())
  const got = mem.restore('agentA', 1)
  assert.equal(got.q, 'paris')
  assert.equal(got.calcColumn, 'amount')
  assert.deepEqual(got.calcFns, ['sum', 'avg'])
  assert.deepEqual(got.sort, { column: 'amount', dir: 'desc' })
  assert.equal(got.chips.length, 1)
  assert.deepEqual(got.chips[0].values, ['FR'])
})

test('createViewMemory: unknown key restores null', () => {
  const mem = createViewMemory()
  assert.equal(mem.restore('agentA', 1), null)
  mem.save('agentA', 1, sampleView())
  assert.equal(mem.restore('agentA', 2), null) // same agent, other dataset
  assert.equal(mem.restore('agentB', 1), null) // other agent, same id
})

test('createViewMemory: key separates agent and source id (no collision)', () => {
  const mem = createViewMemory()
  // 'a' + NUL + '11'  vs  'a1' + NUL + '1' must not collide.
  mem.save('a', 11, { ...sampleView(), q: 'first' })
  mem.save('a1', 1, { ...sampleView(), q: 'second' })
  assert.equal(mem.restore('a', 11).q, 'first')
  assert.equal(mem.restore('a1', 1).q, 'second')
})

test('createViewMemory: save deep-copies (no shared refs on the way in)', () => {
  const mem = createViewMemory()
  const view = sampleView()
  mem.save('agentA', 1, view)
  // Mutate the caller's object AFTER saving: the stored copy must not change.
  view.chips[0].values.push('DE')
  view.calcFns.push('min')
  view.q = 'mutated'
  const got = mem.restore('agentA', 1)
  assert.deepEqual(got.chips[0].values, ['FR'])
  assert.deepEqual(got.calcFns, ['sum', 'avg'])
  assert.equal(got.q, 'paris')
})

test('createViewMemory: restore deep-copies (mutating one restore does not poison the next)', () => {
  const mem = createViewMemory()
  mem.save('agentA', 1, sampleView())
  const a = mem.restore('agentA', 1)
  a.chips[0].values.push('DE')
  a.calcFns.push('min')
  const b = mem.restore('agentA', 1)
  assert.deepEqual(b.chips[0].values, ['FR'])
  assert.deepEqual(b.calcFns, ['sum', 'avg'])
})

test('createViewMemory: re-saving an existing key updates in place, no eviction', () => {
  const mem = createViewMemory(2)
  mem.save('a', 1, { ...sampleView(), q: 'one' })
  mem.save('a', 2, { ...sampleView(), q: 'two' })
  mem.save('a', 1, { ...sampleView(), q: 'one-bis' }) // update, not a new key
  assert.equal(mem.restore('a', 1).q, 'one-bis')
  assert.equal(mem.restore('a', 2).q, 'two') // still present (no eviction)
})

test('createViewMemory: FIFO eviction of the oldest past the cap', () => {
  const mem = createViewMemory(2)
  mem.save('a', 1, { ...sampleView(), q: 'one' })
  mem.save('a', 2, { ...sampleView(), q: 'two' })
  mem.save('a', 3, { ...sampleView(), q: 'three' }) // evicts (a,1), the oldest
  assert.equal(mem.restore('a', 1), null)
  assert.equal(mem.restore('a', 2).q, 'two')
  assert.equal(mem.restore('a', 3).q, 'three')
})

test('createViewMemory: remove forgets one entry', () => {
  const mem = createViewMemory()
  mem.save('a', 1, sampleView())
  mem.remove('a', 1)
  assert.equal(mem.restore('a', 1), null)
  mem.remove('a', 2) // removing an absent key is a no-op
})

test('createViewMemory: clear empties the whole memory', () => {
  const mem = createViewMemory()
  mem.save('a', 1, sampleView())
  mem.save('b', 2, sampleView())
  mem.clear()
  assert.equal(mem.restore('a', 1), null)
  assert.equal(mem.restore('b', 2), null)
})

// --- sanitizeRestoredChips -----------------------------------------------------

test('sanitizeRestoredChips: drops chips whose column no longer exists', () => {
  const chips = [
    { key: 'u1', column: 'country', op: '=', values: ['FR'] },
    { key: 'u2', column: 'ghost', op: '=', values: ['X'] }, // column gone
  ]
  const out = sanitizeRestoredChips(chips, COLUMNS)
  assert.equal(out.length, 1)
  assert.equal(out[0].column, 'country')
})

test('sanitizeRestoredChips: drops chips with no values, keeps regardless of op string', () => {
  const chips = [
    { key: 'u1', column: 'country', op: 'weird-op', values: ['FR'] }, // op is cosmetic
    { key: 'u2', column: 'amount', op: '=', values: [] }, // empty values -> drop
    { key: 'u3', column: 'amount', op: '=' }, // no values array -> drop
    { key: 'u4', column: 'sale_date', op: 'BETWEEN', values: ['2025-01-01', '2025-12-31'] },
  ]
  const out = sanitizeRestoredChips(chips, COLUMNS)
  assert.deepEqual(out.map((c) => c.column), ['country', 'sale_date'])
  // BETWEEN op preserved verbatim, values copied.
  assert.equal(out[1].op, 'BETWEEN')
  assert.deepEqual(out[1].values, ['2025-01-01', '2025-12-31'])
})

test('sanitizeRestoredChips: returns fresh copied values (no shared refs)', () => {
  const values = ['FR']
  const chips = [{ key: 'u1', column: 'country', op: '=', values }]
  const out = sanitizeRestoredChips(chips, COLUMNS)
  values.push('DE')
  assert.deepEqual(out[0].values, ['FR'])
})

test('sanitizeRestoredChips: empty / nullish inputs -> empty array', () => {
  assert.deepEqual(sanitizeRestoredChips(null, COLUMNS), [])
  assert.deepEqual(sanitizeRestoredChips([], COLUMNS), [])
  assert.deepEqual(sanitizeRestoredChips([{ column: 'country', values: ['FR'] }], null), [])
})

// --- sanitizeRestoredSort ------------------------------------------------------

test('sanitizeRestoredSort: keeps a valid sort', () => {
  assert.deepEqual(
    sanitizeRestoredSort({ column: 'amount', dir: 'asc' }, COLUMNS),
    { column: 'amount', dir: 'asc' },
  )
})

test('sanitizeRestoredSort: null on missing column, bad direction or missing sort', () => {
  assert.equal(sanitizeRestoredSort({ column: 'ghost', dir: 'asc' }, COLUMNS), null)
  assert.equal(sanitizeRestoredSort({ column: 'amount', dir: 'sideways' }, COLUMNS), null)
  assert.equal(sanitizeRestoredSort({ column: 'amount' }, COLUMNS), null)
  assert.equal(sanitizeRestoredSort(null, COLUMNS), null)
  assert.equal(sanitizeRestoredSort({ dir: 'asc' }, COLUMNS), null)
})

// --- sanitizeRestoredCalc ------------------------------------------------------

test('sanitizeRestoredCalc: null column -> { column:null, fns:[] }', () => {
  assert.deepEqual(sanitizeRestoredCalc(null, ['sum'], COLUMNS), { column: null, fns: [] })
})

test('sanitizeRestoredCalc: unknown column -> null column + empty fns', () => {
  assert.deepEqual(sanitizeRestoredCalc('ghost', ['sum'], COLUMNS), { column: null, fns: [] })
})

test('sanitizeRestoredCalc: numeric column filters fns to statsSpec ORDER', () => {
  // Requested out of order + one bogus fn: kept in spec order (sum, avg, median, min, max).
  const out = sanitizeRestoredCalc('amount', ['max', 'avg', 'bogus', 'sum'], COLUMNS)
  assert.equal(out.column, 'amount')
  assert.deepEqual(out.fns, ['sum', 'avg', 'max'])
})

test('sanitizeRestoredCalc: no fn survives -> defaults for the type', () => {
  // Numeric default is ['sum'].
  assert.deepEqual(sanitizeRestoredCalc('amount', ['bogus'], COLUMNS), { column: 'amount', fns: ['sum'] })
  assert.deepEqual(sanitizeRestoredCalc('amount', [], COLUMNS), { column: 'amount', fns: ['sum'] })
  // Temporal default is ['min','max'].
  assert.deepEqual(sanitizeRestoredCalc('sale_date', ['sum'], COLUMNS), { column: 'sale_date', fns: ['min', 'max'] })
  // Text default is ['count_distinct'].
  assert.deepEqual(sanitizeRestoredCalc('country', ['sum'], COLUMNS), { column: 'country', fns: ['count_distinct'] })
})

test('sanitizeRestoredCalc: temporal column keeps only min/max in spec order', () => {
  const out = sanitizeRestoredCalc('sale_date', ['max', 'sum', 'min'], COLUMNS)
  assert.deepEqual(out, { column: 'sale_date', fns: ['min', 'max'] })
})
