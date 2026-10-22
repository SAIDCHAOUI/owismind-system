// Workspace reducer (V2) - run with `node --test`. The SAME shared fixtures pin the
// backend reducer (python-lib/owismind/workspace) and this one: contract constants
// read from disk, normalization cases, reducer edge cases and full runs (raw chunks ->
// normalized events -> reduced state).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, readdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import {
  CAPS, OPS, PLAN_ORIGINS, STEP_STATUSES, NOTE_KINDS, WIDGET_KINDS, CHART_TYPES,
  CHART_STYLES, BINDINGS, RUN_STATUSES, TOOLS, WIDGET_SIZES, TEXT_ROLES, SQL_ID_RE, SLUG_RE, PROTOCOL_VERSION,
  normalizeWorkspaceOp, applyWorkspaceEvent, reduceWorkspace, emptyWorkspace,
  finalizeWorkspace, sanitizeWorkspace, hasWorkspaceContent, planProgress,
  stepsWithProgress, journalGroups, widgetsByStep, boardLayout, stepFor,
  provenanceFor, chartSpecForArtifact, EXCHANGE_ID_RE, normalizeCarryOp, resultRef,
  sameResult, studioContextId, withStudioContext,
} from '../src/composables/workspaceModel.js'

const HERE = dirname(fileURLToPath(import.meta.url))
const CONTRACTS = resolve(HERE, '../../contracts')
const FIXTURES = resolve(CONTRACTS, 'fixtures')
const readJson = (p) => JSON.parse(readFileSync(p, 'utf8'))
const contract = readJson(resolve(CONTRACTS, 'workspace_protocol.v1.json'))

// --- contract parity ----------------------------------------------------------------

test('constants mirror the contract file (version, caps, enums, patterns)', () => {
  assert.equal(PROTOCOL_VERSION, contract.version)
  assert.deepEqual({ ...CAPS }, contract.caps)
  const enums = {
    ops: OPS, plan_origins: PLAN_ORIGINS, step_statuses: STEP_STATUSES, note_kinds: NOTE_KINDS,
    widget_kinds: WIDGET_KINDS, chart_types: CHART_TYPES, chart_styles: CHART_STYLES,
    bindings: BINDINGS, run_statuses: RUN_STATUSES, tools: TOOLS,
    widget_sizes: WIDGET_SIZES, text_roles: TEXT_ROLES,
  }
  for (const [k, v] of Object.entries(contract.enums)) assert.deepEqual([...enums[k]], v, 'enum ' + k)
  assert.deepEqual(Object.keys(enums).sort(), Object.keys(contract.enums).sort())
  assert.equal(SQL_ID_RE.source, contract.patterns.sql_id)
  assert.equal(SLUG_RE.source, contract.patterns.slug)
  assert.equal(EXCHANGE_ID_RE.source, contract.patterns.exchange_id)
})

// --- shared fixtures ------------------------------------------------------------------

test('normalization cases (protocol.normalize_op parity)', () => {
  const { cases } = readJson(resolve(FIXTURES, 'workspace_normalize_cases.json'))
  assert.ok(cases.length > 0)
  for (const c of cases) {
    assert.deepEqual(normalizeWorkspaceOp(c.input, c.default_ts), c.expected, c.name)
  }
})

test('normalization is idempotent', () => {
  const { cases } = readJson(resolve(FIXTURES, 'workspace_normalize_cases.json'))
  for (const c of cases) {
    if (!c.expected) continue
    assert.deepEqual(normalizeWorkspaceOp(c.expected, null), c.expected, c.name)
  }
})

test('reducer edge cases (reducer.reduce_events parity)', () => {
  const { cases } = readJson(resolve(FIXTURES, 'workspace_reducer_edge_cases.json'))
  assert.ok(cases.length > 0)
  for (const c of cases) assert.deepEqual(reduceWorkspace(c.events), c.expected, c.name)
})

const RUNS = readdirSync(FIXTURES).filter((f) => /^workspace_run_.*\.json$/.test(f))

test('run fixtures exist', () => {
  assert.ok(RUNS.length >= 3, 'expected the 3 run fixtures, found ' + RUNS.length)
})

