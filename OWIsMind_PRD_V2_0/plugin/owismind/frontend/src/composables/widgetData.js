// Widget data - the client-side twin of evidence/chart_payload.py, used ONLY while a
// run is live: the workspace widgets render as soon as the SQL they are bound to has
// streamed its captured result (generated_sql event, keyed by sqlId), before the
// backend persisted anything. Once the run is stored, GET /workspace serves the
// server-built payloads (widgets_data) and those win. Same rules as the Python
// builders (column resolution, caps, pie "Other" folding, honest {ok:false, reason}),
// so the live and the restored dashboard draw the same figures. Pure, no Vue:
// unit-tested with node:test.

export const MAX_POINTS = 200
export const MAX_SLICES = 12
const LABEL_MAX_CHARS = 80
const LEADING_NUM_RE = /^-?\d+(?:\.\d+)?/

/** Best-effort numeric coercion (mirror of chart_payload._to_number). */
export function toNumber(value) {
  if (value == null || typeof value === 'boolean') return null
  if (typeof value === 'number') return Number.isFinite(value) ? value : null
  let s = String(value).trim()
  if (!s) return null
  s = s.replace(/[\s  %€$£]/g, '')
  if (s.includes(',') && s.includes('.')) {
    s = s.lastIndexOf(',') > s.lastIndexOf('.') ? s.replace(/\./g, '').replace(',', '.') : s.replace(/,/g, '')
  } else if (s.includes(',')) {
    s = s.replace(/,/g, '.')
  }
  // Same accepted literals as Python's float() (sign, exponent, bare fraction).
  if (/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) {
    const f = Number(s)
    return Number.isFinite(f) ? f : null
  }
  const m = LEADING_NUM_RE.exec(s)
  if (!m) return null
  const f = Number(m[0])
  return Number.isFinite(f) ? f : null
}

function label(value) {
  return value == null ? '' : String(value).slice(0, LABEL_MAX_CHARS)
}

function resolve(columns, name) {
  if (!name) return -1
  const target = String(name).trim().toLowerCase()
  return columns.findIndex((c) => String(c).trim().toLowerCase() === target)
}

/**
 * Normalize a captured result as relayed by a live generated_sql event
 * ({columns, rows, truncated?}) into the /evidence/meta result block shape
 * ({captured, columns, rows, row_count, truncated}). null when nothing usable.
 */
export function capturedResult(result, rowCount) {
  if (!result || typeof result !== 'object') return null
  const columns = Array.isArray(result.columns) ? result.columns : null
  const rows = Array.isArray(result.rows) ? result.rows : null
  if (!columns || !rows) return null
  const rc = typeof rowCount === 'number' && Number.isFinite(rowCount)
    ? rowCount
    : (typeof result.row_count === 'number' ? result.row_count : rows.length)
  return { captured: true, columns, rows, row_count: rc, truncated: !!result.truncated }
}

/** Chart.js payload for one chart spec ({type, x, y[]}), or {ok:false, reason}. */
export function buildChartPayload(result, spec) {
  if (!result || !result.captured) return { ok: false, reason: 'no_data' }
  const columns = result.columns || []
  const rows = result.rows || []
  if (!columns.length || !rows.length) return { ok: false, reason: 'no_data' }
  const s = spec || {}
  // 'donut' is the contract's name for a pie drawn with the donut style.
  const ctype = s.type === 'donut' ? 'pie' : s.type
  if (!['line', 'bar', 'pie'].includes(ctype)) return { ok: false, reason: 'bad_spec' }
  let y = s.y
  if (typeof y === 'string') y = [y]
  if (!s.x || !Array.isArray(y) || !y.length) return { ok: false, reason: 'bad_spec' }
  const xi = resolve(columns, s.x)
  if (xi < 0) return { ok: false, reason: 'x_not_found' }
  const yCols = y.map((name) => [String(name), resolve(columns, name)]).filter(([, i]) => i >= 0)
  if (!yCols.length) return { ok: false, reason: 'y_not_found' }
  const capped = rows.slice(0, MAX_POINTS)
  let truncated = !!result.truncated || rows.length > MAX_POINTS
  const cell = (r, i) => (Array.isArray(r) && i < r.length ? r[i] : null)

  if (ctype === 'pie') {
    const [name, yi] = yCols[0]
    let pairs = []
    for (const r of capped) {
      const v = toNumber(cell(r, yi))
      if (v != null && v > 0) pairs.push([label(cell(r, xi)), v])
    }
    if (!pairs.length) return { ok: false, reason: 'no_numeric' }
    pairs.sort((a, b) => b[1] - a[1])
    if (pairs.length > MAX_SLICES) {
      const head = pairs.slice(0, MAX_SLICES - 1)
      const other = pairs.slice(MAX_SLICES - 1).reduce((acc, p) => acc + p[1], 0)
      head.push(['Other', other])
      pairs = head
      truncated = true
    }
    return {
      ok: true,
      label: name,
      labels: pairs.map((p) => p[0]),
      datasets: [{ label: name, data: pairs.map((p) => p[1]) }],
      truncated,
    }
  }

  const labels = capped.map((r) => label(cell(r, xi)))
  let anyNumeric = false
  const datasets = yCols.map(([name, yi]) => ({
    label: name,
    data: capped.map((r) => {
      const v = toNumber(cell(r, yi))
      if (v != null) anyNumeric = true
      return v
    }),
  }))
  if (!anyNumeric) return { ok: false, reason: 'no_numeric' }
  return { ok: true, labels, datasets, truncated }
}

/** KPI payload from the FIRST result row, or {ok:false, reason}. */
export function buildKpiPayload(result, spec) {
  if (!result || !result.captured) return { ok: false, reason: 'no_data' }
  const columns = result.columns || []
  const rows = result.rows || []
  if (!columns.length || !rows.length) return { ok: false, reason: 'no_data' }
  const s = spec || {}
  if (!s.value) return { ok: false, reason: 'bad_spec' }
  const vi = resolve(columns, s.value)
  if (vi < 0) return { ok: false, reason: 'value_not_found' }
  const row0 = rows[0] || []
  const value = vi < row0.length ? toNumber(row0[vi]) : null
  if (value == null) return { ok: false, reason: 'no_numeric' }
  const out = { ok: true, label: label(s.label || s.value), value }
  for (const key of ['delta', 'delta_pct']) {
    if (!s[key]) continue
    const ci = resolve(columns, s[key])
    if (ci >= 0 && ci < row0.length) {
      const num = toNumber(row0[ci])
      if (num != null) out[key] = num
    }
  }
  return out
}

/**
 * The render data of one widget: the server payload when the restored document
 * provides one, otherwise built from the captured result bound to its sql_id.
 * Returns { result, data } (data null for tables / text).
 */
export function widgetRenderData(widget, { serverData, result } = {}) {
  if (!widget) return { result: null, data: null }
  // No rows yet and no server payload: data stays null so the card can show its waiting
  // state (an honest {ok:false} is only built once there is something to build from).
  if (widget.kind === 'chart') return { result, data: serverData || (result ? buildChartPayload(result, widget.chart) : null) }
  if (widget.kind === 'kpi') return { result, data: serverData || (result ? buildKpiPayload(result, widget.kpi) : null) }
  return { result, data: null }
}
