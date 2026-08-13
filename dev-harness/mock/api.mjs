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
import { pickScenario, buildRevenueScenario, buildChartPayload, buildKpiPayload } from './scenario.mjs'

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
  return (sqlItems || []).map(({ result, ...rest }) => rest)
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
  }
  EXCHANGES.set(exchangeId, {
    row,
    evidence: scenario.evidence,
    artifacts: scenario.artifacts,
    sqlItems: scenario.sqlItems,
  })
  if (!CONVERSATIONS.has(sessionId)) {
    CONVERSATIONS.set(sessionId, { title: userText.slice(0, 80), last_at: created, exchange_ids: [] })
  }
  const conv = CONVERSATIONS.get(sessionId)
  conv.exchange_ids.push(exchangeId)
  conv.last_at = nowIso()
  return row
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
})()

// --- evidence meta assembly (mirrors evidence_meta + the route enrichment) -------

function evidenceMetaFor(exchangeId) {
  const entry = EXCHANGES.get(exchangeId)
  if (!entry) return null
  const ev = entry.evidence
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
        truncated: false,
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
    dataset: ev.dataset,
    columns: REVENUE_COLUMNS.map((c) => ({ name: c.name, type: c.type })),
    chips: ev.chips,
    advanced: ev.advanced,
    sql: ev.sql,
    source: {
      dataset: ev.dataset,
      schema: 'public',
      table: 'OWISMIND_LOCAL_drive_revenues',
      url: '',
    },
    sources: [
      { dataset: ev.dataset, schema: 'public', table: 'OWISMIND_LOCAL_drive_revenues', label: ev.dataset },
    ],
    queries: entry.sqlItems.map((item, i) => ({
      index: i + 1,
      success: !!item.success,
      row_count: item.row_count,
      matched: true,
      result_captured: !!item.result,
      step_index: item.step_index,
      agent_key: item.agent_key,
    })),
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
  const keptIds = Array.isArray(body.kept_ids) ? body.kept_ids : null
  const chips = entry.evidence.chips.filter(
    (c) => keptIds == null || keptIds.includes(c.id)
  )
  // The frontend re-sends edited chips inside `filters`; a chip edited there
  // must not ALSO apply with its original values - the client sends the full
  // active set, so locked chips only apply when filters does not carry them.
  const filterCols = new Set((body.filters || []).map((f) => f.column))
  const effectiveChips = chips.filter((c) => !filterCols.has(c.column))
  let rows = applyFilters(REVENUES, effectiveChips)
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
  const scenario = pickScenario(body.message, exchangeId)
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
  const elapsed = Date.now() - run.startedAt
  const finished = run.stopAt != null || elapsed >= run.scenario.lastAt + 150
  let visible
  if (finished) {
    const { events, answer, stopped } = materializedEvents(run)
    visible = events
    if (!run.persisted) {
      run.persisted = true
      const scenario = { ...run.scenario, answer: stopped ? answer : run.scenario.answer }
      persistExchange(run.sessionId, run.exchangeId, run.userText, run.agentKey, run.mode, scenario)
    }
  } else {
    visible = run.scenario.events.filter((e) => e.at <= elapsed).map((e) => e.ev)
  }
  const cursor = Number(query.cursor) || 0
  return {
    httpStatus: 200,
    payload: {
      status: 'ok',
      events: visible.slice(cursor),
      cursor: visible.length,
      done: finished,
      error: null,
    },
  }
}

function handleSourceRoute(pathname, body, query) {
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

function handleEvidenceRoute(pathname, body) {
  const entry = EXCHANGES.get(body.exchange_id)
  if (!entry) return { httpStatus: 404, payload: { status: 'error', error: 'exchange_not_found' } }
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
  const chips = entry.evidence.chips.filter(
    (c) => c.id !== excludeId && (keptIds == null || keptIds.includes(c.id))
  )
  const filterCols = new Set((body.filters || []).map((f) => f.column))
  let rows = applyFilters(REVENUES, chips.filter((c) => !filterCols.has(c.column)))
  rows = applyFilters(rows, body.filters || [])
  rows = applySearch(rows, body.scope_q)
  rows = applyDrill(rows, body.drill)
  const distinct = distinctValues(rows, body.column, body.q)
  return { httpStatus: 200, payload: { status: 'ok', ...distinct } }
}

// --- the middleware ------------------------------------------------------------------

export function createMockApi() {
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
        return sendJson(res, 200, { status: 'ok', count: AGENTS.length, agents: AGENTS })
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
      case route === '/evidence/meta': {
        const meta = evidenceMetaFor(query.exchange_id)
        if (!meta) return sendJson(res, 404, { status: 'error', error: 'exchange_not_found' })
        return sendJson(res, 200, meta)
      }
      case route.startsWith('/evidence/'): {
        const out = handleEvidenceRoute(route, body)
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
