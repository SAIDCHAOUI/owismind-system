// Scripted agent runs for the OWIsMind dev harness.
//
// A scenario is the full life of one exchange: the timed event feed /chat/poll
// serves (same normalized contract as agents/streaming.py + stream_manager.py),
// the persisted SQL items with their captured result, the artifact specs, and the
// evidence descriptor pieces /evidence/meta assembles. Figures are COMPUTED from
// the synthetic dataset so the chat answer, the chart, the captured table and the
// Evidence re-query all tell the same story.

import { REVENUES, TICKETS, aggregate, applyFilters } from './data.mjs'
import { agentEvent, workspaceOps, toDeltas } from './events.mjs'

// --- chart payload (faithful JS port of evidence/chart_payload.py) -------------

function toNumber(value) {
  if (value == null || typeof value === 'boolean') return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

export function buildChartPayload(result, spec) {
  if (!result || !result.captured) return { ok: false, reason: 'no_data' }
  const columns = result.columns || []
  const rows = result.rows || []
  if (!columns.length || !rows.length) return { ok: false, reason: 'no_data' }
  const ctype = spec && spec.type
  if (!['line', 'bar', 'pie'].includes(ctype)) return { ok: false, reason: 'bad_spec' }
  let y = spec.y
  if (typeof y === 'string') y = [y]
  if (!spec.x || !Array.isArray(y) || !y.length) return { ok: false, reason: 'bad_spec' }
  const resolve = (name) =>
    columns.findIndex((c) => String(c).trim().toLowerCase() === String(name).trim().toLowerCase())
  const xi = resolve(spec.x)
  if (xi < 0) return { ok: false, reason: 'x_not_found' }
  const yCols = y.map((name) => [name, resolve(name)]).filter(([, i]) => i >= 0)
  if (!yCols.length) return { ok: false, reason: 'y_not_found' }
  const capped = rows.slice(0, 200)
  if (ctype === 'pie') {
    const [name, yi] = yCols[0]
    const pairs = capped
      .map((r) => [String(r[xi] == null ? '' : r[xi]).slice(0, 80), toNumber(r[yi])])
      .filter(([, v]) => v != null && v > 0)
    if (!pairs.length) return { ok: false, reason: 'no_numeric' }
    pairs.sort((a, b) => b[1] - a[1])
    return {
      ok: true,
      label: name,
      labels: pairs.map(([l]) => l),
      datasets: [{ label: name, data: pairs.map(([, v]) => v) }],
      truncated: false,
    }
  }
  const labels = capped.map((r) => String(r[xi] == null ? '' : r[xi]).slice(0, 80))
  const datasets = yCols.map(([name, yi]) => ({
    label: name,
    data: capped.map((r) => toNumber(r[yi])),
  }))
  return { ok: true, labels, datasets, truncated: false }
}

export function buildKpiPayload(result, spec) {
  if (!result || !result.captured) return { ok: false, reason: 'no_data' }
  const columns = result.columns || []
  const row0 = (result.rows || [])[0]
  if (!columns.length || !row0) return { ok: false, reason: 'no_data' }
  const resolve = (name) =>
    columns.findIndex((c) => String(c).trim().toLowerCase() === String(name || '').trim().toLowerCase())
  const vi = resolve(spec && spec.value)
  if (vi < 0) return { ok: false, reason: 'value_not_found' }
  const value = toNumber(row0[vi])
  if (value == null) return { ok: false, reason: 'no_numeric' }
  const out = { ok: true, label: String((spec && spec.label) || spec.value).slice(0, 80), value }
  for (const key of ['delta', 'delta_pct']) {
    const ci = resolve(spec && spec[key])
    if (ci >= 0) {
      const num = toNumber(row0[ci])
      if (num != null) out[key] = num
    }
  }
  return out
}

// --- shared figures (computed from the synthetic dataset) -----------------------

const fmtM = (n) => (n / 1_000_000).toFixed(2).replace('.', ',') + ' M€'
const fmtEur = (n) =>
  Math.round(n).toLocaleString('fr-FR').replace(/ | /g, ' ') + ' €'

// Actuals vs Budget by solution over the 2026 mock year (the demo question).
function revenueBySolution() {
  const rows2026 = applyFilters(REVENUES, [
    { column: 'Year', op: '=', values: ['2026'] },
    { column: 'Phase', op: 'IN', values: ['ACTUALS', 'BUDGET'] },
  ])
  const bySolution = new Map()
  for (const row of rows2026) {
    if (!bySolution.has(row.Solution)) bySolution.set(row.Solution, { actual: 0, budget: 0 })
    const slot = bySolution.get(row.Solution)
    if (row.Phase === 'ACTUALS') slot.actual += row.Revenues
    else slot.budget += row.Revenues
  }
  const out = [...bySolution.entries()].map(([solution, v]) => ({
    solution,
    actual: Math.round(v.actual * 100) / 100,
    budget: Math.round(v.budget * 100) / 100,
  }))
  out.sort((a, b) => b.actual - a.actual)
  return { rows: out, scannedRows: rows2026.length }
}

// --- the demo scenario: actuals vs budget by solution ---------------------------

const REVENUE_SQL = `SELECT "Solution",
       SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END) AS actual_revenue,
       SUM(CASE WHEN "Phase" = 'BUDGET'  THEN "Revenues" ELSE 0 END) AS budget_revenue
FROM "OWISMIND_LOCAL_drive_revenues"
WHERE "Year" = 2026
  AND "Phase" IN ('ACTUALS', 'BUDGET')
GROUP BY "Solution"
ORDER BY actual_revenue DESC`

function buildRevenueAnswer(agg) {
  const totalActual = agg.rows.reduce((a, r) => a + r.actual, 0)
  const totalBudget = agg.rows.reduce((a, r) => a + r.budget, 0)
  const gapPct = ((totalActual - totalBudget) / totalBudget) * 100
  const lines = agg.rows.map((r) => {
    const gap = ((r.actual - r.budget) / r.budget) * 100
    return `| ${r.solution} | ${fmtEur(r.actual)} | ${fmtEur(r.budget)} | ${gap >= 0 ? '+' : ''}${gap.toFixed(1)} % |`
  })
  const best = agg.rows.reduce((a, b) =>
    (a.actual - a.budget) / a.budget > (b.actual - b.budget) / b.budget ? a : b)
  const worst = agg.rows.reduce((a, b) =>
    (a.actual - a.budget) / a.budget < (b.actual - b.budget) / b.budget ? a : b)
  return [
    `Sur 2026 (janvier à août), les revenus réels atteignent **${fmtM(totalActual)}** contre **${fmtM(totalBudget)}** budgétés, soit un écart global de **${gapPct >= 0 ? '+' : ''}${gapPct.toFixed(1)} %**.`,
    '',
    '| Solution | Actuals | Budget | Écart |',
    '|---|---:|---:|---:|',
    ...lines,
    '',
    'Points marquants :',
    `- **${best.solution}** est la solution la plus au-dessus de son budget (${(((best.actual - best.budget) / best.budget) * 100).toFixed(1)} %).`,
    `- **${worst.solution}** décroche le plus par rapport au budget (${(((worst.actual - worst.budget) / worst.budget) * 100).toFixed(1)} %).`,
    `- L'écart global reste contenu : les volumes Voice et Messaging portent l'essentiel du réalisé.`,
    '',
    `[Scope] Year = 2026 · Phase = ACTUALS vs BUDGET · ${agg.scannedRows} lignes agrégées en ${agg.rows.length} solutions`,
  ].join('\n')
}


// The timed event feed: [{at(ms), ev}]. Terminal events are appended by the API
// layer (final_answer / run_done), so a stop can cut the tail cleanly.
function buildRevenueEvents(exchangeId, agg) {
  const events = []
  const push = (at, ev) => events.push({ at, ev })
  push(0, { type: 'run_started', exchangeId })
  push(200, {
    type: 'agent_event', eventKind: 'START', blockId: null, nextBlockId: null,
    toolName: null, elapsedSeconds: 0.2, label: 'Analyse de la demande',
  })
  push(700, { type: 'narration', text: "Je confie la question à l'expert revenus : comparaison actuals vs budget par solution sur 2026." })
  push(1100, {
    type: 'agent_event', eventKind: 'CALLING_AGENT', blockId: null, nextBlockId: null,
    toolName: null, elapsedSeconds: 1.1, label: "Consultation de l'expert revenus",
    agentKey: 'revenue_expert', stepIndex: 1, stepCount: 1,
  })
  push(2300, {
    type: 'agent_event', eventKind: 'RUNNING_TOOL', blockId: null, nextBlockId: null,
    toolName: 'semantic-model-query', elapsedSeconds: 2.3,
    label: 'Génération du SQL par le modèle sémantique',
  })
  push(3600, {
    type: 'generated_sql', sqlIndex: 1, success: true, rowCount: agg.rows.length,
    sql: REVENUE_SQL, sqlId: 'sq-rev-001', stepIndex: 1, agentKey: 'revenue_expert',
  })
  push(3800, {
    type: 'agent_event', eventKind: 'AGENT_DONE', blockId: null, nextBlockId: null,
    toolName: null, elapsedSeconds: 3.8, label: 'Expert revenus : résultat obtenu',
    agentKey: 'revenue_expert', stepIndex: 1, status: 'ok',
  })
  push(4100, {
    type: 'agent_event', eventKind: 'ARTIFACT', blockId: null, nextBlockId: null,
    toolName: null, elapsedSeconds: 4.1, label: 'Graphique : Actuals vs Budget par solution',
  })
  push(4300, {
    type: 'agent_event', eventKind: 'WRITING_ANSWER', blockId: null, nextBlockId: null,
    toolName: null, elapsedSeconds: 4.3, label: 'Rédaction de la réponse',
  })
  const answer = buildRevenueAnswer(agg)
  let t = 4500
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 55
  }
  push(t + 100, {
    type: 'usage_summary', promptTokens: 6420, completionTokens: 812,
    totalTokens: 7232, estimatedCost: 0.0179,
  })
  return { events, answer, lastAt: t + 100 }
}

