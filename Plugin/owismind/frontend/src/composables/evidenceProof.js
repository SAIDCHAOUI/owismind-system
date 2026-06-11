// Pure Evidence "trust layer" helpers (NO Vue import — node:test testable, F11).
//
// These helpers turn the enriched /evidence/meta contract (frozen in
// docs/superpowers/specs/2026-06-10-evidence-trust-layer-design.md §2) into
// display-ready primitives for the proof sections of the Evidence panel.
// Every new meta field is OPTIONAL: a v1 meta (or a degraded/absent one) must
// fall through to the honest "declared" floor — never throw, never guess up.
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

// Max calc steps ever rendered — mirrors the backend's ≤ 15 steps contract so
// a malformed payload cannot flood the panel.
export const MAX_CALC_STEPS = 15

/**
 * Map the verification verdict onto the trust badge: {key, tone}.
 *
 * (level × result_captured) grammar — frozen in spec §6:
 *   calc_decomposed + captured        -> ev.proof.level.result   (solid)
 *   calc_decomposed | scope_exact     -> ev.proof.level.source   (solid)
 *   scope_partial | source_identified -> ev.proof.level.partial  (dashed)
 *   declared / anything else          -> ev.proof.level.declared (muted)
 *
 * Exhaustive fallback: absent meta, degraded meta (available === false),
 * missing verification block or an UNKNOWN level string all land on
 * `declared` — the floor is the honest claim, never an upgrade.
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

/**
 * Bounded preview of the captured agent result for the mini-table:
 * {columns, rows, more}. `rows` keeps at most `maxRows` list-shaped rows
 * (cell values untouched — the display layer stringifies, keeping null as
 * '—'); `more` counts the hidden remainder. Shape-defensive: anything that
 * is not the contract's list-of-lists yields the empty preview, never throws.
 */
export function resultPreview(result, maxRows = 10) {
  const empty = { columns: [], rows: [], more: 0 }
  if (!result || !Array.isArray(result.rows)) return empty
  const cap = Number.isInteger(maxRows) && maxRows > 0 ? maxRows : 10
  const columns = Array.isArray(result.columns) ? result.columns.map((c) => String(c)) : []
  // Drop non-list rows: the drill action indexes meta.result.rows by the
  // PREVIEW row index, so the preview must be a clean prefix of valid rows.
  const valid = result.rows.filter((r) => Array.isArray(r))
  return {
    columns,
    rows: valid.slice(0, cap),
    more: Math.max(0, valid.length - cap),
  }
}

/**
 * Number of agent conditions NOT reproduced by the interactive view (0 when
 * the verification block is absent or clean). Honesty rule §9: dropped
 * elements are COUNTED and listed, never hidden — so take the max of the
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
