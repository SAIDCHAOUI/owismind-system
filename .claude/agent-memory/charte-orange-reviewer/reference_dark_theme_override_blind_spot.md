---
name: reference_dark_theme_override_blind_spot
description: Recurring charter miss in this repo - a squaring/de-shadowing pass fixes the light rule but leaves the matching :global(body[data-theme="dark"] ...) override with the banned soft shadow. Always grep data-theme in every changed file.
metadata:
  type: reference
---

Several Vue components keep a theme override BELOW the main rule, e.g.
`components/ui/Menu.vue` has `.ui-menu { box-shadow: ... }` at the top of the scoped block and
`:global(body[data-theme="dark"] .ui-menu) { box-shadow: 0 8px 28px rgba(0,0,0,.5), 0 2px 6px rgba(0,0,0,.3); }`
about 10 lines further down. A styling pass that replaces the light shadow with `var(--shadow)` reads
as compliant in the diff hunk, while dark mode still ships the banned glow. Caught 2026-08-07 on the
"premium attention" UX pass (Menu.vue light rule fixed, dark override untouched).

How to apply: for EVERY changed `.vue` file, run
`grep -n 'data-theme' <file>` and read each override, not just the diff hunks. The correct fix is almost
always to DELETE the dark override: `--shadow`, `--surface-hover`, `--border-strong`, `--success-soft`,
`--danger-soft` all already have dark variants in `styles/tokens.css`, so a single token-driven rule
covers both themes (charter section 6). Legitimate overrides that must stay are the `--orange-soft` ->
`--orange-soft-dark` background swaps (rule F2), since there is no single token for that pair.

Same blind spot applies to `border-radius` and hardcoded hex inside those override blocks
(`Menu.vue` still has `color: #f87171` for dark danger). See [[feedback_devs_self_audit_charter]].