for (const file of RUNS) {
  const run = readJson(resolve(FIXTURES, file))
  const reduced = readJson(resolve(FIXTURES, 'reduced', file))

  test(file + ': raw WORKSPACE chunks normalize to the expected events', () => {
    const normalized = run.raw_chunks
      .filter((c) => c && c.type === 'event' && c.eventKind === 'WORKSPACE')
      .map((c) => normalizeWorkspaceOp(c.eventData, null))
      .filter(Boolean)
    // Events without their own ts are stamped by the backend chronometer: compare
    // everything else, and the ts wherever the orchestrator gave one.
    assert.equal(normalized.length, run.expected_events.length)
    normalized.forEach((evt, i) => {
      const exp = run.expected_events[i]
      const { ts: a, ...restA } = evt
      const { ts: b, ...restB } = exp
      assert.deepEqual(restA, restB, file + ' event #' + i)
      if (a !== undefined) assert.equal(a, b, file + ' ts #' + i)
    })
  })

  test(file + ': expected events reduce to the live state', () => {
    assert.deepEqual(reduceWorkspace(run.expected_events), reduced.live)
  })

  test(file + ': a replayed poll page changes nothing', () => {
    const state = reduceWorkspace(run.expected_events)
    for (const evt of run.expected_events) assert.equal(applyWorkspaceEvent(state, evt), false)
    assert.deepEqual(state, reduced.live)
  })

  test(file + ': the persisted (final) state survives the read projection', () => {
    assert.deepEqual(sanitizeWorkspace(reduced.final), reduced.final)
    const live = reduceWorkspace(run.expected_events)
    finalizeWorkspace(live, run.terminal_status)
    assert.equal(live.status, reduced.final.status)
  })
}

// --- frontend-only behavior -------------------------------------------------------------

function ev(seq, op, payload) {
  return { type: 'workspace', v: 1, op, seq, ...payload }
}
const PLAN = ev(1, 'plan.set', {
  mission: 'Mission', origin: 'model',
  steps: [{ id: 'p1', label: 'One', total: 4, unit: 'comptes' }, { id: 'p2', label: 'Two' }],
})

test('non-workspace events are ignored and sanitize rejects a non-v1 document', () => {
  const s = emptyWorkspace('ex-1')
  assert.equal(applyWorkspaceEvent(s, { type: 'answer_delta', text: 'x' }), false)
  assert.equal(applyWorkspaceEvent(s, null), false)
  assert.equal(s.exchange_id, 'ex-1')
  assert.equal(sanitizeWorkspace({ v: 2 }), null)
  assert.equal(sanitizeWorkspace(null), null)
  assert.equal(hasWorkspaceContent(s), false)
})

test('selectors: progress, steps, journal groups, board layout', () => {
  const s = reduceWorkspace([
    PLAN,
    ev(2, 'plan.step', { step_id: 'p1', status: 'done', done: 4 }),
    ev(3, 'note.add', { id: 'n1', step_id: 'p1', kind: 'find', title: 'A', sql_id: 's1q1' }),
    ev(4, 'note.add', { id: 'n2', kind: 'note', title: 'Off plan' }),
    ev(5, 'note.add', { id: 'n3', step_id: 'zz', kind: 'note', title: 'Removed step' }),
    ev(6, 'widget.add', { id: 'w1', step_id: 'p1', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'L', value: 'v' } }),
    ev(7, 'widget.add', { id: 'w2', step_id: 'p2', kind: 'chart', title: 'C', sql_id: 's2q1', chart: { type: 'donut', x: 'a', y: ['b'] } }),
    ev(8, 'prov.set', { sql_id: 's1q1', agent_key: 'revenue', tool: 'semantic-model-query', success: true, row_count: 3 }),
  ])
  assert.ok(hasWorkspaceContent(s))
  assert.deepEqual(planProgress(s), { done: 1, total: 2, pct: 50 })
  const steps = stepsWithProgress(s)
  assert.equal(steps[0].index, 1)
  assert.equal(steps[0].hasBatch, true)
  assert.equal(steps[0].batchPct, 100)
  assert.equal(steps[0].notes, 1)
  assert.equal(steps[0].widgets, 1)
  assert.equal(steps[1].hasBatch, false)
  const groups = journalGroups(s)
  assert.deepEqual(groups.map((g) => g.key), ['step-p1', 'step-p2', 'other'])
  assert.equal(groups[2].notes.length, 2)
  assert.equal(groups[2].removed, true)
  assert.equal(groups[0].widgets, 1)
  const layout = boardLayout(s)
  assert.deepEqual(layout.kpis.map((w) => w.id), ['w1'])
  assert.deepEqual(layout.others.map((w) => w.id), ['w2'])
  assert.deepEqual(Object.keys(widgetsByStep(s)).sort(), ['p1', 'p2'])
  assert.equal(stepFor(s, 'p2').index, 2)
  assert.equal(stepFor(s, 'nope'), null)
  assert.equal(provenanceFor(s, s.widgets[0]).row_count, 3)
  assert.equal(provenanceFor(s, s.widgets[1]), null)
})

