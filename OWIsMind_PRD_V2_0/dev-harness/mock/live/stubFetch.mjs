// A canned fake of POST /v1/messages for `OWI_HARNESS_MODE=stub`: drives the LIVE
// code path (agents, SQL worker, evidence, persistence, polling) end to end with no
// network and no cost. It answers like a model would: plan, expert calls with real
// SQL on the synthetic tables, widgets bound to the returned sql_ids, final answer.
// Two-turn Studio continuity replay: turn 1 builds the analysis; a follow-up whose
// message carries a [CURRENT STUDIO] note (e.g. "garde ce graphique et ajoute en
// dessous le meme sur 2025 uniquement") continues it: edit_studio(continue), one
// expert query for 2025 only, then a section text + its wide line chart appended
// below the carried widgets, and a short "J'ai complete le Studio" answer.

const sleep = (ms, signal) => new Promise((resolve, reject) => {
  const t = setTimeout(resolve, ms)
  if (signal) signal.addEventListener('abort', () => { clearTimeout(t); reject(Object.assign(new Error('aborted'), { name: 'AbortError' })) }, { once: true })
})

let toolSeq = 0
const use = (name, input) => ({ type: 'tool_use', id: 'toolu_stub_' + ++toolSeq, name, input })
const text = (t) => ({ type: 'text', text: t })

const REVENUE_SQL = `SELECT "Solution", ROUND(SUM("revenue"), 2) AS actual_revenue
FROM public."OWISMIND_DEV_drive_revenues"
WHERE "Phase" = 'ACTUALS' AND "period" >= '2026-01-01' AND "period" < '2026-09-01'
GROUP BY "Solution"
ORDER BY actual_revenue DESC`

const TOTAL_SQL = `SELECT ROUND(SUM("revenue"), 2) AS total_actual
FROM public."OWISMIND_DEV_drive_revenues"
WHERE "Phase" = 'ACTUALS' AND "period" >= '2026-01-01' AND "period" < '2026-09-01'`

const MONTHLY_SQL = `SELECT "period", ROUND(SUM("revenue"), 2) AS actual_revenue
FROM public."OWISMIND_DEV_drive_revenues"
WHERE "Phase" = 'ACTUALS' AND "period" >= '2025-01-01' AND "period" < '2026-09-01'
GROUP BY "period"
ORDER BY "period"`

const TICKETS_SQL = `SELECT "Severity", COUNT(DISTINCT "id") AS tickets
FROM public."OWISMIND_DEV_troubletickets_year"
WHERE "Status" IN ('Open', 'In Progress')
GROUP BY "Severity"
ORDER BY "Severity"`

// Studio-first analysis (same contract as the live prompt): plan + scope text (role
// "scope", shown in the Studio header), then per business domain the KPIs first and
// each section text IMMEDIATELY followed by its chart (one wide monthly line chart),
// a closing synthesis text, and a short chat summary pointing to the Studio. Stub
// texts quote no figure (the stub cannot read the SQL results), so they stay honest.
function orchestratorReply(round) {
  switch (round) {
    case 0: return [text('Je prépare le plan de l\'analyse.'), use('set_plan', {
      mission: 'Mesurer le réalisé 2026 par solution, sa tendance mensuelle, puis la charge des incidents ouverts.',
      steps: ['Revenus réalisés', 'Incidents ouverts'],
    }), use('publish_widget', { kind: 'text', role: 'scope', title: 'Périmètre de l\'analyse', text: 'Cette analyse couvre le **réalisé** (en euros) par solution et mois par mois depuis janvier 2025, puis les **incidents encore ouverts** par sévérité. Données synthétiques du harness local.' }),
    use('update_plan_step', { index: 1, status: 'running' })]
    case 1: return [text("J'interroge l'expert revenus."), use('call_revenue_expert', { question: 'ACTUALS revenue 2026 (Jan to Aug) by Solution, the 2026 total, and the monthly ACTUALS revenue from 2025-01 to 2026-08.', step_index: 1 })]
    case 2: return [text('Je publie les revenus réalisés.'),
      use('publish_widget', { kind: 'kpi', title: 'Revenu réel 2026', step_index: 1, sql_id: 's1q2', kpi: { label: 'Revenu réel 2026', value: 'total_actual', unit: '€' } }),
      use('publish_widget', { kind: 'text', role: 'section', title: 'Réalisé 2026 par solution', step_index: 1, sql_id: 's1q1', text: '- Chiffre d\'affaires réalisé de janvier à août 2026.\n- Les solutions sont classées de la plus forte à la plus faible.' }),
      use('publish_widget', { kind: 'chart', title: 'Réalisé 2026 par solution', comment: 'Revenus ACTUALS de janvier à août 2026.', step_index: 1, sql_id: 's1q1', chart: { type: 'bar', style: 'horizontal', x: 'Solution', y: ['actual_revenue'], unit: '€' } }),
      use('publish_widget', { kind: 'text', role: 'section', title: 'Tendance mensuelle', step_index: 1, sql_id: 's1q3', text: '- Le réalisé mois par mois depuis janvier 2025.\n- La courbe montre la saisonnalité et le rythme de 2026.' }),
      use('publish_widget', { kind: 'chart', size: 'wide', title: 'Réalisé mensuel, janvier 2025 à août 2026', comment: 'Revenus ACTUALS par mois.', step_index: 1, sql_id: 's1q3', chart: { type: 'line', x: 'period', y: ['actual_revenue'], x_label: 'Mois', y_label: 'Revenus', unit: '€' } }),
      use('update_plan_step', { index: 1, status: 'done' }), use('update_plan_step', { index: 2, status: 'running' })]
    case 3: return [text("J'interroge l'expert tickets."), use('call_tickets_expert', { question: 'Open or in progress tickets by Severity.', step_index: 2 })]
    case 4: return [text('Je publie la répartition des incidents.'),
      use('publish_widget', { kind: 'text', role: 'section', title: 'Incidents ouverts par sévérité', step_index: 2, sql_id: 's2q1', text: '- Incidents **ouverts ou en cours**, par niveau de sévérité.\n- P1 = le plus critique, à suivre en priorité.' }),
      use('publish_widget', { kind: 'chart', title: 'Incidents ouverts par sévérité', step_index: 2, sql_id: 's2q1', chart: { type: 'donut', x: 'Severity', y: ['tickets'] } }),
      use('publish_widget', { kind: 'text', title: 'Synthèse et points clés', text: '- Le réalisé 2026 se lit par solution, avec le total de l\'année et sa tendance mensuelle.\n- Les incidents ouverts se concentrent sur quelques niveaux de sévérité.\n- À creuser : le lien entre les solutions qui pèsent le plus et les incidents critiques.' }),
      use('update_plan_step', { index: 2, status: 'done' })]
    default: return [use('final_answer', { markdown: '- Le réalisé 2026 (janvier à août) est détaillé par solution, avec le total de l\'année et la tendance mensuelle.\n- Les incidents ouverts sont répartis par sévérité.\n\nL\'analyse détaillée est dans le Studio.\n\n*Mode stub : réponse simulée, données synthétiques.*' })]
  }
}

