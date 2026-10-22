// Workspace store (V2): when the Studio opens and closes by itself during a live run,
// and the dashboard enlargement state. Runs the REAL Pinia store under node:test; the
// browser globals the service layer touches are stubbed (no request is ever sent: the
// runs below have no backend exchange id, so the store never fetches).
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'

globalThis.window = globalThis.window || {}
// services/track.js starts a best-effort flush ticker on import: never let it keep the
// test process alive.
const realSetInterval = globalThis.setInterval
globalThis.setInterval = (fn, ms, ...args) => {
  const handle = realSetInterval(fn, ms, ...args)
  if (handle && typeof handle.unref === 'function') handle.unref()
  return handle
}
const { createPinia, setActivePinia } = await import('pinia')
const { useWorkspaceStore } = await import('../src/stores/workspace.js')
const { dataFocus } = await import('../src/composables/workspaceModel.js')
const { sqlChoices } = await import('../src/composables/sqlChoices.js')

function ev(seq, op, payload) {
  return { type: 'workspace', v: 1, op, seq, ...payload }
}
const PLAN = ev(1, 'plan.set', { mission: 'M', origin: 'model', steps: [{ id: 'p1', label: 'One' }] })
const W1 = ev(2, 'widget.add', { id: 'w1', step_id: 'p1', kind: 'chart', title: 'C', sql_id: 's1q1', chart: { type: 'bar', x: 'a', y: ['b'] } })
const W2 = ev(3, 'widget.add', { id: 'w2', step_id: 'p1', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'L', value: 'v' } })

let ws
beforeEach(() => {
  setActivePinia(createPinia())
  ws = useWorkspaceStore()
})

test('the first published widget opens the Studio on the dashboard; a plan alone does not', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', PLAN)
  assert.equal(ws.open, false)
  ws.onLiveEvent('u1', W1)
  assert.equal(ws.open, true)
  assert.equal(ws.activeTab, 'board')
  ws.onLiveEvent('u1', W2)
  assert.equal(ws.state.widgets.length, 2)
})

test('an explicit user close is sticky for the run: later widgets do not re-open it', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.close({ byUser: true })
  assert.equal(ws.shown.dismissed, true)
  ws.onLiveEvent('u1', W2)
  assert.equal(ws.open, false)
})

test('a programmatic close (navigation, Source Data) never dismisses: the next widget re-opens', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.close()
  assert.equal(ws.shown.dismissed, false)
  assert.equal(ws.open, false)
  ws.onLiveEvent('u1', W2)
  assert.equal(ws.open, true)
})

test('run end opens the Studio once when no live widget event did (cap / replay path)', async () => {
  const e = ws.beginLive('u1')
  ws.onLiveEvent('u1', PLAN)
  // The widget reached the state without a live widget.add (e.g. a re-projected document).
  e.state.widgets.push({ id: 'w9', kind: 'table', title: 'T', sql_id: 's1q1' })
  assert.equal(ws.open, false)
  await ws.endLive('u1', 'done')
  assert.equal(ws.open, true)
  assert.equal(ws.activeTab, 'board')
})

test('run end does not re-open a Studio the user closed, nor one already opened live', async () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.close({ byUser: true })
  await ws.endLive('u1', 'done')
  assert.equal(ws.open, false)

  setActivePinia(createPinia())
  ws = useWorkspaceStore()
  ws.beginLive('u2')
  ws.onLiveEvent('u2', W1)
  ws.close() // navigated away; the live path already showed the widgets
  await ws.endLive('u2', 'done')
  assert.equal(ws.open, false)
})

test('a cancelled poll loop (null status) never opens the Studio', async () => {
  const e = ws.beginLive('u1')
  ws.onLiveEvent('u1', PLAN)
  e.state.widgets.push({ id: 'w9', kind: 'table', title: 'T', sql_id: 's1q1' })
  await ws.endLive('u1', null)
  assert.equal(ws.open, false)
})

