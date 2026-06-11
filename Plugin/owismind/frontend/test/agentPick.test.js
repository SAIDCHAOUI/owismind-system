// pickDefaultAgent: pure default-agent selection — prefer the last-used key when it is
// still enabled, otherwise fall back to the first enabled agent (empty when none).
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { pickDefaultAgent } from '../src/stores/agentPick.js'

test('prefers lastKey when still enabled', () => {
  assert.equal(pickDefaultAgent([{ key: 'a' }, { key: 'b' }], 'b'), 'b')
})

test('falls back to first when lastKey gone/empty', () => {
  assert.equal(pickDefaultAgent([{ key: 'a' }, { key: 'b' }], 'z'), 'a')
  assert.equal(pickDefaultAgent([{ key: 'a' }], null), 'a')
})

test('empty agents -> empty string', () => {
  assert.equal(pickDefaultAgent([], 'x'), '')
})
