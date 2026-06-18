<script setup>
// Settings page (Phase 3). Faithful to the maquette's compact layout
// (`.set-compact` / `.set-head` / `.set-top-grid`) but HONEST: it shows only what
// the backend actually provides.
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
</script>

<template>
  <PageShell wide>
    <!-- Compact header: title on the left, quick theme + language prefs on the right -->
    <template #header>
      <div class="set-head">
        <div class="set-head-l">
          <p class="set-eyebrow">{{ t('set.eyebrow') }}</p>
          <h1 class="set-title">{{ t('set.title') }}</h1>
        </div>
        <div class="set-head-r">
          <div class="pref-toggle" role="group" :aria-label="t('set.appearance')">
            <button
              type="button"
              class="pref-toggle-btn"
              :class="{ active: ui.theme === 'light' }"
              :aria-pressed="ui.theme === 'light'"
              @click="ui.setTheme('light')"
            >
              <Icon name="sun" /><span>{{ t('set.theme.light') }}</span>
            </button>
            <button
              type="button"
              class="pref-toggle-btn"
              :class="{ active: ui.theme === 'dark' }"
              :aria-pressed="ui.theme === 'dark'"
              @click="ui.setTheme('dark')"
            >
              <Icon name="moon" /><span>{{ t('set.theme.dark') }}</span>
            </button>
          </div>

          <div class="pref-select-wrap">
            <select
              class="pref-select"
              :value="ui.lang"
              :aria-label="t('set.language')"
              @change="onLangChange"
            >
              <option v-for="l in AVAILABLE_LOCALES" :key="l.id" :value="l.id">
                {{ l.flag }}&nbsp;&nbsp;{{ l.label }}
              </option>
            </select>
            <span class="pref-select-arr"><Icon name="chevronDown" /></span>
          </div>
        </div>
      </div>
    </template>

    <!-- Top grid: profile (real) + budget (empty) -->
    <div class="set-top-grid">
      <SettingCard :eyebrow="t('set.profile')">
        <template #action>
          <button class="set-profile-edit-btn" type="button" disabled :title="t('x.soon')">
            <Icon name="pencil" /><span>{{ t('set.profile.edit') }}</span>
            <span class="soon-tag">{{ t('x.soon') }}</span>
          </button>
        </template>

        <div class="set-profile-row">
          <div class="avatar-lg">{{ session.initials }}</div>
          <div class="set-profile-info">
            <div class="name-row">
              <span class="name">{{ session.displayName || '-' }}</span>
            </div>
            <div class="set-profile-meta-row">
              <span class="did-pill">
                <Icon name="lock" /><span class="did-label">Dataiku</span>
                <span class="did-id mono">{{ userId }}</span>
              </span>
            </div>
            <div v-if="groups.length" class="group-block">
              <span class="group-label">{{ t('set.profile.groups') }}</span>
              <div class="group-pills">
                <span v-for="g in groups" :key="g" class="group-pill">{{ g }}</span>
              </div>
            </div>
          </div>
        </div>
      </SettingCard>

      <SettingCard :eyebrow="t('set.budget')">
        <div v-if="!usage" class="bud-loading muted">{{ t('set.budget.loading') }}</div>
        <div v-else class="bud" :class="level">
          <div class="bud-head">
            <div class="bud-amounts">
              <span class="bud-spent mono">{{ money(usage.spent_usd) }}</span>
              <span class="bud-of mono">/ {{ money(usage.limit_usd) }}</span>
            </div>
            <span class="bud-pct mono" :class="level">{{ pct }}%</span>
          </div>

          <div class="bud-bar" :class="level">
            <span class="bud-fill" :style="{ width: fill + '%' }" />
          </div>

          <div class="bud-meta">
            <span class="bud-remaining">
              <strong class="mono">{{ money(usage.remaining_usd) }}</strong> {{ t('set.budget.remaining') }}
            </span>
            <span v-if="usage.next_reset" class="bud-reset">
              {{ t('set.budget.resets', [shortDate(usage.next_reset)]) }}
            </span>
          </div>

          <!-- Blocked / disabled / transparency line -->
          <p v-if="blocked" class="bud-flag bud-flag--block">
            <Icon name="alert" />{{ t('set.budget.blocked', [shortDate(usage.next_reset)]) }}
          </p>
          <p v-else-if="level === 'off'" class="bud-flag bud-flag--off">
            <Icon name="wallet" />{{ t('set.budget.off') }}
          </p>
          <p class="bud-source muted">{{ sourceLabel }}</p>

          <div class="bud-stats">
            <span class="bud-stat">
              <span class="bud-stat-k">{{ t('set.budget.requests') }}</span>
              <span class="bud-stat-v mono">{{ formatTokens(usage.request_count, locale) }}</span>
            </span>
            <span class="bud-stat">
              <span class="bud-stat-k">{{ t('set.usage.tokens_month') }}</span>
              <span class="bud-stat-v mono">{{ tokens(usage.total_tokens) }}</span>
            </span>
          </div>
        </div>
      </SettingCard>
    </div>

    <!-- Agent-context window preference (real, persisted in the ui store) -->
    <SettingCard :eyebrow="t('set.context')" class="set-history-card">
      <div class="set-history-row">
        <div class="set-history-text">
          <p class="set-history-label">{{ t('set.context.max') }}</p>
          <p class="set-history-desc">{{ t('set.context.max_desc') }}</p>
        </div>
        <div class="pref-select-wrap">
          <select
            class="pref-select pref-select--narrow"
            :value="ui.contextMessages"
            :aria-label="t('set.context.max')"
            @change="onContextChange"
          >
            <option v-for="n in convOptions" :key="n" :value="n">{{ n }}</option>
          </select>
          <span class="pref-select-arr"><Icon name="chevronDown" /></span>
        </div>
      </div>
    </SettingCard>

    <!-- Usage detail (this month + lifetime) -->
    <SettingCard :eyebrow="t('set.usage')" class="set-usage-card">
      <div v-if="!usage" class="bud-loading muted">{{ t('set.budget.loading') }}</div>
      <div v-else class="use-grid">
        <div class="use-cell">
          <span class="use-k">{{ t('set.usage.tokens_month') }}</span>
          <span class="use-v mono">{{ tokens(usage.total_tokens) }}</span>
          <span class="use-sub mono">↑ {{ tokens(usage.input_tokens) }} · ↓ {{ tokens(usage.output_tokens) }}</span>
        </div>
        <div class="use-cell">
          <span class="use-k">{{ t('set.usage.spend_month') }}</span>
          <span class="use-v mono">{{ money(usage.spent_usd) }}</span>
          <span class="use-sub">{{ formatTokens(usage.request_count, locale) }} {{ t('set.usage.calls') }}</span>
        </div>
        <div class="use-cell">
          <span class="use-k">{{ t('set.usage.lifetime_cost') }}</span>
          <span class="use-v mono">{{ money(usage.lifetime.cost_usd) }}</span>
          <span class="use-sub mono">{{ tokens(usage.lifetime.total_tokens) }} {{ t('msg.usage_tokens') }}</span>
        </div>
        <div v-if="usage.lifetime.last_usage_at" class="use-cell">
          <span class="use-k">{{ t('set.usage.last') }}</span>
          <span class="use-v">{{ shortDate(usage.lifetime.last_usage_at) }}</span>
        </div>
      </div>
    </SettingCard>
  </PageShell>
