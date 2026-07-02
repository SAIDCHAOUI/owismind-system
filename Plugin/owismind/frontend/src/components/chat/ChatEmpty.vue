<script setup>
// Empty conversation state - centered title + subtitle (with a link to the agent
// library). Visual spec ported from `.empty` / `.empty-title` / `.empty-sub`
// (components.css). Suggestion cards (mock editorial in the maquette) are deferred.
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
function openSources() { sources.openPanel(session.selectedAgentKey) }
</script>

<template>
  <div class="empty">
    <div class="empty-title-row">
      <h1 class="empty-title">{{ t('empty.title') }}</h1>
    </div>
    <p class="empty-sub">
      {{ t('empty.sub_a') }}<a class="lnk" @click="router.push('/agents')">{{ t('empty.sub_link') }}</a>{{ t('empty.sub_b') }}
    </p>
    <button v-if="hasSources" type="button" class="empty-sources" @click="openSources">
      <span class="empty-sources__ico"><Icon name="database" :size="18" /></span>
      <span class="empty-sources__text">
        <span class="empty-sources__title">{{ t('src.cta.title') }}</span>
        <span class="empty-sources__hint">{{ t('src.cta.hint') }}</span>
      </span>
      <Icon name="chevronRight" :size="16" class="empty-sources__go" />
    </button>
    <p class="empty-tip">
      <Icon name="info" :size="16" class="empty-tip__ico" />
      <span>{{ t('empty.tip') }}</span>
    </p>
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
.empty-title-row { display: flex; align-items: center; gap: var(--s-3); justify-content: center; }
.empty-title {
  font-family: var(--font-sans);
  font-size: var(--fs-2xl);
  font-weight: 600;
  letter-spacing: -0.025em;
  margin: 0;
  color: var(--orange);
  line-height: 1.15;
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
}
/* Source Data Explorer CTA - a square bordered block (charte geometry): a database
   icon chip (the only orange accent), a title and a one-line hint. Left-aligned so
   the two lines read naturally; hover lifts the border to the strong tone. */
.empty-sources {
  display: flex;
  align-items: center;
  gap: var(--s-4);
  width: 100%;
  max-width: 460px;
  text-align: left;
  padding: 14px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 0;
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: border-color var(--dur) var(--ease), background var(--dur) var(--ease);
}
.empty-sources:hover { border-color: var(--orange); background: var(--surface-hover); }
.empty-sources__ico {
  flex: none;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 36px;
  height: 36px;
  border: 1px solid var(--orange);
  color: var(--orange-text);
  background: var(--orange-soft);
}
.empty-sources__text { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
.empty-sources__title { font-size: var(--fs-md); font-weight: 600; color: var(--text); }
.empty-sources__hint { font-size: var(--fs-sm); color: var(--text-2); line-height: 1.4; }
.empty-sources__go { flex: none; color: var(--text-3); }
:global(body[data-theme="dark"] .empty-sources__ico) { background: var(--orange-soft-dark); }

/* "Be precise" tip - a quiet, left-aligned hint so the multi-line text stays
   readable (the rest of the empty stage is centered). */
.empty-tip {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  text-align: left;
  max-width: 560px;
  margin: 0;
  padding: 10px 14px;
  border-radius: var(--r);
  background: var(--surface-2);
  font-size: var(--fs-sm);
  color: var(--text-2);
  line-height: 1.5;
}
.empty-tip__ico { flex-shrink: 0; margin-top: 1px; color: var(--orange-text); }
</style>
