# ADR-0015 - The Orange charter: sober design system for the OWIsMind UI

> Audience: Frontend developer. Last updated: 2026-06-19. Summary: why OWIsMind's frontend
> follows the sober Orange design system (white/black, a single rare orange accent, square
> geometry, flat surfaces, semantic tokens, real logo image), and what is strictly forbidden
> in the stylesheet and the components.

## Status

Accepted. Decision made by the user on 2026-06-18 ("every time we do styling, it must be like
this"). The charter is formalized in `docs/cadrage/CHARTE_ORANGE_UI.md` (the self-contained
source of truth, to be read before any styling work) and loaded as rule #10 in every session via
`CLAUDE.md`. The refonte delivering this charter was built by 6 parallel Sonnet agents
(2026-06-19) and is packaged in the `index-BHeG2NRY.js` build (79 entries). Validated locally;
not yet confirmed in DSS.

## Context and problem

OWIsMind is an enterprise product running inside Dataiku DSS for a telecom company. The default
look from iterative UI work had accumulated stylistic decisions that were inconsistent and
sometimes at odds with Orange brand guidelines: rounded cards, glow effects, soft shadows,
backdrop-filter blur on modals, inline `color-mix()` functions that broke dark mode, and at
one point a logo that was reconstructed in CSS (an orange square + bar) rather than using the
actual brand image. End users of an Orange enterprise product expect the UI to feel like the
Orange brand: clean, authoritative, editorial, not decorated.

In addition, several specific problems needed to be addressed structurally:

- CSS-generated brand marks are an anti-pattern: they drift from the real brand image, look
  wrong at different DPRs, and require extra maintenance. The actual PNG exists.
- `color-mix()` is not universally supported and produces invisible text in dark mode when the
  underlying token is not defined in the dark scope.
- Hardcoded hex values bypass the semantic token system and break theming.
- Global focus rings that highlight the entire text-input area give the impression that the whole
  input box is an interactive brand element, rather than showing focus on the actual focused
  element only.

The user's decision was clear: "a sober, net Orange": white and black carry the layout; the
orange is a rare accent used ONLY on active states, eyebrows, title-bars, KPI rules, primary
actions and links. One palette. No decoration.

## Decision

The OWIsMind UI follows the Orange charter at all times. The charter is captured in
`docs/cadrage/CHARTE_ORANGE_UI.md`, which replaces the original HTML mockup that was
deleted after the charter was extracted from it. Any agent or developer doing styling work
MUST read that file first; this ADR records the WHY, the charter records the WHAT.

### Core spirit

Sober, authoritative, editorial. Three values:

1. **White and near-black carry the layout.** Orange is ONE accent, used rarely and
   purposefully, never as a background fill on large surfaces.
2. **Square geometry everywhere.** `border-radius: 0` on all surfaces (cards, chips, buttons,
   inputs, modals, checkboxes, tabs, search bars, icon tiles, KPI cards). The only exception
   is avatars (`border-radius: 50%`). The `--r*` radius tokens exist in the token file but are
   not used in OWIsMind.
3. **Flat surfaces, 1px borders, heavy headings.** No gradients, no blur, no glow. Shadows are
   limited to 1px (`var(--shadow)`). Borders are `var(--border-strong)` (visible) or
   `var(--border)` (soft). H1 headings are `--fs-3xl` (36px) / `--fw-heavy` (800).

### Semantic tokens (single source of truth)

All colors pass through the tokens in `frontend/src/styles/tokens.css`. Hardcoded hex values
are forbidden EXCEPT `#fff` on an orange background. The theme (light/dark) is driven by
`body[data-theme]`; using the semantic tokens makes dark mode automatic without per-component
overrides.

Key token assignments:

| Use case | Token |
|---|---|
| Orange accent (bars, backgrounds, primary action) | `var(--orange)` |
| Orange TEXT (AA-safe, links, eyebrows) | `var(--orange-text)` |
| Main text | `var(--text)` |
| Secondary text | `var(--text-2)` |
| Visible border | `var(--border-strong)` |
| Soft separator | `var(--border)` |
| Card/page background | `var(--bg)` |
| Heading weight | `var(--fw-heavy)` (800) |

