// Pure helpers behind the agent-result tables (Evidence "result" section + Table tab).
// The agents keep only a short EXCERPT of each SQL result (the captured rows); when that
// excerpt may hide rows, the tables page through the FULL result instead, re-run by the
// backend (/evidence/result-rows). No Vue here: unit-tested with node:test.

// Each agent keeps at most this many result rows (MAX_RESULT_ROWS in the three Code
// Agents). A capture of that size may be cut even when its `truncated` flag is missing
// (the semantic tool can bound its own output), so it is treated as a possible excerpt.
export const CAPTURE_EXCERPT_ROWS = 50
// Same window policy as the Source Data explorer: a first window of 100 rows, then
// small appends on scroll, bounded on the client (100 + 20 x 20 = 500, under the
// backend's offset cap).
export const RESULT_INITIAL_LIMIT = 100
export const RESULT_MORE_LIMIT = 20
export const RESULT_MAX_ROWS = 500

function finiteCount(n) {
  return typeof n === 'number' && Number.isFinite(n) && n >= 0 ? n : null
}

/**
 * True when a captured result may be only part of the answer, i.e. the full result
 * must be fetched before the table can honestly say how many rows there are.
 * @param {object|null} result meta.result shape { captured, rows, row_count, truncated }
 */
export function needsFullResult(result) {
  if (!result || !result.captured || !Array.isArray(result.rows)) return false
  const n = result.rows.length
  if (result.truncated) return true
  if (n >= CAPTURE_EXCERPT_ROWS) return true
  const rc = finiteCount(result.row_count)
  return rc != null && rc > n
}

/**
 * The count line of a result table, as an i18n key + args (the component formats the
 * numbers). Never claims a total it does not know.
 *   full      : the whole result is on screen            -> "N row(s)"
 *   of_total  : a window of a KNOWN total               -> "Showing N of T rows"
 *   more      : a window, total unknown, more remain    -> "N rows loaded, more available"
 *   excerpt   : only the agent's excerpt could be shown -> "First N rows only, ..."
 * @param {{ shown:number, total:number|null, live:boolean, hasMore:boolean, partial:boolean }} s
 */
export function resultCountLabel(s) {
  const shown = s.shown
  const total = finiteCount(s.total)
  if (s.live) {
    if (total != null && total > shown) return { key: 'res.count.of_total', args: [shown, total] }
    if (s.hasMore) return { key: 'res.count.more', args: [shown] }
    return { key: 'res.count.full', args: [total != null ? total : shown] }
  }
  if (s.partial) {
    if (total != null && total > shown) return { key: 'res.count.of_total', args: [shown, total] }
    return { key: 'res.count.excerpt', args: [shown] }
  }
  return { key: 'res.count.full', args: [total != null ? total : shown] }
}

/** Next window to request, or null when nothing more may be loaded. */
export function nextResultWindow(loaded, hasMore) {
  if (!hasMore || loaded >= RESULT_MAX_ROWS) return null
  return { offset: loaded, limit: Math.min(RESULT_MORE_LIMIT, RESULT_MAX_ROWS - loaded) }
}
