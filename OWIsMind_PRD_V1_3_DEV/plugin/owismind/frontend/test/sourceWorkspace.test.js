// Pure rules behind the unified Analyze workspace (composables/sourceModel.js): measure
// identity + labels, the add/remove guards, the preview column order and the
// magnitude-bar geometry. No Vue, no DOM (F11).
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_WORKSPACE_MEASURES,
  measureKey,
  measureLabelKey,
  addMeasure,
  removeMeasureAt,
  replaceMeasureAt,
  orderPreviewColumns,
  barGeometry,
  measureSpecForColumn,
  defaultWorkspaceMeasures,
  pickCellFilterChip,
} from '../src/composables/sourceModel.js'
import { isIdentifierColumn } from '../src/composables/cellFormat.js'

// ------------------------------------------------------------------ identity + labels
test('measureKey identifies a measure by its function AND its column', () => {
  assert.equal(measureKey({ fn: 'count', column: null }), 'count')
  // The row count never carries a column, whatever a caller passes.
  assert.equal(measureKey({ fn: 'count', column: 'Revenues' }), 'count')
  assert.equal(measureKey({ fn: 'sum', column: 'Revenues' }), 'sum:Revenues')
  assert.notEqual(measureKey({ fn: 'sum', column: 'Revenues' }), measureKey({ fn: 'avg', column: 'Revenues' }))
  assert.notEqual(measureKey({ fn: 'sum', column: 'Revenues' }), measureKey({ fn: 'sum', column: 'Budget' }))
  assert.equal(measureKey(null), '')
})

test('measureLabelKey maps every offered function to a label key', () => {
  assert.equal(measureLabelKey({ fn: 'count' }), 'src.an.fn.count')
  assert.equal(measureLabelKey({ fn: 'sum', column: 'x' }), 'src.an.fn.sum')
  assert.equal(measureLabelKey({ fn: 'avg', column: 'x' }), 'src.an.fn.avg')
  assert.equal(measureLabelKey({ fn: 'median', column: 'x' }), 'src.an.fn.median')
  assert.equal(measureLabelKey({ fn: 'min', column: 'x' }), 'src.ws.fn.min')
  assert.equal(measureLabelKey({ fn: 'max', column: 'x' }), 'src.ws.fn.max')
  assert.equal(measureLabelKey({ fn: 'count_distinct', column: 'x' }), 'src.ws.fn.distinct')
  assert.equal(measureLabelKey({ fn: 'nope', column: 'x' }), '')
})

// ------------------------------------------------------------------------ add / remove
test('addMeasure appends a new measure and returns a NEW list', () => {
  const base = [{ fn: 'count', column: null }]
  const next = addMeasure(base, { fn: 'sum', column: 'Revenues' })
  assert.notEqual(next, base)
  assert.deepEqual(next, [{ fn: 'count', column: null }, { fn: 'sum', column: 'Revenues' }])
  assert.deepEqual(base, [{ fn: 'count', column: null }], 'the input list is never mutated')
})

test('addMeasure refuses an exact duplicate (same fn AND column)', () => {
  const base = [{ fn: 'sum', column: 'Revenues' }]
  assert.equal(addMeasure(base, { fn: 'sum', column: 'Revenues' }), base)
  // Same column, different function: that is a different measure.
  assert.equal(addMeasure(base, { fn: 'avg', column: 'Revenues' }).length, 2)
  // Same function, different column: also a different measure.
  assert.equal(addMeasure(base, { fn: 'sum', column: 'Budget' }).length, 2)
})

test('addMeasure refuses the ceiling, an unknown function and a column-less aggregate', () => {
  const full = []
  for (let i = 0; i < MAX_WORKSPACE_MEASURES; i += 1) full.push({ fn: 'sum', column: 'c' + i })
  assert.equal(full.length, 8)
  assert.equal(addMeasure(full, { fn: 'sum', column: 'other' }), full)
  const base = [{ fn: 'count', column: null }]
  assert.equal(addMeasure(base, { fn: 'nope', column: 'x' }), base)
  assert.equal(addMeasure(base, { fn: 'sum', column: null }), base, 'sum needs a column')
  assert.equal(addMeasure(base, null), base)
})

