<script setup>
// AuthGate - the single full-screen screen shown when /me returns a definitive 401
// (the caller is not signed in to DSS). It is the ONLY thing App.vue renders in that
// state: there is no navigation, no shell, no internal URL. Orange charter throughout
// (real logo image, eyebrow + heavy H1 + orange title-bar, square geometry, flat
// surfaces). It keeps a language toggle (EN/FR) and a theme toggle so the user can
// read the message in their own language / contrast before reloading.
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../../stores/ui.js'
import { Icon } from '../ui'
import logoUrl from '../../assets/orange-logo.png'

const { t } = useI18n()
const ui = useUiStore()

function reload() {
  // F5 equivalent: once the user has signed in to DSS, a reload re-runs /me.
  location.reload()
}
</script>

<template>
  <div class="gate">
    <!-- Top bar: only the brand and the two preference toggles (no nav). -->
    <header class="gate-bar">
      <img :src="logoUrl" class="gate-logo" alt="Orange" />
      <div class="gate-prefs">
        <!-- Language toggle: two explicit segments, the active one filled. -->
        <div class="gate-lang" role="group" :aria-label="t('authgate.lang')">
          <button
            type="button"
            class="gate-lang__seg"
            :class="{ 'is-active': ui.lang === 'en' }"
            :aria-pressed="ui.lang === 'en'"
            @click="ui.setLang('en')"
          >
            EN
          </button>
          <button
            type="button"
            class="gate-lang__seg"
            :class="{ 'is-active': ui.lang === 'fr' }"
            :aria-pressed="ui.lang === 'fr'"
            @click="ui.setLang('fr')"
          >
            FR
          </button>
        </div>
        <button
          type="button"
          class="gate-icon-btn"
          :title="ui.theme === 'light' ? t('authgate.theme_dark') : t('authgate.theme_light')"
          :aria-label="ui.theme === 'light' ? t('authgate.theme_dark') : t('authgate.theme_light')"
          @click="ui.toggleTheme()"
        >
          <Icon :name="ui.theme === 'light' ? 'moon' : 'sun'" :size="18" />
        </button>
      </div>
    </header>

    <!-- Centered editorial card. -->
    <main class="gate-main">
      <section class="gate-card u-rise">
        <p class="gate-eyebrow">{{ t('authgate.eyebrow') }}</p>
        <h1 class="gate-title">{{ t('authgate.title') }}</h1>
        <div class="gate-titlebar" aria-hidden="true"></div>
        <p class="gate-body">{{ t('authgate.body') }}</p>
        <div class="gate-actions">
          <button type="button" class="gate-btn gate-btn--primary" @click="reload">
            <Icon name="refresh" :size="15" />
            <span>{{ t('authgate.reload') }}</span>
          </button>
        </div>
      </section>
    </main>
  </div>
</template>

<style scoped>
/* Full viewport, theme background, flat - no gradient/blur/glow (charter). */
.gate {
  position: fixed;
  inset: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg);
  color: var(--text);
  font-family: var(--font-sans);
}

/* Top bar: brand left, preference toggles right. 1px bottom hairline. */
.gate-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  padding: var(--s-4) var(--s-6);
  border-bottom: 1px solid var(--border);
}
/* Real brand image, never a CSS square (charter / L092). */
.gate-logo {
  height: 28px;
  width: auto;
  display: block;
}
.gate-prefs {
  display: flex;
  align-items: center;
  gap: var(--s-3);
}

/* Language toggle: square segmented control, active segment inverted. */
.gate-lang {
  display: inline-flex;
  border: 1px solid var(--border-strong);
  border-radius: 0;
}
.gate-lang__seg {
  padding: 6px 12px;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  font-family: inherit;
  letter-spacing: 0.04em;
  color: var(--text-2);
  background: transparent;
  border: 0;
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.gate-lang__seg + .gate-lang__seg {
  border-left: 1px solid var(--border-strong);
}
.gate-lang__seg:hover:not(.is-active) {
  color: var(--text);
}
.gate-lang__seg.is-active {
  background: var(--text);
  color: var(--bg);
}

/* Square icon button (theme toggle). */
.gate-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 34px;
  height: 34px;
  padding: 0;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: transparent;
  color: var(--text-2);
  cursor: pointer;
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}
.gate-icon-btn:hover {
  background: var(--surface-hover);
  color: var(--text);
}

/* Centered card area. */
.gate-main {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: var(--s-6);
}
.gate-card {
  width: 100%;
  max-width: 560px;
  padding: var(--s-9) var(--s-8);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: 0;
}

/* Editorial header block: orange eyebrow + heavy H1 + orange title-bar (charter). */
.gate-eyebrow {
  margin: 0;
  font-size: var(--fs-xs);
  font-weight: var(--fw-bold);
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
  color: var(--orange);
}
.gate-title {
  margin: var(--s-2) 0 0;
  font-size: var(--fs-3xl);
  font-weight: var(--fw-heavy);
  line-height: 1.05;
  letter-spacing: -0.01em;
  color: var(--text);
}
.gate-titlebar {
  width: 52px;
  height: 4px;
  margin: var(--s-4) 0 0;
  background: var(--orange);
}
.gate-body {
  margin: var(--s-5) 0 0;
  font-size: var(--fs-md);
  line-height: 1.6;
  color: var(--text-2);
  max-width: 46ch;
}

.gate-actions {
  margin: var(--s-7) 0 0;
}

/* Primary action: solid orange fill, square (charter). Local button (the gate is
   self-contained and must render even if the shared shell is not mounted). */
.gate-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--s-2);
  padding: 11px 20px;
  font-size: var(--fs-sm);
  font-weight: var(--fw-bold);
  font-family: inherit;
  border: 2px solid transparent;
  border-radius: 0;
  cursor: pointer;
  transition: background var(--dur) var(--ease), border-color var(--dur) var(--ease);
}
.gate-btn--primary {
  background: var(--orange);
  color: #fff;
  border-color: var(--orange);
}
.gate-btn--primary:hover {
  background: var(--orange-deep);
  border-color: var(--orange-deep);
}
</style>