</template>

<style scoped>
/* --- Compact header (title + inline prefs) --- */
.set-head {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: var(--s-5);
  flex-wrap: wrap;
  margin-bottom: var(--s-7);
}
.set-eyebrow {
  font-size: var(--fs-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--orange);
  margin: 0 0 var(--s-3);
}
.set-title {
  font-size: var(--fs-2xl);
  font-weight: 600;
  letter-spacing: -0.025em;
  color: var(--text);
  margin: 0;
}
.set-head-r {
  display: flex;
  align-items: center;
  gap: var(--s-3);
  flex-wrap: wrap;
}

/* Theme segmented control */
.pref-toggle {
  display: inline-flex;
  gap: 2px;
  padding: 3px;
  background: var(--surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
}
.pref-toggle-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border-radius: calc(var(--r-sm) - 2px);
  font-size: var(--fs-sm);
  color: var(--text-2);
  transition: all var(--dur) var(--ease);
}
.pref-toggle-btn :deep(.ui-icon) { width: 15px; height: 15px; }
.pref-toggle-btn.active {
  background: var(--bg);
  color: var(--text);
  font-weight: 500;
  box-shadow: var(--shadow);
}

/* Language select */
.pref-select-wrap {
  position: relative;
  display: inline-flex;
}
.pref-select {
  appearance: none;
  -webkit-appearance: none;
  padding: 8px 36px 8px 12px;
  min-width: 180px;
  font-size: var(--fs-sm);
  color: var(--text);
  background: var(--bg);
  border: 1px solid var(--border-strong);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.pref-select:hover { border-color: var(--orange); }
.pref-select:focus {
  outline: none;
  border-color: var(--orange);
  box-shadow: 0 0 0 2px var(--orange-soft-dark);
}
.pref-select-arr {
  position: absolute;
  right: 10px;
  top: 50%;
  transform: translateY(-50%);
  pointer-events: none;
  color: var(--text-3);
}
.pref-select-arr :deep(.ui-icon) { width: 15px; height: 15px; }

/* --- Layout grids --- */
.set-top-grid {
  display: grid;
  grid-template-columns: 1fr 1.15fr;
  gap: var(--s-4);
  margin-bottom: var(--s-4);
}
.set-usage-card { display: block; }
.set-history-card { display: block; margin-bottom: var(--s-4); }

/* History preferences row */
.set-history-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-5);
  flex-wrap: wrap;
}
.set-history-text { min-width: 0; }
.set-history-label { font-size: var(--fs-sm); font-weight: 600; color: var(--text); margin: 0 0 4px; }
.set-history-desc { font-size: var(--fs-xs); color: var(--text-3); margin: 0; max-width: 520px; }
.pref-select--narrow { min-width: 90px; }

