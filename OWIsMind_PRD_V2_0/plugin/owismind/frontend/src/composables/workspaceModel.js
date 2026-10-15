// Workspace model - the PURE reducer behind the V2 workspace panel (plan, journal,
// dashboard, provenance). It mirrors the backend reducer (python-lib/owismind/
// workspace/reducer.py) and the shared contract plugin/owismind/contracts/
// workspace_protocol.v1.json: the SAME function folds the live events relayed by
// /chat/poll and the events of a restored document, so a restored workspace renders
// exactly like the live one. No Vue here: unit-tested with node:test (parity of the
// constants below with the contract file is asserted by test/workspaceModel.test.js).
//
// Validation is fail-closed PER OPERATION: an invalid operation is ignored (the state
// is returned untouched), never thrown - the run keeps going. Unknown keys are dropped
// and every string is truncated to its cap, exactly like the backend's normalize_op.

import { humanizeColumn } from './evidenceProof.js'

// --- constants (mirror of the contract; parity-tested) -------------------------------

export const PROTOCOL_VERSION = 1

export const CAPS = Object.freeze({
  max_plan_steps: 10,
  max_notes: 30,
  max_widgets: 12,
  max_provenance: 24,
  max_workspace_events_per_run: 80,
  max_workspace_json_chars: 200000,
  mission_chars: 240,
  step_label_chars: 140,
  note_title_chars: 140,
  note_text_chars: 1200,
  widget_title_chars: 200,
  widget_comment_chars: 280,
  widget_text_chars: 4000,
  task_chars: 800,
  max_y_series: 8,
})

export const OPS = Object.freeze(['plan.set', 'plan.step', 'note.add', 'widget.add', 'prov.set'])
export const PLAN_ORIGINS = Object.freeze(['model', 'auto'])
export const STEP_STATUSES = Object.freeze(['todo', 'running', 'done', 'error'])
export const NOTE_KINDS = Object.freeze(['plan', 'find', 'check', 'note', 'done'])
export const WIDGET_KINDS = Object.freeze(['chart', 'table', 'kpi', 'text'])
export const CHART_TYPES = Object.freeze(['bar', 'line', 'pie', 'donut'])
export const CHART_STYLES = Object.freeze(['grouped', 'stacked', 'horizontal', 'area', 'smooth', 'stepped', 'donut'])
export const BINDINGS = Object.freeze(['explicit', 'orphan'])
export const RUN_STATUSES = Object.freeze(['running', 'done', 'stopped', 'error'])
export const TOOLS = Object.freeze(['semantic-model-query', 'attribute_lookup', 'correlate'])

export const SQL_ID_RE = /^s[0-9]+(q|lk|qc)[0-9]+$/
export const SLUG_RE = /^[a-z0-9_-]{1,32}$/

// Data widgets MUST carry a sql_id (never a fallback to "the latest result").
const DATA_KINDS = new Set(['chart', 'table', 'kpi'])

// Field caps that live in the contract $defs (not in "caps").
const STEP_UNIT_CHARS = 40
const CHART_COLUMN_CHARS = 128
const CHART_AXIS_LABEL_CHARS = 80
const UNIT_CHARS = 16
const KPI_LABEL_CHARS = 120
const KPI_COLUMN_CHARS = 128
const AGENT_KEY_CHARS = 64
const MAX_SQL_ID_CHARS = 32

// --- field projectors (pure, never throw; mirror of protocol.py) ----------------------

function isObj(v) {
  return !!v && typeof v === 'object' && !Array.isArray(v)
}
/** A real integer >= min (booleans excluded). */
function isInt(v, min) {
  return typeof v === 'number' && Number.isInteger(v) && v >= min
}
/** A trimmed string truncated to `cap`, or null when absent / blank / not a string. */
function text(v, cap) {
  if (typeof v !== 'string') return null
  const s = v.trim()
  return s ? s.slice(0, cap) : null
}
function slug(v) {
  return typeof v === 'string' && SLUG_RE.test(v) ? v : null
}
function sqlId(v) {
  return typeof v === 'string' && v.length <= MAX_SQL_ID_CHARS && SQL_ID_RE.test(v) ? v : null
}
function tsValue(v) {
  return typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null
}

