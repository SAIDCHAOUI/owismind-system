---
name: v2-charter-precedence-radius-regression
description: On branch OWIsMind_PRD_V2_0 the V2 charter (OWIsMind_PRD_V2_0/docs/CHARTE_V2_UI.md) overrides CHARTE_ORANGE_UI.md; recurring regression = devs re-square V2 radius tokens to 0 citing the V1.3 charter.
metadata:
  type: project
---

V2 charter (`OWIsMind_PRD_V2_0/docs/CHARTE_V2_UI.md`, user decision D1 2026-10-15) takes precedence on V2
screens: radii 2-8px via tokens (`--r-pill` = 4px, `--r-lg` = 8px), NO title-bar, NO orange top rule on
cards/KPI, primary action = orange fill + `--on-orange` (black ink, so `#fff` on orange is no longer the
sanctioned exception), weights 400/700 only (`--fw-heavy` maps to 700), `--tracking-eyebrow` = 0, Studio
labels are 12/700 sentence case, floating layers may use `--float` / `--float-strong`.

Observed 2026-10-20 (MeasurePicker rewrite + SourceWorkspace builder): a dev pass replaced `--r-pill` /
`--r-lg` with `border-radius: 0` and wrote comments "SQUARE (charte)", while sibling SourceChips, the
search box and `ui/Menu.vue` keep V2 radii. Same panel ends up mixing square and 4px chips.

**Why:** the V1.3 charter is still auto-referenced by CLAUDE.md rule #10, so implementers default to it.
**How to apply:** on V2 files, grep `border-radius: 0` in the diff and compare with the sibling component
(SourceChips `.src-pop` / `.src-chip`, `ui/Menu.vue`); also flag pre-existing `border-top: 3px solid
var(--orange)` KPI rules and `#fff` on orange. Related: [[recurring-charter-traps]].

Not violations on V2 (reviewed 2026-10-21, Studio BoardGrid/WidgetCard): a transient orange drag-drop
insertion bar (3px, shown only while dragging), the pulsed 8px orange wait square, and `--orange-text`
+ `--orange-line` underline on an active provenance link are V2 SIGNALS (CHARTE_V2 section 2), not
decoration. Markdown tables in Studio text widgets copy the chat `.body` table recipe (11px uppercase
th) on purpose: consistency with MessageAgent, do not flag.

Also not violations (reviewed 2026-10-22, StudioWaiting + Studio header re-layout): square abstract
tiles of the waiting composition (skeleton art, not cards), a hopping 8px orange cursor running at the
same time as the header `.ws-live` pulse (CHARTE_V2 section 2 already sanctions several pulsed running
squares: header + pending widget). Known doc drift, not a code fix: CHARTE_V2 section 3 still says
"en-tete 56 px aligne sur la barre du chat" while the header now holds title + tabs on one grid row
(~90px, user-requested); flag it to the lead as a charter update, do not re-impose 56px.

Seen again 2026-10-22 (chat/SuggestionChips.vue): the lead's own brief said "square chips", the dev wrote
`border-radius: 0` while every chat chip sibling uses `--r-pill`; also an 11px uppercase label in
`--text-3` (~3.3:1, fails AA). Fixed both and told the lead the brief conflicts with CHARTE_V2.
