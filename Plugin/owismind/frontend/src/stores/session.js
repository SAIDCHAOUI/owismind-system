// Session store - identity, the enabled-agents picker list, and the paginated
// conversation list (names only). Wraps the validated backend client
// (services/backend.js) without changing it. All network calls degrade gracefully
// (e.g. outside DSS, where getWebAppBackendUrl is absent) so the shell always renders.
import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { fetchMe, fetchConversations, fetchAgents, fetchUsage } from '../services/backend.js'
import { mergeConversations, upsertAndBump } from './conversationList.js'
import { pickDefaultAgent } from './agentPick.js'

// localStorage key for the last agent the user explicitly selected. Persisting it lets a
// FRESH conversation default to that agent (instead of always the first in the list).
const LAST_AGENT_KEY = 'owismind.lastAgentKey'
function readLastAgent() {
  try {
    return localStorage.getItem(LAST_AGENT_KEY) || ''
  } catch (e) {
    return ''
  }
}
function persistLastAgent(key) {
  try {
    localStorage.setItem(LAST_AGENT_KEY, key)
  } catch (e) {
    /* localStorage unavailable (private mode / no DOM) - preference is best-effort. */
  }
}

export const useSessionStore = defineStore('session', () => {
  const user = ref(null) // { user_id, groups }
  const isAdmin = ref(false)
  const needsConfig = ref(false)
  const agents = ref([]) // [{ key, label }] from /agents
  const selectedAgentKey = ref('')
  const loading = ref(false)
  const error = ref('')

  // Monthly budget status (from /usage): spend, effective limit + source, remaining,
  // reset date, lifetime counters, and whether enforcement is on / the user is blocked.
  // null until loaded (or when storage is unconfigured / the read fails).
  const usage = ref(null)

  // Paginated conversation list (names only) - the sidebar fills + infinite-scrolls it.
  const conversations = ref([]) // [{ id, title, lastAt }]
  const convCursor = ref(null)
  const convHasMore = ref(true)
  const convLoading = ref(false)
  const convError = ref('')

  let _initPromise = null

  const hasAgents = computed(() => agents.value.length > 0)
  // The user has hit their monthly credit AND enforcement is on -> sends are paused.
  // A null/unenforced/under-limit status leaves sending fully enabled.
  const budgetBlocked = computed(
    () => !!usage.value && usage.value.enforced !== false && !!usage.value.blocked,
  )
  const displayName = computed(() => {
    const u = user.value
    if (!u) return ''
    return u.display_name || u.user_id || ''
  })
  const initials = computed(() => {
    const n = displayName.value.trim()
    if (!n) return '?'
    const parts = n.split(/[.\s_-]+/).filter(Boolean)
    const s = (parts[0]?.[0] || '') + (parts[1]?.[0] || '')
    return (s || n[0]).toUpperCase()
  })

  async function loadMe() {
    try {
      const me = await fetchMe()
      user.value = { user_id: me.user_id, groups: me.groups || [], display_name: me.display_name }
      isAdmin.value = !!me.is_admin
      needsConfig.value = !!me.needs_config
    } catch (e) {
      user.value = null
      isAdmin.value = false
    }
  }

  // Monthly budget status. Best-effort: a failure leaves `usage` as-is (the profile shows
  // a neutral state, the chat banner stays hidden, the server-side gate is still the real
  // enforcement). Refreshed on init and after each completed run (so the banner appears
  // as soon as the user crosses their limit).
  async function loadUsage() {
    try {
      const data = await fetchUsage()
      usage.value = data.usage || null
    } catch (e) {
      /* keep the last known status; the backend gate remains authoritative. */
    }
  }

  async function loadAgents() {
    try {
      const data = await fetchAgents()
      agents.value = data.agents || []
      // Default the picker to the last-used agent (if still enabled), else the first one.
      if (agents.value.length && !selectedAgentKey.value) {
        selectedAgentKey.value = pickDefaultAgent(agents.value, readLastAgent())
      }
    } catch (e) {
      agents.value = []
    }
  }

  // Map server rows ({ session_id, title, last_at }) to the sidebar item shape.
  function _toItems(rows) {
    return rows.map((r) => ({ id: r.session_id, title: r.title || '', lastAt: r.last_at }))
  }

  // First page of conversations (names only). `count` (optional) is the page size the
  // Sidebar derives from its viewport height; omitting it uses the backend default.
  // On startup BOTH init() and the Sidebar trigger this - a shared in-flight promise
  // de-dupes them into a single /conversations request (the second caller awaits the
  // first), so the list is never fetched twice per load.
  let _firstConvPromise = null
  async function loadFirstConversations(count) {
    if (_firstConvPromise) return _firstConvPromise
    _firstConvPromise = (async () => {
      convLoading.value = true
      convError.value = ''
      try {
        const data = await fetchConversations(null, count)
        conversations.value = _toItems(data.conversations || [])
        convCursor.value = data.next_cursor || null
        convHasMore.value = !!data.has_more
      } catch (e) {
        conversations.value = []
        convHasMore.value = false
        convError.value = (e && e.message) || 'history_unavailable'
      } finally {
        convLoading.value = false
        _firstConvPromise = null
      }
    })()
    return _firstConvPromise
  }

  // Next page (infinite scroll). Guarded against concurrent / no-more loads.
  async function loadMoreConversations() {
    if (convLoading.value || !convHasMore.value) return
    convLoading.value = true
    try {
      const data = await fetchConversations(convCursor.value, undefined)
      conversations.value = mergeConversations(conversations.value, _toItems(data.conversations || []))
      convCursor.value = data.next_cursor || null
      convHasMore.value = !!data.has_more
    } catch (e) {
      convError.value = (e && e.message) || 'history_unavailable'
      convHasMore.value = false
    } finally {
      convLoading.value = false
    }
  }

  // After a send: insert/bump the active conversation to the top of the list.
  function bumpCurrentConversation(item) {
    conversations.value = upsertAndBump(conversations.value, item)
  }

  // Load everything once (identity first; agents + first page only when configured).
  async function init() {
    loading.value = true
    error.value = ''
    await loadMe()
    if (!needsConfig.value) {
      await Promise.all([loadAgents(), loadFirstConversations(), loadUsage()])
    }
    loading.value = false
  }

  // Memoized init - safe to call from multiple places (router guard, App mount).
  function ensureLoaded() {
    if (!_initPromise) _initPromise = init()
    return _initPromise
  }

  // User-driven selection (the picker): persist it so a fresh conversation defaults to it.
  function selectAgent(key) {
    selectedAgentKey.value = key
    if (key) persistLastAgent(key)
  }

  // Pick the default agent for a fresh conversation: the last-used one if still enabled,
  // else the first. Used by chat.newConversation().
  function useDefaultAgent() {
    selectedAgentKey.value = pickDefaultAgent(agents.value, readLastAgent())
  }

  // Per-conversation agent: when opening an existing conversation, adopt the agent of its
  // NEWEST exchange (if still enabled). Falls back to the last-used default otherwise.
  // Does not persist - opening history must not change the user's last-used default.
  function adoptAgentFromExchanges(rows) {
    const list = rows || []
    for (let i = list.length - 1; i >= 0; i--) {
      const k = list[i] && list[i].agent_key
      if (k && agents.value.some((a) => a.key === k)) {
        selectedAgentKey.value = k
        return
      }
    }
    useDefaultAgent()
  }

  return {
    user,
    isAdmin,
    needsConfig,
    agents,
    selectedAgentKey,
    loading,
    error,
    usage,
    budgetBlocked,
    conversations,
    convCursor,
    convHasMore,
    convLoading,
    convError,
    hasAgents,
    displayName,
    initials,
    loadMe,
    loadUsage,
    loadAgents,
    loadFirstConversations,
    loadMoreConversations,
    bumpCurrentConversation,
    init,
    ensureLoaded,
    selectAgent,
    useDefaultAgent,
    adoptAgentFromExchanges,
  }
})
