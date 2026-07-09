---
name: feedback_devs_self_audit_charter
description: OWIsMind frontend devs already self-audit new views against the Orange charter in-code; review should verify claims with grep, not assume violations from scratch.
metadata:
  type: feedback
---

New Vue views/components in this repo tend to ship already charter-aware: style blocks carry an explicit
comment banner ("Orange charter: square geometry (border-radius 0), 1px borders, flat surfaces, orange a
RARE accent...") and `border-radius: 0` is set explicitly per rule even where it would already default to 0.
The repo also has a git hook (`.claude/hooks/dash-guard.sh`, PostToolUse on Write) that blocks any file
containing U+2014/U+2013 - so em/en dash violations get caught mechanically before they even reach review,
including in files this agent itself writes (e.g. memory files).

Why: user has run recurring compliance efforts here (see `docs/cadrage/CHARTE_ORANGE_UI.md`,
`memory/CONTEXT.md` rule #10) across many sessions, and the codebase reflects that discipline. First
Help & Support hub review (`HelpSupportView.vue`, 2026-07-08 session) came back fully compliant: zero hex
except the allowed `#fff` on an orange-background checkbox, zero color-mix/blur/gradient/glow, all
border-radius explicit 0, zero em/en dash, focus states scoped to the focused element only.

How to apply: still verify every rule against the actual diff (read the charter first, don't skip steps),
but calibrate expectations - a "clean" pass is a plausible real outcome here, not a sign the review was too
shallow. Useful greps: `grep -nP '[\x{2014}\x{2013}]'` for dashes, `grep -n "#[0-9a-fA-F]\{3,6\}"` for hex,
`grep -n "color-mix\|blur\|gradient\|box-shadow\|backdrop-filter"` for banned effects, and always confirm
any new icon/asset referenced (e.g. `Icon name="userPlus"`) resolves to the real SVG registry
(`components/ui/icons.js`) rather than a hand-rolled brand mark.

Do NOT false-flag these two charter-compliant patterns (both seen clean here, 2026-07-08 re-review of
HelpSupportView + AgentsView CTA):
- `outline: 2px solid var(--orange)` inside a `:focus-visible` on a single button/row element (e.g.
  `.sup-check-row:focus-visible`, offset -2px). The banned item is a GLOBAL orange focus ring englobing a
  text input's whole area; a per-element outline scoped to the focused control is exactly the charter's
  allowed "orange border on the focused element only." Text inputs here correctly use `border-color:
  var(--orange)` on focus, not an outline.
- `color: #fff` set unconditionally on a square checkbox whose check glyph only renders when `.on` (which
  adds `background: var(--orange)`). White-on-orange is the charter's single sanctioned hex exception.