function planStep(raw) {
  if (!isObj(raw)) return null
  const id = slug(raw.id)
  const label = text(raw.label, CAPS.step_label_chars)
  if (!id || !label) return null
  const out = { id, label }
  if (isInt(raw.total, 1)) out.total = raw.total
  const unit = text(raw.unit, STEP_UNIT_CHARS)
  if (unit) out.unit = unit
  return out
}

function chartSpec(raw) {
  if (!isObj(raw)) return null
  const x = text(raw.x, CHART_COLUMN_CHARS)
  let y = raw.y
  if (typeof y === 'string') y = [y]
  if (!CHART_TYPES.includes(raw.type) || !x || !Array.isArray(y)) return null
  const series = []
  for (const col of y) {
    const c = text(col, CHART_COLUMN_CHARS)
    if (c) series.push(c)
    if (series.length >= CAPS.max_y_series) break
  }
  if (!series.length) return null
  const out = { type: raw.type, x, y: series }
  if (CHART_STYLES.includes(raw.style)) out.style = raw.style
  for (const [key, cap] of [['x_label', CHART_AXIS_LABEL_CHARS], ['y_label', CHART_AXIS_LABEL_CHARS], ['unit', UNIT_CHARS]]) {
    const v = text(raw[key], cap)
    if (v) out[key] = v
  }
  return out
}

function kpiSpec(raw) {
  if (!isObj(raw)) return null
  const label = text(raw.label, KPI_LABEL_CHARS)
  const value = text(raw.value, KPI_COLUMN_CHARS)
  if (!label || !value) return null
  const out = { label, value }
  for (const key of ['delta', 'delta_pct']) {
    const c = text(raw[key], KPI_COLUMN_CHARS)
    if (c) out[key] = c
  }
  const unit = text(raw.unit, UNIT_CHARS)
  if (unit) out.unit = unit
  return out
}

// --- payload projectors, one per op ---------------------------------------------------

function planSetPayload(raw) {
  const mission = text(raw.mission, CAPS.mission_chars)
  if (mission == null || !PLAN_ORIGINS.includes(raw.origin) || !Array.isArray(raw.steps)) return null
  const steps = []
  const seen = new Set()
  for (const item of raw.steps) {
    const step = planStep(item)
    if (!step || seen.has(step.id)) continue
    seen.add(step.id)
    steps.push(step)
    if (steps.length >= CAPS.max_plan_steps) break
  }
  return steps.length ? { mission, origin: raw.origin, steps } : null
}

function planStepPayload(raw) {
  const stepId = slug(raw.step_id)
  if (!stepId) return null
  const out = { step_id: stepId }
  if (STEP_STATUSES.includes(raw.status)) out.status = raw.status
  if (isInt(raw.done, 0)) out.done = raw.done
  const add = planStep(raw.add_step)
  if (add) out.add_step = add
  // An op that changes nothing is rejected.
  return Object.keys(out).length > 1 ? out : null
}

function notePayload(raw) {
  const id = slug(raw.id)
  const title = text(raw.title, CAPS.note_title_chars)
  if (!id || !NOTE_KINDS.includes(raw.kind) || !title) return null
  const out = { id, kind: raw.kind, title }
  const body = text(raw.text, CAPS.note_text_chars)
  if (body) out.text = body
  if (slug(raw.step_id)) out.step_id = raw.step_id
  if (sqlId(raw.sql_id)) out.sql_id = raw.sql_id
  return out
}

// `binding` is never read from the input: the reducer (and the backend persistence
// step, for orphans) owns it.
function widgetPayload(raw) {
  const id = slug(raw.id)
  const title = text(raw.title, CAPS.widget_title_chars)
  if (!id || !WIDGET_KINDS.includes(raw.kind) || !title) return null
  const kind = raw.kind
  const out = { id, kind, title }
  const comment = text(raw.comment, CAPS.widget_comment_chars)
  if (comment) out.comment = comment
  if (slug(raw.step_id)) out.step_id = raw.step_id
  const bound = sqlId(raw.sql_id)
  if (DATA_KINDS.has(kind)) {
    if (!bound) return null // contract rule D2: a data widget without its sql_id is rejected
    out.sql_id = bound
  } else if (bound) {
    out.sql_id = bound
  }
  if (kind === 'chart') {
    const chart = chartSpec(raw.chart)
    if (!chart) return null
    out.chart = chart
  } else if (kind === 'kpi') {
    const kpi = kpiSpec(raw.kpi)
    if (!kpi) return null
    out.kpi = kpi
  } else if (kind === 'text') {
    const body = text(raw.text, CAPS.widget_text_chars)
    if (!body) return null
    out.text = body
  }
  return out
}

