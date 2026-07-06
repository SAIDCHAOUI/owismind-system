// Pure Source Data Explorer model helpers (NO Vue import - node:test testable, F11).
//
// User-filter chip shape (the store's working state):
//   { key, column, op, values }
//   - key:    stable v-for key ('u<n>')
//   - op:     '=' (one value) | 'IN' (several) - cosmetic; the backend re-normalizes
//   - values: the selected distinct values
//
// The /source/rows payload carries the agent's logical KEY + the integer source id +
// a plain-text search + structured {column, op, values} filters. It never names a
// table or a connection - the server resolves the source id to a dataset.

// Minimum effective search length: below this the term is dropped (mirrors the
// backend, which ignores a q shorter than 2 chars after trimming).
export const SOURCE_Q_MIN = 2
// Hard cap on the search string (mirrors the backend q length limit).
export const SOURCE_Q_MAX = 200
// Fallback window size when a call omits `limit` (the store always passes an
// explicit 100 / 20; this keeps a pagination-less call safe). Mirrors the
// backend's default limit.
export const SOURCE_DEFAULT_LIMIT = 50

// Lowercase + accent-fold for CLIENT-side matching in the pickers. The map is the
// server's translate() map VERBATIM (evidence/source_search.py _ACCENTS_FROM/_TO):
// both sides must fold identically, otherwise a term matches a value while it is in
// the loaded window but stops matching once the search escalates server-side.
const ACCENTS_FROM = 'àáâãäåçèéêëìíîïñòóôõöùúûüýÿ'
const ACCENTS_TO = 'aaaaaaceeeeiiiinooooouuuuyy'
const ACCENT_MAP = new Map(
  Array.from(ACCENTS_FROM, (ch, i) => [ch, ACCENTS_TO[i]]),
)
export function foldSearchTerm(s) {
  let out = ''
  for (const ch of String(s == null ? '' : s).toLowerCase()) {
    out += ACCENT_MAP.get(ch) || ch
  }
  return out
}

// Cosmetic op for a user filter: one value reads as '=', several as 'IN' (the
// backend treats both identically and re-normalizes). CONTRACT: `values` must be
// non-empty - the store removes a chip instead of letting its last value drop.
export function normalizeSourceOp(values) {
  return values.length > 1 ? 'IN' : '='
}

// The effective op of a chip. A temporal BETWEEN range (exactly 2 boundary values) is
// EXPLICIT and preserved verbatim; anything else is re-derived from the value count so a
// stale '=' on a 2-value chip still travels as 'IN'. Single source of truth for both the
// filter payload and the store's view signature.
export function chipOp(chip) {
  if (chip && chip.op === 'BETWEEN' && Array.isArray(chip.values) && chip.values.length === 2) {
    return 'BETWEEN'
  }
  return normalizeSourceOp(chip && Array.isArray(chip.values) ? chip.values : [])
}

// Build one user-filter chip. `seq` is a monotonically-increasing counter owned by
// the store so every chip keeps a stable, unique v-for key across edits. `op` is
// optional: pass 'BETWEEN' (with exactly 2 values) to build a temporal range chip whose
// op is preserved; otherwise the op is derived from the value count.
export function makeSourceChip(column, values, seq, op) {
  const explicitBetween = op === 'BETWEEN' && values.length === 2
  return {
    key: 'u' + seq,
    column,
    op: explicitBetween ? 'BETWEEN' : normalizeSourceOp(values),
    values: values.slice(),
  }
}

// The effective search term: trimmed, dropped to '' below SOURCE_Q_MIN chars, and
// clamped to SOURCE_Q_MAX (the backend clamps identically). Always a string so the
// payload matches the frozen `q: str` contract.
export function effectiveSourceQuery(q) {
  const trimmed = (q == null ? '' : String(q)).trim()
  if (trimmed.length < SOURCE_Q_MIN) return ''
  return trimmed.slice(0, SOURCE_Q_MAX)
}

