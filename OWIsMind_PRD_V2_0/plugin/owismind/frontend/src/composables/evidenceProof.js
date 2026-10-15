// Pure Evidence "trust layer" helpers (NO Vue import - node:test testable, F11).
//
// These helpers turn the enriched /evidence/meta contract (frozen in
// docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md §2) into
// display-ready primitives for the proof sections of the Evidence panel.
// Every new meta field is OPTIONAL: a v1 meta (or a degraded/absent one) must
// fall through to the honest "declared" floor - never throw, never guess up.
//
// Honesty rules (§9): the mapping is fully deterministic, computed from the
// backend's own verification verdict; nothing here upgrades a claim.

// Visual grammar of the trust badge (maquette, no-green rule): solid border =
// certified scope, dashed = partial, muted grey = agent claim only. NEVER green.
const TONE_SOLID = 'solid'
const TONE_DASHED = 'dashed'
const TONE_MUTED = 'muted'

// Frozen explanation-step `kind` enum (spec §2). Kept as a LOCAL copy on
// purpose: an unknown kind coming from a newer/older backend must degrade to
// the `ev.exp.opaque` fallback instead of producing a missing-i18n-key blob.
export const EXPLANATION_KINDS = [
  'source', 'join',
  'filter_eq', 'filter_neq', 'filter_gt', 'filter_gte', 'filter_lt', 'filter_lte',
  'filter_in', 'filter_notin', 'filter_between', 'filter_null', 'filter_notnull',
  'filter_like', 'filter_advanced', 'filter_unmapped',
  'group', 'distinct',
  'agg_sum', 'agg_avg', 'agg_min', 'agg_max',
  'agg_count_star', 'agg_count', 'agg_count_distinct', 'agg_filtered',
  'calc_ratio', 'calc_percent', 'calc_diff', 'calc_share',
  'window_rank', 'window_row_number', 'window_running', 'window_lag',
  'having', 'sort', 'topn', 'limit_arbitrary', 'cte_step', 'union', 'opaque',
]
const KNOWN_KINDS = new Set(EXPLANATION_KINDS)

// Display cap for one step param: long literals (IN lists, LIKE patterns,
// advanced fragments) must not blow up a one-line step. 80 chars TOTAL,
// ellipsis included, so the UI line length is bounded deterministically.
const MAX_PARAM_CHARS = 80

// Max calc steps ever rendered - mirrors the backend's ≤ 15 steps contract so
// a malformed payload cannot flood the panel.
export const MAX_CALC_STEPS = 15

/**
 * Map the verification verdict onto the trust badge: {key, tone}.
 *
 * (level × result_captured) grammar - frozen in spec §6:
 *   calc_decomposed + captured        -> ev.proof.level.result   (solid)
 *   calc_decomposed | scope_exact     -> ev.proof.level.source   (solid)
 *   scope_partial | source_identified -> ev.proof.level.partial  (dashed)
 *   declared / anything else          -> ev.proof.level.declared (muted)
 *
 * Exhaustive fallback: absent meta, degraded meta (available === false),
 * missing verification block or an UNKNOWN level string all land on
 * `declared` - the floor is the honest claim, never an upgrade.
 */
export function trustLevel(meta) {
  const declared = { key: 'ev.proof.level.declared', tone: TONE_MUTED }
  if (!meta || meta.available === false) return declared
  const v = meta.verification
  if (!v || typeof v.level !== 'string') return declared
  const captured = v.result_captured === true
  if (v.level === 'calc_decomposed' && captured) {
    return { key: 'ev.proof.level.result', tone: TONE_SOLID }
  }
  if (v.level === 'calc_decomposed' || v.level === 'scope_exact') {
    return { key: 'ev.proof.level.source', tone: TONE_SOLID }
  }
  if (v.level === 'scope_partial' || v.level === 'source_identified') {
    return { key: 'ev.proof.level.partial', tone: TONE_DASHED }
  }
  return declared
}

/**
 * One explanation step -> {key, args} for `t(key, args)` (LIST interpolation).
 * Unknown/missing kind falls back to 'ev.exp.opaque' (frozen contract §2:
 * "unknown kind → ev.exp.opaque"). Params are display strings VERBATIM
 * (column names are never translated), each bounded to MAX_PARAM_CHARS.
 */