test('expand toggles per widget; focus opens one widget and is reset on close and on another entry', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.toggleExpand('w1')
  assert.equal(ws.isExpanded('w1'), true)
  assert.equal(ws.isExpanded('w2'), false)
  ws.toggleExpand('w1')
  assert.equal(ws.isExpanded('w1'), false)
  ws.focusWidget('w1')
  assert.equal(ws.focusWidgetId, 'w1')
  ws.setTab('data')
  assert.equal(ws.focusWidgetId, null)
  ws.setTab('board')
  ws.focusWidget('w1')
  ws.closeFocus()
  assert.equal(ws.focusWidgetId, null)
  ws.toggleExpand('w1')
  ws.focusWidget('w1')
  ws.close()
  assert.equal(ws.focusWidgetId, null)
  // Another run's Studio shows: the enlargement state starts fresh.
  ws.beginLive('u2')
  ws.onLiveEvent('u2', W1)
  assert.equal(ws.isExpanded('w1'), false)
})

test('a widget arriving while Source Data is open does not steal the panel; the Studio opens once it closes', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  assert.equal(ws.open, true)
  // The user opens Source Data: AppLayout closes the Studio (programmatic) and reports it.
  ws.close()
  ws.setPanelContext({ otherPanel: true })
  ws.onLiveEvent('u1', W2)
  assert.equal(ws.open, false)
  assert.equal(ws.shown.dismissed, false)
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, true)
  assert.equal(ws.activeTab, 'board')
})

test('a deferred open survives the run end, but never a conversation switch or a cancelled run', async () => {
  ws.beginLive('u1')
  ws.setPanelContext({ otherPanel: true })
  ws.onLiveEvent('u1', W1)
  await ws.endLive('u1', 'done')
  assert.equal(ws.open, false)
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, true)

  setActivePinia(createPinia())
  ws = useWorkspaceStore()
  ws.beginLive('u2')
  ws.setPanelContext({ otherPanel: true })
  ws.onLiveEvent('u2', W1)
  ws.clearDeferred() // conversation switch
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, false)

  setActivePinia(createPinia())
  ws = useWorkspaceStore()
  ws.beginLive('u3')
  ws.setPanelContext({ otherPanel: true })
  ws.onLiveEvent('u3', W1)
  await ws.endLive('u3', null)
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, false)
})

test('a deferred auto-open never replaces a Studio the user opened on another answer', async () => {
  // Answer B: a finished run whose Studio the user can re-open.
  ws.beginLive('b')
  ws.onLiveEvent('b', W1)
  ws.bindExchange('b', 'EXB')
  await ws.endLive('b', 'done')
  ws.close() // the user engages Source Data
  ws.setPanelContext({ otherPanel: true })
  // Run A publishes while Source Data shows: deferred.
  ws.beginLive('a')
  ws.onLiveEvent('a', W1)
  assert.equal(ws.open, false)
  // The user opens B's Studio; AppLayout then closes Source Data.
  await ws.openForExchange('EXB', { uid: 'b' })
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, true)
  assert.equal(ws.shown.key, 'live:b')
})

test('closing another panel (narrow backdrop) while the Studio is closed never dismisses the run', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.close() // Source Data engaged
  ws.setPanelContext({ otherPanel: true })
  ws.onLiveEvent('u1', W2)
  ws.close({ byUser: true }) // backdrop tap closes Source Data, not the Studio
  assert.equal(ws.shown.dismissed, false)
  ws.setPanelContext({ otherPanel: false })
  assert.equal(ws.open, true)
})

test('off the chat route widgets never open the Studio; it opens once back on the chat', () => {
  ws.beginLive('u1')
  ws.setPanelContext({ onChat: false })
  ws.onLiveEvent('u1', W1)
  ws.onLiveEvent('u1', W2)
  assert.equal(ws.open, false)
  ws.setPanelContext({ onChat: true })
  assert.equal(ws.open, true)
})

test('conversation switch with a deferred open: the old run never reopens in the new conversation', () => {
  // Run A in conversation S1 publishes while Source Data is engaged: deferred.
  ws.beginLive('a', 'S1')
  ws.setPanelContext({ otherPanel: true, onChat: true, sessionId: 'S1' })
  ws.onLiveEvent('a', W1)
  assert.equal(ws.open, false)
  // openSession(S2), real order: the run is cancelled (its endLive comes later), Source
  // Data closes and the session switches in one tick; the panel watcher may run first.
  ws.setPanelContext({ otherPanel: false, onChat: true, sessionId: 'S2' })
  assert.equal(ws.open, false)
  assert.equal(ws.shown, null)
  // Same conversation: the deferred open still happens.
  setActivePinia(createPinia())
  ws = useWorkspaceStore()
  ws.beginLive('b', 'S1')
  ws.setPanelContext({ otherPanel: true, onChat: true, sessionId: 'S1' })
  ws.onLiveEvent('b', W1)
  ws.setPanelContext({ otherPanel: false, onChat: true, sessionId: 'S1' })
  assert.equal(ws.open, true)
})

