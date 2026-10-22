// The mock OWIsMind backend: a Vite dev-server middleware that answers every
// /owismind-api/* route with the SAME response shapes as the real Flask backend
// (python-lib/owismind). The plugin source is never touched: the frontend talks
// to this middleware exactly as it talks to DSS, via window.getWebAppBackendUrl.
//
// Contracts mirrored here (source of truth = the plugin backend):
//   - transport:  routes.py (status/error envelopes, HTTP codes)
//   - live runs:  agents/streaming.py + agents/stream_manager.py (normalized
//                 events, polling cursor, terminal frames, cooperative stop)
//   - evidence:   evidence/service.py + evidence/chart_payload.py
//   - source:     the /source/* explorer routes (rows / aggregate / distinct)

import {
  REVENUES, REVENUE_COLUMNS, TICKETS, TICKET_COLUMNS,
  applyFilters, applySearch, applyDrill, sortRows, paginate, aggregate, distinctValues,
} from './data.mjs'
import { pickScenario, buildRevenueScenario, buildWorkspaceScenario, buildContinueScenario, wantsContinue, buildChartPayload, buildKpiPayload } from './scenario.mjs'
// Studio continuity (mirror of routes / stream_manager / context / reducer.build_carry).
import { studioPointer, resolveStudioBase, buildCarry, rebindWidgets } from './studio.mjs'
// V2 workspace: the frontend's PURE reducer and payload builders are pinned to the
// backend's by the shared contract fixtures, so the mock reuses them to play the
// worker's role (reduce + finalize at run end) and GET /workspace's joins. Read-only
// imports: the plugin source is never modified for the harness.
import { reduceWorkspace, finalizeWorkspace, hasWorkspaceContent } from '../../plugin/owismind/frontend/src/composables/workspaceModel.js'
import {
  buildChartPayload as buildWidgetChart,
  buildKpiPayload as buildWidgetKpi,
} from '../../plugin/owismind/frontend/src/composables/widgetData.js'
// LIVE mode (real Claude agents over sqlite datasets) - see live/ and the README.
import { loadHarnessConfig } from './live/config.mjs'
import { createLiveBackend } from './live/liveApi.mjs'

// Resolved once: `live` when dev-harness/.env (or the env) holds ANTHROPIC_API_KEY,
// `stub` when forced (canned fake model), else the historical `scripted` mode.
const CONFIG = loadHarnessConfig()
let LIVE = null // the live backend, created on the first createMockApi() call

// --- mock identity + agents -----------------------------------------------------

const ME = {
  status: 'ok',
  user_id: 'said.chaoui',
  display_name: 'Said',
  groups: ['administrators', 'data-team'],
  needs_config: false,
  is_admin: true,
  impersonating: false,
  real_user_id: null,
}

const AGENTS = [
  {
    key: 'ag_owismind',
    label: 'OWIsMind',
    tagline: 'Your business data, answered',
    description:
      'Orchestrated access to the revenue and trouble-ticket domains: ask a business question, '
      + 'get a grounded answer with its SQL, source data and charts.',
    capabilities: [
      'Revenues: actuals, budget and forecast by account, solution or country',
      'Trouble tickets: volumes, severity and resolution times',
      'Cross-domain routing with full SQL transparency',
    ],
    tools: ['Semantic SQL', 'Attribute lookup', 'Charts & KPIs'],
    icon: 'robot',
    badge: 'Orchestrator',
    modes: true,
    has_benchmark: false,
    sources: [
      { id: 0, label: 'DRIVE Revenues', dataset: 'DRIVE_Revenues' },
      { id: 1, label: 'Trouble Tickets', dataset: 'TroubleTickets_year' },
    ],
  },
]

const SOURCES = {
  ag_owismind: [
    { label: 'DRIVE Revenues', dataset: 'DRIVE_Revenues', columns: REVENUE_COLUMNS, rows: REVENUES },
    { label: 'Trouble Tickets', dataset: 'TroubleTickets_year', columns: TICKET_COLUMNS, rows: TICKETS },
  ],
}

// Seeded "my submissions" histories (Help & support). Same item shape as the real
// backend (storage/feedback.py, storage/agent_requests.py) so the history cards -
// status pill, category chip, admin answer - actually render in the harness.
const MY_FEEDBACK = [
  {
    feedback_id: 'fb-1001',
    category: 'wrong',
    status: 'resolved',
    created_at: '2026-08-04T09:12:00Z',
    message: 'The revenue total for Q2 looked off on the budget comparison chart.',
    admin_response: 'Fixed: the ACTUALS phase filter was missing on that comparison.',
  },
  {
    feedback_id: 'fb-1002',
    category: 'feature',
    status: 'in_progress',
    created_at: '2026-08-09T15:40:00Z',
    message: 'Could the Source Data explorer export the filtered view as CSV?',
    admin_response: '',
  },
]

const MY_AGENT_REQUESTS = [
  {
    request_id: 'rq-2001',
    project_key: 'CSC_DELIVERY',
    project_label: 'CSC Delivery',
    status: 'open',
    created_at: '2026-08-07T11:05:00Z',
    business_case: 'Answer delivery-lead-time questions without exporting the snapshot to Excel.',
    datasets: [{ dataset: 'delivery_snapshot', table: 'delivery_snapshot', connection: 'SQL_owi' }],
    admin_response: '',
  },
]

