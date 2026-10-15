// Right-column teaser (V2, design "beacon"): when no right panel is open, the chat
// keeps a SMALL clickable zone on its right that invites the user to open the data /
// the workspace - the panel itself is never imposed on the arrival screen. Pure
// predicates (no Vue), unit-tested with node:test.

// Below this viewport width the beacon column gives way to a floating button (the
// design has no beacon on narrow screens); the same width switches panels to sheets.
export const TEASER_COLUMN_MIN_WIDTH = 900
// Below this viewport width every right panel becomes a bottom sheet (overlay).
export const NARROW_WIDTH = 900

/** True when the viewport is too narrow for a side column (sheet mode). */
export function isNarrow(viewportWidth) {
  return typeof viewportWidth === 'number' && viewportWidth > 0 && viewportWidth < NARROW_WIDTH
}

/**
 * The teaser to show, from the screen state:
 *   routeName        current route name (the teaser lives on the chat only)
 *   rightPanelOpen   a right panel (workspace / evidence / source data) is open
 *   agentHasSources  the selected agent exposes source datasets to explore
 *   workspaceReady   the last answer of the active branch has a workspace
 *   running          that workspace is still being built (live run)
 *   unseen           it was produced while the panel was closed and not opened since
 *   viewportWidth    window.innerWidth
 * Returns { visible, mode: 'workspace' | 'data' | null, signal, running, compact }.
 * `signal` is the rare orange accent: something new waits behind the teaser.
 */
export function teaserState(s) {
  const st = s || {}
  const hidden = { visible: false, mode: null, signal: false, running: false, compact: false }
  if (st.routeName !== 'chat' || st.rightPanelOpen) return hidden
  const mode = st.workspaceReady ? 'workspace' : st.agentHasSources ? 'data' : null
  if (!mode) return hidden
  return {
    visible: true,
    mode,
    signal: mode === 'workspace' && !!(st.unseen || st.running),
    running: mode === 'workspace' && !!st.running,
    compact: !(typeof st.viewportWidth === 'number' && st.viewportWidth >= TEASER_COLUMN_MIN_WIDTH),
  }
}

/**
 * The faded source preview of the beacon: the first `maxCols` columns of the source
 * meta and the first `maxRows` rows (rows as objects keyed by column name, or as
 * positional arrays). Display-only strings; empty when nothing usable.
 */
export function previewTable(meta, rows, maxCols = 3, maxRows = 8) {
  const columns = meta && Array.isArray(meta.columns) ? meta.columns : []
  const names = columns
    .map((c) => (c && typeof c === 'object' ? c.name : c))
    .filter((n) => typeof n === 'string' && n)
    .slice(0, maxCols)
  if (!names.length || !Array.isArray(rows)) return { cols: [], rows: [] }
  const allNames = columns.map((c) => (c && typeof c === 'object' ? c.name : c))
  const cell = (v) => (v == null ? '' : String(v))
  const out = rows.slice(0, maxRows).map((r) =>
    names.map((n) => (Array.isArray(r) ? cell(r[allNames.indexOf(n)]) : r && typeof r === 'object' ? cell(r[n]) : '')),
  )
  return { cols: names, rows: out }
}

// Studio width rule (V2): the Studio takes at most 70% of the width left by the left
// column (rail or expanded sidebar) and the chat ALWAYS keeps at least the other 30%.
// Opening (auto, beacon, "Open the Studio") uses the 70% maximum; the resize handle
// may narrow the Studio, never widen it past 70% (clampStudio, during drags and on
// window resize). Pure, in pixels.
export const STUDIO_SHARE = 0.7
export const STUDIO_MIN_WIDTH = 360

function availableWidth(viewportWidth, leftWidth) {
  const vw = typeof viewportWidth === 'number' && viewportWidth > 0 ? viewportWidth : 1280
  const left = typeof leftWidth === 'number' && leftWidth >= 0 ? leftWidth : 60
  return Math.max(0, vw - left)
}

/** Widest Studio allowed: 70% of the width beside the left column (chat keeps 30%). */
export function studioMaxWidth(viewportWidth, leftWidth) {
  // The epsilon absorbs float noise (1380 * 0.7 = 965.999...).
  return Math.floor(availableWidth(viewportWidth, leftWidth) * STUDIO_SHARE + 1e-6)
}

/** Width the Studio opens at: the 70% maximum. */
export function studioWidth(viewportWidth, leftWidth) {
  return studioMaxWidth(viewportWidth, leftWidth)
}

/**
 * Clamp a requested Studio width (drag, stored value, preset) to
 * [min, 70%]. The 30% chat share wins over the Studio minimum on small widths.
 */
export function clampStudio(px, viewportWidth, leftWidth, minWidth = STUDIO_MIN_WIDTH) {
  const max = studioMaxWidth(viewportWidth, leftWidth)
  const min = Math.min(minWidth, max)
  const want = typeof px === 'number' && Number.isFinite(px) ? Math.round(px) : max
  return Math.min(max, Math.max(min, want))
}

/**
 * The plan card fold state above the prompt. Events: 'run_start' (a run builds a
 * plan: unfold), 'run_end' (collapse), 'toggle' (the user's click), 'restore' (a
 * conversation is (re)opened: collapsed). Pure.
 */
export function nextPlanOpen(prev, event) {
  if (event === 'run_start') return true
  if (event === 'run_end' || event === 'restore') return false
  if (event === 'toggle') return !prev
  return !!prev
}
