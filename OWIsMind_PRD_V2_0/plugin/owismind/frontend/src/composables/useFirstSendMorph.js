/* =============================================================================
 * First-send morph - "the hand-off" (user decision 2026-08-13, "effet luxe").
 *
 * The DOM half of the transition described in `morphSend.js`. Sending the FIRST
 * message of a conversation moves everything at once, so instead of letting the
 * screen cut, we hand the sentence over:
 *
 *   1. RECOMPOSE (0 to 180ms) - the typed line fades into the very same sentence
 *      set in the bubble's typography, ON THE SPOT. The text is never scaled: a
 *      scaled glyph goes soft and gives the trick away. We cross-fade two real
 *      renderings aligned on their first line instead.
 *   2. TRAVEL (200 to 460ms) - the recomposed bubble slides to its place in the
 *      thread. Pure translation, no scale, no deformation.
 *   3. SETTLE (140 to 440ms) - the prompt card travels down and takes its working
 *      width. Width and height are animated (a scale would squash the type, the
 *      1px frame and the 18px radius), which keeps the card readable throughout.
 *
 * The overlay is `pointer-events: none` and the input is live the whole time: the
 * send left at t=0, this is decoration only and can be skipped at any moment.
 * ============================================================================= */

import {
  MORPH,
  flipDelta,
  shouldMorph,
  bubbleStart,
  travelVector,
  morphAllowed,
} from './morphSend.js'

/* The text as the user SAW it. The prompt clears its textarea before the store
 * push, and the sent payload may carry an extra context block the bubble shows,
 * so the visible line is armed by PromptBar right before the send. Stale arms
 * (a send that never happened) expire on their own. */
let armedText = ''
let armedAt = 0
const ARM_TTL_MS = 1000

export function armFirstSend(text) {
  armedText = typeof text === 'string' ? text : ''
  armedAt = Date.now()
}

function takeArmedText() {
  const fresh = armedText && Date.now() - armedAt < ARM_TTL_MS
  const out = fresh ? armedText : ''
  armedText = ''
  return out
}

export function prefersReducedMotion() {
  return !!(
    typeof window !== 'undefined' &&
    window.matchMedia &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  )
}

const EASE = 'cubic-bezier(0.16, 1, 0.3, 1)' // --ease, pure deceleration (no overshoot)
const EASE_IN = 'cubic-bezier(0.4, 0, 0.7, 0.2)' // --ease-in, exits are brisker

function px(v) {
  const n = parseFloat(v)
  return Number.isFinite(n) ? n : 0
}

/**
 * Measure the arrival state. MUST run before the DOM is patched (a pre-flush
 * watcher): once the thread is rendered, the card has already moved.
 */
export function captureFirstSend({ card, input }) {
  const text = takeArmedText()
  if (!card || !input || !text) return null
  const cardRect = card.getBoundingClientRect()
  const textRect = input.getBoundingClientRect()
  if (!cardRect.width || !textRect.width) return null
  if (!morphAllowed({ text, columnWidth: cardRect.width, reducedMotion: prefersReducedMotion() })) return null
  const cs = getComputedStyle(input)
  return {
    text,
    cardRect,
    textRect,
    input: {
      fontSize: cs.fontSize,
      fontFamily: cs.fontFamily,
      lineHeight: px(cs.lineHeight) || px(cs.fontSize) * 1.55,
      letterSpacing: cs.letterSpacing,
      padTop: px(cs.paddingTop),
      color: cs.color,
      width: textRect.width,
    },
  }
}

/* The flying layer lives on <body> so no ancestor `overflow: hidden` clips it
 * (both `.chat` and `.main` clip). It carries no colour of its own: the cloned
 * bubble keeps its scoped classes, so light and dark resolve by themselves. */
function makeLayer() {
  const layer = document.createElement('div')
  layer.className = 'owi-morph-layer'
  // The ghost duplicates the message text: hidden from assistive tech, which does
  // not care about the flight and must not hear the sentence twice.
  layer.setAttribute('aria-hidden', 'true')
  document.body.appendChild(layer)
  return layer
}

/* A faithful stand-in for the text as the textarea was rendering it (a textarea
 * exposes no box for its own text, so we mirror its metrics). */