test('addMeasure drops the column of a row count (the backend rejects one)', () => {
  const next = addMeasure([{ fn: 'sum', column: 'Revenues' }], { fn: 'count', column: 'Revenues' })
  assert.deepEqual(next[1], { fn: 'count', column: null })
})

test('replaceMeasureAt swaps a slot in place, keeping its rank', () => {
  const base = [{ fn: 'count', column: null }, { fn: 'sum', column: 'Revenues' }]
  const next = replaceMeasureAt(base, 0, { fn: 'avg', column: 'Revenues' })
  assert.notEqual(next, base)
  assert.deepEqual(next, [{ fn: 'avg', column: 'Revenues' }, { fn: 'sum', column: 'Revenues' }])
  assert.deepEqual(base[0], { fn: 'count', column: null }, 'the input list is never mutated')
  // A row count never carries a column, whatever the caller passes (base without a
  // count in the other slot, or the swap would be refused as a duplicate).
  const noCount = [{ fn: 'avg', column: 'Budget' }, { fn: 'sum', column: 'Revenues' }]
  assert.deepEqual(replaceMeasureAt(noCount, 1, { fn: 'count', column: 'Revenues' })[1], { fn: 'count', column: null })
})

test('replaceMeasureAt refuses no-ops and duplicates of ANOTHER slot', () => {
  const base = [{ fn: 'count', column: null }, { fn: 'sum', column: 'Revenues' }]
  // Same measure back into its own slot: the SAME list, so callers skip the refetch.
  assert.equal(replaceMeasureAt(base, 0, { fn: 'count', column: null }), base)
  // A measure another slot already holds would print the same figure twice.
  assert.equal(replaceMeasureAt(base, 0, { fn: 'sum', column: 'Revenues' }), base)
  // Invalid inputs: out-of-range index, unknown fn, column-less aggregate.
  assert.equal(replaceMeasureAt(base, 2, { fn: 'avg', column: 'Revenues' }), base)
  assert.equal(replaceMeasureAt(base, -1, { fn: 'avg', column: 'Revenues' }), base)
  assert.equal(replaceMeasureAt(base, 0, { fn: 'nope', column: 'Revenues' }), base)
  assert.equal(replaceMeasureAt(base, 0, { fn: 'avg', column: null }), base)
  assert.equal(replaceMeasureAt(base, 0, null), base)
})

test('removeMeasureAt never empties the list (there is always a result)', () => {
  const one = [{ fn: 'count', column: null }]
  assert.equal(removeMeasureAt(one, 0), one)
  const two = [{ fn: 'count', column: null }, { fn: 'sum', column: 'Revenues' }]
  assert.deepEqual(removeMeasureAt(two, 0), [{ fn: 'sum', column: 'Revenues' }])
  assert.deepEqual(removeMeasureAt(two, 1), [{ fn: 'count', column: null }])
  // Out-of-range indexes change nothing.
  assert.equal(removeMeasureAt(two, 5), two)
  assert.equal(removeMeasureAt(two, -1), two)
})

// -------------------------------------------------------------------- preview columns
const COLUMNS = [
  { name: 'diamond_id', type: 'bigint' },
  { name: 'Account_name', type: 'string' },
  { name: 'Solution', type: 'string' },
  { name: 'Revenues', type: 'double' },
]

test('orderPreviewColumns puts the analyzed columns first, in the given order', () => {
  const out = orderPreviewColumns(COLUMNS, ['Solution', 'Revenues'])
  assert.deepEqual(out.map((c) => c.name), ['Solution', 'Revenues', 'diamond_id', 'Account_name'])
  // The SAME column objects are returned (no copies, no renaming - F25).
  assert.equal(out[0], COLUMNS[2])
})

