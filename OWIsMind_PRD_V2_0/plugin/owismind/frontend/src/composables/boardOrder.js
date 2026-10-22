// Dashboard arrangement (V2 Studio) - the user's own order of the widgets of ONE answer
// and which widgets are expanded to the full row. Pure functions (no Vue import:
// node:test testable) + a tiny best-effort browser persistence.
//
// The workspace contract carries NO order/layout field (widgets are appended in their
// arrival order by both reducers), so the arrangement is a client-side preference:
//   - `order`: widget ids in the user's order. It may be empty (never arranged) or
//     stale (ids of a previous document): it is ALWAYS merged with the current widget
//     ids on read (unknown ids dropped, new widgets appended at the end in arrival
//     order), so a live run keeps adding widgets after the user's arrangement.
//   - `expanded`: { widgetId: true | false }, the user's width OVERRIDE per widget
//     (absent = the automatic width, see layoutBoard).
//
// Layout: ONE grid of `tracks` columns (4 on a wide board, 2 on a medium one, 1 on a
// narrow one, see boardTracks), filled in the user's order, so the board reads like
// the answer, top to bottom; layoutBoard packs it into rows with no hole.
//
// Persistence: one localStorage key holding every board, keyed by exchange id inside a
// namespace (the DSS backend of the webapp: two projects on the same DSS host never
// share boards), capped at MAX_BOARDS (least recently saved evicted). Every storage
// access is wrapped: a private window or a full quota simply means "not remembered".

export const BOARD_STORAGE_KEY = 'owismind.boards.v1'
export const MAX_BOARDS = 60
// Bounds applied to anything read back from storage (never trusted blindly).
const MAX_IDS = 200
const MAX_ID_LEN = 64

// Board widths (px of the board container) where the grid changes its track count.
// BoardGrid's container queries use the SAME values.
export const BOARD_WIDE_MIN = 900
export const BOARD_MEDIUM_MIN = 480

/** Track count of the board grid for a container width. */
export function boardTracks(width) {
  if (!(width >= BOARD_MEDIUM_MIN)) return 1
  return width >= BOARD_WIDE_MIN ? 4 : 2
}

// --- automatic layout (row packing) ----------------------------------------------------
//
// layoutBoard turns the ordered board widgets into one grid span per widget, for the
// ACTIVE column count, so the board reads as full rows:
//   - a section text immediately followed by a chart / table forms a PAIR on one row
//     (the explanation beside its figure): text 2 + data 2 on a 4-column board. The
//     order decides which side the text is on: a data widget followed by a section text
//     pairs too (the user swapped them), unless that text already leads a pair of its own.
//   - HERO: when the data widget of a pair is wide by default (agent hint or heuristic),
//     the text takes a full row ABOVE (or below, when swapped) and the figure the next
//     full row. Only a data widget the USER widened keeps the text beside it (1 + 3).
//     On 2 columns a normal pair is 1 + 1 and a wide one stacks; on 1 column all stack.
//   - a KPI takes 1 column (2 widened) and NEVER stretches to fill a row. When a row
//     holds only KPIs and the next item does not fit, the next item is pulled into the
//     row at a tighter width (a pair as text 1 + data 2, a text or a figure on what is
//     left); if nothing fits, the KPIs share the row (2 + 2, 1 + 1 + 2), capped at 2
//     columns each, and the next widget fills what is still empty. A final row of KPIs
//     only may keep a void (nothing follows to fill it).
//   - a standalone section text takes the full row (half when the user shrinks it).
//   - a standalone chart / table takes half the board, the full row when wide.
//   - otherwise packing is sequential, in the user's order: when the next item does not
//     fit the space left in its row, the LAST text / chart / table of that row is
//     extended to fill it. A pair never splits across rows (only the KPI fill above may
//     take its first member).
// "Wide" for a data widget = the user's override, else the agent's `size` hint, else
// the heuristic (a table with >= WIDE_TABLE_MIN_COLUMNS columns, a line / area chart
// with more than WIDE_SERIES_MAX_POINTS points). The user's Expand / Shrink override
// (board.expanded) always wins: expand = the full row (for a text: it leaves its pair;
// for the figure of a pair: 1 + 3), shrink = the smallest sensible span of its kind.