// Map the user-filter chips to the frozen {column, op, values} filter list, shared by
// the rows and aggregate payload builders (single source of truth so both requests
// carry the EXACT same predicate). Chips with no column or no values are skipped
// defensively. A BETWEEN chip forwards its op + its 2 boundary values UNTOUCHED (the
// server renders `col BETWEEN v1 AND v2`); any other chip re-derives `=`/`IN` from the
// value count, never a stale chip op.
// Exported so the cascading distinct-value picker (sources store loadDistinct) reuses the
// EXACT same chip -> filter shaping when it sends the OTHER active filters as the picker
// scope (minus the chip being edited, which the store drops before calling this).
export function chipsToFilters(chips) {
  const filters = []
  for (const c of chips || []) {
    if (!c || !c.column || !Array.isArray(c.values) || !c.values.length) continue
    filters.push({
      column: c.column,
      op: chipOp(c),
      values: c.values.slice(),
    })
  }
  return filters
}

// Assemble the /source/rows request body. `sourceId` is the integer id from the
// agent's `sources` list; `chips` are the user filters; `sort` is {column, dir} or
// null. Chips with no column or no values are skipped defensively.
//
// Pagination is limit/offset (v2): `limit` is the window size (fresh load 100,
// subsequent "load more" 20), `offset` the running count of already-loaded rows.
// The server clamps both (1..100 / 0..500); a missing/zero limit falls back to a
// sane default so a call without pagination still returns a first window.
export function buildSourceRowsPayload(agentKey, sourceId, q, chips, limit, offset, sort) {
  return {
    agent: agentKey,
    source: sourceId,
    q: effectiveSourceQuery(q),
    filters: chipsToFilters(chips),
    limit: limit || SOURCE_DEFAULT_LIMIT,
    offset: offset || 0,
    sort: sort || null,
  }
}

// --- Aggregation (DB-computed totals + Analyze mini-pivot) --------------------
//
// Every number the user reads must be computed by the DATABASE over the FULL
// filtered set (the visible table is only a 100..500-row window). /source/aggregate
// carries the SAME agent key + source id + effective q + filters as /source/rows,
// plus an optional group + a list of measures. These helpers stay pure (node-testable)
// and produce UI HINTS only - the server re-validates every column and function.

// The aggregation functions the backend accepts. `count` is the only one that takes
// no column (COUNT(*)); every other function needs a column. `median` is numeric-only
// (the server rejects it on a non-numeric column); the UI only ever offers it for one.
export const AGG_FNS = ['count', 'count_distinct', 'sum', 'avg', 'min', 'max', 'median']
// Temporal bucketing granularities offered for a date/timestamp group column.
export const BUCKETS = ['month', 'quarter', 'year']

// Case-insensitive type classifiers over Dataiku / PostgreSQL type names. These are
// UI hints only; the server is the authority - but BOTH classifiers are kept as
// EXACT MIRRORS of their backend counterparts (storage/sql_config.py), because one
// decides what the UI OFFERS and the other GATES it: substring matching here used to
// offer sum/avg on 'interval'/'geopoint' (contain 'int' -> then 400 server-side) and
// hide the sigma on 'money'/'serial' (backend-numeric, no hint substring).
const NUMERIC_TYPE_NAMES = new Set([
  // Dataiku storage types.
  'tinyint', 'smallint', 'int', 'bigint', 'float', 'double', 'decimal',
  // PostgreSQL native type names + common aliases.
  'integer', 'int2', 'int4', 'int8', 'smallserial', 'serial', 'bigserial',
  'numeric', 'real', 'double precision', 'float4', 'float8', 'money',
])
export function isNumericColType(type) {
  const s = String(type == null ? '' : type).toLowerCase().trim()
  return NUMERIC_TYPE_NAMES.has(s)
}
// EXACT mirror of the backend classifier (storage/sql_config.is_temporal_type): the
// Dataiku "date" storage type, datetime, and every "timestamp..." spelling. Bare
// "time" (time of day) is EXCLUDED on BOTH sides: a calendar month range or a
// DATE_TRUNC bucket is undefined there, and a divergence would let the UI offer a
// range the server then fails on (date literals never cast to a time column).
export function isTemporalColType(type) {
  const s = String(type == null ? '' : type).toLowerCase().trim()
  if (!s) return false
  if (s === 'date' || s === 'datetime' || s === 'timestamptz') return true
  return s.startsWith('timestamp')
}

