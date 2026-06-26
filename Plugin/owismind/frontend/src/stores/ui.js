// UI store - the SINGLE source of truth for user preferences (theme, language,
// sidebar state, history window), replacing the maquette's window.STATE. Both the
// header (MainTop) and the Settings page read/write this store, so a change in one
// place is instantly reflected in the other. Every preference is persisted to
// localStorage with ONE key (no competing persistence systems): the language is
// applied + persisted through the i18n module (setLocale), and this store keeps a
// reactive mirror of it so the rest of the app has a uniform preferences API.
import { defineStore } from 'pinia'
import { ref } from 'vue'
import { setLocale, currentLocale } from '../i18n'
import { clampContextMessages, CONTEXT_MESSAGES_DEFAULT } from './prefs.js'

const THEME_KEY = 'owismind.theme'
const COLLAPSE_KEY = 'owismind.sidebarCollapsed'
const SIDEBAR_W_KEY = 'owi.sidebarW' // maquette key
const EVIDENCE_W_KEY = 'owi.evidenceW'
const CTXMSG_KEY = 'owismind.contextMessages'
const MODELMODE_KEY = 'owismind.modelMode'

// Model mode the chat sends with each turn. One model per mode (no escalation):
// smart = Gemini 3.1 Flash-Lite (the cheap, fast DEFAULT), pro = Gemini 3.5 Flash,
// claude = Claude Sonnet. The strong model is opt-in. The backend also defaults to smart.
export const MODEL_MODES = ['smart', 'pro', 'claude']
const MODELMODE_DEFAULT = 'smart'

// Sidebar width clamp (maquette default 260; keep a sane drag range).
const SIDEBAR_MIN = 200
const SIDEBAR_MAX = 420
const SIDEBAR_DEFAULT = 260
const EVIDENCE_DEFAULT = 480
const EVIDENCE_MIN = 360

function readNum(key, fallback) {
  try {
    const v = parseInt(localStorage.getItem(key), 10)
    return Number.isFinite(v) ? v : fallback
  } catch (e) {
    return fallback
  }
}
function readTheme() {
  try {
    const v = localStorage.getItem(THEME_KEY)
    if (v === 'light' || v === 'dark') return v
  } catch (e) {
    /* ignore */
  }
  return 'light' // faithful to the validated maquette default
}

export const useUiStore = defineStore('ui', () => {
  const theme = ref(readTheme())
  const sidebarCollapsed = ref((() => {
    try {
      return localStorage.getItem(COLLAPSE_KEY) === '1'
    } catch (e) {
      return false
    }
  })())
  const sidebarW = ref(clampSidebar(readNum(SIDEBAR_W_KEY, SIDEBAR_DEFAULT)))
  // Width of the Evidence Studio panel (the RIGHTMOST column when open).
  // Clamped on read too: a stale persisted width (e.g. saved on a wider
  // screen) must not brick the evidence layout on a smaller one.
  const evidenceW = ref(clampEvidence(readNum(EVIDENCE_W_KEY, EVIDENCE_DEFAULT)))
  // Language mirrors the active i18n locale (already detected from localStorage at
  // i18n setup). setLang below keeps the two in sync - this store never persists the
  // language itself (setLocale owns the 'owismind.lang' key) to avoid a second system.
  const lang = ref(currentLocale())
  // Agent-context window (count of most-recent MESSAGES sent to the agent), clamped
  // to [10, 50]. New localStorage key (CTXMSG_KEY); the previous conversation-count
  // key is orphaned and harmless (a fresh default is used on first read).
  const contextMessages = ref(
    clampContextMessages(readNum(CTXMSG_KEY, CONTEXT_MESSAGES_DEFAULT)),
  )
  // Model mode (smart / pro / claude) sent with each chat turn.
  const modelMode = ref((() => {
    try {
      const v = localStorage.getItem(MODELMODE_KEY)
      if (MODEL_MODES.includes(v)) return v
    } catch (e) {
      /* ignore */
    }
    return MODELMODE_DEFAULT
  })())

  function clampSidebar(px) {
    return Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, px))
  }
  function clampEvidence(px) {
    // Never let the evidence panel swallow the conversation: keep at least
    // ~520px for sidebar + chat so the thread (and the drag handle itself)
    // always stays usable.
    const max = Math.max(EVIDENCE_MIN, (window.innerWidth || 1280) - 520)
    return Math.min(max, Math.max(EVIDENCE_MIN, px))
  }
  function persist(key, val) {
    try {
      localStorage.setItem(key, String(val))
    } catch (e) {
      /* ignore */
    }
  }
  function applyTheme(t) {
    document.body.dataset.theme = t
  }

  // Apply the persisted theme immediately (idempotent with main.js pre-mount set).
  applyTheme(theme.value)

  function setTheme(t) {
    if (t !== 'light' && t !== 'dark') return
    theme.value = t
    persist(THEME_KEY, t)
    applyTheme(t)
  }
  function toggleTheme() {
    setTheme(theme.value === 'light' ? 'dark' : 'light')
  }
  // Language: setLocale validates the id, applies it to vue-i18n (so the whole UI
  // re-renders), persists it ('owismind.lang') and sets <html lang>. We then mirror the
  // resolved locale here as the reactive source of truth read by the header + Settings.
  function setLang(id) {
    setLocale(id)
    lang.value = currentLocale()
  }
  function setContextMessages(value) {
    const n = clampContextMessages(value)
    contextMessages.value = n
    persist(CTXMSG_KEY, n)
  }
  function setModelMode(m) {
    if (!MODEL_MODES.includes(m)) return
    modelMode.value = m
    persist(MODELMODE_KEY, m)
  }
  // `persistChoice: false` = an AUTOMATIC collapse (e.g. Evidence opening):
  // it must never overwrite the USER's stored preference - only an explicit
  // toggle decides what the next session starts with.
  function setSidebarCollapsed(v, persistChoice = true) {
    sidebarCollapsed.value = !!v
    if (persistChoice) persist(COLLAPSE_KEY, v ? '1' : '0')
  }
  function toggleSidebar() {
    setSidebarCollapsed(!sidebarCollapsed.value)
  }
  function setSidebarWidth(px) {
    sidebarW.value = clampSidebar(px)
    persist(SIDEBAR_W_KEY, sidebarW.value)
  }
  function setEvidenceWidth(px) {
    evidenceW.value = clampEvidence(px)
    persist(EVIDENCE_W_KEY, evidenceW.value)
  }

  return {
    theme,
    lang,
    contextMessages,
    modelMode,
    sidebarCollapsed,
    sidebarW,
    evidenceW,
    setTheme,
    toggleTheme,
    setLang,
    setContextMessages,
    setModelMode,
    setSidebarCollapsed,
    toggleSidebar,
    setSidebarWidth,
    setEvidenceWidth,
  }
})