export function buildRevenueScenario(exchangeId) {
  const agg = revenueBySolution()
  const { events, answer, lastAt } = buildRevenueEvents(exchangeId, agg)
  const resultBlock = {
    captured: true,
    columns: ['Solution', 'actual_revenue', 'budget_revenue'],
    rows: agg.rows.map((r) => [r.solution, r.actual, r.budget]),
    row_count: agg.rows.length,
    truncated: false,
  }
  return {
    events,
    lastAt,
    answer,
    usage: { input_tokens: 6420, output_tokens: 812, total_tokens: 7232, estimated_cost: 0.0179 },
    sqlItems: [
      {
        sql: REVENUE_SQL, success: true, row_count: agg.rows.length,
        sql_id: 'sq-rev-001', step_index: 1, agent_key: 'revenue_expert',
        result: { columns: resultBlock.columns, rows: resultBlock.rows, truncated: false },
      },
    ],
    artifacts: [
      {
        kind: 'chart',
        title: 'Actuals vs Budget par solution (2026)',
        description: 'Revenus réels et budgétés agrégés par solution, janvier à août 2026.',
        sql_id: 'sq-rev-001',
        chart: { type: 'bar', x: 'Solution', y: ['actual_revenue', 'budget_revenue'], y_label: 'EUR', unit: '€' },
      },
      {
        kind: 'table',
        title: 'Détail par solution',
        description: 'Le résultat exact de la requête SQL exécutée par l\'expert revenus.',
        sql_id: 'sq-rev-001',
        chart: null,
      },
    ],
    evidence: {
      dataset: 'DRIVE_Revenues',
      chips: [
        { id: 1, column: 'Year', op: '=', values: ['2026'], editable: true },
        { id: 2, column: 'Phase', op: 'IN', values: ['ACTUALS', 'BUDGET'], editable: true },
      ],
      advanced: { present: false, display: '' },
      sql: REVENUE_SQL,
      explanationSteps: [
        { kind: 'source', params: ['DRIVE_Revenues'] },
        { kind: 'filter_eq', params: ['Year', '2026'] },
        { kind: 'filter_in', params: ['Phase', 2, 'ACTUALS, BUDGET'] },
        { kind: 'group', params: ['Solution'] },
        { kind: 'agg_sum', params: ['Revenues'] },
      ],
      drillColumns: ['Solution'],
      resultBlock,
    },
  }
}