function provPayload(raw) {
  const bound = sqlId(raw.sql_id)
  const agentKey = text(raw.agent_key, AGENT_KEY_CHARS)
  if (!bound || !agentKey || !TOOLS.includes(raw.tool) || typeof raw.success !== 'boolean') return null
  const out = { sql_id: bound, agent_key: agentKey, tool: raw.tool, success: raw.success }
  const task = text(raw.task, CAPS.task_chars)
  if (task) out.task = task
  if (slug(raw.step_id)) out.step_id = raw.step_id
  for (const key of ['duration_ms', 'row_count']) {
    if (isInt(raw[key], 0)) out[key] = raw[key]
  }
  return out
}

const PAYLOAD_BY_OP = {
  'plan.set': planSetPayload,
  'plan.step': planStepPayload,
  'note.add': notePayload,
  'widget.add': widgetPayload,
  'prov.set': provPayload,
}

/**
 * One raw or already-normalized workspace operation -> the normalized event
 * {type:'workspace', v, op, seq, ts?, ...payload}, or null (fail-closed per op).
 * Mirror of protocol.normalize_op (pinned by contracts/fixtures/workspace_normalize_cases.json);
 * idempotent, never throws.
 */
export function normalizeWorkspaceOp(raw, defaultTs) {
  try {
    if (!isObj(raw)) return null
    if (!isInt(raw.v, 0) || raw.v !== PROTOCOL_VERSION) return null
    const build = PAYLOAD_BY_OP[raw.op]
    if (!build || !isInt(raw.seq, 1)) return null
    const payload = build(raw)
    if (!payload) return null
    const evt = { type: 'workspace', v: PROTOCOL_VERSION, op: raw.op, seq: raw.seq }
    let ts = tsValue(raw.ts)
    if (ts == null) ts = tsValue(defaultTs)
    if (ts != null) evt.ts = ts
    return Object.assign(evt, payload)
  } catch (e) {
    return null
  }
}

// --- state ----------------------------------------------------------------------------

/** A fresh, empty reduced state (contract `reduced_state`). */
export function emptyWorkspace(exchangeId) {
  const state = {
    v: PROTOCOL_VERSION,
    status: 'running',
    last_seq: 0,
    plan: null,
    notes: [],
    widgets: [],
    provenance: {},
    summary: { widget_ids_by_step: {}, sql_ids: [] },
  }
  if (exchangeId) state.exchange_id = String(exchangeId)
  return state
}

/** True when a state carries anything worth showing (plan, note or widget). */
export function hasWorkspaceContent(state) {
  return !!(state && (state.plan || (state.notes && state.notes.length) || (state.widgets && state.widgets.length)))
}

// Derived index: widget ids per step + every referenced sql_id (unique, in this order:
// provenance keys, then widget sql_ids, then note sql_ids).
function refreshSummary(state) {
  const byStep = {}
  for (const w of state.widgets) {
    if (!w.step_id) continue
    if (!byStep[w.step_id]) byStep[w.step_id] = []
    byStep[w.step_id].push(w.id)
  }
  const seen = new Set()
  const ids = []
  const add = (id) => {
    if (id && !seen.has(id)) {
      seen.add(id)
      ids.push(id)
    }
  }
  Object.keys(state.provenance).forEach(add)
  state.widgets.forEach((w) => add(w.sql_id))
  state.notes.forEach((n) => add(n.sql_id))
  state.summary = { widget_ids_by_step: byStep, sql_ids: ids }
}

// A plan step as stored: status todo, done 0 when a total is declared.
function newStep(step) {
  const out = { id: step.id, label: step.label, status: 'todo' }
  if (step.total != null) {
    out.total = step.total
    out.done = 0
  }
  if (step.unit != null) out.unit = step.unit
  return out
}

function entry(evt, keys) {
  const out = {}
  for (const k of keys) {
    if (evt[k] !== undefined) out[k] = JSON.parse(JSON.stringify(evt[k]))
  }
  if (evt.ts !== undefined) out.ts = evt.ts
  return out
}