export const WIDE_TABLE_MIN_COLUMNS = 5
export const WIDE_SERIES_MAX_POINTS = 12

const PAIR_DATA_KINDS = new Set(['chart', 'table'])

/** True for the analysis-scope text widget (shown in the Studio header, not on the board). */
export function isScopeWidget(w) {
  return !!w && w.kind === 'text' && w.role === 'scope'
}

/** The analysis scope of a workspace: the LATEST scope text widget (null when none). */
export function scopeWidget(widgets) {
  const list = widgets || []
  for (let i = list.length - 1; i >= 0; i--) if (isScopeWidget(list[i])) return list[i]
  return null
}

/** The widgets placed on the board (every widget but the scope ones). */
export function boardWidgets(widgets) {
  return (widgets || []).filter((w) => w && !isScopeWidget(w))
}

/**
 * Default width of a data widget before any user choice: the agent's `size` hint when
 * present, else the heuristic on its data shape ({ columns, points }, unknown while
 * the rows are on their way: compact until then).
 */
export function autoWide(widget, shape) {
  if (!widget || !PAIR_DATA_KINDS.has(widget.kind)) return false
  if (widget.size === 'wide') return true
  if (widget.size === 'normal') return false
  const s = shape || {}
  if (widget.kind === 'table') return typeof s.columns === 'number' && s.columns >= WIDE_TABLE_MIN_COLUMNS
  const c = widget.chart || {}
  const series = c.type === 'line' || c.style === 'area'
  return series && typeof s.points === 'number' && s.points > WIDE_SERIES_MAX_POINTS
}

/**
 * Grid span of every board widget, in order: [{ id, span, wide, paired, hero }].
 * `wide` is the widget's effective width state (what the Expand / Shrink toggle shows
 * and flips), `paired` marks the two members of a text + data pair, `hero` the members
 * of a pair stacked as two full rows. Scope widgets are left out. `opts`: columns
 * (active column count), overrides ({ id: boolean }, the user's width choices) and
 * shapeOf(widget) -> { columns, points } (data shape, for the heuristic).
 */