// --- dashboard arrangement (user order + automatic row packing) ---------------------

const W3 = ev(4, 'widget.add', { id: 'w3', step_id: 'p1', kind: 'chart', title: 'C3', sql_id: 's1q1', chart: { type: 'bar', x: 'a', y: ['b'] } })
const W4 = ev(5, 'widget.add', { id: 'w4', step_id: 'p1', kind: 'chart', title: 'C4', sql_id: 's1q1', chart: { type: 'line', x: 'a', y: ['b'] } })
const ids = () => ws.boardOrderIds
const spanOf = (id) => ws.boardSpans[id] && ws.boardSpans[id].span

test('widening a widget keeps the order (the packing fills the rows); later widgets append at the end', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.onLiveEvent('u1', W3)
  assert.deepEqual([spanOf('w1'), spanOf('w3')], [2, 2])
  ws.toggleExpand('w3')
  assert.deepEqual(ids(), ['w1', 'w3'])
  assert.equal(ws.isExpanded('w3'), true)
  // w1 alone on its row is extended to fill it: no hole beside it.
  assert.deepEqual([spanOf('w1'), spanOf('w3')], [4, 4])
  // The live run goes on: the Studio stays open and the new widget lands after the arrangement.
  ws.onLiveEvent('u1', W4)
  assert.equal(ws.open, true)
  assert.equal(ws.state.widgets.length, 3)
  assert.equal(ws.moveWidget('w4', 'w3', false), true)
  assert.deepEqual(ids(), ['w1', 'w4', 'w3'])
  assert.deepEqual([spanOf('w1'), spanOf('w4'), spanOf('w3')], [2, 2, 4])
  // Collapsing keeps the place.
  ws.toggleExpand('w3')
  assert.deepEqual(ids(), ['w1', 'w4', 'w3'])
  assert.equal(ws.isExpanded('w3'), false)
  // The layout follows the column count reported by the board.
  ws.setBoardTracks(1)
  assert.deepEqual([spanOf('w1'), spanOf('w4'), spanOf('w3')], [1, 1, 1])
  ws.setBoardTracks(4)
})

test('keyboard moves report the new place within the given ids', () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', W1)
  ws.onLiveEvent('u1', W2)
  ws.onLiveEvent('u1', W3)
  const r = ws.moveWidgetBy('w3', ['w1', 'w3'], -1)
  assert.deepEqual(r, { moved: true, index: 0, count: 2 })
  assert.deepEqual(ids().filter((x) => x !== 'w2'), ['w3', 'w1'])
  assert.deepEqual(ws.moveWidgetBy('w3', ['w3', 'w1'], -1), { moved: false, index: 0, count: 2 })
  assert.equal(ws.moveWidget('w1', 'w1', true), false)
})

