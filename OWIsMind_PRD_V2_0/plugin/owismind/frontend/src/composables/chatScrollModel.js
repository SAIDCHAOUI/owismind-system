// Pure scroll decisions for the chat thread (ChatThread.vue). No DOM access here: the
// component measures, this module decides, so every rule is unit-testable with node --test.
//
// Goal: when a run completes with a long answer, the reader lands on the START of that
// answer (the collapsed agent-steps line just above it stays visible) instead of being
// left at its bottom. Short answers keep the classic bottom pin. A user who scrolled away
// from the bottom during the run is never yanked.

// Breathing room (px) kept above the landing point.
export const LANDING_MARGIN_PX = 16
// The steps line above the answer is kept in view only when it is short relative to the
// viewport (collapsed line); an expanded steps list is skipped in favour of the text.
export const LEAD_MAX_VIEWPORT_RATIO = 0.25

const isNum = (n) => typeof n === 'number' && Number.isFinite(n)

// Offset of an element inside the scroll content, from bounding rects (viewport space).
export function contentOffset(elementRectTop, scrollerRectTop, scrollTop) {
  return elementRectTop - scrollerRectTop + scrollTop
}

// Should a just-finished run trigger the "land on the answer start" scroll?
// - following: the view was pinned to the bottom when the run ended;
// - leftBottomDuringRun: the user scrolled away from the bottom at some point mid-run;
// - sameSession: the run belongs to the conversation still on screen.
export function shouldLandOnCompletion({ following, leftBottomDuringRun, sameSession }) {
  return !!following && !leftBottomDuringRun && !!sameSession
}

// Target scrollTop for the start of the last answer, or null to keep the current
// position (answer fits in the viewport, or inputs are unusable).
// All offsets are in scroll-content coordinates (see contentOffset).
export function answerLandingTop({
  viewportHeight,
  answerTop,
  answerBottom,
  leadTop = null,
  margin = LANDING_MARGIN_PX,
}) {
  if (!isNum(viewportHeight) || viewportHeight <= 0) return null
  if (!isNum(answerTop) || !isNum(answerBottom) || answerBottom <= answerTop) return null
  let start = answerTop
  if (isNum(leadTop) && leadTop <= answerTop && answerTop - leadTop <= viewportHeight * LEAD_MAX_VIEWPORT_RATIO) {
    start = leadTop
  }
  const top = Math.max(0, start - (isNum(margin) ? margin : 0))
  // Fits: the whole answer (from the landing point to its end) is visible at once.
  if (answerBottom - top <= viewportHeight) return null
  return Math.round(top)
}

// scrollTo behaviour honouring prefers-reduced-motion.
export function scrollBehavior(reducedMotion, smooth = true) {
  return smooth && !reducedMotion ? 'smooth' : 'auto'
}