// The bucket granularities valid for a column type: none unless it is temporal.
export function bucketOptionsFor(columnType) {
  return isTemporalColType(columnType) ? BUCKETS.slice() : []
}

// The ordered key-figure spec for the "Calculate" zone, chosen by column TYPE (never a
// hardcoded column name). Each entry is { fn, labelKey } where `fn` is an aggregation
// function and `labelKey` is its i18n label. The zone fetches ONE /source/aggregate with
// these measures (group null) and maps m0..mN back by position.
//   numeric  -> sum, average, median, min, max
//   temporal -> min, max (the earliest / latest value)
//   anything else (text, boolean, ...) -> distinct count
export function statsSpecFor(columnType) {
  if (isNumericColType(columnType)) {
    return [
      { fn: 'sum', labelKey: 'src.calc.sum' },
      { fn: 'avg', labelKey: 'src.calc.avg' },
      { fn: 'median', labelKey: 'src.calc.median' },
      { fn: 'min', labelKey: 'src.calc.min' },
      { fn: 'max', labelKey: 'src.calc.max' },
    ]
  }
  if (isTemporalColType(columnType)) {
    return [
      { fn: 'min', labelKey: 'src.calc.min' },
      { fn: 'max', labelKey: 'src.calc.max' },
    ]
  }
  return [{ fn: 'count_distinct', labelKey: 'src.calc.distinct' }]
}

// The DEFAULT selected measures for the "Calculate" zone when a NEW column is picked,
// chosen by column TYPE. statsSpecFor lists everything that CAN be selected per type;
// this returns the small, sensible starting subset so the user is not shown all five
// numeric figures at once (the feedback that drove this rework). Every returned fn is
// guaranteed to be one of statsSpecFor(columnType)'s entries.
//   numeric  -> sum (the single most-asked figure)
//   temporal -> min, max (the span)
//   anything else (text, boolean, ...) -> distinct count
export function defaultCalcFnsFor(columnType) {
  if (isNumericColType(columnType)) return ['sum']
  if (isTemporalColType(columnType)) return ['min', 'max']
  return ['count_distinct']
}

// Normalize a group spec to the frozen contract: null (no grouping) or
// { column, bucket } where bucket is one of BUCKETS or null (non-temporal group).
// Exported so the Evidence aggregate payload builder reuses the EXACT same shaping
// (the /evidence/aggregate group contract is identical to /source/aggregate).
export function normalizeGroup(group) {
  if (!group || !group.column) return null
  const bucket = BUCKETS.indexOf(group.bucket) !== -1 ? group.bucket : null
  return { column: group.column, bucket }
}

// Normalize the measures list to the frozen contract: 1..8 of { fn, column } where
// `column` is null ONLY for `count`. Unknown functions are dropped; the list is
// capped at 8. (The server clamps again; this keeps the payload honest.) Exported so
// the Evidence aggregate builder reuses the same shaping (identical measure contract).
export function normalizeMeasures(measures) {
  const out = []
  for (const m of measures || []) {
    if (!m || AGG_FNS.indexOf(m.fn) === -1) continue
    out.push({ fn: m.fn, column: m.fn === 'count' ? null : (m.column || null) })
    if (out.length >= 8) break
  }
  return out
}

// Assemble the /source/aggregate request body. It reuses the EXACT same filter
// mapping + effective query as buildSourceRowsPayload, so a total is computed over
// the identical predicate as the visible rows. `group` is null | { column, bucket };
// `measures` is 1..8 of { fn, column }; `limit` is the group-rows cap (server clamps
// to [1..50]; irrelevant when group is null, which returns a single totals row).
export function buildSourceAggregatePayload(agentKey, sourceId, q, chips, group, measures, limit) {
  return {
    agent: agentKey,
    source: sourceId,
    q: effectiveSourceQuery(q),
    filters: chipsToFilters(chips),
    group: normalizeGroup(group),
    measures: normalizeMeasures(measures),
    limit: limit == null ? null : limit,
  }
}

