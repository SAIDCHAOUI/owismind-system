// OWIsMind_PRD_V2_0/plugin/owismind/frontend/test/measurePickerModel.test.js
// Pure model of the Analyze measure picker (composables/measurePickerModel.js): grouping by
// column type, search, flat order and keyboard stepping. NO install: from frontend/ run
//   node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MEASURE_GROUP_ORDER,
  measureGroupOf,
  measureShortLabelKey,
  buildMeasureGroups,
  filterMeasureGroups,
  flattenMeasureOptions,
  stepMeasureOption,
} from '../src/composables/measurePickerModel.js'

const COLUMNS = [
  { name: 'Revenues', type: 'double' },
  { name: 'Customer_ID', type: 'bigint' },
  { name: 'Month', type: 'date' },
  { name: 'Country', type: 'string' },
  { name: 'Volume', type: 'int' },
]
const isId = (name) => name === 'Customer_ID'
const LABELS = {
  count: 'Row count', sum: 'Sum of {0}', avg: 'Average of {0}', median: 'Median of {0}',
  min: 'Min of {0}', max: 'Max of {0}', count_distinct: 'Distinct values of {0}',
}
const labelOf = (o) => LABELS[o.fn].replace('{0}', o.column || '')

test('measureGroupOf: numeric quantities, dates, everything else as text (identifiers too)', () => {
  assert.equal(measureGroupOf('double', false), 'number')
  assert.equal(measureGroupOf('bigint', true), 'text')
  assert.equal(measureGroupOf('date', false), 'date')
  assert.equal(measureGroupOf('timestamp with time zone', false), 'date')
  assert.equal(measureGroupOf('string', false), 'text')
  assert.equal(measureGroupOf('', false), 'text')
})

test('buildMeasureGroups: rows first, then numbers, dates, text, columns in natural order', () => {
  const groups = buildMeasureGroups(COLUMNS, isId)
  assert.deepEqual(groups.map((g) => g.kind), MEASURE_GROUP_ORDER)
  assert.deepEqual(groups[0].columns[0].options, [{ fn: 'count', column: null, key: 'count' }])
  assert.deepEqual(groups[1].columns.map((c) => c.name), ['Revenues', 'Volume'])
  assert.deepEqual(groups[1].columns[0].options.map((o) => o.fn), ['sum', 'avg', 'median', 'min', 'max'])
  assert.deepEqual(groups[2].columns[0].options.map((o) => o.fn), ['min', 'max'])
  // The numeric identifier is never summed: distinct values, in the text group.
  assert.deepEqual(groups[3].columns.map((c) => c.name), ['Customer_ID', 'Country'])
  assert.deepEqual(groups[3].columns[0].options, [{ fn: 'count_distinct', column: 'Customer_ID', key: 'count_distinct:Customer_ID' }])
})

test('buildMeasureGroups: empty groups are dropped, bad columns ignored', () => {
  const groups = buildMeasureGroups([{ name: 'Country', type: 'string' }, null, { type: 'int' }])
  assert.deepEqual(groups.map((g) => g.kind), ['rows', 'text'])
  assert.deepEqual(buildMeasureGroups(null).map((g) => g.kind), ['rows'])
})

test('measureShortLabelKey: short function names inside a column block', () => {
  assert.equal(measureShortLabelKey('sum'), 'src.calc.sum')
  assert.equal(measureShortLabelKey('count_distinct'), 'src.calc.distinct')
  assert.equal(measureShortLabelKey('count'), 'src.an.fn.count')
  assert.equal(measureShortLabelKey('nope'), '')
})

test('filterMeasureGroups: a column-name hit keeps all its functions', () => {
  const groups = filterMeasureGroups(buildMeasureGroups(COLUMNS, isId), 'reven', labelOf)
  assert.deepEqual(groups.map((g) => g.kind), ['number'])
  assert.equal(groups[0].columns[0].options.length, 5)
})

test('filterMeasureGroups: a label hit keeps only the matching functions', () => {
  const groups = filterMeasureGroups(buildMeasureGroups(COLUMNS, isId), 'SUM', labelOf)
  assert.deepEqual(groups.map((g) => g.kind), ['number'])
  assert.deepEqual(groups[0].columns.map((c) => c.options.map((o) => o.key)), [['sum:Revenues'], ['sum:Volume']])
  // "row" finds the row count; a blank term returns the input untouched.
  assert.deepEqual(filterMeasureGroups(buildMeasureGroups(COLUMNS, isId), 'row', labelOf).map((g) => g.kind), ['rows'])
  const all = buildMeasureGroups(COLUMNS, isId)
  assert.equal(filterMeasureGroups(all, '  ', labelOf), all)
  assert.deepEqual(filterMeasureGroups(all, 'zzz', labelOf), [])
})

test('flattenMeasureOptions: display order across groups and columns', () => {
  const flat = flattenMeasureOptions(buildMeasureGroups(COLUMNS, isId))
  assert.equal(flat[0].key, 'count')
  assert.equal(flat[1].key, 'sum:Revenues')
  assert.equal(flat[flat.length - 1].key, 'count_distinct:Country')
  assert.equal(flat.length, 1 + 5 + 5 + 2 + 1 + 1)
})

test('stepMeasureOption: walks enabled options, wraps, skips the used ones', () => {
  const opts = [{ key: 'a' }, { key: 'b' }, { key: 'c' }]
  const usedB = (o) => o.key === 'b'
  assert.equal(stepMeasureOption(opts, -1, 1, usedB), 0)
  assert.equal(stepMeasureOption(opts, 0, 1, usedB), 2)
  assert.equal(stepMeasureOption(opts, 2, 1, usedB), 0) // wraps forward
  assert.equal(stepMeasureOption(opts, 0, -1, usedB), 2) // wraps backward
  assert.equal(stepMeasureOption(opts, -1, -1, usedB), 2) // from nothing, up = last
  assert.equal(stepMeasureOption(opts, 0, 1, () => true), -1) // nothing pickable
  assert.equal(stepMeasureOption([], -1, 1), -1)
})
