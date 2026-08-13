// Scroll affordances for a data table: does its scroll container still hide content on
// the LEFT, on the RIGHT or BELOW, and HOW MANY columns are still out of sight past the
// right edge. A wide table silently cuts its columns at the viewport edge; nothing on
// screen says so, so a first-time user believes the dataset stops there. This composable
// measures the truth and the table turns it into a visible affordance.
//
// It only OBSERVES (scroll + ResizeObserver, both cleaned up on unmount) and exposes the
// three scroll steps the affordances call. The counting math is a pure function, exported
// on its own and unit-tested without Vue (F11).
import { onBeforeUnmount, ref, watch } from 'vue'

// Sub-pixel scroll offsets (fractional zoom, trackpad inertia) must never read as "there
// is more to scroll": everything below this many pixels counts as "at the edge".
const EDGE = 2
// One click travels most of a viewport, keeping a sliver of the previous content on
// screen so the eye can stitch the two views together.
const STEP_X = 0.8
const STEP_Y = 0.9

// How many columns are NOT fully visible past the right edge of the viewport.
// `columns` = [{ left, width }] in the scroll container's CONTENT coordinates (a header
// cell's offsetLeft / offsetWidth); `scrollLeft` + `viewportWidth` = the container's live
// horizontal scroll position and inner width. A half-cut column counts as hidden: a
// column the user cannot read whole is a column they cannot use.
export function countHiddenRightColumns(columns, scrollLeft, viewportWidth) {
  if (!Array.isArray(columns) || !columns.length) return 0
  const left = Number(scrollLeft)
  const width = Number(viewportWidth)
  if (!Number.isFinite(left) || !Number.isFinite(width) || width <= 0) return 0
  const edge = left + width
  let hidden = 0
  for (const col of columns) {
    if (col == null || col.left == null || col.width == null) continue
    const x = Number(col.left)
    const w = Number(col.width)
    if (!Number.isFinite(x) || !Number.isFinite(w)) continue
    // The 1px tolerance keeps a column whose right edge lands exactly on the viewport
    // edge (or a rounding hair past it) counted as VISIBLE.
    if (x + w > edge + 1) hidden += 1
  }
  return hidden
}

// Reactive scroll state of ONE scroll container.
//   elRef:   template ref to the scrolling element (both axes)
//   options: { headerSelector } - CSS selector of the header cells inside the container
//            (default 'thead th'), used to count the hidden columns; { contentSelector }
//            - the element whose SIZE changes when rows/columns are added (default
//            'table'), observed so appended rows update the hints.
// Returns { canLeft, canRight, canDown, hiddenRight } plus the scroll steps and a manual
// measure() for hosts that change the content without resizing it.
export function useScrollHints(elRef, options = {}) {
  const headerSelector = options.headerSelector || 'thead th'
  const contentSelector = options.contentSelector || 'table'

  const canLeft = ref(false)
  const canRight = ref(false)
  const canDown = ref(false)
  const hiddenRight = ref(0)

  let resizeObs = null
  let scheduled = false

  function reset() {
    canLeft.value = false
    canRight.value = false
    canDown.value = false
    hiddenRight.value = 0
  }

  // Header cell geometry in content coordinates. offsetLeft is layout-based (an ancestor
  // scroll never shifts it), which is exactly the coordinate space the pure counter wants.
  function readColumns(el) {
    const cells = el.querySelectorAll(headerSelector)
    const out = []
    for (const cell of cells) out.push({ left: cell.offsetLeft, width: cell.offsetWidth })
    return out
  }

  function measure() {
    const el = elRef.value
    if (!el) {
      reset()
      return
    }
    const maxLeft = el.scrollWidth - el.clientWidth
    const maxTop = el.scrollHeight - el.clientHeight
    canLeft.value = el.scrollLeft > EDGE
    canRight.value = el.scrollLeft < maxLeft - EDGE
    canDown.value = el.scrollTop < maxTop - EDGE
    // The count is only ever shown next to the right affordance: skip the header walk
    // (a layout read) whenever there is nothing left to scroll to.
    hiddenRight.value = canRight.value
      ? countHiddenRightColumns(readColumns(el), el.scrollLeft, el.clientWidth)
      : 0
  }

  // Scroll + resize both fire in bursts; coalesce them into one measurement per frame.
  function schedule() {
    if (scheduled) return
    scheduled = true
    const run = () => {
      scheduled = false
      measure()
    }
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run)
    else run()
  }

  // Reduced motion turns the smooth glide into an instant jump (the position still moves,
  // only the animation is dropped).
  function behavior() {
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return 'auto'
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth'
  }
  function scrollBy(left, top) {
    const el = elRef.value
    if (!el) return
    if (typeof el.scrollBy === 'function') el.scrollBy({ left, top, behavior: behavior() })
    else {
      el.scrollLeft += left
      el.scrollTop += top
    }
  }
  function stepRight() {
    const el = elRef.value
    if (el) scrollBy(el.clientWidth * STEP_X, 0)
  }
  function stepLeft() {
    const el = elRef.value
    if (el) scrollBy(-el.clientWidth * STEP_X, 0)
  }
  function stepDown() {
    const el = elRef.value
    if (el) scrollBy(0, el.clientHeight * STEP_Y)
  }

  function detach(el) {
    if (el) el.removeEventListener('scroll', schedule)
    if (resizeObs) {
      resizeObs.disconnect()
      resizeObs = null
    }
  }
  function attach(el) {
    if (!el) return
    el.addEventListener('scroll', schedule, { passive: true })
    if (typeof ResizeObserver === 'function') {
      resizeObs = new ResizeObserver(schedule)
      // The container (viewport size) AND its content (rows appended, columns revealed):
      // both change what is still hidden.
      resizeObs.observe(el)
      const content = contentSelector ? el.querySelector(contentSelector) : null
      if (content) resizeObs.observe(content)
    }
  }

  // The container mounts/unmounts with its v-if branch: rebind on every identity change.
  watch(elRef, (el, old) => {
    detach(old)
    if (el) {
      attach(el)
      schedule()
    } else {
      reset()
    }
  })

  onBeforeUnmount(() => {
    detach(elRef.value)
  })

  return { canLeft, canRight, canDown, hiddenRight, stepLeft, stepRight, stepDown, measure }
}