test('the arrangement is remembered per answer once its exchange id is known', () => {
  const store = new Map()
  globalThis.window.localStorage = {
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
  try {
    ws.beginLive('u1')
    ws.onLiveEvent('u1', W1)
    ws.onLiveEvent('u1', W3)
    ws.moveWidget('w3', 'w1', false)
    ws.toggleExpand('w3')
    assert.equal(store.size, 0) // no exchange id yet: memory only
    ws.bindExchange('u1', 501)
    assert.equal(store.size, 1)
    // Another live entry re-attached to the same answer restores the arrangement.
    ws.close()
    ws.beginLive('u2')
    ws.bindExchange('u2', 501)
    ws.onLiveEvent('u2', W1)
    ws.onLiveEvent('u2', W3)
    assert.deepEqual(ids(), ['w3', 'w1'])
    assert.equal(ws.isExpanded('w3'), true)
  } finally {
    delete globalThis.window.localStorage
  }
})

test('every kind has a width toggle with an automatic default; the user can override it', () => {
  const TXT = ev(1, 'widget.add', { id: 't1', step_id: 'p1', kind: 'text', title: 'Analyse', text: 'Le **constat**.' })
  const TBL = ev(7, 'widget.add', { id: 'tb', step_id: 'p1', kind: 'table', title: 'T', sql_id: 's1q1' })
  ws.beginLive('u1')
  ws.onLiveEvent('u1', TXT)
  ws.onLiveEvent('u1', W1)
  ws.onLiveEvent('u1', W2)
  ws.onLiveEvent('u1', TBL)
  // Arrival order is kept: the text section, then its chart (a pair on one row).
  assert.deepEqual(ws.state.widgets.map((w) => w.id), ['t1', 'w1', 'w2', 'tb'])
  assert.equal(ws.isExpanded('t1'), false) // beside its chart
  assert.equal(ws.isExpanded('w1'), false)
  assert.equal(ws.isExpanded('w2'), false) // KPI: compact card
  assert.equal(ws.isExpanded('tb'), false) // columns unknown: compact until the rows arrive
  // The KPI and the table share the second row; the table fills what is left.
  assert.deepEqual(['t1', 'w1', 'w2', 'tb'].map(spanOf), [2, 2, 1, 3])
  ws.toggleExpand('t1')
  assert.equal(ws.isExpanded('t1'), true) // out of its pair, full row
  assert.equal(spanOf('t1'), 4)
  ws.toggleExpand('w2')
  assert.equal(ws.isExpanded('w2'), true)
  ws.toggleExpand('tb')
  assert.equal(ws.isExpanded('tb'), true)
  assert.deepEqual(ws.expanded, { t1: true, w2: true, tb: true })
})

test('the scope text lives in the header, never on the board (latest one wins)', () => {
  const S1 = ev(2, 'widget.add', { id: 'sc1', kind: 'text', title: 'Scope', text: 'Revenue 2025', role: 'scope' })
  const TXT = ev(3, 'widget.add', { id: 't1', kind: 'text', title: 'Analyse', text: 'x', role: 'section' })
  const CH = ev(4, 'widget.add', { id: 'c1', kind: 'chart', title: 'C', sql_id: 's1q1', size: 'wide', chart: { type: 'bar', x: 'a', y: ['b'] } })
  const S2 = ev(5, 'widget.add', { id: 'sc2', kind: 'text', title: 'Scope', text: 'Revenue 2025, EMEA', role: 'scope' })
  ws.beginLive('u1')
  ws.onLiveEvent('u1', S1)
  assert.equal(ws.scope.id, 'sc1')
  assert.deepEqual(ws.boardList, [])
  ws.onLiveEvent('u1', TXT)
  ws.onLiveEvent('u1', CH)
  ws.onLiveEvent('u1', S2)
  assert.equal(ws.scope.id, 'sc2')
  assert.deepEqual(ws.boardList.map((w) => w.id), ['t1', 'c1'])
  // A wide chart after its section text: the HERO shape (text row above the figure row).
  assert.deepEqual([spanOf('t1'), spanOf('c1')], [4, 4])
  assert.equal(ws.boardSpans.sc1, undefined)
})

// --- continued Studio (studio.carry / widget.remove / replaces) ----------------------

function memoryStorage() {
  const store = new Map()
  return {
    store,
    getItem: (k) => (store.has(k) ? store.get(k) : null),
    setItem: (k, v) => store.set(k, String(v)),
    removeItem: (k) => store.delete(k),
  }
}
const CW1 = { id: 'w1', kind: 'chart', title: 'CA 2025 vs 2026', sql_id: 's1q1', chart: { type: 'line', x: 'm', y: ['v'] }, binding: 'explicit', origin: 'ex-a' }
const CW2 = { id: 'w2', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'L', value: 'v' }, binding: 'explicit', origin: 'ex-a' }
const carry = (seq, widgets) => ev(seq, 'studio.carry', { base_exchange_id: 'ex-a', widgets })