test('chartSpecForArtifact maps donut onto the pie renderer', () => {
  assert.deepEqual(chartSpecForArtifact({ type: 'donut', x: 'a', y: ['b'] }), { type: 'pie', style: 'donut', x: 'a', y: ['b'] })
  const bar = { type: 'bar', x: 'a', y: ['b'] }
  assert.equal(chartSpecForArtifact(bar), bar)
  assert.equal(chartSpecForArtifact(null), null)
})

test('a data widget without sql_id never enters the state (decision D2)', () => {
  const s = reduceWorkspace([ev(1, 'widget.add', { id: 'w1', kind: 'table', title: 'T' })])
  assert.equal(s.widgets.length, 0)
  assert.equal(s.last_seq, 0)
})

// --- Data tab focus (sql_id) ------------------------------------------------------------

import { dataFocus, filterParts } from '../src/composables/workspaceModel.js'

test('layout hints: size kept on chart / table, role on text, invalid values dropped', () => {
  const chart = { type: 'bar', x: 'a', y: ['b'] }
  const op = (seq, w) => ({ v: PROTOCOL_VERSION, op: 'widget.add', seq, ...w })
  const s = reduceWorkspace([
    op(1, { id: 'c1', kind: 'chart', title: 'C', sql_id: 's1q1', chart, size: 'wide' }),
    op(2, { id: 'tb', kind: 'table', title: 'T', sql_id: 's1q1', size: 'normal' }),
    op(3, { id: 'c2', kind: 'chart', title: 'C2', sql_id: 's1q1', chart, size: 'huge', role: 'scope' }),
    op(4, { id: 'k1', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'K', value: 'v' }, size: 'wide' }),
    op(5, { id: 'sc', kind: 'text', title: 'Scope', text: 'x', role: 'scope', size: 'wide' }),
    op(6, { id: 'tx', kind: 'text', title: 'Sec', text: 'y', role: 'summary' }),
    op(7, { id: 'old', kind: 'text', title: 'Old', text: 'z' }),
  ])
  const by = Object.fromEntries(s.widgets.map((w) => [w.id, w]))
  assert.equal(by.c1.size, 'wide')
  assert.equal(by.tb.size, 'normal')
  assert.equal('size' in by.c2, false)
  assert.equal('role' in by.c2, false)
  assert.equal('size' in by.k1, false)
  assert.equal(by.sc.role, 'scope')
  assert.equal('size' in by.sc, false)
  assert.equal('role' in by.tx, false)
  assert.equal('role' in by.old, false)
  // A stored document keeps the valid hints and drops the rest (same rules).
  const doc = JSON.parse(JSON.stringify({ ...s, v: PROTOCOL_VERSION }))
  doc.widgets.find((w) => w.id === 'tx').role = 'section'
  doc.widgets.find((w) => w.id === 'old').size = 'wide'
  const back = sanitizeWorkspace(doc)
  const b = Object.fromEntries(back.widgets.map((w) => [w.id, w]))
  assert.equal(b.c1.size, 'wide')
  assert.equal(b.sc.role, 'scope')
  assert.equal(b.tx.role, 'section')
  assert.equal('size' in b.old, false)
})

