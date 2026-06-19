# OWIsMind Documentation Site

A self-contained, offline HTML documentation portal for the OWIsMind Dataiku DSS plugin.

## How to open it

Double-click `site/index.html` in your file explorer, or open it in any browser using
`File > Open`. No web server is needed. The site works entirely on the `file://` protocol.

## What it covers

Eight pages arranged as a learning journey, from product overview to architecture decisions:

| Page | File | Audience |
|------|------|----------|
| Welcome | index.html | Everyone |
| The Experience | 01-experience.html | End users |
| Architecture | 02-architecture.html | All technical |
| Frontend | 03-frontend.html | Frontend developers |
| Backend | 04-backend.html | Backend developers |
| The Agents (the brain) | 05-agents.html | AI / agent developers |
| Operations and Maintenance | 06-operations.html | Admins and operators |
| Decisions (ADR) | 07-decisions.html | Anyone asking "why" |

Navigation is provided by the icon rail on the left, the prev/next pager at the bottom of
each page, and a full-text search overlay (press `/` or `Ctrl+K`).

## Self-contained / offline design

- No external network requests. No CDN, no Google Fonts, no remote scripts.
- All assets live under `site/assets/` (site.css, site.js, search-index.js, orange-logo.png).
- The search index is pre-built in `assets/search-index.js` (80 entries covering every page
  and its major sections).
- Dark mode is supported via a CSS variable system toggled by the sun/moon button.

## Source of truth

This site is generated from the canonical markdown documentation under
`project-documentation/` (folders 00-overview through 09-maintenance, plus 08-decisions
and the presentation deck). The `.md` files remain the authoritative source. Each page
links back to its source files using the `source-ref` link style.

When the underlying `.md` documentation changes, the HTML pages should be updated
to reflect the change. The HTML content is authored directly (no build step needed for
the site itself - only the OWIsMind plugin frontend requires `npm run build`).

## File layout

```
site/
  index.html                  - Welcome / landing page
  01-experience.html
  02-architecture.html
  03-frontend.html
  04-backend.html
  05-agents.html
  06-operations.html
  07-decisions.html
  _TEMPLATE.html              - Blank template for new pages (not a live page)
  _STYLEGUIDE.md              - Component catalogue and CSS conventions
  assets/
    site.css                  - Design system (Orange charter: white/black/orange, square geometry)
    site.js                   - Rail, topbar, TOC, pager, search, theme, code copy
    search-index.js           - Pre-built full-text search index (window.SEARCH_INDEX)
    orange-logo.png           - Real Orange brand logo (never rebuilt in CSS)
```
