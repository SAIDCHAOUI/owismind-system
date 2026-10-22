// "Go further" next steps (workspace op suggest.set) - run with `node --test`.
// Shared fixture contracts/fixtures/workspace_suggestions_cases.json pins this reducer
// against the backend one (skipped with a clear message while it is absent); inline
// cases cover the frontend-only rules (sanitize, Studio guard, chip send rule) and the
// REAL Pinia workspace store (live op + reload from GET /workspace, fetch stubbed).
import { test, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { existsSync, readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CAPS, normalizeWorkspaceOp, reduceWorkspace, applyWorkspaceEvent, emptyWorkspace,
  sanitizeWorkspace, hasWorkspaceContent, workspaceSuggestions, suggestionItems,
  studioShouldOpen,
} from '../src/composables/workspaceModel.js'
import { canPickSuggestion, sendSuggestion } from '../src/composables/suggestionChips.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const FIXTURE = resolve(HERE, '../../contracts/fixtures/workspace_suggestions_cases.json')
const fixture = existsSync(FIXTURE) ? JSON.parse(readFileSync(FIXTURE, 'utf8')) : null
const SKIP = fixture ? false : 'shared fixture contracts/fixtures/workspace_suggestions_cases.json not found (backend not delivered yet)'

function ev(seq, op, payload) {
  return { type: 'workspace', v: 1, op, seq, ...payload }
}
const SUGGEST = ev(1, 'suggest.set', { items: ['Comparer 2026 au budget mois par mois', 'Voir la repartition par offre'] })

// --- shared fixture ---------------------------------------------------------------------

test('fixture limits mirror the frontend caps', { skip: SKIP }, () => {
  for (const [k, v] of Object.entries(fixture.limits)) assert.equal(CAPS[k], v, k)
})

test('fixture normalize cases (protocol.normalize_op parity)', { skip: SKIP }, () => {
  assert.ok(fixture.normalize_cases.length > 0)
  for (const c of fixture.normalize_cases) {
    const out = normalizeWorkspaceOp(c.input, c.default_ts)
    assert.deepEqual(out, c.expected, c.name)
    if (c.expected) assert.deepEqual(normalizeWorkspaceOp(c.expected, null), c.expected, c.name + ' (idempotent)')
  }
})

test('fixture reducer cases (reducer parity, Studio-open rule)', { skip: SKIP }, () => {
  assert.ok(fixture.reducer_cases.length > 0)
  for (const c of fixture.reducer_cases) {
    const state = reduceWorkspace(c.events)
    if (c.expected) assert.deepEqual(state, c.expected, c.name)
    if (c.expected_suggestions === null) assert.equal('suggestions' in state, false, c.name + ' key absent')
    else if (c.expected_suggestions !== undefined) assert.deepEqual(state.suggestions, c.expected_suggestions, c.name)
    if (typeof c.opens_studio === 'boolean') assert.equal(hasWorkspaceContent(state), c.opens_studio, c.name + ' opens_studio')
    // The served state of the same run survives the read projection unchanged.
    if (c.expected) assert.deepEqual(sanitizeWorkspace(c.expected), c.expected, c.name + ' sanitize')
  }
})

// --- inline reducer rules ------------------------------------------------------------------

test('suggest.set: key absent until a valid op, last valid op wins, invalid op dropped', () => {
  const s = emptyWorkspace('ex-1')
  assert.equal('suggestions' in s, false)
  assert.deepEqual(workspaceSuggestions(s), [])
  assert.equal(applyWorkspaceEvent(s, SUGGEST), true)
  assert.deepEqual(s.suggestions, SUGGEST.items)
  assert.equal(applyWorkspaceEvent(s, ev(2, 'suggest.set', { items: ['short', 42] })), false)
  assert.deepEqual(s.suggestions, SUGGEST.items)
  assert.equal(applyWorkspaceEvent(s, ev(3, 'suggest.set', { items: ['  Voir le detail par client  '] })), true)
  assert.deepEqual(s.suggestions, ['Voir le detail par client'])
  // A replayed seq changes nothing.
  assert.equal(applyWorkspaceEvent(s, ev(3, 'suggest.set', { items: ['Autre suggestion valide'] })), false)
  assert.deepEqual(s.summary, { widget_ids_by_step: {}, sql_ids: [] })
})

test('suggestionItems: bounds in code points, dropped not truncated, dedupe, first 3 valid', () => {
  const long = 'x'.repeat(CAPS.suggestion_max_chars + 1)
  assert.deepEqual(suggestionItems(['1234567', '12345678', long, 'x'.repeat(120)]), ['12345678', 'x'.repeat(120)])
  // 8 code points but 16 UTF-16 units: accepted (the backend counts code points).
  const astral = '\u{1D400}'.repeat(8)
  assert.deepEqual(suggestionItems([astral]), [astral])
  assert.deepEqual(suggestionItems(['Voir  par OFFRE', 'voir par offre', ' Voir par offre ']), ['Voir  par OFFRE'])
  assert.deepEqual(suggestionItems(['too', 'Premiere idee', 'Deuxieme idee', 'Troisieme idee', 'Quatrieme idee']),
    ['Premiere idee', 'Deuxieme idee', 'Troisieme idee'])
  assert.deepEqual(suggestionItems('Pas une liste'), [])
  assert.deepEqual(suggestionItems(null), [])
})

test('suggestions never open the Studio and are not carried', () => {
  const s = reduceWorkspace([SUGGEST])
  assert.equal(hasWorkspaceContent(s), false)
  assert.equal(studioShouldOpen({ armed: true, dismissed: false, onScreen: false, widgets: s.widgets.length }), false)
  const carried = reduceWorkspace([
    SUGGEST,
    ev(2, 'studio.carry', { base_exchange_id: 'ex-0', widgets: [{ id: 'w1', kind: 'text', title: 'T', text: 'Body', origin: 'ex-0', suggestions: ['Ne doit pas passer'] }] }),
  ])
  assert.deepEqual(carried.suggestions, SUGGEST.items)
  assert.equal('suggestions' in carried.widgets[0], false)
})

test('sanitize keeps valid stored suggestions and drops a corrupt list', () => {
  const doc = { ...emptyWorkspace('ex-1'), status: 'done', suggestions: ['Voir la tendance mensuelle', 'x', 'Voir la tendance  MENSUELLE'] }
  assert.deepEqual(sanitizeWorkspace(doc).suggestions, ['Voir la tendance mensuelle'])
  const bad = sanitizeWorkspace({ ...emptyWorkspace('ex-1'), status: 'done', suggestions: ['bad', 7] })
  assert.equal('suggestions' in bad, false)
})

// --- chip send rule ------------------------------------------------------------------------

function fakeChat(over) {
  const sent = []
  return { canSend: true, sending: false, send: (t) => sent.push(t), sent, ...over }
}

test('a chip sends its text through chat.send, never while a run is in progress', () => {
  const chat = fakeChat()
  assert.equal(canPickSuggestion(chat), true)
  assert.equal(sendSuggestion(chat, '  Voir la repartition par offre '), true)
  assert.deepEqual(chat.sent, ['Voir la repartition par offre'])
  const busy = fakeChat({ sending: true, canSend: false })
  assert.equal(canPickSuggestion(busy), false)
  assert.equal(sendSuggestion(busy, 'Voir la repartition par offre'), false)
  assert.deepEqual(busy.sent, [])
  const blocked = fakeChat({ canSend: false })
  assert.equal(sendSuggestion(blocked, 'Voir la repartition par offre'), false)
  assert.equal(sendSuggestion(fakeChat(), '   '), false)
  assert.equal(sendSuggestion(null, 'Voir la repartition par offre'), false)
})

// --- real workspace store ------------------------------------------------------------------

globalThis.window = globalThis.window || {}
const realSetInterval = globalThis.setInterval
globalThis.setInterval = (fn, ms, ...args) => {
  const handle = realSetInterval(fn, ms, ...args)
  if (handle && typeof handle.unref === 'function') handle.unref()
  return handle
}
const { createPinia, setActivePinia } = await import('pinia')
const { useWorkspaceStore } = await import('../src/stores/workspace.js')

let ws
let served
const realFetch = globalThis.fetch
beforeEach(() => {
  setActivePinia(createPinia())
  ws = useWorkspaceStore()
  served = null
  globalThis.window.getWebAppBackendUrl = (p) => 'http://test' + p
  globalThis.fetch = async () => ({ ok: true, json: async () => served })
})
test.after(() => {
  globalThis.fetch = realFetch
})

test('store: live suggest.set feeds the answer, never opens the Studio', async () => {
  ws.beginLive('u1')
  ws.onLiveEvent('u1', SUGGEST)
  assert.deepEqual(ws.suggestionsFor(null, 'u1'), SUGGEST.items)
  assert.equal(ws.open, false)
  ws.bindExchange('u1', 'ex-1')
  assert.equal(ws.suggestionsOnly('ex-1', 'u1'), false) // still running
  await ws.endLive('u1', 'done')
  assert.equal(ws.open, false)
  assert.equal(ws.hasContent('ex-1', 'u1'), false)
  assert.equal(ws.suggestionsOnly('ex-1', 'u1'), true)
  // "Open the Studio" on such an answer opens nothing (the caller falls back).
  assert.equal(await ws.openForExchange('ex-1', { uid: 'u1' }), false)
  assert.equal(ws.open, false)
})

test('store: reload restores the suggestions from GET /workspace without opening the Studio', async () => {
  served = { workspace: { ...emptyWorkspace('ex-9'), status: 'done', last_seq: 1, suggestions: SUGGEST.items } }
  assert.equal(await ws.loadForExchange('ex-9'), false)
  assert.deepEqual(ws.suggestionsFor('ex-9'), SUGGEST.items)
  assert.equal(ws.open, false)
  assert.equal(ws.suggestionsOnly('ex-9'), true)
})

test('store: an open request on a suggestions-only document closes the panel', async () => {
  served = { workspace: { ...emptyWorkspace('ex-7'), status: 'done', last_seq: 1, suggestions: SUGGEST.items } }
  assert.equal(await ws.openForExchange('ex-7'), false)
  assert.equal(ws.open, false)
  assert.deepEqual(ws.suggestionsFor('ex-7'), SUGGEST.items)
  assert.equal(ws.suggestionsOnly('ex-7'), true)
})

test('store: a Studio with widgets still opens and also carries its suggestions', async () => {
  served = {
    workspace: {
      ...emptyWorkspace('ex-5'), status: 'done', last_seq: 2, suggestions: SUGGEST.items,
      widgets: [{ id: 'w1', kind: 'text', title: 'T', text: 'Body' }],
    },
  }
  assert.equal(await ws.openForExchange('ex-5'), true)
  assert.equal(ws.open, true)
  assert.deepEqual(ws.suggestionsFor('ex-5'), SUGGEST.items)
  assert.equal(ws.suggestionsOnly('ex-5'), false)
})

test('store: seeded row suggestions show without a document, the live/restored state wins', async () => {
  ws.seedSuggestions('ex-3', ['Voir le detail par client', 'court', 'voir le DETAIL par client'])
  assert.deepEqual(ws.suggestionsFor('ex-3'), ['Voir le detail par client'])
  // A seed is not a loaded document: the Studio rules are untouched.
  assert.equal(ws.suggestionsOnly('ex-3'), false)
  assert.equal(ws.hasContent('ex-3'), false)
  served = { workspace: { ...emptyWorkspace('ex-3'), status: 'done', last_seq: 1, suggestions: ['Comparer au budget annuel'] } }
  await ws.loadForExchange('ex-3')
  assert.deepEqual(ws.suggestionsFor('ex-3'), ['Comparer au budget annuel'])
  ws.seedSuggestions('ex-4', 'not a list')
  assert.deepEqual(ws.suggestionsFor('ex-4'), [])
  assert.deepEqual(ws.suggestionsFor(null), [])
})

