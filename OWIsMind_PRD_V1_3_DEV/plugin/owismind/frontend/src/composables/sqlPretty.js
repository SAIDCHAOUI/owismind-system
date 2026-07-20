// Pure, dependency-free SQL prettifier + tokenizer for the Evidence "decortication"
// of the agent's generated query. Display-only: it makes a one-line generated SQL
// readable (clause breaks) and classifies tokens for safe syntax highlighting
// (the component renders each token as escaped text - never v-html). Never throws:
// on any problem it degrades to one plain text token, so the raw SQL still shows.

// SQL keywords highlighted (uppercase set; matched case-insensitively).
const KEYWORDS = new Set([
  'SELECT', 'FROM', 'WHERE', 'GROUP', 'BY', 'ORDER', 'HAVING', 'LIMIT', 'OFFSET',
  'AS', 'ON', 'AND', 'OR', 'NOT', 'IN', 'IS', 'NULL', 'LIKE', 'BETWEEN', 'DISTINCT',
  'JOIN', 'LEFT', 'RIGHT', 'INNER', 'FULL', 'OUTER', 'CROSS', 'UNION', 'ALL', 'WITH',
  'CASE', 'WHEN', 'THEN', 'ELSE', 'END', 'ASC', 'DESC', 'OVER', 'PARTITION',
  'COUNT', 'SUM', 'AVG', 'MIN', 'MAX', 'ROUND', 'CAST', 'COALESCE', 'NULLIF',
  'INTERVAL', 'DATE', 'EXTRACT', 'SUBSTRING', 'TO_CHAR',
])

// Clause keywords that start a new line (longest phrases first so "GROUP BY"
// wins over "GROUP"). Applied to a whitespace-collapsed string.
const CLAUSE_BREAKS = [
  'UNION ALL', 'UNION', 'FROM', 'WHERE', 'GROUP BY', 'ORDER BY', 'HAVING',
  'LIMIT', 'OFFSET',
]
const JOIN_BREAKS = ['LEFT JOIN', 'RIGHT JOIN', 'INNER JOIN', 'FULL JOIN', 'CROSS JOIN', 'JOIN']

function escapeRe(s) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

/**
 * Reformat a (possibly single-line) SQL string for readable display: a newline
 * before each top-level clause, indented joins, and indented AND/OR. Best-effort
 * and display-only (the project's SQL is template-generated and predictable);
 * the exact query is still available verbatim via the copy button.
 */
export function formatSql(sql) {
  if (!sql) return ''
  try {
    let s = String(sql).replace(/\s+/g, ' ').trim()
    for (const kw of CLAUSE_BREAKS) {
      s = s.replace(new RegExp('\\s+\\b' + escapeRe(kw) + '\\b', 'gi'), '\n' + kw)
    }
    for (const kw of JOIN_BREAKS) {
      s = s.replace(new RegExp('\\s+\\b' + escapeRe(kw) + '\\b', 'gi'), '\n' + kw)
    }
    s = s.replace(/\s+\b(AND|OR)\b/gi, '\n  $1')
    return s.replace(/\n{2,}/g, '\n').trim()
  } catch (e) {
    return String(sql)
  }
}

// One token: { text, kind } with kind in 'kw' | 'str' | 'num' | 'text'. The
// trailing catch-all (group 7) consumes any otherwise-unmatched character -
// e.g. a lone/unterminated quote - so the rendered SQL is ALWAYS a verbatim
// reconstruction of the input (nothing silently dropped).
const TOKEN_RE = /('(?:[^']|'')*')|("(?:[^"]|"")*")|(\b\d+(?:\.\d+)?\b)|([A-Za-z_][A-Za-z0-9_]*)|(\s+)|([^\sA-Za-z0-9_'"]+)|(.)/g

/**
 * Tokenize ONE line of SQL into classified tokens for syntax highlighting.
 * Identifiers matching a keyword become 'kw'; single-quoted literals 'str';
 * numbers 'num'; everything else (incl. double-quoted identifiers, punctuation,
 * whitespace) 'text'. Pure; on any failure returns the whole line as one token.
 */
export function tokenizeSql(line) {
  const out = []
  if (!line) return out
  try {
    let m
    TOKEN_RE.lastIndex = 0
    while ((m = TOKEN_RE.exec(line)) !== null) {
      if (m[1]) out.push({ text: m[1], kind: 'str' })
      else if (m[2]) out.push({ text: m[2], kind: 'text' })
      else if (m[3]) out.push({ text: m[3], kind: 'num' })
      else if (m[4]) out.push({ text: m[4], kind: KEYWORDS.has(m[4].toUpperCase()) ? 'kw' : 'text' })
      else out.push({ text: m[0], kind: 'text' })
    }
    return out
  } catch (e) {
    return [{ text: String(line), kind: 'text' }]
  }
}

/** Format then tokenize: returns an array of lines, each an array of tokens. */
export function highlightSqlLines(sql) {
  return formatSql(sql)
    .split('\n')
    .map((line) => tokenizeSql(line))
}
