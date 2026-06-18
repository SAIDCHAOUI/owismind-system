<script setup>
// Settings page (Phase 3). Faithful to the maquette's compact layout but HONEST:
// it shows only what the backend actually provides.
//   - Profile  : from /me - display name, Dataiku id, real groups. No invented
//                email / role / title. The "edit profile" button is disabled
//                ("soon") because there is no "set my name" route yet (memory L017).
//   - Theme    : segmented light/dark control, wired to the ui store.
//   - Language : native select, wired to i18n setLocale.
//   - Budget   : REAL - the user's monthly credit (spend / limit / remaining / reset),
//                from /usage via the session store. Transparent about the limit source
//                (default / temporary boost / admin override). No mock figures.
//   - Usage    : REAL - this-month tokens + spend and the lifetime counters.
import { computed, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { useUiStore } from '../stores/ui.js'
import { useSessionStore } from '../stores/session.js'
import { AVAILABLE_LOCALES } from '../i18n'
import {
  CONTEXT_MESSAGES_MIN,
  CONTEXT_MESSAGES_MAX,
} from '../stores/prefs.js'
import {
  formatMoney,
  formatTokens,
  formatShortDate,
  usagePct,
  gaugePct,
  usageLevel,
} from '../composables/budgetModel.js'
import { PageShell, SettingCard } from '../components/pages'
import { Icon } from '../components/ui'

const { t, locale } = useI18n()
const ui = useUiStore()
const session = useSessionStore()

const groups = computed(() => session.user?.groups || [])
const userId = computed(() => session.user?.user_id || '-')

// --- Monthly budget / usage (real, from /usage via the session store) ----------
const usage = computed(() => session.usage)
// Refresh on entry so the figures are current even if the user lands here directly
// (init() already loads it; this just guarantees freshness without a full reload).
onMounted(() => {
  if (!session.needsConfig && typeof session.loadUsage === 'function') session.loadUsage()
})

const money = (v) => formatMoney(v, locale.value)
const tokens = (v) => formatTokens(v, locale.value)
const shortDate = (v) => formatShortDate(v, locale.value)

const pct = computed(() => (usage.value ? usagePct(usage.value.spent_usd, usage.value.limit_usd) : 0))
const fill = computed(() => (usage.value ? gaugePct(usage.value.spent_usd, usage.value.limit_usd) : 0))
const level = computed(() => usageLevel(usage.value))
const blocked = computed(() => !!usage.value && usage.value.enforced !== false && !!usage.value.blocked)

// Transparency line: WHY the limit is what it is (default / global temp / per-user).
const sourceLabel = computed(() => {
  const u = usage.value
  if (!u) return ''
  const limit = money(u.limit_usd)
  const exp = shortDate(u.limit_expires_at)
  switch (u.limit_source) {
    case 'global_temp':
      return t('set.budget.src_global_temp', [limit, exp])
    case 'user_permanent':
      return t('set.budget.src_user', [limit])
    case 'user_temp':
      return t('set.budget.src_user_temp', [limit, exp])
    default:
      return t('set.budget.src_default', [limit])
  }
})

// Language goes through the ui store (single source of truth shared with the header).
function onLangChange(e) {
  ui.setLang(e.target.value)
}

// Agent-context window - the same ui-store preference the chat send reads. Step of 10
// keeps the choices simple (10/20/30/40/50); the store clamps anything out of range.
// No refetch: changing it only affects the NEXT send (the bounded multi-turn context).
const convStep = 10
const convOptions = computed(() => {
  const out = []
  for (let n = CONTEXT_MESSAGES_MIN; n <= CONTEXT_MESSAGES_MAX; n += convStep) out.push(n)
  return out
})
function onContextChange(e) {
  ui.setContextMessages(e.target.value)
}

// Current locale flag + label for the language select display chip.
const currentLocale = computed(() => AVAILABLE_LOCALES.find(l => l.id === ui.lang) || AVAILABLE_LOCALES[0])
</script>

<template>
  <PageShell wide>
    <!-- Custom header: eyebrow + h1 + orange title-bar on left; theme/lang controls on right -->
    <template #header>
      <div class="header-row">
        <div class="header-left">
          <p class="set-eyebrow">{{ t('set.eyebrow') }}</p>
          <h1 class="set-h1">{{ t('set.title') }}</h1>
          <div class="title-bar"></div>
        </div>
        <div class="controls">
          <!-- Theme segmented control: flat 1px border row, active = near-black bg + white text -->
          <div class="seg" role="group" :aria-label="t('set.appearance')">
            <button
              type="button"
              :class="{ on: ui.theme === 'light' }"
              :aria-pressed="ui.theme === 'light'"
              @click="ui.setTheme('light')"
            >
              <Icon name="sun" /><span>{{ t('set.theme.light') }}</span>
            </button>
            <button
              type="button"
              :class="{ on: ui.theme === 'dark' }"
              :aria-pressed="ui.theme === 'dark'"
              @click="ui.setTheme('dark')"
            >
              <Icon name="moon" /><span>{{ t('set.theme.dark') }}</span>
            </button>
          </div>

          <!-- Language: flag chip + label + chevron over an invisible native select -->
          <div class="lang-wrap">
            <span class="lang-flag-chip" aria-hidden="true">{{ currentLocale.flag }}</span>
            <span class="lang-label" aria-hidden="true">{{ currentLocale.label }}</span>
            <select
              class="lang-select"
              :value="ui.lang"
              :aria-label="t('set.language')"
              @change="onLangChange"
            >
              <option v-for="l in AVAILABLE_LOCALES" :key="l.id" :value="l.id">
                {{ l.label }}
              </option>
            </select>
            <span class="lang-chevron" aria-hidden="true"><Icon name="chevronDown" /></span>
          </div>
        </div>
      </div>
    </template>

    <!-- Top grid: profile (real) + budget (real) -->
    <div class="set-top-grid">
      <!-- Profile card -->
      <SettingCard>
        <div class="card-label-row">
          <span class="card-lbl">{{ t('set.profile') }}</span>
          <button class="set-edit-btn" type="button" disabled :title="t('x.soon')">
            <Icon name="pencil" /><span>{{ t('set.profile.edit') }}</span>
            <span class="soon-badge">{{ t('x.soon') }}</span>
          </button>
        </div>

        <div class="profile-name">
          <div class="avatar-lg">{{ session.initials }}</div>
          <div class="profile-info">
            <b class="profile-display-name">{{ session.displayName || '-' }}</b>
            <div class="id-pill">
              <Icon name="lock" /><span class="id-label">Dataiku</span>
              <span class="id-uid">{{ userId }}</span>
            </div>
          </div>
        </div>

        <template v-if="groups.length">
          <p class="card-lbl" style="margin: 20px 0 10px;">{{ t('set.profile.groups') }}</p>
          <div class="chips">
            <span v-for="g in groups" :key="g" class="chip accent">{{ g }}</span>
          </div>
        </template>
      </SettingCard>

      <!-- Monthly budget card -->
      <SettingCard>
        <p class="card-lbl" style="margin: 0 0 14px;">{{ t('set.budget') }}</p>

        <div v-if="!usage" class="bud-loading muted">{{ t('set.budget.loading') }}</div>
        <div v-else :class="['bud', level]">
          <!-- Amount row: big mono spent + "/ limit" + right-aligned percent -->
          <div class="budget-amt">
            <b class="bud-spent">{{ money(usage.spent_usd) }}</b>
            <span class="bud-of">/ {{ money(usage.limit_usd) }}</span>
            <span class="bud-pct" :class="level">{{ pct }}%</span>
          </div>

          <!-- 8px flat bar, orange fill (or danger on over-budget) -->
          <div class="bud-bar" :class="level">
            <i :style="{ width: fill + '%' }"></i>
          </div>

          <div class="budget-meta">
            <span><strong class="bud-remaining-val">{{ money(usage.remaining_usd) }}</strong> {{ t('set.budget.remaining') }}</span>
            <span v-if="usage.next_reset" class="bud-reset-date">{{ t('set.budget.resets', [shortDate(usage.next_reset)]) }}</span>
          </div>

          <p class="budget-sub">{{ sourceLabel }}</p>

          <!-- Blocked / off flags -->
          <p v-if="blocked" class="bud-flag bud-flag--block">
            <Icon name="alert" />{{ t('set.budget.blocked', [shortDate(usage.next_reset)]) }}
          </p>
          <p v-else-if="level === 'off'" class="bud-flag bud-flag--off">
            <Icon name="wallet" />{{ t('set.budget.off') }}
          </p>

          <!-- Mini-grid: requests + tokens this month -->
          <div class="mini-grid">
            <div>
              <div class="ml">{{ t('set.budget.requests') }}</div>
              <div class="mv">{{ formatTokens(usage.request_count, locale) }}</div>
            </div>
            <div>
              <div class="ml">{{ t('set.usage.tokens_month') }}</div>
              <div class="mv">{{ tokens(usage.total_tokens) }}</div>
            </div>
          </div>
        </div>
      </SettingCard>
    </div>

    <!-- Agent-context window preference (real, persisted in the ui store) -->
    <SettingCard class="set-context-card">
      <div class="block-title">{{ t('set.context') }}</div>
      <div class="ctx-row">
        <div class="ctx-text">
          <div class="ctx-lab">{{ t('set.context.max') }}</div>
          <div class="ctx-sub">{{ t('set.context.max_desc') }}</div>
        </div>
        <div class="ctx-select-wrap">
          <select
            class="ctx-select"
            :value="ui.contextMessages"
            :aria-label="t('set.context.max')"
            @change="onContextChange"
          >
            <option v-for="n in convOptions" :key="n" :value="n">{{ n }}</option>
          </select>
          <span class="ctx-chevron"><Icon name="chevronDown" /></span>
        </div>
      </div>
    </SettingCard>

    <!-- Usage history: 4-up stat tiles separated by 1px right-borders -->
    <SettingCard class="set-usage-card">
      <div class="block-title">{{ t('set.usage') }}</div>
      <div v-if="!usage" class="bud-loading muted">{{ t('set.budget.loading') }}</div>
      <div v-else class="stat-grid">
        <div class="stat">
          <div class="sl">{{ t('set.usage.tokens_month') }}</div>
          <div class="sv">{{ tokens(usage.total_tokens) }}</div>
          <div class="sm">
            <span class="up">{{ tokens(usage.input_tokens) }}</span> · <span class="dn">{{ tokens(usage.output_tokens) }}</span>
          </div>
        </div>
        <div class="stat">
          <div class="sl">{{ t('set.usage.spend_month') }}</div>
          <div class="sv">{{ money(usage.spent_usd) }}</div>
          <div class="sm">{{ formatTokens(usage.request_count, locale) }} {{ t('set.usage.calls') }}</div>
        </div>
        <div class="stat">
          <div class="sl">{{ t('set.usage.lifetime_cost') }}</div>
          <div class="sv">{{ money(usage.lifetime.cost_usd) }}</div>
          <div class="sm">{{ tokens(usage.lifetime.total_tokens) }} {{ t('msg.usage_tokens') }}</div>
        </div>
        <div class="stat stat--last">
          <div class="sl">{{ t('set.usage.last') }}</div>
          <div class="sv sv--date">{{ usage.lifetime.last_usage_at ? shortDate(usage.lifetime.last_usage_at) : '-' }}</div>
        </div>
      </div>
    </SettingCard>
  </PageShell>
</template>

<style scoped>
/* === Header row: left = eyebrow + h1 + title-bar; right = controls === */
.header-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--s-6);
  flex-wrap: wrap;
  margin-bottom: var(--s-9);
}

