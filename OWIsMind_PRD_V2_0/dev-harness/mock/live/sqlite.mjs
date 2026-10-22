// node:sqlite (Node 24 built-in, nothing installed) backing of the LIVE harness:
//   - openDatasetDb : an in-memory DB with the three synthetic tables under a
//                     `public` schema (so `public."OWISMIND_DEV_..."` resolves like
//                     PostgreSQL), then switched to query_only (no write possible).
//   - guardSelect   : the agent SQL guard (one SELECT/WITH statement, no PRAGMA,
//                     ATTACH or write keyword).
//   - runSelect     : run a guarded SELECT with a row cap (stops fetching at cap).
//   - structured*   : the Source Data / Evidence engine (filters, search, sort,
//                     pagination, aggregate, distinct) as PARAMETERIZED SQL built
//                     from validated column names, mirroring mock/data.mjs shapes.

import { DatabaseSync } from 'node:sqlite'

const SQL_TYPE = { bigint: 'INTEGER', double: 'REAL', string: 'TEXT', date: 'TEXT' }

const q = (name) => '"' + String(name).replace(/"/g, '""') + '"'

function fold(value) {
  return String(value == null ? '' : value)
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
}

export function openDatasetDb(datasets) {
  const db = new DatabaseSync(':memory:')
  db.exec("ATTACH DATABASE ':memory:' AS public")
  for (const ds of datasets) {
    const cols = ds.columns.map((c) => `${q(c.name)} ${SQL_TYPE[c.type] || 'TEXT'}`).join(', ')
    db.exec(`CREATE TABLE public.${q(ds.table)} (${cols})`)
    const names = ds.columns.map((c) => c.name)
    const insert = db.prepare(`INSERT INTO public.${q(ds.table)} VALUES (${names.map(() => '?').join(', ')})`)
    db.exec('BEGIN')
    for (const row of ds.rows) insert.run(...names.map((n) => (row[n] === undefined ? null : row[n])))
    db.exec('COMMIT')
  }
  // Accent-folded lowercase text (the backend's accent-folded ILIKE) + a median.
  db.function('owi_fold', { deterministic: true }, (v) => fold(v))
  db.aggregate('owi_median', {
    start: () => [],
    step: (acc, v) => {
      const n = typeof v === 'number' ? v : Number(v)
      if (v != null && Number.isFinite(n)) acc.push(n)
      return acc
    },
    result: (acc) => {
      if (!acc.length) return null
      const s = [...acc].sort((a, b) => a - b)
      const mid = Math.floor(s.length / 2)
      return Math.round((s.length % 2 ? s[mid] : (s[mid - 1] + s[mid]) / 2) * 100) / 100
    },
  })
  // From here on the connection is READ-ONLY: any write statement is refused.
  db.exec('PRAGMA query_only = ON')
  return db
}

// --- agent SQL guard ------------------------------------------------------------------

const FORBIDDEN = /\b(pragma|attach|detach|insert|update|delete|drop|create|alter|replace|vacuum|reindex|analyze|load_extension|readfile|writefile)\b/i

// Strip string literals / quoted identifiers / comments so keyword checks only see
// SQL tokens. Returns the skeleton or null when a literal is unterminated.
function skeleton(sql) {
  let out = ''
  let i = 0
  while (i < sql.length) {
    const c = sql[i]
    if (c === "'" || c === '"') {
      const end = sql.indexOf(c, i + 1)
      if (end < 0) return null
      let j = end
      // doubled quote = escaped quote inside the literal
      while (sql[j + 1] === c) {
        const next = sql.indexOf(c, j + 2)
        if (next < 0) return null
        j = next
      }
      out += c === "'" ? "''" : '""'
      i = j + 1
    } else if (c === '-' && sql[i + 1] === '-') {
      const end = sql.indexOf('\n', i)
      i = end < 0 ? sql.length : end
      out += ' '
    } else if (c === '/' && sql[i + 1] === '*') {
      const end = sql.indexOf('*/', i + 2)
      if (end < 0) return null
      i = end + 2
      out += ' '
    } else {
      out += c
      i += 1
    }
  }
  return out
}

/** Validate one agent SQL. Returns { ok:true, sql } or { ok:false, error }. */
export function guardSelect(sql) {
  if (typeof sql !== 'string' || !sql.trim()) return { ok: false, error: 'empty_sql' }
  if (sql.length > 8000) return { ok: false, error: 'sql_too_long' }
  const sk = skeleton(sql)
  if (sk == null) return { ok: false, error: 'unterminated_literal' }
  const body = sk.trim().replace(/;\s*$/, '')
  if (body.includes(';')) return { ok: false, error: 'multiple_statements' }
  if (!/^(select|with)\b/i.test(body)) return { ok: false, error: 'not_a_select' }
  const bad = body.match(FORBIDDEN)
  if (bad) return { ok: false, error: 'forbidden_keyword:' + bad[1].toUpperCase() }
  return { ok: true, sql: sql.trim().replace(/;\s*$/, '') }
}

/** Run a guarded SELECT; fetch stops at `cap` rows (truncated flag). */
export function runSelect(db, sql, cap = 500) {
  const guard = guardSelect(sql)
  if (!guard.ok) return { ok: false, error: guard.error }
  try {
    const stmt = db.prepare(guard.sql)
    stmt.setReturnArrays(true)
    const columns = stmt.columns().map((c) => c.name)
    const rows = []
    let truncated = false
    for (const row of stmt.iterate()) {
      if (rows.length >= cap) {
        truncated = true
        break
      }
      rows.push(row.map((v) => (typeof v === 'bigint' ? Number(v) : v)))
    }
    return { ok: true, columns, rows, truncated }
  } catch (e) {
    return { ok: false, error: String((e && e.message) || e).slice(0, 300) }
  }
}

// --- structured engine (Source Data + Evidence re-queries) --------------------------

function colSet(ds) {
  return new Set(ds.columns.map((c) => c.name))
}

// One structured filter -> [sqlFragment, params] or null (unknown column / op).
function filterSql(f, cols) {
  if (!f || !cols.has(f.column)) return null
  const c = q(f.column)
  const values = Array.isArray(f.values) ? f.values.slice(0, 200) : []
  switch (String(f.op || '=').toUpperCase()) {
    case '=': return values.length ? [`${c} = ?`, [values[0]]] : null
    case '!=':
    case '<>': return values.length ? [`(${c} IS NULL OR ${c} <> ?)`, [values[0]]] : null
    case 'IN': return values.length ? [`${c} IN (${values.map(() => '?').join(', ')})`, values] : ['0', []]
    case 'NOT IN': return values.length ? [`(${c} IS NULL OR ${c} NOT IN (${values.map(() => '?').join(', ')}))`, values] : null
    case '>': return values.length ? [`${c} > ?`, [values[0]]] : null
    case '>=': return values.length ? [`${c} >= ?`, [values[0]]] : null
    case '<': return values.length ? [`${c} < ?`, [values[0]]] : null
    case '<=': return values.length ? [`${c} <= ?`, [values[0]]] : null
    case 'BETWEEN': return values.length >= 2 ? [`${c} BETWEEN ? AND ?`, [values[0], values[1]]] : null
    case 'IS NULL': return [`(${c} IS NULL OR ${c} = '')`, []]
    case 'IS NOT NULL': return [`(${c} IS NOT NULL AND ${c} <> '')`, []]
    case 'LIKE': return values.length ? [`owi_fold(${c}) LIKE ? ESCAPE '\\'`, ['%' + likeEscape(fold(String(values[0]).replace(/%/g, ''))) + '%']] : null
    default: return null
  }
}

function likeEscape(s) {
  return s.replace(/[\\%_]/g, (m) => '\\' + m)
}

// Every scope condition (filters, accent-folded search, drill) as one WHERE clause.
export function scopeWhere(ds, { filters, q: term, drill } = {}) {
  const cols = colSet(ds)
  const parts = []
  const params = []
  for (const f of filters || []) {
    const out = filterSql(f, cols)
    if (!out) continue
    parts.push(out[0])
    params.push(...out[1].map(String))
  }
  const t = fold(term || '').trim()
  if (t.length >= 2) {
    parts.push('(' + ds.columns.map((c) => `owi_fold(${q(c.name)}) LIKE ? ESCAPE '\\'`).join(' OR ') + ')')
    for (let i = 0; i < ds.columns.length; i++) params.push('%' + likeEscape(t) + '%')
  }
  for (const d of drill || []) {
    if (!d || !cols.has(d.column)) continue
    if (d.value == null) parts.push(`${q(d.column)} IS NULL`)
    else {
      parts.push(`${q(d.column)} = ?`)
      params.push(String(d.value))
    }
  }
  return { where: parts.length ? 'WHERE ' + parts.join(' AND ') : '', params }
}

const table = (ds) => `public.${q(ds.table)}`

function all(db, sql, params) {
  const stmt = db.prepare(sql)
  return stmt.all(...params).map((r) => ({ ...r }))
}

export function structuredRows(db, ds, opts = {}) {
  const { where, params } = scopeWhere(ds, opts)
  const cols = colSet(ds)
  const lim = Math.max(1, Math.min(Number(opts.limit) || 100, 100))
  const off = Math.max(0, Math.min(Number(opts.offset) || 0, 5000))
  const sort = opts.sort && cols.has(opts.sort.column)
    ? `ORDER BY ${q(opts.sort.column)} ${opts.sort.dir === 'desc' ? 'DESC' : 'ASC'}`
    : ''
  const rows = all(db, `SELECT * FROM ${table(ds)} ${where} ${sort} LIMIT ${lim + 1} OFFSET ${off}`, params)
  return { rows: rows.slice(0, lim), has_more: rows.length > lim, offset: off }
}

function measureSql(m, cols) {
  const fn = m && m.fn
  if (fn === 'count') return 'COUNT(*)'
  if (!cols.has(m.column)) return 'NULL'
  const c = q(m.column)
  const nonEmpty = `NULLIF(${c}, '')`
  switch (fn) {
    case 'count_distinct': return `COUNT(DISTINCT ${nonEmpty})`
    case 'sum': return `ROUND(SUM(${c}), 2)`
    case 'avg': return `ROUND(AVG(${c}), 2)`
    case 'min': return `MIN(${nonEmpty})`
    case 'max': return `MAX(${nonEmpty})`
    case 'median': return `owi_median(${c})`
    default: return 'NULL'
  }
}

function bucketSql(column, bucket) {
  const c = q(column)
  if (bucket === 'year') return `substr(${c}, 1, 4)`
  if (bucket === 'quarter') return `(substr(${c}, 1, 4) || '-Q' || ((CAST(substr(${c}, 6, 2) AS INTEGER) + 2) / 3))`
  if (bucket === 'month') return `substr(${c}, 1, 7)`
  return c
}

export function structuredAggregate(db, ds, opts = {}) {
  const cols = colSet(ds)
  const specs = (opts.measures || []).slice(0, 8)
  if (!specs.length) return { rows: [], totals: null, truncated: false }
  const { where, params } = scopeWhere(ds, opts)
  const select = specs.map((m, i) => `${measureSql(m, cols)} AS m${i}`).join(', ')
  const totals = all(db, `SELECT ${select} FROM ${table(ds)} ${where}`, params)[0]
  const group = opts.group
  if (!group || !cols.has(group.column)) return { rows: [totals], totals: null, truncated: false }
  const key = bucketSql(group.column, group.bucket)
  const cap = Math.max(1, Math.min(Number(opts.limit) || 50, 50))
  const rows = all(
    db,
    `SELECT ${key} AS key, ${select} FROM ${table(ds)} ${where} GROUP BY 1 ORDER BY m0 DESC, key ASC LIMIT ${cap + 1}`,
    params,
  )
  return { rows: rows.slice(0, cap), totals, truncated: rows.length > cap }
}

export function structuredDistinct(db, ds, column, term, scope = {}, cap = 50) {
  const cols = colSet(ds)
  if (!cols.has(column)) return { values: [], truncated: false }
  const { where, params } = scopeWhere(ds, scope)
  const c = q(column)
  const conds = [`${c} IS NOT NULL`, `${c} <> ''`]
  const t = fold(term || '').trim()
  if (t) {
    conds.push(`owi_fold(${c}) LIKE ? ESCAPE '\\'`)
    params.push('%' + likeEscape(t) + '%')
  }
  const sql = `SELECT DISTINCT ${c} AS v FROM ${table(ds)} ${where ? where + ' AND ' : 'WHERE '}${conds.join(' AND ')} ORDER BY 1 LIMIT ${cap + 1}`
  const values = all(db, sql, params).map((r) => r.v)
  return { values: values.slice(0, cap), truncated: values.length > cap }
}