// Live mode: the orchestrator exposes the three sqlite datasets as its sources.
function agentsPayload() {
  if (!LIVE) return AGENTS
  return AGENTS.map((a) => ({
    ...a,
    capabilities: [...a.capabilities, 'Won opportunities: deal amounts and contract lengths'],
    sources: LIVE.sources,
  }))
}

// --- in-memory state (exchanges, conversations, live runs) -----------------------

let exchangeSeq = 1000
let runSeq = 1

// exchange_id -> { row, evidence, artifacts, sqlItems }
const EXCHANGES = new Map()
// session_id -> { title, last_at, exchange_ids: [] }
const CONVERSATIONS = new Map()
// run_id -> { events, lastAt, scenario, exchangeId, sessionId, startedAt, stopAt, persisted }
const RUNS = new Map()

function nowIso() {
  return new Date().toISOString()
}

// --- Storage inventory (mirrors storage/migrations.py + sql_config.storage_status) ---
// Same logical names, same declaration order, same naming rule: the project key
// leads, the admin prefix (when set) sits before the mandatory `owismind`
// namespace. Keep in sync with _DDL_BY_LOGICAL / _ROLE_BY_LOGICAL.
const MOCK_PROJECT_KEY = 'OWISMIND_LOCAL'
const MOCK_TABLE_PREFIX = 'beta'
const MOCK_TABLES = [
  ['chat', 'webapp_chat_v5'],
  ['users', 'webapp_users_v1'],
  ['settings', 'webapp_settings_v1'],
  ['usage_monthly', 'webapp_usage_monthly_v1'],
  ['artifacts', 'webapp_artifacts_v1'],
  ['user_quota', 'webapp_user_quota_v1'],
  ['golden_suggestions', 'webapp_golden_suggestions_v1'],
  ['events', 'webapp_events_v1'],
  ['feedback', 'webapp_feedback_v1'],
  ['agent_requests', 'webapp_agent_requests_v1'],
  ['agent_runs', 'webapp_agent_runs_v1'],
  ['agent_run_steps', 'webapp_agent_run_steps_v1'],
  ['agent_run_events', 'webapp_agent_run_events_v1'],
]

function adminStorage() {
  const namespace = MOCK_TABLE_PREFIX ? `${MOCK_TABLE_PREFIX}-owismind` : 'owismind'
  const physical = (logical) => `${MOCK_PROJECT_KEY}_${namespace}_${logical}`
  const managed = MOCK_TABLES.map(([role, logical]) => ({
    role,
    logical,
    physical: physical(logical),
    qualified: `public."${physical(logical)}"`,
  }))
  return {
    configured: true,
    connection: 'SQL_owi',
    project_key: MOCK_PROJECT_KEY,
    project_key_source: 'dataiku_default',
    table_prefix: MOCK_TABLE_PREFIX,
    table_prefix_input: MOCK_TABLE_PREFIX,
    table_prefix_ignored: false,
    namespace,
    traces_dataset: 'beta-owismind_webapp_traces_v2',
    schema: 'public',
    tables: {
      chat: physical('webapp_chat_v5'),
      users: physical('webapp_users_v1'),
      settings: physical('webapp_settings_v1'),
      usage_monthly: physical('webapp_usage_monthly_v1'),
      user_quota: physical('webapp_user_quota_v1'),
      golden_suggestions: physical('webapp_golden_suggestions_v1'),
    },
    managed_tables: managed,
  }
}

function lightSqlItems(sqlItems) {
  // The conversation readback keeps SQL items LIGHT (no captured rows) - the
  // captures come back through /evidence/meta, mirroring the real payloads.
  return (sqlItems || []).map(({ result, fullResult, ...rest }) => rest)
}

// Mirror of stream_manager's end-of-run step: reduce the run's workspace events, stamp
// the status + exchange id, re-bind data widgets (orphan when their sql_id was never
// captured). null when the run emitted no workspace operation (no row is written).
// Like reducer.is_empty, next steps alone (suggest.set) are content: the row is written
// so the chips replay on reload, while the Studio still opens on widgets / plan only.
function buildWorkspaceDoc(exchangeId, events, status, sqlItems) {
  const ws = events.filter((e) => e && e.type === 'workspace')
  if (!ws.length) return null
  const state = reduceWorkspace(ws, exchangeId)
  const hasSuggestions = Array.isArray(state.suggestions) && state.suggestions.length > 0
  if (!hasWorkspaceContent(state) && !hasSuggestions) return null
  finalizeWorkspace(state, status)
  // Carried widgets (Studio continuity, `origin` set) keep their binding: their SQL
  // lives in their origin exchange (reducer.finalize skips them).
  return rebindWidgets(state, new Set((sqlItems || []).map((it) => it.sql_id)))
}

// A stored workspace offers the Studio when it has a plan or at least one widget; one
// holding only next steps (suggest.set) does not (storage.workspace_flags "studio").
function offersStudio(doc) {
  return !!(doc && ((doc.plan && typeof doc.plan === 'object') || (Array.isArray(doc.widgets) && doc.widgets.length)))
}

