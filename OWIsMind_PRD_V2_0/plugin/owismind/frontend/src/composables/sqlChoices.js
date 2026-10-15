// Multi-SQL Evidence (V2.0): the stored queries of ONE answer, as the choices of the
// Data / Evidence SQL selector. The server lists them in /evidence/meta `queries[]`
// (sql_id, step_index, agent_key, row_count, active, widgets bound to it); the
// workspace, when there is one, adds the step label and its provenance. Pure (no
// Vue), unit-tested with node:test.

function stepOf(wsState, stepId) {
  const steps = (wsState && wsState.plan && wsState.plan.steps) || []
  const i = steps.findIndex((s) => s.id === stepId)
  return i >= 0 ? { index: i + 1, label: steps[i].label } : null
}

/**
 * Selector choices: [{ sqlId, n, active, success, stepIndex, stepLabel, agentKey,
 * widgets: [title], rowCount }], in the server's query order (falling back to the
 * workspace's sql_ids when the server lists no sql_id, an older backend).
 * `activeSqlId` marks the active one when the server does not flag it.
 */
export function sqlChoices(meta, wsState, activeSqlId) {
  const queries = meta && Array.isArray(meta.queries) ? meta.queries : []
  const prov = (wsState && wsState.provenance) || {}
  const wsWidgets = (wsState && wsState.widgets) || []
  const seen = new Set()
  const out = []
  const add = (sqlId, q) => {
    if (typeof sqlId !== 'string' || !sqlId || seen.has(sqlId)) return
    seen.add(sqlId)
    const p = prov[sqlId] || null
    const step = p && p.step_id ? stepOf(wsState, p.step_id) : null
    const fromServer = q && Array.isArray(q.widgets) ? q.widgets.map((w) => w && w.title).filter(Boolean) : null
    const widgets = fromServer && fromServer.length ? fromServer : wsWidgets.filter((w) => w.sql_id === sqlId).map((w) => w.title)
    const rc = q && typeof q.row_count === 'number' ? q.row_count : p && typeof p.row_count === 'number' ? p.row_count : null
    out.push({
      sqlId,
      n: out.length + 1,
      active: q && typeof q.active === 'boolean' ? q.active : sqlId === activeSqlId,
      success: q ? q.success !== false : p ? p.success !== false : true,
      stepIndex: step ? step.index : q && typeof q.step_index === 'number' ? q.step_index : null,
      stepLabel: step ? step.label : null,
      agentKey: (q && q.agent_key) || (p && p.agent_key) || null,
      widgets,
      rowCount: rc,
    })
  }
  for (const q of queries) add(q && q.sql_id, q)
  if (!out.length && wsState && wsState.summary) {
    for (const sid of wsState.summary.sql_ids || []) add(sid, null)
  }
  // Exactly one active choice when the active id is known.
  if (activeSqlId && !out.some((c) => c.active)) {
    for (const c of out) c.active = c.sqlId === activeSqlId
  }
  return out
}
