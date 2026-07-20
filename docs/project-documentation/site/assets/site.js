/**
 * OWIsMind Documentation Site - Core JavaScript
 * Dependency-free vanilla JS. Offline/file:// safe.
 * No em dash anywhere in this file.
 *
 * Security: all user-derived or index-derived strings are inserted
 * via textContent or explicit attribute setters - never via
 * innerHTML concatenation. Only fully-static, author-controlled
 * markup (SVG icons, fixed skeleton HTML) uses innerHTML.
 */

/* ============================================================
   JOURNEY: ordered pages from simple to deeply technical
   ============================================================ */
var PAGES = [
  {
    file: 'index.html',
    page: 'welcome',
    title: 'Welcome',
    level: 0,
    group: 'Discover'
  },
  {
    file: '01-experience.html',
    page: 'experience',
    title: 'The Experience',
    level: 1,
    group: 'Use'
  },
  {
    file: '02-architecture.html',
    page: 'architecture',
    title: 'Architecture',
    level: 2,
    group: 'Understand'
  },
  {
    file: '03-frontend.html',
    page: 'frontend',
    title: 'Frontend',
    level: 3,
    group: 'Build'
  },
  {
    file: '04-backend.html',
    page: 'backend',
    title: 'Backend',
    level: 4,
    group: 'Build'
  },
  {
    file: '05-agents.html',
    page: 'agents',
    title: 'The Agents (the brain)',
    level: 5,
    group: 'Build'
  },
  {
    file: '06-operations.html',
    page: 'operations',
    title: 'Operations & Maintenance',
    level: 6,
    group: 'Operate'
  },
  {
    file: '07-decisions.html',
    page: 'decisions',
    title: 'Decisions (ADR)',
    level: 7,
    group: 'Decide'
  }
];

var MAX_LEVEL = 7;

/* ============================================================
   SVG ICONS - static authored strings, safe for innerHTML
   ============================================================ */
var ICONS = {
  home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9,22 9,12 15,12 15,22"/></svg>',
  book: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/></svg>',
  cpu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="6" height="6"/><rect x="2" y="2" width="20" height="20" rx="2"/><line x1="9" y1="2" x2="9" y2="9"/><line x1="15" y1="2" x2="15" y2="9"/><line x1="9" y1="15" x2="9" y2="22"/><line x1="15" y1="15" x2="15" y2="22"/><line x1="2" y1="9" x2="9" y2="9"/><line x1="2" y1="15" x2="9" y2="15"/><line x1="15" y1="9" x2="22" y2="9"/><line x1="15" y1="15" x2="22" y2="15"/></svg>',
  layers: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="12,2 2,7 12,12 22,7"/><polyline points="2,17 12,22 22,17"/><polyline points="2,12 12,17 22,12"/></svg>',
  server: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="2" y="2" width="20" height="8" rx="2"/><rect x="2" y="14" width="20" height="8" rx="2"/><line x1="6" y1="6" x2="6" y2="6"/><line x1="6" y1="18" x2="6" y2="18"/></svg>',
  zap: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polygon points="13,2 3,14 12,14 11,22 21,10 12,10"/></svg>',
  settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/></svg>',
  clipboard: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/></svg>',
  sun: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>',
  moon: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z"/></svg>',
  search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
  arrowRight: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="5" y1="12" x2="19" y2="12"/><polyline points="12,5 19,12 12,19"/></svg>',
  arrowLeft: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="19" y1="12" x2="5" y2="12"/><polyline points="12,19 5,12 12,5"/></svg>',
  externalLink: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6"/><polyline points="15,3 21,3 21,9"/><line x1="10" y1="14" x2="21" y2="3"/></svg>',
  menu: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>'
};

var PAGE_ICONS = {
  'welcome':      ICONS.home,
  'experience':   ICONS.book,
  'architecture': ICONS.layers,
  'frontend':     ICONS.cpu,
  'backend':      ICONS.server,
  'agents':       ICONS.zap,
  'operations':   ICONS.settings,
  'decisions':    ICONS.clipboard
};

/* ============================================================
   DOM HELPERS - create elements without innerHTML for data
   ============================================================ */

/** Create an element with optional class(es) and text content. */
function el(tag, opts) {
  var node = document.createElement(tag);
  if (opts) {
    if (opts.cls) node.className = opts.cls;
    if (opts.text !== undefined) node.textContent = opts.text;
    if (opts.id) node.id = opts.id;
    if (opts.attrs) {
      Object.keys(opts.attrs).forEach(function(k) {
        node.setAttribute(k, opts.attrs[k]);
      });
    }
  }
  return node;
}