const NOTE_KEYS = ['id', 'kind', 'title', 'text', 'step_id', 'sql_id']
const WIDGET_KEYS = ['id', 'kind', 'title', 'comment', 'step_id', 'sql_id', 'chart', 'kpi', 'text']
const PROV_KEYS = ['agent_key', 'tool', 'task', 'step_id', 'duration_ms', 'row_count', 'success']

const HANDLERS = {
  'plan.set'(state, evt) {
    // The first plan.set creates the plan; a later one REPLACES it (version + 1).
    // Notes and widgets keep their step_id (shown as "step removed" when it vanished).
    const version = state.plan ? state.plan.version + 1 : 1
    state.plan = { version, origin: evt.origin, mission: evt.mission, steps: evt.steps.map(newStep) }
  },
  'plan.step'(state, evt) {
    if (!state.plan) return
    const steps = state.plan.steps
    // add_step BEFORE status/done, so one op can add and start a step.
    const added = evt.add_step
    if (added && steps.length < CAPS.max_plan_steps && steps.every((s) => s.id !== added.id)) {
      steps.push(newStep(added))
    }
    const step = steps.find((s) => s.id === evt.step_id)
    if (!step) return
    if (evt.status !== undefined) step.status = evt.status
    if (evt.done !== undefined) step.done = evt.done
  },
  'note.add'(state, evt) {
    const notes = state.notes
    if (notes.length >= CAPS.max_notes || notes.some((n) => n.id === evt.id)) return
    notes.push(entry(evt, NOTE_KEYS))
  },
  'widget.add'(state, evt) {
    const widgets = state.widgets
    if (widgets.length >= CAPS.max_widgets || widgets.some((w) => w.id === evt.id)) return
    const widget = entry(evt, WIDGET_KEYS)
    if (DATA_KINDS.has(widget.kind)) widget.binding = 'explicit'
    widgets.push(widget)
  },
  'prov.set'(state, evt) {
    const prov = state.provenance
    const key = evt.sql_id
    const known = Object.prototype.hasOwnProperty.call(prov, key)
    if (!known && Object.keys(prov).length >= CAPS.max_provenance) return
    const out = {}
    for (const k of PROV_KEYS) if (evt[k] !== undefined) out[k] = evt[k]
    prov[key] = out // a known key is overwritten in place (position kept)
  },
}

/**
 * Fold ONE workspace event into `state` (mutated in place - the store hands a
 * reactive() object, so nested pushes re-render live). Same rules as the backend
 * reducer (workspace/reducer.py, pinned by the shared fixtures): the event is
 * re-normalized first; a `seq` not strictly greater than `last_seq` is a replay and is
 * ignored; an accepted event advances `last_seq` even when it is a semantic no-op.
 * Returns true when the event was accepted.
 */
export function applyWorkspaceEvent(state, raw) {
  if (!state || !isObj(raw)) return false
  if (raw.type != null && raw.type !== 'workspace') return false
  const evt = normalizeWorkspaceOp(raw)
  if (!evt || evt.seq <= (state.last_seq || 0)) return false
  state.last_seq = evt.seq
  HANDLERS[evt.op](state, evt)
  refreshSummary(state)
  return true
}

/** Replay a list of events onto a fresh state (restore path + tests). */
export function reduceWorkspace(events, exchangeId) {
  const state = emptyWorkspace(exchangeId)
  for (const evt of events || []) applyWorkspaceEvent(state, evt)
  return state
}

/** Seal the run status (run_done / stopped / error); ignores unknown statuses. */
export function finalizeWorkspace(state, status) {
  if (state && RUN_STATUSES.includes(status)) state.status = status
  return state
}

/**
 * Re-project a SERVED reduced state (GET /workspace) onto the strict contract shape:
 * defense in depth, the frontend never trusts a stored document blindly. Mirror of
 * reducer.sanitize; returns null for a document that is not a v1 workspace.
 */
