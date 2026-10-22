// Dashboard arrangement (V2 Studio) - run with `node --test`. Pure ordering logic
// (merge with the current widgets, moves), the automatic row packing (layoutBoard)
// and the best-effort persistence against an in-memory storage stub (including a
// throwing one).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  BOARD_STORAGE_KEY, MAX_BOARDS, emptyBoard, sanitizeBoard, isEmptyBoard,
  mergeBoardOrder, orderWidgets, moveToFront, moveRelative, moveWithinGroup,
  loadBoard, saveBoard, boardTracks, layoutBoard, autoWide, scopeWidget, boardWidgets,
  isScopeWidget, filterBoard, replaceInOrder, removeFromBoard,
} from '../src/composables/boardOrder.js'

function memoryStorage() {
  const m = new Map()
  return {
    getItem: (k) => (m.has(k) ? m.get(k) : null),
    setItem: (k, v) => m.set(k, String(v)),
    removeItem: (k) => m.delete(k),
    raw: m,
  }
}
const throwing = {
  getItem() { throw new Error('SecurityError') },
  setItem() { throw new Error('QuotaExceededError') },
}

test('merge keeps the saved order, drops unknown ids and appends new widgets in arrival order', () => {
  assert.deepEqual(mergeBoardOrder([], ['a', 'b', 'c']), ['a', 'b', 'c'])
  assert.deepEqual(mergeBoardOrder(['c', 'a'], ['a', 'b', 'c']), ['c', 'a', 'b'])
  assert.deepEqual(mergeBoardOrder(['zz', 'b', 'b', 'a'], ['a', 'b']), ['b', 'a'])
  // A live run adds widgets after the user arranged the board: they land at the end.
  assert.deepEqual(mergeBoardOrder(['b', 'a'], ['a', 'b', 'd', 'e']), ['b', 'a', 'd', 'e'])
  assert.deepEqual(mergeBoardOrder(null, null), [])
})

test('orderWidgets returns the same widget objects in the arranged order', () => {
  const a = { id: 'a' }, b = { id: 'b' }, c = { id: 'c' }
  const out = orderWidgets([a, b, c], ['c', 'a'])
  assert.deepEqual(out.map((w) => w.id), ['c', 'a', 'b'])
  assert.equal(out[0], c)
  assert.deepEqual(orderWidgets([], ['a']), [])
})

test('moveToFront and moveRelative', () => {
  assert.deepEqual(moveToFront(['a', 'b', 'c'], 'c'), ['c', 'a', 'b'])
  assert.deepEqual(moveToFront(['a', 'b'], 'zz'), ['a', 'b'])
  assert.deepEqual(moveRelative(['a', 'b', 'c'], 'a', 'c', true), ['b', 'c', 'a'])
  assert.deepEqual(moveRelative(['a', 'b', 'c'], 'c', 'a', false), ['c', 'a', 'b'])
  assert.deepEqual(moveRelative(['a', 'b', 'c'], 'a', 'b', true), ['b', 'a', 'c'])
  // Drop on itself or on an unknown widget: unchanged (and a new array).
  const same = ['a', 'b']
  const r = moveRelative(same, 'a', 'a', true)
  assert.deepEqual(r, same)
  assert.notEqual(r, same)
  assert.deepEqual(moveRelative(same, 'a', 'zz', false), same)
})

test('moveWithinGroup moves inside one visual group only (KPI row vs grid)', () => {
  // k1/k2 are KPI cards (their own row), c1/c2/t1 the grid.
  const order = ['k1', 'c1', 'k2', 'c2', 't1']
  const grid = ['c1', 'c2', 't1']
  let r = moveWithinGroup(order, 'c2', grid, -1)
  assert.equal(r.moved, true)
  assert.deepEqual(r.order, ['k1', 'c2', 'c1', 'k2', 't1'])
  assert.deepEqual([r.index, r.count], [0, 3])
  r = moveWithinGroup(order, 'c1', grid, Infinity)
  assert.deepEqual(r.order.filter((x) => grid.includes(x)), ['c2', 't1', 'c1'])
  assert.equal(r.index, 2)
  r = moveWithinGroup(order, 'k2', ['k1', 'k2'], -Infinity)
  assert.deepEqual(r.order.filter((x) => x.startsWith('k')), ['k2', 'k1'])
  // Already first / last: nothing moves, the index is reported for the announcement.
  r = moveWithinGroup(order, 'c1', grid, -1)
  assert.deepEqual([r.moved, r.index], [false, 0])
  r = moveWithinGroup(order, 'zz', grid, 1)
  assert.deepEqual([r.moved, r.index], [false, -1])
})

