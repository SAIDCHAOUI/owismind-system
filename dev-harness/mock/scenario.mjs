// Scripted agent runs for the OWIsMind dev harness.
//
// A scenario is the full life of one exchange: the timed event feed /chat/poll
// serves (same normalized contract as agents/streaming.py + stream_manager.py),
// the persisted SQL items with their captured result, the artifact specs, and the
// evidence descriptor pieces /evidence/meta assembles. Figures are COMPUTED from
// the synthetic dataset so the chat answer, the chart, the captured table and the
// Evidence re-query all tell the same story.

import { REVENUES, aggregate, applyFilters } from './data.mjs'

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

// Split an answer into small deltas so the frontend streams like the real Mesh.
function toDeltas(text, chunk = 24) {
  const out = []
  for (let i = 0; i < text.length; i += chunk) out.push(text.slice(i, i + chunk))
  return out
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

// Route a user message to a scenario (the mock's tiny "orchestrator").
export function pickScenario(message, exchangeId) {
  const m = String(message || '').toLowerCase()
  if (/\b(bonjour|hello|salut|merci|aide|help|qui es[- ]tu)\b/.test(m)) return buildChatterScenario(exchangeId)
  if (m.includes('kpi') || m.includes('total')) return buildKpiScenario(exchangeId)
  return buildRevenueScenario(exchangeId)
}