Theme-specific overrides use `:global(body[data-theme="dark"] .class)` with the FULL selector
inside `:global` (the scoped-styles rule F2, from lesson L022). `color-mix()` is NEVER used
(L031); use `rgba()` with tokens.

### Typography pattern (H1 pages)

Every page title follows the three-element pattern:

1. **Eyebrow:** `var(--orange)`, uppercase, 12px, 700, `letter-spacing: 0.1em`.
2. **H1:** `--fs-3xl` (36px), `--fw-heavy` (800), `letter-spacing: -0.01em`, `line-height: 1.05`.
3. **Title-bar:** a filled block `52px x 4px` in `var(--orange)`, `margin: 16px 0 0`.

This pattern is implemented by the shared `PageShell` component; for custom headers
(using the `#header` slot), the three elements are reproduced manually.

### The real logo image (brand discipline rule)

The brand logo is ALWAYS the real PNG asset:

```js
import logoUrl from '../../assets/orange-logo.png'
// ...
<img :src="logoUrl" alt="Orange">
```

It is NEVER reconstructed in CSS (no orange square + bar pattern). This rule is the result of
a concrete incident (lesson L092): the shell component had replaced the logo with a CSS square
during the 2026-06-19 refonte, discovered after review, and the real image was rewired
immediately. The lesson is now rule #10 in `CLAUDE.md`: "always the REAL `orange-logo.png`
image, never a generated square".

### Hard bans

The following are absolutely forbidden in any OWIsMind stylesheet or component, with no
exception:

| Banned construct | Reason |
|---|---|
| Em dash (U+2014) / en dash (U+2013) | Typographic rule #9 (ADR-0012). |
| `color-mix()` | Breaks dark mode; use `rgba()` + tokens. |
| `blur` / `backdrop-filter` | No blur anywhere (decorative ban, also a performance concern on low-power devices). |
| `linear-gradient` / `radial-gradient` | No gradients: flat surfaces only. |
| Glow effects, large soft shadows | Maximum shadow = 1px `var(--shadow)`. |
| Emoji in the UI | Not in the Orange brand tone. |
| Global focus ring on the text-input area | The focus ring applies only to the actually-focused element, never a global selector that outlines the input container. |
| CSS-reconstructed brand mark | Always use the real `orange-logo.png` image, never a CSS-composed substitute (L092). |
| Rounded surfaces (`border-radius > 0`) | Only avatars are round (50%); all other surfaces are square (0). |
| Hardcoded hex color values | Exception: `#fff` on an orange background. Use tokens everywhere else. |

### Component patterns

Key patterns from the charter (full reference in `docs/cadrage/CHARTE_ORANGE_UI.md`):

- **Button:** square, ghost default (2px `var(--text)` border, transparent fill; hover inverts: `var(--text)` fill + `var(--bg)` text). Primary: filled `var(--orange)` + `#fff`, hover `var(--orange-deep)`. No rounded corners.
- **Modal:** flat scrim (`rgba(0,0,0,.55)`, no blur). Square card with 1px `var(--border-strong)`, zero radius, minimal shadow. The close button and icon tile are also square.
- **Cards:** `border: 1px solid var(--border-strong)`, `border-radius: 0`, `background: var(--bg)`.
- **Tabs:** bottom border row; active = `var(--text)` + 3px orange underline; inactive = `var(--text-2)`.
- **Shared primitives (`Button`, `Modal`):** the chat and Evidence panel inherit styles from the shared primitives. Any restyle of `Button` or `Modal` carries through to the chat view - verify no regression.

### Light/dark scope

Token-driven dark mode is automatic. The only case requiring an explicit scoped override is when
a component uses a token whose dark value is defined differently for a specific context. Use
`:global(body[data-theme="dark"] .component-class)` with the ENTIRE selector inside `:global`.
Never rely on CSS variables computed under the wrong scope (the cause of the dark-mode invisible
text bug fixed in lesson L084, tokens `--success-soft` / `--danger-soft`).

### Build and packaging

- Never hand-edit `resource/owismind-app/` (generated by Vite build). Edit `frontend/src` then
  run `/build-plugin`.
