# OWIsMind Docs - Station Agent Style Guide

This is your contract. Copy `_TEMPLATE.html`, set `data-page` and `<title>`, then fill in `<main>`. Everything else (rail, topbar, TOC, pager) is rendered by `site.js` automatically.

---

## Quick-start

1. Copy `_TEMPLATE.html` to your page file (e.g. `02-architecture.html`).
2. Set `<title>Architecture - OWIsMind Docs</title>`.
3. Set `<body data-page="architecture">` (see valid page keys below).
4. Fill in the **Page Header** block (eyebrow / h1 / page-sub).
5. Author `<main>` content using the components in this guide.
6. Delete the example blocks from the template.

Valid `data-page` values (must match the PAGES array in `site.js`):

| data-page | File | Title |
|-----------|------|-------|
| `welcome` | index.html | Welcome |
| `experience` | 01-experience.html | The Experience |
| `architecture` | 02-architecture.html | Architecture |
| `frontend` | 03-frontend.html | Frontend |
| `backend` | 04-backend.html | Backend |
| `agents` | 05-agents.html | The Agents (the brain) |
| `operations` | 06-operations.html | Operations & Maintenance |
| `decisions` | 07-decisions.html | Decisions (ADR) |

---

## Non-negotiable rules

1. **NO em dash (U+2014) or en dash (U+2013) anywhere** - in text, code comments, attributes. Use `-`, `:`, `,`, or parentheses.
2. **No external network references** - all assets must be under `site/assets/`. No CDN links, no Google Fonts, no remote images.
3. **No inline event handlers** (`onclick=`, `onmouseover=`) - the JS handles interactivity.
4. **No hardcoded colors** in `style=""` attributes - always use CSS classes and the token variables.
5. **Use the real logo image** (`assets/orange-logo.png`) if you embed it in content. Never CSS-generate it.
6. **No emoji** in the UI or content.
7. **You author only `<main>` content**. Do not add a second `<nav>`, `<header>`, or `<footer>` at the shell level.
8. **Heading hierarchy**: `h2` = major section (TOC entry), `h3` = subsection (TOC entry, indented), `h4` = minor label (not in TOC).

---

## Color palette

| Purpose | Token | Value |
|---------|-------|-------|
| Background | `--bg` | #fff / #0a0a0a |
| Panel / card | `--panel` | #fff / #141414 |
| Soft fill | `--soft` | #f6f6f6 / #1a1a1a |
| Primary text | `--ink` | #000 / #fff |
| Secondary text | `--ink-2` | #595959 / #b0b0b0 |
| Muted text | `--ink-3` | #8f8f8f / #7d7d7d |
| Borders | `--line` | #ccc / #333 |
| Soft borders | `--line-soft` | #e4e4e4 / #262626 |
| Orange accent (rare) | `--orange` | #ff7900 |
| Orange text (AA on white) | `--orange-deep` | #f16e00 |

**Orange is an accent, not a fill.** Use it only on: active states, eyebrows, title-bars, primary CTAs, KPI top-rules, key links.

---

## Components

### Page Header

Always the first element inside `.wrap`. Required on every page.

```html
<header class="page-header">
  <p class="eyebrow">Level 2 - Understand</p>
  <h1>Architecture</h1>
  <span class="title-bar" aria-hidden="true"></span>
  <p class="page-sub">How the system is structured: frontend, backend, agents, and storage.</p>
</header>
```

---

### Callout boxes

Four variants. Use an `<aside>` with `role="note"`. No emoji - use SVG icons only.

```html
<!-- NOTE (grey left rule) -->
<aside class="callout callout-note" role="note">
  <svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
    <circle cx="12" cy="12" r="10"/>
    <line x1="12" y1="8" x2="12" y2="12"/>
    <line x1="12" y1="16" x2="12.01" y2="16"/>
  </svg>
  <div class="callout-body">
    <p class="callout-title">Note</p>
    <p>Contextual information.</p>
  </div>
</aside>

<!-- WARNING (orange left rule) -->
<aside class="callout callout-warning" role="note">
  <svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
    <path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/>
    <line x1="12" y1="9" x2="12" y2="13"/>
    <line x1="12" y1="17" x2="12.01" y2="17"/>
  </svg>
  <div class="callout-body">
    <p class="callout-title">Warning</p>
    <p>Something important to be aware of.</p>
  </div>
</aside>

<!-- IN-FLUX (yellow left rule - something actively changing) -->
<aside class="callout callout-influx" role="note">
  <svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
    <polyline points="23 4 23 10 17 10"/>
    <path d="M20.49 15a9 9 0 11-2.12-9.36L23 10"/>
  </svg>
  <div class="callout-body">
    <p class="callout-title">In Flux</p>
    <p>This is actively changing.</p>
  </div>
</aside>

<!-- ROADMAP (grey left rule - not yet built) -->
<aside class="callout callout-roadmap" role="note">
  <svg class="callout-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true">
    <circle cx="12" cy="12" r="10"/>
    <polyline points="12,6 12,12 16,14"/>
  </svg>
  <div class="callout-body">
    <p class="callout-title">Roadmap</p>
    <p>Planned but not yet implemented.</p>
  </div>
</aside>
```

