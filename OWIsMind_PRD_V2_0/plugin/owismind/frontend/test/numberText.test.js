// Figures never split (text widget) - run with `node --test`.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { keepNumbersTogether as keep } from '../src/composables/numberText.js'

const N = ' ' // narrow no-break space (digit groups)
const S = ' ' // no-break space (figure + unit)

test('digit groups are joined with a narrow no-break space, the unit kept attached', () => {
  assert.equal(keep('Total : 8 593 242,88 EUR.'), `Total : 8${N}593${N}242,88${S}EUR.`)
  assert.equal(keep('soit 12 400 clients'), `soit 12${N}400 clients`)
  assert.equal(keep('1 000 000'), `1${N}000${N}000`)
  assert.equal(keep('- 3 200 k€ et 4 M'), `- 3${N}200${S}k€ et 4${S}M`)
})

test('units: %, currencies, magnitudes; only whole unit tokens', () => {
  assert.equal(keep('hausse de 12,5 %'), `hausse de 12,5${S}%`)
  assert.equal(keep('12 USD, 3 $ et 2 pts'), `12${S}USD, 3${S}$ et 2${S}pts`)
  assert.equal(keep('1,2 Md de CA'), `1,2${S}Md de CA`)
  assert.equal(keep('sur 3 Mois'), 'sur 3 Mois')
  assert.equal(keep('les 5 Meilleurs'), 'les 5 Meilleurs')
  assert.equal(keep('4 kg'), '4 kg')
})

test('things that are not grouped figures are left alone', () => {
  assert.equal(keep('entre 2025 2026'), 'entre 2025 2026')
  assert.equal(keep('ref 12 3456'), 'ref 12 3456')
  assert.equal(keep('10 et 20 comptes'), '10 et 20 comptes')
  assert.equal(keep('1. 200 clients'), '1. 200 clients')
})

test('code spans and fenced blocks are never rewritten', () => {
  assert.equal(keep('`1 000 EUR` puis 1 000 EUR'), `\`1 000 EUR\` puis 1${N}000${S}EUR`)
  const fenced = '```\nSELECT 1 000 %\n```\n2 000 EUR'
  assert.equal(keep(fenced), `\`\`\`\nSELECT 1 000 %\n\`\`\`\n2${N}000${S}EUR`)
  assert.equal(keep('~~~\n1 000\n'), '~~~\n1 000\n')
})

test('markdown structure survives (tables, emphasis, lists)', () => {
  assert.equal(keep('| A | 1 234 EUR |'), `| A | 1${N}234${S}EUR |`)
  assert.equal(keep('**8 593 EUR** au total'), `**8${N}593${S}EUR** au total`)
  assert.equal(keep('- 1 500 tickets\n- 2 %'), `- 1${N}500 tickets\n- 2${S}%`)
})

test('idempotent, and safe on empty / non-string input', () => {
  const once = keep('Total 8 593 242,88 EUR, +12 %')
  assert.equal(keep(once), once)
  assert.equal(keep(''), '')
  assert.equal(keep(null), '')
  assert.equal(keep(undefined), '')
  assert.equal(keep(42), '')
})
