---
name: recurring-charter-leftovers
description: The four charter violations that survive every OWIsMind styling pass - grep these first, they are almost always present.
metadata:
  type: reference
---

Four leftovers recur in every large styling pass of this frontend. Grep them at the START of a review, before reading the diff line by line:

1. **Orange focus on form fields.** A pass converts `:hover` to `var(--text-3)` and forgets the `:focus` line right below it. Grep: `grep -rn ':focus[^{]*{[^}]*var(--orange)\|:focus-within[^{]*{[^}]*var(--orange)' --include='*.vue' src`. Keep only the `outline: 2px solid var(--orange)` hits (keyboard focus-visible on buttons/rows, sanctioned); every `border-color: var(--orange)` on an input / select / textarea / search wrapper breaks the ratified field-focus recipe (border `--text-3` + `--elev-1`).
2. **Gauges get pill-ified.** Progress/accuracy bars (`.q-mini-bar` in AdminView, `.meter` in BenchmarkSuggestView) are STRUCTURAL and stay square, but they read as "capsules" to whoever rounds the chips. Data tables, panel headers and KPI tiles are usually handled correctly; the gauges are not.
3. **`Tabs.vue` gets edited** despite the explicit ban in charter section 6 (it is shared with the validated Evidence panel). The tell: a consumer adds a defensive `:deep(.ui-tabs .ui-tab)::after` with a comment about winning "regardless of stylesheet order" - that specificity fight only exists because the primitive was touched.
4. **A hardcoded colour hides in the dark override.** The light rule uses tokens, then `:global(body[data-theme="dark"] .x)` drops a raw hex. Grep `#[0-9a-fA-F]{3,6}` on the diff and check every hit that is not `#fff` on orange or a tokens.css definition.

Related: [[dark-theme-override-blind-spot]], [[devs-self-audit-charter]].
