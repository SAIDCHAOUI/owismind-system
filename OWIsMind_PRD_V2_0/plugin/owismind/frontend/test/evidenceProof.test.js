// OWIsMind_PRD_V1_3_DEV/plugin/owismind/frontend/test/evidenceProof.test.js
// Pure Evidence trust-layer helpers (composables/evidenceProof.js). NO install:
//   from frontend/ run  node --test test/evidenceProof.test.js
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  trustLevel,
  calcStepArgs,
  droppedNote,
  EXPLANATION_KINDS,
  MAX_CALC_STEPS,
} from '../src/composables/evidenceProof.js'

function metaWith(level, captured, extra) {
  return Object.assign(
    { available: true, verification: { level, result_captured: captured } },
    extra || {},
  )
}

// ---------------------------------------------------------------------------
// trustLevel - full (level × result_captured) matrix + degraded/v1 fallbacks
// ---------------------------------------------------------------------------

test('trustLevel: calc_decomposed + captured is the strongest badge', () => {
  assert.deepEqual(trustLevel(metaWith('calc_decomposed', true)), {
    key: 'ev.proof.level.result',
    tone: 'solid',
  })
})

test('trustLevel: calc_decomposed without captured result downgrades to source', () => {
  assert.deepEqual(trustLevel(metaWith('calc_decomposed', false)), {
    key: 'ev.proof.level.source',
    tone: 'solid',
  })
})

test('trustLevel: scope_exact maps to source whatever result_captured says', () => {
  // captured is orthogonal: it only elevates calc_decomposed, never scope_exact.
  assert.deepEqual(trustLevel(metaWith('scope_exact', true)), {
    key: 'ev.proof.level.source',
    tone: 'solid',
  })
  assert.deepEqual(trustLevel(metaWith('scope_exact', false)), {
    key: 'ev.proof.level.source',
    tone: 'solid',
  })
})

test('trustLevel: scope_partial and source_identified map to partial (dashed)', () => {
  for (const level of ['scope_partial', 'source_identified']) {
    for (const captured of [true, false]) {
      assert.deepEqual(trustLevel(metaWith(level, captured)), {
        key: 'ev.proof.level.partial',
        tone: 'dashed',
      })
    }
  }
})

test('trustLevel: declared level maps to the muted floor', () => {
  for (const captured of [true, false]) {
    assert.deepEqual(trustLevel(metaWith('declared', captured)), {
      key: 'ev.proof.level.declared',
      tone: 'muted',
    })
  }
})

test('trustLevel: absent meta falls back to declared', () => {
  const expected = { key: 'ev.proof.level.declared', tone: 'muted' }
  assert.deepEqual(trustLevel(null), expected)
  assert.deepEqual(trustLevel(undefined), expected)
})

test('trustLevel: v1 meta without a verification block falls back to declared', () => {
  assert.deepEqual(trustLevel({ available: true, dataset: 'D', chips: [] }), {
    key: 'ev.proof.level.declared',
    tone: 'muted',
  })
})

test('trustLevel: degraded meta is declared even with a strong stray level', () => {
  // available === false is the degraded marker - never upgrade a degraded panel.
  const meta = { available: false, verification: { level: 'calc_decomposed', result_captured: true } }
  assert.deepEqual(trustLevel(meta), { key: 'ev.proof.level.declared', tone: 'muted' })
})

test('trustLevel: unknown or malformed level strings fall back to declared', () => {
  for (const level of ['certified', '', 42, null]) {
    const meta = { available: true, verification: { level, result_captured: true } }
    assert.deepEqual(trustLevel(meta), { key: 'ev.proof.level.declared', tone: 'muted' })
  }
})

test('trustLevel: tone is always one of the three frozen tones', () => {
  const tones = new Set(['solid', 'dashed', 'muted'])
  const levels = ['calc_decomposed', 'scope_exact', 'scope_partial', 'source_identified', 'declared', 'weird']
  for (const level of levels) {
    for (const captured of [true, false]) {
      assert.ok(tones.has(trustLevel(metaWith(level, captured)).tone))
    }
  }
  assert.ok(tones.has(trustLevel(null).tone))
})

// ---------------------------------------------------------------------------
// calcStepArgs - known kinds, opaque fallback, param truncation
// ---------------------------------------------------------------------------

test('calcStepArgs: known kind maps to its ev.exp.* key with verbatim params', () => {
  const out = calcStepArgs({ kind: 'filter_eq', params: ['phase', 'ACTUALS'] })
  assert.deepEqual(out, { key: 'ev.exp.filter_eq', args: ['phase', 'ACTUALS'] })
})

test('calcStepArgs: every kind of the frozen enum maps to its own key', () => {
  for (const kind of EXPLANATION_KINDS) {
    assert.equal(calcStepArgs({ kind, params: [] }).key, 'ev.exp.' + kind)
  }
})

test('calcStepArgs: unknown kind falls back to ev.exp.opaque (params kept)', () => {
  const out = calcStepArgs({ kind: 'quantum_join', params: ['x'] })
  assert.deepEqual(out, { key: 'ev.exp.opaque', args: ['x'] })
})

test('calcStepArgs: missing/malformed step degrades to opaque with no args', () => {
  assert.deepEqual(calcStepArgs(null), { key: 'ev.exp.opaque', args: [] })
  assert.deepEqual(calcStepArgs({}), { key: 'ev.exp.opaque', args: [] })
  assert.deepEqual(calcStepArgs({ kind: 'group', params: 'oops' }), { key: 'ev.exp.group', args: [] })
})

