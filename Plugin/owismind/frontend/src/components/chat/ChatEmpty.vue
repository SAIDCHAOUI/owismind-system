<script setup>
// Empty conversation state - centered title + subtitle (with a link to the agent
// library). Visual spec ported from `.empty` / `.empty-title` / `.empty-sub`
// (components.css). Suggestion cards (mock editorial in the maquette) are deferred.
import { useI18n } from 'vue-i18n'
import { useRouter } from 'vue-router'
import { Icon } from '../ui'

const { t } = useI18n()
const router = useRouter()
</script>

<template>
  <div class="empty">
    <div class="empty-title-row">
      <h1 class="empty-title">{{ t('empty.title') }}</h1>
    </div>
    <p class="empty-sub">
      {{ t('empty.sub_a') }}<a class="lnk" @click="router.push('/agents')">{{ t('empty.sub_link') }}</a>{{ t('empty.sub_b') }}
    </p>
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