/** Set innerHTML from a static authored string (icons, fixed skeletons). */
function setStaticHtml(node, html) {
  node.innerHTML = html;
  return node;
}

/** Append multiple children to a parent. */
function append(parent) {
  var children = Array.prototype.slice.call(arguments, 1);
  children.forEach(function(c) { if (c) parent.appendChild(c); });
  return parent;
}

/* ============================================================
   THEME
   ============================================================ */
function getTheme() {
  return localStorage.getItem('owi-theme') || 'light';
}

function setTheme(t) {
  document.body.dataset.theme = t;
  localStorage.setItem('owi-theme', t);
  document.querySelectorAll('.theme-toggle-btn').forEach(function(btn) {
    btn.setAttribute('aria-label', t === 'dark' ? 'Switch to light mode' : 'Switch to dark mode');
    var iconSun  = btn.querySelector('.icon-sun');
    var iconMoon = btn.querySelector('.icon-moon');
    if (iconSun)  iconSun.style.display  = (t === 'dark')  ? 'block' : 'none';
    if (iconMoon) iconMoon.style.display = (t === 'light') ? 'block' : 'none';
  });
}

function toggleTheme() {
  setTheme(getTheme() === 'dark' ? 'light' : 'dark');
}

/** Build the sun/moon icon pair for a theme toggle button (static SVG). */
function buildThemeIcons(theme) {
  var sunSpan  = el('span', { cls: 'icon-sun' });
  var moonSpan = el('span', { cls: 'icon-moon' });
  setStaticHtml(sunSpan,  ICONS.sun);
  setStaticHtml(moonSpan, ICONS.moon);
  sunSpan.style.display  = (theme === 'dark')  ? 'block' : 'none';
  moonSpan.style.display = (theme === 'light') ? 'block' : 'none';
  return [sunSpan, moonSpan];
}

/* ============================================================
   RAIL RENDERER - uses DOM methods for data, innerHTML for icons
   ============================================================ */
function renderRail(currentPage) {
  var rail = document.getElementById('rail');
  if (!rail) return;

  rail.textContent = ''; // clear

  // Logo
  var logoA = el('a', {
    cls: 'rail-logo',
    attrs: { href: 'index.html', 'aria-label': 'OWIsMind docs home' }
  });
  var logoImg = el('img', {
    attrs: { src: 'assets/orange-logo.png', alt: 'OWIsMind' }
  });
  logoA.appendChild(logoImg);
  rail.appendChild(logoA);

  // Nav links per page
  PAGES.forEach(function(p) {
    var isActive = p.page === currentPage;
    var a = el('a', {
      cls: 'rail-btn' + (isActive ? ' active' : ''),
      attrs: {
        href: p.file,
        'aria-label': p.title,
        title: p.title
      }
    });
    setStaticHtml(a, PAGE_ICONS[p.page] || ICONS.book); // static SVG icon
    rail.appendChild(a);
  });

  // Spacer
  rail.appendChild(el('div', { cls: 'rail-sp' }));

  // Search trigger
  var searchBtn = el('button', {
    cls: 'rail-btn',
    id: 'rail-search-btn',
    attrs: { 'aria-label': 'Search documentation', title: 'Search' }
  });
  setStaticHtml(searchBtn, ICONS.search);
  searchBtn.addEventListener('click', openSearch);
  rail.appendChild(searchBtn);

  // Theme toggle
  var theme = getTheme();
  var themeBtn = el('button', {
    cls: 'rail-btn rail-theme theme-toggle-btn',
    attrs: {
      'aria-label': theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode',
      title: 'Toggle theme'
    }
  });
  var themeIcons = buildThemeIcons(theme);
  themeBtn.appendChild(themeIcons[0]);
  themeBtn.appendChild(themeIcons[1]);
  themeBtn.addEventListener('click', toggleTheme);
  rail.appendChild(themeBtn);
}

/* ============================================================
   TOPBAR RENDERER - uses DOM methods for all data-derived strings
   ============================================================ */
