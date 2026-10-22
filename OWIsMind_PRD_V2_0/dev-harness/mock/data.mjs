// Synthetic datasets + a tiny in-memory query engine for the OWIsMind dev harness.
//
// Everything here is FAKE and generated deterministically (seeded PRNG): no real
// account, revenue or ticket ever appears. The engine mimics the SHAPES the real
// backend computes over PostgreSQL (structured filters, accent-folded search,
// DB-side aggregation, bounded distinct) so the frontend behaves exactly as in DSS.

// --- deterministic PRNG (mulberry32) -----------------------------------------
export function mulberry32(seed) {
  let a = seed >>> 0
  return function () {
    a |= 0
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// --- synthetic revenue base (mirrors the DRIVE_Revenues column families) ------
const ACCOUNTS = [
  { name: 'Global Telecom Partners', code: 'GTP', country: 'Germany' },
  { name: 'Nordic Carrier AB', code: 'NCA', country: 'Sweden' },
  { name: 'Iberia Connect SA', code: 'IBC', country: 'Spain' },
  { name: 'Pacific Wholesale Ltd', code: 'PWL', country: 'Australia' },
  { name: 'Atlantic Networks Inc', code: 'ANI', country: 'United States' },
  { name: 'Sahara Telecom Group', code: 'STG', country: 'Morocco' },
  { name: 'Danube Mobile Kft', code: 'DMK', country: 'Hungary' },
  { name: 'Levant Communications', code: 'LVC', country: 'Jordan' },
]

const SOLUTIONS = [
  { solution: 'Voice Termination', line: 'Voice', product: 'International Voice' },
  { solution: 'SMS A2P', line: 'Messaging', product: 'A2P Gateway' },
  { solution: 'Roaming Data', line: 'Mobility', product: 'Data Roaming Sponsored' },
  { solution: 'IPX Transit', line: 'Data', product: 'IPX Premium' },
  { solution: 'Capacity Leasing', line: 'Infrastructure', product: 'Submarine Capacity' },
]

const MONTHS = [1, 2, 3, 4, 5, 6, 7, 8] // 2026 year-to-date in the mock

export const REVENUE_COLUMNS = [
  { name: 'diamond_id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'carrier_code', type: 'string' },
  { name: 'Country', type: 'string' },
  { name: 'Product', type: 'string' },
  { name: 'Solution', type: 'string' },
  { name: 'SolutionLine', type: 'string' },
  { name: 'Phase', type: 'string' },
  { name: 'Year', type: 'bigint' },
  { name: 'Month', type: 'bigint' },
  { name: 'Snapshot_date', type: 'date' },
  { name: 'Revenues', type: 'double' },
]

function buildRevenues() {
  const rng = mulberry32(20260813)
  const rows = []
  let id = 100000
  for (const account of ACCOUNTS) {
    for (const sol of SOLUTIONS) {
      // A stable base amount per (account, solution) pair, in EUR / month.
      const base = 40000 + rng() * 260000
      for (const month of MONTHS) {
        const season = 1 + 0.12 * Math.sin((month / 12) * Math.PI * 2)
        const budget = base * season * (0.95 + rng() * 0.15)
        const actual = base * season * (0.82 + rng() * 0.34)
        const date = `2026-${String(month).padStart(2, '0')}-01`
        for (const [phase, amount] of [
          ['ACTUALS', actual],
          ['BUDGET', budget],
        ]) {
          rows.push({
            diamond_id: ++id,
            Account_name: account.name,
            carrier_code: account.code,
            Country: account.country,
            Product: sol.product,
            Solution: sol.solution,
            SolutionLine: sol.line,
            Phase: phase,
            Year: 2026,
            Month: month,
            Snapshot_date: date,
            Revenues: Math.round(amount * 100) / 100,
          })
        }
      }
    }
  }
  return rows
}

export const REVENUES = buildRevenues()

// --- synthetic trouble tickets (second source dataset) ------------------------
export const TICKET_COLUMNS = [
  { name: 'id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'Severity', type: 'string' },
  { name: 'Status', type: 'string' },
  { name: 'Category', type: 'string' },
  { name: 'creationDate', type: 'date' },
  { name: 'Duration_ticket_total', type: 'double' },
]

const SEVERITIES = ['P1', 'P2', 'P3', 'P4']
const STATUSES = ['Open', 'In Progress', 'Resolved', 'Closed']
const CATEGORIES = ['Quality of Service', 'Billing Dispute', 'Provisioning', 'Outage', 'Routing']

function buildTickets() {
  const rng = mulberry32(20260901)
  const rows = []
  let id = 500000
  for (const account of ACCOUNTS) {
    const count = 10 + Math.floor(rng() * 12)
    for (let i = 0; i < count; i++) {
      const month = 1 + Math.floor(rng() * 8)
      const day = 1 + Math.floor(rng() * 27)
      rows.push({
        id: ++id,
        Account_name: account.name,
        Severity: SEVERITIES[Math.floor(rng() * SEVERITIES.length)],
        Status: STATUSES[Math.floor(rng() * STATUSES.length)],
        Category: CATEGORIES[Math.floor(rng() * CATEGORIES.length)],
        creationDate: `2026-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`,
        Duration_ticket_total: Math.round(rng() * 4800 * 10) / 10,
      })
    }
  }
  return rows
}

export const TICKETS = buildTickets()

// --- tiny query engine (mirrors the backend's SQL shapes) ----------------------

// Accent-folded, lowercased text for the free-text search (mirrors the backend's
// accent-folded ILIKE).
function fold(value) {
  return String(value == null ? '' : value)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
}

function toNumber(value) {
  if (value == null) return null
  const n = Number(value)
  return Number.isFinite(n) ? n : null
}

// Loose equality used by filters: '2026' matches 2026 (values travel as strings).
function looseEq(cell, value) {
  if (cell === value) return true
  return String(cell) === String(value)
}

function compare(cell, value) {
  const cn = toNumber(cell)
  const vn = toNumber(value)
  if (cn != null && vn != null) return cn - vn
  const cs = String(cell == null ? '' : cell)
  const vs = String(value == null ? '' : value)
  return cs < vs ? -1 : cs > vs ? 1 : 0
}

// One structured filter {column, op, values} applied to one row. Supported ops
// mirror what the real validators accept from the chips.
function matchFilter(row, filter) {
  const cell = row[filter.column]
  const values = filter.values || []
  switch ((filter.op || '=').toUpperCase()) {
    case '=':
      return values.length ? looseEq(cell, values[0]) : true
    case '!=':
    case '<>':
      return values.length ? !looseEq(cell, values[0]) : true
    case 'IN':
      return values.some((v) => looseEq(cell, v))
    case 'NOT IN':
      return !values.some((v) => looseEq(cell, v))
    case '>':
      return values.length ? compare(cell, values[0]) > 0 : true
    case '>=':
      return values.length ? compare(cell, values[0]) >= 0 : true
    case '<':
      return values.length ? compare(cell, values[0]) < 0 : true
    case '<=':
      return values.length ? compare(cell, values[0]) <= 0 : true
    case 'BETWEEN':
      return values.length >= 2
        ? compare(cell, values[0]) >= 0 && compare(cell, values[1]) <= 0
        : true
    case 'IS NULL':
      return cell == null || cell === ''
    case 'IS NOT NULL':
      return cell != null && cell !== ''
    case 'LIKE':
      return values.length ? fold(cell).includes(fold(String(values[0]).replace(/%/g, ''))) : true
    default:
      return true
  }
}

export function applyFilters(rows, filters) {
  const list = (filters || []).filter((f) => f && f.column)
  if (!list.length) return rows
  return rows.filter((row) => list.every((f) => matchFilter(row, f)))
}

// Free-text search over EVERY column (accent-folded), mirroring the backend.
export function applySearch(rows, q) {
  const term = fold(q || '').trim()
  if (term.length < 2) return rows
  return rows.filter((row) => Object.values(row).some((v) => fold(v).includes(term)))
}

// Drill labels [{column, value}] -> strict equality / IS NULL conditions.
export function applyDrill(rows, drill) {
  const list = (drill || []).filter((d) => d && d.column)
  if (!list.length) return rows
  return rows.filter((row) =>
    list.every((d) => (d.value == null ? row[d.column] == null : looseEq(row[d.column], d.value)))
  )
}

export function sortRows(rows, sort) {
  if (!sort || !sort.column) return rows
  const dir = sort.dir === 'desc' ? -1 : 1
  return [...rows].sort((a, b) => dir * compare(a[sort.column], b[sort.column]))
}

export function paginate(rows, limit, offset) {
  const lim = Math.max(1, Math.min(Number(limit) || 100, 100))
  const off = Math.max(0, Math.min(Number(offset) || 0, 5000))
  const page = rows.slice(off, off + lim)
  return { rows: page, has_more: rows.length > off + lim, offset: off }
}

// --- aggregation (the "Calculate" zone + totals bar + Analyze mini-pivot) ------

function computeMeasure(rows, measure) {
  const fn = measure.fn
  if (fn === 'count') return rows.length
  const col = measure.column
  const raw = rows.map((r) => r[col]).filter((v) => v != null && v !== '')
  if (fn === 'count_distinct') return new Set(raw.map((v) => String(v))).size
  const nums = raw.map(toNumber).filter((v) => v != null)
  if (fn === 'min' || fn === 'max') {
    if (!raw.length) return null
    if (nums.length === raw.length) {
      return fn === 'min' ? Math.min(...nums) : Math.max(...nums)
    }
    const sorted = [...raw].sort((a, b) => compare(a, b))
    return fn === 'min' ? sorted[0] : sorted[sorted.length - 1]
  }
  if (!nums.length) return null
  if (fn === 'sum') return round2(nums.reduce((a, b) => a + b, 0))
  if (fn === 'avg') return round2(nums.reduce((a, b) => a + b, 0) / nums.length)
  if (fn === 'median') {
    const sorted = [...nums].sort((a, b) => a - b)
    const mid = Math.floor(sorted.length / 2)
    return round2(sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2)
  }
  return null
}

function round2(n) {
  return Math.round(n * 100) / 100
}

function bucketValue(value, bucket) {
  const s = String(value == null ? '' : value)
  const m = s.match(/^(\d{4})-(\d{2})/)
  if (!m) return s
  if (bucket === 'year') return m[1]
  if (bucket === 'quarter') return `${m[1]}-Q${Math.ceil(Number(m[2]) / 3)}`
  return `${m[1]}-${m[2]}` // month
}

// {rows, totals, truncated} with the exact /aggregate contract:
//   group null -> rows = [{m0, m1, ...}] (one row), totals = null
//   group set  -> rows = [{key, m0, ...}] ordered, totals = {m0, ...}, truncated flag
export function aggregate(rows, group, measures, limit) {
  const specs = (measures || []).slice(0, 8)
  if (!specs.length) return { rows: [], totals: null, truncated: false }
  const asRow = (subset) => {
    const out = {}
    specs.forEach((m, i) => {
      out['m' + i] = computeMeasure(subset, m)
    })
    return out
  }
  if (!group || !group.column) {
    return { rows: [asRow(rows)], totals: null, truncated: false }
  }
  const byKey = new Map()
  for (const row of rows) {
    const raw = row[group.column]
    const key = group.bucket ? bucketValue(raw, group.bucket) : raw
    const k = key == null ? null : key
    if (!byKey.has(k)) byKey.set(k, [])
    byKey.get(k).push(row)
  }
  let grouped = [...byKey.entries()].map(([key, subset]) => ({ key, ...asRow(subset) }))
  // Order by the first measure descending when numeric, else by key ascending -
  // matching the backend's ordered group rows.
  grouped.sort((a, b) => {
    const an = toNumber(a.m0)
    const bn = toNumber(b.m0)
    if (an != null && bn != null && an !== bn) return bn - an
    return compare(a.key, b.key)
  })
  const cap = Math.max(1, Math.min(Number(limit) || 50, 50))
  const truncated = grouped.length > cap
  return { rows: grouped.slice(0, cap), totals: asRow(rows), truncated }
}

export function distinctValues(rows, column, q, cap = 50) {
  const term = fold(q || '').trim()
  const seen = new Set()
  const values = []
  for (const row of rows) {
    const v = row[column]
    if (v == null || v === '') continue
    const s = String(v)
    if (term && !fold(s).includes(term)) continue
    if (seen.has(s)) continue
    seen.add(s)
    values.push(v)
    if (values.length > cap) break
  }
  const truncated = values.length > cap
  return { values: values.slice(0, cap), truncated }
}