export function layoutBoard(widgets, opts) {
  const o = opts || {}
  const n = Math.max(1, Math.floor(Number(o.columns)) || 1)
  const overrides = o.overrides && typeof o.overrides === 'object' ? o.overrides : {}
  const shapeOf = typeof o.shapeOf === 'function' ? o.shapeOf : () => null
  const list = boardWidgets(widgets)
  const half = Math.max(1, Math.floor(n / 2))
  const kpiMax = Math.min(2, n)

  const override = (w) => (typeof overrides[w.id] === 'boolean' ? overrides[w.id] : null)
  const isData = (w) => !!w && PAIR_DATA_KINDS.has(w.kind)
  // A text the user widened stays alone on its row: it never pairs.
  const pairText = (w) => !!w && w.kind === 'text' && override(w) !== true
  const dataWide = (w) => {
    const ov = override(w)
    return ov !== null ? ov : autoWide(w, shapeOf(w))
  }

  // 1. Units, in order: a pair [text, data] (either side first) or one widget.
  const units = []
  for (let i = 0; i < list.length; i++) {
    const w = list[i]
    const next = list[i + 1]
    if (pairText(w) && isData(next)) {
      units.push({ text: w, data: next, textFirst: true })
      i++
    } else if (isData(w) && pairText(next) && !isData(list[i + 2])) {
      units.push({ text: next, data: w, textFirst: false })
      i++
    } else {
      units.push({ one: w })
    }
  }

  // 2. Pieces: { items, kpi, fit(room) -> spans | null }. `items` carry their natural
  // spans; fit gives the tighter spans filling exactly `room` columns (null = too
  // narrow), used only to complete a row of KPIs. A KPI piece never adapts.
  const pieces = []
  const single = (w, extra) => {
    const ov = override(w)
    if (w.kind === 'kpi') {
      const wide = ov === true
      return { items: [{ id: w.id, span: wide ? kpiMax : 1, wide, paired: false, hero: false }], kpi: true, fit: () => null }
    }
    const isText = w.kind === 'text'
    const wide = isText ? ov !== false : dataWide(w)
    const min = isText ? 1 : half
    return {
      items: [{ id: w.id, span: wide ? n : half, wide, paired: false, hero: false, ...extra }],
      kpi: false,
      fit: (room) => (room >= min ? [room] : null),
    }
  }
  for (const u of units) {
    if (u.one) {
      pieces.push(single(u.one))
      continue
    }
    const wide = dataWide(u.data)
    const byUser = override(u.data) === true
    if ((n >= 4 && (!wide || byUser)) || (n >= 2 && n < 4 && !wide)) {
      // Side by side: 2 + 2 (1 + 3 when the user widened the figure; 1 + 1 on 2 columns).
      const textSpan = n >= 4 && wide ? Math.max(1, Math.round(n / 4)) : half
      const t = { id: u.text.id, span: textSpan, wide: false, paired: true, hero: false }
      const d = { id: u.data.id, span: n - textSpan, wide, paired: true, hero: false }
      const dataNatural = d.span
      pieces.push({
        items: u.textFirst ? [t, d] : [d, t],
        kpi: false,
        fit: (room) => {
          const ds = Math.min(dataNatural, room - 1)
          if (ds < half) return null
          return u.textFirst ? [room - ds, ds] : [ds, room - ds]
        },
      })
    } else {
      // Hero (a wide figure, 4 columns) or no room beside it: two full rows, in order.
      const hero = n >= 4
      const t = single(u.text, { paired: true, hero })
      t.items[0].span = n
      t.items[0].wide = false
      const d = single(u.data, { paired: true, hero })
      d.items[0].span = n
      pieces.push(...(u.textFirst ? [t, d] : [d, t]))
    }
  }

  // 3. Row packing, in order.
  const kpiIds = new Set(pieces.filter((p) => p.kpi).map((p) => p.items[0].id))
  const out = []
  let row = []
  let used = 0
  const startRow = () => {
    row = []
    used = 0
  }
  const place = (it, span) => {
    const placed = { ...it, span }
    out.push(placed)
    row.push(placed)
    used += span
    if (used >= n) startRow()
  }
  // KPIs only: they share the row round-robin from the last one, 2 columns at most
  // each. Returns the columns still empty.
  const shareKpis = () => {
    let gap = n - used
    let grew = true
    while (gap > 0 && grew) {
      grew = false
      for (let i = row.length - 1; i >= 0 && gap > 0; i--) {
        if (row[i].span < kpiMax) {
          row[i].span++
          used++
          gap--
          grew = true
        }
      }
    }
    return gap
  }
  const stretchOf = () => {
    for (let i = row.length - 1; i >= 0; i--) if (!kpiIds.has(row[i].id)) return row[i]
    return null
  }
  // Close the current row: its last text / chart / table absorbs the space left, else
  // its KPIs share it. Returns the columns still empty (KPIs only).
  const closeRow = () => {
    let gap = used > 0 ? n - used : 0
    if (gap > 0) {
      const s = stretchOf()
      if (s) {
        s.span += gap
        gap = 0
      } else {
        gap = shareKpis()
      }
    }
    if (gap === 0) startRow()
    return gap
  }
  for (const p of pieces) {
    const total = p.items.reduce((sum, it) => sum + it.span, 0)
    if (p.kpi) {
      if (used + total > n && closeRow() > 0) startRow()
      place(p.items[0], total)
      continue
    }
    if (used + total <= n) {
      p.items.forEach((it) => place(it, it.span))
      continue
    }
    if (used > 0 && !stretchOf()) {
      // A row of KPIs only: pull this piece in at a tighter width when it fits.
      const tight = p.fit(n - used)
      if (tight) {
        p.items.forEach((it, i) => place(it, tight[i]))
        continue
      }
      const gap = closeRow()
      if (gap > 0) {
        // Still a void beside the KPIs: the next widget fills it, the rest follows.
        place(p.items[0], gap)
        p.items.slice(1).forEach((it) => {
          const w = list.find((x) => x.id === it.id)
          const own = single(w).items[0]
          if (used + own.span > n) closeRow()
          place({ ...it, wide: own.wide }, own.span)
        })
        continue
      }
    } else if (used > 0) {
      closeRow()
    }
    p.items.forEach((it) => place(it, it.span))
  }
  // The final row: a text / chart / table fills it; KPIs alone may leave a void.
  if (used > 0) closeRow()
  return out
}