// --- KPI scenario (asked with "kpi" / "total" in the message) --------------------

export function buildKpiScenario(exchangeId) {
  const agg = revenueBySolution()
  const totalActual = Math.round(agg.rows.reduce((a, r) => a + r.actual, 0) * 100) / 100
  const totalBudget = Math.round(agg.rows.reduce((a, r) => a + r.budget, 0) * 100) / 100
  const deltaPct = Math.round(((totalActual - totalBudget) / totalBudget) * 1000) / 10
  const sql = `SELECT SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END) AS total_actual,
       SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END) AS total_budget,
       ROUND(100.0 * (SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END)
             - SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END))
             / NULLIF(SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END), 0), 1) AS delta_pct
FROM "OWISMIND_LOCAL_drive_revenues"
WHERE "Year" = 2026`
  const answer = [
    `Le revenu réel total 2026 (janvier à août) s'établit à **${fmtM(totalActual)}**, contre **${fmtM(totalBudget)}** budgétés (**${deltaPct >= 0 ? '+' : ''}${deltaPct} %**).`,
    '',
    `[Scope] Year = 2026 · toutes solutions confondues`,
  ].join('\n')
  const events = []
  const push = (at, ev) => events.push({ at, ev })
  push(0, { type: 'run_started', exchangeId })
  push(200, { type: 'agent_event', eventKind: 'START', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 0.2, label: 'Analyse de la demande' })
  push(900, { type: 'agent_event', eventKind: 'CALLING_AGENT', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 0.9, label: "Consultation de l'expert revenus", agentKey: 'revenue_expert', stepIndex: 1 })
  push(2000, { type: 'agent_event', eventKind: 'RUNNING_TOOL', blockId: null, nextBlockId: null, toolName: 'semantic-model-query', elapsedSeconds: 2.0 })
  push(3000, { type: 'generated_sql', sqlIndex: 1, success: true, rowCount: 1, sql, sqlId: 'sq-kpi-001', stepIndex: 1, agentKey: 'revenue_expert' })
  push(3200, { type: 'agent_event', eventKind: 'AGENT_DONE', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 3.2, label: 'Expert revenus : résultat obtenu', status: 'ok' })
  push(3400, { type: 'agent_event', eventKind: 'ARTIFACT', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 3.4, label: 'KPI : revenu total 2026' })
  let t = 3600
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 55
  }
  push(t + 100, { type: 'usage_summary', promptTokens: 3180, completionTokens: 240, totalTokens: 3420, estimatedCost: 0.0082 })
  const resultBlock = {
    captured: true,
    columns: ['total_actual', 'total_budget', 'delta_pct'],
    rows: [[totalActual, totalBudget, deltaPct]],
    row_count: 1,
    truncated: false,
  }
  return {
    events,
    lastAt: t + 100,
    answer,
    usage: { input_tokens: 3180, output_tokens: 240, total_tokens: 3420, estimated_cost: 0.0082 },
    sqlItems: [
      {
        sql, success: true, row_count: 1, sql_id: 'sq-kpi-001', step_index: 1,
        agent_key: 'revenue_expert',
        result: { columns: resultBlock.columns, rows: resultBlock.rows, truncated: false },
      },
    ],
    artifacts: [
      {
        kind: 'kpi',
        title: 'Revenu total 2026',
        description: 'Réalisé vs budget, toutes solutions, janvier à août 2026.',
        sql_id: 'sq-kpi-001',
        chart: null,
        kpi: { label: 'Revenu réel 2026', value: 'total_actual', delta_pct: 'delta_pct', unit: '€' },
      },
    ],
    evidence: {
      dataset: 'DRIVE_Revenues',
      chips: [{ id: 1, column: 'Year', op: '=', values: ['2026'], editable: true }],
      advanced: { present: false, display: '' },
      sql,
      explanationSteps: [
        { kind: 'source', params: ['DRIVE_Revenues'] },
        { kind: 'filter_eq', params: ['Year', '2026'] },
        { kind: 'agg_sum', params: ['Revenues'] },
      ],
      drillColumns: [],
      resultBlock,
    },
  }
}

// --- Detail scenario (asked with "détail" / "liste" / "lignes") -------------------
// A row-level listing much longer than what an agent keeps: the capture holds the
// first 50 rows (the agents' MAX_RESULT_ROWS) with row_count = 50 (the real agents
// count AFTER the cut), truncated: true. The FULL result rides on the SQL item
// (`fullResult`, mock-only) so /evidence/result-rows can page it like the real
// backend re-running the stored SELECT.
const DETAIL_SQL = `SELECT "Account_name", "Country", "Solution", "Month", "Revenues"
FROM "OWISMIND_LOCAL_drive_revenues"
WHERE "Year" = 2026 AND "Phase" = 'ACTUALS'
ORDER BY "Revenues" DESC`