export function sanitizeWorkspace(doc) {
  try {
    if (!isObj(doc) || doc.v !== PROTOCOL_VERSION) return null
    const state = emptyWorkspace()
    state.status = RUN_STATUSES.includes(doc.status) ? doc.status : 'error'
    if (typeof doc.exchange_id === 'string' && doc.exchange_id) state.exchange_id = doc.exchange_id.slice(0, 128)
    if (isInt(doc.last_seq, 0)) state.last_seq = doc.last_seq
    const plan = doc.plan
    if (isObj(plan) && PLAN_ORIGINS.includes(plan.origin)) {
      const mission = text(plan.mission, CAPS.mission_chars)
      const steps = []
      const seen = new Set()
      for (const raw of Array.isArray(plan.steps) ? plan.steps : []) {
        const step = planStep(raw)
        if (!step || seen.has(step.id)) continue
        seen.add(step.id)
        const stored = newStep(step)
        if (STEP_STATUSES.includes(raw.status)) stored.status = raw.status
        if (isInt(raw.done, 0)) stored.done = raw.done
        steps.push(stored)
        if (steps.length >= CAPS.max_plan_steps) break
      }
      if (mission != null && steps.length) {
        state.plan = { version: isInt(plan.version, 1) ? plan.version : 1, origin: plan.origin, mission, steps }
      }
    }
    const seenNotes = new Set()
    for (const raw of Array.isArray(doc.notes) ? doc.notes : []) {
      if (!isObj(raw)) continue
      const note = notePayload(raw)
      if (!note || seenNotes.has(note.id)) continue
      seenNotes.add(note.id)
      if (tsValue(raw.ts) != null) note.ts = raw.ts
      state.notes.push(note)
      if (state.notes.length >= CAPS.max_notes) break
    }
    const seenWidgets = new Set()
    for (const raw of Array.isArray(doc.widgets) ? doc.widgets : []) {
      if (!isObj(raw)) continue
      const widget = widgetPayload(raw)
      if (!widget || seenWidgets.has(widget.id)) continue
      seenWidgets.add(widget.id)
      if (DATA_KINDS.has(widget.kind)) widget.binding = BINDINGS.includes(raw.binding) ? raw.binding : 'explicit'
      if (tsValue(raw.ts) != null) widget.ts = raw.ts
      state.widgets.push(widget)
      if (state.widgets.length >= CAPS.max_widgets) break
    }
    if (isObj(doc.provenance)) {
      for (const [key, raw] of Object.entries(doc.provenance)) {
        if (!isObj(raw)) continue
        const prov = provPayload({ ...raw, sql_id: key })
        if (!prov) continue
        delete prov.sql_id
        state.provenance[key] = prov
        if (Object.keys(state.provenance).length >= CAPS.max_provenance) break
      }
    }
    refreshSummary(state)
    return state
  } catch (e) {
    return null
  }
}

// --- selectors (read-only) ---------------------------------------------------------------

/** Plan progress: { done, total, pct } over the steps (done = status done). */
export function planProgress(state) {
  const steps = (state && state.plan && state.plan.steps) || []
  const done = steps.filter((s) => s.status === 'done').length
  return { done, total: steps.length, pct: steps.length ? Math.round((done / steps.length) * 100) : 0 }
}

/**
 * Steps decorated for display: 1-based index, batch progress (done/total) when the
 * step counts units, and the number of notes/widgets attached to it.
 */
export function stepsWithProgress(state) {
  const steps = (state && state.plan && state.plan.steps) || []
  return steps.map((s, i) => {
    const hasBatch = s.total != null && s.total > 1
    const done = s.done != null ? s.done : 0
    return {
      ...s,
      index: i + 1,
      hasBatch,
      batchPct: hasBatch ? Math.round((Math.min(done, s.total) / s.total) * 100) : 0,
      notes: (state.notes || []).filter((n) => n.step_id === s.id).length,
      widgets: (state.widgets || []).filter((w) => w.step_id === s.id).length,
    }
  })
}

/**
 * Journal groups: one group per plan step (plan order) holding its notes, then one
 * trailing "other" group for notes without a step or whose step was removed by a
 * plan replacement (`removed: true` when it references a vanished step id).
 */
export function journalGroups(state) {
  const steps = (state && state.plan && state.plan.steps) || []
  const ids = new Set(steps.map((s) => s.id))
  const groups = steps.map((s, i) => ({
    key: 'step-' + s.id,
    stepId: s.id,
    index: i + 1,
    label: s.label,
    status: s.status,
    notes: [],
    widgets: 0,
  }))
  const byId = new Map(groups.map((g) => [g.stepId, g]))
  const other = { key: 'other', stepId: null, index: 0, label: '', status: 'done', notes: [], widgets: 0, removed: false }
  for (const n of (state && state.notes) || []) {
    const g = n.step_id && ids.has(n.step_id) ? byId.get(n.step_id) : other
    if (g === other && n.step_id) other.removed = true
    g.notes.push(n)
  }
  for (const w of (state && state.widgets) || []) {
    const g = w.step_id && ids.has(w.step_id) ? byId.get(w.step_id) : null
    if (g) g.widgets += 1
  }
  return other.notes.length ? [...groups, other] : groups
}

