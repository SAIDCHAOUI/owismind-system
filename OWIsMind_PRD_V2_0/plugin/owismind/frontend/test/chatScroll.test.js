// Unit tests for the pure chat scroll decisions (composables/chatScrollModel.js).
// Runnable with the built-in test runner (NO install): from frontend/ run
//   node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  LANDING_MARGIN_PX,
  contentOffset,
  shouldLandOnCompletion,
  answerLandingTop,
  scrollBehavior,
} from '../src/composables/chatScrollModel.js'

test('contentOffset converts a viewport rect into a scroll-content offset', () => {
  assert.equal(contentOffset(300, 100, 1000), 1200)
  assert.equal(contentOffset(-50, 100, 1000), 850)
})

test('completion landing only when the reader followed the run to its end', () => {
  assert.equal(shouldLandOnCompletion({ following: true, leftBottomDuringRun: false, sameSession: true }), true)
  // The user scrolled up mid-run: never yank them.
  assert.equal(shouldLandOnCompletion({ following: false, leftBottomDuringRun: true, sameSession: true }), false)
  // Left the bottom then came back: still respected, no jump.
  assert.equal(shouldLandOnCompletion({ following: true, leftBottomDuringRun: true, sameSession: true }), false)
  // Another conversation owns the screen now.
  assert.equal(shouldLandOnCompletion({ following: true, leftBottomDuringRun: false, sameSession: false }), false)
})

test('long answer: land on the answer start minus the margin', () => {
  const top = answerLandingTop({ viewportHeight: 600, answerTop: 2000, answerBottom: 3500 })
  assert.equal(top, 2000 - LANDING_MARGIN_PX)
})

test('a short steps line above the answer is kept in view', () => {
  const top = answerLandingTop({ viewportHeight: 600, answerTop: 2000, answerBottom: 3500, leadTop: 1960, margin: 10 })
  assert.equal(top, 1950)
})

test('a tall (expanded) steps block is skipped in favour of the answer text', () => {
  const top = answerLandingTop({ viewportHeight: 600, answerTop: 2000, answerBottom: 3500, leadTop: 1500, margin: 10 })
  assert.equal(top, 1990)
})

test('a lead located below the answer start is ignored', () => {
  const top = answerLandingTop({ viewportHeight: 600, answerTop: 2000, answerBottom: 3500, leadTop: 2100, margin: 0 })
  assert.equal(top, 2000)
})

test('answer that fits the viewport keeps the current behaviour (null)', () => {
  assert.equal(answerLandingTop({ viewportHeight: 800, answerTop: 2000, answerBottom: 2500 }), null)
  // Exactly fitting, margin included.
  assert.equal(answerLandingTop({ viewportHeight: 516, answerTop: 2000, answerBottom: 2500 }), null)
  assert.equal(answerLandingTop({ viewportHeight: 515, answerTop: 2000, answerBottom: 2500 }), 1984)
})

test('landing never goes above the top of the content', () => {
  assert.equal(answerLandingTop({ viewportHeight: 300, answerTop: 5, answerBottom: 2000 }), 0)
})

test('unusable measures return null', () => {
  assert.equal(answerLandingTop({ viewportHeight: 0, answerTop: 0, answerBottom: 2000 }), null)
  assert.equal(answerLandingTop({ viewportHeight: 600, answerTop: NaN, answerBottom: 2000 }), null)
  assert.equal(answerLandingTop({ viewportHeight: 600, answerTop: 900, answerBottom: 900 }), null)
  assert.equal(answerLandingTop({ viewportHeight: 600, answerTop: 900, answerBottom: undefined }), null)
})

test('scroll behaviour honours prefers-reduced-motion', () => {
  assert.equal(scrollBehavior(false), 'smooth')
  assert.equal(scrollBehavior(true), 'auto')
  assert.equal(scrollBehavior(false, false), 'auto')
})
