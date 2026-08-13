// Pure geometry + guard rails of the first-send morph (no Vue, no DOM).
// NO install: from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MORPH,
  flipDelta,
  isNoop,
  shouldMorph,
  morphAllowed,
  bubbleStart,
  travelVector,
  MAX_MORPH_CHARS,
  MIN_MORPH_WIDTH,
} from '../src/composables/morphSend.js'

const rect = (left, top, width, height) => ({ left, top, width, height })

test('flipDelta inverts the move: where the card WAS, relative to where it lands', () => {
  const d = flipDelta(rect(100, 200, 600, 130), rect(60, 640, 900, 98))
  assert.equal(d.dx, 40) // it sat 40px to the right
  assert.equal(d.dy, -440) // and 440px higher
  assert.equal(Math.round(d.sx * 100), 67) // 600 / 900
})

test('flipDelta also reports the BOTTOM-anchored dy (the prompt card case)', () => {
  // Card 130 tall at y=200 (bottom 330) landing 98 tall at y=640 (bottom 738).
  const d = flipDelta(rect(100, 200, 600, 130), rect(60, 640, 900, 98))
  assert.equal(d.dyBottom, -408) // 330 - 738
  // The two differ by exactly the height change: using the top-anchored value while
  // ALSO restoring the old (taller) height starts the card 32px TOO HIGH, which is
  // the teleport this test exists to prevent.
  assert.equal(d.dyBottom - d.dy, 130 - 98)
})

test('flipDelta: same size means both vertical deltas agree', () => {
  const d = flipDelta(rect(0, 100, 500, 90), rect(0, 500, 500, 90))
  assert.equal(d.dy, d.dyBottom)
  assert.equal(d.dx, 0)
})

test('flipDelta clamps the width ratio so a card never squashes', () => {
  assert.equal(flipDelta(rect(0, 0, 100, 10), rect(0, 0, 1000, 10)).sx, 0.6)
  assert.equal(flipDelta(rect(0, 0, 1000, 10), rect(0, 0, 100, 10)).sx, 1.6)
})

test('flipDelta returns null on a missing or malformed rect', () => {
  assert.equal(flipDelta(null, rect(0, 0, 10, 10)), null)
  assert.equal(flipDelta(rect(0, 0, 10, 10), { top: 1 }), null)
})

test('isNoop: a card that did not really move is not worth animating', () => {
  assert.equal(isNoop({ dx: 1, dy: -2, sx: 1 }), true)
  assert.equal(isNoop({ dx: 0, dy: -300, sx: 1 }), false)
  assert.equal(isNoop({ dx: 0, dy: 0, sx: 0.6 }), false) // width alone is enough
  assert.equal(isNoop(null), true)
})

test('shouldMorph obeys reduced motion before anything else', () => {
  const delta = { dx: 0, dy: -300, sx: 0.7 }
  assert.equal(shouldMorph({ reducedMotion: false, delta }), true)
  assert.equal(shouldMorph({ reducedMotion: true, delta }), false)
})

test('morphAllowed: the flourish steps aside for long text, tall text, narrow columns', () => {
  const ok = { text: 'Revenus 2026 par solution', columnWidth: 700, reducedMotion: false }
  assert.equal(morphAllowed(ok), true)
  assert.equal(morphAllowed({ ...ok, text: 'x'.repeat(MAX_MORPH_CHARS + 1) }), false)
  assert.equal(morphAllowed({ ...ok, text: 'a\nb\nc\nd\ne\nf\ng\nh\ni' }), false)
  assert.equal(morphAllowed({ ...ok, columnWidth: MIN_MORPH_WIDTH - 1 }), false)
  assert.equal(morphAllowed({ ...ok, reducedMotion: true }), false)
  assert.equal(morphAllowed({ ...ok, text: '   ' }), false)
})

test('bubbleStart puts the bubble text on the line the input was showing', () => {
  // Input: text box at y=400, 8px top padding, 26px lines -> first line centre 421.
  // Bubble: 10px top padding, 24px lines -> its first line centre sits at 22.
  const start = bubbleStart({
    textRect: rect(300, 400, 600, 60),
    inputPadTop: 8,
    inputLineH: 26,
    bubblePad: { top: 10, left: 14 },
    bubbleLineH: 24,
  })
  assert.equal(start.top, 399) // 421 - 22
  assert.equal(start.left, 286) // the frame starts left of the text column
})

test('bubbleStart returns null without a source rect', () => {
  assert.equal(bubbleStart({ textRect: null, inputPadTop: 0, inputLineH: 10, bubblePad: { top: 0, left: 0 }, bubbleLineH: 10 }), null)
})

test('travelVector is a straight line to the real bubble', () => {
  const v = travelVector({ left: 286, top: 399 }, rect(700, 96, 320, 44))
  assert.deepEqual(v, { dx: 414, dy: -303 })
})

test('the sentence leaves before the card, and the whole thing stays under 500ms', () => {
  assert.ok(MORPH.cardDelay > 0, 'the card waits a beat')
  assert.ok(MORPH.travelDelay >= MORPH.recompose, 'it only travels once it is legible')
  assert.ok(MORPH.travelDelay + MORPH.travel <= 500, 'past 500ms a transition reads as lag')
})