test('track count follows the board width', () => {
  assert.deepEqual([boardTracks(0), boardTracks(479), boardTracks(480), boardTracks(899), boardTracks(900)], [1, 1, 2, 2, 4])
})

// --- automatic layout ---------------------------------------------------------------

const T = (id, extra) => ({ id, kind: 'text', title: id, text: 'x', ...extra })
const C = (id, extra) => ({ id, kind: 'chart', title: id, sql_id: 's1q1', chart: { type: 'bar', x: 'a', y: ['b'] }, ...extra })
const TB = (id, extra) => ({ id, kind: 'table', title: id, sql_id: 's1q1', ...extra })
const K = (id) => ({ id, kind: 'kpi', title: id, sql_id: 's1q1', kpi: { label: id, value: 'v' } })
const spans = (items) => items.map((it) => it.id + ':' + it.span).join(' ')
const KPI_IDS = /^k/
// Every row of the result is exactly full (no hole), in order. The only void allowed
// is a final row made of KPIs alone (nothing follows to fill it). A KPI never spans
// more than 2 columns.
function assertNoHole(items, n) {
  let used = 0
  let row = []
  for (const it of items) {
    assert.ok(it.span >= 1 && it.span <= n, 'span out of range: ' + it.id)
    assert.ok(used + it.span <= n, 'row overflow at ' + it.id)
    if (KPI_IDS.test(it.id)) assert.ok(it.span <= 2, 'stretched KPI: ' + it.id + ':' + it.span)
    used = (used + it.span) % n
    row = used === 0 ? [] : row.concat(it)
  }
  if (used !== 0) assert.ok(row.every((it) => KPI_IDS.test(it.id)), 'the last row is not filled')
}

test('a section text followed by a normal chart is a 2 + 2 pair', () => {
  const out = layoutBoard([T('t1'), C('c1')], { columns: 4 })
  assert.equal(spans(out), 't1:2 c1:2')
  assert.deepEqual(out.map((it) => it.paired), [true, true])
  assert.deepEqual(out.map((it) => it.wide), [false, false])
})

test('a wide data widget (agent hint or heuristic) makes a HERO: text row above the figure row', () => {
  const hero = layoutBoard([T('t'), C('c', { size: 'wide' })], { columns: 4 })
  assert.equal(spans(hero), 't:4 c:4')
  assert.deepEqual(hero.map((it) => [it.paired, it.hero, it.wide]), [[true, true, false], [true, true, true]])
  // Heuristic: a table with >= 5 columns, a line / area chart with more than 12 points.
  const shapeOf = (w) => (w.kind === 'table' ? { columns: 6 } : { points: 24 })
  assert.equal(spans(layoutBoard([T('t'), TB('tb')], { columns: 4, shapeOf })), 't:4 tb:4')
  const line = C('c', { chart: { type: 'line', x: 'm', y: ['v'] } })
  assert.equal(spans(layoutBoard([T('t'), line], { columns: 4, shapeOf })), 't:4 c:4')
  // A bar chart with many points stays normal; an explicit "normal" beats the heuristic.
  assert.equal(spans(layoutBoard([T('t'), C('c')], { columns: 4, shapeOf })), 't:2 c:2')
  assert.equal(spans(layoutBoard([T('t'), TB('tb', { size: 'normal' })], { columns: 4, shapeOf })), 't:2 tb:2')
  // Only the user's own Expand keeps the text beside the figure (1 + 3); Shrink on a
  // hero figure brings the 2 + 2 pair back.
  const out = layoutBoard([T('t'), C('c')], { columns: 4, overrides: { c: true } })
  assert.equal(spans(out), 't:1 c:3')
  assert.equal(out[1].wide, true)
  assert.equal(spans(layoutBoard([T('t'), C('c', { size: 'wide' })], { columns: 4, overrides: { c: true } })), 't:1 c:3')
  assert.equal(spans(layoutBoard([T('t'), C('c', { size: 'wide' })], { columns: 4, overrides: { c: false } })), 't:2 c:2')
  // Swapped (figure first): the hero keeps the user's order.
  assert.equal(spans(layoutBoard([C('c', { size: 'wide' }), T('t')], { columns: 4 })), 'c:4 t:4')
})

