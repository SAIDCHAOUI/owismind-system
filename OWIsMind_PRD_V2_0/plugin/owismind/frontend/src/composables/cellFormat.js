// Pure display formatting for SQL result table cells (NO Vue import - node:test
// testable, F11). Raw SQL results arrive as JS numbers or plain decimal strings
// ('12345678.901235') and were previously rendered verbatim - unreadable for a
// human. This module makes every numeric cell human-readable (locale grouping,
// bounded decimals via the shared formatStatNumber) while NEVER altering
// identifier-like values (ids, codes, years, phone numbers) or non-numeric text.
//
// Two consumption paths, one formatting truth:
//  - Captured results (ArtifactTable / EvidenceResult): rows are ARRAYS with no
//    type metadata -> per-column numeric-ness is INFERRED from the values.
//  - Live source tables (EvidenceTable / SourceTable): columns carry the DSS
//    storage type -> `isNumericColType` decides, this module only formats.
import { formatStatNumber } from './sourceModel.js'

// Strict numeric-string shape: plain decimals with optional exponent. Dates
// ('2025-01-01'), month keys ('2025-01'), mixed text and pre-formatted numbers
// ('1,234.5') are all rejected - they pass through verbatim.
const NUM_RE = /^[+-]?(\d+(\.\d+)?|\.\d+)([eE][+-]?\d+)?$/

// Column names whose numeric content is an IDENTIFIER, not a quantity: grouping
// separators would corrupt reading ('12,345,678' for an account id; '2,026' for a
// year). Word-boundary match (start/end or any non-alphanumeric separator) on the
// usual identifier vocabulary, both English and this project's French columns.
// Deliberately NOT in the list: num / number / no, which name COUNTS at least as
// often as identifiers (num_tickets, number_of_incidents); id-shaped values they
// may hold are still caught by the value-shape guard in inferNumericColumns.
const ID_NAME_RE = new RegExp(
  '(?:^|[^a-z0-9])(id|ids|code|codes|key|keys|year|yr|annee|siren|siret'
  + '|iban|phone|tel|zip|postal|postcode|month|week|day)(?:[^a-z0-9]|$)',
  'i',
)

// How many rows the array-path inference scans per column. Enough to be reliable,
// bounded so a huge captured result costs nothing to classify.
const INFER_SCAN_ROWS = 50

// Value-shape identifier guard (array path): >= this many scanned values, ALL
// plain integers of the SAME digit width >= ID_SHAPE_MIN_WIDTH, reads as an
// identifier/period series ('202501', phone numbers, serials) - a real quantity
// column varies in magnitude or carries decimals. Small samples (single totals)
// are exempt: a lone SUM must stay formatted.
const ID_SHAPE_MIN_VALUES = 3
const ID_SHAPE_MIN_WIDTH = 6
const INT_RE = /^[+-]?\d+$/

/** True when `value` is a finite number or a plain numeric string. */
export function isNumericValue(value) {
  if (typeof value === 'number') return Number.isFinite(value)
  if (typeof value !== 'string') return false
  const s = value.trim()
  return s !== '' && NUM_RE.test(s)
}

/** True when the column NAME says its values are identifiers (never grouped). */
export function isIdentifierColumn(name) {
  return ID_NAME_RE.test(String(name == null ? '' : name))
}

/**
 * Infer which columns of a captured (array-rows) result are numeric quantities.
 * A column qualifies when at least one scanned value is numeric and NO scanned
 * non-empty value is non-numeric (mixed columns stay text), and its name does
 * not mark it as an identifier. Returns an array of booleans aligned on
 * `columns`; never throws on malformed rows.
 */
export function inferNumericColumns(columns, rows) {
  const cols = Array.isArray(columns) ? columns : []
  const list = Array.isArray(rows) ? rows : []
  const scan = list.slice(0, INFER_SCAN_ROWS)
  return cols.map((name, j) => {
    if (isIdentifierColumn(name)) return false
    let count = 0
    let allInts = true
    let width = -1
    let constantWidth = true
    for (const row of scan) {
      if (!Array.isArray(row)) continue
      const v = row[j]
      if (v == null || (typeof v === 'string' && v.trim() === '')) continue
      if (!isNumericValue(v)) return false
      count += 1
      const s = String(v).trim().replace(/^[+-]/, '')
      if (!INT_RE.test(s)) allInts = false
      if (width === -1) width = s.length
      else if (s.length !== width) constantWidth = false
    }
    if (count === 0) return false
    // Value-shape guard: a series of same-width plain integers ('202501',
    // '8001234567') is an identifier/period, not a quantity - leave it verbatim.
    if (count >= ID_SHAPE_MIN_VALUES && allInts && constantWidth
        && width >= ID_SHAPE_MIN_WIDTH) {
      return false
    }
    return true
  })
}

/**
 * Display string for one table cell. Numeric quantities go through the shared
 * locale-aware formatter (grouping, <= 2 decimals, tiny-value protection, big
 * integer-string passthrough); everything else renders verbatim; null -> '-'.
 */
export function formatCell(value, numeric, locale) {
  if (value == null) return '-'
  if (!numeric || !isNumericValue(value)) return String(value)
  return formatStatNumber(value, locale)
}
