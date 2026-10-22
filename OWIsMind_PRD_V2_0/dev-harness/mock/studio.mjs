// Studio continuity, mirror of the real backend (source of truth = the plugin):
//   - routes._sanitize_screen_context  -> studioPointer (screen_context.studio_exchange_id)
//   - stream_manager._resolve_studio_base -> resolveStudioBase (owner, SAME session,
//     not this exchange, not running, has widgets; else the newest ancestor of the
//     conversation with a workspace)
//   - agents/context.build_studio_block -> buildStudioBlock ([CURRENT STUDIO] + token)
//   - workspace/reducer.build_carry     -> buildCarry (studio.continue -> studio.carry,
//     SAME seq, relayed in place of the studio.continue)
// The base exchange id never reaches the agent: only the widget ids travel in the token.

export const EXCHANGE_ID_RE = /^[A-Za-z0-9_-]{1,128}$/
export const STUDIO_BLOCK_MAX_CHARS = 1800
export const STUDIO_TOKEN_MAX_CHARS = 600
const STUDIO_SCOPE_CHARS = 200
const TITLE_LADDER = [80, 40, 20]
const MAX_WIDGETS = 12
const MAX_CARRY_REMOVE = 12
const SLUG_RE = /^[a-z0-9_-]{1,32}$/
const HEADER = '\n\n[CURRENT STUDIO - the dashboard the user sees now, built earlier in THIS conversation from real queries]'

/** The validated studio_exchange_id of a /chat/start screen_context, or null. */
export function studioPointer(screenContext) {
  const raw = screenContext && typeof screenContext === 'object' ? screenContext.studio_exchange_id : null
  return typeof raw === 'string' && EXCHANGE_ID_RE.test(raw) ? raw : null
}

export const MAX_STUDIO_BASE_PROBES = 4

/**
 * The Studio a run may CONTINUE: { baseId, doc } or null.
 * Without a pointer, the newest ancestor whose workspace HAS widgets (at most
 * MAX_STUDIO_BASE_PROBES workspaces looked at): a widget-less one, e.g. an answer
 * that only stored its next steps, is skipped (port of _resolve_studio_base).
 * @param {object} o
 * @param {Map} o.exchanges        exchange_id -> { row, workspace }
 * @param {Array<string>} o.chain  the conversation's exchange ids, oldest first
 */
export function resolveStudioBase({ exchanges, chain, sessionId, exchangeId, pointer }) {
  const candidates = pointer
    ? [pointer]
    : [...(chain || [])].reverse().filter((id) => {
      const e = exchanges.get(id)
      return e && e.workspace
    }).slice(0, MAX_STUDIO_BASE_PROBES)
  for (const candidate of candidates) {
    if (candidate === exchangeId) return null
    const entry = exchanges.get(candidate)
    // Owner-scoped in the real backend: the harness has one user, so an unknown id
    // stands for someone else's exchange (reads as absent).
    if (!entry || !entry.workspace || !entry.row) return null
    if (entry.row.session_id !== sessionId) return null
    const doc = entry.workspace
    if (doc.status === 'running') return null
    if (Array.isArray(doc.widgets) && doc.widgets.length) return { baseId: candidate, doc }
    if (pointer) return null
  }
  return null
}

