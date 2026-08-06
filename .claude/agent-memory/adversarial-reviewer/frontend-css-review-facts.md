---
name: frontend-css-review-facts
description: Verified facts + one near-miss false positive for reviewing OWIsMind frontend styling/UX diffs (markdown sanitizer, scoped keyframes, theme tokens, flex anchoring)
metadata:
  type: reference
---

Established by tracing/compiling during the 2026-08-07 "premium attention" UX pass review. All
verified against the real files, not assumed.

**DOMPurify keeps `style`.** `composables/useMarkdown.js` calls
`DOMPurify.sanitize(raw, { USE_PROFILES: { html: true } })`. In dompurify 3.4.8, `'style'` IS in the
html attribute allowlist (`purify.cjs.js` line 315) and also in `DEFAULT_URI_SAFE_ATTRIBUTES` (line 614),
and `SAFE_FOR_TEMPLATES` is off, so attribute values pass through byte-identical. markdown-it emits the
compact form `<th style="text-align:right">` (no space; confirmed by running markdown-it directly).
Consequence: column alignment in agent markdown tables works through the INLINE style, which outranks
any stylesheet rule - CSS `[style*="text-align:right"]` selectors are belt-and-braces, never load-bearing.

**Scoped CSS does not rename foreign keyframes.** A Vue 3 `<style scoped>` block may reference a
`@keyframes` defined in `styles/base.css` (e.g. `owi-rise`, `slide-up`, `shimmer-sweep`); the compiler
only rewrites keyframes DEFINED in the same block. Verified in the built CSS:
`.send-hint[data-v-...]{animation:owi-rise ...}` with `@keyframes owi-rise` living in the global bundle.

**`--orange` is theme-invariant.** The dark block `body[data-theme="dark"]` redefines only
`--orange-soft-dark`, `--orange-on-dark`, `--orange-text` - never `--orange` itself. So a CSS swatch
`background: var(--orange)` always matches a canvas color resolved via `cssVar('--orange')` (palette
slot 0 in `ArtifactChart.buildConfig`, assigned as `pal[i % pal.length]` with `i === 0` for a lone dataset).

**Standing pre-existing bug (do NOT blame a diff for it).** `ArtifactChart.cssVar()` reads
`getComputedStyle(document.documentElement)` (`<html>`), but every dark token lives on
`body[data-theme="dark"]`. Custom properties inherit DOWN, so html never sees them: canvas-baked
axis/tick/legend colors keep their LIGHT values in dark mode, even though the MutationObserver
re-render fires correctly. Moving text out of the canvas into HTML (tokens resolve normally there) is
a fix in the right direction, not a regression.

**Near-miss false positive worth remembering - flex anchoring before claiming a click-swallow.**
I nearly reported HIGH on the new focus-conditional `.send-hint` in `PromptBar.vue`: mousedown on the
send button blurs the textarea, `v-if` removes the hint, Vue flushes in a microtask before mouseup, so
a layout shift WOULD retarget the click to a common ancestor and swallow the send. The reasoning about
event ordering is correct and reusable, but the geometry refutes it here: `.prompt-row` is
`justify-content: space-between` and `.prompt-right` is the last child, so the group is RIGHT-anchored
and the hint is its FIRST child. Removing a leading item in a right-anchored flex group moves only the
group's left edge - the mic and send buttons do not move. **Rule: before reporting a
disappearing-sibling click-swallow, determine which edge of the flex group is anchored and where the
conditional element sits in source order.**

**Equal-specificity hover-vs-active.** `.side-item:hover` / `.conv-item:hover` (0,2,0) lose to
`.side-item.active` / `.conv-item.active` (0,2,0) because `.active` is later in source. Confirmed in
the built CSS. Any "make hover stronger" pass silently excludes the active row unless it adds
`:hover` to the active selector. Verify in the BUILT css, not the source, since bundlers may merge rules.

See [[owismind-frontend-review-patterns]] for scope-claim verification and [[repo-review-pitfalls]] for
the dash scan and baseline test counts.