function renderTopbar(currentPage) {
  var topbar = document.getElementById('topbar');
  if (!topbar) return;

  topbar.textContent = '';

  var page  = PAGES.find(function(p) { return p.page === currentPage; });
  var level = page ? page.level : 0;
  var title = page ? page.title : 'OWIsMind';
  var group = page ? page.group : 'Discover';

  // Mobile menu toggle
  var menuBtn = el('button', {
    cls: 'icon-btn',
    id: 'menu-toggle',
    attrs: { 'aria-label': 'Toggle navigation' }
  });
  setStaticHtml(menuBtn, ICONS.menu);
  menuBtn.addEventListener('click', function() {
    var railEl = document.getElementById('rail');
    if (railEl) railEl.classList.toggle('open');
  });
  topbar.appendChild(menuBtn);

  // Breadcrumb
  var breadcrumb = el('div', { cls: 'topbar-breadcrumb' });
  var homeLink = el('a', { text: 'OWIsMind docs', attrs: { href: 'index.html' } });
  breadcrumb.appendChild(homeLink);
  if (currentPage !== 'welcome') {
    var sep = el('span', { cls: 'sep', text: '/' });
    var current = el('span', { cls: 'current', text: title });
    breadcrumb.appendChild(sep);
    breadcrumb.appendChild(current);
  }
  topbar.appendChild(breadcrumb);

  // Depth meter
  var meter = el('div', {
    cls: 'depth-meter',
    attrs: { 'aria-label': 'Depth: level ' + level + ' of ' + MAX_LEVEL }
  });
  for (var i = 0; i <= MAX_LEVEL; i++) {
    var pip = el('div', { cls: 'depth-pip' + (i <= level ? ' filled' : '') });
    meter.appendChild(pip);
  }
  var depthLabel = el('span', { cls: 'depth-label', text: group });
  meter.appendChild(depthLabel);
  topbar.appendChild(meter);

  // Right controls
  var right = el('div', { cls: 'topbar-right' });

  var searchBtn = el('button', {
    cls: 'icon-btn',
    id: 'topbar-search-btn',
    attrs: { 'aria-label': 'Search' }
  });
  setStaticHtml(searchBtn, ICONS.search);
  searchBtn.addEventListener('click', openSearch);
  right.appendChild(searchBtn);

  var theme = getTheme();
  var themeBtn = el('button', {
    cls: 'icon-btn theme-toggle-btn',
    attrs: { 'aria-label': theme === 'dark' ? 'Switch to light mode' : 'Switch to dark mode' }
  });
  var themeIcons = buildThemeIcons(theme);
  themeBtn.appendChild(themeIcons[0]);
  themeBtn.appendChild(themeIcons[1]);
  themeBtn.addEventListener('click', toggleTheme);
  right.appendChild(themeBtn);

  topbar.appendChild(right);
}

/* ============================================================
   TOC RENDERER - uses DOM methods; heading text set via textContent
   ============================================================ */
function slugify(text) {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .trim();
}