export function buildDetailScenario(exchangeId) {
  const columns = ['Account_name', 'Country', 'Solution', 'Month', 'Revenues']
  const full = applyFilters(REVENUES, [
    { column: 'Year', op: '=', values: [2026] },
    { column: 'Phase', op: '=', values: ['ACTUALS'] },
  ])
    .slice()
    .sort((a, b) => b.Revenues - a.Revenues)
    .map((r) => columns.map((c) => r[c]))
  const excerpt = full.slice(0, 50)
  const answer = [
    'Voici le détail des revenus réels 2026 par client, du plus élevé au plus faible.',
    '',
    '[Scope] Year = 2026 · Phase = ACTUALS',
  ].join('\n')
  const events = []
  const push = (at, ev) => events.push({ at, ev })
  push(0, { type: 'run_started', exchangeId })
  push(200, { type: 'agent_event', eventKind: 'START', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 0.2, label: 'Analyse de la demande' })
  push(900, { type: 'agent_event', eventKind: 'CALLING_AGENT', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 0.9, label: "Consultation de l'expert revenus", agentKey: 'revenue_expert', stepIndex: 1 })
  push(2000, { type: 'generated_sql', sqlIndex: 1, success: true, rowCount: 50, sql: DETAIL_SQL, sqlId: 'sq-det-001', stepIndex: 1, agentKey: 'revenue_expert' })
  push(2300, { type: 'agent_event', eventKind: 'AGENT_DONE', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 2.3, label: 'Expert revenus : résultat obtenu', status: 'ok' })
  push(2500, { type: 'agent_event', eventKind: 'ARTIFACT', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 2.5, label: 'Tableau : détail des revenus' })
  let t = 2700
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 55
  }
  push(t + 100, { type: 'usage_summary', promptTokens: 2100, completionTokens: 180, totalTokens: 2280, estimatedCost: 0.005 })
  const resultBlock = { captured: true, columns, rows: excerpt, row_count: 50, truncated: true }
  return {
    events,
    lastAt: t + 100,
    answer,
    usage: { input_tokens: 2100, output_tokens: 180, total_tokens: 2280, estimated_cost: 0.005 },
    sqlItems: [
      {
        sql: DETAIL_SQL, success: true, row_count: 50, sql_id: 'sq-det-001', step_index: 1,
        agent_key: 'revenue_expert',
        result: { columns, rows: excerpt, truncated: true },
        fullResult: { columns, rows: full },
      },
    ],
    artifacts: [
      {
        kind: 'table',
        title: 'Revenus réels 2026 par client',
        description: 'Une ligne par client, mois et solution, triée par revenu décroissant.',
        sql_id: 'sq-det-001',
        chart: null,
      },
    ],
    evidence: {
      dataset: 'DRIVE_Revenues',
      chips: [
        { id: 1, column: 'Year', op: '=', values: ['2026'], editable: true },
        { id: 2, column: 'Phase', op: '=', values: ['ACTUALS'], editable: true },
      ],
      advanced: { present: false, display: '' },
      sql: DETAIL_SQL,
      explanationSteps: [
        { kind: 'source', params: ['DRIVE_Revenues'] },
        { kind: 'filter_eq', params: ['Year', '2026'] },
        { kind: 'filter_eq', params: ['Phase', 'ACTUALS'] },
      ],
      drillColumns: [],
      resultBlock,
    },
  }
}

// Conversational answer with NO SQL at all (small talk / capability question): the
// real orchestrator answers such turns directly, stores no generated_sql, and
// /evidence/meta then degrades to { available:false, reason:'no_sql' }. Exercises the
// SQL-less Evidence path (Source data stays reachable through the agent's datasets).
export function buildChatterScenario(exchangeId) {
  const answer = [
    "Bonjour ! Je suis OWIsMind, l'assistant data d'Orange Wholesale International.",
    '',
    'Posez-moi une question sur les **revenus DRIVE** ou les **trouble tickets** - par exemple : « Total des revenus 2026 par pays ».',
  ].join('\n')
  const events = []
  const push = (at, ev) => events.push({ at, ev })
  push(0, { type: 'run_started', exchangeId })
  push(200, { type: 'agent_event', eventKind: 'START', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds: 0.2, label: 'Analyse de la demande' })
  let t = 700
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 45
  }
  push(t + 100, { type: 'usage_summary', promptTokens: 610, completionTokens: 70, totalTokens: 680, estimatedCost: 0.0012 })
  return {
    events,
    lastAt: t + 100,
    answer,
    usage: { input_tokens: 610, output_tokens: 70, total_tokens: 680, estimated_cost: 0.0012 },
    sqlItems: [],
    artifacts: [],
    evidence: null,
  }
}

// --- V2 multi-facet workspace scenario (default question) -------------------------
// A plan-first orchestrator run: 4 steps, 2 sub-agents (revenue, tickets), 3 captured
// SQL (s1q1, s1q2, s2q1), 5 widgets (bar chart, KPI, donut, table, text), 4 notes and
// a provenance record per SQL. The WORKSPACE operations are emitted EXACTLY as the
// backend relays them (agents/streaming.py: {type:'workspace', v, op, seq, ts, ...});
// the generated_sql events carry sqlId + the captured result like the real relay.

const WS_REVENUE_SQL = REVENUE_SQL
const WS_TOTAL_SQL = `SELECT SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END) AS total_actual,
       SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END) AS total_budget,
       ROUND(100.0 * (SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END)
             - SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END))
             / NULLIF(SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END), 0), 1) AS delta_pct
FROM "OWISMIND_LOCAL_drive_revenues"
WHERE "Year" = 2026 AND "Phase" IN ('ACTUALS', 'BUDGET')`
const WS_TICKETS_SQL = `SELECT "Severity", COUNT(DISTINCT "id") AS tickets,
       ROUND(AVG("Duration_ticket_total") / 60.0, 1) AS avg_hours
FROM "OWISMIND_LOCAL_troubletickets_year"
WHERE "creationDate" >= '2026-01-01' AND "Status" IN ('Open', 'In Progress')
GROUP BY "Severity"
ORDER BY "Severity"`