test('dataFocus: the widget opened from, else the first widget on that sql_id', () => {
  const s = reduceWorkspace([
    PLAN,
    ev(2, 'widget.add', { id: 'w1', step_id: 'p2', kind: 'table', title: 'T1', sql_id: 's2q1' }),
    ev(3, 'widget.add', { id: 'w2', step_id: 'p1', kind: 'chart', title: 'C', sql_id: 's2q1', chart: { type: 'bar', x: 'a', y: ['b'] } }),
    ev(4, 'prov.set', { sql_id: 's2q1', agent_key: 'tickets', tool: 'semantic-model-query', success: true, step_id: 'p2' }),
  ])
  const f = dataFocus(s, 's2q1', 'w2')
  assert.equal(f.widget.id, 'w2')
  assert.equal(f.step.index, 1)
  assert.equal(f.provenance.agent_key, 'tickets')
  assert.equal(dataFocus(s, 's2q1', 'nope').widget.id, 'w1')
  assert.equal(dataFocus(s, 's2q1', 'w1').step.index, 2)
  // Unknown result or missing input: no focus (stale focus never shows other rows).
  assert.equal(dataFocus(s, 's9q9', 'w1'), null)
  assert.equal(dataFocus(s, null), null)
  assert.equal(dataFocus(null, 's2q1'), null)
})

test('filterParts: explainer steps go through the step wording, chips get a business column name, strings stay literal', () => {
  const stepArgs = (f) => ({ key: 'ev.exp.' + f.kind, args: f.params.map(String) })
  assert.deepEqual(filterParts({ kind: 'filter_eq', params: ['Year', 2026] }, stepArgs), { key: 'ev.exp.filter_eq', args: ['Year', '2026'] })
  assert.deepEqual(filterParts({ column: 'Phase', op: 'IN', values: ['A', 'B'] }, stepArgs), { text: 'Phase : A, B' })
  assert.deepEqual(filterParts({ column: 'x', op: '>=', values: [3] }, stepArgs), { text: 'X >= 3' })
  assert.deepEqual(filterParts({ column: 'revenue_month', op: '=', values: ['2026-01'] }, stepArgs), { text: 'Revenue month : 2026-01' })
  assert.deepEqual(filterParts('Year = 2026', stepArgs), { text: 'Year = 2026' })
  assert.equal(filterParts({ kind: 'group', params: ['a'] }, stepArgs), null)
  assert.equal(filterParts(null, stepArgs), null)
  assert.equal(filterParts('', stepArgs), null)
})

import { agentLabelKey, resultLabel } from '../src/composables/workspaceModel.js'

test('plain labels: expert names and result names, never an id', () => {
  assert.equal(agentLabelKey('revenue'), 'ws.agent.revenue')
  assert.equal(agentLabelKey('SalesDrive_revenue_expert'), 'ws.agent.revenue')
  assert.equal(agentLabelKey('CSSO_Trouble_Tickets_Expert'), 'ws.agent.tickets')
  assert.equal(agentLabelKey(''), 'ws.agent.generic')
  assert.equal(resultLabel({ widgets: ['Revenus par pays'], stepLabel: 'Step' }), 'Revenus par pays')
  assert.equal(resultLabel({ widgets: [], stepLabel: 'Incidents ouverts' }), 'Incidents ouverts')
  assert.equal(resultLabel({ widgets: [] }), null)
  assert.equal(resultLabel(null), null)
})

// --- Studio panel decisions ---------------------------------------------------------

import { studioShouldOpen, studioCloseEffect, dataTabView } from '../src/composables/workspaceModel.js'