// Safe percentage of a value against a total: null when the total is 0 / null /
// non-finite, or the value is null / non-finite (never divide-by-zero, NaN% or a
// misleading 0% for an unknown value). A real 0 value yields 0%.
export function shareOfTotal(value, total) {
  if (value == null) return null
  const v = Number(value)
  const tot = Number(total)
  if (!Number.isFinite(v) || !Number.isFinite(tot) || tot === 0) return null
  return (v / tot) * 100
}

// Locale-aware, compact-but-EXACT number for the totals bar / Analyze cells: integers
// are grouped with no decimals, non-integers capped to 2 decimals. A numeric string
// (decimals often arrive as strings from PostgreSQL) is formatted as a number; a
// non-numeric string (a date, text) passes through verbatim. null -> '-'.
export function formatStatNumber(value, locale) {
  if (value == null) return '-'
  let n
  if (typeof value === 'number') {
    if (!Number.isFinite(value)) return String(value)
    n = value
  } else {
    const s = String(value)
    // An integer string wider than Number.MAX_SAFE_INTEGER (16+ digits) would lose its
    // low-order digits through Number(): return the DB-exact string untouched instead
    // of silently showing an altered total (huge monetary/quantity SUMs).
    const digits = s.trim()
    if (/^-?\d{16,}$/.test(digits)) return digits
    const parsed = Number(s)
    if (s.trim() === '' || !Number.isFinite(parsed)) return s
    n = parsed
  }
  // Tiny non-zero magnitudes must never render as "0" (a MIN of 0.0004 read as zero is
  // a wrong number, not a truncation): below 0.01 switch to significant digits.
  if (n !== 0 && Math.abs(n) < 0.01) {
    return new Intl.NumberFormat(locale || 'en', { maximumSignificantDigits: 2 }).format(n)
  }
  return new Intl.NumberFormat(locale || 'en', {
    minimumFractionDigits: 0,
    maximumFractionDigits: Number.isInteger(n) ? 0 : 2,
  }).format(n)
}

// Parse a bucket key (group value produced by a date_trunc) into a Date, dodging
// timezone drift: an ISO date/timestamp is read from its YYYY-MM-DD prefix (UTC), a
// pure-digit string / number is treated as epoch ms. Returns null when unparseable.
function toBucketDate(key) {
  if (key instanceof Date) return isNaN(key.getTime()) ? null : key
  if (typeof key === 'number' && Number.isFinite(key)) {
    const d = new Date(key)
    return isNaN(d.getTime()) ? null : d
  }
  const s = String(key == null ? '' : key).trim()
  if (!s) return null
  const iso = s.match(/^(\d{4})-(\d{2})-(\d{2})/)
  if (iso) return new Date(Date.UTC(Number(iso[1]), Number(iso[2]) - 1, Number(iso[3])))
  if (/^\d+$/.test(s)) {
    const d = new Date(Number(s))
    return isNaN(d.getTime()) ? null : d
  }
  const d = new Date(s)
  return isNaN(d.getTime()) ? null : d
}

// Format a temporal bucket key as YYYY-MM (month), YYYY-Qn (quarter) or YYYY (year).
// null key -> null (the caller renders the "empty group" label). An unparseable key
// falls back to its verbatim string so nothing is ever silently dropped.
// Chronological re-sort of a BUCKETED aggregate result for display. The server
// returns calendar buckets ordered key DESC so its group CAP keeps the MOST RECENT
// periods on a long history; the display still reads oldest-to-newest. Pure copy
// sort on the ISO-ish key (lexicographic == chronological for date_trunc output);
// null keys (rows with no date) go LAST. Non-destructive: returns a new array.
export function sortBucketRowsAsc(rows) {
  return (rows || []).slice().sort((a, b) => {
    const ka = a && a.key != null ? String(a.key) : null
    const kb = b && b.key != null ? String(b.key) : null
    if (ka == null && kb == null) return 0
    if (ka == null) return 1
    if (kb == null) return -1
    return ka < kb ? -1 : ka > kb ? 1 : 0
  })
}