// A sealed base answer ex-a in memory: two widgets, the user's arrangement, its data.
function sealedBase() {
  const base = ws.beginLive('ua', 'sess')
  ws.bindExchange('ua', 'ex-a')
  ws.onLiveEvent('ua', W1)
  ws.onLiveEvent('ua', W2)
  ws.onLiveEvent('ua', { type: 'generated_sql', sqlId: 's1q1', sql: 'SELECT a', success: true, rowCount: 2, result: { columns: ['m', 'v'], rows: [['jan', 1], ['feb', 2]] } })
  ws.moveWidget('w2', 'w1', false)
  ws.toggleExpand('w1')
  base.running = false
  base.widgetsData = { w1: { labels: ['jan', 'feb'] } }
  base.resolved = { s1q1: { sql: 'SELECT a /* base */', filters: [], result: { captured: true, columns: ['m', 'v'], rows: [['jan', 1]] } } }
  return base
}

test('studio.carry copies the base board, its data and switches the Studio to the new answer', () => {
  const storage = memoryStorage()
  globalThis.window.localStorage = storage
  try {
    const base = sealedBase()
    assert.equal(ws.shown, base)
    assert.equal(ws.studioExchangeId(), 'ex-a')
    const next = ws.beginLive('ub', 'sess')
    ws.bindExchange('ub', 'ex-b')
    ws.onLiveEvent('ub', carry(1, [CW1, CW2]))
    // Same visuals: the user's order and width survive on the new answer.
    assert.equal(ws.shown, next)
    assert.deepEqual(ws.boardList.map((w) => w.id), ['w2', 'w1'])
    assert.equal(ws.isExpanded('w1'), true)
    assert.equal(next.state.base_exchange_id, 'ex-a')
    assert.ok(storage.store.size >= 1)
    // Data copied from the in-memory base, filed under its origin.
    assert.deepEqual(next.widgetsData.w1, { labels: ['jan', 'feb'] })
    assert.equal(ws.sqlInfo('s1q1', 'ex-a').sql, 'SELECT a /* base */')
    assert.equal(ws.sqlInfo('s1q1', 'ex-a').exchangeId, 'ex-a')
    // A new widget of this run appears at the bottom; its s1q1 is THIS run's.
    ws.onLiveEvent('ub', ev(2, 'widget.add', { id: 'w3', kind: 'table', title: '2025', sql_id: 's1q1' }))
    ws.onLiveEvent('ub', { type: 'generated_sql', sqlId: 's1q1', sql: 'SELECT b', success: true })
    assert.deepEqual(ws.boardList.map((w) => w.id), ['w2', 'w1', 'w3'])
    assert.equal(ws.sqlInfo('s1q1').sql, 'SELECT b')
    assert.equal(ws.sqlInfo('s1q1', 'ex-a').sql, 'SELECT a /* base */')
    assert.equal(ws.resultRef(ws.boardList[1]).key, 'ex-a|s1q1')
    assert.equal(ws.resultRef(ws.boardList[2]).key, 'ex-b|s1q1')
    // The base answer keeps its own snapshot.
    assert.equal(base.state.base_exchange_id, undefined)
    assert.deepEqual(base.state.widgets.map((w) => w.id), ['w1', 'w2'])
    // A running Studio is never sent as a base.
    assert.equal(ws.studioExchangeId(), null)
  } finally {
    delete globalThis.window.localStorage
  }
})

test('widget.remove drops the widget from the board; replaces keeps its place', () => {
  sealedBase()
  ws.beginLive('ub', 'sess')
  ws.bindExchange('ub', 'ex-b')
  ws.onLiveEvent('ub', carry(1, [CW1, CW2]))
  ws.onLiveEvent('ub', ev(2, 'widget.add', { id: 'w3', kind: 'table', title: 'T', sql_id: 's1q1' }))
  assert.deepEqual(ws.boardOrderIds, ['w2', 'w1'])
  ws.onLiveEvent('ub', ev(3, 'widget.add', { id: 'w4', replaces: 'w2', kind: 'table', title: 'T2', sql_id: 's1q2' }))
  assert.deepEqual(ws.boardList.map((w) => w.id), ['w4', 'w1', 'w3'])
  ws.onLiveEvent('ub', ev(4, 'widget.remove', { id: 'w1' }))
  assert.deepEqual(ws.boardList.map((w) => w.id), ['w4', 'w3'])
  assert.equal(ws.expanded.w1, undefined)
})

