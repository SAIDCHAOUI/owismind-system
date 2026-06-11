// Chat store — the active conversation as a TREE of exchanges, sending state, and the
// prompt draft. Wraps the validated transport (useChatStream) and the session store
// (selected agent, history).
//
// A conversation is a tree: each exchange stores its parent (parentId). The store keeps a
// flat `exchanges` list and derives the ACTIVE PATH (`turns`) via the pure tree walk
// (conversationTree.js): at each node it follows the override child if one is pinned, else
// the LATEST child by createdAt. Editing a prompt or regenerating creates a NEW SIBLING
// exchange (nothing is deleted) — the new sibling is the latest child, so it becomes the
// active branch automatically. Turn-level version arrows navigate siblings and re-walk the
// path below them (handled by setTurnVersion + buildActivePath).
//
// Shapes:
//   exchange: reactive({ id, parentId, userText, version, createdAt })
//             id is null while the run is live, reconciled to the backend exchange id on
//             /chat/start (onExchangeId). createdAt is a monotonic client stamp for live
//             ordering (history rows carry the server created_at).
//   version:  reactive(createAnswerState()) — the ordered display timeline + SQL/usage +
//             persisted feedback (see composables/timelineModel.js).
//   turn:     { exchange, siblings, versionIdx } — one row of the active path (turns).
import { defineStore } from 'pinia'
import { ref, reactive, computed } from 'vue'
import { useSessionStore } from './session.js'
import { useUiStore } from './ui.js'
import { runChatStream } from '../composables/useChatStream.js'
import { createAnswerState } from '../composables/timelineModel.js'
import { fetchConversation, stopChat } from '../services/backend.js'
import { buildActivePath } from './conversationTree.js'
import { useEvidenceStore } from './evidence.js'
import { lastEvidenceExchangeId } from '../composables/evidenceModel.js'

// One session id per conversation (the backend stores it; history is scoped by user).
function newSessionId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID()
  }
  return 'sess-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

// A reactive answer-version: the timeline reducer mutates it in place during a run.
function newVersion(over) {
  return reactive(createAnswerState(over))
}

