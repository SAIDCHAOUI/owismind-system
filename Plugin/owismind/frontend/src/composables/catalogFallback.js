// Pure state-machine deciding whether a "Request an agent" catalog picker (DSS
// projects, then SQL datasets of the chosen project) shows the LIVE list fed by the
// backend or falls back to manual text entry. No Vue / no I/O, so it stays
// unit-testable with node:test (NO INSTALL: no vitest - rule F11).
//
// Rule (design spec 2026-07-08, "Frontend > Onglet Demander un agent"): a catalog
// response that is either NOT ok ({ok:false}, e.g. no impersonation permission
// granted, or any server-side error) OR ok but empty (ok:true with a zero-length
// list, e.g. the user has no DSS projects / the project has no SQL dataset) means
// the backend could not resolve a usable list -> the form switches to manual entry
// automatically. A response that has not arrived yet (`response` is null/undefined -
// still loading, or the call was never made) stays LOADING: the state machine never
// guesses "manual" before an actual answer (ok or not) is known.

export const CATALOG_MODE = {
  LOADING: 'loading',
  CATALOG: 'catalog',
  MANUAL: 'manual',
}

// Generic resolver: `response` is the raw backend payload, `itemsKey` the property
// holding the list on a successful response (e.g. 'projects' or 'datasets').
export function catalogMode(response, itemsKey) {
  if (response == null) return CATALOG_MODE.LOADING
  if (!response.ok) return CATALOG_MODE.MANUAL
  const list = Array.isArray(response[itemsKey]) ? response[itemsKey] : []
  return list.length > 0 ? CATALOG_MODE.CATALOG : CATALOG_MODE.MANUAL
}

// GET /catalog/projects -> {ok:true, projects:[...]} | {ok:false, reason}.
export function projectCatalogMode(response) {
  return catalogMode(response, 'projects')
}

// GET /catalog/datasets -> {ok:true, datasets:[...]} | {ok:false, reason}.
export function datasetCatalogMode(response) {
  return catalogMode(response, 'datasets')
}