function openTicketsBySeverity() {
  const by = new Map()
  for (const t of TICKETS) {
    if (!['Open', 'In Progress'].includes(t.Status)) continue
    if (!by.has(t.Severity)) by.set(t.Severity, { n: 0, dur: 0 })
    const slot = by.get(t.Severity)
    slot.n += 1
    slot.dur += t.Duration_ticket_total
  }
  return [...by.entries()]
    .sort((a, b) => (a[0] < b[0] ? -1 : 1))
    .map(([sev, v]) => [sev, v.n, Math.round((v.dur / v.n / 60) * 10) / 10])
}

export function buildWorkspaceScenario(exchangeId) {
  const agg = revenueBySolution()
  const totalActual = Math.round(agg.rows.reduce((a, r) => a + r.actual, 0) * 100) / 100
  const totalBudget = Math.round(agg.rows.reduce((a, r) => a + r.budget, 0) * 100) / 100
  const deltaPct = Math.round(((totalActual - totalBudget) / totalBudget) * 1000) / 10
  const tickets = openTicketsBySeverity()
  const openTotal = tickets.reduce((a, r) => a + r[1], 0)
  const p1 = tickets.find((r) => r[0] === 'P1') || ['P1', 0, 0]
  const best = agg.rows[0]

  const revResult = { columns: ['Solution', 'actual_revenue', 'budget_revenue'], rows: agg.rows.map((r) => [r.solution, r.actual, r.budget]), truncated: false }
  const totalResult = { columns: ['total_actual', 'total_budget', 'delta_pct'], rows: [[totalActual, totalBudget, deltaPct]], truncated: false }
  const ticketResult = { columns: ['Severity', 'tickets', 'avg_hours'], rows: tickets, truncated: false }

  const events = []
  const push = (at, ev) => events.push({ at, ev })
  const wsOp = workspaceOps()
  const ws = (at, op, payload) => push(at, wsOp(Math.round(at / 100) / 10, op, payload))
  const step = (at, label, extra) => push(at, agentEvent(at / 1000, label, extra))

  push(0, { type: 'run_started', exchangeId })
  step(200, 'Analyse de la demande', { eventKind: 'START' })
  push(450, { type: 'narration', text: 'Je découpe la question en quatre étapes avant toute requête.' })
  ws(600, 'plan.set', {
    mission: 'Comparer le réalisé 2026 au budget par solution, chiffrer l’écart global, puis mesurer la charge des incidents ouverts.',
    origin: 'model',
    steps: [
      { id: 'p1', label: 'Réalisé et budget 2026 par solution' },
      { id: 'p2', label: 'Revenu total 2026 et écart au budget' },
      { id: 'p3', label: 'Incidents ouverts par sévérité', total: 4, unit: 'sévérités' },
      { id: 'p4', label: 'Synthèse et recommandations' },
    ],
  })
  ws(900, 'plan.step', { step_id: 'p1', status: 'running' })
  step(1100, "Consultation de l'expert revenus", { eventKind: 'CALLING_AGENT', agentKey: 'revenue', stepIndex: 1, stepCount: 3 })
  step(1700, 'Génération du SQL par le modèle sémantique', { eventKind: 'RUNNING_TOOL', toolName: 'semantic-model-query' })
  push(2600, { type: 'generated_sql', sqlIndex: 1, success: true, rowCount: agg.rows.length, sql: WS_REVENUE_SQL, sqlId: 's1q1', stepIndex: 1, agentKey: 'revenue', result: revResult })
  step(2700, 'Expert revenus : résultat obtenu', { eventKind: 'AGENT_DONE', agentKey: 'revenue', status: 'ok' })
  ws(2750, 'prov.set', { sql_id: 's1q1', agent_key: 'revenue', tool: 'semantic-model-query', task: 'Réalisé (ACTUALS) et budget 2026 par solution, du plus grand au plus petit réalisé.', step_id: 'p1', duration_ms: 1580, row_count: agg.rows.length, success: true })
  ws(3000, 'note.add', { id: 'n1', step_id: 'p1', kind: 'find', title: `${best.solution} porte le réalisé`, text: `${best.solution} : ${fmtEur(best.actual)} réalisés pour ${fmtEur(best.budget)} budgétés.`, sql_id: 's1q1' })
  ws(3300, 'widget.add', { id: 'w1', step_id: 'p1', kind: 'chart', title: 'Réalisé et budget 2026 par solution', comment: 'Deux barres par solution : le réalisé et le budget de janvier à août.', sql_id: 's1q1', chart: { type: 'bar', x: 'Solution', y: ['actual_revenue', 'budget_revenue'], y_label: 'Revenus', unit: '€' } })
  ws(3500, 'plan.step', { step_id: 'p1', status: 'done' })
  ws(3600, 'plan.step', { step_id: 'p2', status: 'running' })
  step(3700, "Consultation de l'expert revenus", { eventKind: 'CALLING_AGENT', agentKey: 'revenue', stepIndex: 2, stepCount: 3 })
  push(4700, { type: 'generated_sql', sqlIndex: 2, success: true, rowCount: 1, sql: WS_TOTAL_SQL, sqlId: 's1q2', stepIndex: 1, agentKey: 'revenue', result: totalResult })
  step(4800, 'Expert revenus : résultat obtenu', { eventKind: 'AGENT_DONE', agentKey: 'revenue', status: 'ok' })
  ws(4850, 'prov.set', { sql_id: 's1q2', agent_key: 'revenue', tool: 'semantic-model-query', task: 'Revenu total 2026 réalisé et budgété, avec l’écart en pourcentage.', step_id: 'p2', duration_ms: 960, row_count: 1, success: true })
  ws(5000, 'widget.add', { id: 'w2', step_id: 'p2', kind: 'kpi', title: 'Revenu réel 2026', comment: 'Réalisé de janvier à août, comparé au budget de la même période.', sql_id: 's1q2', kpi: { label: 'Revenu réel 2026', value: 'total_actual', delta_pct: 'delta_pct', unit: '€' } })
  ws(5150, 'note.add', { id: 'n2', step_id: 'p2', kind: 'check', title: 'Écart global vérifié', text: `Réalisé ${fmtM(totalActual)} contre ${fmtM(totalBudget)} budgétés (${deltaPct >= 0 ? '+' : ''}${deltaPct} %).`, sql_id: 's1q2' })
  ws(5300, 'plan.step', { step_id: 'p2', status: 'done' })
  ws(5400, 'plan.step', { step_id: 'p3', status: 'running', done: 0 })
  step(5500, "Consultation de l'expert tickets", { eventKind: 'CALLING_AGENT', agentKey: 'tickets', stepIndex: 3, stepCount: 3 })
  ws(6000, 'plan.step', { step_id: 'p3', done: 1 })
  ws(6400, 'plan.step', { step_id: 'p3', done: 2 })
  ws(6800, 'plan.step', { step_id: 'p3', done: 3 })
  push(7100, { type: 'generated_sql', sqlIndex: 3, success: true, rowCount: tickets.length, sql: WS_TICKETS_SQL, sqlId: 's2q1', stepIndex: 2, agentKey: 'tickets', result: ticketResult })
  step(7200, 'Expert tickets : résultat obtenu', { eventKind: 'AGENT_DONE', agentKey: 'tickets', status: 'ok' })
  ws(7250, 'prov.set', { sql_id: 's2q1', agent_key: 'tickets', tool: 'semantic-model-query', task: 'Nombre de tickets ouverts ou en cours depuis janvier 2026, par sévérité, avec la durée moyenne en heures.', step_id: 'p3', duration_ms: 1710, row_count: tickets.length, success: true })
  ws(7300, 'plan.step', { step_id: 'p3', done: 4 })
  ws(7450, 'widget.add', { id: 'w3', step_id: 'p3', kind: 'chart', title: 'Incidents ouverts par sévérité', comment: `${openTotal} tickets ouverts ou en cours depuis janvier.`, sql_id: 's2q1', chart: { type: 'donut', x: 'Severity', y: ['tickets'] } })
  ws(7600, 'widget.add', { id: 'w4', step_id: 'p3', kind: 'table', title: 'Détail par sévérité', comment: 'Nombre de tickets et durée moyenne de traitement.', sql_id: 's2q1' })
  ws(7750, 'note.add', { id: 'n3', step_id: 'p3', kind: 'find', title: `${p1[1]} incidents P1 encore ouverts`, text: `Durée moyenne de ${String(p1[2]).replace('.', ',')} h sur les P1 ouverts.`, sql_id: 's2q1' })
  ws(7900, 'plan.step', { step_id: 'p3', status: 'done' })
  ws(8000, 'plan.step', { step_id: 'p4', status: 'running' })
  ws(8300, 'widget.add', { id: 'w5', step_id: 'p4', kind: 'text', title: 'Synthèse', text: `**${best.solution}** tire le réalisé 2026 ; l’écart global au budget est de **${deltaPct >= 0 ? '+' : ''}${deltaPct} %**.\n\nCôté service, **${openTotal} incidents** restent ouverts, dont **${p1[1]} P1** : à suivre en priorité.` })
  ws(8450, 'note.add', { id: 'n4', step_id: 'p4', kind: 'done', title: 'Bilan prêt', text: 'Quatre étapes terminées, trois requêtes, cinq widgets publiés.' })
  ws(8550, 'plan.step', { step_id: 'p4', status: 'done' })
  step(8600, 'Rédaction de la réponse', { eventKind: 'WRITING_ANSWER' })

  const answer = [
    `**Réalisé et budget par solution.** ${best.solution} porte le réalisé 2026 avec ${fmtEur(best.actual)} pour ${fmtEur(best.budget)} budgétés.`,
    '',
    `**Écart global.** Le réalisé atteint ${fmtM(totalActual)} contre ${fmtM(totalBudget)} budgétés, soit ${deltaPct >= 0 ? '+' : ''}${deltaPct} %.`,
    '',
    `**Incidents ouverts.** ${openTotal} tickets sont ouverts ou en cours depuis janvier, dont ${p1[1]} en P1 (durée moyenne ${String(p1[2]).replace('.', ',')} h).`,
    '',
    '**Limites.** Données de janvier à août 2026 ; les tickets ne sont pas encore rapprochés des comptes du réalisé.',
  ].join('\n')
  let t = 8800
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 40
  }
  push(t + 100, { type: 'usage_summary', promptTokens: 11240, completionTokens: 1420, totalTokens: 12660, estimatedCost: 0.0312 })

  // Per-query Evidence descriptors (multi-SQL Evidence: /evidence/meta?sql_id=).
  const block = (r, n) => ({ captured: true, columns: r.columns, rows: r.rows, row_count: n, truncated: false })
  const revChips = [
    { id: 1, column: 'Year', op: '=', values: ['2026'], editable: true },
    { id: 2, column: 'Phase', op: 'IN', values: ['ACTUALS', 'BUDGET'], editable: true },
  ]
  const revSteps = [
    { kind: 'source', params: ['DRIVE_Revenues'] },
    { kind: 'filter_eq', params: ['Year', '2026'] },
    { kind: 'filter_in', params: ['Phase', 2, 'ACTUALS, BUDGET'] },
  ]
  const sqlItems = [
    { sql: WS_REVENUE_SQL, success: true, row_count: agg.rows.length, sql_id: 's1q1', step_index: 1, agent_key: 'revenue', result: revResult,
      evidence: { base: 'revenues', dataset: 'DRIVE_Revenues', chips: revChips, advanced: { present: false, display: '' }, sql: WS_REVENUE_SQL,
        explanationSteps: [...revSteps, { kind: 'group', params: ['Solution'] }, { kind: 'agg_sum', params: ['Revenues'] }], drillColumns: ['Solution'], resultBlock: block(revResult, agg.rows.length) } },
    { sql: WS_TOTAL_SQL, success: true, row_count: 1, sql_id: 's1q2', step_index: 1, agent_key: 'revenue', result: totalResult,
      evidence: { base: 'revenues', dataset: 'DRIVE_Revenues', chips: revChips, advanced: { present: false, display: '' }, sql: WS_TOTAL_SQL,
        explanationSteps: [...revSteps, { kind: 'agg_sum', params: ['Revenues'] }], drillColumns: [], resultBlock: block(totalResult, 1) } },
    { sql: WS_TICKETS_SQL, success: true, row_count: tickets.length, sql_id: 's2q1', step_index: 2, agent_key: 'tickets', result: ticketResult,
      evidence: { base: 'tickets', dataset: 'TroubleTickets_year',
        chips: [{ id: 1, column: 'Status', op: 'IN', values: ['Open', 'In Progress'], editable: true }],
        advanced: { present: true, display: '"creationDate" >= \'2026-01-01\'' }, sql: WS_TICKETS_SQL,
        explanationSteps: [{ kind: 'source', params: ['TroubleTickets_year'] }, { kind: 'filter_gte', params: ['creationDate', '2026-01-01'] }, { kind: 'filter_in', params: ['Status', 2, 'Open, In Progress'] }, { kind: 'group', params: ['Severity'] }],
        drillColumns: ['Severity'], resultBlock: block(ticketResult, tickets.length) } },
  ]
  // Filters as GET /workspace serves them: the filter_* explainer steps of each SQL.
  const filtersBySql = {
    s1q1: [{ kind: 'filter_eq', params: ['Year', '2026'] }, { kind: 'filter_in', params: ['Phase', 2, 'ACTUALS, BUDGET'] }],
    s1q2: [{ kind: 'filter_eq', params: ['Year', '2026'] }, { kind: 'filter_in', params: ['Phase', 2, 'ACTUALS, BUDGET'] }],
    s2q1: [{ kind: 'filter_gte', params: ['creationDate', '2026-01-01'] }, { kind: 'filter_in', params: ['Status', 2, 'Open, In Progress'] }],
  }
  const revenue = buildRevenueScenario(exchangeId)
  return {
    events,
    lastAt: t + 100,
    answer,
    usage: { input_tokens: 11240, output_tokens: 1420, total_tokens: 12660, estimated_cost: 0.0312 },
    sqlItems,
    filtersBySql,
    artifacts: [],
    // The Data tab (Evidence) keeps the V1.3 revenue descriptor for this exchange.
    evidence: { ...revenue.evidence, sql: WS_REVENUE_SQL },
  }
}