test('studioShouldOpen: first widget opens, then never again unless re-armed; dismissed always blocks', () => {
  // First published widget of the run.
  assert.equal(studioShouldOpen({ armed: true, dismissed: false, onScreen: false, widgets: 1 }), true)
  // Already opened for this run (disarmed): later widgets only appear on the board.
  assert.equal(studioShouldOpen({ armed: false, dismissed: false, onScreen: false, widgets: 2 }), false)
  // The user closed it during the run.
  assert.equal(studioShouldOpen({ armed: true, dismissed: true, onScreen: false, widgets: 3 }), false)
  // Already showing this run, or nothing to show.
  assert.equal(studioShouldOpen({ armed: true, dismissed: false, onScreen: true, widgets: 1 }), false)
  assert.equal(studioShouldOpen({ armed: true, dismissed: false, onScreen: false, widgets: 0 }), false)
  assert.equal(studioShouldOpen(null), false)
})

test('studioCloseEffect: only an explicit user close is sticky for a live run', () => {
  assert.equal(studioCloseEffect({ running: true, byUser: true }), 'dismiss')
  assert.equal(studioCloseEffect({ running: true, byUser: false }), 'rearm')
  assert.equal(studioCloseEffect({ running: true }), 'rearm')
  assert.equal(studioCloseEffect({ running: false, byUser: true }), null)
  assert.equal(studioCloseEffect(null), null)
})

test('dataTabView: degraded meta falls back to the rows the Studio captured', () => {
  const rows = new Set(['s1q1', 's2q1'])
  const hasRows = (sid) => rows.has(sid)
  const degraded = { available: false, reason: 'no_matching_dataset', sql_id: 's1q1' }
  // Focused on a result whose rows the Studio holds: the rows, flagged unverified.
  assert.deepEqual(
    dataTabView({ focusSqlId: 's1q1', meta: degraded, activeSqlId: 's1q1', hasRows }),
    { mode: 'focus', sqlId: 's1q1', unverified: true },
  )
  // Focused, degraded, no captured rows: the Evidence panel keeps its honest message.
  assert.equal(dataTabView({ focusSqlId: 's9q9', meta: degraded, activeSqlId: 's9q9', hasRows }).mode, 'evidence')
  // No focus (Data tab clicked): the active result's rows, else the first with rows.
  assert.deepEqual(
    dataTabView({ meta: degraded, activeSqlId: 's2q1', candidates: ['s1q1', 's2q1'], hasRows }),
    { mode: 'focus', sqlId: 's2q1', unverified: true },
  )
  assert.deepEqual(
    dataTabView({ meta: { available: false }, activeSqlId: null, candidates: ['s3q1', 's1q1'], hasRows }),
    { mode: 'focus', sqlId: 's1q1', unverified: true },
  )
  assert.equal(dataTabView({ meta: degraded, activeSqlId: 's9q9', candidates: [], hasRows }).mode, 'evidence')
})

test('dataTabView: available meta keeps the previous behaviour (unscoped focus only)', () => {
  const hasRows = () => true
  const scoped = { available: true, sql_id: 's1q1' }
  assert.equal(dataTabView({ focusSqlId: 's1q1', meta: scoped, activeSqlId: 's1q1', hasRows }).mode, 'evidence')
  // Older backend: the view is not scoped to the focused query.
  assert.deepEqual(
    dataTabView({ focusSqlId: 's2q1', meta: { available: true }, activeSqlId: null, hasRows }),
    { mode: 'focus', sqlId: 's2q1', unverified: false },
  )
  assert.equal(dataTabView({ meta: scoped, activeSqlId: 's1q1', hasRows }).mode, 'evidence')
  // Meta unknown or loading: the Evidence panel (and its skeleton) decides.
  assert.equal(dataTabView({ focusSqlId: 's1q1', meta: null, hasRows }).mode, 'evidence')
  assert.equal(dataTabView({ focusSqlId: 's1q1', meta: scoped, loading: true, hasRows }).mode, 'evidence')
})

import { resultHasRows } from '../src/composables/workspaceModel.js'

test('resultHasRows: an empty capture is no data (the Data tab keeps the Evidence panel)', () => {
  assert.equal(resultHasRows({ captured: true, columns: ['a'], rows: [[1]] }), true)
  assert.equal(resultHasRows({ captured: true, columns: ['a'], rows: [] }), false)
  assert.equal(resultHasRows({ captured: true, columns: ['a'] }), false)
  assert.equal(resultHasRows(null), false)
  const hasRows = (sid) => resultHasRows({ s1q1: { rows: [] } }[sid])
  assert.equal(dataTabView({ focusSqlId: 's1q1', meta: { available: false }, activeSqlId: 's1q1', hasRows }).mode, 'evidence')
})

