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

// ============================ Presentation helpers ==========================
// Pure display-logic moved out of the view so it is unit-tested with node:test.
// None of these touch Vue / i18n: they return stable string kinds / token
// expressions / widths the template maps to a class or an inline style. The backend
// always stamps a mode on every scored row (Smart|Pro|Claude), so "single mode"
// is a VIEW concern derived from the configs, not a backend flag.

// The set of DISTINCT modes present across the configurations (lower-cased, blanks
// dropped). A benchmark that ran a single configuration therefore has one mode.
export function distinctModes(results) {
  const configs = results && Array.isArray(results.configs) ? results.configs : []
  const set = new Set()
  configs.forEach((c) => {
    const m = String((c && c.mode) || '').trim().toLowerCase()
    if (m) set.add(m)
  })
  return set
}

// Whether more than one mode is actually benchmarked. Drives the conditional mode
// badges / legend / KPI tile: when false the mode apparatus is noise and is hidden.
export function hasMultipleModes(results) {
  return distinctModes(results).size > 1
}

// Confidence band -> hero verdict pill kind (good / mid / bad), unknown = plaus.
export function heroVerdictKind(band) {
  const b = String(band || '').toLowerCase()
  if (b === 'high') return 'good'
  if (b === 'medium') return 'mid'
  if (b === 'low') return 'bad'
  return 'plaus'
}

// Mode name -> badge class (Smart green, Pro orange, Claude red, else standard grey).
export function modeClass(mode) {
  const m = String(mode || '').toLowerCase()
  if (m === 'smart') return 'mode-smart'
  if (m === 'pro') return 'mode-pro'
  if (m === 'claude') return 'mode-claude'
  return 'mode-default'
}

// Mode name -> dot color token expression (used via :style, never an HTML/SVG attribute).
export function modeColor(mode) {
  const m = String(mode || '').toLowerCase()
  if (m === 'smart') return 'var(--success)'
  if (m === 'pro') return 'var(--orange)'
  if (m === 'claude') return 'var(--danger)'
  return 'var(--text-3)'
}

// Mode name -> display label (backend supplies the display casing; blank -> Standard).
export function modeLabel(mode) {
  const m = String(mode == null ? '' : mode).trim()
  return m || 'Standard'
}

// Per-question result pill kind, from the EFFECTIVE verdict: ok / bad / plaus.
export function resultPillKind(row) {
  const k = verdictKind(row)
  if (k === 'correct') return 'ok'
  if (k === 'incorrect') return 'bad'
  return 'plaus'
}

// A stable left-rail accent for a question line: 'danger' when the effective verdict
// is incorrect, 'warn' when it still needs a human review, else '' (no accent).
export function rowAccentKind(row) {
  const k = verdictKind(row)
  if (k === 'incorrect') return 'danger'
  if (k === 'review' || (row && row.needs_review)) return 'warn'
  return ''
}

// A 0..1 accuracy fraction -> a CSS width string for a meter bar.
export function meterWidth(acc) {
  return pctFromAccuracy(acc) + '%'
}
// Category accuracy -> meter width (same geometry, reads cat.accuracy defensively).
export function catWidth(cat) {
  return pctFromAccuracy(cat && cat.accuracy) + '%'
}

// --- Evolution (attempt history) -------------------------------------------
const EVOLUTION_KINDS = ['improved', 'regressed', 'same', 'first']
// Trend of the latest attempt vs the previous one, '' when absent / unknown.
export function evolutionKind(row) {
  const d = String((row && row.delta) || '').toLowerCase()
  return EVOLUTION_KINDS.indexOf(d) >= 0 ? d : ''
}
// Trend -> pill class (improved = up, regressed = down, same / first = flat).
export function evolutionClass(row) {
  const k = evolutionKind(row)
  if (k === 'improved') return 'evo-up'
  if (k === 'regressed') return 'evo-down'
  return 'evo-flat'
}
// How many attempts this question has accumulated in the benchmark (>= 1).
export function attemptCount(row) {
  const n = Number(row && row.n_attempts)
  return Number.isFinite(n) && n > 0 ? n : 1
}
// The ordered attempt history (oldest -> newest), defensive against a missing array.
export function attemptHistory(row) {
  return row && Array.isArray(row.attempts) ? row.attempts : []
}
// One attempt's verdict pill kind (ok / bad / plaus), folding any override.
export function attemptPillKind(att) {
  if (!att || typeof att !== 'object') return 'plaus'
  if (att.correct === true) return 'ok'
  if (att.correct === false) return 'bad'
  const v = String(att.verdict || '').toLowerCase()
  if (v === 'correct') return 'ok'
  if (v === 'incorrect') return 'bad'
  return 'plaus'
}

// The agent's actual tools for one row -> a readable comma list (or '').
export function actualToolsText(row) {
  const v = row && row.actual_tools
  if (Array.isArray(v)) return v.filter((x) => x != null && String(x).trim()).join(', ')
  return v != null ? String(v).trim() : ''
}
// Whether a row carries any reference-vs-produced material worth its own tab.
export function hasRefVsActual(row) {
  if (!row) return false
  return !!(row.expected_sql || row.expected_tool || actualToolsText(row))
}
// The golden expected value + optional type in parentheses, '' when absent.
export function expectedText(row) {
  if (!row || row.expected_value == null || row.expected_value === '') return ''
  const ty = row.expected_value_type ? ' (' + row.expected_value_type + ')' : ''
  return String(row.expected_value) + ty
}
// A judge score (0..5) formatted to 2 decimals, '-' when not a finite number.
export function fmtScore(v) {
  return typeof v === 'number' && Number.isFinite(v) ? v.toFixed(2) : '-'
}

// Whether a captured result cell should be treated as a number (for right-alignment).
export function cellIsNumeric(cell) {
  return typeof cell === 'number' && Number.isFinite(cell)
}
// Format one captured result cell: group large magnitudes / decimals with the
// locale separators (revenue amounts read cleanly), but leave years / small ids /
// counts and any non-number literal untouched. Never throws.
export function formatCell(cell, locale = 'en') {
  if (cell == null) return ''
  if (typeof cell === 'number' && Number.isFinite(cell)) {
    if (Math.abs(cell) >= 10000 || !Number.isInteger(cell)) {
      try {
        return cell.toLocaleString(locale)
      } catch (e) {
        return String(cell)
      }
    }
    return String(cell)
  }
  return String(cell)
}
