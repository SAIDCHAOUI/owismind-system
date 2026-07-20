// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/promptContextModel.test.js
// Pure prompt-context model (composables/promptContextModel.js). NO install:
//   from frontend/ run  node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  MAX_CONTEXT_VALUES,
  MAX_CONTEXT_VALUE_CHARS,
  contextKey,
  normalizeContextItem,
  addContextValue,
  buildContextBlock,
} from '../src/composables/promptContextModel.js'

test('caps have the expected values', () => {
  assert.equal(MAX_CONTEXT_VALUES, 12)
  assert.equal(MAX_CONTEXT_VALUE_CHARS, 200)
})

test('normalizeContextItem: rejects missing column', () => {
  assert.equal(normalizeContextItem({ column: '', value: 'x' }), null)
  assert.equal(normalizeContextItem({ column: '   ', value: 'x' }), null)
  assert.equal(normalizeContextItem({ value: 'x' }), null)
})

test('normalizeContextItem: rejects null/undefined/empty value', () => {
  assert.equal(normalizeContextItem({ column: 'c', value: null }), null)
  assert.equal(normalizeContextItem({ column: 'c', value: undefined }), null)
  assert.equal(normalizeContextItem({ column: 'c', value: '' }), null)
  assert.equal(normalizeContextItem({ column: 'c', value: '   ' }), null)
})

test('normalizeContextItem: rejects value longer than the cap', () => {
  const long = 'a'.repeat(MAX_CONTEXT_VALUE_CHARS + 1)
  assert.equal(normalizeContextItem({ column: 'c', value: long }), null)
  const atCap = 'a'.repeat(MAX_CONTEXT_VALUE_CHARS)
  assert.deepEqual(normalizeContextItem({ column: 'c', value: atCap }), {
    source: '',
    column: 'c',
    value: atCap,
  })
})

test('normalizeContextItem: trims fields and coerces non-strings', () => {
  assert.deepEqual(normalizeContextItem({ source: '  Accounts ', column: ' Country ', value: '  France ' }), {
    source: 'Accounts',
    column: 'Country',
    value: 'France',
  })
  // Non-string value / column are coerced with String().
  assert.deepEqual(normalizeContextItem({ column: 42, value: 2026 }), {
    source: '',
    column: '42',
    value: '2026',
  })
  // Zero is a valid value (String(0) = '0', not empty).
  assert.deepEqual(normalizeContextItem({ column: 'n', value: 0 }), {
    source: '',
    column: 'n',
    value: '0',
  })
})

test('contextKey: distinguishes source, column and value', () => {
  const a = normalizeContextItem({ source: 's', column: 'c', value: 'v' })
  const b = normalizeContextItem({ source: 's', column: 'c', value: 'v2' })
  const c = normalizeContextItem({ source: 's2', column: 'c', value: 'v' })
  assert.notEqual(contextKey(a), contextKey(b))
  assert.notEqual(contextKey(a), contextKey(c))
  assert.equal(contextKey(a), contextKey(normalizeContextItem({ source: 's', column: 'c', value: 'v' })))
})

test('addContextValue: adds without mutating the input list', () => {
  const list = []
  const res = addContextValue(list, { column: 'c', value: 'v' })
  assert.equal(res.status, 'added')
  assert.equal(res.items.length, 1)
  assert.equal(list.length, 0) // input untouched
})

test('addContextValue: invalid item leaves the list unchanged', () => {
  const list = [normalizeContextItem({ column: 'c', value: 'v' })]
  const res = addContextValue(list, { column: '', value: 'x' })
  assert.equal(res.status, 'invalid')
  assert.equal(res.items.length, 1)
})

test('addContextValue: dedup by (source, column, value)', () => {
  let items = []
  items = addContextValue(items, { source: 's', column: 'c', value: 'v' }).items
  const res = addContextValue(items, { source: 's', column: 'c', value: 'v' })
  assert.equal(res.status, 'exists')
  assert.equal(res.items.length, 1)
  // Same column, different value = a new entry.
  const res2 = addContextValue(items, { source: 's', column: 'c', value: 'w' })
  assert.equal(res2.status, 'added')
  assert.equal(res2.items.length, 2)
})

test('addContextValue: caps at MAX_CONTEXT_VALUES', () => {
  let items = []
  for (let i = 0; i < MAX_CONTEXT_VALUES; i++) {
    const r = addContextValue(items, { column: 'c', value: 'v' + i })
    assert.equal(r.status, 'added')
    items = r.items
  }
  assert.equal(items.length, MAX_CONTEXT_VALUES)
  const full = addContextValue(items, { column: 'c', value: 'overflow' })
  assert.equal(full.status, 'full')
  assert.equal(full.items.length, MAX_CONTEXT_VALUES)
})

test('buildContextBlock: empty list -> empty string', () => {
  assert.equal(buildContextBlock([], 'en'), '')
  assert.equal(buildContextBlock(null, 'en'), '')
})

test('buildContextBlock: en header, single group, source suffix', () => {
  const items = [normalizeContextItem({ source: 'Accounts', column: 'Country', value: 'France' })]
  assert.equal(buildContextBlock(items, 'en'), 'Data context:\n- Country = "France" (source: Accounts)')
})

test('buildContextBlock: fr header on the fr prefix', () => {
  const items = [normalizeContextItem({ column: 'Ville', value: 'Paris' })]
  assert.equal(buildContextBlock(items, 'fr'), 'Contexte de données :\n- Ville = "Paris"')
})

test('buildContextBlock: fr source label uses French colon spacing', () => {
  const items = [normalizeContextItem({ source: 'Comptes', column: 'Ville', value: 'Paris' })]
  assert.equal(
    buildContextBlock(items, 'fr'),
    'Contexte de données :\n- Ville = "Paris" (source : Comptes)',
  )
})

test('buildContextBlock: empty source omits the suffix', () => {
  const items = [normalizeContextItem({ column: 'c', value: 'v' })]
  assert.equal(buildContextBlock(items, 'en'), 'Data context:\n- c = "v"')
})

test('buildContextBlock: groups by (source, column) in insertion order', () => {
  const items = [
    normalizeContextItem({ source: 'A', column: 'Country', value: 'France' }),
    normalizeContextItem({ source: 'A', column: 'City', value: 'Lyon' }),
    normalizeContextItem({ source: 'A', column: 'Country', value: 'Spain' }),
    normalizeContextItem({ source: 'B', column: 'Country', value: 'Italy' }),
  ]
  const block = buildContextBlock(items, 'en')
  assert.equal(
    block,
    [
      'Data context:',
      '- Country = "France", "Spain" (source: A)',
      '- City = "Lyon" (source: A)',
      '- Country = "Italy" (source: B)',
    ].join('\n'),
  )
})
