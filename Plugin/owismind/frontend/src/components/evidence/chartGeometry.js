// chartGeometry.js — pure SVG geometry computation for artifact charts.
// No Vue imports — this module is fully testable with node:test.
// Given a chart spec + data, returns a structured geometry object for rendering.
// All math lives here; the Vue component only renders the returned values.

// Fixed viewBox dimensions shared across all chart types.
const VB_W = 640
const VB_H = 360

// Layout constants (pixels in viewBox space)
const PAD_LEFT = 60 // room for y-axis labels
const PAD_RIGHT = 20
const PAD_TOP = 24
const PAD_BOTTOM = 52 // room for x-axis labels
const PLOT_W = VB_W - PAD_LEFT - PAD_RIGHT
const PLOT_H = VB_H - PAD_TOP - PAD_BOTTOM

// Category/point caps to avoid overcrowded charts
const CAP_CATEGORIES = 60
const CAP_PIE_SLICES = 12

// Fail fast with a structured reason (the component shows an honest empty state).
function fail(reason) {
  return { ok: false, reason }
}

// Resolve a column name (case-insensitive) to its index in a columns array.
// Returns -1 if not found.
function resolveCol(columns, name) {
  if (!name || !Array.isArray(columns)) return -1
  const target = String(name).toLowerCase()
  return columns.findIndex((c) => String(c).toLowerCase() === target)
}

// Coerce a cell value to a finite number. Returns 0 for non-numeric / null / undefined.
function toNum(v) {
  if (v == null) return 0
  const n = typeof v === 'number' ? v : Number(v)
  return Number.isFinite(n) ? n : 0
}

// Format a number for y-axis labels — abbreviate large values for readability.
function fmtY(v) {
  const abs = Math.abs(v)
  if (abs >= 1e9) return (v / 1e9).toFixed(1).replace(/\.0$/, '') + 'B'
  if (abs >= 1e6) return (v / 1e6).toFixed(1).replace(/\.0$/, '') + 'M'
  if (abs >= 1e3) return (v / 1e3).toFixed(1).replace(/\.0$/, '') + 'K'
  if (!Number.isInteger(v)) return v.toFixed(2)
  return String(v)
}

// Truncate a long label for axis tick display.
function fmtLabel(s, max) {
  const str = s == null ? '' : String(s)
  return str.length > max ? str.slice(0, max - 1) + '…' : str
}

// Build a nice y-axis scale: returns { min, max, step, ticks: [number] }.
function niceScale(dataMin, dataMax, targetTicks = 5) {
  const range = dataMax - dataMin || 1
  const rough = range / (targetTicks - 1)
  const mag = Math.pow(10, Math.floor(Math.log10(rough)))
  const steps = [1, 2, 2.5, 5, 10]
  let step = steps.find((s) => s * mag >= rough) * mag
  if (!step) step = 10 * mag
  const niceMin = dataMin >= 0 ? 0 : Math.floor(dataMin / step) * step
  const niceMax = Math.ceil(dataMax / step) * step
  const ticks = []
  for (let t = niceMin; t <= niceMax + step * 0.001; t += step) {
    ticks.push(Math.round(t * 1e9) / 1e9) // fix floating point dust
  }
  return { min: niceMin, max: niceMax, step, ticks }
}

// ─── LINE CHART ─────────────────────────────────────────────────────────────

