import { createApp } from 'vue'
import { createPinia } from 'pinia'

// Global style layer (order matters): tokens first, then base reset/keyframes.
import './styles/tokens.css'
import './styles/base.css'

import { i18n } from './i18n'
import { router } from './router'
import App from './App.vue'

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

// DEV-only: expose pinia for local visual validation (seeding a demo conversation
// without a backend). Tree-shaken out of production builds.
if (import.meta.env.DEV) {
  window.__pinia = pinia
}

app.mount('#app')