const MONTHLY_2025_SQL = `SELECT "period", ROUND(SUM("revenue"), 2) AS actual_revenue
FROM public."OWISMIND_DEV_drive_revenues"
WHERE "Phase" = 'ACTUALS' AND "period" >= '2025-01-01' AND "period" < '2026-01-01'
GROUP BY "period"
ORDER BY "period"`

// The CONTINUE turn (the user refines the Studio on screen).
function continueReply(round) {
  switch (round) {
    case 0: return [text('Je garde le Studio affiché et j\'ajoute la vue 2025 en dessous.'),
      use('edit_studio', { mode: 'continue' }),
      use('call_revenue_expert', { question: 'Monthly ACTUALS revenue for 2025 only (2025-01 to 2025-12).' })]
    case 1: return [text('Je publie la vue 2025.'),
      use('publish_widget', { kind: 'text', role: 'section', title: 'Réalisé mensuel 2025', sql_id: 's1q1', text: '- Le réalisé mois par mois sur la seule année 2025.\n- À lire sous la courbe 2025-2026 pour comparer les rythmes.' }),
      use('publish_widget', { kind: 'chart', size: 'wide', title: 'Réalisé mensuel 2025', comment: 'Revenus ACTUALS par mois, janvier à décembre 2025.', sql_id: 's1q1', chart: { type: 'line', x: 'period', y: ['actual_revenue'], x_label: 'Mois', y_label: 'Revenus', unit: '€' } })]
    default: return [use('final_answer', { markdown: 'J\'ai complété le Studio (ajout du réalisé mensuel 2025, sous le graphique existant).\n\n*Mode stub : réponse simulée, données synthétiques.*' })]
  }
}

function expertReply(isRevenue, round, question) {
  if (isRevenue && /2025 only/.test(question)) {
    if (round === 0) return [use('run_sql', { sql: MONTHLY_2025_SQL, purpose: 'Monthly ACTUALS revenue 2025.' })]
    return [text('Result: s1q1 (monthly ACTUALS revenue 2025).')]
  }
  if (isRevenue) {
    if (round === 0) return [use('run_sql', { sql: REVENUE_SQL, purpose: 'ACTUALS revenue 2026 by Solution.' })]
    if (round === 1) return [use('run_sql', { sql: TOTAL_SQL, purpose: 'ACTUALS revenue 2026 total.' })]
    if (round === 2) return [use('run_sql', { sql: MONTHLY_SQL, purpose: 'Monthly ACTUALS revenue 2025-01 to 2026-08.' })]
    return [text('Results: s1q1 (revenue by Solution), s1q2 (2026 total), s1q3 (monthly revenue).')]
  }
  if (round === 0) return [use('run_sql', { sql: TICKETS_SQL, purpose: 'Open tickets by Severity.' })]
  return [text('Result: s2q1 (open tickets by Severity).')]
}

export function createStubFetch({ latencyMs = 450 } = {}) {
  return async function stubFetch(_url, init) {
    const body = JSON.parse(init.body)
    await sleep(latencyMs, init.signal)
    // The current question = the LAST user message with plain text content (the
    // replayed history comes before it); the round counts the replies after it.
    const messages = body.messages || []
    let current = 0
    messages.forEach((m, i) => { if (m.role === 'user' && typeof m.content === 'string') current = i })
    const round = messages.slice(current).filter((m) => m.role === 'assistant').length
    const question = String((messages[current] && messages[current].content) || '')
    const system = String(body.system || '')
    let content
    if (system.startsWith('You are the OWIsMind orchestrator')) {
      content = question.includes('[CURRENT STUDIO') ? continueReply(round) : orchestratorReply(round)
    } else content = expertReply(system.includes('REVENUE expert'), round, question)
    const hasTool = content.some((b) => b.type === 'tool_use')
    const payload = {
      id: 'msg_stub', type: 'message', role: 'assistant', model: body.model, content,
      stop_reason: hasTool ? 'tool_use' : 'end_turn',
      usage: { input_tokens: 1800 + round * 400, output_tokens: 120 + content.length * 40, cache_creation_input_tokens: 0, cache_read_input_tokens: 0 },
    }
    return new Response(JSON.stringify(payload), { status: 200, headers: { 'content-type': 'application/json' } })
  }
}