function persistExchange(sessionId, exchangeId, userText, agentKey, mode, scenario, createdAt) {
  const created = createdAt || nowIso()
  const row = {
    exchange_id: exchangeId,
    session_id: sessionId,
    user_id: ME.user_id,
    user_display_name: ME.display_name,
    user_groups: JSON.stringify(ME.groups),
    user_text: userText,
    assistant_text: scenario.answer,
    generated_sql: lightSqlItems(scenario.sqlItems),
    agent_key: agentKey,
    created_at: created,
    answered_at: nowIso(),
    feedback_rating: null,
    feedback_reasons: null,
    feedback_comment: null,
    parent_exchange_id: null,
    input_tokens: scenario.usage.input_tokens,
    output_tokens: scenario.usage.output_tokens,
    total_tokens: scenario.usage.total_tokens,
    estimated_cost: scenario.usage.estimated_cost,
    mode: mode || 'smart',
    screen_ctx: null,
    // V2: /conversation flags each row whose stored workspace offers a Studio (plan or
    // widgets) and carries its next steps (port of storage.workspace_flags).
    has_workspace: offersStudio(scenario.workspace),
  }
  if (scenario.workspace && Array.isArray(scenario.workspace.suggestions) && scenario.workspace.suggestions.length) {
    row.suggestions = [...scenario.workspace.suggestions]
  }
  EXCHANGES.set(exchangeId, {
    live: !!scenario.live,
    row,
    evidence: scenario.evidence,
    artifacts: scenario.artifacts,
    sqlItems: scenario.sqlItems,
    workspace: scenario.workspace || null,
    filtersBySql: scenario.filtersBySql || {},
  })
  if (!CONVERSATIONS.has(sessionId)) {
    CONVERSATIONS.set(sessionId, { title: userText.slice(0, 80), last_at: created, exchange_ids: [] })
  }
  const conv = CONVERSATIONS.get(sessionId)
  conv.exchange_ids.push(exchangeId)
  conv.last_at = nowIso()
  return row
}

// The previous turns of a conversation (oldest first) for a live run's context. Mirror
// of context.flatten_exchanges_to_messages: the assistant turn carries the bounded
// "[SQL généré pour cette réponse : ...]" block of its stored SQL (grounding).
function sqlContext(items) {
  const parts = (items || []).map((it) => String((it && it.sql) || '').trim()).filter(Boolean)
  return parts.length ? '\n\n[SQL généré pour cette réponse :\n' + parts.join('\n').slice(0, 4000) + ']' : ''
}

function conversationHistory(sessionId, limit) {
  const conv = CONVERSATIONS.get(sessionId)
  if (!conv || !limit) return []
  return conv.exchange_ids.slice(-limit).map((id) => {
    const row = EXCHANGES.get(id).row
    const assistant = row.assistant_text ? row.assistant_text + sqlContext(row.generated_sql) : row.assistant_text
    return { user: row.user_text, assistant }
  })
}

// Seed one finished conversation so the sidebar, reload path and Evidence panel
// have data before the first live run.
;(function seed() {
  const exchangeId = 'ex-seed-1'
  const scenario = buildRevenueScenario(exchangeId)
  const created = new Date(Date.now() - 3 * 3600 * 1000).toISOString()
  persistExchange(
    'sess-seed-1', exchangeId,
    'Compare les revenus réels et le budget par solution sur 2026',
    'ag_owismind', 'smart', scenario, created,
  )
  // A finished V2 run with its stored workspace (restore path: "Open the workspace").
  const wsId = 'ex-seed-ws-1'
  const wsScenario = buildWorkspaceScenario(wsId)
  const wsEvents = wsScenario.events.map((e) => e.ev)
  persistExchange(
    'sess-seed-ws-1', wsId,
    'Compare le réalisé 2026 au budget par solution et mesure les incidents ouverts',
    'ag_owismind', 'pro',
    { ...wsScenario, workspace: buildWorkspaceDoc(wsId, wsEvents, 'done', wsScenario.sqlItems) },
    new Date(Date.now() - 1 * 3600 * 1000).toISOString(),
  )
})()

// GET /workspace (mirror of the real route): the stored reduced state + the joins by
// sql_id (raw SQL, filters, captured result block) + server-built widget payloads.
// Mirror of workspace/resolve.py: result ALWAYS present ({captured:false} = no rows).
function resolveEntries(entry, sqlIds) {
  const resolved = {}
  for (const sid of sqlIds) {
    const items = (entry.sqlItems || []).filter((it) => it.sql_id === sid)
    if (items.length !== 1) continue      // missing or ambiguous: never resolved
    const item = items[0]
    resolved[sid] = {
      sql: item.sql,
      success: item.success != null ? !!item.success : null,
      row_count: item.row_count != null ? item.row_count : null,
      agent_key: item.agent_key || null,
      source_url: null,
      filters: entry.filtersBySql[sid] || [],
      result: item.result
        ? { captured: true, columns: item.result.columns, rows: item.result.rows, row_count: item.row_count, truncated: !!item.result.truncated }
        : { captured: false, row_count: item.row_count != null ? item.row_count : null },
    }
  }
  return resolved
}

function widgetData(w, resolved) {
  if (w.binding === 'orphan') return { ok: false, reason: 'orphan' }
  const result = resolved[w.sql_id] ? resolved[w.sql_id].result : null
  if (w.kind === 'chart') return buildWidgetChart(result, w.chart)
  if (w.kind === 'kpi') return buildWidgetKpi(result, w.kpi)
  return result && result.captured ? { ok: true } : { ok: false, reason: 'no_data' }
}

