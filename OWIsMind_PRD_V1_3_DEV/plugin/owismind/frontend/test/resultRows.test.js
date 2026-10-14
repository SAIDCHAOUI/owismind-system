// Pure helpers of the agent-result tables (composables/resultRows.js). NO install:
//   from frontend/ run  node --test test/resultRows.test.js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  CAPTURE_EXCERPT_ROWS,
  RESULT_MAX_ROWS,
  RESULT_MORE_LIMIT,
  needsFullResult,
  nextResultWindow,
  resultCountLabel,
} from '../src/composables/resultRows.js'

const rowsOf = (n) => Array.from({ length: n }, (_, i) => [i])

test('needsFullResult: a small complete capture is shown as-is (no request)', () => {
  assert.equal(needsFullResult({ captured: true, rows: rowsOf(12), row_count: 12 }), false)
  assert.equal(needsFullResult({ captured: true, rows: [], row_count: 0 }), false)
})

test('needsFullResult: a flagged, excerpt-sized or under-counted capture needs the full result', () => {
  assert.equal(needsFullResult({ captured: true, rows: rowsOf(3), truncated: true }), true)
  // The agents cap at 50 rows and their row_count is taken AFTER the cut: 50 is suspect.
  assert.equal(
    needsFullResult({ captured: true, rows: rowsOf(CAPTURE_EXCERPT_ROWS), row_count: 50 }),
    true,
  )
  assert.equal(needsFullResult({ captured: true, rows: rowsOf(10), row_count: 1000 }), true)
})

test('needsFullResult: nothing captured or malformed means nothing to page', () => {
  assert.equal(needsFullResult(null), false)
  assert.equal(needsFullResult({ captured: false, row_count: 1000 }), false)
  assert.equal(needsFullResult({ captured: true, rows: 'oops', truncated: true }), false)
})

test('resultCountLabel: a window of a known total says "N of T"', () => {
  assert.deepEqual(
    resultCountLabel({ shown: 100, total: 1000, live: true, hasMore: true, partial: false }),
    { key: 'res.count.of_total', args: [100, 1000] },
  )
})

test('resultCountLabel: the whole result on screen is a plain count', () => {
  assert.deepEqual(
    resultCountLabel({ shown: 80, total: 80, live: true, hasMore: false, partial: false }),
    { key: 'res.count.full', args: [80] },
  )
  assert.deepEqual(
    resultCountLabel({ shown: 12, total: 12, live: false, hasMore: false, partial: false }),
    { key: 'res.count.full', args: [12] },
  )
})

test('resultCountLabel: an unknown total never claims completeness', () => {
  assert.deepEqual(
    resultCountLabel({ shown: 100, total: null, live: true, hasMore: true, partial: false }),
    { key: 'res.count.more', args: [100] },
  )
  // Full result unreadable: the excerpt is flagged, even when the agent count equals it.
  assert.deepEqual(
    resultCountLabel({ shown: 50, total: 50, live: false, hasMore: false, partial: true }),
    { key: 'res.count.excerpt', args: [50] },
  )
  assert.deepEqual(
    resultCountLabel({ shown: 50, total: 900, live: false, hasMore: false, partial: true }),
    { key: 'res.count.of_total', args: [50, 900] },
  )
})

test('nextResultWindow: appends small windows up to the client cap', () => {
  assert.deepEqual(nextResultWindow(100, true), { offset: 100, limit: RESULT_MORE_LIMIT })
  assert.deepEqual(nextResultWindow(RESULT_MAX_ROWS - 5, true), { offset: RESULT_MAX_ROWS - 5, limit: 5 })
  assert.equal(nextResultWindow(RESULT_MAX_ROWS, true), null)
  assert.equal(nextResultWindow(100, false), null)
})