function validId(id) {
  return typeof id === 'string' && id.length > 0 && id.length <= MAX_ID_LEN
}

/** An empty arrangement. */
export function emptyBoard() {
  return { order: [], expanded: {} }
}

/** A clean arrangement from any value (storage, caller): bounded ids, no duplicates. */
export function sanitizeBoard(raw) {
  const out = emptyBoard()
  if (!raw || typeof raw !== 'object') return out
  if (Array.isArray(raw.order)) {
    const seen = new Set()
    for (const id of raw.order) {
      if (out.order.length >= MAX_IDS) break
      if (validId(id) && !seen.has(id)) {
        seen.add(id)
        out.order.push(id)
      }
    }
  }
  if (raw.expanded && typeof raw.expanded === 'object' && !Array.isArray(raw.expanded)) {
    let n = 0
    for (const [id, on] of Object.entries(raw.expanded)) {
      if (n >= MAX_IDS) break
      if (typeof on === 'boolean' && validId(id)) {
        out.expanded[id] = on
        n++
      }
    }
  }
  return out
}

/** True when the arrangement holds nothing worth remembering. */
export function isEmptyBoard(board) {
  return !board || (!board.order.length && !Object.keys(board.expanded).length)
}

/**
 * The effective order: the saved ids still present on the board (in the saved order),
 * then every other current widget in arrival order. Unknown ids are dropped.
 */
