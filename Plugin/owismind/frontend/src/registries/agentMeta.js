// Agent metadata registry - OPTIONAL descriptive cards (icon / tagline / badge /
// description / bullets / tools), ported from the maquette (data.js → OWI_DATA.agents).
//
// IMPORTANT (memory F7 + confidentiality): this registry is NOT the source of the
// agent LIST. The list always comes from the backend GET /agents (enabled, opaque
// logical keys). This registry only ENRICHES a backend agent when its label
// matches a known entry - otherwise the agent shows a generic, honest card (we
// never invent capabilities/tools for an unknown agent). All copy is {fr,en} →
// render through useTr(). Extensibility: add a card = add one entry here.
export const agentMeta = [
  {
    id: 'owismind',
    name: 'OWIsMind',
    tagline: { fr: 'Orchestrateur multi-agent', en: 'Multi-agent orchestrator' },
    icon: 'sparkle',
    badge: 'default',
    desc: {
      fr: "L'agent principal d'OWI. Comprend votre question en langage naturel, route vers les bons sous-agents (Revenues, Tickets, CX…) et synthétise une réponse exécutive avec preuves.",
      en: "OWI's main agent. Understands your question in natural language, routes to the right sub-agents (Revenues, Tickets, CX…) and synthesises an executive response with evidence.",
    },
    bullets: [
      { fr: 'Routage intelligent multi-agent', en: 'Smart multi-agent routing' },
      { fr: 'Synthèse exécutive multi-source', en: 'Multi-source executive synthesis' },
      { fr: 'Evidence Studio attaché à chaque réponse', en: 'Evidence Studio attached to every answer' },
    ],
    tools: ['resolve_intent', 'plan_steps', 'route_to_agent', 'synthesize'],
  },
  {
    id: 'cooper',
    name: 'Cooper',
    tagline: { fr: 'Agent commercial - comptes clés', en: 'Sales agent - key accounts' },
    icon: 'robot',
    badge: 'new',
    desc: {
      fr: "L'agent dédié aux comptes clés OWI. Compile un brief client en 30 secondes : revenus, opportunités pipeline, tickets ouverts et signaux commerciaux. Idéal pour préparer une réunion.",
      en: 'The agent dedicated to OWI key accounts. Compiles a customer brief in 30 seconds: revenue, pipeline opportunities, open tickets and commercial signals. Perfect to prep a meeting.',
    },
    bullets: [
      { fr: 'Brief client 360° en un prompt', en: '360° customer brief in one prompt' },
      { fr: 'Pipeline & opportunités intégrés', en: 'Pipeline & opportunities built-in' },
      { fr: 'Signaux commerciaux (NPS, churn)', en: 'Commercial signals (NPS, churn)' },
    ],
    tools: ['customer_360', 'pipeline_query', 'competitive_signals'],
  },
  {
    id: 'revenues',
    name: 'Revenues',
    tagline: { fr: 'Revenus, budget, forecast', en: 'Revenue, budget, forecast' },
    icon: 'trendUp',
    badge: '',
    desc: {
      fr: 'Spécialiste du modèle sémantique Revenues. Répond aux questions de revenus, budget et forecast par client, solution line, géographie et période. Génère du SQL traçable.',
      en: 'Specialist of the Revenues semantic model. Answers revenue, budget and forecast questions by customer, solution line, geography and period. Generates traceable SQL.',
    },
    bullets: [
      { fr: 'Modèle sémantique sem_revenue_unified', en: 'Semantic model sem_revenue_unified' },
      { fr: 'Phases ACTUALS · BUDGET · FORECAST', en: 'Phases ACTUALS · BUDGET · FORECAST' },
      { fr: 'SQL généré exposé dans Evidence', en: 'Generated SQL exposed in Evidence' },
    ],
    tools: ['resolve_customer', 'revenue_semantic_query'],
  },
  {
    id: 'tickets',
    name: 'Tickets',
    tagline: { fr: 'Incidents, SLA, support', en: 'Incidents, SLA, support' },
    icon: 'alert',
    badge: '',
    desc: {
      fr: 'Spécialiste des tickets opérationnels OWI. Incidents, sévérité, SLA, MTTR par client, solution et période. Refresh 15 minutes.',
      en: 'Specialist of OWI operational tickets. Incidents, severity, SLA, MTTR by customer, solution and period. 15-minute refresh.',
    },
    bullets: [
      { fr: 'Source ops_tickets_v2', en: 'Source ops_tickets_v2' },
      { fr: 'Sévérités P1 → P3, SLA, MTTR', en: 'Severities P1 → P3, SLA, MTTR' },
      { fr: 'Refresh 15 min', en: '15-minute refresh' },
    ],
    tools: ['tickets_query', 'incident_drill'],
  },
  {
    id: 'cx',
    name: 'CX / NPS',
    tagline: { fr: 'Satisfaction & verbatims', en: 'Satisfaction & verbatims' },
    icon: 'thumbsUp',
    badge: 'beta',
    desc: {
      fr: 'Analyse NPS, verbatims clients, sentiment et signaux de churn. Identifie les comptes à risque et les leviers de fidélisation.',
      en: 'NPS analysis, customer verbatims, sentiment and churn signals. Identifies at-risk accounts and retention levers.',
    },
    bullets: [
      { fr: 'NPS par client / segment', en: 'NPS by customer / segment' },
      { fr: 'Analyse sémantique des verbatims', en: 'Semantic analysis of verbatims' },
      { fr: 'Score de churn prédictif', en: 'Predictive churn score' },
    ],
    tools: ['nps_query', 'verbatim_analysis', 'churn_score'],
  },
  {
    id: 'opps',
    name: 'Opportunities',
    tagline: { fr: 'Pipeline & forecasting', en: 'Pipeline & forecasting' },
    icon: 'layers',
    badge: 'beta',
    desc: {
      fr: 'Pipeline commercial, win-rate, forecasting des deals en cours. Vue par BU, par sales owner, par stage.',
      en: 'Sales pipeline, win-rate, forecasting of in-flight deals. View by BU, sales owner, stage.',
    },
    bullets: [
      { fr: 'Pipeline par stage et owner', en: 'Pipeline by stage and owner' },
      { fr: 'Win-rate historique', en: 'Historical win-rate' },
      { fr: 'Forecast probabilisé', en: 'Probabilistic forecast' },
    ],
    tools: ['pipeline_query', 'winrate_calc'],
  },
]