test('hero sections alternate with side-by-side pairs', () => {
  const W = (id) => C(id, { size: 'wide' })
  const out = layoutBoard([T('t1'), W('c1'), T('t2'), C('c2'), T('t3'), W('c3'), T('t4'), C('c4')], { columns: 4 })
  assert.equal(spans(out), 't1:4 c1:4 t2:2 c2:2 t3:4 c3:4 t4:2 c4:2')
  assert.deepEqual(out.map((it) => it.hero), [true, true, false, false, true, true, false, false])
  assertNoHole(out, 4)
})

test('autoWide: hint first, heuristic second, unknown shape = compact', () => {
  assert.equal(autoWide(TB('a'), { columns: 4 }), false)
  assert.equal(autoWide(TB('a'), { columns: 5 }), true)
  assert.equal(autoWide(TB('a'), null), false)
  assert.equal(autoWide(C('a', { chart: { type: 'bar', style: 'area' } }), { points: 13 }), true)
  assert.equal(autoWide(C('a', { chart: { type: 'line' } }), { points: 12 }), false)
  assert.equal(autoWide(K('k'), { columns: 9 }), false)
  assert.equal(autoWide(T('t', { size: 'wide' })), false)
})

test('the user swaps a pair: the data widget first still pairs with its text', () => {
  assert.equal(spans(layoutBoard([C('c'), T('t')], { columns: 4 })), 'c:2 t:2')
  // ... unless that text leads a pair of its own (text-first wins).
  assert.equal(spans(layoutBoard([C('c0'), T('t'), C('c1')], { columns: 4 })), 'c0:4 t:2 c1:2')
})

test('a lone KPI pulls the next pair into its row (KPI 1 + text 1 + figure 2)', () => {
  const out = layoutBoard([K('k'), T('t'), C('c'), T('t2'), C('c2')], { columns: 4 })
  assert.equal(spans(out), 'k:1 t:1 c:2 t2:2 c2:2')
  assert.deepEqual(out.map((it) => it.paired), [false, true, true, true, true])
  assertNoHole(out, 4)
  // The swapped pair keeps its order when pulled in.
  assert.equal(spans(layoutBoard([K('k'), C('c'), T('t')], { columns: 4 })), 'k:1 c:2 t:1')
  // A lone KPI then a hero: the text fills the KPI row, the figure keeps its full row.
  assert.equal(spans(layoutBoard([K('k'), T('t'), C('c', { size: 'wide' })], { columns: 4 })), 'k:1 t:3 c:4')
  // A lone KPI then a standalone figure: the figure is the one that stretches.
  assert.equal(spans(layoutBoard([K('k'), C('c')], { columns: 4 })), 'k:1 c:3')
})

test('two KPIs share their row 2 + 2 when the next pair cannot join them', () => {
  const out = layoutBoard([K('k1'), K('k2'), T('t'), C('c')], { columns: 4 })
  assert.equal(spans(out), 'k1:2 k2:2 t:2 c:2')
  assertNoHole(out, 4)
  // ... but a following figure joins them at its own width.
  assert.equal(spans(layoutBoard([K('k1'), K('k2'), C('c'), C('c2')], { columns: 4 })), 'k1:1 k2:1 c:2 c2:4')
})