/** Widgets grouped by step id ('' = no step / removed step), plan order kept. */
export function widgetsByStep(state) {
  const out = {}
  const ids = new Set(((state && state.plan && state.plan.steps) || []).map((s) => s.id))
  for (const w of (state && state.widgets) || []) {
    const key = w.step_id && ids.has(w.step_id) ? w.step_id : ''
    if (!out[key]) out[key] = []
    out[key].push(w)
  }
  return out
}

/** Board layout: KPI cards ride in their own row, every other widget in the grid. */
export function boardLayout(state) {
  const widgets = (state && state.widgets) || []
  return {
    kpis: widgets.filter((w) => w.kind === 'kpi'),
    others: widgets.filter((w) => w.kind !== 'kpi'),
  }
}

/** The step a widget/note belongs to (null when none or removed). */
export function stepFor(state, stepId) {
  const steps = (state && state.plan && state.plan.steps) || []
  const i = steps.findIndex((s) => s.id === stepId)
  return i >= 0 ? { ...steps[i], index: i + 1 } : null
}

/** The provenance record of a widget (or of any item carrying a sql_id), or null. */
export function provenanceFor(state, item) {
  const sid = item && item.sql_id
  if (!sid || !state || !state.provenance) return null
  return state.provenance[sid] || null
}

/**
 * The Data tab focus for one sql_id: the widget it was opened from (or the first
 * widget bound to that result), its step and provenance. null when the sql_id is
 * unknown to the workspace (stale focus after a plan/workspace change).
 */
export function dataFocus(state, sqlId, widgetId) {
  if (!state || !sqlId) return null
  const widgets = state.widgets || []
  const known = (state.summary && state.summary.sql_ids || []).includes(sqlId) || !!(state.provenance && state.provenance[sqlId])
  if (!known) return null
  const widget = widgets.find((w) => w.id === widgetId && w.sql_id === sqlId) || widgets.find((w) => w.sql_id === sqlId) || null
  const prov = (state.provenance && state.provenance[sqlId]) || null
  const stepId = (widget && widget.step_id) || (prov && prov.step_id) || null
  return { sqlId, widget, provenance: prov, step: stepId ? stepFor(state, stepId) : null }
}

/**
 * One filter of a resolved sql_id as display parts: the explainer step form
 * ({kind:'filter_*', params}) maps to an i18n key + args (Evidence wording); the
 * chip shape {column, op, values} and plain strings map to literal text (the column
 * worded for the business user by humanizeColumn).
 */
export function filterParts(f, stepArgs) {
  if (typeof f === 'string') return f ? { text: f } : null
  if (!f || typeof f !== 'object') return null
  if (typeof f.kind === 'string' && f.kind.startsWith('filter_')) return stepArgs(f)
  if (!f.column) return null
  const values = Array.isArray(f.values) ? f.values : f.value != null ? [f.value] : []
  const op = f.op && f.op !== '=' && f.op !== 'IN' ? ' ' + f.op + ' ' : ' : '
  return { text: humanizeColumn(f.column) + op + values.map(String).join(', ') }
}

/** The Chart.js spec the existing ArtifactChart expects (donut = pie + donut style). */
export function chartSpecForArtifact(chart) {
  if (!chart) return null
  if (chart.type === 'donut') return { ...chart, type: 'pie', style: 'donut' }
  return chart
}

/**
 * Plain-language i18n key for the expert that produced a result (the user never sees
 * an agent key): revenue and incident experts are named, anything else is "an expert".
 */
export function agentLabelKey(agentKey) {
  const k = String(agentKey || '').toLowerCase()
  if (k.includes('revenu') || k.includes('sales')) return 'ws.agent.revenue'
  if (k.includes('ticket') || k.includes('incident')) return 'ws.agent.tickets'
  return 'ws.agent.generic'
}

/**
 * Plain label of one result for the Data selector: the first widget title using it,
 * else its plan step label, else null (the caller numbers it "Result n").
 */
export function resultLabel(choice) {
  if (!choice) return null
  if (Array.isArray(choice.widgets) && choice.widgets.length) return choice.widgets[0]
  return choice.stepLabel || null
}
