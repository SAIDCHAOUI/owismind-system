// i18n parity guard for the domain catalog (extra.js) - run with `node --test`.
// Every flat key must exist in BOTH locales (fr + en) with a non-empty string, and
// list-interpolation placeholders ({0}, {1}, ...) must match across locales so a
// t('key', [args]) call renders the same slots in either language. This protects the
// benchmark-view keys added by the consultation redesign against a one-locale drift.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { extraMessages } from '../src/i18n/extra.js'

const fr = extraMessages.fr
const en = extraMessages.en

test('extra.js - fr and en expose the exact same key set', () => {
  const frKeys = Object.keys(fr).sort()
  const enKeys = Object.keys(en).sort()
  const onlyFr = frKeys.filter((k) => !(k in en))
  const onlyEn = enKeys.filter((k) => !(k in fr))
  assert.deepEqual(onlyFr, [], 'keys only in fr: ' + onlyFr.join(', '))
  assert.deepEqual(onlyEn, [], 'keys only in en: ' + onlyEn.join(', '))
})

test('extra.js - every value is a non-empty string', () => {
  for (const [k, v] of Object.entries(fr)) {
    assert.equal(typeof v, 'string', 'fr value not a string: ' + k)
    assert.ok(v.length > 0, 'fr value empty: ' + k)
  }
  for (const [k, v] of Object.entries(en)) {
    assert.equal(typeof v, 'string', 'en value not a string: ' + k)
    assert.ok(v.length > 0, 'en value empty: ' + k)
  }
})

// The sorted set of {n} placeholders inside a string (list interpolation slots).
function slots(str) {
  const found = String(str).match(/\{\d+\}/g) || []
  return Array.from(new Set(found)).sort()
}

test('extra.js - interpolation slots match across locales', () => {
  for (const k of Object.keys(fr)) {
    assert.deepEqual(slots(fr[k]), slots(en[k]), 'placeholder mismatch for key: ' + k)
  }
})
