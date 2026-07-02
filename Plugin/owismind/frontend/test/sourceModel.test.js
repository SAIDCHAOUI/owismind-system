// Plugin/owismind/frontend/test/sourceModel.test.js
// Pure Source Data Explorer model (composables/sourceModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  normalizeSourceOp,
  makeSourceChip,
  effectiveSourceQuery,
  buildSourceRowsPayload,
  SOURCE_Q_MIN,
  SOURCE_Q_MAX,
} from '../src/composables/sourceModel.js'
import { extraMessages } from '../src/i18n/extra.js'

test('normalizeSourceOp: single value = "=", several = "IN"', () => {
  assert.equal(normalizeSourceOp(['x']), '=')
  assert.equal(normalizeSourceOp(['x', 'y']), 'IN')
})

test('makeSourceChip: stable key, normalized op, cloned values', () => {
  const values = ['A']
  const chip = makeSourceChip('country', values, 3)
  assert.equal(chip.key, 'u3')
  assert.equal(chip.column, 'country')
  assert.equal(chip.op, '=')
  assert.deepEqual(chip.values, ['A'])
  values.push('B')
  assert.equal(chip.values.length, 1) // no aliasing with the source array
  assert.equal(makeSourceChip('c', ['A', 'B'], 4).op, 'IN')
})

test('effectiveSourceQuery: trims, drops below the min, clamps to the max', () => {
  assert.equal(effectiveSourceQuery('  ab '), 'ab')
  assert.equal(effectiveSourceQuery('a'), '') // 1 char < SOURCE_Q_MIN
  assert.equal(effectiveSourceQuery('  '), '') // whitespace only
  assert.equal(effectiveSourceQuery(null), '')
  assert.equal(effectiveSourceQuery(undefined), '')
  assert.equal(SOURCE_Q_MIN, 2)
  const long = 'x'.repeat(SOURCE_Q_MAX + 50)
  assert.equal(effectiveSourceQuery(long).length, SOURCE_Q_MAX)
})

test('buildSourceRowsPayload: full shape per the frozen contract', () => {
  const chips = [
    makeSourceChip('country', ['DZ'], 1),
    makeSourceChip('phase', ['ACTUALS', 'BUDGET'], 2),
  ]
  const p = buildSourceRowsPayload('agentA', 3, 'algerie', chips, 2, { column: 'total', dir: 'desc' })
  assert.equal(p.agent, 'agentA')
  assert.equal(p.source, 3)
  assert.equal(p.q, 'algerie')
  assert.deepEqual(p.filters, [
    { column: 'country', op: '=', values: ['DZ'] },
    { column: 'phase', op: 'IN', values: ['ACTUALS', 'BUDGET'] },
  ])
  assert.equal(p.page, 2)
  assert.deepEqual(p.sort, { column: 'total', dir: 'desc' })
})

test('buildSourceRowsPayload: q below the threshold becomes an empty string', () => {
  const p = buildSourceRowsPayload('agentA', 0, 'a', [], 0, null)
  assert.equal(p.q, '')
  assert.deepEqual(p.filters, [])
  assert.equal(p.page, 0)
  assert.equal(p.sort, null)
})

test('buildSourceRowsPayload: op is derived from the value count, not a stale chip op', () => {
  // A chip whose op says '=' but that carries two values must still travel as 'IN'.
  const chip = { key: 'u1', column: 'phase', op: '=', values: ['A', 'B'] }
  const p = buildSourceRowsPayload('agentA', 1, '', [chip], 0, null)
  assert.deepEqual(p.filters, [{ column: 'phase', op: 'IN', values: ['A', 'B'] }])
})

test('buildSourceRowsPayload: skips empty / malformed chips', () => {
  const chips = [
    { key: 'u1', column: 'ok', op: '=', values: ['v'] },
    { key: 'u2', column: '', op: '=', values: ['v'] }, // no column
    { key: 'u3', column: 'noval', op: '=', values: [] }, // no values
    null,
  ]
  const p = buildSourceRowsPayload('agentA', 1, '', chips, 0, null)
  assert.deepEqual(p.filters, [{ column: 'ok', op: '=', values: ['v'] }])
})

test('buildSourceRowsPayload: defaults for omitted page / sort', () => {
  const p = buildSourceRowsPayload('agentA', 2, '', undefined, undefined, undefined)
  assert.equal(p.page, 0)
  assert.equal(p.sort, null)
  assert.deepEqual(p.filters, [])
})

test('buildSourceRowsPayload: does not alias the chip values array', () => {
  const chip = makeSourceChip('c', ['A'], 1)
  const p = buildSourceRowsPayload('agentA', 1, '', [chip], 0, null)
  p.filters[0].values.push('B')
  assert.equal(chip.values.length, 1)
})

// --- i18n contract: every Source Explorer key exists in fr + en ----------------------

const SRC_KEYS = [
  'ev.tab.sources',
  'src.cta.title', 'src.cta.hint', 'src.panel.title', 'src.dataset_label',
  'src.search.placeholder', 'src.search.min',
  'src.filters.title', 'src.filters.add', 'src.filters.clear', 'src.filters.remove',
  'src.column',
  'src.picker.empty', 'src.picker.truncated', 'src.picker.max', 'src.picker.apply',
  'src.loading', 'src.error', 'src.retry', 'src.empty',
  'src.loaded', 'src.more', 'src.loadingMore',
]

test('extra.js covers every Source Explorer key (fr + en)', () => {
  for (const loc of ['fr', 'en']) {
    for (const key of SRC_KEYS) {
      const v = extraMessages[loc][key]
      assert.equal(typeof v, 'string', loc + ' missing ' + key)
      assert.ok(v.length > 0, loc + ' empty ' + key)
    }
  }
})
