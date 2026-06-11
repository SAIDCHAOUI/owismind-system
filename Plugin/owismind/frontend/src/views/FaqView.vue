<script setup>
// FAQ page (Phase 3). Static bilingual content from the faqContent registry,
// rendered as native <details> accordions (faithful to the maquette). We ADD the
// client-side search the maquette declared (`.faq-search`) but never wired:
// it filters groups/questions on the current locale, case-insensitively.
import { ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useTr } from '../composables/useTr.js'
import { faqGroups } from '../registries/faqContent.js'
import { PageShell } from '../components/pages'
import { Icon } from '../components/ui'

const { t } = useI18n()
const tr = useTr()

const query = ref('')

// Filter on translated question + answer text. Empty query → everything.
const filteredGroups = computed(() => {
  const q = query.value.trim().toLowerCase()
  if (!q) return faqGroups
  return faqGroups
    .map((g) => ({
      ...g,
      qs: g.qs.filter(
        (item) =>
          tr(item.q).toLowerCase().includes(q) || tr(item.a).toLowerCase().includes(q),
      ),
    }))
    .filter((g) => g.qs.length > 0)
})

const hasResults = computed(() => filteredGroups.value.length > 0)
</script>

<template>
  <PageShell :eyebrow="t('faq.eyebrow')" :title="t('faq.title')" :desc="t('faq.desc')">
    <div class="faq-search-wrap">
      <span class="faq-search-ico"><Icon name="search" /></span>
      <input v-model="query" class="faq-search" type="search" :placeholder="t('faq.search')" />
    </div>

    <p v-if="!hasResults" class="faq-no-results">{{ t('faq.no_results', [query]) }}</p>

    <div v-for="(g, gi) in filteredGroups" :key="gi" class="faq-group">
      <div class="faq-group-title">{{ tr(g.title) }}</div>
      <details v-for="(item, ii) in g.qs" :key="ii" class="faq-item">
        <summary>
          <span class="faq-q">{{ tr(item.q) }}</span>
          <span class="faq-ico"><Icon name="plus" /></span>
        </summary>
        <div class="faq-a">{{ tr(item.a) }}</div>
      </details>
    </div>
  </PageShell>
</template>

<style scoped>
.faq-search-wrap {
  position: relative;
  margin-bottom: var(--s-6);
}
.faq-search-ico {
  position: absolute;
  left: 14px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-3);
  pointer-events: none;
}
.faq-search-ico :deep(.ui-icon) { width: 16px; height: 16px; }
.faq-search {
  width: 100%;
  padding: 12px 14px 12px 40px;
  font-size: var(--fs-sm);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r);
  color: var(--text);
  transition: border-color var(--dur) var(--ease);
}
.faq-search:focus { outline: none; border-color: var(--text-3); }

.faq-no-results {
  font-size: var(--fs-sm);
  color: var(--text-2);
  padding: var(--s-2) 0 var(--s-6);
}

.faq-group { margin-bottom: var(--s-7); }
.faq-group-title {
  font-size: 11px;
  color: var(--orange);
  font-weight: 600;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  margin-bottom: var(--s-3);
}
.faq-item { border-bottom: 1px solid var(--border); }
.faq-item summary {
  list-style: none;
  cursor: pointer;
  padding: var(--s-4) 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  font-size: var(--fs-md);
  font-weight: 500;
  color: var(--text);
  user-select: none;
}
.faq-item summary::-webkit-details-marker { display: none; }
.faq-q { min-width: 0; }
.faq-ico {
  flex-shrink: 0;
  color: var(--text-3);
  transition: transform var(--dur) var(--ease);
}
.faq-ico :deep(.ui-icon) { width: 14px; height: 14px; }
.faq-item[open] .faq-ico { transform: rotate(45deg); }
.faq-a {
  padding: 0 0 var(--s-4);
  color: var(--text-2);
  font-size: var(--fs-sm);
  line-height: 1.65;
}
</style>