.set-eyebrow {
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--orange);
  margin: 0 0 10px;
}

.set-h1 {
  font-size: var(--fs-3xl);
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em;
  color: var(--text);
  margin: 0;
  line-height: 1.05;
}

/* 52x4px solid orange title-bar, matches mockup */
.title-bar {
  width: 52px;
  height: 4px;
  background: var(--orange);
  margin-top: 16px;
}

/* Controls row: theme segmented + language select */
.controls {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-top: 6px;
  flex-wrap: wrap;
}

/* Segmented control: 1px border box, active = near-black bg + inverted text */
.seg {
  display: flex;
  border: 1px solid var(--border-strong);
}

.seg button {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 9px 16px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text-2);
  transition: background var(--dur) var(--ease), color var(--dur) var(--ease);
}

.seg button + button {
  border-left: 1px solid var(--border-strong);
}

.seg button :deep(.ui-icon) {
  width: 15px;
  height: 15px;
}

.seg button.on {
  background: var(--text);
  color: var(--bg);
}

/* Language select: flag chip + label + chevron over a native select */
.lang-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: 1px solid var(--border-strong);
  padding: 9px 14px;
  background: var(--bg);
}

.lang-flag-chip {
  font-size: 13px;
  pointer-events: none;
}

.lang-select {
  /* Invisible overlay for click/keyboard, positioned over the whole wrapper */
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
  font-size: var(--fs-sm);
}