function workspaceFor(exchangeId) {
  const entry = EXCHANGES.get(exchangeId)
  if (!entry || !entry.workspace) return null
  const ws = entry.workspace
  const own = ws.widgets.filter((w) => !w.origin)
  const carried = ws.widgets.filter((w) => w.origin)
  const ownIds = [...ws.summary.sql_ids]
  for (const w of own) if (w.sql_id && !ownIds.includes(w.sql_id)) ownIds.push(w.sql_id)
  const resolved = resolveEntries(entry, ownIds)
  const widgetsData = {}
  for (const w of own) if (w.kind !== 'text') widgetsData[w.id] = widgetData(w, resolved)
  // Studio continuity: carried widgets resolve against their ORIGIN exchange only
  // (its sql_id s1q1 is minted per run); a missing origin reads as orphan.
  const origins = {}
  for (const originId of [...new Set(carried.map((w) => w.origin))].slice(0, 12)) {
    const group = carried.filter((w) => w.origin === originId)
    const origin = EXCHANGES.get(originId)
    if (!origin) {
      for (const w of group) if (w.kind !== 'text') widgetsData[w.id] = { ok: false, reason: 'orphan' }
      continue
    }
    const sids = [...new Set(group.map((w) => w.sql_id).filter(Boolean))]
    const oResolved = resolveEntries(origin, sids)
    const prov = (origin.workspace && origin.workspace.provenance) || {}
    origins[originId] = {
      resolved: oResolved,
      provenance: Object.fromEntries(sids.filter((sid) => prov[sid]).map((sid) => [sid, prov[sid]])),
    }
    for (const w of group) if (w.kind !== 'text') widgetsData[w.id] = widgetData(w, oResolved)
  }
  return { status: 'ok', workspace: ws, events: null, resolved, widgets_data: widgetsData, origins }
}

// --- evidence meta assembly (mirrors evidence_meta + the route enrichment) -------

// V2.0 multi-SQL Evidence (mirror of evidence/service._load_sql_item): the ACTIVE
// stored query = the one named by sql_id (unknown -> 404 sql_id_not_found), else the
// latest successful one. A query carrying its own `evidence` block (the multi-facet
// scenario) brings its dataset, chips and base rows; otherwise the exchange's.
function activeEvidence(entry, sqlId) {
  const items = entry.sqlItems || []
  let item = null
  if (sqlId) {
    item = items.find((it) => it.sql_id === sqlId)
    if (!item) return { missing: true }
  } else {
    item = [...items].reverse().find((it) => it.success && it.evidence) || null
  }
  const ev = (item && item.evidence) || entry.evidence
  const tickets = !!(ev && ev.base === 'tickets')
  return {
    item,
    ev,
    baseRows: tickets ? TICKETS : REVENUES,
    baseColumns: tickets ? TICKET_COLUMNS : REVENUE_COLUMNS,
    table: tickets ? 'OWISMIND_LOCAL_troubletickets_year' : 'OWISMIND_LOCAL_drive_revenues',
  }
}

// queries[] of /evidence/meta (mirror of summarize_queries + _attach_query_widgets).
function queriesFor(entry, activeItem) {
  const widgetsBySql = {}
  for (const w of (entry.workspace && entry.workspace.widgets) || []) {
    // A carried widget's sql_id belongs to its ORIGIN exchange.
    if (!w.sql_id || w.origin) continue
    if (!widgetsBySql[w.sql_id]) widgetsBySql[w.sql_id] = []
    widgetsBySql[w.sql_id].push({ id: w.id, kind: w.kind, title: w.title, source: 'workspace' })
  }
  return (entry.sqlItems || []).map((item, i) => ({
    index: i + 1,
    success: !!item.success,
    row_count: item.row_count,
    matched: true,
    result_captured: !!item.result,
    step_index: item.step_index,
    agent_key: item.agent_key,
    ...(item.sql_id ? { sql_id: item.sql_id, widgets: widgetsBySql[item.sql_id] || [] } : {}),
    active: item === activeItem,
  }))
}

const SQL_ID_RE = /^s[0-9]+(q|lk|qc)[0-9]+$/