test('calcStepArgs: params longer than 80 chars are truncated to 80 with ellipsis', () => {
  const long = 'x'.repeat(200)
  const { args } = calcStepArgs({ kind: 'filter_like', params: ['col', long] })
  assert.equal(args[1].length, 80)
  assert.ok(args[1].endsWith('…'))
  assert.equal(args[1].slice(0, 79), 'x'.repeat(79))
})

test('calcStepArgs: an exactly-80-chars param is kept untouched', () => {
  const exact = 'y'.repeat(80)
  const { args } = calcStepArgs({ kind: 'having', params: [exact] })
  assert.equal(args[0], exact)
})

test('calcStepArgs: non-string params are stringified, null becomes empty', () => {
  const { args } = calcStepArgs({ kind: 'topn', params: [10, 'total', null] })
  assert.deepEqual(args, ['10', 'total', ''])
})

// ---------------------------------------------------------------------------
// droppedNote - count of non-reproduced conditions
// ---------------------------------------------------------------------------

test('droppedNote: absent verification means nothing was dropped', () => {
  assert.equal(droppedNote(null), 0)
  assert.equal(droppedNote(undefined), 0)
  assert.equal(droppedNote({}), 0)
})

test('droppedNote: returns the dropped_predicates count', () => {
  assert.equal(droppedNote({ dropped_predicates: 3, dropped_display: [] }), 3)
})

test('droppedNote: a longer dropped_display list wins over the counter', () => {
  assert.equal(droppedNote({ dropped_predicates: 1, dropped_display: ['a', 'b', 'c'] }), 3)
})

test('droppedNote: negative/NaN counters are floored at 0', () => {
  assert.equal(droppedNote({ dropped_predicates: -2 }), 0)
  assert.equal(droppedNote({ dropped_predicates: 'oops' }), 0)
  assert.equal(droppedNote({ dropped_predicates: 'oops', dropped_display: ['x'] }), 1)
})

// ---------------------------------------------------------------------------
// Exported constants sanity (the components rely on them)
// ---------------------------------------------------------------------------

test('constants: frozen enum carries 41 kinds including opaque; step cap is 15', () => {
  assert.equal(EXPLANATION_KINDS.length, 41)
  assert.ok(EXPLANATION_KINDS.includes('opaque'))
  assert.equal(new Set(EXPLANATION_KINDS).size, EXPLANATION_KINDS.length) // no dupes
  assert.equal(MAX_CALC_STEPS, 15)
})

// ---------------------------------------------------------------------------
// humanizeColumn / businessStepArgs - business wording of column names
// ---------------------------------------------------------------------------
import { humanizeColumn, businessStepArgs } from '../src/composables/evidenceProof.js'

test('humanizeColumn: underscores, qualifiers, quotes and camelCase become sentence case', () => {
  assert.equal(humanizeColumn('REVENUE_MONTH'), 'Revenue month')
  assert.equal(humanizeColumn('customer_name'), 'Customer name')
  assert.equal(humanizeColumn('t."Account_name"'), 'Account name')
  assert.equal(humanizeColumn('creationDate'), 'Creation date')
  assert.equal(humanizeColumn('CA_HT'), 'CA HT')
  assert.equal(humanizeColumn('customer_ID'), 'Customer ID')
})

test('humanizeColumn: a business label wins over the humanized name', () => {
  const labels = { Phase: 'Type de chiffre', Account_name: 'Client' }
  assert.equal(humanizeColumn('Phase', labels), 'Type de chiffre')
  assert.equal(humanizeColumn('r.Account_name', labels), 'Client')
  assert.equal(humanizeColumn('Other_col', labels), 'Other col')
})

test('humanizeColumn: expressions, literals and empty input are left alone', () => {
  assert.equal(humanizeColumn('amount * qty'), 'amount * qty')
  assert.equal(humanizeColumn("'2026-01'"), "'2026-01'")
  assert.equal(humanizeColumn(''), '')
  assert.equal(humanizeColumn(null), '')
})

test('businessStepArgs: filter sentences name the column in business words, values verbatim', () => {
  assert.deepEqual(businessStepArgs({ kind: 'filter_eq', params: ['revenue_month', '2026-01'] }), {
    key: 'ev.exp.filter_eq', args: ['Revenue month', '2026-01'],
  })
  assert.deepEqual(businessStepArgs({ kind: 'filter_in', params: ['PHASE', 2, 'ACTUALS, BUDGET'] }), {
    key: 'ev.exp.filter_in', args: ['Phase', '2', 'ACTUALS, BUDGET'],
  })
  assert.deepEqual(businessStepArgs({ kind: 'group', params: ['account_name, carrier_code'] }), {
    key: 'ev.exp.group', args: ['Account name, Carrier code'],
  })
  assert.deepEqual(businessStepArgs({ kind: 'filter_eq', params: ['Phase', 'A'] }, { Phase: 'Type' }).args, ['Type', 'A'])
})

test('businessStepArgs: non-column steps and unknown kinds fall back to calcStepArgs', () => {
  const adv = { kind: 'filter_advanced', params: ['a_b > 3 OR c_d IS NULL'] }
  assert.deepEqual(businessStepArgs(adv), calcStepArgs(adv))
  assert.deepEqual(businessStepArgs({ kind: 'nope' }), { key: 'ev.exp.opaque', args: [] })
  assert.deepEqual(businessStepArgs(null), calcStepArgs(null))
})