export const useChatStore = defineStore('chat', () => {
  const session = useSessionStore()
  const ui = useUiStore()
  const evidence = useEvidenceStore()

  const activeSessionId = ref(newSessionId())
  const exchanges = ref([]) // [reactive({ id, parentId, userText, version, createdAt })]
  const overrides = ref({}) // parentKey -> chosen child exchange id (version navigation)
  const draft = ref('')
  const sending = ref(false)
  const errorMsg = ref('')
  // Lazy thread load (a conversation's messages are fetched only when it is opened).
  const threadLoading = ref(false)
  const threadError = ref('')

  // The active path through the tree (latest branch by default; overrides win per node).
  const turns = computed(() => buildActivePath(exchanges.value, overrides.value))

  // A monotonic client clock so freshly created exchanges sort AFTER prior ones (and after
  // history rows, whose createdAt is a server timestamp) — keeps the newest branch active.
  let _clock = 0
  function nextStamp() {
    return new Date().toISOString() + '#' + (++_clock)
  }

  // Cancellation token for the in-flight poll loop. Switching conversation or starting a
  // newer run cancels the previous loop so it stops polling a run nobody is watching.
  let activeToken = null
  // The in-flight run's server id, for an explicit USER stop (POST /chat/stop). Tracked
  // apart from the poll token because stopping does NOT cancel polling — we keep polling
  // so the worker's partial answer + terminal `stopped` event still render. `stopPending`
  // covers the race where the user hits stop before /chat/start has returned the run id.
  let activeRunId = null
  let stopPending = false
  function cancelActive() {
    if (activeToken) activeToken.cancelled = true
    activeToken = null
    activeRunId = null
    stopPending = false
  }

  const hasMessages = computed(() => turns.value.length > 0)
  // threadLoading/threadError matter here: after a failed or in-flight conversation
  // switch, `exchanges` still holds the PREVIOUS thread — a send would persist under
  // the NEW session id with a parent exchange from the OLD one (cross-conversation
  // corruption). No sends until the thread on screen is the active session's.
  const canSend = computed(
    () =>
      !sending.value &&
      !threadLoading.value &&
      !threadError.value &&
      !session.needsConfig &&
      session.hasAgents &&
      !!session.selectedAgentKey,
  )

  // /conversation rows -> exchange list (one per row). Each row's stored answer becomes a
  // done single-text-block version carrying its feedback (L031) and tree links. The live
  // timeline is NOT persisted, so the answer is rebuilt as a single text block.
  function rowToExchange(r) {
    const version = newVersion({
      timeline: r.assistant_text
        ? [{ id: 'txt-0', seq: 0, kind: 'text', text: r.assistant_text, open: false }]
        : [],
      sql: Array.isArray(r.generated_sql) ? r.generated_sql : [],
      status: 'done',
      exchangeId: r.exchange_id || null,
      feedbackRating: r.feedback_rating === 0 || r.feedback_rating === 1 ? r.feedback_rating : null,
      feedbackReasons: Array.isArray(r.feedback_reasons) ? r.feedback_reasons : [],
      feedbackComment: r.feedback_comment || '',
    })
    return reactive({
      // Stable render key, fixed at load. Loaded rows have a unique exchange_id; the
      // fallback covers the rare null (never used as the tree id, which stays exchange_id).
      uid: r.exchange_id || nextStamp(),
      id: r.exchange_id,
      parentId: r.parent_exchange_id || null,
      userText: r.user_text || '',
      version,
      createdAt: r.created_at || '',
    })
  }

  function newConversation() {
    cancelActive()
    evidence.close()
    activeSessionId.value = newSessionId()
    exchanges.value = []
    overrides.value = {}
    errorMsg.value = ''
    threadLoading.value = false // clear any spinner left over from an interrupted openSession fetch
    threadError.value = ''
    // Phase C — last-used agent for a fresh conversation. Guarded so Phase B runs without
    // Phase C (the session store doesn't define this method yet).
    if (typeof session.useDefaultAgent === 'function') session.useDefaultAgent()
  }

  // Evidence continuity: entering a conversation re-opens its proof panel on the
  // LAST sql-bearing exchange of the active branch. Same auto contract as the
  // end-of-run reveal: opens only when /evidence/meta confirms the interactive
  // view — never degraded, never an error surface. Fire-and-forget: a rapid
  // switch is safe (openSession→evidence.close() bumps the store's seq, which
  // invalidates an in-flight auto commit).
  function _autoOpenEvidence(sessionId) {
    if (activeSessionId.value !== sessionId) return
    const evidenceId = lastEvidenceExchangeId(turns.value)
    if (evidenceId) {
      Promise.resolve(evidence.openForExchange(evidenceId, { auto: true })).catch(() => {})
    }
  }

  // Route → store sync (ChatView's param watcher). Re-entering the conversation that
  // is ALREADY active with its thread in memory (e.g. coming back from Settings, or
  // the URL stamp of a started-as-new conversation) skips the refetch but re-runs
  // the evidence continuity (the panel closes on route leave). The loading/error
  // guards matter: after a FAILED or still-in-flight open, `exchanges` still holds
  // the PREVIOUS conversation's rows — skipping there would show the wrong thread,
  // so anything not cleanly in memory goes through a genuine openSession (which is
  // also the retry path). Bonus over the old always-refetch: a live run now
  // SURVIVES a Settings round-trip (no cancelActive on the way back).
  function ensureSession(sessionId) {
    if (
      sessionId === activeSessionId.value &&
      exchanges.value.length &&
      !threadLoading.value &&
      !threadError.value
    ) {
      // Not while a run is in flight: the end-of-run reveal owns the panel then —
      // racing it could commit the PREVIOUS exchange's proof over the new one.
      if (!sending.value) _autoOpenEvidence(sessionId)
      return
    }
    return openSession(sessionId)
  }

  // Open an existing conversation: lazily fetch ITS rows (on click / deep-link) and rebuild
  // the tree. A fetch failure surfaces via threadError (never throws).
  //
  // We deliberately DO NOT clear `exchanges` here: the current thread stays on screen
  // (under a centered loading overlay, ChatView) during the fetch and is replaced only when
  // the target conversation's rows arrive — no "new conversation" flash (mirror L031).
  async function openSession(sessionId) {
    cancelActive()
    evidence.close()
    activeSessionId.value = sessionId
    overrides.value = {}
    errorMsg.value = ''
    threadError.value = ''
    threadLoading.value = true
    try {
      const data = await fetchConversation(sessionId)
      if (activeSessionId.value !== sessionId) return // superseded by a newer open
      exchanges.value = (data.rows || []).map(rowToExchange)
      _autoOpenEvidence(sessionId)
      // Phase C — adopt this conversation's agent only AFTER the agent list is loaded (it
      // loads via init()/loadAgents on a separate, slower path: /me then /agents — 2 round
      // trips — while /conversation is a single one that can win the cold-path race, leaving
      // session.agents empty when adopt runs). ensureLoaded() is memoized + already in flight
      // from App mount, so .then runs adopt on the next microtask (warm path still adopts).
      // Re-guard the active session in case the user switched conversations meanwhile.
      const rows = data.rows || []
      const adopt = () => {
        if (activeSessionId.value === sessionId && typeof session.adoptAgentFromExchanges === 'function') {
          session.adoptAgentFromExchanges(rows)
        }
      }
      if (typeof session.ensureLoaded === 'function') session.ensureLoaded().then(adopt)
      else adopt()
    } catch (e) {
      if (activeSessionId.value !== sessionId) return
      threadError.value = (e && e.message) || 'history_unavailable'
    } finally {
      if (activeSessionId.value === sessionId) threadLoading.value = false
    }
  }

  // Create a new exchange under `parentId`, run the agent into its version, and reconcile
  // its real backend id (assigned by /chat/start). The new exchange is the latest child of
  // its parent -> active by default (we also clear any override at that parent so the fresh
  // branch stays selected). This is the single place an exchange is created + run.
  async function _runExchange(userText, parentId) {
    cancelActive()
    const version = newVersion()
    // `uid` is the stable render key, assigned once and NEVER changed. `id` starts null and
    // is reconciled to the backend exchange id (onExchangeId) — keying the v-for on `uid`
    // (not `id`) avoids a mid-stream remount/flicker when that reconciliation happens.
    const exch = reactive({ uid: nextStamp(), id: null, parentId: parentId || null, userText, version, createdAt: nextStamp() })
    exchanges.value.push(exch)
    // Keep the freshly created branch active: drop any override pinned at this parent.
    const parentKey = parentId || '__root__'
    if (overrides.value[parentKey] != null) {
      const next = { ...overrides.value }
      delete next[parentKey]
      overrides.value = next
    }
    // Sidebar bump data captured at RUN ENTRY: the finally below can run up to a
    // poll cycle AFTER a cancellation, when the store may already hold ANOTHER
    // conversation — reading store state there created phantom/retitled sidebar
    // entries. The run's own conversation is the right one to promote either way:
    // the backend worker persists its answer even when polling was cancelled.
    const runSessionId = activeSessionId.value
    const firstTurn = turns.value[0]
    const runTitle = (firstTurn && firstTurn.exchange.userText) || userText
    const token = { cancelled: false }
    activeToken = token
    errorMsg.value = ''
    sending.value = true
    try {
      await runChatStream({
        sessionId: activeSessionId.value,
        message: userText,
        agentKey: session.selectedAgentKey,
        historyLimit: ui.contextMessages,
        parentExchangeId: parentId || null,
        target: version,
        token,
        onExchangeId: (id) => { exch.id = id }, // reconcile temp (null) key -> real backend id
        onRunId: (runId) => {
          activeRunId = runId
          // Honour a stop the user pressed before /chat/start returned the run id (race).
          if (stopPending) { stopPending = false; stopChat(runId).catch(() => {}) }
        },
      })
      // Evidence Studio auto-open (premium reveal): a CLEANLY finished answer
      // that produced at least one successful SQL gets its proof panel opened
      // automatically. openForExchange({auto:true}) only opens when
      // /evidence/meta confirms the interactive view (whitelisted table +
      // parsed filters) — never a degraded auto-open. Not on stopped/error.
      if (!token.cancelled && version.status === 'done' && version.sql.some((q) => q && q.success)) {
        // Fire-and-forget: the reveal must never affect the send flow. The
        // store catches its own fetch errors; this guards the commit path too.
        Promise.resolve(evidence.openForExchange(exch.id, { auto: true })).catch(() => {})
      }
    } catch (e) {
      if (!token.cancelled) {
        version.status = 'error'
        version.error = (e && e.message) || 'inconnue'
        errorMsg.value = version.error
      }
    } finally {
      if (activeToken === token) {
        activeToken = null
        activeRunId = null
        stopPending = false
      }
      sending.value = false
      // Promote/insert the RUN's conversation at the top (data captured at entry —
      // never the store's CURRENT session, which may have changed since).
      session.bumpCurrentConversation({
        id: runSessionId,
        title: runTitle,
        lastAt: new Date().toISOString(),
      })
    }
  }

  // Send a follow-up: a child of the last turn (the bottom of the active path).
  function send(text) {
    const t = (text || '').trim()
    if (!t || !canSend.value) return
    const last = turns.value[turns.value.length - 1]
    return _runExchange(t, last ? last.exchange.id : null)
  }

  // Edit a prompt: a NEW SIBLING of the edited turn (same parent, new text). Nothing is
  // deleted — the old version stays reachable via the turn's version arrows.
  function editTurn(turn, newText) {
    const t = (newText || '').trim()
    if (!t || !canSend.value || !turn) return
    return _runExchange(t, turn.exchange.parentId)
  }

  // Regenerate a turn: a NEW SIBLING with the SAME prompt (a fresh branch / new version).
  function regenerateTurn(turn) {
    if (!canSend.value || !turn) return
    return _runExchange(turn.exchange.userText, turn.exchange.parentId)
  }

  // Pin a specific sibling (version) at a turn's parent, then re-walk the path below it.
  // Ignore a still-live sibling (id === null): a null override is ambiguous and the live
  // run is already the latest/active child anyway.
  function setTurnVersion(turn, idx) {
    if (!turn) return
    const sib = turn.siblings[idx]
    if (!sib || !sib.id) return
    overrides.value = { ...overrides.value, [turn.exchange.parentId || '__root__']: sib.id }
  }

  // Explicit user stop of the in-flight run (the ■ button). Best-effort: asks the backend
  // to cut the run short — it persists the PARTIAL answer and emits a terminal `stopped`
  // event the poll loop renders (partial + a discreet "generation stopped" marker). We
  // deliberately do NOT cancel the poll token: polling continues so the partial + marker
  // appear, then the loop ends on `done`. A `run_not_found` (race: run already finished) is
  // a benign no-op. If the run id isn't known yet (stop pressed before /chat/start
  // resolved), defer via `stopPending` (onRunId fires the stop as soon as the id arrives).
  function stopGeneration() {
    if (!sending.value) return
    if (activeRunId) stopChat(activeRunId).catch(() => {})
    else stopPending = true
  }

  return {
    activeSessionId,
    exchanges,
    turns,
    draft,
    sending,
    errorMsg,
    threadLoading,
    threadError,
    hasMessages,
    canSend,
    newConversation,
    ensureSession,
    openSession,
    send,
    editTurn,
    regenerateTurn,
    setTurnVersion,
    stopGeneration,
  }
})