test('the provenance drawer and the Data focus address a carried result on its origin', () => {
  sealedBase()
  ws.beginLive('ub', 'sess')
  ws.bindExchange('ub', 'ex-b')
  ws.onLiveEvent('ub', carry(1, [CW1]))
  ws.openProvenance('s1q1', 'w1')
  assert.equal(ws.drawerOrigin, 'ex-a')
  ws.openData('s1q1', 'w1')
  assert.equal(ws.dataOrigin, 'ex-a')
  assert.equal(ws.dataExchangeId, 'ex-a')
  assert.equal(ws.hostsEvidence('ex-a'), true)
  assert.equal(ws.hostsEvidence('ex-zz'), false)
  ws.clearDataFocus()
  assert.equal(ws.dataExchangeId, 'ex-b')
  assert.equal(ws.hostsEvidence('ex-a'), false)
})

test('a base not in memory is read once from the server (widgets data + origins)', async () => {
  const calls = []
  globalThis.window.getWebAppBackendUrl = (p) => p
  const realFetch = globalThis.fetch
  globalThis.fetch = async (url) => {
    calls.push(String(url))
    return {
      ok: true,
      json: async () => ({
        workspace: { v: 1, status: 'done', widgets: [], provenance: { s1q1: { agent_key: 'revenue', tool: 'semantic-model-query', success: true } } },
        resolved: { s1q1: { sql: 'SELECT served' } },
        widgets_data: { w1: { labels: ['x'] } },
        origins: { 'ex-0': { resolved: { s2q1: { sql: 'SELECT older' } }, provenance: {} } },
      }),
    }
  }
  try {
    const next = ws.beginLive('ub', 'sess')
    ws.bindExchange('ub', 'ex-b')
    ws.onLiveEvent('ub', carry(1, [CW1, { ...CW2, id: 'w5', sql_id: 's2q1', origin: 'ex-0' }]))
    await new Promise((r) => setTimeout(r, 0))
    await new Promise((r) => setTimeout(r, 0))
    assert.equal(calls.length, 1)
    assert.ok(calls[0].includes('exchange_id=ex-a'))
    assert.deepEqual(next.widgetsData.w1, { labels: ['x'] })
    assert.equal(ws.sqlInfo('s1q1', 'ex-a').sql, 'SELECT served')
    assert.ok(ws.sqlInfo('s1q1', 'ex-a').provenance)
    // Flattened: a widget carried twice reads the exchange that owns its query.
    assert.equal(ws.sqlInfo('s2q1', 'ex-0').sql, 'SELECT older')
  } finally {
    globalThis.fetch = realFetch
    delete globalThis.window.getWebAppBackendUrl
  }
})

// --- HTTP walkthrough checks: sql_id collision, chat-only turn ---------------------------

// Turn 2 (ex-1002) restored from GET /workspace: its OWN s1q1 sits in provenance and
// resolved, and the carried w1 (origin ex-1001) has the SAME sql_id s1q1.
const TURN2_DOC = {
  workspace: {
    v: 1, status: 'done', exchange_id: 'ex-1002', base_exchange_id: 'ex-1001', last_seq: 3,
    plan: null, notes: [],
    widgets: [
      { id: 'w1', kind: 'table', title: 'CA mensuel', sql_id: 's1q1', binding: 'explicit', origin: 'ex-1001' },
      { id: 'w2', kind: 'table', title: 'CA 2025', sql_id: 's1q1', binding: 'explicit' },
    ],
    provenance: { s1q1: { agent_key: 'revenue-own', tool: 'semantic-model-query', success: true, row_count: 12 } },
  },
  events: null,
  resolved: { s1q1: { sql: 'SELECT own', filters: [{ column: 'year', op: '=', values: [2025] }], result: { captured: true, columns: ['m', 'v'], rows: [['own', 1]] } } },
  widgets_data: {},
  origins: {
    'ex-1001': {
      resolved: { s1q1: { sql: 'SELECT origin', filters: [{ column: 'year', op: 'IN', values: [2025, 2026] }], result: { captured: true, columns: ['m', 'v'], rows: [['origin', 2]] } } },
      provenance: { s1q1: { agent_key: 'revenue-origin', tool: 'semantic-model-query', success: true, row_count: 24 } },
    },
  },
}