function buildToc() {
  var main = document.querySelector('main');
  var toc  = document.getElementById('toc');
  if (!main || !toc) return;

  var headings = main.querySelectorAll('h2, h3');
  if (headings.length < 2) {
    toc.style.display = 'none';
    return;
  }

  // Assign IDs to headings that lack them
  var used = {};
  headings.forEach(function(h) {
    if (!h.id) {
      var base = slugify(h.textContent);
      var id = base || 'section';
      var n = 1;
      while (used[id]) { id = base + '-' + (++n); }
      h.id = id;
      used[id] = true;
    } else {
      used[h.id] = true;
    }
  });

  // Build TOC with DOM methods - no innerHTML for heading text
  toc.textContent = '';

  var label = el('p', { cls: 'toc-label', text: 'On this page' });
  toc.appendChild(label);

  var list = el('ul', { cls: 'toc-list' });

  headings.forEach(function(h) {
    var isH3 = h.tagName === 'H3';
    var li = el('li', {
      cls: 'toc-item' + (isH3 ? ' toc-h3' : ''),
      attrs: { 'data-target': h.id }
    });
    var a = el('a', {
      text: h.textContent,          // textContent: safe, no XSS
      attrs: { href: '#' + h.id }  // h.id comes from slugify (alphanumeric + hyphen only)
    });
    a.addEventListener('click', function(e) {
      e.preventDefault();
      var target = document.getElementById(h.id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    });
    li.appendChild(a);
    list.appendChild(li);
  });

  toc.appendChild(list);
  setupScrollspy(headings, toc);
}

function setupScrollspy(headings, toc) {
  var scroll = document.querySelector('.scroll');
  if (!scroll) return;

  function onScroll() {
    var scrollTop = scroll.scrollTop;
    var active = null;
    headings.forEach(function(h) {
      if (h.offsetTop - 80 <= scrollTop) active = h.id;
    });
    toc.querySelectorAll('.toc-item').forEach(function(li) {
      li.classList.toggle('active', li.dataset.target === active);
    });
  }

  scroll.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
}

/* ============================================================
   PREV/NEXT PAGER - uses DOM methods for all data strings
   ============================================================ */
function renderPager(currentPage) {
  var pager = document.getElementById('pager');
  if (!pager) return;

  pager.textContent = '';

  var idx  = PAGES.findIndex(function(p) { return p.page === currentPage; });
  var prev = idx > 0 ? PAGES[idx - 1] : null;
  var next = idx < PAGES.length - 1 ? PAGES[idx + 1] : null;

  function buildPagerLink(p, direction) {
    if (!p) {
      return el('div', { cls: direction === 'prev' ? 'pager-prev' : 'pager-next' });
    }
    var isPrev = direction === 'prev';
    var a = el('a', {
      cls: isPrev ? 'pager-prev' : 'pager-next',
      attrs: { href: p.file }
    });

    var dirSpan = el('span', { cls: 'pager-dir' });
    if (isPrev) {
      setStaticHtml(dirSpan, ICONS.arrowLeft); // static SVG
      dirSpan.appendChild(document.createTextNode(' Previous'));
    } else {
      dirSpan.appendChild(document.createTextNode('Next '));
      var iconSpan = el('span');
      setStaticHtml(iconSpan, ICONS.arrowRight); // static SVG
      dirSpan.appendChild(iconSpan);
    }

    var titleSpan = el('span', { cls: 'pager-title', text: p.title });
    var levelSpan = el('span', {
      cls: 'pager-level',
      text: 'Level ' + p.level + ' - ' + p.group
    });

    append(a, dirSpan, titleSpan, levelSpan);
    return a;
  }

  pager.appendChild(buildPagerLink(prev, 'prev'));
  pager.appendChild(buildPagerLink(next, 'next'));
}

/* ============================================================
   SEARCH - overlay skeleton is static HTML; results use DOM methods
   ============================================================ */
var searchOverlay = null;
var searchInput   = null;

function buildSearchOverlay() {
  var existing = document.getElementById('search-overlay');
  if (existing) { searchOverlay = existing; return; }

  // The overlay skeleton is fully static authored markup - no data interpolated.
  var overlayEl = el('div', {
    id: 'search-overlay',
    cls: 'search-overlay',
    attrs: { role: 'dialog', 'aria-label': 'Search documentation', 'aria-modal': 'true' }
  });

  // Static skeleton: search box + input row
  setStaticHtml(overlayEl, [
    '<div class="search-box" role="search">',
    '  <div class="search-input-row">',
    '    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    '    <input type="search" id="search-q" placeholder="Search the docs..." autocomplete="off" aria-label="Search query">',
    '    <button class="search-close" id="search-close-btn" aria-label="Close search">ESC</button>',
    '  </div>',
    '  <div class="search-results" id="search-results" aria-live="polite"></div>',
    '</div>'
  ].join(''));

  document.body.appendChild(overlayEl);
  searchOverlay = overlayEl;
  searchInput   = overlayEl.querySelector('#search-q');

  overlayEl.querySelector('#search-close-btn').addEventListener('click', closeSearch);
  overlayEl.addEventListener('click', function(e) {
    if (e.target === overlayEl) closeSearch();
  });
  searchInput.addEventListener('input', runSearch);
}

function openSearch() {
  buildSearchOverlay();
  searchOverlay.classList.add('open');
  if (searchInput) {
    searchInput.value = '';
    searchInput.focus();
    runSearch();
  }
}

function closeSearch() {
  if (searchOverlay) searchOverlay.classList.remove('open');
}

/**
 * runSearch - all user-supplied and index-derived strings go through
 * textContent / setAttribute, never innerHTML concatenation.
 */
function runSearch() {
  var q       = searchInput ? searchInput.value.trim().toLowerCase() : '';
  var results = document.getElementById('search-results');
  if (!results) return;

  var index = (typeof window !== 'undefined' && window.SEARCH_INDEX) ? window.SEARCH_INDEX : [];

  results.textContent = ''; // safe clear

  if (!q) return;

  if (index.length === 0) {
    var msg = el('div', {
      cls: 'search-empty',
      text: 'Search index not loaded. Open the site via a local server or add search-index.js.'
    });
    results.appendChild(msg);
    return;
  }

  var hits = index.filter(function(item) {
    return (
      (item.title && item.title.toLowerCase().indexOf(q) !== -1) ||
      (item.text  && item.text.toLowerCase().indexOf(q)  !== -1) ||
      (item.page  && item.page.toLowerCase().indexOf(q)  !== -1)
    );
  }).slice(0, 20);

  if (hits.length === 0) {
    var noRes = el('div', { cls: 'search-empty' });
    noRes.textContent = 'No results for "' + q + '".'; // q is not HTML, textContent is safe
    results.appendChild(noRes);
    return;
  }

  hits.forEach(function(item) {
    // Build the result link entirely with DOM methods
    var href = item.file || '#';
    if (item.anchor) href += '#' + item.anchor;

    var a = el('a', {
      cls: 'search-result-item',
      attrs: { href: href }
    });

    var pageDiv = el('div', { cls: 'search-result-page', text: item.page || '' });
    var titleDiv = el('div', { cls: 'search-result-title', text: item.title || '' });
    a.appendChild(pageDiv);
    a.appendChild(titleDiv);

    // Excerpt: extract a plain-text slice and set via textContent
    if (item.text) {
      var lc = item.text.toLowerCase();
      var idx2 = lc.indexOf(q);
      if (idx2 !== -1) {
        var start = Math.max(0, idx2 - 40);
        var slice = (start > 0 ? '...' : '') + item.text.slice(start, idx2 + q.length + 60) + '...';
        var excerptDiv = el('div', { cls: 'search-result-excerpt', text: slice });
        a.appendChild(excerptDiv);
      }
    }

    results.appendChild(a);
  });
}

/* ============================================================
   CODE BLOCK: copy-to-clipboard
   ============================================================ */
function initCodeCopy() {
  document.querySelectorAll('.code-copy').forEach(function(btn) {
    btn.addEventListener('click', function() {
      var block = btn.closest('.code-block');
      if (!block) return;
      var pre = block.querySelector('pre');
      if (!pre) return;
      var text = pre.textContent;

      function markCopied() {
        btn.textContent = 'Copied!';
        btn.classList.add('copied');
        setTimeout(function() {
          btn.textContent = 'Copy';
          btn.classList.remove('copied');
        }, 2000);
      }

      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(markCopied).catch(function() {
          fallbackCopy(text);
          markCopied();
        });
      } else {
        fallbackCopy(text);
        markCopied();
      }
    });
  });
}

