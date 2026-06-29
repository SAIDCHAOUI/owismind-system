// Pure benchmark-results helpers (no Vue) - the donut geometry, the band -> token
// mapping, the per-question verdict resolution and a defensive normalizer for the
// RESULTS payload. Kept framework-free so it is unit-testable with node:test
// (mirrors budgetModel.js / timelineModel.js). The backend is the source of truth
// for every number; these helpers only DERIVE the presentational bits and guard
// against a missing / malformed payload so the consultation view never crashes.

// A finite number from a backend value (missing / garbage -> fallback).
function num(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

// Clamp a percent into [0, 100].
export function clampPct(value) {
  const n = num(value)
  return Math.max(0, Math.min(100, n))
}

// Percent (0..100) from a 0..1 accuracy fraction.
export function pctFromAccuracy(accuracy) {
  return clampPct(num(accuracy) * 100)
}

// SVG donut geometry for a circle of radius `r`: the full circumference plus the
// stroke-dashoffset that leaves only `pct`% of the ring drawn. Used with
// stroke-dasharray = circumference and a -90deg rotation so the arc starts at top.
export function donutGeometry(pct, r = 52) {
  const radius = num(r, 52)
  const circumference = 2 * Math.PI * radius
  const filled = clampPct(pct) / 100
  return {
    r: radius,
    circumference,
    offset: circumference * (1 - filled),
  }
}

// Confidence band -> a CSS token expression for the donut stroke. The charter allows
// the orange / success / danger tokens for the band: high = success (green), medium =
// orange (brand accent), low = danger (red); anything unknown stays neutral.
export function bandToken(band) {
  switch (String(band || '').toLowerCase()) {
    case 'high':
      return 'var(--success)'
    case 'medium':
      return 'var(--orange)'
    case 'low':
      return 'var(--danger)'
    default:
      return 'var(--text-3)'
  }
}

// The EFFECTIVE verdict of one detail row, folding in any admin override the backend
// already resolved (effective_correct / effective_verdict), falling back to the raw
// judge correctness and the needs-review flag. Returns a stable kind the view maps to
// an i18n label + a color: 'correct' | 'incorrect' | 'review' | 'unknown'.
export function verdictKind(row) {
  if (!row || typeof row !== 'object') return 'unknown'
  const ec = row.effective_correct
  if (ec === true) return 'correct'
  if (ec === false) return 'incorrect'
  const v = String(row.effective_verdict || '').toLowerCase()
  if (v === 'correct') return 'correct'
  if (v === 'incorrect') return 'incorrect'
  if (row.needs_review) return 'review'
  if (row.correct === true) return 'correct'
  if (row.correct === false) return 'incorrect'
  return 'unknown'
}

// Display string for a percent value: prefer the backend's own *_pct (a number we
// round, or a pre-formatted string), else a dash.
export function pctText(value) {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.round(value) + '%'
  if (typeof value === 'string' && value.trim()) return value.trim()
  return '-'
}

// A stable key for one detail row. Detail is the LATEST attempt per
// (question_id, agent_key, mode) inside the selected benchmark, so this triplet stays
// unique. Used as the v-for key, the expand-state key and the override-comment key.
export function rowKey(row) {
  const r = row || {}
  return [r.question_id, r.agent_key, r.mode].map((x) => (x == null ? '' : String(x))).join('::')
}

// Defensive normalizer: coerce the RESULTS payload into a stable shape with safe
// defaults so the template can render it without optional-chaining everything. Numbers
// are coerced; the pre-formatted strings + the *_pct fields are passed through verbatim
// (the backend localizes / formats them already).
export function normalizeResults(raw) {
  const r = raw && typeof raw === 'object' ? raw : {}
  const k = r.kpis && typeof r.kpis === 'object' ? r.kpis : {}
  return {
    // A benchmark is the unit of consultation now (it spans many runs). `benchmarks` is
    // the selector list; the detail rows each carry their own run_id / attempt history.
    benchmark_id: r.benchmark_id != null ? String(r.benchmark_id) : '',
    benchmark_name: r.benchmark_name != null ? String(r.benchmark_name) : '',
    benchmarks: Array.isArray(r.benchmarks) ? r.benchmarks : [],
    kpis: {
      accuracy: num(k.accuracy),
      accuracy_pct: k.accuracy_pct,
      n_correct: num(k.n_correct),
      n_scored: num(k.n_scored),
      band: k.band || '',
      n_questions: num(k.n_questions),
      n_configs: num(k.n_configs),
      total_cost: num(k.total_cost),
      total_cost_str: k.total_cost_str || '',
      needs_review: num(k.needs_review),
    },
    configs: Array.isArray(r.configs) ? r.configs : [],
    categories: Array.isArray(r.categories) ? r.categories : [],
    detail: Array.isArray(r.detail) ? r.detail : [],
  }
}

// Whether a normalized RESULTS object actually carries something to show.
export function hasScoredResults(results) {
  if (!results || typeof results !== 'object') return false
  return (
    num(results.kpis && results.kpis.n_scored) > 0 ||
    (Array.isArray(results.configs) && results.configs.length > 0) ||
    (Array.isArray(results.detail) && results.detail.length > 0)
  )
}