function makeTypedMirror(first) {
  const el = document.createElement('div')
  const s = el.style
  s.position = 'fixed'
  s.left = first.textRect.left + 'px'
  s.top = first.textRect.top + first.input.padTop + 'px'
  s.width = first.input.width + 'px'
  s.margin = '0'
  s.padding = '0'
  s.whiteSpace = 'pre-wrap'
  s.overflowWrap = 'anywhere'
  s.fontFamily = first.input.fontFamily
  s.fontSize = first.input.fontSize
  s.lineHeight = first.input.lineHeight + 'px'
  s.letterSpacing = first.input.letterSpacing
  s.color = first.input.color
  el.textContent = first.text
  return el
}

/* The real bubble, cloned: same scoped classes, same tokens, same theme. Cloning
 * beats rebuilding - there is no second source of truth to keep in sync. */
function makeBubbleGhost(bubbleEl, rect) {
  const el = bubbleEl.cloneNode(true)
  el.removeAttribute('id')
  const s = el.style
  s.position = 'fixed'
  s.margin = '0'
  s.width = rect.width + 'px'
  s.boxSizing = 'border-box'
  s.transformOrigin = 'top left'
  return el
}

/**
 * Play the transition. Runs AFTER the DOM patch (nextTick), so the thread, its
 * bubble and the card's final geometry all exist.
 *
 * `findBubble` returns the first user bubble; `stage` (optional) is the arrival
 * heading block, animated out by its own leave hook in the view.
 */
export function playFirstSend(first, { card, findBubble }) {
  if (!first || !card) return null
  const last = card.getBoundingClientRect()
  const delta = flipDelta(first.cardRect, last)
  if (!shouldMorph({ reducedMotion: prefersReducedMotion(), delta })) return null

  const animations = []
  let layer = null
  try {
    return build()
  } catch (e) {
    // A flourish must never take the screen down with it: undo whatever was put on
    // stage and let the plain state stand.
    animations.forEach((a) => {
      try {
        a.cancel()
      } catch (err) {
        /* already gone */
      }
    })
    if (layer && layer.parentNode) layer.parentNode.removeChild(layer)
    return null
  }

  function build() {

  /* --- 1. The card settles ------------------------------------------------- */
  // Width and height are animated on purpose: scaling the card would squash the
  // placeholder, the send button, the 1px frame and the 18px radius. This is one
  // small subtree, so the per-frame layout cost stays local.
  // The inversion must match the anchors the forced size creates: `dx` because a
  // width-constrained card sits at the LEFT edge of its wrapper (no auto margins),
  // and `dyBottom` because the card is anchored to the bottom of the flex column,
  // so the taller hero height pushes its top edge up on its own.
  animations.push(
    card.animate(
      [
        {
          transform: `translate(${delta.dx}px, ${delta.dyBottom}px)`,
          width: first.cardRect.width + 'px',
          height: first.cardRect.height + 'px',
        },
        { transform: 'translate(0, 0)', width: last.width + 'px', height: last.height + 'px' },
      ],
      { duration: MORPH.card, delay: MORPH.cardDelay, easing: EASE, fill: 'backwards' },
    ),
  )

  /* --- 2. The sentence is handed over -------------------------------------- */
  const bubble = typeof findBubble === 'function' ? findBubble() : null
  if (bubble) {
    // The message row carries the standard entry animation (`msg-in` on `.msg`,
    // MessageUser.vue). Kill it BEFORE measuring, or the bubble is measured 6px
    // low, mid-slide, and the sentence lands off its mark. It is never restored:
    // for this one message, the morph IS the entry.
    const row = bubble.closest('.msg')
    if (row) row.style.animation = 'none'
    const bubbleRect = bubble.getBoundingClientRect()
    const cs = getComputedStyle(bubble)
    const start = bubbleStart({
      textRect: first.textRect,
      inputPadTop: first.input.padTop,
      inputLineH: first.input.lineHeight,
      bubblePad: { top: px(cs.paddingTop), left: px(cs.paddingLeft) },
      bubbleLineH: px(cs.lineHeight) || px(cs.fontSize) * 1.5,
    })
    if (start) {
      layer = makeLayer()
      const typed = makeTypedMirror(first)
      const ghost = makeBubbleGhost(bubble, bubbleRect)
      ghost.style.left = start.left + 'px'
      ghost.style.top = start.top + 'px'
      layer.appendChild(typed)
      layer.appendChild(ghost)

      // The real one waits its turn, hidden until the ghost lands on it.
      const prevOpacity = bubble.style.opacity
      bubble.style.opacity = '0'

      const { dx, dy } = travelVector(start, bubbleRect)

      // 2a. RECOMPOSE in place: the typed line steps back, the same sentence in
      // the bubble's typography steps forward. Neither is scaled.
      animations.push(
        typed.animate(
          [
            { opacity: 1, transform: 'translateY(0)' },
            { opacity: 0, transform: 'translateY(-2px)' },
          ],
          { duration: MORPH.recompose, easing: EASE_IN, fill: 'forwards' },
        ),
      )
      animations.push(
        ghost.animate(
          [
            { opacity: 0, transform: 'translateY(2px)' },
            { opacity: 1, transform: 'translateY(0)' },
          ],
          { duration: MORPH.recompose, easing: EASE, fill: 'backwards' },
        ),
      )
      // 2b. TRAVEL: straight to its place in the thread. Translation only.
      const flight = ghost.animate(
        [{ transform: 'translate(0, 0)' }, { transform: `translate(${dx}px, ${dy}px)` }],
        { duration: MORPH.travel, delay: MORPH.travelDelay, easing: EASE, fill: 'forwards' },
      )
      animations.push(flight)

      // 2c. HAND OVER: the real bubble takes back its place, the layer dies.
      flight.finished
        .then(() => {
          bubble.style.opacity = prevOpacity
        })
        .catch(() => {
          // Cancelled (navigation, a second send): give the bubble back at once.
          bubble.style.opacity = prevOpacity
        })
        .finally(() => {
          if (layer && layer.parentNode) layer.parentNode.removeChild(layer)
          layer = null
        })
    }
  }

    /** Abort everything and leave no trace (route change, unmount, second send). */
    return function cancel() {
      animations.forEach((a) => {
        try {
          a.cancel()
        } catch (e) {
          /* already finished */
        }
      })
      if (layer && layer.parentNode) layer.parentNode.removeChild(layer)
      layer = null
    }
  }
}

