// sqlPretty: pure SQL prettifier + tokenizer for the Evidence SQL decortication.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { formatSql, tokenizeSql, highlightSqlLines } from '../src/composables/sqlPretty.js'

test('formatSql breaks a one-line query onto clauses', () => {
  const out = formatSql('SELECT a, SUM(b) AS t FROM tbl WHERE a = 1 GROUP BY a ORDER BY t DESC LIMIT 10')
  const lines = out.split('\n')
  assert.ok(lines.some((l) => l.startsWith('FROM')))
  assert.ok(lines.some((l) => l.startsWith('WHERE')))
  assert.ok(lines.some((l) => l.startsWith('GROUP BY')))
  assert.ok(lines.some((l) => l.startsWith('ORDER BY')))
  assert.ok(lines.some((l) => l.startsWith('LIMIT')))
})

test('formatSql indents AND/OR', () => {
  const out = formatSql('SELECT * FROM t WHERE a = 1 AND b = 2 OR c = 3')
  assert.ok(out.includes('\n  AND'))
  assert.ok(out.includes('\n  OR'))
})

test('formatSql is null-safe', () => {
  assert.equal(formatSql(''), '')
  assert.equal(formatSql(null), '')
})

test('tokenizeSql classifies keywords, strings and numbers', () => {
  const toks = tokenizeSql("SELECT a FROM t WHERE name = 'EVPL' AND n = 42")
  const kinds = (text) => toks.filter((t) => t.text === text).map((t) => t.kind)
  assert.deepEqual(kinds('SELECT'), ['kw'])
  assert.deepEqual(kinds('FROM'), ['kw'])
  assert.deepEqual(kinds("'EVPL'"), ['str'])
  assert.deepEqual(kinds('42'), ['num'])
  // A plain identifier is not a keyword.
  assert.deepEqual(kinds('name'), ['text'])
})

test('tokenize reassembles to the original text', () => {
  const line = "SELECT a, b FROM t WHERE x IN ('a','b')"
  const joined = tokenizeSql(line).map((t) => t.text).join('')
  assert.equal(joined, line)
})

test('tokenize reconstructs verbatim even with a lone quote', () => {
  // Unterminated/lone quote must NOT be silently dropped (catch-all group).
  const line = "WHERE name = 'foo"
  const joined = tokenizeSql(line).map((t) => t.text).join('')
  assert.equal(joined, line)
})

test('highlightSqlLines returns lines of tokens', () => {
  const lines = highlightSqlLines('SELECT a FROM t')
  assert.ok(Array.isArray(lines))
  assert.ok(lines.length >= 2)
  assert.ok(Array.isArray(lines[0]))
})