function fallbackCopy(text) {
  var ta = document.createElement('textarea');
  ta.value = text;
  ta.style.position = 'fixed';
  ta.style.opacity = '0';
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand('copy'); } catch (e) { /* silent */ }
  document.body.removeChild(ta);
}

/* ============================================================
   SMOOTH SCROLL for in-page anchor links
   ============================================================ */
function initSmoothScroll() {
  document.addEventListener('click', function(e) {
    var a = e.target.closest('a[href^="#"]');
    if (!a) return;
    var id = a.getAttribute('href').slice(1);
    if (!id) return;
    var target = document.getElementById(id);
    if (!target) return;
    e.preventDefault();
    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    history.pushState(null, '', '#' + id);
  });
}

/* ============================================================
   KEYBOARD
   ============================================================ */
function isInputFocused() {
  var active = document.activeElement;
  if (!active) return false;
  var tag = active.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || active.isContentEditable;
}

function initKeyboard() {
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') {
      closeSearch();
      var rail = document.getElementById('rail');
      if (rail) rail.classList.remove('open');
    }
    if ((e.key === '/' || (e.key === 'k' && (e.metaKey || e.ctrlKey))) && !isInputFocused()) {
      e.preventDefault();
      openSearch();
    }
  });
}

/* ============================================================
   INIT
   ============================================================ */
document.addEventListener('DOMContentLoaded', function() {
  var currentPage = document.body.dataset.page || 'welcome';

  // Apply theme (fallback if the flash-guard did not run)
  document.body.dataset.theme = getTheme();

  renderRail(currentPage);
  renderTopbar(currentPage);
  buildToc();
  renderPager(currentPage);
  initCodeCopy();
  initSmoothScroll();
  initKeyboard();

  // Close mobile rail on outside click
  document.addEventListener('click', function(e) {
    var rail = document.getElementById('rail');
    if (!rail || !rail.classList.contains('open')) return;
    var menuBtn = document.getElementById('menu-toggle');
    if (!rail.contains(e.target) && (!menuBtn || !menuBtn.contains(e.target))) {
      rail.classList.remove('open');
    }
  });
});
