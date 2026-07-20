// Pure budget/usage helpers - run with `node --test test/*.test.js` (NO install).
// Asserts the gauge math + the severity level + the formatting edge cases that the
// profile card, the chat banner and the admin quotas table all depend on.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  toNum,
  formatMoney,
  formatTokens,
  formatShortDate,
  usagePct,
  gaugePct,
  usageLevel,
} from '../src/composables/budgetModel.js'

test('toNum coerces and defaults', () => {
  assert.equal(toNum(12.5), 12.5)
  assert.equal(toNum('3'), 3)
  assert.equal(toNum(null), 0)
  assert.equal(toNum(undefined, 7), 7)
  assert.equal(toNum('abc'), 0)
  assert.equal(toNum(Infinity), 0)
})

test('formatMoney - whole + cents are stable', () => {
  assert.equal(formatMoney(50, 'en'), '$50.00')
  assert.equal(formatMoney(0, 'en'), '$0.00')
  assert.equal(formatMoney(12.5, 'en'), '$12.50')
  assert.equal(formatMoney(37.5, 'en', '€'), '€37.50')
})

test('formatMoney - tiny non-zero keeps precision (never a misleading $0.00)', () => {
  // < 0.01 widens to 4 decimals so real usage is visible.
  assert.equal(formatMoney(0.004, 'en'), '$0.004')
  assert.notEqual(formatMoney(0.004, 'en'), '$0.00')
})

test('formatTokens groups and coerces', () => {
  assert.equal(formatTokens(0, 'en'), '0')
  assert.equal(formatTokens(12345, 'en'), '12,345')
  assert.equal(formatTokens(null, 'en'), '0')
})

test('formatShortDate - empty/invalid yields empty string', () => {
  assert.equal(formatShortDate(null, 'en'), '')
  assert.equal(formatShortDate('', 'en'), '')
  assert.equal(formatShortDate('not-a-date', 'en'), '')
  assert.notEqual(formatShortDate('2026-07-01T00:00:00', 'en'), '')
})

test('usagePct - normal, over, and zero-limit', () => {
  assert.equal(usagePct(25, 50), 50)
  assert.equal(usagePct(60, 50), 120) // can exceed 100
  assert.equal(usagePct(0, 50), 0)
  assert.equal(usagePct(5, 0), 100) // $0 limit + any spend = fully used
  assert.equal(usagePct(0, 0), 0)
})

test('gaugePct clamps to [0,100]', () => {
  assert.equal(gaugePct(60, 50), 100)
  assert.equal(gaugePct(25, 50), 50)
  assert.equal(gaugePct(-5, 50), 0)
})

test('usageLevel - off / over / warn / ok', () => {
  assert.equal(usageLevel(null), 'ok')
  assert.equal(usageLevel({ enforced: false, blocked: true, spent_usd: 99, limit_usd: 50 }), 'off')
  assert.equal(usageLevel({ enforced: true, blocked: true, spent_usd: 50, limit_usd: 50 }), 'over')
  assert.equal(usageLevel({ enforced: true, blocked: false, spent_usd: 50, limit_usd: 50 }), 'over') // 100%
  assert.equal(usageLevel({ enforced: true, blocked: false, spent_usd: 40, limit_usd: 50 }), 'warn') // 80%
  assert.equal(usageLevel({ enforced: true, blocked: false, spent_usd: 10, limit_usd: 50 }), 'ok')
})
