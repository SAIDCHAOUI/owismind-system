---
name: flip-with-animated-size-lies
description: A FLIP that also animates width/height must re-derive its inversion from the anchored edges, and the dev-harness rAF probe is how you prove the first frame
metadata:
  type: project
---

When a FLIP animation also animates `width`/`height` (instead of `scale`), the measured
"Last" rect is NO LONGER the element's natural position during the animation: forcing the
old size re-runs layout, and the element moves by the size delta along whatever edge its
container anchors it to. In `ChatView` the prompt card lives in a bottom-anchored column
flex (`.chat` = ChatThread `flex:1` + `.prompt-wrap`), so a top-edge `dy` overshoots
upward by exactly `first.height - last.height`; and a block given an explicit `width`
sits at the LEFT edge of its (already final-width) wrapper, so the `dx` term is
mandatory even though the wrapper is `margin: 0 auto` centred.

Rule: with an animated box size, invert from the ANCHORED edges - `dy = first.bottom -
last.bottom` for a bottom-anchored card, `dx = first.left - last.left` for a
left-flowing block. A pure translate FLIP is the only case where top/left edges work.

**Why:** found 2026-08-13 in `composables/useFirstSendMorph.js` (first-send morph). The
card teleported 151px left + 22px up in one frame on a 1440 canvas before travelling
(116px up with a 5-line draft) - invisible in code review, obvious on the first frame.

**How to apply:** any time a diff animates `width`/`height` alongside a transform-based
FLIP, ask which edge the container anchors, then measure. Beware the blind spot: `dx` is
0 whenever both stages resolve to the same card width (chat column <= ~845px, i.e. 1440
WITH the Source Data dock open), so testing one layout proves nothing.

**Proof recipe (no install, ~30s per scenario):** the harness on 127.0.0.1:5199 plus
`node dev-harness/tools/browse.mjs <steps.json>` with an `evalLog` async IIFE that (1)
sets `ta.value` + dispatches `input` (Vue reads `event.target.value`, no native-setter
trick needed - and the setter trick intermittently throws "Illegal invocation" through
Playwright), (2) dispatches a synthetic `KeyboardEvent('keydown',{key:'Enter'})`, (3)
samples geometry in a `requestAnimationFrame` loop into an array and returns it. That
loop is what catches single-frame jumps, wrong landing points (the ghost landed 6px low
because the bubble was measured during its own `msg-in` backwards fill) and orphaned
layers. See also [[boot-race-exchanges-length]] for replaying watcher order.

Verified the same way and CLEAN, do not re-litigate: Vue force-calls `_leaveCb()` when a
`<Transition :css="false">` leave is preempted by a re-enter, so a `done()` that never
fires cannot strand the element; `flight.finished.catch()` does restore the hidden real
bubble on cancel; unmount mid-flight leaves no `.owi-morph-layer` on `<body>`.