function buildLine({ columns, rows, x, y }) {
  const xi = resolveCol(columns, x)
  if (xi < 0) return fail('x column not found: ' + x)
  const yIndices = y.map((yc) => resolveCol(columns, yc))
  if (yIndices.some((i) => i < 0)) return fail('y column not found: ' + y.find((_, i) => yIndices[i] < 0))

  const capped = rows.slice(0, CAP_CATEGORIES)

  // Extract and coerce y values per series
  const series = yIndices.map((yi, si) => ({
    key: y[si],
    values: capped.map((row) => toNum(row[yi])),
  }))

  // Check that at least one series has non-zero data
  const hasData = series.some((s) => s.values.some((v) => v !== 0))
  if (!hasData && capped.length === 0) return fail('no rows')

  const allValues = series.flatMap((s) => s.values)
  const scale = niceScale(Math.min(0, ...allValues), Math.max(...allValues))

  const xLabels = capped.map((row) => fmtLabel(row[xi], 12))

  // Map data → SVG coordinates
  const n = capped.length
  function mapX(i) {
    if (n <= 1) return PAD_LEFT + PLOT_W / 2
    return PAD_LEFT + (i / (n - 1)) * PLOT_W
  }
  function mapY(v) {
    const range = scale.max - scale.min || 1
    return PAD_TOP + PLOT_H - ((v - scale.min) / range) * PLOT_H
  }

  const polylines = series.map((s) => ({
    key: s.key,
    points: s.values.map((v, i) => mapX(i) + ',' + mapY(v)).join(' '),
    // Dots for each point (small circle cx/cy)
    dots: s.values.map((v, i) => ({ cx: mapX(i), cy: mapY(v), value: v })),
  }))

  // X-axis ticks: evenly spaced, capped to avoid overlap
  const xTickStep = n <= 12 ? 1 : Math.ceil(n / 12)
  const xTicks = capped
    .map((_, i) => i)
    .filter((i) => i % xTickStep === 0 || i === n - 1)
    .map((i) => ({ x: mapX(i), label: xLabels[i], i }))

  // Y-axis ticks
  const yTicks = scale.ticks.map((v) => ({ y: mapY(v), label: fmtY(v), v }))

  // Zero line (useful when scale crosses 0)
  const zeroY = scale.min <= 0 && scale.max >= 0 ? mapY(0) : null

  return {
    ok: true,
    type: 'line',
    viewBox: `0 0 ${VB_W} ${VB_H}`,
    pad: { left: PAD_LEFT, right: PAD_RIGHT, top: PAD_TOP, bottom: PAD_BOTTOM },
    plotW: PLOT_W, plotH: PLOT_H,
    polylines,
    xTicks,
    yTicks,
    zeroY,
    scale,
    truncated: rows.length > CAP_CATEGORIES,
    series: series.map((s) => s.key),
  }
}

// ─── BAR CHART ──────────────────────────────────────────────────────────────

function buildBar({ columns, rows, x, y }) {
  const xi = resolveCol(columns, x)
  if (xi < 0) return fail('x column not found: ' + x)
  const yIndices = y.map((yc) => resolveCol(columns, yc))
  if (yIndices.some((i) => i < 0)) return fail('y column not found: ' + y.find((_, i) => yIndices[i] < 0))

  const capped = rows.slice(0, CAP_CATEGORIES)
  if (capped.length === 0) return fail('no rows')

  const series = yIndices.map((yi, si) => ({
    key: y[si],
    values: capped.map((row) => toNum(row[yi])),
  }))

  const allValues = series.flatMap((s) => s.values)
  const scale = niceScale(Math.min(0, ...allValues), Math.max(...allValues))

  const xLabels = capped.map((row) => fmtLabel(row[xi], 10))
  const n = capped.length
  const S = series.length // number of y series (grouped bars)

  const groupW = PLOT_W / n
  const barPad = groupW * 0.15 // outer padding per group
  const barW = (groupW - barPad * 2) / S

  function mapY(v) {
    const range = scale.max - scale.min || 1
    return PAD_TOP + PLOT_H - ((v - scale.min) / range) * PLOT_H
  }
  const zeroY = mapY(Math.max(scale.min, 0))

  const bars = series.map((s, si) => ({
    key: s.key,
    rects: s.values.map((v, i) => {
      const groupX = PAD_LEFT + i * groupW
      const bx = groupX + barPad + si * barW
      const by = v >= 0 ? mapY(v) : zeroY
      const bh = Math.abs(mapY(v) - zeroY)
      return { x: bx, y: by, width: barW, height: Math.max(bh, 1), value: v }
    }),
  }))

  // X-axis ticks: center of each group
  const xTickStep = n <= 14 ? 1 : Math.ceil(n / 14)
  const xTicks = xLabels
    .map((label, i) => ({ x: PAD_LEFT + i * groupW + groupW / 2, label, i }))
    .filter(({ i }) => i % xTickStep === 0 || i === n - 1)

  const yTicks = scale.ticks.map((v) => ({ y: mapY(v), label: fmtY(v), v }))

  return {
    ok: true,
    type: 'bar',
    viewBox: `0 0 ${VB_W} ${VB_H}`,
    pad: { left: PAD_LEFT, right: PAD_RIGHT, top: PAD_TOP, bottom: PAD_BOTTOM },
    plotW: PLOT_W, plotH: PLOT_H,
    bars,
    xTicks,
    yTicks,
    zeroY,
    scale,
    truncated: rows.length > CAP_CATEGORIES,
    series: series.map((s) => s.key),
  }
}