.lang-label {
  font-size: 13px;
  font-weight: 600;
  color: var(--text-2);
  pointer-events: none;
  white-space: nowrap;
}

.lang-chevron {
  pointer-events: none;
  color: var(--text-3);
  line-height: 0;
  margin-left: 4px;
}

.lang-chevron :deep(.ui-icon) {
  width: 14px;
  height: 14px;
}

/* === Layout grids === */
.set-top-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}

.set-context-card {
  display: block;
  margin-bottom: var(--s-4);
}

.set-usage-card {
  display: block;
}

/* === Card internals: label rows, profile, budget === */

/* Uppercase 11px/800 card label */
.card-lbl {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin: 0;
}

.card-label-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 18px;
}

/* --- Profile card --- */
.profile-name {
  display: flex;
  align-items: flex-start;
  gap: 14px;
  margin-bottom: 0;
}

/* Avatar: circle, near-black bg, white initial, bold 800 */
.avatar-lg {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: var(--text);
  color: var(--bg);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 800;
  font-size: 20px;
  flex: 0 0 52px;
}

:global(body[data-theme="dark"] .avatar-lg) {
  background: var(--text);
  color: var(--bg);
}

.profile-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-width: 0;
}

.profile-display-name {
  font-size: 18px;
  font-weight: 800;
  color: var(--text);
}

