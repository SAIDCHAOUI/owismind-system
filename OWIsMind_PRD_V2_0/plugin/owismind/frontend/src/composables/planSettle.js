// Plan display of a finished run (V2, PlanCard). The orchestrator only closes the
// steps still 'running' when a run ends (node_finish guard): a step that never
// started, typically the closing "synthesis" step, which no specialist call ever
// marks, would stay unchecked although the final answer IS that synthesis. Once a
// run has ended SUCCESSFULLY (status 'done'), the final answer concludes the plan:
// every step still 'todo' or 'running' is shown as 'done'. A failed step keeps its
// 'error'; a stopped, failed or still running run keeps its honest state as is.
// Pure and read-only (the stored workspace state is never mutated), so the live path
// and a reloaded conversation (same sealed status) render the same final plan.

const OPEN_STEP_STATUSES = new Set(['todo', 'running'])

/** True when a run ended successfully but its plan still holds open steps. */
export function planNeedsSettle(state) {
  if (!state || state.status !== 'done') return false
  const steps = (state.plan && Array.isArray(state.plan.steps) && state.plan.steps) || []
  return steps.some((s) => s && OPEN_STEP_STATUSES.has(s.status))
}

/**
 * The workspace state as the plan card shows it: unchanged (same object) unless
 * planNeedsSettle, else a shallow copy whose plan steps are closed as 'done' (a batch
 * step is filled up to its total). Feed the result to stepsWithProgress / planProgress.
 */
export function settlePlanState(state) {
  if (!planNeedsSettle(state)) return state
  const steps = state.plan.steps.map((s) => {
    if (!s || !OPEN_STEP_STATUSES.has(s.status)) return s
    const out = { ...s, status: 'done' }
    if (out.total != null) out.done = out.total
    return out
  })
  return { ...state, plan: { ...state.plan, steps } }
}
