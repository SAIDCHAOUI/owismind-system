// Tests for composables/cellFormat.js - the pure table-cell display formatter
// (human-readable numbers in SQL result tables, identifier protection, per-column
// numeric inference for captured array-rows results). Pure node:test (F11).
import test from 'node:test'
import assert from 'node:assert/strict'
import {
  isNumericValue,
  isIdentifierColumn,
  inferNumericColumns,
  formatCell,
} from '../src/composables/cellFormat.js'

// ---------------------------------------------------------------- isNumericValue
test('isNumericValue accepts numbers and plain numeric strings', () => {
  assert.equal(isNumericValue(0), true)
  assert.equal(isNumericValue(-12.5), true)
  assert.equal(isNumericValue('12345678.901235'), true)
  assert.equal(isNumericValue('-42'), true)
  assert.equal(isNumericValue('.5'), true)
  assert.equal(isNumericValue('1.2e6'), true)
  assert.equal(isNumericValue(' 12 '), true) // trimmed
})

test('isNumericValue rejects dates, formatted numbers, text and empties', () => {
  assert.equal(isNumericValue('2025-01-01'), false)
  assert.equal(isNumericValue('2025-01'), false)
  assert.equal(isNumericValue('1,234.5'), false) // pre-formatted stays verbatim
  assert.equal(isNumericValue('12 500'), false)
  assert.equal(isNumericValue('EVPL'), false)
  assert.equal(isNumericValue(''), false)
  assert.equal(isNumericValue(null), false)
  assert.equal(isNumericValue(undefined), false)
  assert.equal(isNumericValue(NaN), false)
  assert.equal(isNumericValue(Infinity), false)
  assert.equal(isNumericValue(true), false)
})

// ------------------------------------------------------------ isIdentifierColumn
test('isIdentifierColumn flags id/code/year-like names on word boundaries', () => {
  assert.equal(isIdentifierColumn('id'), true)
  assert.equal(isIdentifierColumn('diamond_id'), true)
  assert.equal(isIdentifierColumn('Customer_id'), true)
  assert.equal(isIdentifierColumn('carrier_code'), true)
  assert.equal(isIdentifierColumn('Year'), true)
  assert.equal(isIdentifierColumn('year_month'), true)
  assert.equal(isIdentifierColumn('zip'), true)
})

test('isIdentifierColumn leaves quantity columns alone', () => {
  assert.equal(isIdentifierColumn('Revenue_EUR'), false)
  assert.equal(isIdentifierColumn('Total Revenue (EUR)'), false)
  assert.equal(isIdentifierColumn('amount'), false)
  assert.equal(isIdentifierColumn('idea_score'), false) // 'idea' is not 'id'
  assert.equal(isIdentifierColumn('monthly_total'), false) // 'monthly' is not 'month'
  // num/number are COUNT names at least as often as identifier names: never
  // excluded by NAME (the value-shape guard still catches id-shaped values).
  assert.equal(isIdentifierColumn('num_tickets'), false)
  assert.equal(isIdentifierColumn('number_of_incidents'), false)
  assert.equal(isIdentifierColumn(''), false)
  assert.equal(isIdentifierColumn(null), false)
})

// ---------------------------------------------------------- inferNumericColumns
test('inferNumericColumns classifies captured array rows per column', () => {
  const columns = ['Account_name', 'Revenue_EUR', 'diamond_id', 'month']
  const rows = [
    ['Acme', '1234.5', '111', '2025-01'],
    ['Beta', 987654321, '222', '2025-02'],
    ['Gamma', null, '333', '2025-03'],
  ]
  assert.deepEqual(inferNumericColumns(columns, rows), [
    false, // text
    true, // numeric quantity
    false, // numeric but identifier by name
    false, // identifier by name (and not numeric anyway)
  ])
})

test('inferNumericColumns: mixed / all-null columns are not numeric', () => {
  const columns = ['mixed', 'empty']
  const rows = [
    ['12', null],
    ['n/a', null],
  ]
  assert.deepEqual(inferNumericColumns(columns, rows), [false, false])
})

test('inferNumericColumns never throws on malformed input', () => {
  assert.deepEqual(inferNumericColumns(null, null), [])
  assert.deepEqual(inferNumericColumns(['a'], [null, 'not-a-row', { x: 1 }]), [false])
  const sparse = inferNumericColumns(['a', 'b'], [['1']]) // short row: b unseen
  assert.deepEqual(sparse, [true, false])
})

test('value-shape guard: same-width integer series read as identifiers', () => {
  // A period series (YYYYMM) or a phone/serial series: constant width, all
  // integers, >= 3 values -> NOT formatted, whatever the column name says.
  const cols = ['Period', 'Phone_like', 'Amount']
  const rows = [
    ['202501', '8001234567', '1234.5'],
    ['202502', '8007654321', 98765],
    ['202503', '8009999999', '42'],
  ]
  assert.deepEqual(inferNumericColumns(cols, rows), [false, false, true])
})

test('value-shape guard exempts small samples and varying widths', () => {
  // A single integer TOTAL row must stay formatted (no series to judge).
  assert.deepEqual(inferNumericColumns(['total'], [['1234567']]), [true])
  // Varying widths = real magnitudes, formatted even when all integers.
  const rows = [['123456'], ['98765432'], ['1200']]
  assert.deepEqual(inferNumericColumns(['count'], rows), [true])
})

test('formatCell normalizes negative zero', () => {
  assert.equal(formatCell(-0, true, 'en'), '0')
  assert.equal(formatCell('-0', true, 'en'), '0')
})

// ------------------------------------------------------------------- formatCell
test('formatCell makes big raw SQL numbers human-readable', () => {
  assert.equal(formatCell('12345678.901235', true, 'en'), '12,345,678.9')
  assert.equal(formatCell(12000000, true, 'en'), '12,000,000')
  assert.equal(formatCell('-9876543.21', true, 'en'), '-9,876,543.21')
})

test('formatCell leaves non-numeric, identifier and null cells alone', () => {
  assert.equal(formatCell(null, true, 'en'), '-')
  assert.equal(formatCell(undefined, false, 'en'), '-')
  assert.equal(formatCell('EVPL', true, 'en'), 'EVPL') // numeric column, text value
  assert.equal(formatCell('2025-01-01', true, 'en'), '2025-01-01')
  assert.equal(formatCell('12345678', false, 'en'), '12345678') // id column: verbatim
})

test('formatCell keeps tiny magnitudes visible and huge int strings exact', () => {
  assert.equal(formatCell(0.0004, true, 'en'), '0.0004')
  const huge = '12345678901234567890'
  assert.equal(formatCell(huge, true, 'en'), huge) // 16+ digits: DB-exact passthrough
})
