---
name: analyze-workspace-and-screen-context
description: Hidden coupling that makes UI surfaces load-bearing in OWIsMind (screenContextModel reads calc*/analyze* off the SOURCES store) + dev-harness recipes that prove frontend defects empirically
metadata:
  type: reference
---

Established during the 2026-08-13 "Analyze workspace v3 + dock resize + scroll hints" review.

**The non-obvious coupling: removing a component from a host can silently break the agent
hand-off.** `composables/screenContextModel.js` builds the `source_state` block sent with
`/chat/start` from `stores/screenContext.js:_sourcesState()`, which reads `calcColumn /
calcValues / analyzeGroup / analyzeRows ...` OFF THE SOURCES STORE. Those refs are only ever
written by `SourceCalc.vue` / `SourceAnalyze.vue` when they are mounted WITHOUT a `surface`
prop (their default surface IS `useSourcesStore()`). So the moment a host stops rendering
those two components on the sources surface, the whole calc/analyze part of the screen
context dies - AND `userShaped` (screenContextModel `snapshotFromExplorer`) drops to
"chips only", so a user who merely analyzes without filtering gets NO chip at all. Nothing
in the diff of the sources components hints at it. **Rule: whenever a diff removes or
replaces a component that writes into a store, grep that store's refs for OTHER readers
(`screenContext.js`, `sourceViewMemory`, tracking) before accepting the replacement.**
Note the mirror case is fine: the Evidence "Source data" LEGACY host passes `:surface="evidence"`,
so it keeps working - the regression is scoped to whichever surface lost the component.

**`useClickOutside` targets must include the TRIGGER for a toggle button.** Established
pattern in this repo: `SourceCalc` passes `measZone`, `SourceChips` passes `zone`, `ui/Menu`
passes `wrap` - a wrapper containing trigger + panel. A popover that passes only its own card
ref (`ColumnMenu`, `CellActionPopover`, `MeasurePicker`) is fine ONLY if its trigger calls
`open()` and not `toggle()`: the composable listens on `mousedown` in CAPTURE, so mousedown
closes and the following `click` re-opens. Proof technique: stamp the DOM node
(`el.__mark = 'FIRST'`), click the trigger again, check the mark is GONE while the card is
still present - that distinguishes "close+reopen" from "click did nothing".

**A `pointer-events: none` veil is not inert.** Blurring + `pointer-events: none` on a panel
(the Source Data teaser) leaves every input/button in the TAB ORDER: a keyboard user can
type in the search and press Enter, firing real backend queries while the "engage" state
never flips. Needs `inert` (or `aria-hidden` + `tabindex=-1`) to match the visual promise.

**dev-harness recipes that worked** (`node dev-harness/tools/browse.mjs <steps.json>`,
server `http://127.0.0.1:5199`):
- engage the dock: `{"click": ".src-teaser-veil"}` ; Analyze: `{"clickNth": {"selector": ".src-viewseg-btn", "index": 1}}`
- a `<select>` has no step: `{"eval": "(()=>{const s=document.querySelector('.ws-select'); s.value='Solution'; s.dispatchEvent(new Event('change'))})()"}`
- `{"type": {...}}` uses Playwright `fill()`, which does NOT require pointer actionability -
  perfect for proving a `pointer-events:none` overlay does not block keyboard input.
- Evidence agent-mode explorer = the SECOND `.ev-src-chip` (the first is the detected/legacy table).
- clicking a selector covered by an open teleported popover times out - close it first or
  dispatch a synthetic `mousedown` on an outside element.

See [[frontend-css-review-facts]] for styling-side facts and [[owismind-frontend-review-patterns]]
for scope-claim verification.