- `frontend/` and `node_modules/` are never included in the deployment zip.
- The build currently produces `index-BHeG2NRY.js` (79 entries, PNG bundled by Vite).
  `orange-logo.png` is bundled via the Vite asset pipeline - the `import` in the component
  triggers the bundle, so the image is available at the correct hashed URL in production.

## Rationale

- **Single point of reference for styling.** The charter file is the deleted mockup's
  replacement: a developer doing any UI work reads it first and never needs to reconstruct
  intent from scratch or from memory.
- **Semantic tokens prevent theming bugs.** Every dark-mode-invisible color in the history of
  this project (L084) was caused by a non-token value. The ban on hardcoded hex and `color-mix`
  makes dark mode robust by construction.
- **Square geometry is a brand posture, not a preference.** Orange's enterprise brand is
  authoritative and net: rounded corners soften that authority and produce a consumer-app feel
  that is off-brand.
- **The real logo is the only correct logo.** CSS-generated brand marks scale poorly, look
  incorrect at high DPR, and are maintenance liabilities. The PNG is already in the repository;
  using it is both simpler and correct.
- **Banning blur and glow is a safety posture.** Backdrop-filter blur is a GPU-heavy CSS
  property that can cause significant performance degradation on low-power or integrated-GPU
  machines. The flat-surface posture is not only on-brand but also safer for a shared
  enterprise instance.

## Consequences

Positive:

- Consistent, predictable UI that survives future contributions: the bans are checkable by grep
  and by Vite build (e.g. searching for `backdrop-filter` or `color-mix` in `.vue` files).
- Dark mode robust by construction: token-driven, no per-component theme override required for
  standard use cases.
- Logo integrity: the brand image is always the real PNG, never a CSS approximation.
- No infrastructure cost: the charter is a markdown file in `docs/cadrage/`, not a design-system
  npm package.

Negative or watch points:

- Square geometry is a constraint: any template or component from an external source (a library,
  a snippet) must be un-rounded before use. This is non-negotiable.
- The charter must be read before any styling task. A developer who skips it will inadvertently
  reintroduce bans (experienced three times in the history of this project: rounded modals,
  CSS logo, global focus ring).
- The orange accent MUST be rare. Overuse is as much a violation as total absence. The charter's
  80/20 heuristic: 80% white/black surfaces, 20% accent-bearing elements at most.

## Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Adopt a third-party design system (Material, Ant, etc.) | Would override the Orange brand posture and introduce large dependency trees (violates the NO INSTALL rule implicitly, and the brand direction explicitly). |
| Keep the original iterative styles with per-component fixes | Produced inconsistency (rounded here, square there; glow in one modal, flat in another); a single coherent charter is cleaner and more maintainable. |
| CSS-generated logo mark | Discovered to be wrong (L092): scales poorly, looks incorrect, is a maintenance liability. The PNG is in the repo and is the right choice. |
| Allow rounded corners on cards / modals | Inconsistent with the Orange editorial brand posture; user decision was explicit ("square, always"). |
| Use `color-mix()` for tinted surfaces | Broke dark mode (invisible text); `rgba()` + tokens is equivalent and robust. |

## See also

- `docs/cadrage/CHARTE_ORANGE_UI.md` - the authoritative style reference (read this before
  any styling task; it is the self-contained source of truth).
- `frontend/src/styles/tokens.css` - the semantic token definitions (colors, spacing,
  typography, weight scale).
- [Frontend - overview and structure](../03-frontend/01-overview-and-structure.md) - the
  Vue component structure, theme bootstrap and i18n that the charter's components live in.
- [ADR-0001 - Vue SPA served by DSS](0001-vue-spa-servie-par-dss.md) - the build pipeline
  that packages the frontend (including the logo PNG) as static assets.
- [ADR-0012 - Typographic rule: no em dash](0012-regle-typographique-sans-tiret-cadratin.md) -
  the complementary typographic rule (rule #9) that the charter references as its first ban.
- [Known gotchas and lessons](../09-maintenance/03-known-gotchas-and-lessons.md) - L084
  (dark-mode invisible tokens), L091 (brand discipline: no unauthorized accents), L092
  (the CSS-generated logo incident that crystallized the real-image rule).
- [ADR index](README.md) - all architecture decisions.
- [Documentation portal](../README.md) - back to the general table of contents.