// --- Studio continuity (studio.continue / studio.carry / widget.remove / replaces) ----

const CONTINUITY = readJson(resolve(FIXTURES, 'workspace_continuity_cases.json'))

test('continuity normalization cases (protocol.normalize_op parity)', () => {
  assert.ok(CONTINUITY.normalize_cases.length > 0)
  for (const c of CONTINUITY.normalize_cases) {
    assert.deepEqual(normalizeWorkspaceOp(c.input, c.default_ts), c.expected, c.name)
  }
})

test('continuity reducer cases (reducer parity: carry, remove, replaces, summary skip)', () => {
  assert.ok(CONTINUITY.reducer_cases.length > 0)
  for (const c of CONTINUITY.reducer_cases) assert.deepEqual(reduceWorkspace(c.events), c.expected, c.name)
})

const CARRY = {
  type: 'workspace', v: 1, op: 'studio.carry', seq: 1, base_exchange_id: 'ex-a',
  widgets: [
    { id: 'w1', kind: 'chart', title: 'CA', step_id: 'p1', sql_id: 's1q1', chart: { type: 'line', x: 'm', y: ['v'] }, size: 'wide', origin: 'ex-a', binding: 'explicit' },
    { id: 's1', kind: 'text', title: 'Scope', text: 'Perimetre', role: 'scope', origin: 'ex-a' },
  ],
}

test('a carry prepends the base widgets (origin kept, step dropped) before this run and sets the base', () => {
  const own = { type: 'workspace', v: 1, op: 'widget.add', seq: 2, id: 'w3', kind: 'chart', title: '2025', sql_id: 's1q1', chart: { type: 'bar', x: 'm', y: ['v'] } }
  const st = reduceWorkspace([CARRY, own])
  assert.equal(st.base_exchange_id, 'ex-a')
  assert.deepEqual(st.widgets.map((w) => [w.id, w.origin || null]), [['w1', 'ex-a'], ['s1', 'ex-a'], ['w3', null]])
  assert.equal(st.widgets[0].step_id, undefined)
  assert.equal(st.widgets[0].size, 'wide')
  // Only THIS run's s1q1 is in the summary (the carried one belongs to ex-a).
  assert.deepEqual(st.summary.sql_ids, ['s1q1'])
  // The carry never goes through the agent-stream normalizer.
  assert.equal(normalizeWorkspaceOp(CARRY), null)
  assert.equal(normalizeCarryOp(CARRY).widgets.length, 2)
  assert.equal(normalizeCarryOp({ ...CARRY, base_exchange_id: 'bad id!' }), null)
})

test('remove drops a carried widget; replaces swaps one in place', () => {
  const rm = { type: 'workspace', v: 1, op: 'widget.remove', seq: 2, id: 's1' }
  const rep = { type: 'workspace', v: 1, op: 'widget.add', seq: 3, id: 'w4', replaces: 'w1', kind: 'chart', title: 'New', sql_id: 's1q2', chart: { type: 'bar', x: 'm', y: ['v'] } }
  const st = reduceWorkspace([CARRY, { ...CARRY, seq: 2, op: 'widget.add', id: 'w2', kind: 'kpi', title: 'K', sql_id: 's1q1', kpi: { label: 'L', value: 'v' } }, { ...rm, seq: 3 }, { ...rep, seq: 4 }])
  assert.deepEqual(st.widgets.map((w) => w.id), ['w4', 'w2'])
  assert.equal(st.widgets[0].replaces, undefined)
  assert.equal(st.widgets[0].origin, undefined)
})

