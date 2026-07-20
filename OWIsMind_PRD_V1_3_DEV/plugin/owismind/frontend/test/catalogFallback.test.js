// catalogMode / projectCatalogMode / datasetCatalogMode: pure fallback state-machine
// for the "Request an agent" catalog pickers (project dropdown, then SQL dataset
// multi-select) - LOADING until a response arrives, MANUAL on a not-ok or empty
// response, CATALOG on a non-empty ok response.
import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  CATALOG_MODE,
  catalogMode,
  projectCatalogMode,
  datasetCatalogMode,
} from '../src/composables/catalogFallback.js'

test('no response yet (null/undefined) -> LOADING', () => {
  assert.equal(catalogMode(null, 'projects'), CATALOG_MODE.LOADING)
  assert.equal(catalogMode(undefined, 'projects'), CATALOG_MODE.LOADING)
})

test('ok:false -> MANUAL regardless of reason', () => {
  assert.equal(catalogMode({ ok: false }, 'projects'), CATALOG_MODE.MANUAL)
  assert.equal(catalogMode({ ok: false, reason: 'no_permission' }, 'projects'), CATALOG_MODE.MANUAL)
})

test('ok:true with an empty list -> MANUAL', () => {
  assert.equal(catalogMode({ ok: true, projects: [] }, 'projects'), CATALOG_MODE.MANUAL)
})

test('ok:true with a malformed (non-array) list -> MANUAL, never throws', () => {
  assert.equal(catalogMode({ ok: true, projects: null }, 'projects'), CATALOG_MODE.MANUAL)
  assert.equal(catalogMode({ ok: true }, 'projects'), CATALOG_MODE.MANUAL)
})

test('ok:true with a non-empty list -> CATALOG', () => {
  assert.equal(catalogMode({ ok: true, projects: [{ key: 'A', label: 'A' }] }, 'projects'), CATALOG_MODE.CATALOG)
})

test('projectCatalogMode reads the "projects" key', () => {
  assert.equal(projectCatalogMode({ ok: true, projects: [{ key: 'A' }] }), CATALOG_MODE.CATALOG)
  assert.equal(projectCatalogMode({ ok: true, projects: [] }), CATALOG_MODE.MANUAL)
  assert.equal(projectCatalogMode({ ok: false }), CATALOG_MODE.MANUAL)
  assert.equal(projectCatalogMode(null), CATALOG_MODE.LOADING)
})

test('datasetCatalogMode reads the "datasets" key', () => {
  assert.equal(
    datasetCatalogMode({ ok: true, datasets: [{ dataset: 'd', table: 't', connection: 'c' }] }),
    CATALOG_MODE.CATALOG,
  )
  assert.equal(datasetCatalogMode({ ok: true, datasets: [] }), CATALOG_MODE.MANUAL)
  assert.equal(datasetCatalogMode({ ok: false, reason: 'project_not_found' }), CATALOG_MODE.MANUAL)
  assert.equal(datasetCatalogMode(undefined), CATALOG_MODE.LOADING)
})
