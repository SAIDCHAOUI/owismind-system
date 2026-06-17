<script setup>
// Sources section — WHERE the data comes from, in business terms: the matched
// dataset name plus an honest "+ n other queries" mention when the answer ran
// more than one. Gated on the NEW meta.source field: a v1 meta (no source
// block) renders nothing, keeping the panel pixel-identical to today.
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { useEvidenceStore } from '../../stores/evidence.js'
import { Icon } from '../ui'

const { t } = useI18n()
const evidence = useEvidenceStore()

const source = computed(() => (evidence.meta && evidence.meta.source) || null)
// Contract: meta.source.dataset, falling back to the v1 top-level dataset.
const datasetName = computed(() => {
  if (!source.value) return ''
  return source.value.dataset || (evidence.meta && evidence.meta.dataset) || ''
})
// Other queries the answer executed beyond the one this panel proves.
const extraQueries = computed(() => {
  const q = evidence.meta && evidence.meta.queries
  return Array.isArray(q) && q.length > 1 ? q.length - 1 : 0
})
// Optional link to the source dataset in Dataiku (configured on the agent). When
// present, the dataset name opens the dataset in a new tab.
const sourceUrl = computed(() => (source.value && source.value.url) || '')
</script>

<template>
  <section v-if="source && datasetName" class="ev-sources">
    <span class="ev-sec-title">{{ t('ev.proof.sources') }}</span>
    <div class="ev-source-line">
      <Icon name="database" />
      <a
        v-if="sourceUrl"
        class="ev-source-name ev-source-link"
        :href="sourceUrl"
        target="_blank"
        rel="noopener noreferrer"
        :title="t('ev.proof.sources.open')"
      >{{ datasetName }}</a>
      <span v-else class="ev-source-name">{{ datasetName }}</span>
      <span v-if="extraQueries > 0" class="ev-source-more">
        {{ t('ev.proof.sources.more', [extraQueries]) }}
      </span>
    </div>
  </section>
</template>

<style scoped>
/* No z-index: the chips popover (z-index 5, L043) must stay above. */
.ev-sources { display: flex; flex-direction: column; gap: var(--s-2); }
/* Section label — same pattern as .ev-chips-title (EvidenceChips). */
.ev-sec-title {
  font-size: var(--fs-xs); color: var(--text-3);
  text-transform: uppercase; letter-spacing: 0.04em;
}
.ev-source-line { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
.ev-source-line :deep(.ui-icon) { flex: none; width: 14px; height: 14px; color: var(--text-3); }
.ev-source-name {
  font-size: var(--fs-sm); font-weight: 500; color: var(--text);
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
}
/* Clickable source: orange (AA token) + underline on hover. */
.ev-source-link { color: var(--orange-text); text-decoration: none; cursor: pointer; }
.ev-source-link:hover { text-decoration: underline; }
.ev-source-more { flex: none; font-size: var(--fs-xs); color: var(--text-3); }
</style>