test('three KPIs then a pair: 1 + 1 + 2, never a stretched KPI', () => {
  const out = layoutBoard([K('k1'), K('k2'), K('k3'), T('t'), C('c')], { columns: 4 })
  assert.equal(spans(out), 'k1:1 k2:1 k3:2 t:2 c:2')
  assertNoHole(out, 4)
  // A standalone text completes the row instead.
  assert.equal(spans(layoutBoard([K('k1'), K('k2'), K('k3'), T('t'), T('t2')], { columns: 4 })), 'k1:1 k2:1 k3:1 t:1 t2:4')
  // Four KPIs fill a row exactly; a final lone KPI takes 2 columns and leaves the rest.
  assert.equal(spans(layoutBoard([K('a'), K('b'), K('c'), K('d'), K('e')], { columns: 4 })), 'a:1 b:1 c:1 d:1 e:2')
})

test('a widened KPI alone: the next widget fills the empty half', () => {
  const out = layoutBoard([K('k'), T('t'), C('c')], { columns: 4, overrides: { k: true } })
  assert.equal(spans(out), 'k:2 t:2 c:4')
  assertNoHole(out, 4)
})

test('an odd standalone chart is extended to the full row; two share one', () => {
  assert.equal(spans(layoutBoard([C('a'), C('b'), C('c')], { columns: 4 })), 'a:2 b:2 c:4')
  // A pair never splits: the chart (never the KPI) absorbs the space before it.
  const out = layoutBoard([C('a'), K('k'), T('t'), C('c')], { columns: 4 })
  assert.equal(spans(out), 'a:3 k:1 t:2 c:2')
  assertNoHole(out, 4)
})

test('a standalone section text takes the full row, half when shrunk', () => {
  assert.equal(spans(layoutBoard([T('a'), T('b')], { columns: 4 })), 'a:4 b:4')
  const out = layoutBoard([T('a'), K('k'), T('b')], { columns: 4, overrides: { a: false } })
  assert.equal(spans(out), 'a:3 k:1 b:4')
  assert.equal(out[0].wide, false)
  assert.equal(out[2].wide, true)
})

test('user overrides win over defaults; the no-hole fill still applies', () => {
  // Expanding a text takes it out of its pair (full row), the chart is then alone.
  let out = layoutBoard([T('t'), C('c')], { columns: 4, overrides: { t: true } })
  assert.equal(spans(out), 't:4 c:4')
  assert.deepEqual(out.map((it) => it.paired), [false, false])
  // Shrinking a wide table back to compact.
  out = layoutBoard([TB('a', { size: 'wide' }), C('b')], { columns: 4, overrides: { a: false } })
  assert.equal(spans(out), 'a:2 b:2')
  // A widened KPI takes 2 columns.
  out = layoutBoard([K('k1'), K('k2'), K('k3')], { columns: 4, overrides: { k1: true } })
  assert.equal(spans(out), 'k1:2 k2:1 k3:1')
  assertNoHole(out, 4)
  // A widened chart alone: full row.
  assert.equal(spans(layoutBoard([C('a'), C('b')], { columns: 4, overrides: { a: true } })), 'a:4 b:4')
})

test('2-column board: pairs 1 + 1, a wide pair stacks, KPIs pair up', () => {
  assert.equal(spans(layoutBoard([T('t'), C('c')], { columns: 2 })), 't:1 c:1')
  assert.equal(spans(layoutBoard([T('t'), C('c', { size: 'wide' })], { columns: 2 })), 't:2 c:2')
  const out = layoutBoard([K('a'), K('b'), K('c'), C('d'), T('e')], { columns: 2 })
  assert.equal(spans(out), 'a:1 b:1 c:2 d:1 e:1')
  assertNoHole(out, 2)
})

test('1-column board: every widget spans the column', () => {
  const out = layoutBoard([K('a'), T('t'), C('c'), TB('tb', { size: 'wide' })], { columns: 1 })
  assert.equal(spans(out), 'a:1 t:1 c:1 tb:1')
  assert.equal(spans(layoutBoard([T('t'), C('c')], { columns: 0 })), 't:1 c:1')
})

