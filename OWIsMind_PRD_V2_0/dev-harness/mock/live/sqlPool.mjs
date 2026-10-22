// A single lazily-started SQL worker with a per-statement timeout. Queries are
// serialized (one statement at a time, bounded load); a statement over budget kills
// the worker, answers { ok:false, error:'statement_timeout' } and the next query
// starts a fresh worker.

import { Worker } from 'node:worker_threads'

const WORKER_URL = new URL('./sqlWorker.mjs', import.meta.url)

let current = null // { worker, ready, pending }
let seq = 0
let chain = Promise.resolve()

function start() {
  const worker = new Worker(WORKER_URL)
  const slot = { worker, pending: new Map(), ready: null }
  slot.ready = new Promise((resolve, reject) => {
    worker.once('message', (m) => (m && m.ready ? resolve() : reject(new Error('worker_not_ready'))))
    worker.once('error', reject)
  })
  worker.on('message', (m) => {
    const p = m && m.id != null ? slot.pending.get(m.id) : null
    if (!p) return
    slot.pending.delete(m.id)
    p(m)
  })
  worker.on('exit', () => {
    for (const p of slot.pending.values()) p({ ok: false, error: 'worker_exited' })
    slot.pending.clear()
    if (current === slot) current = null
  })
  return slot
}

function execOne(sql, cap, timeoutMs) {
  if (!current) current = start()
  const slot = current
  const id = ++seq
  return slot.ready.then(() => new Promise((resolve) => {
    const timer = setTimeout(() => {
      slot.pending.delete(id)
      if (current === slot) current = null
      slot.worker.terminate().catch(() => {})
      resolve({ ok: false, error: 'statement_timeout' })
    }, timeoutMs)
    slot.pending.set(id, (m) => {
      clearTimeout(timer)
      resolve(m)
    })
    slot.worker.postMessage({ id, sql, cap })
  }))
}

/** Run one agent SELECT (guarded inside the worker). Never rejects. */
export function runAgentSql(sql, { cap = 500, timeoutMs = 5000 } = {}) {
  const job = chain
    .then(() => execOne(sql, cap, timeoutMs))
    .catch((e) => ({ ok: false, error: String((e && e.message) || e) }))
  chain = job.then(() => {}, () => {})
  return job
}

export function stopSqlPool() {
  if (current) current.worker.terminate().catch(() => {})
  current = null
}
