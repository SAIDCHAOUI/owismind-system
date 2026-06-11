<script setup>
// Generic page placeholder for secondary routes not yet built (help pages).
// Driven by route meta i18n keys (eyebrow/title/desc). Renders an HONEST
// "coming soon" state via the shared PageShell — never fake content.
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { PageShell } from '../components/pages'

const route = useRoute()
const { t, te } = useI18n()

// Title may be a raw string (e.g. "Admin") or an i18n key.
const eyebrow = computed(() => (route.meta.eyebrow ? t(route.meta.eyebrow) : ''))
const title = computed(() => {
  const k = route.meta.title
  if (!k) return ''
  return te(k) ? t(k) : k
})
const desc = computed(() => (route.meta.desc ? t(route.meta.desc) : ''))
</script>

<template>
  <PageShell :eyebrow="eyebrow" :title="title" :desc="desc">
    <div class="page-placeholder">
      <div class="page-placeholder-bar" />
      <p>{{ t('page.placeholder') }}</p>
    </div>
  </PageShell>
</template>

<style scoped>
.page-placeholder {
  margin-top: var(--s-7);
  padding: 28px;
  border: 1px dashed var(--border-strong);
  border-radius: var(--r-lg);
  background: var(--surface);
  color: var(--text-2);
  font-size: 14.5px;
  line-height: 1.6;
}
.page-placeholder-bar {
  width: 36px;
  height: 3px;
  background: var(--orange);
  border-radius: 3px;
  margin-bottom: 14px;
  opacity: 0.85;
}
.page-placeholder p { margin: 0; }
</style>