/**
 * The arrival heading leaving: subtitle first, then the title, then the orange
 * title-bar closing back onto its own centre (the entry `bar-wipe` played in
 * reverse). Called from the view's Transition leave hook, which also freezes the
 * block's geometry so the card's FLIP measures the real final layout.
 */
export function playStageExit(el, done) {
  // `done()` REMOVES the element. Every path below must reach it, including the
  // failure ones: a leave hook that never calls done leaves the heading in the DOM
  // for good, on top of the thread.
  if (prefersReducedMotion()) {
    done()
    return null
  }
  const anims = []
  try {
    const title = el.querySelector('.empty-title')
    const sub = el.querySelector('.empty-sub')
    const bar = el.querySelector('.empty-bar')
    const out = (node, delay, dy) =>
      node &&
      anims.push(
        node.animate(
          [
            { opacity: 1, transform: 'translateY(0)' },
            { opacity: 0, transform: `translateY(${dy}px)` },
          ],
          { duration: MORPH.exit, delay, easing: EASE_IN, fill: 'forwards' },
        ),
      )
    out(sub, 0, -6)
    out(title, 30, -10)
    if (bar) {
      // The title-bar closes back onto its own centre: the entry wipe, reversed.
      anims.push(
        bar.animate([{ transform: 'scaleX(1)' }, { transform: 'scaleX(0)' }], {
          duration: MORPH.barClose,
          delay: MORPH.barCloseDelay,
          easing: EASE_IN,
          fill: 'forwards',
        }),
      )
    }
  } catch (e) {
    done()
    return null
  }
  const last = anims[anims.length - 1]
  if (!last) {
    done()
    return null
  }
  last.finished.then(done).catch(done)
  return () => anims.forEach((a) => a.cancel())
}
