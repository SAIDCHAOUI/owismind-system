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
  workspaceSuggestions,
  suggestionItems,
  studioShouldOpen,
  studioCloseEffect,
  studioContextId,
  resultRef as refOf,
} from '../composables/workspaceModel.js'
import { capturedResult, widgetRenderData } from '../composables/widgetData.js'
import { nextPlanOpen } from '../composables/teaserModel.js'
import {
  emptyBoard,
  loadBoard,
  saveBoard,
  isEmptyBoard,
  mergeBoardOrder,
  moveRelative,
  moveWithinGroup,
  orderWidgets,
  boardWidgets,
  scopeWidget,
  layoutBoard,
  filterBoard,
  replaceInOrder,
  removeFromBoard,
} from '../composables/boardOrder.js'

// The Studio has two tabs: the dashboard (ALWAYS first, the default) and the data.
// The plan lives above the prompt (PlanCard), its notes under each step.
export const WORKSPACE_TABS = Object.freeze(['board', 'data'])
// Restored documents kept in memory (re-opening one is instant); live entries are
// never evicted while their run is in flight.
const MAX_RESTORED = 20

// Dashboard arrangement persistence (composables/boardOrder.js): the workspace
// contract has no order/layout field, so the user's order and expanded widgets are a
// browser preference per answer. Both accessors are best effort: no storage (private
// mode, tests) = the arrangement only lives in memory.
function boardStorage() {
  try {
    return typeof window !== 'undefined' && window.localStorage ? window.localStorage : null
  } catch (e) {
    return null
  }
}
// The DSS backend URL of this webapp names its project: two projects on one DSS host
// (DEV / PRD) never share arrangements even when their exchange ids collide.
function boardNamespace() {
  try {
    const fn = typeof window !== 'undefined' && window.getWebAppBackendUrl
    return typeof fn === 'function' ? String(fn('/')) : 'local'
  } catch (e) {
    return 'local'
  }
}
function readBoard(exchangeId) {
  return exchangeId == null ? emptyBoard() : loadBoard(boardStorage(), boardNamespace(), exchangeId)
}
function writeBoard(e) {
  if (e && e.exchangeId != null) saveBoard(boardStorage(), boardNamespace(), e.exchangeId, e.board)
}

// GET /workspace `origins` -> { exchangeId: { resolved, provenance, live } } (plain
// objects only: the frontend never trusts a served shape blindly).
function plainMap(v) {
  return v && typeof v === 'object' && !Array.isArray(v) ? v : {}
}
function originsFrom(raw) {
  const out = {}
  for (const [id, o] of Object.entries(plainMap(raw))) {
    if (!/^[A-Za-z0-9_-]{1,128}$/.test(id) || !o || typeof o !== 'object') continue
    out[id] = { resolved: plainMap(o.resolved), provenance: plainMap(o.provenance), live: {} }
  }
  return out
}

function newEntry(key, exchangeId, live, sessionId) {
  return reactive({
    key,
    // Conversation the live run belongs to (a deferred open never crosses conversations).
    sessionId: sessionId || null,
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
    // Results of CARRIED widgets (a continued Studio), by origin exchange id:
    // { resolved: {sql_id: entry}, provenance: {sql_id: entry}, live: {sql_id: capture} }.
    // A carried widget is always read from here, never from this exchange's maps.
    origins: {},
    loading: false,
    // GET /workspace in flight after the run ended: widgets keep their waiting state.
    refreshing: false,
    error: '',
    // The user closed the panel during THIS run: no automatic re-open for it.
    dismissed: false,
    // The Studio may still open by itself for this run (live entries only): disarmed
    // once it opened, re-armed by a programmatic close (route change, Source Data).
    autoOpen: live,
    // A live widget.add was accepted for this run (the run-end open is only the
    // fallback for runs whose widgets never reached the live path).
    liveWidget: false,
    // A widget arrived while another right panel the user opened was showing: the
    // Studio opens once that panel closes (see setOtherPanel).
    deferred: false,
    // The user's dashboard arrangement of this answer: { order: [widget ids],
    // expanded: { id: true } }, restored from the browser when the exchange is known.
    board: readBoard(exchangeId),
  })
}