export function mergeBoardOrder(saved, currentIds) {
  const current = (currentIds || []).filter(validId)
  const present = new Set(current)
  const seen = new Set()
  const out = []
  for (const id of saved || []) {
    if (present.has(id) && !seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  for (const id of current) {
    if (!seen.has(id)) {
      seen.add(id)
      out.push(id)
    }
  }
  return out
}

/**
 * The arrangement restricted to `ids` (order kept, other ids dropped, width choices of
 * the kept widgets only). A continued Studio starts from its base board this way: the
 * carried widgets keep the place and the width the user gave them.
 */
export function filterBoard(board, ids) {
  const clean = sanitizeBoard(board)
  const keep = new Set((ids || []).filter(validId))
  const out = emptyBoard()
  out.order = clean.order.filter((id) => keep.has(id))
  for (const [id, on] of Object.entries(clean.expanded)) if (keep.has(id)) out.expanded[id] = on
  return out
}

/**
 * `newId` takes the place of `oldId` in the order (a widget that `replaces` another).
 * Unchanged when `oldId` is not in the order; a stale `newId` elsewhere is dropped.
 */
export function replaceInOrder(order, oldId, newId) {
  const list = order || []
  if (!validId(newId) || !list.includes(oldId)) return list.slice()
  return list.filter((id) => id !== newId).map((id) => (id === oldId ? newId : id))
}

/** The arrangement without one widget (a widget.remove): order and width choice. */
export function removeFromBoard(board, id) {
  const clean = sanitizeBoard(board)
  const out = { order: clean.order.filter((x) => x !== id), expanded: { ...clean.expanded } }
  delete out.expanded[id]
  return out
}

/** The widgets sorted by the arrangement (same objects, new array). */
export function orderWidgets(widgets, saved) {
  const list = widgets || []
  const byId = new Map()
  for (const w of list) if (w && validId(w.id) && !byId.has(w.id)) byId.set(w.id, w)
  const ordered = mergeBoardOrder(saved, list.map((w) => w && w.id)).map((id) => byId.get(id))
  // Widgets without a usable id (never produced by the reducer) keep their place at the end.
  for (const w of list) if (!w || !validId(w.id)) ordered.push(w)
  return ordered
}

/** `id` moved to the front of the order (unchanged when unknown). */
export function moveToFront(order, id) {
  if (!order.includes(id)) return order.slice()
  return [id, ...order.filter((x) => x !== id)]
}

/**
 * `id` moved right before (`after` false) or right after (`after` true) `targetId`.
 * Unchanged when either id is unknown or they are the same widget.
 */
export function moveRelative(order, id, targetId, after) {
  if (id === targetId || !order.includes(id) || !order.includes(targetId)) return order.slice()
  const rest = order.filter((x) => x !== id)
  const at = rest.indexOf(targetId) + (after ? 1 : 0)
  rest.splice(at, 0, id)
  return rest
}

/**
 * Keyboard / menu move inside ONE visual group (`peerIds`: the ids shown in the same
 * row or grid, in their current order). `delta` -1 = one place earlier, +1 = one place
 * later, -Infinity / +Infinity = first / last of the group. Returns
 * { order, moved, index, count } where index is the new 0-based place in the group.
 */
export function moveWithinGroup(order, id, peerIds, delta) {
  const peers = (peerIds || []).filter((x) => order.includes(x))
  const from = peers.indexOf(id)
  const count = peers.length
  if (from < 0) return { order: order.slice(), moved: false, index: -1, count }
  let to = delta === -Infinity ? 0 : delta === Infinity ? count - 1 : from + delta
  to = Math.max(0, Math.min(count - 1, to))
  if (to === from) return { order: order.slice(), moved: false, index: from, count }
  const target = peers[to]
  return { order: moveRelative(order, id, target, to > from), moved: true, index: to, count }
}

// --- persistence (best effort) ----------------------------------------------------------

// Every board saved in one storage value: { [namespace + ' ' + exchangeId]: { order, expanded, t } }.
function readAll(storage) {
  try {
    const raw = storage && storage.getItem(BOARD_STORAGE_KEY)
    const all = raw ? JSON.parse(raw) : null
    return all && typeof all === 'object' && !Array.isArray(all) ? all : {}
  } catch (e) {
    return {}
  }
}

function slot(namespace, exchangeId) {
  return String(namespace || 'local') + ' ' + String(exchangeId)
}

/** The saved arrangement of one answer (an empty one when none or unreadable). */
export function loadBoard(storage, namespace, exchangeId) {
  if (!storage || exchangeId == null || exchangeId === '') return emptyBoard()
  return sanitizeBoard(readAll(storage)[slot(namespace, exchangeId)])
}

/**
 * Remember the arrangement of one answer (an empty one is forgotten). The least
 * recently saved boards beyond MAX_BOARDS are evicted. Returns false when the storage
 * refused the write (private mode, quota): the arrangement then only lives in memory.
 */
export function saveBoard(storage, namespace, exchangeId, board, now) {
  if (!storage || exchangeId == null || exchangeId === '') return false
  try {
    const all = readAll(storage)
    const key = slot(namespace, exchangeId)
    const clean = sanitizeBoard(board)
    if (isEmptyBoard(clean)) delete all[key]
    else all[key] = { ...clean, t: typeof now === 'number' ? now : Date.now() }
    const keys = Object.keys(all)
    if (keys.length > MAX_BOARDS) {
      keys
        .sort((a, b) => ((all[a] && all[a].t) || 0) - ((all[b] && all[b].t) || 0))
        .slice(0, keys.length - MAX_BOARDS)
        .forEach((k) => delete all[k])
    }
    storage.setItem(BOARD_STORAGE_KEY, JSON.stringify(all))
    return true
  } catch (e) {
    return false
  }
}
