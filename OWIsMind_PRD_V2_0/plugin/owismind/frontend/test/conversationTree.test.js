import { test } from 'node:test'
import assert from 'node:assert/strict'
import { buildActivePath, childrenOf } from '../src/stores/conversationTree.js'

// exchange = { id, parentId, createdAt }
const ex = (id, parentId, createdAt) => ({ id, parentId, createdAt })

test('linear conversation -> straight path, no siblings', () => {
  const xs = [ex('a', null, '1'), ex('b', 'a', '2'), ex('c', 'b', '3')]
  const path = buildActivePath(xs, {})
  assert.deepEqual(path.map((t) => t.exchange.id), ['a', 'b', 'c'])
  assert.deepEqual(path.map((t) => t.siblings.length), [1, 1, 1])
})

test('default active child is the latest by createdAt (latest branch)', () => {
  // turn b edited -> b2 (newer); b had child c (older branch), b2 has child d
  const xs = [ex('a', null, '1'), ex('b', 'a', '2'), ex('c', 'b', '3'), ex('b2', 'a', '4'), ex('d', 'b2', '5')]
  const path = buildActivePath(xs, {})
  assert.deepEqual(path.map((t) => t.exchange.id), ['a', 'b2', 'd'])           // latest branch
  assert.equal(path[1].siblings.length, 2)                                     // b, b2 are versions
  assert.equal(path[1].versionIdx, 1)                                          // b2 is active (idx 1, sorted by createdAt)
})

test('override selects an older sibling and re-walks below it', () => {
  const xs = [ex('a', null, '1'), ex('b', 'a', '2'), ex('c', 'b', '3'), ex('b2', 'a', '4'), ex('d', 'b2', '5')]
  const path = buildActivePath(xs, { a: 'b' })   // pick b at parent 'a'
  assert.deepEqual(path.map((t) => t.exchange.id), ['a', 'b', 'c'])
  assert.equal(path[1].versionIdx, 0)
})

test('a live leaf with null id ends the walk (no infinite loop)', () => {
  const xs = [ex('a', null, '1'), ex(null, 'a', '2')]
  const path = buildActivePath(xs, {})
  assert.equal(path.length, 2)
  assert.equal(path[1].exchange.id, null)
})

test('childrenOf root uses parentId null', () => {
  const xs = [ex('a', null, '1'), ex('b', null, '2')]
  assert.deepEqual(childrenOf(xs, null).map((e) => e.id), ['a', 'b'])
})
