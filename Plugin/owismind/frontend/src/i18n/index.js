// vue-i18n setup — consolidates ALL UI strings (ported from the maquette's
// window.OWI_I18N via a one-off extraction → messages.json). The maquette's
// positional `{0}`/`{1}` placeholders map directly onto vue-i18n list
// interpolation: t('key', [arg0, arg1]).
//
// Extensibility (add a language): drop its id into langs.json + a locale block in
// messages.json, and add the field on any data {fr,en} object (see useTr).
import { createI18n } from 'vue-i18n'
import messages from './messages.json'
import langs from './langs.json'
import { timelineMessages } from '../registries/timelineSteps.js'
import { extraMessages } from './extra.js'

const STORAGE_KEY = 'owismind.lang' // same key the maquette used
export const AVAILABLE_LOCALES = langs
const SUPPORTED = langs.map((l) => l.id)

function detectLocale() {
  try {
    const v = localStorage.getItem(STORAGE_KEY)
    if (v && SUPPORTED.includes(v)) return v
  } catch (e) {
    /* localStorage may be unavailable */
  }
  const nav = (navigator.language || 'fr').slice(0, 2).toLowerCase()
  return SUPPORTED.includes(nav) ? nav : 'fr'
}

export const i18n = createI18n({
  legacy: false, // Composition API
  globalInjection: true, // $t in templates
  locale: detectLocale(),
  fallbackLocale: 'fr',
  messages,
  warnHtmlMessage: false, // a few keys carry trusted canned HTML (e.g. default.answer_html)
  missingWarn: false,
  fallbackWarn: false,
})

function htmlLangFor(id) {
  return (langs.find((l) => l.id === id) || langs[0]).htmlLang
}

// Merge domain-specific catalogs (kept out of the maquette extraction so it stays
// pristine, and added modularly): live-timeline eventKind labels + Phase-3 UI
// strings (honest empty states, "coming soon", registry fallbacks).
i18n.global.mergeLocaleMessage('fr', timelineMessages.fr)
i18n.global.mergeLocaleMessage('en', timelineMessages.en)
i18n.global.mergeLocaleMessage('fr', extraMessages.fr)
i18n.global.mergeLocaleMessage('en', extraMessages.en)

// Apply <html lang> at boot to match the active locale.
document.documentElement.lang = htmlLangFor(i18n.global.locale.value)

/** Switch locale, persist it, and update <html lang>. */
export function setLocale(id) {
  if (!SUPPORTED.includes(id)) return
  i18n.global.locale.value = id
  try {
    localStorage.setItem(STORAGE_KEY, id)
  } catch (e) {
    /* ignore */
  }
  document.documentElement.lang = htmlLangFor(id)
}

export function currentLocale() {
  return i18n.global.locale.value
}