function evidenceMetaFor(exchangeId, sqlId) {
  const entry = EXCHANGES.get(exchangeId)
  if (!entry) return null
  const scope = activeEvidence(entry, sqlId)
  if (scope.missing) return { missing: true }
  const ev = scope.ev
  // The picked query failed: honest degraded meta that still lists every query.
  if (scope.item && !scope.item.success) {
    return {
      status: 'ok', exchange_id: exchangeId, available: false, reason: 'no_successful_sql',
      sql: scope.item.sql || null, sql_id: scope.item.sql_id || null,
      queries: queriesFor(entry, scope.item),
      verification: { level: 'declared', result_captured: false }, artifacts: [],
    }
  }
  // No SQL stored for this exchange (conversational answer): the real backend
  // degrades to an honest declared-level meta (evidence_meta, reason 'no_sql').
  if (!ev) {
    return {
      status: 'ok',
      exchange_id: exchangeId,
      available: false,
      reason: 'no_sql',
      sql: null,
      verification: { level: 'declared', result_captured: false },
      artifacts: [],
    }
  }
  const resultBlock = ev.resultBlock
  const resultsBySql = {}
  for (const item of entry.sqlItems) {
    if (item.sql_id && item.result) {
      resultsBySql[item.sql_id] = {
        captured: true,
        columns: item.result.columns,
        rows: item.result.rows,
        row_count: item.row_count,
        truncated: !!item.result.truncated,
      }
    }
  }
  const artifacts = entry.artifacts.map((a) => {
    const out = { ...a }
    const block = a.sql_id ? resultsBySql[a.sql_id] || null : resultBlock
    if (a.kind === 'chart') out.data = buildChartPayload(block, a.chart)
    else if (a.kind === 'kpi') out.data = buildKpiPayload(block, a.kpi)
    else if (a.kind === 'table' && a.sql_id && block && block !== resultBlock) out.data = block
    return out
  })
  return {
    status: 'ok',
    available: true,
    sql_id: scope.item ? scope.item.sql_id || null : null,
    dataset: ev.dataset,
    columns: scope.baseColumns.map((c) => ({ name: c.name, type: c.type })),
    chips: ev.chips,
    advanced: ev.advanced,
    sql: ev.sql,
    source: {
      dataset: ev.dataset,
      schema: 'public',
      table: scope.table,
      url: '',
    },
    sources: [
      { dataset: ev.dataset, schema: 'public', table: scope.table, label: ev.dataset },
    ],
    queries: queriesFor(entry, scope.item),
    verification: {
      level: 'calc_decomposed',
      result_captured: !!(resultBlock && resultBlock.captured),
      dropped_predicates: 0,
      dropped_display: [],
      single_source: true,
      where_complete: true,
      select_understood: true,
    },
    explanation: { ok: true, steps: ev.explanationSteps },
    result: resultBlock,
    drilldown: ev.drillColumns.length
      ? { available: true, columns: ev.drillColumns, reason: null }
      : { available: false, columns: [], reason: 'no_group_keys' },
    artifacts,
  }
}

// The evidence table is the revenue base scoped by the chips (mirror of the
// server-side rebuilt WHERE): chips whose id is NOT in kept_ids are dropped,
// then the user's editable filters / search / drill apply on top.
function evidenceBaseRows(entry, body) {
  const scope = activeEvidence(entry, body.sql_id)
  const ev = scope.ev || entry.evidence
  const keptIds = Array.isArray(body.kept_ids) ? body.kept_ids : null
  const chips = ev.chips.filter(
    (c) => keptIds == null || keptIds.includes(c.id)
  )
  // The frontend re-sends edited chips inside `filters`; a chip edited there
  // must not ALSO apply with its original values - the client sends the full
  // active set, so locked chips only apply when filters does not carry them.
  const filterCols = new Set((body.filters || []).map((f) => f.column))
  const effectiveChips = chips.filter((c) => !filterCols.has(c.column))
  let rows = applyFilters(scope.baseRows || REVENUES, effectiveChips)
  rows = applyFilters(rows, body.filters || [])
  rows = applySearch(rows, body.q)
  rows = applyDrill(rows, body.drill)
  return rows
}

// --- HTTP plumbing ----------------------------------------------------------------

function sendJson(res, status, payload) {
  res.statusCode = status
  res.setHeader('Content-Type', 'application/json; charset=utf-8')
  res.setHeader('Cache-Control', 'no-store')
  res.end(JSON.stringify(payload))
}

function readBody(req) {
  return new Promise((resolve) => {
    const chunks = []
    req.on('data', (c) => chunks.push(c))
    req.on('end', () => {
      try {
        resolve(chunks.length ? JSON.parse(Buffer.concat(chunks).toString('utf8')) : {})
      } catch {
        resolve({})
      }
    })
    req.on('error', () => resolve({}))
  })
}

// --- route handlers ----------------------------------------------------------------

function handleChatStart(body) {
  const sessionId = body.session_id || 'sess-' + Date.now()
  const exchangeId = 'ex-' + ++exchangeSeq
  const runId = 'run-' + ++runSeq + '-' + Math.random().toString(36).slice(2, 8)
  // Studio continuity (stream_manager._resolve_studio_base): the Studio shown
  // (screen_context.studio_exchange_id, a pointer only) or the newest exchange of the
  // conversation with a workspace, validated (same session, not running, widgets).
  const conv = CONVERSATIONS.get(sessionId)
  const studioBase = resolveStudioBase({
    exchanges: EXCHANGES,
    chain: conv ? conv.exchange_ids : [],
    sessionId,
    exchangeId,
    pointer: studioPointer(body.screen_context),
  })
  if (LIVE) {
    const run = {
      exchangeId,
      sessionId,
      userText: String(body.message || ''),
      agentKey: body.agent_key || 'ag_owismind',
      mode: body.mode || 'smart',
      startedAt: Date.now(),
      persisted: false,
      studioBase,
    }
    RUNS.set(runId, run)
    LIVE.startRun(run, body)
    return { status: 'ok', run_id: runId, exchange_id: exchangeId }
  }
  // Scripted continue: a message that refines what is on screen, with a valid base,
  // plays the continue run (its studio.carry already expanded, as the worker relays it).
  const scenario = studioBase && wantsContinue(body.message)
    ? buildContinueScenario(exchangeId, (seq, ts) => buildCarry(studioBase.doc, studioBase.baseId, seq, [], ts))
    : pickScenario(body.message, exchangeId)
  RUNS.set(runId, {
    scenario,
    exchangeId,
    sessionId,
    userText: String(body.message || ''),
    agentKey: body.agent_key || 'ag_owismind',
    mode: body.mode || 'smart',
    startedAt: Date.now(),
    cursorEvents: null, // materialized terminal-complete list, built lazily
    stopAt: null,
    persisted: false,
  })
  return { status: 'ok', run_id: runId, exchange_id: exchangeId }
}