// Normalize a name/label/id to an alphanumeric lowercase key for fuzzy matching
// (e.g. "CX / NPS" → "cxnps", "OWIsMind" → "owismind").
function norm(s) {
  return String(s || '').toLowerCase().replace(/[^a-z0-9]/g, '')
}

// Index by both id and display name so a backend label ("Revenues", "CX"…) can
// resolve regardless of which form the admin enabled it under.
const byNorm = {}
for (const m of agentMeta) {
  byNorm[norm(m.id)] = m
  byNorm[norm(m.name)] = m
}

// Registry keys long enough to be safe for substring matching (avoids a 2-letter
// id like "cx" matching an unrelated label), longest first so the most specific
// key wins. Lets a decorated backend label such as "Agent - OWIsMind_orchestrator"
// still resolve to the OWIsMind card via its embedded "owismind".
const SUBSTRING_KEYS = Object.keys(byNorm)
  .filter((k) => k.length >= 4)
  .sort((a, b) => b.length - a.length)

/**
 * Resolve descriptive metadata for a backend agent label, or null if unknown.
 * The label is the only thing the backend exposes (never an agent_id). Tries an
 * exact normalized match first, then falls back to the longest registry key
 * contained in the label (so admin-decorated labels like "Agent - X" still match).
 */
export function resolveAgentMeta(label) {
  const n = norm(label)
  if (!n) return null
  if (byNorm[n]) return byNorm[n]
  const hit = SUBSTRING_KEYS.find((k) => n.includes(k))
  return hit ? byNorm[hit] : null
}