export function formatBucketKey(key, bucket) {
  if (key == null) return null
  const d = toBucketDate(key)
  if (!d) return String(key)
  const y = d.getUTCFullYear()
  if (bucket === 'year') return String(y)
  if (bucket === 'quarter') return y + '-Q' + (Math.floor(d.getUTCMonth() / 3) + 1)
  return y + '-' + String(d.getUTCMonth() + 1).padStart(2, '0')
}

// --- Temporal range filter (date BETWEEN, picked in 1-2 clicks) ----------------
//
// A temporal filter is a month RANGE, not a list of hand-picked months: the popover
// offers two 'YYYY-MM' month fields (From / To) plus a one-click full-year fill. Apply
// builds ONE chip { column, op:'BETWEEN', values:[start, end] } the backend renders as
// `col BETWEEN start AND end` (inclusive on both ends).

// Parse a 'YYYY-MM' month string into { y, m } (m is 1..12), or null when missing /
// malformed. Anything the two native <input type="month"> fields emit is 'YYYY-MM'.
function parseYearMonth(s) {
  const m = String(s == null ? '' : s).trim().match(/^(\d{4})-(\d{2})$/)
  if (!m) return null
  const y = Number(m[1])
  const mo = Number(m[2])
  if (mo < 1 || mo > 12) return null
  return { y, m: mo }
}
// Zero-padded 'YYYY-MM' from a parsed { y, m }.
function fmtYearMonth(y, m) {
  return String(y).padStart(4, '0') + '-' + String(m).padStart(2, '0')
}
// a <= b over { y, m } pairs (calendar order).
function yearMonthLE(a, b) {
  return a.y < b.y || (a.y === b.y && a.m <= b.m)
}

// Build an inclusive BETWEEN range from two 'YYYY-MM' month strings. Returns
// { start, end } or null when either month is missing / malformed (apply stays disabled).
//   start = first instant of the From month -> 'YYYY-MM-01'
//   end   = last instant of the To month    -> 'YYYY-MM-<lastDay>T23:59:59.999'
// The end reaches the last millisecond of the To month so an inclusive BETWEEN covers
// every timestamp inside that month WITHOUT swallowing the first instant of the next
// month. A reversed From > To is swapped (it still reads as the same span).
export function monthRangeToBetween(fromYM, toYM) {
  const a = parseYearMonth(fromYM)
  const b = parseYearMonth(toYM)
  if (!a || !b) return null
  const lo = yearMonthLE(a, b) ? a : b
  const hi = yearMonthLE(a, b) ? b : a
  const start = fmtYearMonth(lo.y, lo.m) + '-01'
  // Day 0 of the NEXT month (hi.m is 1-based, so it is the 0-based index of the month
  // after hi) resolves to the last calendar day of the hi month, leap years included.
  // MICROSECOND end bound: PostgreSQL timestamps store microsecond precision, so an
  // inclusive BETWEEN up to .999999 covers every representable instant of the last day
  // (a .999 bound would drop rows in the final sub-millisecond window) while still
  // never touching the first instant of the next month.
  const lastDay = new Date(Date.UTC(hi.y, hi.m, 0)).getUTCDate()
  const end = fmtYearMonth(hi.y, hi.m) + '-' + String(lastDay).padStart(2, '0') + 'T23:59:59.999999'
  return { start, end }
}

