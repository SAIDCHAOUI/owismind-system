// Evidence descriptor of ONE agent SQL in the live harness (a pragmatic JS cousin of
// evidence/service.py + the SQL explainer): the FROM table picks the dataset, the
// top-level AND conjuncts of a simple WHERE become editable chips, everything the
// parser cannot decompose is LISTED as dropped (never hidden) and lowers the
// verification level. Pure, never throws.

const IDENT = String.raw`(?:"(?:[^"]|"")+"|[A-Za-z_][A-Za-z0-9_]*)`
const QUALIFIED = String.raw`${IDENT}(?:\s*\.\s*${IDENT})?`

const unquote = (s) => {
  const t = String(s).trim()
  return t.startsWith('"') && t.endsWith('"') ? t.slice(1, -1).replace(/""/g, '"') : t
}
const lastPart = (s) => unquote(String(s).split(/\s*\.\s*(?=(?:"|[A-Za-z_]))/).pop())

// Mask string literals so structural regexes never match inside them.
function mask(sql) {
  return sql.replace(/'(?:[^']|'')*'/g, (m) => "'" + '_'.repeat(Math.max(0, m.length - 2)) + "'")
}

// Split `text` on a top-level keyword (outside parentheses / literals).
function splitTopLevel(text, masked, re) {
  const parts = []
  let depth = 0
  let start = 0
  const lower = masked.toLowerCase()
  for (let i = 0; i < masked.length; i++) {
    const c = masked[i]
    if (c === '(') depth++
    else if (c === ')') depth--
    else if (depth === 0) {
      const m = lower.slice(i).match(re)
      if (m && (i === 0 || /\s/.test(masked[i - 1]))) {
        parts.push([text.slice(start, i), masked.slice(start, i)])
        i += m[0].length - 1
        start = i + 1
      }
    }
  }
  parts.push([text.slice(start), masked.slice(start)])
  return parts
}

function literal(raw) {
  const t = raw.trim()
  if (/^'(?:[^']|'')*'$/.test(t)) return t.slice(1, -1).replace(/''/g, "'")
  if (/^-?\d+(?:\.\d+)?$/.test(t)) return t
  return null
}

function listLiterals(raw) {
  const inner = raw.trim().replace(/^\(/, '').replace(/\)$/, '')
  const out = []
  for (const piece of inner.match(/'(?:[^']|'')*'|-?\d+(?:\.\d+)?/g) || []) out.push(literal(piece))
  return out.every((v) => v != null) ? out : null
}

// One conjunct -> a chip {column, op, values} or null (not decomposable).
function parsePredicate(text, colByLower) {
  const t = text.trim().replace(/^\((.*)\)$/s, '$1').trim()
  const colRe = String.raw`^(${QUALIFIED})\s*`
  const col = (raw) => colByLower.get(lastPart(raw).toLowerCase()) || null
  let m = t.match(new RegExp(colRe + String.raw`(=|<>|!=|>=|<=|>|<)\s*('(?:[^']|'')*'|-?\d+(?:\.\d+)?)$`, 's'))
  if (m && col(m[1])) return { column: col(m[1]), op: m[2] === '!=' ? '<>' : m[2], values: [literal(m[3])] }
  m = t.match(new RegExp(colRe + String.raw`(NOT\s+IN|IN)\s*(\(.*\))$`, 'is'))
  if (m && col(m[1])) {
    const values = listLiterals(m[3])
    if (values && values.length) return { column: col(m[1]), op: /not/i.test(m[2]) ? 'NOT IN' : 'IN', values }
  }
  m = t.match(new RegExp(colRe + String.raw`BETWEEN\s+('(?:[^']|'')*'|-?\d+(?:\.\d+)?)\s+AND\s+('(?:[^']|'')*'|-?\d+(?:\.\d+)?)$`, 'is'))
  if (m && col(m[1])) return { column: col(m[1]), op: 'BETWEEN', values: [literal(m[2]), literal(m[3])] }
  m = t.match(new RegExp(colRe + String.raw`I?LIKE\s+('(?:[^']|'')*')$`, 'is'))
  if (m && col(m[1])) return { column: col(m[1]), op: 'LIKE', values: [literal(m[2])] }
  m = t.match(new RegExp(colRe + String.raw`IS\s+(NOT\s+)?NULL$`, 'is'))
  if (m && col(m[1])) return { column: col(m[1]), op: m[2] ? 'IS NOT NULL' : 'IS NULL', values: [] }
  return null
}

const FILTER_KIND = {
  '=': 'filter_eq', '<>': 'filter_neq', '>': 'filter_gt', '>=': 'filter_gte', '<': 'filter_lt', '<=': 'filter_lte',
  IN: 'filter_in', 'NOT IN': 'filter_notin', BETWEEN: 'filter_between', LIKE: 'filter_like',
  'IS NULL': 'filter_null', 'IS NOT NULL': 'filter_notnull',
}

export function filterStep(chip) {
  const kind = FILTER_KIND[chip.op]
  if (chip.op === 'IN' || chip.op === 'NOT IN') return { kind, params: [chip.column, chip.values.length, chip.values.join(', ')] }
  if (chip.op === 'BETWEEN') return { kind, params: [chip.column, chip.values[0], chip.values[1]] }
  if (chip.op === 'IS NULL' || chip.op === 'IS NOT NULL') return { kind, params: [chip.column] }
  return { kind, params: [chip.column, chip.values[0]] }
}

// Clause text between `kw` and the next clause keyword, at the outer level.
function clause(sql, masked, kw, stops) {
  const lower = masked.toLowerCase()
  const re = new RegExp(String.raw`\b${kw}\b`, 'i')
  const m = lower.match(re)
  if (!m) return null
  const from = m.index + m[0].length
  let end = sql.length
  for (const stop of stops) {
    const sm = lower.slice(from).match(new RegExp(String.raw`\b${stop}\b`, 'i'))
    if (sm) end = Math.min(end, from + sm.index)
  }
  return [sql.slice(from, end).trim(), masked.slice(from, end).trim()]
}

/**
 * The evidence block of one SQL: { dataset, key, table, chips, advanced, sql,
 * explanationSteps, drillColumns, verification } or { unavailable: reason }.
 */
export function describeSql(sql, datasets) {
  try {
    const masked = mask(sql)
    const tables = []
    const fromRe = new RegExp(String.raw`\b(?:from|join)\s+(${QUALIFIED})`, 'gi')
    for (const m of masked.matchAll(fromRe)) {
      const name = lastPart(sql.slice(m.index + m[0].length - m[1].length, m.index + m[0].length)).toLowerCase()
      const ds = datasets.find((d) => d.table.toLowerCase() === name || d.dataset.toLowerCase() === name)
      if (ds && !tables.includes(ds)) tables.push(ds)
    }
    if (!tables.length) return { unavailable: 'no_matching_dataset' }
    const ds = tables[0]
    const colByLower = new Map(ds.columns.map((c) => [c.name.toLowerCase(), c.name]))
    const singleSource = tables.length === 1 && !/\bjoin\b/i.test(masked)
    const hasSetOp = /\b(union|intersect|except)\b/i.test(masked)
    const nested = /^\s*with\b/i.test(masked) || /\(\s*select\b/i.test(masked)

    const chips = []
    const dropped = []
    let whereComplete = true
    if (nested) {
      // CTE / sub-select: the outer WHERE is not the whole scope, never pretend.
      whereComplete = false
      dropped.push('requête composée (CTE ou sous-requête)')
    } else {
      const where = clause(sql, masked, 'where', ['group\\s+by', 'order\\s+by', 'having', 'limit'])
      if (where) {
        const pieces = splitTopLevel(where[0], where[1], /^and\b/)
        // BETWEEN a AND b was split: glue the bound back to its predicate.
        const merged = []
        for (const [txt, msk] of pieces) {
          const prev = merged[merged.length - 1]
          if (prev && /\bbetween\s+\S+\s*$/i.test(prev[1])) {
            prev[0] += ' AND ' + txt
            prev[1] += ' AND ' + msk
          } else merged.push([txt, msk])
        }
        for (const [txt, msk] of merged) {
          if (/\bor\b/i.test(msk)) {
            whereComplete = false
            dropped.push(txt.trim().slice(0, 160))
            continue
          }
          const chip = parsePredicate(txt, colByLower)
          if (chip) chips.push({ id: chips.length + 1, ...chip, editable: true })
          else {
            whereComplete = false
            dropped.push(txt.trim().slice(0, 160))
          }
        }
      }
    }

    const steps = [{ kind: 'source', params: [ds.dataset] }, ...chips.map(filterStep)]
    for (const d of dropped) steps.push({ kind: 'filter_advanced', params: [d] })
    let groupCols = []
    let selectUnderstood = !nested && !hasSetOp
    const group = nested ? null : clause(sql, masked, 'group\\s+by', ['order\\s+by', 'having', 'limit'])
    if (group) {
      for (const g of group[0].split(',')) {
        const name = colByLower.get(lastPart(g).toLowerCase())
        if (name) groupCols.push(name)
        else if (!/^\d+$/.test(g.trim())) selectUnderstood = false
      }
      if (groupCols.length) steps.push({ kind: 'group', params: [groupCols.join(', ')] })
    }
    const aggRe = /\b(sum|avg|min|max|count)\s*\(\s*(distinct\s+)?([^()]*?)\s*\)/gi
    const seen = new Set()
    for (const m of masked.matchAll(aggRe)) {
      const fn = m[1].toLowerCase()
      const arg = m[3].trim()
      let step = null
      if (fn === 'count' && (arg === '*' || arg === '1')) step = { kind: 'agg_count_star', params: [] }
      else {
        const name = colByLower.get(lastPart(arg).toLowerCase())
        if (!name) continue
        if (fn === 'count') step = { kind: m[2] ? 'agg_count_distinct' : 'agg_count', params: [name] }
        else step = { kind: 'agg_' + fn, params: [name] }
      }
      const sig = JSON.stringify(step)
      if (!seen.has(sig)) {
        seen.add(sig)
        steps.push(step)
      }
    }
    const order = nested ? null : clause(sql, masked, 'order\\s+by', ['limit'])
    if (order) {
      const first = order[0].split(',')[0].trim()
      const dir = /\bdesc\b/i.test(first) ? 'DESC' : 'ASC'
      steps.push({ kind: 'sort', params: [first.replace(/\s+(asc|desc)\b.*$/i, '').trim(), dir] })
    }

    let level = 'source_identified'
    if (whereComplete && singleSource && !hasSetOp) level = selectUnderstood ? 'calc_decomposed' : 'scope_exact'
    else if (chips.length) level = 'scope_partial'
    return {
      key: ds.key,
      dataset: ds.dataset,
      table: ds.table,
      chips,
      advanced: dropped.length ? { present: true, display: dropped.join(' AND ').slice(0, 400) } : { present: false, display: '' },
      sql,
      explanationSteps: steps,
      drillColumns: whereComplete && singleSource && !hasSetOp ? groupCols : [],
      drillReason: !singleSource ? 'multi_source' : hasSetOp ? 'set_op' : !whereComplete ? 'incomplete_where' : groupCols.length ? null : 'no_group_keys',
      verification: {
        level,
        dropped_predicates: dropped.length,
        dropped_display: dropped.slice(0, 10),
        single_source: singleSource,
        where_complete: whereComplete,
        select_understood: selectUnderstood,
      },
    }
  } catch {
    return { unavailable: 'no_matching_dataset' }
  }
}