export function calcStepArgs(step) {
  const kind = step && typeof step.kind === 'string' ? step.kind : ''
  const key = KNOWN_KINDS.has(kind) ? 'ev.exp.' + kind : 'ev.exp.opaque'
  const raw = step && Array.isArray(step.params) ? step.params : []
  const args = raw.map((p) => {
    const s = p == null ? '' : String(p)
    return s.length > MAX_PARAM_CHARS ? s.slice(0, MAX_PARAM_CHARS - 1) + '…' : s
  })
  return { key, args }
}

// Plain column reference: optional quotes and table qualifier, word characters only.
// Anything else (an expression, a literal, an advanced fragment) stays verbatim.
const COLUMN_REF_RE = /^"?[A-Za-z_][\w$]*"?(\."?[A-Za-z_][\w$]*"?)*$/

/**
 * Business-readable name of a column for users who never see the schema:
 * the label from `labels` (a {column: label} map) when one exists, else a
 * humanized name (qualifier and quotes dropped, underscores / camelCase to
 * spaces, sentence case; 1-2 letter upper-case tokens such as "CA" or "ID" kept).
 * A value that is not a plain column reference is returned unchanged.
 */
export function humanizeColumn(name, labels) {
  const raw = name == null ? '' : String(name).trim()
  if (!raw) return ''
  const label = labels && typeof labels === 'object' ? labels[raw] : null
  if (typeof label === 'string' && label.trim()) return label.trim()
  if (!COLUMN_REF_RE.test(raw)) return raw
  const bare = raw.replace(/"/g, '').split('.').pop()
  const bareLabel = labels && typeof labels === 'object' ? labels[bare] : null
  if (typeof bareLabel === 'string' && bareLabel.trim()) return bareLabel.trim()
  const words = bare
    .replace(/([a-z0-9])([A-Z])/g, '$1 $2')
    .split(/[_\s$]+/)
    .filter(Boolean)
    .map((w) => (w.length <= 2 && w === w.toUpperCase() && /[A-Z]/.test(w) ? w : w.toLowerCase()))
  if (!words.length) return raw
  const text = words.join(' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}

// Which params of a step name a column ('list' = a ", "-joined list of columns).
const COLUMN_PARAMS = {
  filter_eq: [0], filter_neq: [0], filter_gt: [0], filter_gte: [0], filter_lt: [0],
  filter_lte: [0], filter_in: [0], filter_notin: [0], filter_between: [0],
  filter_null: [0], filter_notnull: [0], filter_like: [0],
  agg_sum: [0], agg_avg: [0], agg_min: [0], agg_max: [0], agg_count: [0],
  agg_count_distinct: [0], calc_ratio: [0, 1], calc_diff: [0, 1], calc_share: [0],
  group: 'list',
}

/**
 * calcStepArgs with every column param worded for the business user
 * (humanizeColumn). Literals, values and advanced fragments stay verbatim.
 */
export function businessStepArgs(step, labels) {
  const kind = step && typeof step.kind === 'string' ? step.kind : ''
  const which = COLUMN_PARAMS[kind]
  if (!which || !Array.isArray(step.params)) return calcStepArgs(step)
  const params = step.params.map((p, i) => {
    if (p == null) return p
    if (which === 'list') {
      return i === 0 ? String(p).split(/\s*,\s*/).map((c) => humanizeColumn(c, labels)).join(', ') : p
    }
    return which.includes(i) ? humanizeColumn(p, labels) : p
  })
  return calcStepArgs({ ...step, params })
}

/**
 * Number of agent conditions NOT reproduced by the interactive view (0 when
 * the verification block is absent or clean). Honesty rule §9: dropped
 * elements are COUNTED and listed, never hidden - so take the max of the
 * numeric counter and the display list (the advanced/unmapped fragments may
 * be listed without being counted as predicates).
 */
export function droppedNote(verification) {
  if (!verification) return 0
  const n = Number(verification.dropped_predicates)
  const counted = Number.isFinite(n) && n > 0 ? Math.floor(n) : 0
  const listed = Array.isArray(verification.dropped_display)
    ? verification.dropped_display.length
    : 0
  return Math.max(counted, listed)
}
