// Shared builders of the normalized run events (contract: agents/streaming.py +
// agents/stream_manager.py). The scripted scenarios AND the live LLM runner build
// their events through these helpers, so both modes emit byte-compatible shapes.

// One timeline step (an `agent_event` with an orchestrator label). `extra` carries
// eventKind and the optional correlation tags (agentKey, stepIndex, stepCount, status).
export function agentEvent(elapsedSeconds, label, extra) {
  return { type: 'agent_event', blockId: null, nextBlockId: null, toolName: null, elapsedSeconds, label, ...extra }
}

// A workspace operation factory with its own monotonic seq (one per run), relayed
// exactly as the backend does: {type:'workspace', v, op, seq, ts, ...payload}.
export function workspaceOps() {
  let seq = 0
  return (tsSeconds, op, payload) => ({ type: 'workspace', v: 1, op, seq: ++seq, ts: tsSeconds, ...payload })
}

// A generated_sql event (mandatory keys first, then the trust-layer tags, then the
// captured result; the poll strips `result` like the worker does).
export function generatedSqlEvent({ sqlIndex, success, rowCount, sql, sqlId, stepIndex, agentKey, result }) {
  const ev = { type: 'generated_sql', sqlIndex, success, rowCount, sql }
  if (sqlId != null) ev.sqlId = sqlId
  if (stepIndex != null) ev.stepIndex = stepIndex
  if (agentKey != null) ev.agentKey = agentKey
  if (result) ev.result = result
  return ev
}

export function usageSummaryEvent(promptTokens, completionTokens, estimatedCost) {
  return { type: 'usage_summary', promptTokens, completionTokens, totalTokens: promptTokens + completionTokens, estimatedCost }
}

// Split an answer into small deltas so the frontend streams like the real Mesh.
export function toDeltas(text, chunk = 24) {
  const out = []
  for (let i = 0; i < text.length; i += chunk) out.push(text.slice(i, i + chunk))
  return out
}
