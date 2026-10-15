/* =============================================================================
 * Send morph - the geometry of the first-send transition ("the hand-off").
 *
 * When the first message of a conversation leaves, three things move at once:
 *   1. the typed text flies from the input to the user bubble,
 *   2. the prompt card travels from the centre of the arrival screen down to the
 *      foot of the thread (a FLIP: measure First, let the layout change, then
 *      Invert and Play),
 *   3. the heading, its subtitle and the orange title-bar leave upward.
 *
 * Everything here is PURE geometry + timing: no DOM, no Vue. The view owns the
 * elements and the Web Animations calls; this module owns the numbers, so the
 * behaviour is unit-testable (test/morphSend.test.js) and the view stays thin.
 * ============================================================================= */

/* Timings, in ms. The text leaves FIRST, the card follows a beat later: the
 * message departs, then the tool puts itself away. Total stays under the charter's
 * 500ms ceiling, so the transition is over long before the first tokens land. */
export const MORPH = {
  recompose: 180, // the typed line becoming the same sentence in bubble type
  travel: 260, // the recomposed bubble sliding to its place in the thread
  travelDelay: 200, // it only leaves once it is legible in its new type
  card: 300, // the prompt card settling at the foot of the thread
  cardDelay: 140, // the message departs first, the tool puts itself away after
  exit: 130, // heading and subtitle leaving upward
  barClose: 140, // the orange title-bar closing back onto its centre
  barCloseDelay: 100,
}


/* A rect as we need it here (a DOMRect is accepted: same field names). */
function isRect(r) {
  return !!r && typeof r.top === 'number' && typeof r.left === 'number' && typeof r.width === 'number'
}

/**
 * FLIP inversion for a node that changed place (and possibly size) between two
 * layouts. Returns the transform to apply BEFORE playing it back to identity.
 *
 * TWO vertical deltas, and picking the wrong one teleports the card:
 *  - `dy` (top edges) is the classic FLIP, correct when the node keeps its size;
 *  - `dyBottom` (bottom edges) is the one to use when the animation ALSO restores
 *    the old height, because the prompt card is anchored to the BOTTOM of a flex
 *    column: forcing the taller "hero" height pushes its top edge up by exactly the
 *    height difference, so a top-anchored inversion overshoots by that much.
 * `sx` is clamped: a card that barely changes width should not visibly squash.
 */
export function flipDelta(first, last) {
  if (!isRect(first) || !isRect(last)) return null
  const dx = Math.round(first.left - last.left)
  const dy = Math.round(first.top - last.top)
  const firstBottom = first.top + (first.height || 0)
  const lastBottom = last.top + (last.height || 0)
  const ratio = last.width > 0 ? first.width / last.width : 1
  const sx = Math.min(1.6, Math.max(0.6, ratio))
  return { dx, dy, dyBottom: Math.round(firstBottom - lastBottom), sx }
}

/** Nothing to animate: the node did not actually move (or moved by a hair). */
export function isNoop(delta, threshold = 4) {
  if (!delta) return true
  return Math.abs(delta.dx) < threshold && Math.abs(delta.dy) < threshold && Math.abs(delta.sx - 1) < 0.02
}

/**
 * The morph is a flourish, never a dependency: it is skipped when the user asked
 * for less motion, when a rect is missing (hidden tab, detached node), or when
 * the distance is negligible. The send itself has already happened either way.
 */
export function shouldMorph({ reducedMotion, delta }) {
  if (reducedMotion) return false
  return !isNoop(delta)
}

/* Guard rails. A long message flying across the screen is noise, not craft, and a
 * narrow column (embedded DSS iframe) has no room for the flight. Outside these
 * bounds the plain message entry animation stays in charge. */
export const MAX_MORPH_CHARS = 600
export const MAX_MORPH_LINES = 8
export const MIN_MORPH_WIDTH = 420

export function morphAllowed({ text, columnWidth, reducedMotion }) {
  if (reducedMotion) return false
  const s = typeof text === 'string' ? text : ''
  if (!s.trim()) return false
  if (s.length > MAX_MORPH_CHARS) return false
  if (s.split('\n').length > MAX_MORPH_LINES) return false
  return !(columnWidth > 0 && columnWidth < MIN_MORPH_WIDTH)
}

/**
 * Where the recomposed bubble must START so it reads as the SAME sentence the user
 * just typed: its first text line sits on the line the input was showing.
 *
 * The two type sizes differ (prompt 17px, bubble 15px), so aligning the boxes would
 * visibly shift the words. We align the CENTRE of the first line instead (the closest
 * cheap stand-in for a baseline match), and the bubble's padding is subtracted so its
 * text column, not its frame, is what lands on the input's text column.
 */
export function bubbleStart({ textRect, inputPadTop, inputLineH, bubblePad, bubbleLineH }) {
  if (!isRect(textRect)) return null
  const inputFirstLineMid = textRect.top + inputPadTop + inputLineH / 2
  const bubbleFirstLineMid = bubblePad.top + bubbleLineH / 2
  return {
    left: Math.round(textRect.left - bubblePad.left),
    top: Math.round(inputFirstLineMid - bubbleFirstLineMid),
  }
}

/** Straight travel from the recomposed bubble's start to where it really belongs. */
export function travelVector(from, to) {
  if (!from || !isRect(to)) return { dx: 0, dy: 0 }
  return { dx: Math.round(to.left - from.left), dy: Math.round(to.top - from.top) }
}