export const useWorkspaceStore = defineStore('workspace', () => {
  const entries = reactive({}) // key -> entry
  const keyByExchange = reactive({}) // exchange id -> entry key
  const restoredOrder = [] // LRU of restored keys (eviction only)
  // Next steps of stored answers as served on the /conversation rows (exchange id ->
  // items, re-validated). Kept apart from the entries on purpose: a seeded answer has no
  // document in memory (its Studio, if any, is still fetched on demand), and a long
  // conversation must not push real restored documents out of the LRU.
  const seededSuggestions = reactive({})
  const shownKey = ref(null)
  const open = ref(false)
  const activeTab = ref('board')
  // Plan card above the prompt: unfolded while a run builds it, collapsed otherwise.
  const planOpen = ref(false)
  function planEvent(event) {
    planOpen.value = nextPlanOpen(planOpen.value, event)
  }
  // Provenance drawer: the sql_id it explains (null = closed) + the widget it opened from.
  const drawerSqlId = ref(null)
  const drawerWidgetId = ref(null)
  // Exchange that owns the drawer's result when it is a carried widget's (null = the
  // shown answer): a result is addressed by (origin, sql_id), never by sql_id alone.
  const drawerOrigin = ref(null)
  // "New" markers on the tabs that received content while another tab was shown.
  const fresh = reactive({ board: false })
  // Data tab focus: the ONE result (sql_id) the Data tab shows when opened from a
  // widget or the provenance drawer (null = the whole exchange's Evidence view).
  const dataSqlId = ref(null)
  const dataWidgetId = ref(null)
  const dataOrigin = ref(null)
  // Exchange whose workspace finished while the panel was not showing it: the teaser
  // carries the orange "new" signal until the user opens it.
  const unseenExchangeId = ref(null)
  // Dashboard of the SHOWN entry: the user's width overrides (id -> true wide / false
  // compact, kept per answer with the user's order, see entry.board; absent = the
  // default width of the widget's kind) and the ONE widget shown alone in the focus
  // overlay (null = none). `boardTracks` = column count of the board grid right now
  // (reported by BoardGrid from its width), used to keep rows free of holes.
  const expanded = computed(() => (shown.value ? shown.value.board.expanded : {}))
  const boardOrderIds = computed(() => (shown.value ? shown.value.board.order : []))
  const boardTracks = ref(4)
  const focusWidgetId = ref(null)
  // Screen context fed by AppLayout (setPanelContext): the auto-open never pre-empts a
  // right panel the USER opened (Source Data engaged, a standalone Evidence panel) and
  // never opens off the chat route (Settings, FAQ...): it is deferred instead.
  const otherPanel = ref(false)
  const offChat = ref(false)
  const currentSession = ref(null)
  let seq = 0

  const shown = computed(() => (shownKey.value ? entries[shownKey.value] || null : null))
  const state = computed(() => (shown.value ? shown.value.state : null))
  const exchangeId = computed(() => (shown.value ? shown.value.exchangeId : null))
  // Exchange whose Evidence the Data tab shows: the origin of a focused carried result,
  // else the shown answer.
  const dataExchangeId = computed(() => dataOrigin.value || exchangeId.value)

  /** The (exchange, sql_id) a widget of the shown Studio reads its result from. */
  function resultRef(widget) {
    return refOf(widget, exchangeId.value)
  }
  /** True when the Evidence panel of `id` belongs to the shown Studio (its Data tab). */
  function hostsEvidence(id) {
    return id != null && (id === exchangeId.value || id === dataExchangeId.value)
  }
  /** screen_context.studio_exchange_id: the sealed Studio on screen, else null. */
  function studioExchangeId() {
    const e = shown.value
    return studioContextId({ open: open.value, exchangeId: e && e.exchangeId, running: !!(e && e.running) })
  }

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

  /**
   * The next steps proposed under one answer (suggest.set, [] when none): live from the
   * op, restored from GET /workspace. Never part of the Studio.
   */
  function suggestionsFor(exchangeIdOrNull, uid) {
    const e = entryFor(exchangeIdOrNull, uid)
    const own = e ? workspaceSuggestions(e.state) : []
    if (own.length || exchangeIdOrNull == null) return own
    return seededSuggestions[exchangeIdOrNull] || []
  }

  /** Seed the next steps of one stored answer from its /conversation row. */
  function seedSuggestions(exchangeIdValue, items) {
    if (exchangeIdValue == null) return
    const valid = suggestionItems(items)
    if (valid.length) seededSuggestions[exchangeIdValue] = valid
    else delete seededSuggestions[exchangeIdValue]
  }

  /**
   * True when the answer's document is in memory, sealed and holds ONLY next steps (no
   * plan, note nor widget): its "Open the Studio" entry point is withdrawn, the Studio
   * never opens for it.
   */
  function suggestionsOnly(exchangeIdOrNull, uid) {
    const e = entryFor(exchangeIdOrNull, uid)
    return !!(e && !e.running && !e.loading && !hasWorkspaceContent(e.state) && workspaceSuggestions(e.state).length)
  }

  function markFresh(op) {
    if (op === 'widget.add' && !(open.value && activeTab.value === 'board')) fresh.board = true
  }

  function show(key, tab) {
    if (shownKey.value !== key) {
      drawerSqlId.value = null
      drawerWidgetId.value = null
      drawerOrigin.value = null
      dataSqlId.value = null
      dataWidgetId.value = null
      dataOrigin.value = null
      fresh.board = false
      // Whatever the Studio shows now (opened by the user or by itself), a deferred
      // auto-open must never replace it later.
      clearDeferred()
      focusWidgetId.value = null
    }
    shownKey.value = key
    open.value = true
    const shownEntry = entries[key]
    if (shownEntry && shownEntry.exchangeId && shownEntry.exchangeId === unseenExchangeId.value) unseenExchangeId.value = null
    if (tab) setTab(tab)
  }

  // --- live path (driven by the chat store) ---------------------------------------

  /** A run starts: create its live entry (no panel change yet). */
  function beginLive(uid, sessionId) {
    clearDeferred()
    const key = liveKey(uid)
    entries[key] = newEntry(key, null, true, sessionId)
    return entries[key]
  }

  /** /chat/start returned the real exchange id of a live run. */
  function bindExchange(uid, exchangeIdValue) {
    const e = entries[liveKey(uid)]
    if (!e || !exchangeIdValue) return
    e.exchangeId = exchangeIdValue
    e.state.exchange_id = String(exchangeIdValue)
    keyByExchange[exchangeIdValue] = e.key
    // An arrangement made before the id was known is saved now; otherwise a saved one
    // (the same answer re-attached) is restored.
    if (isEmptyBoard(e.board)) e.board = readBoard(exchangeIdValue)
    else writeBoard(e)
  }

  /**
   * One polled event of a live run. Workspace operations go through the reducer; a
   * generated_sql capture is kept by sql_id so widgets bound to it render live. The
   * first published widget opens the Studio on the dashboard (see autoOpen).
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
    const widgetsBefore = e.state.widgets.length
    const idsBefore = new Set(e.state.widgets.map((w) => w.id))
    const hadPlan = !!e.state.plan
    const hadBase = !!e.state.base_exchange_id
    if (!applyWorkspaceEvent(e.state, evt)) return
    if (evt.op === 'studio.carry' && !hadBase && e.state.base_exchange_id) adoptBase(e)
    else if (evt.op === 'widget.remove' && idsBefore.has(evt.id)) dropFromBoard(e, evt.id)
    else if (evt.op === 'widget.add' && evt.replaces && idsBefore.has(evt.replaces) && !e.state.widgets.some((w) => w.id === evt.replaces)) {
      replaceOnBoard(e, evt.replaces, evt.id)
    }
    markFresh(evt.op === 'studio.carry' ? 'widget.add' : evt.op)
    // A plan appears: the plan card above the prompt unfolds.
    if (!hadPlan && e.state.plan) planEvent('run_start')
    // The agent publishes a widget: the Studio opens by itself on the dashboard (first
    // widget of the run, or the next one after a programmatic close); later widgets
    // simply appear on the open board.
    if (e.state.widgets.length > widgetsBefore) {
      e.liveWidget = true
      autoOpen(e)
    }
  }

  // --- continued Studio (studio.carry, widget.remove, replaces) -----------------------

  // A continued run carried widgets of the base Studio: the new answer starts with the
  // base board (the user's order and widths of the carried widgets) and their data,
  // copied from the base entry in memory, else read ONCE from the stored base document.
  // The base entry itself is never touched (the old answer keeps its own snapshot).
  function adoptBase(e) {
    const baseId = e.state.base_exchange_id
    const carried = e.state.widgets.filter((w) => w.origin).map((w) => w.id)
    const base = entryFor(baseId)
    const baseBoard = base ? base.board : readBoard(baseId)
    const board = filterBoard(baseBoard, carried)
    if (!isEmptyBoard(board)) {
      // Widgets of this run that arrived before the carry keep their arrival place after it.
      board.order = mergeBoardOrder(board.order, [...board.order, ...e.board.order])
      e.board = { order: board.order, expanded: { ...board.expanded, ...e.board.expanded } }
      writeBoard(e)
    }
    if (base && hasWorkspaceContent(base.state)) {
      copyBaseData(e, baseId, carried, {
        widgetsData: base.widgetsData,
        resolved: base.resolved,
        provenance: base.state.provenance,
        live: base.sqlById,
        origins: base.origins,
      })
      return
    }
    // Not in memory (an answer opened from an older session): one owner-scoped read.
    fetchWorkspace(baseId)
      .then((doc) => {
        if (!doc || entries[e.key] !== e) return
        const served = sanitizeWorkspace(doc.workspace)
        copyBaseData(e, baseId, carried, {
          widgetsData: plainMap(doc.widgets_data),
          resolved: plainMap(doc.resolved),
          provenance: (served && served.provenance) || {},
          live: {},
          origins: originsFrom(doc.origins),
        })
      })
      .catch(() => {
        /* best effort: the carried widgets read the stored document at run end */
      })
  }

  // Data of the carried widgets: their server payloads (widgets_data, keyed by widget
  // id) and the results they read, filed under their origin exchange (flattened: a
  // widget carried twice still points at the exchange that owns its query). Anything
  // the entry already holds (the stored document arrived first) wins.
  function copyBaseData(e, baseId, carriedIds, src) {
    for (const id of carriedIds) {
      if (src.widgetsData[id] && !e.widgetsData[id]) e.widgetsData[id] = src.widgetsData[id]
    }
    const origins = { ...e.origins }
    for (const w of e.state.widgets) {
      if (!w.origin || origins[w.origin]) continue
      if (w.origin === baseId) {
        origins[baseId] = { resolved: src.resolved || {}, provenance: src.provenance || {}, live: src.live || {} }
      } else if (src.origins && src.origins[w.origin]) {
        origins[w.origin] = src.origins[w.origin]
      }
    }
    e.origins = origins
  }

  function dropFromBoard(e, widgetId) {
    e.board = removeFromBoard(e.board, widgetId)
    writeBoard(e)
  }
  function replaceOnBoard(e, oldId, newId) {
    const order = replaceInOrder(e.board.order, oldId, newId)
    if (order.join('\u0000') === e.board.order.join('\u0000')) return
    e.board = { order, expanded: { ...e.board.expanded } }
    writeBoard(e)
  }

  // Open the Studio by itself for a live entry when studioShouldOpen allows it (never
  // after the user closed it during the run). Disarms the entry once it is on screen.
  // While another user-opened panel shows, or off the chat route, the open is deferred
  // (the entry stays armed).
  function autoOpen(e) {
    const onScreen = open.value && shownKey.value === e.key
    const go = studioShouldOpen({ armed: e.autoOpen, dismissed: e.dismissed, onScreen, widgets: e.state.widgets.length })
    if (go && (otherPanel.value || offChat.value)) {
      e.deferred = true
      return false
    }
    e.deferred = false
    if (go) show(e.key, 'board')
    if (go || onScreen) e.autoOpen = false
    return go
  }

  /**
   * AppLayout reports the screen context: `otherPanel` = another right panel the user
   * opened is showing, `onChat` = the chat route is displayed, `sessionId` = the active
   * conversation. Once neither blocks, a Studio open deferred meanwhile (widgets
   * arrived) happens now, unless the Studio already shows something (an answer the
   * user opened) or the deferred run belongs to another conversation: then the
   * deferral is dropped.
   */
  function setPanelContext(ctx) {
    const c = ctx || {}
    otherPanel.value = !!c.otherPanel
    offChat.value = c.onChat === false
    if (c.sessionId !== undefined) currentSession.value = c.sessionId || null
    if (otherPanel.value || offChat.value) return
    for (const x of Object.values(entries)) {
      if (x.deferred && x.sessionId && currentSession.value && x.sessionId !== currentSession.value) x.deferred = false
    }
    const pending = Object.values(entries).find((x) => x.deferred)
    if (!pending) return
    if (open.value) clearDeferred()
    else autoOpen(pending)
  }
  /** Forget deferred opens (conversation switch, new run): never resurface an old run. */
  function clearDeferred() {
    for (const x of Object.values(entries)) x.deferred = false
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
    planEvent('run_end')
    // null status = a cancelled poll loop (the user left): the status stays unknown.
    if (!status) e.deferred = false
    if (status) finalizeWorkspace(e.state, status === 'running' ? 'done' : status)
    if (!hasWorkspaceContent(e.state)) return
    const onScreen = open.value && shownKey.value === e.key
    if (status && onScreen && e.state.widgets.length && activeTab.value !== 'data') {
      setTab('board')
    }
    if (status && !onScreen && e.exchangeId) unseenExchangeId.value = e.exchangeId
    const mySeq = seq
    if (e.exchangeId) await refresh(e)
    // No live widget event opened the Studio (event cap reached, replayed seq) but the
    // finished run holds widgets: open it once now. Skipped when the user (or a
    // navigation) opened / closed a panel meanwhile (seq) or another run started.
    const otherRun = Object.values(entries).some((x) => x !== e && x.running)
    if (status && !e.liveWidget && mySeq === seq && entries[e.key] === e && !otherRun) autoOpen(e)
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
    // The served origins win; results copied live from an in-memory base are kept for
    // an origin the server did not join (older backend).
    e.origins = { ...(e.origins || {}), ...originsFrom(doc.origins) }
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
    // A sealed answer known to hold only next steps has no Studio: never open it.
    if (suggestionsOnly(id, uid)) return false
    if (existing && (existing.live || hasWorkspaceContent(existing.state))) {
      ++seq
      if (existing.live && existing.exchangeId == null) bindExchange(uid, id)
      show(existing.key, tab || 'board')
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
      // The stored document holds only next steps (suggest.set): no Studio to show,
      // close the loading panel and let the caller fall back.
      if (!hasWorkspaceContent(e.state) && workspaceSuggestions(e.state).length) {
        e.loading = false
        close()
        return false
      }
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

  /**
   * Load the stored workspace of an exchange WITHOUT opening the Studio (conversation
   * entry: the plan card and the beacon need it, the panel is never imposed).
   */
  async function loadForExchange(id) {
    if (!id) return false
    const existing = entryFor(id)
    if (existing && hasWorkspaceContent(existing.state)) return true
    // Already in memory with only its next steps: nothing more to read.
    if (existing && suggestionsOnly(id)) return false
    const key = 'ex:' + id
    const e = entries[key] || newEntry(key, id, false)
    entries[key] = e
    keyByExchange[id] = key
    rememberRestored(key)
    e.loading = true
    try {
      applyDocument(e, (await fetchWorkspace(id)) || {})
      return hasWorkspaceContent(e.state)
    } catch (err) {
      e.error = (err && err.message) || 'workspace_unavailable'
      return false
    } finally {
      e.loading = false
    }
  }

  // --- panel ----------------------------------------------------------------------

  function setTab(tab) {
    if (!WORKSPACE_TABS.includes(tab)) return
    activeTab.value = tab
    if (tab in fresh) fresh[tab] = false
    // The focus overlay belongs to the dashboard.
    if (tab !== 'board') focusWidgetId.value = null
  }

  /**
   * Close the panel. Only an explicit user close (`{ byUser: true }`: the X, the sheet
   * backdrop) during a live run is sticky for that run (no re-open); a programmatic
   * close (route change, Source Data or another proof panel opening) re-arms the
   * auto-open so the next widget brings the Studio back (studioCloseEffect).
   */
  function close(opts) {
    ++seq
    // A close while the Studio is already closed (closing another panel, repeated
    // programmatic closes) never touches the run: `shown` survives a close.
    const e = open.value ? shown.value : null
    const effect = e ? studioCloseEffect({ running: e.running, byUser: !!(opts && opts.byUser) }) : null
    if (effect === 'dismiss') e.dismissed = true
    else if (effect === 'rearm') e.autoOpen = true
    open.value = false
    drawerSqlId.value = null
    drawerWidgetId.value = null
    drawerOrigin.value = null
    focusWidgetId.value = null
  }

  // --- dashboard enlargement (shown entry) ------------------------------------------

  function shownWidget(widgetId) {
    const e = shown.value
    return (e && widgetId && e.state.widgets.find((w) => w && w.id === widgetId)) || null
  }
  function shownWidgetIds() {
    const e = shown.value
    return e ? e.state.widgets.map((w) => w && w.id) : []
  }
  // Data shape of a widget for the automatic width (layoutBoard): column count of a
  // table, point count of a chart (unknown while its rows are on their way).
  function shapeOf(widget) {
    if (!widget || (widget.kind !== 'table' && widget.kind !== 'chart')) return null
    const r = widgetData(widget)
    if (widget.kind === 'table') return { columns: r.result && Array.isArray(r.result.columns) ? r.result.columns.length : null }
    return { points: r.data && Array.isArray(r.data.labels) ? r.data.labels.length : null }
  }
  // The analysis scope (Studio header) and the board widgets in the user's order.
  const scope = computed(() => (shown.value ? scopeWidget(shown.value.state.widgets) : null))
  const boardList = computed(() => (shown.value ? orderWidgets(boardWidgets(shown.value.state.widgets), shown.value.board.order) : []))
  // Span of every board widget for the active column count: { id: { span, wide, paired } }.
  const boardSpans = computed(() => {
    const e = shown.value
    const out = {}
    if (!e) return out
    for (const it of layoutBoard(boardList.value, { columns: boardTracks.value, overrides: e.board.expanded, shapeOf })) {
      out[it.id] = it
    }
    return out
  })
  /** Effective width of one widget: the user's choice, else the automatic layout. */
  function isExpanded(widgetId) {
    const it = widgetId ? boardSpans.value[widgetId] : null
    return !!(it && it.wide)
  }
  function setBoardTracks(n) {
    const v = Number(n)
    if (v >= 1 && v !== boardTracks.value) boardTracks.value = Math.floor(v)
  }
  function setBoard(e, order, expandedMap) {
    e.board = { order, expanded: expandedMap }
    writeBoard(e)
  }
  /**
   * Toggle one widget between its compact width and the wide one (the user's choice
   * is kept for this answer). The row packing (layoutBoard) keeps the board free of
   * holes whatever the choice, so the order never has to change.
   */
  function toggleExpand(widgetId) {
    const e = shown.value
    if (!e || !shownWidget(widgetId)) return
    const order = mergeBoardOrder(e.board.order, shownWidgetIds())
    setBoard(e, order, { ...e.board.expanded, [widgetId]: !isExpanded(widgetId) })
  }
  /** Drag and drop: `widgetId` placed right before / after `targetId`. */
  function moveWidget(widgetId, targetId, after) {
    const e = shown.value
    if (!e || !widgetId || !targetId) return false
    const order = mergeBoardOrder(e.board.order, shownWidgetIds())
    const next = moveRelative(order, widgetId, targetId, !!after)
    if (next.join('\u0000') === order.join('\u0000')) return false
    setBoard(e, next, { ...e.board.expanded })
    return true
  }
  /**
   * Keyboard move inside one visual group (`peerIds`, the ids of the same row/grid):
   * `delta` -1 / +1 one place, -Infinity / +Infinity first / last. Returns
   * { moved, index, count } for the screen-reader announcement.
   */
  function moveWidgetBy(widgetId, peerIds, delta) {
    const e = shown.value
    if (!e || !widgetId) return { moved: false, index: -1, count: 0 }
    const order = mergeBoardOrder(e.board.order, shownWidgetIds())
    const r = moveWithinGroup(order, widgetId, peerIds, delta)
    if (r.moved) setBoard(e, r.order, { ...e.board.expanded })
    return { moved: r.moved, index: r.index, count: r.count }
  }
  /** Show ONE widget alone in the focus overlay (null closes it). */
  function focusWidget(widgetId) {
    focusWidgetId.value = widgetId || null
  }
  function closeFocus() {
    focusWidgetId.value = null
  }

  // The exchange owning a result opened from `widgetId` (its origin when carried),
  // unless the caller names it. null = the shown answer.
  function originFor(widgetId, origin) {
    if (origin !== undefined) return origin || null
    const w = shownWidget(widgetId)
    return (w && w.origin) || null
  }

  /**
   * Open the Data tab focused on ONE result: a sql_id of the shown answer, or of
   * `origin` for a carried widget (derived from `widgetId` when omitted).
   */
  function openData(sqlId, widgetId, origin) {
    dataSqlId.value = sqlId || null
    dataWidgetId.value = sqlId ? widgetId || null : null
    dataOrigin.value = sqlId ? originFor(widgetId, origin) : null
    drawerSqlId.value = null
    drawerWidgetId.value = null
    drawerOrigin.value = null
    setTab('data')
  }
  /** Leave the focused result: the Data tab shows the exchange's whole Evidence view. */
  function clearDataFocus() {
    dataSqlId.value = null
    dataWidgetId.value = null
    dataOrigin.value = null
  }

  function openProvenance(sqlId, widgetId, origin) {
    if (!sqlId) return
    drawerSqlId.value = sqlId
    drawerWidgetId.value = widgetId || null
    drawerOrigin.value = originFor(widgetId, origin)
  }
  function closeProvenance() {
    drawerSqlId.value = null
    drawerWidgetId.value = null
    drawerOrigin.value = null
  }

  // --- read helpers (shown entry) -------------------------------------------------------

  function firstCount(...values) {
    for (const v of values) if (typeof v === 'number' && Number.isFinite(v)) return v
    return null
  }

  // The result maps of one exchange as seen from the shown entry: its own (server
  // joins, live captures, provenance) or those of the origin of carried widgets.
  function sourcesOf(e, origin) {
    if (!origin || origin === e.exchangeId) return { resolved: e.resolved, live: e.sqlById, provenance: e.state.provenance }
    const o = (e.origins && e.origins[origin]) || {}
    return { resolved: o.resolved || {}, live: o.live || {}, provenance: o.provenance || {} }
  }

  /**
   * Everything known about one result of the shown workspace (server join wins):
   * `sqlId` of the shown answer, or of `origin` for a carried widget. `exchangeId` is
   * the exchange owning the query (the one its rows / Evidence are read from).
   */
  function sqlInfo(sqlId, origin) {
    const e = shown.value
    if (!e || !sqlId) return null
    const from = origin && origin !== e.exchangeId ? origin : null
    const src = sourcesOf(e, from)
    const server = src.resolved[sqlId] || null
    const live = src.live[sqlId] || null
    const prov = src.provenance[sqlId] || null
    if (!server && !live && !prov) return null
    // The server always sends a result block; {captured:false} means "no rows".
    const serverRows = server && server.result && server.result.captured ? server.result : null
    const result = serverRows || (live && live.result) || null
    return {
      sqlId,
      origin: from,
      exchangeId: from || (e.exchangeId != null ? String(e.exchangeId) : null),
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
    const info = widget.sql_id ? sqlInfo(widget.sql_id, widget.origin) : null
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
    drawerOrigin,
    dataSqlId,
    dataWidgetId,
    dataOrigin,
    dataExchangeId,
    resultRef,
    hostsEvidence,
    studioExchangeId,
    unseenExchangeId,
    expanded,
    boardOrderIds,
    boardTracks,
    scope,
    boardList,
    boardSpans,
    setBoardTracks,
    focusWidgetId,
    isExpanded,
    toggleExpand,
    moveWidget,
    moveWidgetBy,
    focusWidget,
    closeFocus,
    setPanelContext,
    clearDeferred,
    openData,
    clearDataFocus,
    shown,
    state,
    exchangeId,
    entryFor,
    hasContent,
    suggestionsFor,
    suggestionsOnly,
    seedSuggestions,
    beginLive,
    bindExchange,
    onLiveEvent,
    endLive,
    openForExchange,
    loadForExchange,
    planOpen,
    planEvent,
    setTab,
    close,
    openProvenance,
    closeProvenance,
    sqlInfo,
    widgetData,
  }
})