const PRIOR_GLYPHS = /[⟦⟧]/g
function cleanText(value, cap) {
  const s = String(value == null ? '' : value).slice(0, 4 * cap).replace(PRIOR_GLYPHS, '').replace(/"/g, "'")
  return s.split(/\s+/).filter(Boolean).join(' ').slice(0, cap)
}

function widgetPhrase(w, titleCap) {
  const kind = w.kind || '?'
  const parts = [w.id || '?', kind]
  if (kind === 'chart' && w.chart && w.chart.type) parts.push(String(w.chart.type))
  if (kind === 'text') parts.push(w.role || 'section')
  else if (w.size) parts.push(String(w.size))
  const title = titleCap ? cleanText(w.title, titleCap) : ''
  return parts.join(' ') + (title ? ` "${title}"` : '')
}

/** The visible [CURRENT STUDIO] block + the machine token, or '' (port of context.py). */
export function buildStudioBlock(doc) {
  const widgets = ((doc && doc.widgets) || []).filter((w) => w && typeof w.id === 'string').slice(0, MAX_WIDGETS)
  if (!widgets.length) return ''
  const scope = widgets.find((w) => w.kind === 'text' && w.role === 'scope')
  const scopeText = cleanText(scope && scope.text, STUDIO_SCOPE_CHARS)
  const used = widgets.length
  const head = HEADER + (scopeText ? '\nScope: ' + scopeText : '')
  const tail = `\nCapacity: ${used} of ${MAX_WIDGETS} used, ${Math.max(0, MAX_WIDGETS - used)} free.`
  let line = ''
  let visible = ''
  for (const cap of TITLE_LADDER) {
    line = '\nWidgets (board order): ' + widgets.map((w) => widgetPhrase(w, cap)).join(' | ')
    visible = head + line + tail
    if (visible.length <= STUDIO_BLOCK_MAX_CHARS) break
  }
  if (visible.length > STUDIO_BLOCK_MAX_CHARS) {
    const room = STUDIO_BLOCK_MAX_CHARS - head.length - tail.length - 3
    visible = head + line.slice(0, Math.max(0, room)) + '...' + tail
  }
  const ids = widgets.map((w) => w.id)
  const token = '⟦owi:studio=' + JSON.stringify({ ids, n: ids.length }) + '⟧'
  if (token.length > STUDIO_TOKEN_MAX_CHARS) return ''
  return visible + token
}

/** Widget ids of a [CURRENT STUDIO] token (port of the orchestrator's parse_studio). */
export function parseStudioIds(text) {
  const all = [...String(text || '').matchAll(/⟦owi:studio=([^⟧]*)⟧/g)]
  if (!all.length) return null
  try {
    const data = JSON.parse(all[all.length - 1][1])
    const ids = [...new Set((data.ids || []).filter((id) => typeof id === 'string' && SLUG_RE.test(id)))].slice(0, MAX_WIDGETS)
    return ids.length ? ids : null
  } catch {
    return null
  }
}

const DATA_KINDS = ['chart', 'table', 'kpi']

/**
 * studio.carry continuing `doc` of `baseId` (port of reducer.build_carry), same seq.
 * Only widgets travel: the base's `suggestions` (suggest.set) belong to its answer,
 * never to the board, so they are never carried.
 */
export function buildCarry(doc, baseId, seq, remove, ts) {
  if (!doc || !EXCHANGE_ID_RE.test(String(baseId || ''))) return null
  const dropped = new Set((Array.isArray(remove) ? remove : []).filter((id) => SLUG_RE.test(String(id))).slice(0, MAX_CARRY_REMOVE))
  const widgets = []
  for (const w of doc.widgets || []) {
    if (!w || dropped.has(w.id) || widgets.some((x) => x.id === w.id)) continue
    // The widget projection without step_id / ts (the base plan is not carried).
    const { step_id: _s, ts: _t, replaces: _r, origin, binding, ...rest } = w
    const out = { ...rest }
    if (DATA_KINDS.includes(w.kind)) out.binding = binding === 'orphan' ? 'orphan' : 'explicit'
    out.origin = typeof origin === 'string' && EXCHANGE_ID_RE.test(origin) ? origin : baseId
    widgets.push(out)
    if (widgets.length >= MAX_WIDGETS) break
  }
  const ev = { type: 'workspace', v: 1, op: 'studio.carry', seq, base_exchange_id: baseId, widgets }
  if (typeof ts === 'number') ev.ts = ts
  return ev
}

/**
 * The worker's live relay: wraps an `emit` so a studio.continue becomes the
 * studio.carry of the validated base (once per run); without a base it is relayed
 * unchanged (a reducer no-op).
 */
export function carryingEmit(emit, base) {
  let carried = false
  return (ev) => {
    if (base && !carried && ev && ev.type === 'workspace' && ev.op === 'studio.continue') {
      const carry = buildCarry(base.doc, base.baseId, ev.seq, ev.remove, ev.ts)
      if (carry) {
        carried = true
        return emit(carry)
      }
    }
    return emit(ev)
  }
}

/** Re-binds the run's own data widgets in place at run end; carried ones keep theirs (finalize). */
export function rebindWidgets(state, knownSqlIds) {
  for (const w of state.widgets || []) {
    if (w.kind === 'text' || w.origin) continue
    w.binding = knownSqlIds.has(w.sql_id) ? 'explicit' : 'orphan'
  }
  return state
}
