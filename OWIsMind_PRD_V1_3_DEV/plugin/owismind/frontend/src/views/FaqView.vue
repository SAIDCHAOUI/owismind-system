<script setup>
// FAQ page (Phase 3). Static bilingual content from the faqContent registry,
// rendered as native <details> accordions (faithful to the maquette). We ADD the
// client-side search the maquette declared but never wired:
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
    <div class="faq-search-wrap u-rise">
      <span class="faq-search-ico"><Icon name="search" /></span>
      <input v-model="query" class="faq-search" type="search" :placeholder="t('faq.search')" />
    </div>

    <p v-if="!hasResults" class="faq-no-results">{{ t('faq.no_results', [query]) }}</p>

    <div
      v-for="(g, gi) in filteredGroups"
      :key="gi"
      class="faq-group u-rise"
      :style="{ animationDelay: Math.min(gi * 60, 240) + 'ms' }"
    >
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
/* Premium pass (user decision 2026-08-13): the pill search leads, each question is
   its own soft card that lifts under the pointer, and the answer unfolds instead of
   snapping open. Semantic tokens only - no gradient/blur/color-mix. */
.faq-search-wrap {
  position: relative;
  margin-bottom: var(--s-6);
}
.faq-search-ico {
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  color: var(--text-3);
  pointer-events: none;
}
.faq-search-ico :deep(.ui-icon) { width: 16px; height: 16px; }
.faq-search {
  width: 100%;
  padding: 12px 18px 12px 44px;
  font-size: var(--fs-sm);
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--r-pill);
  color: var(--text);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.faq-search:hover { border-color: var(--border-strong); }
/* Focus lifts the field (elevation + a border step), never an orange ring. */
.faq-search:focus {
  outline: none;
  border-color: var(--text-3);
  box-shadow: var(--elev-1);
}
:global(body[data-theme="dark"] .faq-search) { background: var(--surface); }

.faq-no-results {
  font-size: var(--fs-sm);
  color: var(--text-2);
  padding: var(--s-2) 0 var(--s-6);
}

.faq-group { margin-bottom: var(--s-7); }
/* Section eyebrow: shared 11px / 800 / 0.08em micro-label recipe, in orange. */
.faq-group-title {
  font-size: 11px;
  color: var(--orange-text);
  font-weight: var(--fw-heavy);
  letter-spacing: var(--tracking-eyebrow);
  text-transform: uppercase;
  margin-bottom: var(--s-3);
}

/* One question = one card: hairline frame, lift on hover, held open with a
   resting shadow so the expanded answer reads as the focused surface. */
.faq-item {
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  background: var(--bg);
  margin-bottom: var(--s-2);
  transition: border-color var(--dur) var(--ease), box-shadow var(--dur) var(--ease);
}
.faq-item:hover { border-color: var(--border-strong); box-shadow: var(--elev-1); }
.faq-item[open] { border-color: var(--border-strong); box-shadow: var(--elev-1); }
:global(body[data-theme="dark"] .faq-item) {
  background: var(--surface-2);
  border-color: var(--border-strong);
}
:global(body[data-theme="dark"] .faq-item:hover) { border-color: var(--text-3); }

.faq-item summary {
  list-style: none;
  cursor: pointer;
  padding: var(--s-4) var(--s-5);
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--s-4);
  font-size: var(--fs-md);
  font-weight: 500;
  color: var(--text);
  user-select: none;
  border-radius: var(--r-lg);
}
.faq-item summary::-webkit-details-marker { display: none; }
.faq-item summary:focus-visible { outline: 2px solid var(--orange); outline-offset: -2px; }
.faq-q { min-width: 0; }
/* The toggle glyph rotates into a minus and picks up a quiet disc on hover. */
.faq-ico {
  flex-shrink: 0;
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  border-radius: var(--r-pill);
  color: var(--text-3);
  transition: transform var(--dur) var(--ease), background var(--dur) var(--ease),
    color var(--dur) var(--ease);
}
.faq-item summary:hover .faq-ico { background: var(--surface-hover); color: var(--text); }
.faq-ico :deep(.ui-icon) { width: 14px; height: 14px; }
.faq-item[open] .faq-ico { transform: rotate(45deg); }
.faq-a {
  padding: 0 var(--s-5) var(--s-4);
  color: var(--text-2);
  font-size: var(--fs-sm);
  line-height: 1.65;
}
/* The answer unfolds on open (native <details> gives no closing hook, so the
   collapse stays instant - the opening is what the eye follows). */
.faq-item[open] .faq-a { animation: faq-unfold var(--dur-slow) var(--ease-out) both; }
@keyframes faq-unfold {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (prefers-reduced-motion: reduce) {
  .faq-item[open] .faq-a { animation: none; }
  /* The glyph still flips to mark the open state; it just gets there instantly. */
  .faq-ico { transition: background var(--dur) var(--ease), color var(--dur) var(--ease); }
}
</style>