// Build the FULL event list for a run given its state (normal end or user stop),
// mirroring the worker: agent events, then final_answer + run_done | stopped.
function materializedEvents(run) {
  const cutoff = run.stopAt == null ? Infinity : run.stopAt
  const live = run.scenario.events.filter((e) => e.at <= cutoff).map((e) => e.ev)
  const stopped = run.stopAt != null && run.stopAt < run.scenario.lastAt
  const partial = live
    .filter((e) => e.type === 'answer_delta')
    .map((e) => e.text)
    .join('')
  const answer = stopped ? partial : run.scenario.answer
  live.push({ type: 'final_answer', exchangeId: run.exchangeId, text: answer })
  live.push(stopped ? { type: 'stopped', exchangeId: run.exchangeId } : { type: 'run_done', status: 'success' })
  return { events: live, answer, stopped }
}

function handleChatPoll(query) {
  const run = RUNS.get(query.run_id)
  if (!run) return { httpStatus: 404, payload: { status: 'error', error: 'run_not_found' } }
  if (run.live) return { httpStatus: 200, payload: LIVE.poll(run, query.cursor) }
  const elapsed = Date.now() - run.startedAt
  const finished = run.stopAt != null || elapsed >= run.scenario.lastAt + 150
  let visible
  if (finished) {
    const { events, answer, stopped } = materializedEvents(run)
    visible = events
    if (!run.persisted) {
      run.persisted = true
      const capturedIds = new Set(events.filter((e) => e.type === 'generated_sql').map((e) => e.sqlId))
      const sqlItems = (run.scenario.sqlItems || []).filter((it) => capturedIds.has(it.sql_id))
      const workspace = buildWorkspaceDoc(run.exchangeId, events, stopped ? 'stopped' : 'done', sqlItems)
      const scenario = { ...run.scenario, sqlItems, workspace, answer: stopped ? answer : run.scenario.answer }
      persistExchange(run.sessionId, run.exchangeId, run.userText, run.agentKey, run.mode, scenario)
    }
  } else {
    visible = run.scenario.events.filter((e) => e.at <= elapsed).map((e) => e.ev)
  }
  const cursor = Number(query.cursor) || 0
  // The worker strips captured rows from the polled copy (rows stay persistence-only).
  const polled = visible.slice(cursor).map((e) => {
    if (e.type !== 'generated_sql' || !e.result) return e
    const { result, ...rest } = e
    return rest
  })
  return {
    httpStatus: 200,
    payload: {
      status: 'ok',
      events: polled,
      cursor: visible.length,
      done: finished,
      error: null,
    },
  }
}

function handleSourceRoute(pathname, body, query) {
  if (LIVE) return LIVE.handleSource(pathname, body, query)
  const agentKey = body.agent != null ? body.agent : query.agent
  const sourceId = Number(body.source != null ? body.source : query.source) || 0
  const defs = SOURCES[agentKey] || SOURCES.ag_owismind
  const def = defs[sourceId] || defs[0]
  if (pathname.endsWith('/meta')) {
    return { status: 'ok', label: def.label, columns: def.columns }
  }
  let rows = applyFilters(def.rows, body.filters || [])
  rows = applySearch(rows, body.q)
  if (pathname.endsWith('/rows')) {
    rows = sortRows(rows, body.sort)
    const page = paginate(rows, body.limit, body.offset)
    return { status: 'ok', rows: page.rows, has_more: page.has_more, offset: page.offset }
  }
  if (pathname.endsWith('/aggregate')) {
    const agg = aggregate(rows, body.group, body.measures, body.limit)
    return { status: 'ok', ...agg }
  }
  // distinct: scope_q is the table-level search; q is the picker's own column search.
  let scoped = applyFilters(def.rows, body.filters || [])
  scoped = applySearch(scoped, body.scope_q)
  const distinct = distinctValues(scoped, body.column, body.q)
  return { status: 'ok', ...distinct }
}

