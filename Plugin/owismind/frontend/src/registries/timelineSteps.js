// Timeline step registry — maps a backend `agent_event.eventKind` to a human
// label + icon for the live execution timeline (design rule: map technical
// eventKinds to human labels). Extensible: add an eventKind = add one entry here
// (+ its i18n strings below); unknown kinds fall back to a humanized label.
//
// The label strings are MERGED into vue-i18n (see i18n/index.js) so all UI text
// stays consolidated. resolveTimelineStep returns { key, fallback, icon }.

// eventKind → { key: i18n key, icon: registry icon name }
const KNOWN = {
  AGENT_TURN_START: { key: 'tl.kind.turn_start', icon: 'sparkles' },
  AGENT_TURN_END: { key: 'tl.kind.turn_end', icon: 'check' },
  AGENT_BLOCK_START: { key: 'tl.kind.block_start', icon: 'layers' },
  AGENT_BLOCK_END: { key: 'tl.kind.block_end', icon: 'check' },
  AGENT_TOOL_START: { key: 'tl.kind.tool_start', icon: 'route' },
  AGENT_TOOL_END: { key: 'tl.kind.tool_end', icon: 'check' },
  AGENT_THINKING: { key: 'tl.kind.thinking', icon: 'sparkle' },
  AGENT_PLANNING: { key: 'tl.kind.planning', icon: 'sliders' },
  // Orchestrator kinds (trust layer v2 protocol, spec §5). The orchestrator
  // usually attaches a human `label` to these events — preferred at resolve
  // time — so these keys are the LABELLESS fallback. Kinds sharing a meaning
  // with an existing entry reuse its key (PLANNING, TOOL_DONE).
  START: { key: 'tl.kind.start', icon: 'sparkles' },
  PLANNING: { key: 'tl.kind.planning', icon: 'sliders' },
  PLAN_READY: { key: 'tl.kind.plan_ready', icon: 'check' },
  DIRECT_ANSWER: { key: 'tl.kind.direct_answer', icon: 'sparkle' },
  CALLING_AGENT: { key: 'tl.kind.calling_agent', icon: 'route' },
  AGENT_DONE: { key: 'tl.kind.agent_done', icon: 'check' },
  RUNNING_TOOL: { key: 'tl.kind.running_tool', icon: 'route' },
  TOOL_DONE: { key: 'tl.kind.tool_end', icon: 'check' },
  WRITING_ANSWER: { key: 'tl.kind.writing_answer', icon: 'sparkle' },
  DONE: { key: 'tl.kind.done', icon: 'check' },
}

// i18n strings for the known kinds (merged into the vue-i18n catalog at setup).
export const timelineMessages = {
  fr: {
    'tl.kind.turn_start': 'Analyse de la demande',
    'tl.kind.turn_end': 'Tour terminé',
    'tl.kind.block_start': 'Composition de la réponse',
    'tl.kind.block_end': 'Bloc terminé',
    'tl.kind.tool_start': "Appel d'un outil",
    'tl.kind.tool_end': 'Outil terminé',
    'tl.kind.thinking': 'Raisonnement',
    'tl.kind.planning': 'Planification',
    'tl.kind.step': 'Étape',
    'tl.kind.start': 'Démarrage',
    'tl.kind.plan_ready': 'Plan établi',
    'tl.kind.direct_answer': 'Réponse directe',
    'tl.kind.calling_agent': "Appel d'un agent",
    'tl.kind.agent_done': 'Agent terminé',
    'tl.kind.running_tool': "Exécution d'un outil",
    'tl.kind.writing_answer': 'Rédaction de la réponse',
    'tl.kind.done': 'Terminé',
  },
  en: {
    'tl.kind.turn_start': 'Parsing the request',
    'tl.kind.turn_end': 'Turn complete',
    'tl.kind.block_start': 'Composing the answer',
    'tl.kind.block_end': 'Block complete',
    'tl.kind.tool_start': 'Calling a tool',
    'tl.kind.tool_end': 'Tool complete',
    'tl.kind.thinking': 'Reasoning',
    'tl.kind.planning': 'Planning',
    'tl.kind.step': 'Step',
    'tl.kind.start': 'Starting',
    'tl.kind.plan_ready': 'Plan ready',
    'tl.kind.direct_answer': 'Direct answer',
    'tl.kind.calling_agent': 'Calling an agent',
    'tl.kind.agent_done': 'Agent complete',
    'tl.kind.running_tool': 'Running a tool',
    'tl.kind.writing_answer': 'Writing the answer',
    'tl.kind.done': 'Done',
  },
}

// Humanize an unknown eventKind: strip a leading SUB_AGENT_AGENT_ / SUB_AGENT_
// (orchestrator-relayed sub-agent events) then AGENT_, lowercase, spaces,
// capitalize. e.g. "AGENT_CUSTOM_PHASE" → "Custom phase",
// "SUB_AGENT_AGENT_TOOL_START" → "Tool start". UNKNOWN_CHUNK_TYPE:* → step.
function humanize(eventKind) {
  if (!eventKind) return ''
  if (String(eventKind).startsWith('UNKNOWN_CHUNK_TYPE')) return null // → generic 'step'
  const s = String(eventKind)
    .replace(/^SUB_AGENT_AGENT_/, '') // longest prefix first (order matters)
    .replace(/^SUB_AGENT_/, '')
    .replace(/^AGENT_/, '')
    .replace(/_/g, ' ')
    .toLowerCase()
    .trim()
  return s ? s.charAt(0).toUpperCase() + s.slice(1) : null
}

/**
 * Resolve a timeline step's display.
 * `label` (optional) is the backend-provided human label (orchestrator events,
 * spec §5): when it is a non-empty string it WINS over the registry — the
 * orchestrator knows the business phrasing better than a static kind map. The
 * icon still resolves from the kind, so known steps keep theirs.
 * Returns { key, fallback, icon }: render `key ? t(key) : fallback`.
 */
export function resolveTimelineStep(eventKind, label) {
  const hit = KNOWN[eventKind]
  if (typeof label === 'string' && label) {
    return { key: '', fallback: label, icon: hit ? hit.icon : 'route' }
  }
  if (hit) return { key: hit.key, fallback: '', icon: hit.icon }
  const human = humanize(eventKind)
  if (human) return { key: '', fallback: human, icon: 'route' }
  return { key: 'tl.kind.step', fallback: '', icon: 'route' }
}
