// Pure conversation-list helpers (no Vue). NO install: from frontend/ run node --test test/
import { test } from 'node:test'
import assert from 'node:assert/strict'
import { mergeConversations, upsertAndBump } from '../src/stores/conversationList.js'

test('mergeConversations appends new ids, dedupes existing (first wins)', () => {
  const a = [{ id: 's1', title: 'A', lastAt: '2026-06-09T10:00' }]
  const b = [
    { id: 's1', title: 'A2', lastAt: '2026-06-09T11:00' }, // dup id -> ignored
    { id: 's2', title: 'B', lastAt: '2026-06-09T09:00' },
  ]
  const out = mergeConversations(a, b)
  assert.deepEqual(out.map((c) => c.id), ['s1', 's2'])
  assert.equal(out[0].title, 'A') // existing kept, not overwritten by the page dup
})

test('upsertAndBump moves an existing conversation to the top with new fields', () => {
  const list = [
    { id: 's1', title: 'A', lastAt: '1' },
    { id: 's2', title: 'B', lastAt: '2' },
  ]
  const out = upsertAndBump(list, { id: 's2', title: 'B!', lastAt: '9' })
  assert.deepEqual(out.map((c) => c.id), ['s2', 's1'])
  assert.equal(out[0].title, 'B!')
  assert.equal(out.length, 2)
})

test('upsertAndBump inserts a brand-new conversation at the top', () => {
  const out = upsertAndBump([{ id: 's1', title: 'A', lastAt: '1' }], { id: 's3', title: 'New', lastAt: '9' })
  assert.deepEqual(out.map((c) => c.id), ['s3', 's1'])
})
