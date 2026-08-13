<script setup>
// Empty conversation state - a QUIET arrival: one compact heading + one line.
// The Source Data view no longer needs a CTA here (it is docked on the right by
// default - AppLayout auto-opens it); a small re-open chip appears only when the
// user dismissed the dock. Attention belongs to the prompt bar below.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Icon } from '../ui'
import { useSessionStore } from '../../stores/session.js'
import { useSourcesStore } from '../../stores/sources.js'

const { t } = useI18n()
const router = useRouter()
const session = useSessionStore()
const sources = useSourcesStore()

// The selected agent exposes at least one browsable source dataset.
const hasSources = computed(() => {
  const a = session.selectedAgent
  return !!(a && Array.isArray(a.sources) && a.sources.length)
})
// Discreet re-open: only when the dock is closed (the user dismissed it).
const showReopen = computed(() => hasSources.value && !sources.open)
function openSources() { sources.openPanel(session.selectedAgentKey) }
</script>

<template>
  <div class="empty">
    <div class="u-rise">
      <h1 class="empty-title">{{ t('empty.title') }}</h1>
      <span class="empty-bar" aria-hidden="true" />
    </div>
    <p class="empty-sub u-rise" style="animation-delay: 60ms">
      {{ t('empty.sub_a') }}<a class="lnk" @click="router.push('/agents')">{{ t('empty.sub_link') }}</a>{{ t('empty.sub_b') }}
    </p>
    <button
      v-if="showReopen"
      type="button"
      class="empty-reopen u-rise"
      style="animation-delay: 120ms"
      @click="openSources"
    >
      <Icon name="database" :size="14" />
      <span>{{ t('src.panel.title') }}</span>
    </button>
  </div>
</template>

<style scoped>
.empty {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 0 var(--s-7);
  text-align: center;
  width: var(--chat-col);
  max-width: var(--chat-col-max);
  margin: 0 auto;
  gap: var(--s-5);
}
/* Heading = ink, heavy, tight (charte display recipe) with the 52x4 orange
   title-bar centered under it. The orange stays a bar, not the whole line -
   the eye lands here once, then drops to the prompt. */
.empty-title {
  font-family: var(--font-sans);
  font-size: var(--fs-2xl);
  font-weight: var(--fw-heavy);
  letter-spacing: -0.01em; /* charte H1 tracking */
  margin: 0;
  color: var(--text);
  line-height: 1.1;
}
/* The 52x4 title-bar draws itself under the heading on arrival (a wipe from the
   centre), which is the one deliberate flourish of the empty screen. */
.empty-bar {
  display: block;
  width: 52px;
  height: 4px;
  background: var(--orange);
  margin: var(--s-4) auto 0;
  animation: bar-wipe var(--dur-slow) var(--ease-out) 160ms both;
}
@keyframes bar-wipe {
  from { transform: scaleX(0); }
  to { transform: scaleX(1); }
}
.empty-sub {
  font-size: var(--fs-md);
  color: var(--text-2);
  max-width: 720px;
  margin: 0;
  line-height: 1.55;
}
.empty-sub .lnk {
  color: var(--text);
  font-weight: 500;
  text-decoration: underline;
  text-underline-offset: 3px;
  cursor: pointer;
  transition: color var(--dur) var(--ease);
}
.empty-sub .lnk:hover { color: var(--orange-text); }
/* Re-open chip (dock dismissed): a quiet capsule that lifts off the page on hover. */
.empty-reopen {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: var(--r-pill);
  background: var(--bg);
  color: var(--text-2);
  font-size: var(--fs-sm);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease), transform var(--dur) var(--ease);
}
.empty-reopen:hover {
  border-color: var(--text);
  color: var(--text);
  box-shadow: var(--elev-1);
  transform: translateY(-1px);
}
.empty-reopen:active { transform: translateY(0) scale(0.98); }
.empty-reopen :deep(.ui-icon) { color: var(--orange-text); }

@media (prefers-reduced-motion: reduce) {
  .empty-bar { animation: none; }
  .empty-reopen { transition: border-color var(--dur) var(--ease), color var(--dur) var(--ease); }
  .empty-reopen:hover,
  .empty-reopen:active { transform: none; box-shadow: none; }
}
</style>