// ─── PIE CHART ──────────────────────────────────────────────────────────────

function buildPie({ columns, rows, x, y }) {
  // Pie uses first y column only
  const yCol = y[0]
  const xi = resolveCol(columns, x)
  const yi = resolveCol(columns, yCol)
  if (yi < 0) return fail('y column not found: ' + yCol)

  const allSlices = rows.map((row) => ({
    label: xi >= 0 ? fmtLabel(row[xi], 18) : '',
    value: toNum(row[yi]),
  }))

  // Drop zero/negative slices (a pie wedge with negative area is meaningless)
  const positive = allSlices.filter((s) => s.value > 0)
  if (positive.length === 0) return fail('no positive values for pie')

  // Cap slices: group the rest as "Other"
  let slices = positive
  let othersTotal = 0
  if (slices.length > CAP_PIE_SLICES) {
    // Sort descending so the capped tail is the smallest
    slices = [...slices].sort((a, b) => b.value - a.value)
    const kept = slices.slice(0, CAP_PIE_SLICES)
    othersTotal = slices.slice(CAP_PIE_SLICES).reduce((s, c) => s + c.value, 0)
    slices = kept
    if (othersTotal > 0) slices = [...slices, { label: 'Other', value: othersTotal, isOther: true }]
  }

  const total = slices.reduce((s, c) => s + c.value, 0)
  if (total === 0) return fail('total is zero')

  // SVG arc path for a wedge: center (cx,cy), radius r, start/end angles in radians.
  const cx = VB_W / 2, cy = VB_H / 2, r = Math.min(PLOT_W, PLOT_H) * 0.42

  function polarToXY(angle, radius) {
    return [
      cx + radius * Math.cos(angle - Math.PI / 2),
      cy + radius * Math.sin(angle - Math.PI / 2),
    ]
  }

  function wedgePath(startAngle, endAngle) {
    const large = endAngle - startAngle > Math.PI ? 1 : 0
    const [x1, y1] = polarToXY(startAngle, r)
    const [x2, y2] = polarToXY(endAngle, r)
    return `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${large} 1 ${x2} ${y2} Z`
  }

  let angle = 0
  const wedges = slices.map((s) => {
    const sweep = (s.value / total) * 2 * Math.PI
    const midAngle = angle + sweep / 2
    const pct = (s.value / total) * 100
    const path = wedgePath(angle, angle + sweep)
    // Label position: mid-radius for small wedges (inside would overlap)
    const labelR = r * 0.72
    const [lx, ly] = polarToXY(midAngle, labelR)
    angle += sweep
    return { label: s.label, value: s.value, pct, path, lx, ly, isOther: !!s.isOther }
  })

  return {
    ok: true,
    type: 'pie',
    viewBox: `0 0 ${VB_W} ${VB_H}`,
    cx, cy, r,
    wedges,
    total,
    truncated: positive.length > CAP_PIE_SLICES,
    series: [yCol],
  }
}

// ─── PUBLIC API ─────────────────────────────────────────────────────────────

/**
 * Build SVG-ready geometry for a chart artifact.
 *
 * @param {object} spec
 * @param {string} spec.type - 'line' | 'bar' | 'pie'
 * @param {string[]} spec.columns - column names from meta.result
 * @param {Array[]} spec.rows - data rows from meta.result
 * @param {string} spec.x - x-axis column name (case-insensitive match)
 * @param {string[]} spec.y - array of y-axis column names (case-insensitive match)
 * @returns {{ ok: boolean, reason?: string, type: string, ... }}
 */
export function buildChartGeometry({ type, columns, rows, x, y }) {
  if (!Array.isArray(columns) || columns.length === 0) return fail('no columns')
  if (!Array.isArray(rows)) return fail('no rows data')
  if (!Array.isArray(y) || y.length === 0) return fail('no y columns specified')

  switch (type) {
    case 'line': return buildLine({ columns, rows, x, y })
    case 'bar':  return buildBar({ columns, rows, x, y })
    case 'pie':  return buildPie({ columns, rows, x, y })
    default:     return fail('unknown chart type: ' + type)
  }
}
