// Workspace store (V2) - the right-column workspace of an answer: plan, journal,
// dashboard and provenance. One ENTRY per answer:
//   - a LIVE entry per running exchange (keyed by the exchange's stable client uid,
//     bound to the backend exchange id once /chat/start returns it), folded event by
//     event from /chat/poll through the pure reducer (composables/workspaceModel.js);
//   - a RESTORED entry per stored exchange, loaded from GET /workspace (rendered by the
//     SAME components and the same reducer, so "open the workspace" under an answer
//     shows the screen exactly as it was generated).
// The panel shows one entry at a time (`shownKey`). Every fetch is guarded by a
// sequence number so a stale response never overwrites a newer open/close (same idiom
// as the evidence store).
import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { fetchWorkspace } from '../services/backend.js'
import {
  emptyWorkspace,
  applyWorkspaceEvent,
  finalizeWorkspace,
  sanitizeWorkspace,
  reduceWorkspace,
  hasWorkspaceContent,
} from '../composables/workspaceModel.js'
import { capturedResult, widgetRenderData } from '../composables/widgetData.js'

export const WORKSPACE_TABS = Object.freeze(['plan', 'journal', 'board', 'data'])
// Restored documents kept in memory (re-opening one is instant); live entries are
// never evicted while their run is in flight.
const MAX_RESTORED = 20

