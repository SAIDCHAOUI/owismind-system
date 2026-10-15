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
  CHART_STYLES, BINDINGS, RUN_STATUSES, TOOLS, SQL_ID_RE, SLUG_RE, PROTOCOL_VERSION,
  normalizeWorkspaceOp, applyWorkspaceEvent, reduceWorkspace, emptyWorkspace,
  finalizeWorkspace, sanitizeWorkspace, hasWorkspaceContent, planProgress,
  stepsWithProgress, journalGroups, widgetsByStep, boardLayout, stepFor,
  provenanceFor, chartSpecForArtifact,
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
  }
  for (const [k, v] of Object.entries(contract.enums)) assert.deepEqual([...enums[k]], v, 'enum ' + k)
  assert.deepEqual(Object.keys(enums).sort(), Object.keys(contract.enums).sort())
  assert.equal(SQL_ID_RE.source, contract.patterns.sql_id)
  assert.equal(SLUG_RE.source, contract.patterns.slug)
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