/* --- Profile card (real /me data only) --- */
.set-profile-row {
  display: flex;
  align-items: flex-start;
  gap: var(--s-4);
}
.avatar-lg {
  width: 52px;
  height: 52px;
  flex-shrink: 0;
  border-radius: 50%;
  display: grid;
  place-items: center;
  background: var(--surface);
  border: 1px solid var(--border);
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}
.set-profile-info { min-width: 0; display: flex; flex-direction: column; gap: 8px; }
.name-row { display: flex; align-items: center; gap: 8px; }
.name { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.set-profile-meta-row { display: flex; flex-wrap: wrap; gap: 8px; }
.did-pill {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 3px 9px;
  border-radius: var(--r-pill);
  background: var(--surface);
  border: 1px solid var(--border);
  font-size: var(--fs-xs);
  color: var(--text-2);
}
.did-pill :deep(.ui-icon) { width: 12px; height: 12px; color: var(--text-3); }
.did-label { font-weight: 600; color: var(--text-2); }
.did-id { color: var(--text); font-size: 11px; }
.group-block { display: flex; flex-direction: column; gap: 6px; }
.group-label {
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  color: var(--text-3);
}
.group-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.group-pill {
  padding: 2px 9px;
  border-radius: var(--r-pill);
  background: var(--orange-soft-dark);
  color: var(--orange);
  font-size: 11px;
  font-weight: 500;
}

/* Disabled "edit profile" button (no set-name route yet → labeled "soon") */
.set-profile-edit-btn {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg);
  font-size: var(--fs-xs);
  color: var(--text-2);
  cursor: not-allowed;
  opacity: 0.7;
}
.set-profile-edit-btn :deep(.ui-icon) { width: 13px; height: 13px; }
.soon-tag {
  font-size: 9px;
  font-weight: 700;
  letter-spacing: 0.06em;
  text-transform: uppercase;
  padding: 1px 6px;
  border-radius: var(--r-pill);
  background: var(--orange-soft-dark);
  color: var(--orange);
}

/* --- Monthly budget card (real /usage data) --- */
.bud-loading { font-size: var(--fs-sm); padding: var(--s-3) 0; }
.bud { display: flex; flex-direction: column; gap: var(--s-3); }
.bud-head { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); }
.bud-amounts { display: flex; align-items: baseline; gap: 6px; min-width: 0; }
.bud-spent { font-size: var(--fs-2xl); font-weight: 600; letter-spacing: -0.02em; color: var(--text); }
.bud-of { font-size: var(--fs-md); color: var(--text-3); }
.bud-pct { font-size: var(--fs-sm); font-weight: 600; color: var(--text-2); }
.bud-pct.warn { color: var(--orange-text); }
.bud-pct.over { color: var(--danger); }

/* Gauge: a rounded track with a fill colored by severity. */
.bud-bar { position: relative; height: 9px; border-radius: var(--r-pill); background: var(--surface-2); overflow: hidden; }
.bud-fill {
  position: absolute; left: 0; top: 0; bottom: 0; border-radius: var(--r-pill);
  background: var(--orange); transition: width var(--dur-slow) var(--ease);
}
.bud-bar.warn .bud-fill { background: var(--orange); }
.bud-bar.over .bud-fill { background: var(--danger); }
.bud-bar.off .bud-fill { background: var(--text-3); }

.bud-meta { display: flex; align-items: baseline; justify-content: space-between; gap: var(--s-3); flex-wrap: wrap; }
.bud-remaining { font-size: var(--fs-sm); color: var(--text-2); }
.bud-remaining strong { color: var(--text); font-weight: 600; }
.bud-reset { font-size: var(--fs-xs); color: var(--text-3); }

.bud-flag {
  display: flex; align-items: center; gap: 7px; margin: 0;
  font-size: var(--fs-xs); line-height: 1.5; padding: 7px 10px; border-radius: var(--r-sm);
}
.bud-flag :deep(.ui-icon) { width: 14px; height: 14px; flex-shrink: 0; }
.bud-flag--block { color: var(--danger); background: var(--danger-soft); }
.bud-flag--off { color: var(--text-2); background: var(--surface); }
.bud-source { font-size: var(--fs-xs); line-height: 1.5; margin: 0; }

.bud-stats { display: flex; gap: var(--s-5); flex-wrap: wrap; padding-top: var(--s-2); border-top: 1px solid var(--border); }
.bud-stat { display: flex; flex-direction: column; gap: 2px; }
.bud-stat-k { font-size: 10px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-3); }
.bud-stat-v { font-size: var(--fs-md); font-weight: 600; color: var(--text); }

/* --- Usage detail grid (this month + lifetime) --- */
.use-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: var(--s-4); }
.use-cell {
  display: flex; flex-direction: column; gap: 4px;
  padding: var(--s-4); border: 1px solid var(--border); border-radius: var(--r); background: var(--bg);
}
.use-k { font-size: 10px; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; color: var(--text-3); }
.use-v { font-size: var(--fs-lg); font-weight: 600; color: var(--text); letter-spacing: -0.01em; }
.use-sub { font-size: var(--fs-xs); color: var(--text-3); }

@media (max-width: 760px) {
  .set-top-grid { grid-template-columns: 1fr; }
}
</style>
