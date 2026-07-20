// Pure budget/usage helpers (no Vue) - formatting + the gauge math shared by the
// profile consumption card, the chat budget banner and the admin quotas table. Kept
// framework-free so it is unit-testable with node:test (mirrors timelineModel.js).
//
// The backend is the single source of truth for the limit RESOLUTION (default / global
// temp boost / per-user override) and the blocked flag; these helpers only DERIVE the
// presentational bits (percent used, a coarse severity level, locale-aware strings).

// A safe non-negative number from a backend numeric (missing/garbage -> default).
export function toNum(value, fallback = 0) {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

// Locale-aware money string. Amounts are US dollars (the LLM-Mesh estimated cost). A
// tiny non-zero amount keeps more precision so real usage never reads as a flat "$0.00".
export function formatMoney(amount, locale = 'en', currency = '$') {
  const n = toNum(amount)
  const maxFrac = n > 0 && n < 0.01 ? 4 : 2
  return (
    currency +
    n.toLocaleString(locale, { minimumFractionDigits: 2, maximumFractionDigits: maxFrac })
  )
}

// Locale-grouped integer token count ("12,345" / "12 345").
export function formatTokens(n, locale = 'en') {
  return toNum(n).toLocaleString(locale)
}

// A short, locale-aware date (reset date / last-usage date). Empty string when absent
// or unparseable - the caller hides the line rather than show "Invalid Date".
export function formatShortDate(iso, locale = 'en') {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleDateString(locale, { year: 'numeric', month: 'short', day: 'numeric' })
}

// Percent of the monthly limit consumed (rounded; can exceed 100). A non-positive limit
// reads as fully used once anything was spent (a $0 limit = an explicit hard block).
export function usagePct(spent, limit) {
  const s = toNum(spent)
  const l = toNum(limit)
  if (l <= 0) return s > 0 ? 100 : 0
  return Math.round((s / l) * 100)
}

// The gauge fill width, clamped to [0, 100] (the bar never overflows visually even when
// spend edged past the cap before the blocking request).
export function gaugePct(spent, limit) {
  return Math.max(0, Math.min(100, usagePct(spent, limit)))
}

// Coarse severity for coloring: 'off' (enforcement disabled - tracking only), 'over'
// (blocked / at-or-past the limit), 'warn' (>= 80%), else 'ok'.
export function usageLevel(usage) {
  if (!usage) return 'ok'
  if (usage.enforced === false) return 'off'
  if (usage.blocked) return 'over'
  const pct = usagePct(usage.spent_usd, usage.limit_usd)
  if (pct >= 100) return 'over'
  if (pct >= 80) return 'warn'
  return 'ok'
}