---

### Code block with copy button

```html
<div class="code-block">
  <div class="code-block-header">
    <span class="code-filename">path/to/file.py</span>
    <span class="code-lang">Python</span>
    <button class="code-copy" aria-label="Copy code">Copy</button>
  </div>
  <pre><code>def my_function():
    return "hello"</code></pre>
</div>
```

The `code-copy` button is wired automatically by `site.js`. The filename span is optional - omit it if there is no specific file path. The `code-lang` span is optional.

---

### KPI card (orange top rule, big number)

```html
<div class="card kpi">
  <p class="k-label">Total agents</p>
  <p class="k-val">2</p>
  <p class="k-sub">Deployed in DSS env 3.11</p>
</div>
```

Add `.mono` to `.k-val` for monospace numbers: `<p class="k-val mono">8</p>`

Use `.grid-3` or `.grid-2` to lay them out side by side:

```html
<div class="grid-3">
  <div class="card kpi">...</div>
  <div class="card kpi">...</div>
  <div class="card kpi">...</div>
</div>
```

---

### Card

```html
<div class="card card-pad">
  <p class="card-label">Card label</p>
  <p>Card body content.</p>
</div>
```

Multi-block card (sections separated by a 1px line):

```html
<div class="card">
  <div class="block">
    <p class="block-title">Section one</p>
    <p class="block-note">Some explanation.</p>
  </div>
  <div class="block">
    <p class="block-title">Section two</p>
    <p>More content.</p>
  </div>
</div>
```

---

### Chips

```html
<div class="chips">
  <span class="chip">SQL direct</span>
  <span class="chip accent">Validated DSS</span>
</div>
```

`.chip` = plain bordered square tag. `.chip.accent` = orange border + deep-orange text.

---

### Table

Wrap in `.card` for a bordered container:

```html
<div class="card">
  <table>
    <thead>
      <tr>
        <th>Column A</th>
        <th>Column B</th>
        <th>Column C</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <td><code>webapp_chat_v5</code></td>
        <td>Conversations and exchanges</td>
        <td>v5</td>
      </tr>
    </tbody>
  </table>
</div>
```

---

### Buttons

```html
<!-- Default: ink border, inverts on hover -->
<button class="btn">Secondary action</button>

<!-- Primary: orange fill -->
<button class="btn btn-primary">Primary action</button>

<!-- Small variants -->
<button class="btn btn-sm">Small</button>
<button class="btn btn-primary btn-sm">Small primary</button>

<!-- As an anchor -->
<a href="02-architecture.html" class="btn">Go to Architecture</a>
```

---

### Diagram (inline SVG with theme tokens)

Wrap with `.diagram-wrap`. Apply class `diagram` to the `<svg>`. Use the theming helper classes on elements inside:

| Class | Purpose |
|-------|---------|
| `.node` | White/panel fill, border |
| `.node-soft` | Soft fill, border |
| `.node-accent` | Orange fill |
| `.edge` | Grey stroke line |
| `.edge-accent` | Orange stroke line |
| `.lane` | Soft background rectangle |
| `.arrowhead` | Grey arrow fill |
| `.arrowhead-accent` | Orange arrow fill |
| `text` (element) | Inherits ink color and font |
| `.text-muted` | `--ink-3` color |
| `.text-accent` | `--orange-deep` color |

