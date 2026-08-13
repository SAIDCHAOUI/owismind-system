// Tests for composables/useScrollHints.js - the pure column-counting math behind the
// table scroll affordances (how many columns are still hidden past the right edge).
// Pure node:test, no Vue, no DOM (F11).
import test from 'node:test'
import assert from 'node:assert/strict'
import { countHiddenRightColumns } from '../src/composables/useScrollHints.js'

// A 6-column table, 120px each: content 720px wide.
const COLS = [
  { left: 0, width: 120 },
  { left: 120, width: 120 },
  { left: 240, width: 120 },
  { left: 360, width: 120 },
  { left: 480, width: 120 },
  { left: 600, width: 120 },
]

test('counts the columns cut off past the right edge', () => {
  // 300px viewport at offset 0 shows columns 1-2 whole, cuts the 3rd: 4 hidden.
  assert.equal(countHiddenRightColumns(COLS, 0, 300), 4)
  // 360px shows exactly 3 whole columns: 3 hidden.
  assert.equal(countHiddenRightColumns(COLS, 0, 360), 3)
})

test('a half-visible column counts as hidden', () => {
  // 240px viewport: columns 1-2 whole, column 3 half in view -> hidden.
  assert.equal(countHiddenRightColumns(COLS, 0, 240), 4)
  assert.equal(countHiddenRightColumns(COLS, 0, 241), 4)
})

test('scrolling right lowers the count', () => {
  assert.equal(countHiddenRightColumns(COLS, 120, 360), 2)
  assert.equal(countHiddenRightColumns(COLS, 240, 360), 1)
  // Fully scrolled: the last column's right edge is the viewport edge, nothing hidden.
  assert.equal(countHiddenRightColumns(COLS, 360, 360), 0)
})

test('a viewport wider than the content hides nothing', () => {
  assert.equal(countHiddenRightColumns(COLS, 0, 1200), 0)
})

test('one pixel of rounding slack never invents a hidden column', () => {
  // The last column ends 0.5px past the edge: sub-pixel layout, not a real cut.
  assert.equal(countHiddenRightColumns([{ left: 0, width: 300.5 }], 0, 300), 0)
  // Two pixels past the edge IS a real cut.
  assert.equal(countHiddenRightColumns([{ left: 0, width: 302 }], 0, 300), 1)
})

test('empty, malformed and non-array inputs answer 0 instead of throwing', () => {
  assert.equal(countHiddenRightColumns([], 0, 300), 0)
  assert.equal(countHiddenRightColumns(null, 0, 300), 0)
  assert.equal(countHiddenRightColumns(undefined, 0, 300), 0)
  assert.equal(countHiddenRightColumns(COLS, 0, 0), 0)
  assert.equal(countHiddenRightColumns(COLS, NaN, 300), 0)
  assert.equal(countHiddenRightColumns(COLS, 0, NaN), 0)
  // A cell whose geometry could not be read is skipped, the others still count: here
  // only the third column (240..360) falls past a 200px viewport.
  assert.equal(
    countHiddenRightColumns([{ left: 0, width: 120 }, { left: null, width: null }, { left: 240, width: 120 }], 0, 200),
    1,
  )
})

test('the counter never depends on how many columns are on the left', () => {
  // Same 3 columns cut on the right, whether or not columns scrolled out on the left.
  const wide = [
    { left: 0, width: 100 },
    { left: 100, width: 100 },
    { left: 200, width: 100 },
    { left: 300, width: 100 },
    { left: 400, width: 100 },
  ]
  assert.equal(countHiddenRightColumns(wide, 200, 100), 2)
  assert.equal(countHiddenRightColumns(wide, 300, 100), 1)
})