// --- Studio continuity: the CONTINUE run ------------------------------------------
// The user refines the Studio on screen ("garde ce graphique et ajoute en dessous...").
// Played as the worker RELAYS it: the orchestrator's studio.continue is already
// expanded into the studio.carry of the validated base (same seq 1, built by the
// caller from the stored base document), then this run adds ONE section text and ONE
// wide line chart bound to ITS OWN s1q1 (the same id as the base's s1q1, on purpose:
// the carried widgets resolve against their origin exchange, never this one).

const CONTINUE_SQL = `SELECT "Month",
       SUM(CASE WHEN "Phase" = 'ACTUALS' THEN "Revenues" ELSE 0 END) AS actual_revenue,
       SUM(CASE WHEN "Phase" = 'BUDGET' THEN "Revenues" ELSE 0 END) AS budget_revenue
FROM "OWISMIND_LOCAL_drive_revenues"
WHERE "Year" = 2026 AND "Phase" IN ('ACTUALS', 'BUDGET')
GROUP BY "Month"
ORDER BY "Month"`

const CONTINUE_RE = /(garde|rajoute|ajoute|en dessous|en bas|à côté|a cote|remplace|enl[eè]ve|ce graphique|keep|add|below|next to|replace|remove)/i

/** True when the message refines what is on screen (the scripted CONTINUE rule). */
export function wantsContinue(message) {
  return CONTINUE_RE.test(String(message || ''))
}