function handleEvidenceRoute(pathname, body, query) {
  const entry = EXCHANGES.get(body.exchange_id)
  if (!entry) return { httpStatus: 404, payload: { status: 'error', error: 'exchange_not_found' } }
  // V2.0 multi-SQL: sql_id as body field or query param; malformed 400, unknown 404,
  // failed query 409 (never a silent fallback to the latest query).
  if (body.sql_id == null && query && query.sql_id) body.sql_id = query.sql_id
  if (body.sql_id != null) {
    if (!SQL_ID_RE.test(String(body.sql_id))) return { httpStatus: 400, payload: { status: 'error', error: 'invalid_sql_id' } }
    const sc = activeEvidence(entry, body.sql_id)
    if (sc.missing) return { httpStatus: 404, payload: { status: 'error', error: 'sql_id_not_found' } }
    if (!pathname.endsWith('/result-rows') && sc.item && !sc.item.success) {
      return { httpStatus: 409, payload: { status: 'error', error: 'no_successful_sql' } }
    }
  }
  if (pathname.endsWith('/result-rows')) {
    // Mirror of evidence_result_rows: page the FULL result of the stored item (the
    // real backend re-runs the agent's SELECT); total only on offset 0.
    const items = entry.sqlItems || []
    const item = body.sql_id
      ? items.find((it) => it.sql_id === body.sql_id)
      : [...items].reverse().find((it) => it.success && it.result)
    if (!item) return { httpStatus: 409, payload: { status: 'error', error: 'result_not_found' } }
    const full = item.fullResult || item.result
    const limit = Math.max(1, Math.min(100, Number(body.limit) || 50))
    const offset = Math.max(0, Math.min(500, Number(body.offset) || 0))
    const rows = full.rows.slice(offset, offset + limit)
    return {
      httpStatus: 200,
      payload: {
        status: 'ok', columns: full.columns, rows, offset,
        has_more: offset + limit < full.rows.length,
        total: offset === 0 ? full.rows.length : null,
      },
    }
  }
  // Live exchanges re-query the sqlite tables (scripted ones keep the JS engine).
  if (entry.live) return LIVE.evidenceRoute(pathname, body, entry)
  if (pathname.endsWith('/rows')) {
    let rows = evidenceBaseRows(entry, body)
    rows = sortRows(rows, body.sort)
    const page = paginate(rows, body.limit, body.offset)
    return { httpStatus: 200, payload: { status: 'ok', rows: page.rows, has_more: page.has_more, offset: page.offset } }
  }
  if (pathname.endsWith('/aggregate')) {
    const rows = evidenceBaseRows(entry, body)
    const agg = aggregate(rows, body.group, body.measures, body.limit)
    return { httpStatus: 200, payload: { status: 'ok', ...agg } }
  }
  // distinct (cascading picker): the OTHER chips + scope search, minus exclude_id.
  const excludeId = body.exclude_id
  const keptIds = Array.isArray(body.kept_ids) ? body.kept_ids : null
  const dscope = activeEvidence(entry, body.sql_id)
  const chips = (dscope.ev || entry.evidence).chips.filter(
    (c) => c.id !== excludeId && (keptIds == null || keptIds.includes(c.id))
  )
  const filterCols = new Set((body.filters || []).map((f) => f.column))
  let rows = applyFilters(dscope.baseRows || REVENUES, chips.filter((c) => !filterCols.has(c.column)))
  rows = applyFilters(rows, body.filters || [])
  rows = applySearch(rows, body.scope_q)
  rows = applyDrill(rows, body.drill)
  const distinct = distinctValues(rows, body.column, body.q)
  return { httpStatus: 200, payload: { status: 'ok', ...distinct } }
}

// --- the middleware ------------------------------------------------------------------