test('sanitize keeps the base id and the widget origins (pattern-checked)', () => {
  const doc = reduceWorkspace([CARRY])
  doc.status = 'done'
  const clean = sanitizeWorkspace(JSON.parse(JSON.stringify(doc)))
  assert.equal(clean.base_exchange_id, 'ex-a')
  assert.deepEqual(clean.widgets.map((w) => w.origin), ['ex-a', 'ex-a'])
  const forged = JSON.parse(JSON.stringify(doc))
  forged.base_exchange_id = '../x'
  forged.widgets[0].origin = 'a b'
  const out = sanitizeWorkspace(forged)
  assert.equal(out.base_exchange_id, undefined)
  assert.equal(out.widgets[0].origin, undefined)
  // An old document (no continuity fields) is unchanged.
  assert.equal(sanitizeWorkspace({ v: 1, status: 'done', widgets: [] }).base_exchange_id, undefined)
})

test('resultRef keys a result by (owning exchange, sql_id), never by sql_id alone', () => {
  const carried = { id: 'w1', sql_id: 's1q1', origin: 'ex-a' }
  const own = { id: 'w3', sql_id: 's1q1' }
  const a = resultRef(carried, 'ex-b')
  const b = resultRef(own, 'ex-b')
  assert.deepEqual(a, { origin: 'ex-a', exchangeId: 'ex-a', sqlId: 's1q1', key: 'ex-a|s1q1' })
  assert.deepEqual(b, { origin: null, exchangeId: 'ex-b', sqlId: 's1q1', key: 'ex-b|s1q1' })
  assert.notEqual(a.key, b.key)
  assert.equal(sameResult(a, b), false)
  assert.equal(sameResult(b, resultRef({ sql_id: 's1q1' }, 'ex-b')), true)
  assert.equal(resultRef({ id: 't' }, 'ex-b'), null)
  // A live run without its exchange id yet still has a usable (own) ref.
  assert.equal(resultRef(own, null).exchangeId, null)
})

test('dataFocus resolves a carried result on its origin (no step, no local provenance)', () => {
  const st = reduceWorkspace([
    CARRY,
    { type: 'workspace', v: 1, op: 'plan.set', seq: 2, mission: 'M', origin: 'model', steps: [{ id: 'p1', label: 'One' }] },
    { type: 'workspace', v: 1, op: 'widget.add', seq: 3, id: 'w3', step_id: 'p1', kind: 'table', title: 'T', sql_id: 's1q1' },
    { type: 'workspace', v: 1, op: 'prov.set', seq: 4, sql_id: 's1q1', agent_key: 'revenue', tool: 'semantic-model-query', success: true, step_id: 'p1' },
  ])
  const carried = dataFocus(st, 's1q1', 'w1', 'ex-a')
  assert.equal(carried.widget.id, 'w1')
  assert.equal(carried.step, null)
  assert.equal(carried.provenance, null)
  const own = dataFocus(st, 's1q1', 'w1')
  assert.equal(own.widget.id, 'w3') // never the carried widget of the same sql_id
  assert.equal(own.step.id, 'p1')
  assert.ok(own.provenance)
  assert.equal(dataFocus(st, 's1q1', null, 'ex-zz'), null)
  assert.equal(provenanceFor(st, st.widgets[0]), null)
  // The plan counts only this run's widgets.
  assert.equal(stepsWithProgress(st)[0].widgets, 1)
})

test('the shown sealed Studio rides in screen_context as studio_exchange_id', () => {
  assert.equal(studioContextId({ open: true, exchangeId: 'ex-a', running: false }), 'ex-a')
  assert.equal(studioContextId({ open: true, exchangeId: 42, running: false }), '42')
  assert.equal(studioContextId({ open: false, exchangeId: 'ex-a' }), null)
  assert.equal(studioContextId({ open: true, exchangeId: 'ex-a', running: true }), null)
  assert.equal(studioContextId({ open: true, exchangeId: null }), null)
  assert.equal(studioContextId({ open: true, exchangeId: 'a b' }), null)
  assert.deepEqual(withStudioContext(undefined, 'ex-a'), { open: false, studio_exchange_id: 'ex-a' })
  const ev = { open: true, exchange_id: 'ex-a', active_tab: 'sources' }
  assert.deepEqual(withStudioContext(ev, 'ex-a'), { ...ev, studio_exchange_id: 'ex-a' })
  assert.equal(withStudioContext(ev, null), ev)
  assert.equal(withStudioContext(undefined, null), undefined)
})