function monthlyActualVsBudget() {
  const rows2026 = applyFilters(REVENUES, [
    { column: 'Year', op: '=', values: ['2026'] },
    { column: 'Phase', op: 'IN', values: ['ACTUALS', 'BUDGET'] },
  ])
  const byMonth = new Map()
  for (const row of rows2026) {
    if (!byMonth.has(row.Month)) byMonth.set(row.Month, { actual: 0, budget: 0 })
    const slot = byMonth.get(row.Month)
    if (row.Phase === 'ACTUALS') slot.actual += row.Revenues
    else slot.budget += row.Revenues
  }
  return [...byMonth.entries()].sort((a, b) => a[0] - b[0])
    .map(([m, v]) => [m, Math.round(v.actual * 100) / 100, Math.round(v.budget * 100) / 100])
}

/**
 * @param {string} exchangeId
 * @param {(seq:number, ts:number) => object|null} makeCarry  the expanded studio.carry
 */
export function buildContinueScenario(exchangeId, makeCarry) {
  const rows = monthlyActualVsBudget()
  const result = { columns: ['Month', 'actual_revenue', 'budget_revenue'], rows, truncated: false }
  const best = rows.reduce((a, r) => (r[1] - r[2] > a[1] - a[2] ? r : a), rows[0])
  const events = []
  const push = (at, ev) => events.push({ at, ev })
  const wsOp = workspaceOps()
  const ws = (at, op, payload) => push(at, wsOp(Math.round(at / 100) / 10, op, payload))
  const step = (at, label, extra) => push(at, agentEvent(at / 1000, label, extra))

  push(0, { type: 'run_started', exchangeId })
  step(200, 'Analyse de la demande', { eventKind: 'START' })
  push(400, { type: 'narration', text: 'Je garde le Studio affiché et j’ajoute la vue mensuelle en dessous.' })
  // seq 1: the orchestrator's studio.continue, relayed as the carry of the base.
  const carry = wsOp(0.6, 'studio.continue', {})
  const expanded = makeCarry(carry.seq, carry.ts)
  push(600, expanded || carry)
  // New ids start past the highest carried w<n> (the orchestrator's _next_widget).
  const top = Math.max(0, ...((expanded && expanded.widgets) || []).map((w) => Number((/^w(\d+)$/.exec(w.id) || [])[1]) || 0))
  const textId = 'w' + (top + 1)
  const chartId = 'w' + (top + 2)
  step(900, "Consultation de l'expert revenus", { eventKind: 'CALLING_AGENT', agentKey: 'revenue', stepIndex: 1, stepCount: 1 })
  step(1300, 'Génération du SQL par le modèle sémantique', { eventKind: 'RUNNING_TOOL', toolName: 'semantic-model-query' })
  push(2100, { type: 'generated_sql', sqlIndex: 1, success: true, rowCount: rows.length, sql: CONTINUE_SQL, sqlId: 's1q1', stepIndex: 1, agentKey: 'revenue', result })
  step(2200, 'Expert revenus : résultat obtenu', { eventKind: 'AGENT_DONE', agentKey: 'revenue', status: 'ok' })
  ws(2250, 'prov.set', { sql_id: 's1q1', agent_key: 'revenue', tool: 'semantic-model-query', task: 'Réalisé et budget 2026 par mois (janvier à août).', duration_ms: 1150, row_count: rows.length, success: true })
  ws(2500, 'widget.add', { id: textId, kind: 'text', title: 'Réalisé et budget mois par mois', sql_id: 's1q1', text: `- Le réalisé suit le budget de janvier à août 2026.\n- Le meilleur mois face au budget est le mois **${best[0]}**.` })
  ws(2700, 'widget.add', { id: chartId, kind: 'chart', size: 'wide', title: 'Réalisé et budget mensuels 2026', comment: 'Revenus ACTUALS et BUDGET par mois, janvier à août 2026.', sql_id: 's1q1', chart: { type: 'line', x: 'Month', y: ['actual_revenue', 'budget_revenue'], x_label: 'Mois', y_label: 'Revenus', unit: '€' } })
  step(2900, 'Rédaction de la réponse', { eventKind: 'WRITING_ANSWER' })
  const answer = "J'ai complété le Studio (ajout du réalisé et du budget mois par mois, sous le graphique existant). Le détail est dans le Studio."
  let t = 3000
  for (const delta of toDeltas(answer)) {
    push(t, { type: 'answer_delta', text: delta })
    t += 40
  }
  push(t + 100, { type: 'usage_summary', promptTokens: 6120, completionTokens: 610, totalTokens: 6730, estimatedCost: 0.0141 })
  const block = { captured: true, columns: result.columns, rows, row_count: rows.length, truncated: false }
  const chips = [
    { id: 1, column: 'Year', op: '=', values: ['2026'], editable: true },
    { id: 2, column: 'Phase', op: 'IN', values: ['ACTUALS', 'BUDGET'], editable: true },
  ]
  const filters = [{ kind: 'filter_eq', params: ['Year', '2026'] }, { kind: 'filter_in', params: ['Phase', 2, 'ACTUALS, BUDGET'] }]
  const sqlItems = [{
    sql: CONTINUE_SQL, success: true, row_count: rows.length, sql_id: 's1q1', step_index: 1, agent_key: 'revenue', result,
    evidence: { base: 'revenues', dataset: 'DRIVE_Revenues', chips, advanced: { present: false, display: '' }, sql: CONTINUE_SQL,
      explanationSteps: [{ kind: 'source', params: ['DRIVE_Revenues'] }, ...filters, { kind: 'group', params: ['Month'] }, { kind: 'agg_sum', params: ['Revenues'] }],
      drillColumns: ['Month'], resultBlock: block },
  }]
  const revenue = buildRevenueScenario(exchangeId)
  return {
    events,
    lastAt: t + 100,
    answer,
    usage: { input_tokens: 6120, output_tokens: 610, total_tokens: 6730, estimated_cost: 0.0141 },
    sqlItems,
    filtersBySql: { s1q1: filters },
    artifacts: [],
    evidence: { ...revenue.evidence, sql: CONTINUE_SQL },
  }
}

// Route a user message to a scenario (the mock's tiny "orchestrator"). V2: EVERY
// business question plays the multi-facet workspace run - the V1.3 keyword routes
// ("total", "liste", "lignes", "détail" are words of ordinary questions) used to
// send natural questions to legacy runs WITHOUT any workspace, so the panel never
// showed up. The V1.3 runs now need an explicit "v1" prefix; greetings stay chatter.
export function pickScenario(message, exchangeId) {
  const m = String(message || '').toLowerCase().trim()
  if (/^(bonjour|hello|salut|merci|aide|help|qui es[- ]tu)\b[\s!?.]*$/.test(m)) return buildChatterScenario(exchangeId)
  if (/^v1\b/.test(m)) {
    if (m.includes('kpi') || m.includes('total')) return buildKpiScenario(exchangeId)
    if (/(détail|detail|liste|lignes)/.test(m)) return buildDetailScenario(exchangeId)
    return buildRevenueScenario(exchangeId)
  }
  return buildWorkspaceScenario(exchangeId)
}