```html
<figure class="diagram-wrap">
  <svg class="diagram diagram-svg" viewBox="0 0 400 120" xmlns="http://www.w3.org/2000/svg">
    <rect class="lane" x="0" y="0" width="400" height="120"/>

    <rect class="node" x="20" y="40" width="100" height="40"/>
    <text x="70" y="65" text-anchor="middle" class="diagram">Vue 3</text>

    <line class="edge" x1="120" y1="60" x2="160" y2="60"/>
    <polygon class="arrowhead" points="160,55 170,60 160,65"/>

    <rect class="node-accent" x="170" y="40" width="100" height="40"/>
    <text x="220" y="62" text-anchor="middle" fill="#fff" class="diagram">Backend</text>

    <line class="edge-accent" x1="270" y1="60" x2="310" y2="60"/>
    <polygon class="arrowhead-accent" points="310,55 320,60 310,65"/>

    <rect class="node" x="320" y="40" width="60" height="40"/>
    <text x="350" y="65" text-anchor="middle" class="diagram">DSS</text>
  </svg>
  <p class="diagram-caption">Caption describing what the diagram shows.</p>
</figure>
```

---

### Source reference link

Link to the canonical `.md` source file. Place it after a section or at the bottom of a card.

```html
<a href="../05-agents/01-agent-overview.md" class="source-ref">
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="12" height="12" aria-hidden="true">
    <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/>
    <polyline points="15,3 21,3 21,9"/>
    <line x1="10" y1="14" x2="21" y2="3"/>
  </svg>
  Source: 05-agents/01-agent-overview.md
</a>
```

---

### Key/value metadata block

```html
<dl class="kv">
  <dt>Plugin ID</dt>
  <dd>owismind</dd>
  <dt>SQL connection</dt>
  <dd>SQL_owi (PostgreSQL)</dd>
  <dt>Frontend build</dt>
  <dd>Vue 3 + Vite</dd>
</dl>
```

---

### Badges

```html
<!-- Orange filled (admin / primary) -->
<span class="badge-admin">Admin</span>

<!-- Neutral bordered badge -->
<span class="badge">v5</span>

<!-- Orange filled small badge -->
<span class="badge orange">Live</span>
```

---

### Grid layouts

```html
<div class="grid-2">...</div>   <!-- 2 columns -->
<div class="grid-3">...</div>   <!-- 3 columns -->
<div class="grid-4">...</div>   <!-- 4 columns (no gap, borders between) -->
```

All grids collapse to 1 column below 880px.

---

### Utility classes

| Class | Effect |
|-------|--------|
| `.mt` | margin-top: 16px |
| `.mt-2` | margin-top: 24px |
| `.mt-3` | margin-top: 36px |
| `.mb` | margin-bottom: 16px |
| `.stack` | flex column, gap 16px |
| `.row` | flex row, align center, gap 12px |
| `.u-mono` | monospace font |
| `.u-muted` | `--ink-3` color |
| `.u-small` | font-size: 12px |
| `.u-upper` | uppercase label style (11px/800/spaced) |

---

## Search index (optional)

If you want your page's content to appear in search results, add entries to `assets/search-index.js`:

```js
// assets/search-index.js
window.SEARCH_INDEX = window.SEARCH_INDEX || [];
window.SEARCH_INDEX.push(
  {
    file: '02-architecture.html',
    page: 'Architecture',
    anchor: 'system-overview',      // the h2 id generated by site.js
    title: 'System Overview',
    text: 'Plain text content of this section, no HTML tags.'
  }
  // ... more entries
);
```

Each station agent can append to `window.SEARCH_INDEX` from its own page. The array is merged at runtime across all included scripts.

---

## What site.js does automatically

You do not need to author, call, or configure any of these:

- **Rail**: built from the `PAGES` array, marks the current page active.
- **Topbar**: breadcrumb "OWIsMind docs / Page Title", depth meter (0-7 pips), theme toggle, search trigger.
- **TOC**: scans `<main>` for `h2`/`h3`, assigns stable IDs via `slugify()`, builds the sticky sidebar, scrollspy highlights active section.
- **Pager**: prev/next links from the ordered `PAGES` array.
- **Theme**: reads/writes `localStorage['owi-theme']`, sets `body[data-theme]`.
- **Search**: keyboard shortcut `/` or Cmd+K opens the overlay. Reads `window.SEARCH_INDEX`.
- **Code copy**: `.code-copy` buttons are wired to copy the sibling `<pre>` content.
- **Smooth scroll**: all `<a href="#...">` links scroll smoothly.
- **Mobile**: rail collapses to a hamburger-revealed drawer below 640px.
- **Escape key**: closes search overlay and mobile rail.