// Build an inclusive BETWEEN range for a TEXT column that stores ISO date strings (a
// live-schema "string" column whose values read as 'YYYY-MM' / 'YYYY-MM-DD...'). The
// backend renders `col BETWEEN start AND end` as quoted literals compared as TEXT, so the
// bounds must sort correctly under BOTH text collation families the DB may use:
//   - byte-wise / "C" collation (compares raw code points), and
//   - punctuation-insensitive collations (ignore '-', compare the digit run '20250399').
// Reuses monthRangeToBetween's parse + reversed-range swap.
//   start = 'YYYY-MM'      (the From month string itself)
//   end   = 'YYYY-MM-99'   (the To month + a '-99' day sentinel)
// Why these bounds hold in both collation families: after the shared 'YYYY-MM' prefix the
// remaining characters are all DIGITS, so the comparison is decided by the digit sequence
// alone (the '-' separators either compare equal byte-wise or are dropped) - identical in
// both families. Lower bound: 'YYYY-MM' is a prefix of every 'YYYY-MM', 'YYYY-MM-DD...'
// value of the From month (and of later months), so all of them sort >= start; earlier
// months sort below it. Upper bound: every real day '01'..'31' (and a bare 'YYYY-MM')
// sorts below the '99' sentinel, while the NEXT month ('YYYY-(MM+1)...') sorts above it,
// so the To month is fully included and the following month is fully excluded.
export function monthRangeToBetweenLexical(fromYM, toYM) {
  const a = parseYearMonth(fromYM)
  const b = parseYearMonth(toYM)
  if (!a || !b) return null
  const lo = yearMonthLE(a, b) ? a : b
  const hi = yearMonthLE(a, b) ? b : a
  const start = fmtYearMonth(lo.y, lo.m)
  const end = fmtYearMonth(hi.y, hi.m) + '-99'
  return { start, end }
}

// True when a distinct-values window looks like ISO date / month strings: the list is
// non-empty and EVERY non-null / non-empty value starts with a 'YYYY-MM' prefix, optionally
// followed by a day/time tail introduced by '-', 'T' or a space ('YYYY-MM', 'YYYY-MM-DD',
// 'YYYY-MM-DDThh:mm:ss', 'YYYY-MM-DD hh:mm'). Null / empty entries are IGNORED; a window of
// ONLY nulls/empties returns false (nothing to sniff on). Drives auto-entering range mode
// over a STRING column that actually stores dates: the live schema types it text, so
// isTemporalColType is false and the user would otherwise tick months one by one.
export function looksLikeIsoDateValues(values) {
  if (!Array.isArray(values) || !values.length) return false
  let seen = 0
  for (const v of values) {
    if (v == null) continue
    const s = String(v).trim()
    if (!s) continue
    seen += 1
    if (!/^\d{4}-\d{2}([-T ].*)?$/.test(s)) return false
  }
  return seen > 0
}

// Inverse of monthRangeToBetween, for pre-filling the range popover when a BETWEEN chip
// is edited: read the 'YYYY-MM' back from the stored [start, end] values (their leading
// YYYY-MM prefix). Works for both bound styles - the calendar-precise
// 'YYYY-MM-01' / 'YYYY-MM-DDT23:59:59.999999' bounds AND the TEXT-safe 'YYYY-MM' /
// 'YYYY-MM-99' bounds - since only the shared leading prefix is read. Returns
// { from, to } or null when the pair is missing / unreadable.
export function betweenValuesToMonthRange(values) {
  if (!Array.isArray(values) || values.length !== 2) return null
  const from = yearMonthPrefix(values[0])
  const to = yearMonthPrefix(values[1])
  if (!from || !to) return null
  return { from, to }
}
// The 'YYYY-MM' prefix of an ISO date / timestamp string, or null.
function yearMonthPrefix(v) {
  const m = String(v == null ? '' : v).match(/^(\d{4})-(\d{2})/)
  return m ? m[1] + '-' + m[2] : null
}

// The 4-digit year of an ISO date / timestamp value (its leading YYYY), or null. Used to
// derive the "Full year" quick-fill options from a temporal column's distinct values.
export function yearOfValue(v) {
  const m = String(v == null ? '' : v).match(/^(\d{4})/)
  return m ? m[1] : null
}