test('no board ever has a hole (mixed sequences, every breakpoint)', () => {
  const pool = [K('k1'), T('t1'), C('c1'), K('k2'), TB('tb', { size: 'wide' }), T('t2'), C('c2'), C('c3'), K('k3'), T('t3'), K('k4'), C('c4', { size: 'wide' })]
  for (const n of [1, 2, 4]) {
    for (let start = 0; start < pool.length; start++) {
      const seq = pool.slice(start).concat(pool.slice(0, start))
      assertNoHole(layoutBoard(seq, { columns: n }), n)
      assertNoHole(layoutBoard(seq, { columns: n, overrides: { t1: true, c2: true, k2: true, t3: false } }), n)
    }
  }
})

test('exhaustive: every short sequence keeps full rows and KPIs at 2 columns at most', () => {
  // Kinds: KPI, widened KPI, text, normal chart, wide chart, wide table.
  const make = [
    (i) => K('k' + i),
    (i) => K('kw' + i),
    (i) => T('t' + i),
    (i) => C('c' + i),
    (i) => C('cw' + i, { size: 'wide' }),
    (i) => TB('tb' + i, { size: 'wide' }),
  ]
  const walk = (seq) => {
    if (seq.length) {
      const widgets = seq.map((k, i) => make[k](i))
      const overrides = {}
      for (const w of widgets) if (w.id.startsWith('kw')) overrides[w.id] = true
      for (const n of [1, 2, 4]) assertNoHole(layoutBoard(widgets, { columns: n, overrides }), n)
    }
    if (seq.length < 5) for (let k = 0; k < make.length; k++) walk(seq.concat(k))
  }
  walk([])
})

test('scope widgets stay off the board; the latest one is the scope', () => {
  const s1 = T('s1', { role: 'scope' })
  const s2 = T('s2', { role: 'scope' })
  const list = [s1, T('t', { role: 'section' }), C('c'), s2]
  assert.equal(spans(layoutBoard(list, { columns: 4 })), 't:2 c:2')
  assert.equal(scopeWidget(list), s2)
  assert.equal(scopeWidget([T('t')]), null)
  assert.equal(scopeWidget(null), null)
  assert.deepEqual(boardWidgets(list).map((w) => w.id), ['t', 'c'])
  assert.equal(isScopeWidget(C('c', { role: 'scope' })), false)
})

test('old widgets without size / role keep the automatic layout', () => {
  const old = [
    { id: 't', kind: 'text', title: 'Intro', text: 'x' },
    { id: 'c', kind: 'chart', title: 'C', sql_id: 's1q1', chart: { type: 'bar', x: 'a', y: ['b'] } },
    { id: 'k', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'K', value: 'v' } },
  ]
  const out = layoutBoard(old, { columns: 4 })
  assert.equal(spans(out), 't:2 c:2 k:2')
  assert.deepEqual(layoutBoard([], { columns: 4 }), [])
  assert.deepEqual(layoutBoard(null), [])
})

test('sanitizeBoard bounds and cleans anything read back', () => {
  assert.deepEqual(sanitizeBoard(null), emptyBoard())
  assert.deepEqual(sanitizeBoard('x'), emptyBoard())
  const clean = sanitizeBoard({
    order: ['a', 'a', 3, '', 'x'.repeat(65), 'b'],
    expanded: { a: true, c: false, b: 'yes', ['y'.repeat(65)]: true },
  })
  assert.deepEqual(clean, { order: ['a', 'b'], expanded: { a: true, c: false } })
  assert.deepEqual(sanitizeBoard({ expanded: ['a'] }).expanded, {})
  assert.equal(sanitizeBoard({ order: Array.from({ length: 500 }, (_, i) => 'w' + i) }).order.length, 200)
  assert.equal(isEmptyBoard(emptyBoard()), true)
  assert.equal(isEmptyBoard({ order: [], expanded: { a: true } }), false)
})