export function createMockApi() {
  if (CONFIG.mode !== 'scripted' && !LIVE) {
    LIVE = createLiveBackend(CONFIG, { persistExchange, buildWorkspaceDoc, queriesFor, conversationHistory })
  }
  console.log(
    `[owi-harness] mode: ${CONFIG.mode}`
      + (CONFIG.mode === 'live' ? ` (model ${CONFIG.model}, key from .env or ANTHROPIC_API_KEY)` : '')
      + (CONFIG.mode === 'stub' ? ' (canned fake model, no network)' : '')
      + (CONFIG.mode === 'scripted' ? ' (no ANTHROPIC_API_KEY found)' : ''),
  )
  return async function owismindMockApi(req, res, next) {
    const url = new URL(req.url, 'http://localhost')
    const pathname = url.pathname
    if (!pathname.startsWith('/owismind-api/')) return next()
    const query = Object.fromEntries(url.searchParams.entries())
    const body = req.method === 'POST' ? await readBody(req) : {}
    const route = pathname.slice('/owismind-api'.length)

    // Simulated latency so spinners and skeletons are visible (bounded, small).
    await new Promise((r) => setTimeout(r, 40 + Math.random() * 80))

    switch (true) {
      case route === '/ping':
        return sendJson(res, 200, { status: 'ok', python: 'mock' })
      case route === '/me':
        return sendJson(res, 200, ME)
      case route === '/agents':
        return sendJson(res, 200, { status: 'ok', count: AGENTS.length, agents: agentsPayload() })
      case route === '/usage':
        return sendJson(res, 200, {
          status: 'ok',
          usage: {
            spent_usd: 3.42,
            limit_usd: 50,
            remaining_usd: 46.58,
            limit_source: 'default',
            enforced: true,
            blocked: false,
            next_reset: '2026-09-01',
            period_start: '2026-08-01',
            request_count: 57,
            // Same shape as storage/budget.py _status_from_row: current-month token
            // counters at the top level, lifetime counters in a nested object.
            input_tokens: 412_000,
            output_tokens: 88_000,
            total_tokens: 500_000,
            lifetime: {
              input_tokens: 2_140_000,
              output_tokens: 402_000,
              total_tokens: 2_542_000,
              cost_usd: 18.73,
              last_usage_at: nowIso(),
            },
          },
        })
      case route === '/track':
        return sendJson(res, 200, { ok: true, accepted: 0 })
      case route === '/chat/start':
        return sendJson(res, 200, handleChatStart(body))
      case route === '/chat/poll': {
        const out = handleChatPoll(query)
        return sendJson(res, out.httpStatus, out.payload)
      }
      case route === '/chat/stop': {
        const run = RUNS.get(body.run_id)
        if (run && run.live) {
          if (!LIVE.stop(run)) return sendJson(res, 404, { status: 'error', error: 'run_not_found' })
          return sendJson(res, 200, { status: 'ok' })
        }
        if (!run || run.persisted) return sendJson(res, 404, { status: 'error', error: 'run_not_found' })
        run.stopAt = Date.now() - run.startedAt
        return sendJson(res, 200, { status: 'ok' })
      }
      case route === '/chat/active':
        return sendJson(res, 200, { status: 'ok', run: null })
      case route === '/chat/activity':
        return sendJson(res, 200, { status: 'ok', events: [] })
      case route === '/chat/feedback': {
        const entry = EXCHANGES.get(body.exchange_id)
        if (entry) {
          entry.row.feedback_rating = body.rating
          entry.row.feedback_reasons = JSON.stringify(body.reasons || [])
          entry.row.feedback_comment = body.comment || ''
        }
        return sendJson(res, 200, { status: 'ok' })
      }
      case route === '/conversations': {
        const conversations = [...CONVERSATIONS.entries()]
          .map(([session_id, c]) => ({ session_id, title: c.title, last_at: c.last_at }))
          .sort((a, b) => (a.last_at < b.last_at ? 1 : -1))
        return sendJson(res, 200, { status: 'ok', conversations, next_cursor: null, has_more: false })
      }
      case route === '/conversation': {
        const conv = CONVERSATIONS.get(query.session_id)
        const rows = conv ? conv.exchange_ids.map((id) => EXCHANGES.get(id).row) : []
        return sendJson(res, 200, { status: 'ok', session_id: query.session_id, count: rows.length, rows })
      }
      case route === '/workspace': {
        const doc = workspaceFor(query.exchange_id)
        if (!doc) return sendJson(res, 404, { status: 'error', error: 'workspace_not_found' })
        return sendJson(res, 200, doc)
      }
      case route === '/evidence/meta': {
        if (query.sql_id && !SQL_ID_RE.test(query.sql_id)) return sendJson(res, 400, { status: 'error', error: 'invalid_sql_id' })
        const liveEntry = EXCHANGES.get(query.exchange_id)
        const meta = liveEntry && liveEntry.live
          ? LIVE.evidenceMeta(query.exchange_id, liveEntry, query.sql_id)
          : evidenceMetaFor(query.exchange_id, query.sql_id)
        if (!meta) return sendJson(res, 404, { status: 'error', error: 'exchange_not_found' })
        if (meta.missing) return sendJson(res, 404, { status: 'error', error: 'sql_id_not_found' })
        return sendJson(res, 200, meta)
      }
      case route.startsWith('/evidence/'): {
        const out = handleEvidenceRoute(route, body, query)
        return sendJson(res, out.httpStatus, out.payload)
      }
      case route.startsWith('/source/'):
        return sendJson(res, 200, handleSourceRoute(route, body, query))
      case route === '/benchmark/suggestions':
        return sendJson(res, 200, { status: 'ok', count: 0, suggestions: [] })
      case route === '/benchmark/results':
        return sendJson(res, 200, { status: 'ok', configured: false, results: null })
      case route === '/feedback/mine':
        return sendJson(res, 200, { status: 'ok', items: MY_FEEDBACK })
      case route === '/feedback/submit':
        return sendJson(res, 200, { status: 'ok', feedback_id: 'fb-' + Date.now() })
      case route === '/agent-request/mine':
        return sendJson(res, 200, { status: 'ok', items: MY_AGENT_REQUESTS })
      case route === '/agent-request/submit':
        return sendJson(res, 200, { status: 'ok', request_id: 'rq-' + Date.now() })
      case route === '/catalog/projects':
        return sendJson(res, 200, { ok: false, reason: 'mock_no_catalog' })
      case route === '/admin/storage':
        // Shape of the REAL backend (api/routes.py admin_storage_get ->
        // sql_config.storage_status): the payload is wrapped in `storage`, and
        // `managed_tables` is the full inventory derived from the DDL registry.
        // A prefix is configured here on purpose, so the Admin page is exercised
        // with the "{project}_{prefix}-owismind_{logical}" naming it must show.
        return sendJson(res, 200, { status: 'ok', storage: adminStorage() })
      case route === '/admin/users':
        // The REAL backend decodes user_groups into a LIST before responding
        // (storage/admin.py) - mirror it, never the raw stored JSON string.
        return sendJson(res, 200, {
          users: [{
            user_id: ME.user_id, display_name: ME.display_name, user_groups: ME.groups,
            is_admin: true, first_seen: '2026-06-01T09:00:00Z', last_seen: nowIso(),
            total_input_tokens: 2_140_000, total_output_tokens: 402_000, total_cost: 18.73,
          }],
        })
      case route === '/admin/agents':
        return sendJson(res, 200, { agents: [] })
      case route === '/admin/projects':
        return sendJson(res, 200, { projects: ['OWISMIND_LOCAL'] })
      case route === '/admin/budget':
        return sendJson(res, 200, {
          status: 'ok',
          config: { limit_usd: 50, enabled: true, default_limit_usd: 50 },
          period_start: '2026-08-01',
          next_reset: '2026-09-01',
          users: [],
        })
      default:
        return sendJson(res, 200, { status: 'ok' })
    }
  }
}
