// Worker thread that executes the AGENTS' SQL on its own read-only copy of the
// synthetic DB. node:sqlite is synchronous: running model-written SQL here keeps a
// pathological query (cartesian join...) off the Vite server thread, and the pool
// terminates the worker when a statement exceeds its time budget.

import { parentPort } from 'node:worker_threads'
import { buildLiveDatasets } from './datasets.mjs'
import { openDatasetDb, runSelect } from './sqlite.mjs'

const db = openDatasetDb(buildLiveDatasets())
parentPort.postMessage({ ready: true })

parentPort.on('message', ({ id, sql, cap }) => {
  const started = Date.now()
  const out = runSelect(db, sql, cap)
  parentPort.postMessage({ id, ...out, duration_ms: Date.now() - started })
})