test('save / load round trip per namespace and exchange; an empty board is forgotten', () => {
  const s = memoryStorage()
  assert.equal(saveBoard(s, 'nsA', 42, { order: ['b', 'a'], expanded: { b: true } }, 1), true)
  assert.deepEqual(loadBoard(s, 'nsA', 42), { order: ['b', 'a'], expanded: { b: true } })
  assert.deepEqual(loadBoard(s, 'nsA', '42'), { order: ['b', 'a'], expanded: { b: true } })
  // Another DSS project (namespace) or another answer never sees it.
  assert.deepEqual(loadBoard(s, 'nsB', 42), emptyBoard())
  assert.deepEqual(loadBoard(s, 'nsA', 43), emptyBoard())
  saveBoard(s, 'nsA', 42, emptyBoard(), 2)
  assert.deepEqual(JSON.parse(s.getItem(BOARD_STORAGE_KEY)), {})
  // No exchange id yet (a live run before /chat/start): nothing is written.
  assert.equal(saveBoard(s, 'nsA', null, { order: ['a'], expanded: {} }), false)
  assert.deepEqual(loadBoard(s, 'nsA', null), emptyBoard())
})

test('the oldest boards are evicted past the cap', () => {
  const s = memoryStorage()
  for (let i = 0; i < MAX_BOARDS + 5; i++) saveBoard(s, 'ns', i, { order: ['a'], expanded: {} }, i)
  const all = JSON.parse(s.getItem(BOARD_STORAGE_KEY))
  assert.equal(Object.keys(all).length, MAX_BOARDS)
  assert.deepEqual(loadBoard(s, 'ns', 0), emptyBoard())
  assert.deepEqual(loadBoard(s, 'ns', MAX_BOARDS + 4).order, ['a'])
})

test('a broken or refusing storage degrades to "not remembered", never throws', () => {
  assert.deepEqual(loadBoard(throwing, 'ns', 1), emptyBoard())
  assert.equal(saveBoard(throwing, 'ns', 1, { order: ['a'], expanded: {} }), false)
  assert.deepEqual(loadBoard(null, 'ns', 1), emptyBoard())
  const s = memoryStorage()
  s.setItem(BOARD_STORAGE_KEY, '{not json')
  assert.deepEqual(loadBoard(s, 'ns', 1), emptyBoard())
  assert.equal(saveBoard(s, 'ns', 1, { order: ['a'], expanded: {} }, 1), true)
  assert.deepEqual(loadBoard(s, 'ns', 1).order, ['a'])
})

// --- continued Studio (carry / replaces / remove) ----------------------------------------

test('filterBoard keeps the order and widths of the carried widgets only', () => {
  const board = { order: ['w3', 'w1', 'w2'], expanded: { w1: true, w2: false, w9: true } }
  assert.deepEqual(filterBoard(board, ['w1', 'w3']), { order: ['w3', 'w1'], expanded: { w1: true } })
  assert.deepEqual(filterBoard(board, []), emptyBoard())
  assert.deepEqual(filterBoard(null, ['w1']), emptyBoard())
  // The source arrangement is never mutated.
  assert.deepEqual(board.order, ['w3', 'w1', 'w2'])
})

test('replaceInOrder puts the new widget at the place of the one it replaces', () => {
  assert.deepEqual(replaceInOrder(['w1', 'w2', 'w3'], 'w2', 'w4'), ['w1', 'w4', 'w3'])
  // A stale copy of the new id elsewhere is dropped (no duplicate).
  assert.deepEqual(replaceInOrder(['w4', 'w1', 'w2'], 'w2', 'w4'), ['w1', 'w4'])
  // Unknown target or invalid id: unchanged copy.
  const order = ['w1', 'w2']
  const same = replaceInOrder(order, 'w9', 'w4')
  assert.deepEqual(same, order)
  assert.notEqual(same, order)
  assert.deepEqual(replaceInOrder(order, 'w1', ''), order)
})

test('removeFromBoard drops the widget from the order and its width choice', () => {
  const board = { order: ['w1', 'w2'], expanded: { w1: true, w2: false } }
  assert.deepEqual(removeFromBoard(board, 'w1'), { order: ['w2'], expanded: { w2: false } })
  assert.deepEqual(removeFromBoard(board, 'w9'), board)
  assert.deepEqual(board.order, ['w1', 'w2'])
})