function newEntry(key, exchangeId, live) {
  return reactive({
    key,
    exchangeId: exchangeId || null,
    live,
    running: live,
    state: emptyWorkspace(exchangeId),
    // ROWS BY SQL_ID, the single source every widget renders from (see sqlInfo): live
    // captures { sql, success, rowCount, agentKey, result } from ANY polled event that
    // carries a sqlId (generated_sql today, without rows: the worker keeps rows
    // persistence-only; a per-sql_id rows payload is planned for phase 2 and lands
    // here with no other change), merged with the server joins below.
    sqlById: {},
    // Server joins (restored / refreshed after the run): resolved[sql_id], widgets_data[widget_id]
    resolved: {},
    widgetsData: {},
    loading: false,
    // GET /workspace in flight after the run ended: widgets keep their waiting state.
    refreshing: false,
    error: '',
    // The user closed the panel during THIS run: no automatic re-open for it.
    dismissed: false,
  })
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const entries = reactive({}) // key -> entry
  const keyByExchange = reactive({}) // exchange id -> entry key
  const restoredOrder = [] // LRU of restored keys (eviction only)
  const shownKey = ref(null)
  const open = ref(false)
  const activeTab = ref('plan')
  // Provenance drawer: the sql_id it explains (null = closed) + the widget it opened from.
  const drawerSqlId = ref(null)
  const drawerWidgetId = ref(null)
  // "New" markers on the tabs that received content while another tab was shown.
  const fresh = reactive({ plan: false, journal: false, board: false })
  let seq = 0

  const shown = computed(() => (shownKey.value ? entries[shownKey.value] || null : null))
  const state = computed(() => (shown.value ? shown.value.state : null))
  const exchangeId = computed(() => (shown.value ? shown.value.exchangeId : null))

  function liveKey(uid) {
    return 'live:' + uid
  }

  // The entry of an exchange: by backend id first, then by the live client uid.
  function entryFor(exchangeIdOrNull, uid) {
    if (exchangeIdOrNull && keyByExchange[exchangeIdOrNull]) return entries[keyByExchange[exchangeIdOrNull]] || null
    if (uid && entries[liveKey(uid)]) return entries[liveKey(uid)]
    return null
  }

  /** True when an answer (by exchange id and/or live uid) has workspace content in memory. */
  function hasContent(exchangeIdOrNull, uid) {
    const e = entryFor(exchangeIdOrNull, uid)
    return !!(e && hasWorkspaceContent(e.state))
  }

  function markFresh(op) {
    const tab = op === 'note.add' ? 'journal' : op === 'widget.add' ? 'board' : op && op.indexOf('plan.') === 0 ? 'plan' : null
    if (tab && !(open.value && activeTab.value === tab)) fresh[tab] = true
  }

  function show(key, tab) {
    if (shownKey.value !== key) {
      drawerSqlId.value = null
      drawerWidgetId.value = null
      fresh.plan = false
      fresh.journal = false
      fresh.board = false
    }
    shownKey.value = key
    open.value = true
    if (tab) setTab(tab)
  }

  // --- live path (driven by the chat store) ---------------------------------------

  /** A run starts: create its live entry (no panel change yet). */
  function beginLive(uid) {
    const key = liveKey(uid)
    entries[key] = newEntry(key, null, true)
    return entries[key]
  }

  /** /chat/start returned the real exchange id of a live run. */
  function bindExchange(uid, exchangeIdValue) {
    const e = entries[liveKey(uid)]
    if (!e || !exchangeIdValue) return
    e.exchangeId = exchangeIdValue
    e.state.exchange_id = String(exchangeIdValue)
    keyByExchange[exchangeIdValue] = e.key
  }

  /**
   * One polled event of a live run. Workspace operations go through the reducer; a
   * generated_sql capture is kept by sql_id so widgets bound to it render live. The
   * FIRST plan opens the panel on the Plan tab (once per run, unless the user closed
   * it during this run).
   */
  function onLiveEvent(uid, evt) {
    const e = entries[liveKey(uid)]
    if (!e || !evt) return
    if (evt.type !== 'workspace') {
      // Any event tagged with a sql_id feeds the rows-by-sql_id map (one code path).
      const sid = evt.sqlId
      if (typeof sid === 'string' && sid && (evt.type === 'generated_sql' || evt.result)) {
        const prev = e.sqlById[sid] || {}
        e.sqlById[sid] = {
          sql: evt.sql != null ? evt.sql : prev.sql || null,
          success: evt.success != null ? evt.success : prev.success,
          rowCount: evt.rowCount != null ? evt.rowCount : prev.rowCount,
          agentKey: evt.agentKey || prev.agentKey || null,
          result: capturedResult(evt.result, evt.rowCount) || prev.result || null,
        }
      }
      return
    }
    // The reducer drops a replayed seq (re-delivered poll page) on its own.
    const hadPlan = !!e.state.plan
    if (!applyWorkspaceEvent(e.state, evt)) return
    markFresh(evt.op)
    if (!hadPlan && e.state.plan && !e.dismissed && !(open.value && shownKey.value === e.key)) {
      // Auto-open (like the Source Data dock's auto mode): no analytics event.
      show(e.key, 'plan')
    }
  }

  /**
   * The run ended (done / stopped / error). Seals the status; when the panel shows
   * this run and widgets exist, the dashboard takes over. Then the stored document is
   * fetched once (best effort) so the dashboard switches to the server-built payloads
   * and the resolved provenance (pretty SQL, filters, counts).
   */
  async function endLive(uid, status) {
    const e = entries[liveKey(uid)]
    if (!e || !e.running) return
    e.running = false
    // null status = a cancelled poll loop (the user left): the status stays unknown.
    if (status) finalizeWorkspace(e.state, status === 'running' ? 'done' : status)
    if (!hasWorkspaceContent(e.state)) return
    if (status && open.value && shownKey.value === e.key && e.state.widgets.length && activeTab.value !== 'data') {
      setTab('board')
    }
    if (e.exchangeId) await refresh(e)
  }

  // --- restore path ---------------------------------------------------------------

  // Merge one GET /workspace response into an entry (state re-projected: the frontend
  // never trusts a stored document blindly).
  function applyDocument(e, doc) {
    const events = Array.isArray(doc.events) ? doc.events : null
    const reduced = events
      ? reduceWorkspace(events, e.exchangeId)
      : sanitizeWorkspace(doc.workspace) || emptyWorkspace(e.exchangeId)
    if (events && doc.workspace && doc.workspace.status) finalizeWorkspace(reduced, doc.workspace.status)
    if (e.exchangeId) reduced.exchange_id = String(e.exchangeId)
    e.state = reactive(reduced)
    e.resolved = doc.resolved && typeof doc.resolved === 'object' ? doc.resolved : {}
    e.widgetsData = doc.widgets_data && typeof doc.widgets_data === 'object' ? doc.widgets_data : {}
  }

  async function refresh(e) {
    e.refreshing = true
    try {
      const doc = await fetchWorkspace(e.exchangeId)
      // A live run that restarted meanwhile owns its entry: only merge a sealed one.
      if (e.running) return
      // Keep the live state when the server has nothing yet (worker still persisting).
      if (doc && doc.workspace) applyDocument(e, doc)
    } catch (err) {
      /* best effort: the live state stays on screen */
    } finally {
      e.refreshing = false
    }
  }

  function rememberRestored(key) {
    const i = restoredOrder.indexOf(key)
    if (i >= 0) restoredOrder.splice(i, 1)
    restoredOrder.push(key)
    while (restoredOrder.length > MAX_RESTORED) {
      const old = restoredOrder.shift()
      if (old === shownKey.value) {
        restoredOrder.push(old)
        break
      }
      const e = entries[old]
      if (e && e.exchangeId && keyByExchange[e.exchangeId] === old) delete keyByExchange[e.exchangeId]
      delete entries[old]
    }
  }

  /**
   * Open the workspace of one exchange ("Open the workspace" under an answer, or the
   * conversation-entry continuity with `auto`). An in-memory entry (live or already
   * restored) shows instantly; otherwise GET /workspace. Resolves to true when the
   * workspace is shown, false when the exchange has none (the caller falls back to
   * the V1.3 Evidence panel) or the open was superseded.
   */
  async function openForExchange(id, opts) {
    if (!id) return false
    const tab = (opts && opts.tab) || null
    const uid = opts && opts.uid
    const existing = entryFor(id, uid)
    if (existing && (existing.live || hasWorkspaceContent(existing.state))) {
      ++seq
      if (existing.live && existing.exchangeId == null) bindExchange(uid, id)
      show(existing.key, tab || (existing.state.widgets.length ? 'board' : 'plan'))
      return true
    }
    const key = 'ex:' + id
    const e = entries[key] || newEntry(key, id, false)
    entries[key] = e
    keyByExchange[id] = key
    rememberRestored(key)
    const my = ++seq
    e.loading = true
    e.error = ''
    show(key, tab || 'board')
    try {
      const doc = await fetchWorkspace(id)
      if (my !== seq) return false
      applyDocument(e, doc || {})
      if (!tab && !e.state.widgets.length) setTab('plan')
      return true
    } catch (err) {
      if (my !== seq) return false
      e.error = (err && err.message) || 'workspace_unavailable'
      if (e.error === 'workspace_not_found') {
        // No workspace for this exchange (a V1.3 answer): close, the caller falls back.
        close()
        return false
      }
      return true
    } finally {
      if (my === seq) e.loading = false
    }
  }

  // --- panel ----------------------------------------------------------------------

  function setTab(tab) {
    if (!WORKSPACE_TABS.includes(tab)) return
    activeTab.value = tab
    if (tab in fresh) fresh[tab] = false
  }

  /** Close the panel. Closing during a live run is sticky for that run (no re-open). */
  function close() {
    ++seq
    if (shown.value && shown.value.running) shown.value.dismissed = true
    open.value = false
    drawerSqlId.value = null
    drawerWidgetId.value = null
  }

  function openProvenance(sqlId, widgetId) {
    if (!sqlId) return
    drawerSqlId.value = sqlId
    drawerWidgetId.value = widgetId || null
  }
  function closeProvenance() {
    drawerSqlId.value = null
    drawerWidgetId.value = null
  }

  // --- read helpers (shown entry) -------------------------------------------------------

  function firstCount(...values) {
    for (const v of values) if (typeof v === 'number' && Number.isFinite(v)) return v
    return null
  }

  /** Everything known about one sql_id of the shown workspace (server join wins). */
  function sqlInfo(sqlId) {
    const e = shown.value
    if (!e || !sqlId) return null
    const server = e.resolved[sqlId] || null
    const live = e.sqlById[sqlId] || null
    const prov = e.state.provenance[sqlId] || null
    if (!server && !live && !prov) return null
    // The server always sends a result block; {captured:false} means "no rows".
    const serverRows = server && server.result && server.result.captured ? server.result : null
    const result = serverRows || (live && live.result) || null
    return {
      sqlId,
      sql: (server && server.sql) || (live && live.sql) || null,
      filters: server && Array.isArray(server.filters) ? server.filters : [],
      result,
      sourceUrl: (server && server.source_url) || null,
      provenance: prov,
      rowCount: firstCount(
        prov && prov.row_count,
        server && server.row_count,
        server && server.result && server.result.row_count,
        result && result.row_count,
        live && live.rowCount,
      ),
    }
  }

  /** Render data of one widget of the shown workspace: { result, data, orphan }. */
  function widgetData(widget) {
    const e = shown.value
    if (!e || !widget) return { result: null, data: null, orphan: false, pending: false }
    const server = e.widgetsData[widget.id] || null
    if (widget.binding === 'orphan' || (server && server.reason === 'orphan')) {
      return { result: null, data: null, orphan: true, pending: false }
    }
    const info = widget.sql_id ? sqlInfo(widget.sql_id) : null
    // Tables take their rows from the result; only chart/kpi payloads come from the server.
    const serverData = widget.kind === 'chart' || widget.kind === 'kpi' ? server : null
    const out = widgetRenderData(widget, { serverData, result: info ? info.result : null })
    return { ...out, orphan: false, pending: !!(e.running || e.refreshing) }
  }

  return {
    entries,
    open,
    activeTab,
    fresh,
    drawerSqlId,
    drawerWidgetId,
    shown,
    state,
    exchangeId,
    entryFor,
    hasContent,
    beginLive,
    bindExchange,
    onLiveEvent,
    endLive,
    openForExchange,
    setTab,
    close,
    openProvenance,
    closeProvenance,
    sqlInfo,
    widgetData,
  }
})
