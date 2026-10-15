// Unit tests for the pure preference helper (stores/prefs.js). NO install:
//   from frontend/ run  node --test test/
// Bounds the agent-context window [10,50] (default 20); mirrors the backend
// validate_history_limit so the persisted pref and the server clamp always agree.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  clampContextMessages,
  CONTEXT_MESSAGES_MIN,
  CONTEXT_MESSAGES_MAX,
  CONTEXT_MESSAGES_DEFAULT,
} from '../src/stores/prefs.js'

test('constants are 10 / 50 / 20', () => {
  assert.equal(CONTEXT_MESSAGES_MIN, 10)
  assert.equal(CONTEXT_MESSAGES_MAX, 50)
  assert.equal(CONTEXT_MESSAGES_DEFAULT, 20)
})

test('accepts in-range values (10, 20, 50)', () => {
  assert.equal(clampContextMessages(10), 10)
  assert.equal(clampContextMessages(20), 20)
  assert.equal(clampContextMessages(50), 50)
})

test('clamps below 10 and above 50', () => {
  assert.equal(clampContextMessages(9), 10)
  assert.equal(clampContextMessages(0), 10)
  assert.equal(clampContextMessages(51), 50)
  assert.equal(clampContextMessages(9999), 50)
})

test('defaults to 20 on invalid input', () => {
  assert.equal(clampContextMessages('abc'), 20)
  assert.equal(clampContextMessages(null), 20)
  assert.equal(clampContextMessages(undefined), 20)
  assert.equal(clampContextMessages(NaN), 20)
})

test('accepts numeric strings and floors them', () => {
  assert.equal(clampContextMessages('30'), 30)
  assert.equal(clampContextMessages(33.7), 33)
})
