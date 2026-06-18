<script setup>
// Top bar - contextual title on the left; quick theme + language controls on the
// right. Visual spec ported from `.main-top` / `.main-top-left|right` / `.top-action`
// (components.css). When the sidebar is collapsed it also exposes an expand button.
//
// NOTE: the maquette houses theme/language inside Settings; we surface quick
// controls here for V1 ergonomics. The canonical Settings page (Phase 3) keeps them too.
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../../stores/ui.js'
import { useSessionStore } from '../../stores/session.js'
import { AVAILABLE_LOCALES } from '../../i18n'
import { Icon, Menu } from '../ui'

const route = useRoute()
const { t, te } = useI18n()
const ui = useUiStore()
const session = useSessionStore()

const title = computed(() => {
  if (route.name === 'chat') {
    const sid = route.params.sessionId
    if (sid) {
      const c = session.conversations.find((x) => x.id === sid)
      return c ? c.title : t('sb.new_conversation')
    }
    return t('sb.new_conversation')
  }
  const k = route.meta.title
  if (!k) return ''
  return te(k) ? t(k) : k
})

const langItems = computed(() =>
  AVAILABLE_LOCALES.map((l) => ({ key: l.id, label: `${l.flag}  ${l.label}` })),
)
// Single source of truth: write + read the language through the ui store, so the
// header and the Settings page stay perfectly in sync (and persist identically).
function onLang(id) {
  ui.setLang(id)
}
const langShort = computed(() => {
  const l = AVAILABLE_LOCALES.find((x) => x.id === ui.lang)
  return l ? l.short : String(ui.lang || '').toUpperCase()
})
</script>

<template>
  <header class="main-top">
    <div class="main-top-left">
      <button
        v-if="ui.sidebarCollapsed"
        class="top-action"
        :title="t('sb.expand')"
        @click="ui.toggleSidebar()"
      >
        <Icon name="sidebar" />
      </button>
      <h1 class="main-top-title">{{ title }}</h1>
    </div>

    <div class="main-top-right">
      <button
        class="top-action"
        :title="ui.theme === 'light' ? t('set.theme.dark') : t('set.theme.light')"
        @click="ui.toggleTheme()"
      >
        <Icon :name="ui.theme === 'light' ? 'moon' : 'sun'" />
      </button>

      <Menu align="right" :items="langItems" @select="onLang">
        <template #trigger="{ toggle }">
          <button class="top-action top-action--lang" :title="t('sb.lang_short')" @click="toggle">
            <Icon name="globe" /><span class="lang-short">{{ langShort }}</span>
          </button>
        </template>
      </Menu>
    </div>
  </header>
</template>

<style scoped>
/* =========================================================================
   Top bar - Orange brand. Flat, 56px, bottom hairline.
   Left: sidebar expand (when collapsed) + contextual title.
   Right: theme toggle + language selector.
   Matches mockup .topbar / .icon-btn / .lang spec.
   ========================================================================= */
.main-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 22px;
  height: 56px;
  gap: 16px;
  flex-shrink: 0;
  background: var(--bg);
  border-bottom: 1px solid var(--border);
}
.main-top-left { display: flex; align-items: center; gap: 10px; min-width: 0; }
.main-top-right { display: flex; align-items: center; gap: 6px; margin-left: auto; }

/* Contextual title: modest weight in the topbar (the big H1 lives in the page body) */
.main-top-title {
  font-size: 15px;
  font-weight: 700;
  color: var(--text);
  margin: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-family: var(--font-sans);
}

/* Icon buttons: sidebar toggle + theme toggle - per mockup .icon-btn */
.top-action {
  width: 34px;
  height: 34px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text-2);
  /* sharp: no border-radius */
  transition: color var(--dur) var(--ease);
  flex-shrink: 0;
}
.top-action:hover { color: var(--text); }
.top-action:focus-visible { outline: 2px solid var(--orange); outline-offset: 1px; }
.top-action :deep(.ui-icon) { width: 18px; height: 18px; }

/* Language selector: globe + short code, weight 600 - per mockup .lang */
.top-action--lang {
  width: auto;
  padding: 0 6px;
  gap: 6px;
  font-size: 13px;
  font-weight: 600;
}
.top-action--lang :deep(.ui-icon) { width: 16px; height: 16px; }
.lang-short { letter-spacing: 0.02em; }

@media (prefers-reduced-motion: reduce) {
  .top-action { transition: none; }
}
</style>