async function withFetch(handler, fn) {
  globalThis.window.getWebAppBackendUrl = (p) => p
  const realFetch = globalThis.fetch
  globalThis.fetch = handler
  try {
    return await fn()
  } finally {
    globalThis.fetch = realFetch
    delete globalThis.window.getWebAppBackendUrl
  }
}
const okJson = (body) => ({ ok: true, json: async () => body })

test('sql_id collision: a carried s1q1 never reads the current exchange s1q1', async () => {
  await withFetch(async () => okJson(JSON.parse(JSON.stringify(TURN2_DOC))), async () => {
    assert.equal(await ws.openForExchange('ex-1002'), true)
    const [w1, w2] = ws.state.widgets
    // Widget rows.
    assert.deepEqual(ws.widgetData(w1).result.rows, [['origin', 2]])
    assert.deepEqual(ws.widgetData(w2).result.rows, [['own', 1]])
    assert.equal(ws.resultRef(w1).exchangeId, 'ex-1001')
    assert.equal(ws.resultRef(w2).exchangeId, 'ex-1002')
    // Provenance drawer link (origin derived from the widget).
    ws.openProvenance(w1.sql_id, w1.id)
    const drawer = ws.sqlInfo(ws.drawerSqlId, ws.drawerOrigin)
    assert.equal(drawer.sql, 'SELECT origin')
    assert.equal(drawer.provenance.agent_key, 'revenue-origin')
    assert.equal(drawer.rowCount, 24)
    assert.equal(drawer.filters[0].op, 'IN')
    // Data tab / DataFocus / Evidence opener.
    ws.openData(ws.drawerSqlId, ws.drawerWidgetId, ws.drawerOrigin)
    assert.equal(ws.dataExchangeId, 'ex-1001')
    const focus = dataFocus(ws.state, ws.dataSqlId, ws.dataWidgetId, ws.dataOrigin)
    assert.equal(focus.widget.id, 'w1')
    assert.equal(focus.provenance, null)
    assert.equal(ws.sqlInfo(ws.dataSqlId, ws.dataOrigin).exchangeId, 'ex-1001')
    // The same sql_id on THIS exchange stays the run's own.
    ws.openData('s1q1', 'w2')
    assert.equal(ws.dataOrigin, null)
    assert.equal(ws.dataExchangeId, 'ex-1002')
    assert.equal(ws.sqlInfo('s1q1').provenance.agent_key, 'revenue-own')
    assert.equal(dataFocus(ws.state, 's1q1', 'w1').widget.id, 'w2')
    // sqlChoices of this exchange's Evidence: only the own widget labels s1q1.
    assert.deepEqual(sqlChoices({ queries: [{ sql_id: 's1q1' }] }, ws.state, 's1q1')[0].widgets, ['CA 2025'])
    // A missing origin join is an empty read, never a fallback to this exchange.
    assert.equal(ws.sqlInfo('s1q1', 'ex-unknown'), null)
  })
})

test('a chat-only turn (no workspace) keeps the shown Studio: no fetch, no flicker, no summary', async () => {
  const calls = []
  await withFetch(async (url) => {
    calls.push(String(url))
    return okJson(JSON.parse(JSON.stringify(TURN2_DOC)))
  }, async () => {
    await ws.openForExchange('ex-1002')
    const shownBefore = ws.shown
    calls.length = 0
    ws.beginLive('u3', 'sess')
    ws.bindExchange('u3', 'ex-1003')
    ws.onLiveEvent('u3', { type: 'generated_sql', sqlId: 's1q1', sql: 'SELECT chat', success: true })
    assert.equal(ws.shown, shownBefore)
    await ws.endLive('u3', 'done')
    assert.equal(ws.open, true)
    assert.equal(ws.shown, shownBefore)
    assert.equal(ws.exchangeId, 'ex-1002')
    assert.equal(ws.shown.error, '')
    assert.equal(ws.shown.loading, false)
    assert.equal(calls.length, 0) // GET /workspace of ex-1003 (404) is never requested
    assert.equal(ws.hasContent('ex-1003'), false) // no Studio button on that answer
    assert.equal(ws.unseenExchangeId, null)
    assert.equal(ws.studioExchangeId(), 'ex-1002') // the next turn still points at it
  })
})
