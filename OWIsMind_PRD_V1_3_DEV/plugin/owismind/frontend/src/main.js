import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Global style layer (order matters): tokens first, then base reset/keyframes.
import './styles/tokens.css'
import './styles/base.css'

import { i18n } from './i18n'
import { router } from './router'
import App from './App.vue'
import { track } from './services/track.js'

// Set the theme on <body> BEFORE mount to avoid a flash of unstyled tokens (the
// semantic tokens live under body[data-theme]). The ui store reconciles afterward.
document.body.dataset.theme = (() => {
  try {
    const v = localStorage.getItem('owismind.theme')
    return v === 'dark' || v === 'light' ? v : 'light'
  } catch (e) {
    return 'light'
  }
})()

const pinia = createPinia()
const app = createApp(App).use(pinia).use(i18n).use(router)

// Usage analytics: capture uncaught frontend errors (best-effort, model-limited to 10
// per session so a broken page cannot flood). The message is capped to 200 chars and no
// stack is sent. track() never throws, so these handlers can never worsen an error state.
function capMessage(msg) {
  const s = msg == null ? '' : String(msg)
  return s.length > 200 ? s.slice(0, 200) : s
}
window.addEventListener('error', (e) => {
  track('error_frontend', { message: capMessage(e && e.message), source: 'window' })
})
window.addEventListener('unhandledrejection', (e) => {
  const reason = e && e.reason
  const msg = reason && reason.message ? reason.message : reason
  track('error_frontend', { message: capMessage(msg), source: 'promise' })
})
app.config.errorHandler = (err, instance, info) => {
  track('error_frontend', { message: capMessage(err && err.message), source: 'vue' })
  // Preserve Vue's default surfacing (setting errorHandler suppresses it otherwise).
  // eslint-disable-next-line no-console
  console.error(err, info)
}

// DEV-only: expose pinia for local visual validation (seeding a demo conversation
// without a backend). Tree-shaken out of production builds.
if (import.meta.env.DEV) {
  window.__pinia = pinia
}

app.mount('#app')