test('orderPreviewColumns dedupes, ignores unknown names and keeps every column', () => {
  const out = orderPreviewColumns(COLUMNS, ['Revenues', 'Revenues', 'nope', null])
  assert.deepEqual(out.map((c) => c.name), ['Revenues', 'diamond_id', 'Account_name', 'Solution'])
  assert.equal(out.length, COLUMNS.length)
})

test('orderPreviewColumns without pins keeps the natural order', () => {
  assert.deepEqual(
    orderPreviewColumns(COLUMNS, []).map((c) => c.name),
    COLUMNS.map((c) => c.name),
  )
  assert.deepEqual(orderPreviewColumns(COLUMNS, null).map((c) => c.name), COLUMNS.map((c) => c.name))
  assert.deepEqual(orderPreviewColumns(null, ['x']), [])
})

// ------------------------------------------------------------------------ bar geometry
test('barGeometry anchors an all-positive series to the left edge', () => {
  assert.deepEqual(barGeometry(100, 0, 100), { left: 0, width: 100 })
  assert.deepEqual(barGeometry(25, 0, 100), { left: 0, width: 25 })
  // A series whose minimum is positive still scales from zero (a bar is a magnitude).
  assert.deepEqual(barGeometry(50, 20, 100), { left: 0, width: 50 })
})

test('barGeometry draws a diverging bar around zero when the series spans it', () => {
  // -50..100 -> span 150, zero line at 33.33%
  const zero = (50 / 150) * 100
  const pos = barGeometry(100, -50, 100)
  assert.equal(Math.round(pos.left), Math.round(zero))
  assert.equal(Math.round(pos.width), Math.round((100 / 150) * 100))
  const neg = barGeometry(-50, -50, 100)
  assert.equal(Math.round(neg.left), 0)
  assert.equal(Math.round(neg.width), Math.round(zero))
  // The sign is preserved: two opposite values never render the same bar.
  assert.notDeepEqual(barGeometry(-25, -50, 100), barGeometry(25, -50, 100))
})

test('barGeometry anchors an all-negative series to the right edge', () => {
  const g = barGeometry(-100, -100, 0)
  assert.equal(Math.round(g.left), 0)
  assert.equal(Math.round(g.width), 100)
  const half = barGeometry(-50, -100, 0)
  assert.equal(Math.round(half.left), 50)
  assert.equal(Math.round(half.width), 50)
})

test('barGeometry answers an empty bar for a flat or unreadable series', () => {
  assert.deepEqual(barGeometry(0, 0, 0), { left: 0, width: 0 })
  assert.deepEqual(barGeometry(null, 0, 100), { left: 0, width: 0 })
  assert.deepEqual(barGeometry('nope', 0, 100), { left: 0, width: 0 })
  assert.deepEqual(barGeometry(5, NaN, NaN), { left: 0, width: 0 })
})

// ------------------------------------------------------------------- offerable measures
test('measureSpecForColumn offers quantities on a real numeric column', () => {
  assert.deepEqual(
    measureSpecForColumn('Revenues', 'double', false).map((s) => s.fn),
    ['sum', 'avg', 'median', 'min', 'max'],
  )
})

test('measureSpecForColumn never offers to SUM an identifier', () => {
  // Numeric to the database, nonsense as a quantity: only its distinct count is a question.
  assert.deepEqual(
    measureSpecForColumn('diamond_id', 'bigint', true).map((s) => s.fn),
    ['count_distinct'],
  )
  // A temporal or text column is unaffected by the guard.
  assert.deepEqual(measureSpecForColumn('Snapshot_date', 'date', false).map((s) => s.fn), ['min', 'max'])
  assert.deepEqual(measureSpecForColumn('Solution', 'string', false).map((s) => s.fn), ['count_distinct'])
  assert.deepEqual(measureSpecForColumn('Country', 'string', true).map((s) => s.fn), ['count_distinct'])
})

