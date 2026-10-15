// Right-column teaser predicates (V2 "beacon") - run with `node --test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { teaserState, isNarrow, NARROW_WIDTH, TEASER_COLUMN_MIN_WIDTH } from '../src/composables/teaserModel.js'

const base = { routeName: 'chat', rightPanelOpen: false, agentHasSources: true, workspaceReady: false, viewportWidth: 1440 }

test('arrival screen: a data teaser, never an open panel', () => {
  assert.deepEqual(teaserState(base), { visible: true, mode: 'data', signal: false, running: false, compact: false })
})

test('hidden off the chat, when a right panel is open, or with nothing to show', () => {
  assert.equal(teaserState({ ...base, routeName: 'settings' }).visible, false)
  assert.equal(teaserState({ ...base, rightPanelOpen: true }).visible, false)
  assert.equal(teaserState({ ...base, agentHasSources: false }).visible, false)
  assert.equal(teaserState(null).visible, false)
})

test('a workspace wins over the data teaser; the orange signal only when unseen or running', () => {
  const ready = teaserState({ ...base, workspaceReady: true })
  assert.equal(ready.mode, 'workspace')
  assert.equal(ready.signal, false)
  assert.equal(teaserState({ ...base, workspaceReady: true, unseen: true }).signal, true)
  const live = teaserState({ ...base, workspaceReady: true, running: true })
  assert.equal(live.signal, true)
  assert.equal(live.running, true)
  // A source-less agent still gets the workspace teaser.
  assert.equal(teaserState({ ...base, agentHasSources: false, workspaceReady: true }).visible, true)
  // `unseen` never lights the data teaser.
  assert.equal(teaserState({ ...base, unseen: true }).signal, false)
})

test('compact below the column width, narrow (sheet) below 900px', () => {
  assert.equal(teaserState({ ...base, viewportWidth: TEASER_COLUMN_MIN_WIDTH }).compact, false)
  assert.equal(teaserState({ ...base, viewportWidth: TEASER_COLUMN_MIN_WIDTH - 1 }).compact, true)
  assert.equal(teaserState({ ...base, viewportWidth: undefined }).compact, true)
  assert.equal(isNarrow(NARROW_WIDTH - 1), true)
  assert.equal(isNarrow(NARROW_WIDTH), false)
  assert.equal(isNarrow(0), false)
})

import { previewTable } from '../src/composables/teaserModel.js'

test('previewTable: first 3 columns, first 8 rows, objects or arrays, strings only', () => {
  const meta = { columns: [{ name: 'a' }, { name: 'b' }, { name: 'c' }, { name: 'd' }] }
  const objRows = Array.from({ length: 10 }, (_, i) => ({ a: i, b: null, c: 'x', d: 'hidden' }))
  const t1 = previewTable(meta, objRows)
  assert.deepEqual(t1.cols, ['a', 'b', 'c'])
  assert.equal(t1.rows.length, 8)
  assert.deepEqual(t1.rows[0], ['0', '', 'x'])
  assert.deepEqual(previewTable(meta, [[1, 2, 3, 4]]).rows, [['1', '2', '3']])
  assert.deepEqual(previewTable(null, objRows), { cols: [], rows: [] })
  assert.deepEqual(previewTable(meta, null), { cols: [], rows: [] })
})

import { studioWidth, studioMaxWidth, clampStudio, nextPlanOpen, STUDIO_MIN_WIDTH } from '../src/composables/teaserModel.js'

test('studioWidth: opens at 70% of the width beside the left column, chat keeps 30%', () => {
  // 1440 wide, 60px rail: 1380 available -> 966 Studio, 414 chat.
  assert.equal(studioWidth(1440, 60), 966)
  assert.ok(1440 - 60 - studioWidth(1440, 60) >= Math.ceil(1380 * 0.3))
  // 1280 wide, 260px expanded sidebar: 1020 available -> 714 Studio, 306 chat.
  assert.equal(studioWidth(1280, 260), 714)
  // Defaults on bad input: 1280 viewport, 60px rail.
  assert.equal(studioWidth(undefined, undefined), Math.floor(1220 * 0.7))
  assert.equal(studioMaxWidth(1440, 60), studioWidth(1440, 60))
})

test('clampStudio: a drag can narrow the Studio but never widen it past 70%', () => {
  assert.equal(clampStudio(5000, 1440, 60), 966)
  assert.equal(clampStudio(600, 1440, 60), 600)
  assert.equal(clampStudio(100, 1440, 60), STUDIO_MIN_WIDTH)
  // A stored wide value is pulled back when the window shrinks.
  assert.equal(clampStudio(966, 1100, 60), Math.floor(1040 * 0.7))
  // Expanding the sidebar shrinks the allowance too.
  assert.equal(clampStudio(966, 1440, 300), Math.floor(1140 * 0.7))
  // Tiny width: the 30% chat share wins over the Studio minimum.
  assert.equal(clampStudio(400, 500, 60), Math.floor(440 * 0.7))
  // Custom minimum (Source Data dock) and a non-number request.
  assert.equal(clampStudio(100, 1440, 60, 340), 340)
  assert.equal(clampStudio(NaN, 1440, 60), 966)
})

test('nextPlanOpen: unfold while a run builds, collapse at the end and on restore, toggle', () => {
  assert.equal(nextPlanOpen(false, 'run_start'), true)
  assert.equal(nextPlanOpen(true, 'run_end'), false)
  assert.equal(nextPlanOpen(true, 'restore'), false)
  assert.equal(nextPlanOpen(false, 'toggle'), true)
  assert.equal(nextPlanOpen(true, 'toggle'), false)
  assert.equal(nextPlanOpen(true, 'unknown'), true)
})