/* id-pill: 1px border, flat, lock icon + "Dataiku" label + mono uid */
.id-pill {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  border: 1px solid var(--border-strong);
  padding: 5px 9px;
  font-size: 12px;
  color: var(--text-2);
}

.id-pill :deep(.ui-icon) {
  width: 12px;
  height: 12px;
  color: var(--text-3);
}

.id-label {
  font-weight: 600;
}

.id-uid {
  font-family: var(--font-mono);
  font-weight: 600;
  color: var(--text);
}

/* Square chips with orange accent border + accent text */
.chips {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.chip {
  border: 1px solid var(--border-strong);
  padding: 5px 10px;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  background: var(--bg);
  /* border-radius: 0 is the default (no border-radius = square) */
}

.chip.accent {
  border-color: var(--orange);
  color: var(--orange-text);
}

/* Disabled "customize profile" button */
.set-edit-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 7px 13px;
  border: 1px solid var(--border-strong);
  font-size: 12px;
  font-weight: 700;
  color: var(--text-2);
  background: var(--bg);
  cursor: not-allowed;
  opacity: 0.5;
}

.set-edit-btn :deep(.ui-icon) {
  width: 13px;
  height: 13px;
}

.soon-badge {
  display: inline-block;
  background: var(--orange);
  color: #fff;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  padding: 2px 6px;
  margin-left: 4px;
  vertical-align: middle;
}

/* --- Monthly budget card --- */
.bud-loading {
  font-size: var(--fs-sm);
  padding: var(--s-3) 0;
}

.bud {
  display: flex;
  flex-direction: column;
  gap: 0;
}

/* Big mono amount: "$x.xx" + "/ $50.00" + right-pushed percent */
.budget-amt {
  display: flex;
  align-items: baseline;
  gap: 10px;
}

.bud-spent {
  font-size: 34px;
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--text);
  line-height: 1;
}

.bud-of {
  font-family: var(--font-mono);
  font-size: 18px;
  color: var(--text-3);
}

.bud-pct {
  margin-left: auto;
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--text-2);
  font-size: var(--fs-sm);
}

.bud-pct.warn { color: var(--orange-text); }
.bud-pct.over { color: var(--danger); }

/* 8px flat track (no border-radius = square), orange fill */
.bud-bar {
  height: 8px;
  background: var(--surface-2);
  margin: 16px 0;
  overflow: hidden;
}

.bud-bar i {
  display: block;
  height: 100%;
  background: var(--orange);
  transition: width var(--dur-slow) var(--ease);
}