// --------------------------------------------------------------- the default measure
// The workspace must never open on a row count: the count is already stated under the
// dataset (user ask 2026-08-13), so the opening figure is the sum of the first quantity.
test('defaultWorkspaceMeasures opens on the SUM of the first numeric quantity column', () => {
  const columns = [
    { name: 'Account_name', type: 'string' },
    { name: 'Revenues', type: 'double' },
    { name: 'Margin', type: 'double' },
  ]
  assert.deepEqual(defaultWorkspaceMeasures(columns, isIdentifierColumn), [
    { fn: 'sum', column: 'Revenues' },
  ])
})

test('defaultWorkspaceMeasures skips identifier-shaped numerics', () => {
  const columns = [
    { name: 'diamond_id', type: 'bigint' },
    { name: 'year', type: 'int' },
    { name: 'postal_code', type: 'int' },
    { name: 'Revenues', type: 'double' },
  ]
  assert.deepEqual(defaultWorkspaceMeasures(columns, isIdentifierColumn), [
    { fn: 'sum', column: 'Revenues' },
  ])
})

test('defaultWorkspaceMeasures falls back to the row count when nothing can be summed', () => {
  const rowCount = [{ fn: 'count', column: null }]
  assert.deepEqual(defaultWorkspaceMeasures([{ name: 'Solution', type: 'string' }], isIdentifierColumn), rowCount)
  assert.deepEqual(defaultWorkspaceMeasures([{ name: 'customer_id', type: 'bigint' }], isIdentifierColumn), rowCount)
  assert.deepEqual(defaultWorkspaceMeasures([], isIdentifierColumn), rowCount)
  assert.deepEqual(defaultWorkspaceMeasures(null, isIdentifierColumn), rowCount)
  // No guard injected: every numeric column is fair game (never a crash).
  assert.deepEqual(defaultWorkspaceMeasures([{ name: 'year', type: 'int' }]), [{ fn: 'sum', column: 'year' }])
})

test('defaultWorkspaceMeasures ignores unusable column entries', () => {
  const columns = [null, { name: '', type: 'int' }, { name: 'Revenues', type: 'double' }]
  assert.deepEqual(defaultWorkspaceMeasures(columns, isIdentifierColumn), [
    { fn: 'sum', column: 'Revenues' },
  ])
})

// ------------------------------------------------------- which chip a cell value joins
test('pickCellFilterChip joins an existing equality chip on the column', () => {
  const chips = [
    { key: 'u1', column: 'Country', values: ['FR'] },
    { key: 'u2', column: 'Solution', values: ['VOICE'] },
  ]
  assert.equal(pickCellFilterChip(chips, 'Country').key, 'u1')
  assert.equal(pickCellFilterChip(chips, 'Margin'), null, 'no chip on that column -> a fresh one')
})

test('pickCellFilterChip never merges a raw value into a range chip', () => {
  const chips = [{ key: 'u1', column: 'Snapshot_date', op: 'BETWEEN', values: ['2026-01', '2026-06'] }]
  assert.equal(pickCellFilterChip(chips, 'Snapshot_date'), null)
})

test('pickCellFilterChip leaves a LOCKED agent chip alone and prefers the user chip', () => {
  const locked = { key: 'a1', column: 'Country', values: ['FR'], source: 'agent', editable: false }
  assert.equal(pickCellFilterChip([locked], 'Country'), null, 'the agent scope is not the user to edit')

  const editableAgent = { key: 'a2', column: 'Country', values: ['FR'], source: 'agent', editable: true }
  assert.equal(pickCellFilterChip([editableAgent], 'Country').key, 'a2')

  const userChip = { key: 'u9', column: 'Country', values: ['BE'], source: 'user', editable: true }
  assert.equal(
    pickCellFilterChip([editableAgent, userChip], 'Country').key,
    'u9',
    'a user chip wins when the column carries both',
  )
})

test('pickCellFilterChip tolerates a malformed chip list', () => {
  assert.equal(pickCellFilterChip(null, 'Country'), null)
  assert.equal(pickCellFilterChip([null, undefined], 'Country'), null)
})