.bud-bar.over i { background: var(--danger); }
.bud-bar.off i  { background: var(--text-3); }

.budget-meta {
  display: flex;
  justify-content: space-between;
  font-size: var(--fs-sm);
  color: var(--text-2);
}

.bud-remaining-val {
  font-family: var(--font-mono);
  font-weight: 700;
  color: var(--text);
}

.bud-reset-date {
  color: var(--text-3);
}

/* "Monthly limit: $50.00 (default)." sub-text */
.budget-sub {
  font-size: 13px;
  color: var(--text-2);
  margin: 6px 0 0;
}

/* Blocked / off flags */
.bud-flag {
  display: flex;
  align-items: center;
  gap: 7px;
  margin: 8px 0 0;
  font-size: var(--fs-xs);
  padding: 7px 10px;
}

.bud-flag :deep(.ui-icon) {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
}

.bud-flag--block {
  color: var(--danger);
  background: var(--danger-soft);
}

.bud-flag--off {
  color: var(--text-2);
  background: var(--surface);
}

/* 2-column mini-grid: requests + tokens this month */
.mini-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 24px;
  margin-top: 20px;
  padding-top: 18px;
  border-top: 1px solid var(--border);
}

.ml {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
}

.mv {
  font-size: 20px;
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--text);
  margin-top: 4px;
}

/* --- Context preferences row --- */
.block-title {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin: 0 0 16px;
}

.ctx-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-6);
}

.ctx-text {
  min-width: 0;
}

.ctx-lab {
  font-weight: 700;
  font-size: 15px;
  color: var(--text);
}

.ctx-sub {
  font-size: 13px;
  color: var(--text-2);
  margin-top: 4px;
}

/* Context select: 1px border, flat, narrow */
.ctx-select-wrap {
  position: relative;
  display: inline-flex;
  align-items: center;
  border: 1px solid var(--border-strong);
  background: var(--bg);
}

.ctx-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 9px 36px 9px 14px;
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--text);
  background: transparent;
  border: none;
  cursor: pointer;
  min-width: 72px;
}

.ctx-select:focus {
  outline: none;
}

.ctx-chevron {
  position: absolute;
  right: 10px;
  pointer-events: none;
  color: var(--text-3);
  line-height: 0;
}

.ctx-chevron :deep(.ui-icon) {
  width: 14px;
  height: 14px;
}

/* --- Usage history: 4-up stat tiles, 1px right-border separators --- */
.stat-grid {
  display: grid;
  grid-template-columns: repeat(4, 1fr);
  gap: 0;
  /* Tiles bleed to the card edges via negative margin on the wrapping SettingCard padding */
  margin: 12px -1px -1px;
  border-top: 1px solid var(--border);
}

.stat {
  padding: 20px 22px;
  border-right: 1px solid var(--border);
}

.stat--last {
  border-right: none;
}

/* Uppercase 11px/800 stat label */
.sl {
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.1em;
  text-transform: uppercase;
  color: var(--text-2);
  margin-bottom: 10px;
}

/* 22px mono value */
.sv {
  font-size: 22px;
  font-weight: 800;
  font-family: var(--font-mono);
  color: var(--text);
}

/* Date value uses sans-serif at slightly smaller size */
.sv--date {
  font-family: var(--font-sans);
  font-size: 18px;
}

/* Small sub-line under the value */
.sm {
  font-size: 12px;
  color: var(--text-3);
  margin-top: 6px;
  font-family: var(--font-mono);
}

.up { color: var(--success); }
.dn { color: var(--text-2); }

/* --- Responsive --- */
@media (max-width: 760px) {
  .set-top-grid {
    grid-template-columns: 1fr;
  }

  .stat-grid {
    grid-template-columns: repeat(2, 1fr);
  }

  .stat:nth-child(2) {
    border-right: none;
  }

  .stat:nth-child(3) {
    border-right: 1px solid var(--border);
  }

  .header-row {
    flex-direction: column;
  }

  .controls {
    margin-top: 0;
  }
}

@media (max-width: 480px) {
  .stat-grid {
    grid-template-columns: 1fr;
  }

  .stat {
    border-right: none;
    border-bottom: 1px solid var(--border);
  }

  .stat--last {
    border-bottom: none;
  }
}
</style>
